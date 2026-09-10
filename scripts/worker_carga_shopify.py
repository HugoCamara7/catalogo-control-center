#!/usr/bin/env python3
"""Ejecuta una carga a Shopify dentro de un runner de GitHub Actions.

Este es el proceso que sigue cargando cuando el usuario cierra la sesion o
apaga la PC. No depende de Streamlit para avanzar: lee el registro del job del
repositorio PRIVADO de datos, carga producto por producto y **publica el
avance despues de cada bloque**, en el mismo repositorio.

Por que reusa el motor de app_matrixify
---------------------------------------
`process_sync_job_next_block` ya resuelve lo dificil: partir en bloques,
reintentar los errores transitorios, y no repetir un producto ya cargado.
Tiene pruebas y esta en produccion. Escribir aqui una segunda implementacion
seria tener dos motores de carga que se separan sin que nadie lo note --el
mismo error que se evito con `normalize_size`--. Lo que este worker agrega es
de donde sale el estado y a donde va el avance.

Arrastra Streamlit como dependencia de importacion, igual que `catalog_engine`.
Es la deuda anotada en la seccion 2 del CLAUDE.md (extraer
`engines/shopify_sync.py`); no se paga aqui para no mezclar dos cambios.

Los logs de este proceso son PUBLICOS
-------------------------------------
El workflow vive en el repositorio publico. Todo lo que se imprima queda a la
vista de cualquiera, para siempre. Este worker imprime **solo** contadores,
numero de bloque y codigos Modelo-Color; el detalle de cada error va al
registro del job, en el repositorio privado. Cada print pasa por `_decir()`,
que sanea. No agregues un `print()` suelto.
"""

from __future__ import annotations

import argparse
import os
import sys
import time
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
if str(RAIZ) not in sys.path:
    sys.path.insert(0, str(RAIZ))

from engines.carga_remota import (  # noqa: E402
    JOB_CORRIENDO,
    MINUTOS_MAXIMOS_RUNNER,
    AlmacenJobsGitHub,
    ErrorCargaRemota,
    agregar_evento,
    ahora_utc,
    cerrar_job,
    disparar_workflow,
    registrar_avance_bloque,
    texto_publico,
)


def _decir(*partes):
    """Unica salida a consola. Sanea y vacia el buffer.

    El flush no es cosmetico: sin el, la salida se queda en el buffer de Python
    y un runner que muere por timeout no deja ni una linea de lo que alcanzo a
    hacer, que es justo cuando hace falta leerla.
    """
    print(texto_publico(" ".join(str(parte) for parte in partes), 300), flush=True)


def _entorno(*nombres, obligatorio=True):
    for nombre in nombres:
        valor = (os.getenv(nombre) or "").strip()
        if valor:
            return valor
    if obligatorio:
        raise SystemExit(
            f"Falta la variable de entorno {nombres[0]}. Revisa los secretos del workflow."
        )
    return ""


def _almacen_desde_entorno():
    repositorio = _entorno("CATALOG_TICKETS_REPOSITORY")
    if "/" not in repositorio:
        raise SystemExit("CATALOG_TICKETS_REPOSITORY debe tener la forma owner/repo.")
    owner, repo = repositorio.split("/", 1)
    return AlmacenJobsGitHub(
        owner=owner,
        repo=repo,
        token=_entorno("CATALOG_TICKETS_TOKEN"),
        branch=_entorno("CATALOG_TICKETS_BRANCH", obligatorio=False) or "catalog-tickets",
        prefix=_entorno("CATALOG_TICKETS_PREFIX", obligatorio=False) or "catalog_tickets",
    )


def _url_de_la_ejecucion():
    servidor = os.getenv("GITHUB_SERVER_URL") or "https://github.com"
    repositorio = os.getenv("GITHUB_REPOSITORY") or ""
    run_id = os.getenv("GITHUB_RUN_ID") or ""
    if not repositorio or not run_id:
        return ""
    return f"{servidor}/{repositorio}/actions/runs/{run_id}"


