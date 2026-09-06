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


def _ejecutar(job, sha, almacen, site_key, minutos_maximos):
    # La importacion va aqui adentro, no arriba: importar app_matrixify tarda
    # unos segundos y arrastra Streamlit. Si falta un secreto o el job no
    # existe, es mejor fallar rapido y sin pagar ese costo.
    import pandas as pd

    from catalog_engine import read_matrixify_excel, shopify_config_from_env
    import app_matrixify as app

    configuracion = shopify_config_from_env(site_key)
    if not configuracion.get("shop_domain") or not configuracion.get("admin_access_token"):
        raise RuntimeError(
            f"Faltan credenciales de Shopify para el sitio «{site_key}». "
            "Revisa los secretos del repositorio."
        )

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

    while True:
        actual = app._load_sync_job(job_local["id"]) or {}
        if not [clave for clave in (actual.get("pending_keys") or []) if str(clave).strip()]:
            break
        if time.monotonic() >= limite:
            _decir("Se acabo el tiempo del runner; dejo el resto pendiente para el proximo disparo.")
            agregar_evento(job, "Tiempo agotado", "El runner corto antes del limite de GitHub")
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