def _encadenar_siguiente_tanda(job):
    """Vuelve a disparar el workflow para seguir donde este runner lo dejo.

    El tope de GitHub son 6 h por job y el worker corta a los 330 min. Con
    8.000 productos eso son seis tandas, y hasta ahora cada una habia que
    pedirla a mano: la carga avanzaba solo mientras alguien estuviera pendiente
    de darle al boton, que es justo lo que este runner existe para evitar.

    Tres guardas, y ninguna es opcional:

    - **Solo si hubo avance.** Un job que no consigue cargar ni un producto se
      relanzaria para siempre, gastando runners y escribiendo en Shopify sin
      llegar a nada. Si esta tanda no movio el contador, se para y lo dice.
    - **Solo con token propio.** `GITHUB_TOKEN` NO sirve: GitHub ignora a
      proposito los workflow_dispatch hechos con el, para que un workflow no
      pueda relanzarse en bucle. Hace falta el token de cargas, con
      **Actions: write**.
    - **Nunca levanta.** El relanzado es un extra; que falle no puede convertir
      en fallida una tanda que si cargo sus productos. Se avisa y ya.

    Sin el token el comportamiento es exactamente el de antes: se deja el job
    en cola y el mensaje dice que hay que volver a lanzar.
    """
    token = (os.getenv("CARGA_REMOTA_TOKEN") or "").strip()
    if not token:
        # El punto detras del nombre NO es cosmetico: `texto_publico` enmascara
        # un "TOKEN" seguido de espacio o de dos puntos, asi que "CARGA_REMOTA_TOKEN:
        # la siguiente" saldria como "CARGA_REMOTA_[oculto] siguiente".
        _decir("Falta el secreto CARGA_REMOTA_TOKEN. La siguiente tanda hay que lanzarla a mano.")
        return False

    repositorio = (os.getenv("GITHUB_REPOSITORY") or "").strip()
    owner, _, repo = repositorio.partition("/")
    workflow = (os.getenv("CARGA_REMOTA_WORKFLOW") or "carga-shopify.yml").strip()
    ref = (os.getenv("CARGA_REMOTA_REF") or os.getenv("GITHUB_REF_NAME") or "main").strip()
    if not owner or not repo:
        _decir("No se de que repositorio soy; no encadeno la siguiente tanda.")
        return False

    try:
        disparar_workflow(
            owner=owner, repo=repo, workflow=workflow, ref=ref, token=token,
            inputs={
                "job_id": job.get("id"),
                "site_key": job.get("site_key"),
                "ticket": job.get("ticket") or "",
            },
        )
    except Exception as exc:  # noqa: BLE001 - un extra no puede tumbar la tanda
        _decir("No pude encadenar la siguiente tanda:", texto_publico(exc, 200))
        agregar_evento(job, "Aviso", f"No pude encadenar: {texto_publico(exc, 200)}")
        return False

    _decir("Siguiente tanda lanzada; la carga continua sola.")
    agregar_evento(job, "Encadenada", "Se disparo la siguiente tanda")
    return True


def _resultados_del_bloque(job_local, ya_vistas):
    """Filas de resultado que aparecieron en este bloque.

    El job local acumula TODAS las filas desde el principio. Publicar la lista
    entera en cada bloque haria que el ultimo commit repitiera el catalogo
    completo; se publica solo lo nuevo.
    """
    filas = list(job_local.get("result_rows") or [])
    return filas[ya_vistas:], len(filas)


def main():
    parser = argparse.ArgumentParser(description="Carga un catalogo a Shopify desde GitHub Actions.")
    parser.add_argument("--job-id", default=os.getenv("JOB_ID", ""), help="Identificador del job.")
    parser.add_argument(
        "--minutos-maximos",
        type=int,
        default=int(os.getenv("MINUTOS_MAXIMOS") or MINUTOS_MAXIMOS_RUNNER),
        help="Corta y deja pendientes antes de que el runner muera por timeout.",
    )
    args = parser.parse_args()

    job_id = (args.job_id or "").strip()
    if not job_id:
        raise SystemExit("Falta --job-id (o la variable JOB_ID).")

    almacen = _almacen_desde_entorno()
    job, sha = almacen.leer(job_id)
    if not job:
        raise SystemExit(f"No encontre el registro del job {job_id} en el repositorio de datos.")

    site_key = (job.get("site_key") or "").strip()
    _decir(f"Job {job_id} · sitio {site_key} · solicitud {job.get('ticket')}")

    # Marcar "corriendo" ANTES de nada pesado. Si el runner muere leyendo el
    # Excel, la pantalla tiene que poder decir que arranco y no quedarse en
    # "en cola" para siempre.
    job["status"] = JOB_CORRIENDO
    job["run_id"] = os.getenv("GITHUB_RUN_ID") or ""
    job["run_url"] = _url_de_la_ejecucion()
    job["attempts"] = int(job.get("attempts") or 0) + 1
    job["started_at"] = job.get("started_at") or ahora_utc()
    job["message"] = "Runner de GitHub Actions tomo la carga."
    agregar_evento(job, "Runner", f"intento {job['attempts']}")
    sha = almacen.guardar(job, sha, mensaje=f"catalog: job {job_id} corriendo")

    codigo_salida = 0
    try:
        codigo_salida = _ejecutar(job, sha, almacen, site_key, args.minutos_maximos)
    except Exception as exc:  # noqa: BLE001 - el fallo tiene que quedar registrado
        # Nada puede terminar sin dejar rastro en el registro: si el worker
        # revienta y solo lo cuenta el log, la pantalla se queda en "cargando"
        # para siempre y nadie sabe que paso.
        detalle = texto_publico(exc, 500)
        _decir("ERROR:", detalle)
        try:
            actual, sha_actual = almacen.leer(job_id)
            actual = actual or job
            agregar_evento(actual, "Error", detalle)
            cerrar_job(actual, error=detalle)
            almacen.guardar(actual, sha_actual, mensaje=f"catalog: job {job_id} fallido")
        except Exception as fallo_guardado:  # noqa: BLE001
            _decir("No pude registrar el fallo:", texto_publico(fallo_guardado))
        codigo_salida = 1
    return codigo_salida


# Las dos credenciales sin las que no hay carga, con el sufijo de la variable
# de entorno que las trae. `catalog_engine._env_name` le antepone el sitio:
# supermall -> SUPERMALL_SHOP_DOMAIN. El workflow mapea cada secreto del
# repositorio a esa variable, en su bloque `env:`.
CREDENCIALES_DE_SHOPIFY = (
    ("shop_domain", "SHOP_DOMAIN"),
    ("admin_access_token", "ADMIN_API_ACCESS_TOKEN"),
)


def _credenciales_que_faltan(site_key, configuracion):
    """Los NOMBRES de las variables que llegaron vacias al runner.

    Se derivan de `_env_name`, no de una lista escrita a mano: con la lista
    fija, un sitio nuevo nombraria las variables de otro. Y son nombres, nunca
    valores -- lo que se imprime va a un log publico.
    """
    from catalog_engine import _env_name

    return [
        _env_name(site_key, sufijo)
        for clave, sufijo in CREDENCIALES_DE_SHOPIFY
        if not str(configuracion.get(clave) or "").strip()
    ]


def _error_de_credenciales(site_key, faltantes):
    """El mensaje que se lee en el log, en el registro del job y en la pantalla.

    Nombra las variables. "Revisa los secretos del repositorio" a secas obliga
    a adivinar cual de los dos secretos de cual de los seis sitios es, y es
    justo el fallo que se ve al estrenar uno: Supermall.pe estaba dado de alta
    en SITE_CONFIGS, en Streamlit y en el bloque `env:` del workflow, pero sus
    secretos de Actions nunca se crearon.

    Ojo con el orden: la lista termina en un nombre acabado en TOKEN, y
    `texto_publico` enmascara un "TOKEN" seguido de un espacio. Por eso detras
    va un punto y no una palabra. Hay una prueba que lo fija.
    """
    return (
        f"Faltan credenciales de Shopify para el sitio «{site_key}». "
        f"Vacias en el runner: {', '.join(faltantes)}. "
        "Se cargan de los secretos de Actions del repositorio del codigo, "
        "que el workflow mapea en su bloque env."
    )


def _ejecutar(job, sha, almacen, site_key, minutos_maximos):
    # La importacion va aqui adentro, no arriba: importar app_matrixify tarda
    # unos segundos y arrastra Streamlit. Si el job no existe, es mejor fallar
    # rapido y sin pagar ese costo.
    #
    # Lo que NO se puede hacer hoy es comprobar las credenciales antes de ese
    # costo: `catalog_engine` importa `app_matrixify` en su linea 7, asi que
    # pedirle `shopify_config_from_env` ya arrastra Streamlit entero. Es la
    # deuda de la seccion 2 del CLAUDE.md (extraer `engines/shopify_sync.py`);
    # se anota aqui para que quede claro que el orden de estas lineas no ahorra
    # nada mientras esa inversion siga en pie.
    import pandas as pd

    from catalog_engine import read_matrixify_excel, shopify_config_from_env
    import app_matrixify as app

    configuracion = shopify_config_from_env(site_key)
    faltantes = _credenciales_que_faltan(site_key, configuracion)
    if faltantes:
        raise RuntimeError(_error_de_credenciales(site_key, faltantes))

    ruta_matrixify = (job.get("matrixify_path") or "").strip()
    if not ruta_matrixify:
        raise RuntimeError("El job no apunta a ningun Matrixify.")
    _decir("Bajando el Matrixify de la solicitud")
    contenido = almacen.leer_archivo(ruta_matrixify)
    destino = Path("job_inputs") / f"{job['id']}_matrixify.xlsx"
    destino.parent.mkdir(parents=True, exist_ok=True)
    destino.write_bytes(contenido)
    matrixify_df = read_matrixify_excel(destino)
    if matrixify_df is None or matrixify_df.empty:
        raise RuntimeError("El Matrixify de la solicitud no tiene filas para cargar.")

    modo = (job.get("mode") or "complete").strip() or "complete"

    # Las claves salen del Excel, que es la fuente de verdad, no de la lista
    # guardada: si el adjunto se reemplazo por una version corregida, la lista
    # vieja cargaria productos que ya no estan en el archivo.
    claves_archivo = app._sync_job_product_keys(matrixify_df, mode=modo)
    ya_cargados = {clave for clave in (job.get("completed_keys") or []) if str(clave).strip()}
    pendientes = [clave for clave in claves_archivo if clave not in ya_cargados]

    job["product_keys"] = list(claves_archivo)
    job["total_products"] = len(claves_archivo)
    job["pending_keys"] = list(pendientes)
    if not pendientes:
        _decir("No queda nada pendiente; el job ya estaba cargado.")
        cerrar_job(job)
        almacen.guardar(job, sha, mensaje=f"catalog: job {job['id']} sin pendientes")
        return 0

    _decir(f"{len(pendientes):,} productos pendientes de {len(claves_archivo):,}")

    tamano_bloque = max(1, int(job.get("batch_size") or 20))
    job_local = app._create_sync_job(
        site_key,
        modo,
        matrixify_df,
        batch_size=tamano_bloque,
        activate_inventory_locations=True,
    )
    # Se reanuda marcando como hechos los que ya se cargaron en intentos
    # anteriores. Sin esto, un runner que murio a la mitad volveria a escribir
    # en Shopify los productos que ya estaban bien.
    job_local["completed_keys"] = [clave for clave in claves_archivo if clave in ya_cargados]
    job_local["pending_keys"] = list(pendientes)
    job_local["processed_products"] = len(job_local["completed_keys"])
    app._save_sync_job(job_local)

    limite = time.monotonic() + max(1, int(minutos_maximos)) * 60
    filas_vistas = 0
    bloque = 0
    # Lo que ya estaba hecho ANTES de esta tanda. Es la referencia para saber
    # si este runner avanzo, que es lo que decide si se encadena el siguiente.
    hechos_al_arrancar = len(ya_cargados)

    while True:
        actual = app._load_sync_job(job_local["id"]) or {}
        if not [clave for clave in (actual.get("pending_keys") or []) if str(clave).strip()]:
            break
        if time.monotonic() >= limite:
            _decir("Se acabo el tiempo del runner; dejo el resto pendiente para el proximo disparo.")
            agregar_evento(job, "Tiempo agotado", "El runner corto antes del limite de GitHub")
            # Solo se encadena si ESTA tanda cargo algo. Sin avance, relanzar
            # seria un bucle infinito escribiendo en Shopify.
            if int(job.get("processed_products") or 0) > hechos_al_arrancar:
                _encadenar_siguiente_tanda(job)
            else:
                _decir("Esta tanda no cargo ningun producto; no encadeno para no entrar en bucle.")
                agregar_evento(job, "Sin avance", "No se encadena la siguiente tanda")
            break

        bloque += 1
        ok_antes = int(actual.get("ok_products") or 0)
        parciales_antes = int(actual.get("partial_products") or 0)
        errores_antes = int(actual.get("error_products") or 0)
        hechos_antes = set(actual.get("completed_keys") or [])
        con_error_antes = set(actual.get("error_keys") or [])

        despues = app.process_sync_job_next_block(job_local["id"], configuracion)

        nuevos_hechos = [clave for clave in (despues.get("completed_keys") or [])
                         if clave not in hechos_antes]
        nuevos_error = [clave for clave in (despues.get("error_keys") or [])
                        if clave not in con_error_antes]
        filas_nuevas, filas_vistas = _resultados_del_bloque(despues, filas_vistas)

        registrar_avance_bloque(
            job,
            ok=int(despues.get("ok_products") or 0) - ok_antes,
            parciales=int(despues.get("partial_products") or 0) - parciales_antes,
            errores=int(despues.get("error_products") or 0) - errores_antes,
            completados=nuevos_hechos,
            con_error=nuevos_error,
            filas=filas_nuevas,
        )
        job["status"] = JOB_CORRIENDO
        job["message"] = (
            f"Bloque {job.get('current_block')}: "
            f"{job.get('processed_products'):,} de {job.get('total_products'):,} productos."
        )
        agregar_evento(
            job, f"Bloque {job.get('current_block')}",
            f"{len(nuevos_hechos)} procesados, {len(nuevos_error)} con error",
        )
        # Publicar AQUI, dentro del bucle, es lo que hace que la carga sea
        # reanudable. Guardando solo al final, un runner que muere a los 40
        # minutos no deja constancia de nada y el proximo intento recarga todo.
        sha = almacen.guardar(
            job, sha, mensaje=f"catalog: job {job['id']} bloque {job.get('current_block')}"
        )
        _decir(
            f"Bloque {job.get('current_block')} · "
            f"{job.get('processed_products'):,}/{job.get('total_products'):,} · "
            f"ok {job.get('ok_products'):,} · parciales {job.get('partial_products'):,} · "
            f"errores {job.get('error_products'):,}"
        )

    # Resultado descargable, en el repositorio privado junto al resto de
    # adjuntos de la solicitud. No se sube como artifact de Actions: en un
    # repositorio publico eso seria publicar el detalle de la carga.
    filas = list(job.get("result_rows") or [])
    if filas:
        try:
            resultado_df = pd.DataFrame(filas)
            eventos_df = pd.DataFrame(job.get("events") or [])
            payload = app.dataframe_to_excel_bytes(
                {"Resultado": resultado_df, "Eventos": eventos_df}
            )
            if hasattr(payload, "getvalue"):
                payload = payload.getvalue()
            ruta_resultado = (
                f"{almacen.prefix}/artifacts/{job.get('ticket') or 'sin-solicitud'}"
                f"/job_{job['id']}_resultado.xlsx"
            )
            almacen.guardar_archivo(
                ruta_resultado, payload, mensaje=f"catalog: resultado job {job['id']}"
            )
            job["result_path"] = ruta_resultado
        except Exception as exc:  # noqa: BLE001
            # El resultado es un extra: que no se pueda escribir el Excel no
            # convierte en fallida una carga que si se ejecuto.
            agregar_evento(job, "Aviso", f"No pude guardar el Excel de resultado: {texto_publico(exc)}")
            _decir("Aviso: no pude guardar el Excel de resultado.")

    cerrar_job(job)
    almacen.guardar(job, sha, mensaje=f"catalog: job {job['id']} {job.get('status')}")
    _decir("Estado final:", job.get("status"), "·", job.get("message"))
    return 1 if job.get("status") == "failed" else 0


if __name__ == "__main__":
    raise SystemExit(main())
