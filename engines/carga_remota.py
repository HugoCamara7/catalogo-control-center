"""Motor de carga remota: la sincronizacion con Shopify corre en GitHub Actions.

Sin dependencias de Streamlit ni de pandas.

Por que existe
--------------
La carga corria DENTRO del proceso de Streamlit. Cuando el navegador se
desconecta --la PC se apaga, se cae el wifi, se cierra la pestana-- Streamlit
corta la sesion y el script deja de avanzar a mitad del catalogo. No habia
nada del otro lado que siguiera.

El panel "Sincronizacion recuperable por bloques" de app_matrixify parecia
resolverlo y no lo hacia, por dos razones:

1. No avanza solo. Alguien tiene que pulsar "Continuar siguiente bloque".
   Era recuperable, no autonomo.
2. Guarda el avance en `outputs/sync_jobs/`, que es disco del contenedor de
   Streamlit Cloud y esta en .gitignore. Un reinicio del contenedor borra el
   avance, no solo la sesion.

Aqui la carga la ejecuta un runner de GitHub Actions: una maquina que no es la
del usuario. El avance vive en el repositorio PRIVADO de datos, al lado de las
solicitudes, asi que sobrevive al contenedor tambien.

El punto de enganche YA EXISTIA
-------------------------------
`TicketService` recibe el adaptador de jobs por inyeccion y `start_load()` ya
llama a `self.jobs.start(ticket)`, guardando lo que devuelve en
`ticket["job"]`. Como el ticket se persiste en GitHub, el identificador del
job sobrevive al cierre de sesion **sin tocar la maquina de estados**. Es la
misma historia que el motor de notificaciones: enchufando el adaptador aqui,
las tres superficies que ejecutan cargas lo heredan sin saber que existe.

Por eso este modulo NO tiene una segunda maquina de estados de solicitudes.
Solo sabe de jobs.

Los logs de Actions son PUBLICOS
--------------------------------
El workflow vive en `catalogo-control-center`, que es un repositorio publico:
sus minutos de Actions son gratis e ilimitados, pero **cualquiera puede leer
el log de una ejecucion**. GitHub enmascara los secretos declarados, y nada
mas que eso.

Por eso todo lo que el worker imprime pasa por `texto_publico()`, y el detalle
de cada error va al registro del job --repositorio privado-- y no al log. Si
alguien agrega un print, que sea por ahi.

Que devuelve
------------
Registros de job como diccionarios planos, serializables a JSON. Ninguna
funcion de este modulo dibuja nada.
"""

from __future__ import annotations

import base64
import json
import re
import uuid
from datetime import datetime, timezone
from urllib.error import HTTPError
from urllib.parse import quote
from urllib.request import Request, urlopen


# --- estados del job ------------------------------------------------------
# Deliberadamente pocos y distintos de los 23 estados de la solicitud. Un job
# es un intento de ejecucion; la solicitud es el tramite. Mezclarlos fue lo que
# hizo falta corregir en agosto de 2026.
JOB_ENCOLADO = "queued"
JOB_CORRIENDO = "running"
JOB_COMPLETADO = "completed"
JOB_COMPLETADO_CON_ERRORES = "completed_with_errors"
JOB_FALLIDO = "failed"
JOB_SIN_DISPARAR = "not_dispatched"

ESTADOS_JOB_VIVO = {JOB_ENCOLADO, JOB_CORRIENDO}
ESTADOS_JOB_TERMINADO = {JOB_COMPLETADO, JOB_COMPLETADO_CON_ERRORES, JOB_FALLIDO}

ETIQUETAS_JOB = {
    JOB_ENCOLADO: "En cola",
    JOB_CORRIENDO: "Cargando en Shopify",
    JOB_COMPLETADO: "Carga terminada",
    JOB_COMPLETADO_CON_ERRORES: "Carga terminada con errores",
    JOB_FALLIDO: "La carga fallo",
    JOB_SIN_DISPARAR: "No se pudo iniciar",
}

# Cuantos productos procesa el runner antes de publicar el avance. Cada
# publicacion es un commit al repositorio de datos, asi que no puede ser 1: con
# 400 productos serian 400 commits. Y no puede ser el catalogo entero, porque
# entonces un runner que muere no deja rastro de lo que alcanzo a cargar.
PRODUCTOS_POR_BLOQUE = 20

# Tope del runner de GitHub para un job (6 h). El worker corta antes y deja el
# job en "queued" con sus pendientes, para que el siguiente disparo lo retome
# desde donde iba en vez de recargar lo ya cargado.
MINUTOS_MAXIMOS_RUNNER = 330


def ahora_utc():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _texto(valor):
    if valor is None:
        return ""
    return str(valor).strip()


# --- saneado para logs publicos -------------------------------------------
# Cada patron es un secreto que, si se cuela en un print, queda publicado para
# siempre en el log de la ejecucion. `Bearer` va incluido porque un mensaje de
# error de urllib puede traer la cabecera entera.
_PATRONES_SECRETOS = (
    re.compile(r"shpat_[A-Za-z0-9_\-]+"),
    re.compile(r"shpss_[A-Za-z0-9_\-]+"),
    re.compile(r"github_pat_[A-Za-z0-9_]+"),
    re.compile(r"\bgh[pousr]_[A-Za-z0-9]{16,}"),
    re.compile(r"(?i)bearer\s+[A-Za-z0-9._\-]+"),
    re.compile(r"(?i)(authorization|token|access_token|password)[\"'\s:=]+[^\s,;\"']+"),
    re.compile(r"https://[^\s/]*:[^\s/@]+@[^\s]+"),
)

LARGO_MAXIMO_LOG = 300


def texto_publico(valor, largo=LARGO_MAXIMO_LOG):
    """Deja un texto en condiciones de aparecer en un log publico.

    Enmascara lo que parezca un secreto y recorta. NO es una garantia de que
    el texto sea inofensivo --un mensaje de Shopify puede traer datos de
    negocio-- sino la ultima red antes de publicar. La regla de verdad es que
    el worker imprima contadores y codigos Modelo-Color, y mande el detalle al
    registro del job, que vive en el repositorio privado.
    """
    texto = _texto(valor)
    if not texto:
        return ""
    for patron in _PATRONES_SECRETOS:
        texto = patron.sub("[oculto]", texto)
    texto = " ".join(texto.split())
    if len(texto) > largo:
        texto = texto[: largo - 1] + "…"
    return texto


# Prefijo del codigo de una carga que no sale de ninguna solicitud. Se ve
# como lo que es: inventar un CAT-#### haria creer que existe una solicitud.
CODIGO_CARGA_SUELTA = "CARGA"


def sello_de_tiempo(formato="%Y%m%d%H%M%S"):
    """La hora UTC formateada, para un id o un codigo legible.

    **No es `ahora_utc`**, que devuelve el ISO en TEXTO para guardarlo en el
    registro del job. Confundirlas costo un `AttributeError: 'str' object has
    no attribute 'strftime'` que tumbaba la pantalla entera en el primer clic
    de "Cargar a Shopify en el servidor" -- `start_suelto` le pedia `.strftime`
    al texto. Con las dos funciones separadas y con nombre, la pregunta "¿esto
    es un `datetime` o ya es texto?" tiene una respuesta a la vista.
    """
    return datetime.now(timezone.utc).strftime(formato)


def nuevo_id_job(codigo_solicitud=""):
    marca_tiempo = sello_de_tiempo()
    sufijo = uuid.uuid4().hex[:8]
    base = re.sub(r"[^A-Za-z0-9]+", "-", _texto(codigo_solicitud)).strip("-").lower()
    return f"{base}-{marca_tiempo}-{sufijo}" if base else f"job-{marca_tiempo}-{sufijo}"


def nuevo_registro_job(
    *,
    codigo_solicitud,
    site_key,
    matrixify_path,
    claves_producto=None,
    mode="complete",
    batch_size=PRODUCTOS_POR_BLOQUE,
    creado_por="",
    marca="",
):
    """Arma el registro que viaja al repositorio de datos.

    `claves_producto` son los Modelo-Color a cargar. Van completos en el
    registro a proposito: son la lista de pendientes, y sin ellos un runner que
    muere no puede reanudar sin volver a leer y re-analizar el Excel.
    """
    claves = [clave for clave in (list(claves_producto or [])) if _texto(clave)]
    claves = list(dict.fromkeys(claves))
    batch_size = max(1, int(batch_size or PRODUCTOS_POR_BLOQUE))
    ahora = ahora_utc()
    return {
        "id": nuevo_id_job(codigo_solicitud),
        "ticket": _texto(codigo_solicitud),
        "site_key": _texto(site_key),
        "marca": _texto(marca),
        "mode": _texto(mode) or "complete",
        "status": JOB_ENCOLADO,
        "matrixify_path": _texto(matrixify_path),
        "batch_size": batch_size,
        "total_products": len(claves),
        "processed_products": 0,
        "ok_products": 0,
        "partial_products": 0,
        "error_products": 0,
        "current_block": 0,
        "total_blocks": (len(claves) + batch_size - 1) // batch_size if claves else 0,
        "product_keys": list(claves),
        "pending_keys": list(claves),
        "completed_keys": [],
        "error_keys": [],
        "result_rows": [],
        "result_path": "",
        "run_id": "",
        "run_url": "",
        "attempts": 0,
        "message": "Job creado; esperando al runner de GitHub Actions.",
        "error": "",
        "events": [],
        "created_by": _texto(creado_por),
        "created_at": ahora,
        "updated_at": ahora,
        "started_at": "",
        "finished_at": "",
    }


def agregar_evento(job, etapa, detalle="", producto=""):
    """Deja rastro dentro del registro del job.

    Se recorta a 250 como en el panel por bloques: el registro se serializa
    entero en cada publicacion, y un job de 800 productos con un evento por
    producto convierte cada commit en un archivo de megabytes.
    """
    eventos = job.setdefault("events", [])
    eventos.append({
        "created_at": ahora_utc(),
        "Etapa": _texto(etapa),
        "Producto": _texto(producto),
        "Detalle": _texto(detalle)[:1000],
    })
    if len(eventos) > 250:
        job["events"] = eventos[-250:]
    return job


# Tope de filas de resultado que caben en el registro del job.
#
# El registro se reescribe ENTERO en cada bloque, asi que lo que crece sin
# techo se paga en cada commit. Con 8.112 productos y sus tallas, `result_rows`
# llevaba el archivo por encima del megabyte -- y ahi la Contents API deja de
# devolver el contenido, o sea que el job se vuelve imposible de reanudar
# (septiembre de 2026, la carga de Supermall se quedo clavada en 1.280).
#
# `leer` ya sabe leer archivos grandes, pero eso arregla la lectura, no el
# peso: un registro de 8 MB reescrito 400 veces son gigabytes de subida y
# minutos de runner tirados.
FILAS_RESULTADO_MAXIMAS = 5000


def acotar_filas_de_resultado(job, maximo=FILAS_RESULTADO_MAXIMAS):
    """Deja el registro por debajo del tope SIN perder lo que se va a mirar.

    No se recorta por antiguedad a secas: de una carga de 8.000 productos, lo
    que alguien abre el Excel a buscar son los que **fallaron**, no los 7.900
    que salieron bien. Asi que las filas que no son OK se conservan TODAS y el
    tope se gasta en las OK mas recientes.

    Lo descartado se **cuenta** en el propio registro (`result_rows_omitidas`).
    Un informe al que le faltan filas y no lo dice es peor que uno incompleto.
    """
    filas = list(job.get("result_rows") or [])
    maximo = max(1, int(maximo or FILAS_RESULTADO_MAXIMAS))
    if len(filas) <= maximo:
        return job

    def es_ok(fila):
        if not isinstance(fila, dict):
            return False
        return _texto(fila.get("Resultado")).upper() == "OK"

    problemas = [fila for fila in filas if not es_ok(fila)]
    correctas = [fila for fila in filas if es_ok(fila)]
    # Si los problemas por si solos pasan del tope, se conservan los ultimos:
    # son los del bloque en curso, que es por donde se sigue mirando.
    conservadas = problemas[-maximo:] if len(problemas) >= maximo else (
        problemas + correctas[-(maximo - len(problemas)):]
    )
    job["result_rows"] = conservadas
    job["result_rows_omitidas"] = int(job.get("result_rows_omitidas") or 0) + (
        len(filas) - len(conservadas)
    )
    return job


def registrar_avance_bloque(job, *, ok=0, parciales=0, errores=0,
                            completados=None, con_error=None, filas=None):
    """Aplica al registro lo que salio de un bloque y recalcula los contadores.

    `pending_keys` se recalcula por diferencia contra los completados, no
    restando cantidades: si el runner muere y el bloque se repite, un producto
    ya cargado no puede volver a la cola ni contarse dos veces.
    """
    completados = [clave for clave in (completados or []) if _texto(clave)]
    con_error = [clave for clave in (con_error or []) if _texto(clave)]

    ya_completados = list(dict.fromkeys(list(job.get("completed_keys") or []) + completados))
    job["completed_keys"] = ya_completados
    job["error_keys"] = list(dict.fromkeys(list(job.get("error_keys") or []) + con_error))

    hechos = set(ya_completados)
    job["pending_keys"] = [
        clave for clave in (job.get("product_keys") or job.get("pending_keys") or [])
        if clave not in hechos
    ]

    job["ok_products"] = int(job.get("ok_products") or 0) + int(ok or 0)
    job["partial_products"] = int(job.get("partial_products") or 0) + int(parciales or 0)
    job["error_products"] = int(job.get("error_products") or 0) + int(errores or 0)
    job["processed_products"] = len(ya_completados)
    job["current_block"] = int(job.get("current_block") or 0) + 1
    if filas:
        job.setdefault("result_rows", []).extend(list(filas))
        acotar_filas_de_resultado(job)
    job["updated_at"] = ahora_utc()
    return job


def cerrar_job(job, *, error=""):
    """Fija el estado final segun lo que quedo pendiente y lo que fallo."""
    pendientes = [clave for clave in (job.get("pending_keys") or []) if _texto(clave)]
    if error:
        job["status"] = JOB_FALLIDO
        job["error"] = _texto(error)
        job["message"] = f"La carga se detuvo: {_texto(error)[:200]}"
    elif pendientes:
        # No es un cierre: el runner se quedo sin tiempo. Vuelve a la cola para
        # que el siguiente disparo retome los pendientes.
        job["status"] = JOB_ENCOLADO
        job["message"] = f"Quedan {len(pendientes):,} productos pendientes; vuelve a lanzar para continuar."
    elif int(job.get("error_products") or 0):
        job["status"] = JOB_COMPLETADO_CON_ERRORES
        job["message"] = f"Carga terminada con {int(job['error_products']):,} productos en error."
    else:
        job["status"] = JOB_COMPLETADO
        job["message"] = f"Carga terminada: {int(job.get('ok_products') or 0):,} productos."
    if job["status"] in ESTADOS_JOB_TERMINADO:
        job["finished_at"] = ahora_utc()
    job["updated_at"] = ahora_utc()
    return job


def resumen_job(job):
    """Los datos que necesita una pantalla para dibujar el avance.

    Devuelve DATOS, no widgets: quien dibuja es app_matrixify. Misma regla que
    `flujo.seguimiento_carga`.
    """
    if not isinstance(job, dict):
        return {}
    total = int(job.get("total_products") or 0)
    procesados = int(job.get("processed_products") or 0)
    estado = _texto(job.get("status")) or JOB_ENCOLADO
    return {
        "id": _texto(job.get("id")),
        "ticket": _texto(job.get("ticket")),
        "estado": estado,
        "etiqueta": ETIQUETAS_JOB.get(estado, estado),
        "vivo": estado in ESTADOS_JOB_VIVO,
        "terminado": estado in ESTADOS_JOB_TERMINADO,
        "total": total,
        "procesados": procesados,
        "pendientes": max(total - procesados, 0),
        "ok": int(job.get("ok_products") or 0),
        "parciales": int(job.get("partial_products") or 0),
        "errores": int(job.get("error_products") or 0),
        "porcentaje": (procesados / total) if total else 0.0,
        "bloque": int(job.get("current_block") or 0),
        "bloques": int(job.get("total_blocks") or 0),
        "mensaje": _texto(job.get("message")),
        "error": _texto(job.get("error")),
        "run_url": _texto(job.get("run_url")),
        "result_path": _texto(job.get("result_path")),
        "actualizado": _texto(job.get("updated_at")),
        "iniciado": _texto(job.get("started_at")),
        "terminado_en": _texto(job.get("finished_at")),
    }


# --- almacen del avance ---------------------------------------------------

# --- Diagnostico: esta carga, sobrevive al cierre de sesion? -------------
#
# La app cae al adaptador local EN SILENCIO cuando falta configuracion. Eso es
# correcto -- sin `[carga_remota]` todo sigue funcionando como antes -- pero deja
# a quien carga sin forma de saber si puede cerrar la pestana. Y esa es
# justamente la pregunta que importa cuando una carga dura horas.
#
# Aqui se responde con DATOS, no con widgets: quien dibuja es app_matrixify.
REQUISITOS_CARGA_REMOTA = (
    ("token", "Token con permiso Actions: write",
     "Agrega `token` a la sección [carga_remota] de Secrets. NO es el de [ticketing]: "
     "aquel escribe contenidos en el repositorio de datos, este dispara un workflow "
     "en el repositorio del código, que es otro permiso."),
    ("almacen", "Repositorio de datos para guardar el avance",
     "El avance vive en el repositorio privado, junto a las solicitudes. Con el backend "
     "de solicitudes en modo local no hay dónde publicarlo: configura [ticketing]."),
    ("habilitado", "Carga remota habilitada",
     "La sección [carga_remota] tiene `enabled = false`. Quítalo o ponlo en true."),
    ("repositorio", "Repositorio y workflow indicados",
     "Revisa `repository` y `workflow` en [carga_remota]. Por defecto son "
     "`HugoCamara7/catalogo-control-center` y `carga-shopify.yml`."),
)


def diagnostico_carga_remota(config, *, almacen_disponible=False):
    """Si la carga sobrevive al cierre de sesion, y que falta si no.

    Devuelve {"sobrevive": bool, "pasos": [{clave, titulo, estado, arreglo}]}.
    `estado` es "ok" o "error". No consulta la red: mira la configuracion, que
    es lo que decide si `get_job_adapter` devuelve el adaptador real o el local.
    """
    config = dict(config or {})
    habilitado = _texto(config.get("enabled", "true")).casefold() not in {"false", "0", "no"}
    token = bool(_texto(config.get("token")))
    repositorio = _texto(config.get("repository")) or "HugoCamara7/catalogo-control-center"
    workflow = _texto(config.get("workflow")) or "carga-shopify.yml"
    cumplido = {
        "token": token,
        "almacen": bool(almacen_disponible),
        "habilitado": habilitado,
        "repositorio": bool(repositorio and "/" in repositorio and workflow),
    }
    pasos = []
    for clave, titulo, arreglo in REQUISITOS_CARGA_REMOTA:
        ok = cumplido.get(clave, False)
        detalle = ""
        if clave == "repositorio" and ok:
            detalle = f"{repositorio} · {workflow}"
        pasos.append({
            "clave": clave,
            "titulo": titulo,
            "estado": "ok" if ok else "error",
            "arreglo": "" if ok else arreglo,
            "detalle": detalle,
        })
    return {"sobrevive": all(cumplido.values()), "pasos": pasos}


class ErrorCargaRemota(RuntimeError):
    """Algo impidio crear, disparar o leer un job."""


class AlmacenJobsGitHub:
    """Los registros de job, en el repositorio PRIVADO de datos.

    Al lado de las solicitudes y con el mismo mecanismo (GitHub Contents con
    sha), porque el avance tiene que sobrevivir a lo mismo que ellas: el
    contenedor de Streamlit, el runner de Actions y la PC del usuario.

    No hereda de GitHubTicketStore a proposito. Ese almacen tiene una cache de
    modulo pensada para la bandeja, con la que un job en curso devolveria
    avance viejo; y el worker corre sin Streamlit y no deberia arrastrar la
    maquina de solicitudes entera para escribir un JSON.
    """

    def __init__(self, owner, repo, token, branch="catalog-tickets",
                 prefix="catalog_tickets", timeout=30):
        if not all([_texto(owner), _texto(repo), _texto(token), _texto(branch)]):
            raise ErrorCargaRemota("Configuracion de GitHub incompleta para las cargas remotas.")
        self.owner = _texto(owner)
        self.repo = _texto(repo)
        self.token = _texto(token)
        self.branch = _texto(branch)
        self.prefix = _texto(prefix).strip("/") or "catalog_tickets"
        self.timeout = int(timeout)
        self.base = f"https://api.github.com/repos/{quote(self.owner)}/{quote(self.repo)}/contents"

    def ruta_de_matrixify(self, job_id, filename=""):
        """Donde vive el Matrixify de una carga que NO sale de una solicitud.

        Cuando la carga viene de una solicitud, el Matrixify es un adjunto de
        esa solicitud y la ruta la da `attach_matrixify`. Una carga suelta no
        tiene solicitud de la que colgarse, asi que el archivo va al lado del
        registro del job, con su mismo identificador: si algun dia hay que
        mirar que se cargo, el job y su archivo estan juntos.
        """
        seguro = re.sub(r"[^A-Za-z0-9_\-.]+", "-", _texto(job_id)).strip("-") or "job"
        nombre = re.sub(r"[^A-Za-z0-9_\-.]+", "-", _texto(filename)).strip("-") or "matrixify.xlsx"
        if not nombre.lower().endswith((".xlsx", ".xls")):
            nombre = f"{nombre}.xlsx"
        return f"{self.prefix}/catalog_jobs/{seguro}/{nombre}"

    def _ruta(self, job_id):
        seguro = re.sub(r"[^A-Za-z0-9_\-.]+", "-", _texto(job_id)).strip("-") or "job"
        return f"{self.prefix}/catalog_jobs/{seguro}.json"

    def _pedir(self, metodo, ruta, payload=None, con_ref=True):
        url = f"{self.base}/{quote(ruta, safe='/')}"
        if metodo == "GET" and con_ref:
            url += f"?ref={quote(self.branch)}"
        cuerpo = json.dumps(payload).encode("utf-8") if payload is not None else None
        peticion = Request(
            url,
            data=cuerpo,
            method=metodo,
            headers={
                "Accept": "application/vnd.github+json",
                "Authorization": f"Bearer {self.token}",
                "X-GitHub-Api-Version": "2022-11-28",
                "User-Agent": "catalog-control-center",
                "Content-Type": "application/json",
            },
        )
        try:
            with urlopen(peticion, timeout=self.timeout) as respuesta:
                crudo = respuesta.read().decode("utf-8")
                return json.loads(crudo) if crudo else {}
        except HTTPError as exc:
            if exc.code == 404:
                return None
            detalle = exc.read().decode("utf-8", errors="replace")
            # El detalle puede traer la URL con el token. Se sanea SIEMPRE, no
            # solo cuando el que mira es el log del runner: esta excepcion
            # tambien termina en pantalla y en la auditoria.
            raise ErrorCargaRemota(
                f"GitHub respondio {exc.code}: {texto_publico(detalle, 300)}"
            ) from exc

    def _pedir_crudo(self, ruta):
        """El contenido del archivo, en bytes, sin pasar por base64.

        Existe porque la Contents API **deja de mandar `content` en los
        archivos de mas de 1 MB**: responde con la cadena vacia y el campo
        `encoding` en "none". Con `Accept: application/vnd.github.raw` el mismo
        endpoint devuelve el archivo entero hasta 100 MB.
        """
        url = f"{self.base}/{quote(ruta, safe='/')}?ref={quote(self.branch)}"
        peticion = Request(
            url,
            method="GET",
            headers={
                "Accept": "application/vnd.github.raw",
                "Authorization": f"Bearer {self.token}",
                "X-GitHub-Api-Version": "2022-11-28",
                "User-Agent": "catalog-control-center",
            },
        )
        try:
            with urlopen(peticion, timeout=self.timeout) as respuesta:
                return respuesta.read()
        except HTTPError as exc:
            if exc.code == 404:
                return b""
            detalle = exc.read().decode("utf-8", errors="replace")
            raise ErrorCargaRemota(
                f"GitHub respondio {exc.code} al leer el registro: {texto_publico(detalle, 300)}"
            ) from exc

    def leer(self, job_id):
        """Devuelve (job, sha). (None, None) si no existe.

        El sha sale de los METADATOS y el contenido puede venir por dos vias:
        el `content` en base64, o crudo cuando ese campo llega vacio. Es lo que
        pasa a partir de 1 MB, y un registro de una carga larga los pasa: en
        septiembre de 2026 una carga de 8.112 productos quedo **imposible de
        reanudar** al llegar a los 1.280 --el `json.loads` de una cadena vacia
        levantaba "Expecting value: line 1 column 1 (char 0)"-- justo cuando la
        reanudacion es lo unico que importa. Los datos estaban intactos; lo que
        no servia era la puerta por la que se pedian.
        """
        datos = self._pedir("GET", self._ruta(job_id))
        if not isinstance(datos, dict) or "content" not in datos:
            return None, None
        crudo = base64.b64decode(datos.get("content", "") or "")
        if not crudo:
            crudo = self._pedir_crudo(self._ruta(job_id))
        if not crudo:
            return None, None
        try:
            return json.loads(crudo.decode("utf-8")), datos.get("sha")
        except (ValueError, UnicodeDecodeError) as exc:
            raise ErrorCargaRemota(f"El registro del job {job_id} no es JSON valido.") from exc

    def guardar(self, job, sha=None, mensaje=""):
        """Escribe el registro. Sin sha lo busca; si existe, lo pisa.

        Devuelve el sha nuevo, para encadenar publicaciones de bloque sin un
        GET de por medio en cada una.
        """
        ruta = self._ruta(job.get("id"))
        if sha is None:
            _, sha = self.leer(job.get("id"))
        cuerpo = {
            "message": mensaje or f"catalog: job {job.get('id')} {job.get('status')}",
            "content": base64.b64encode(
                json.dumps(job, ensure_ascii=False, indent=2).encode("utf-8")
            ).decode("ascii"),
            "branch": self.branch,
        }
        if sha:
            cuerpo["sha"] = sha
        datos = self._pedir("PUT", ruta, cuerpo, con_ref=False)
        return ((datos or {}).get("content") or {}).get("sha")

    def leer_archivo(self, ruta):
        """Baja un adjunto del repositorio de datos (el Matrixify, por ejemplo).

        La API de Contents devuelve el contenido embutido solo hasta 1 MB. Un
        Matrixify de catalogo completo pasa ese tope de sobra, y en ese caso
        GitHub manda `content` vacio con `download_url`: hay que ir por ahi o
        el worker se queda con cero bytes y reporta "Excel vacio".
        """
        datos = self._pedir("GET", _texto(ruta))
        if not isinstance(datos, dict):
            raise ErrorCargaRemota(f"No encontre el archivo {ruta} en el repositorio de datos.")
        contenido = datos.get("content") or ""
        if contenido:
            return base64.b64decode(contenido)
        url_descarga = _texto(datos.get("download_url"))
        if not url_descarga:
            raise ErrorCargaRemota(f"El archivo {ruta} llego sin contenido ni enlace de descarga.")
        peticion = Request(
            url_descarga,
            headers={
                "Authorization": f"Bearer {self.token}",
                "User-Agent": "catalog-control-center",
            },
        )
        with urlopen(peticion, timeout=max(self.timeout, 120)) as respuesta:
            return respuesta.read()

    def guardar_archivo(self, ruta, contenido, mensaje=""):
        _, sha = (None, None)
        existente = self._pedir("GET", _texto(ruta))
        if isinstance(existente, dict):
            sha = existente.get("sha")
        cuerpo = {
            "message": mensaje or f"catalog: resultado {ruta}",
            "content": base64.b64encode(contenido or b"").decode("ascii"),
            "branch": self.branch,
        }
        if sha:
            cuerpo["sha"] = sha
        self._pedir("PUT", _texto(ruta), cuerpo, con_ref=False)
        return _texto(ruta)


# --- disparo del workflow -------------------------------------------------

def disparar_workflow(*, owner, repo, workflow, ref, token, inputs=None, timeout=30):
    """Lanza un workflow_dispatch.

    Necesita un token con permiso **Actions: write**. El de `[ticketing]` es de
    contenidos y NO sirve: por eso la configuracion pide uno propio y el
    adaptador avisa en vez de fallar en silencio.

    GitHub responde 204 sin cuerpo: la respuesta no trae el id de la ejecucion.
    No se sale a buscarlo con un sondeo --serian varias llamadas mas por clic,
    y con suerte la ejecucion aun no existe--; es el propio worker el que
    escribe su `run_url` en el registro del job al arrancar, que ademas es el
    unico que la sabe con certeza.
    """
    faltantes = [nombre for nombre, valor in
                 (("owner", owner), ("repo", repo), ("workflow", workflow),
                  ("ref", ref), ("token", token)) if not _texto(valor)]
    if faltantes:
        raise ErrorCargaRemota(
            "Falta configuracion para disparar la carga en Actions: " + ", ".join(faltantes)
        )
    url = (
        f"https://api.github.com/repos/{quote(_texto(owner))}/{quote(_texto(repo))}"
        f"/actions/workflows/{quote(_texto(workflow))}/dispatches"
    )
    payload = {
        "ref": _texto(ref),
        # Los inputs de workflow_dispatch viajan como texto. Un entero aqui lo
        # rechaza la API con 422.
        "inputs": {clave: _texto(valor) for clave, valor in (inputs or {}).items()},
    }
    peticion = Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        method="POST",
        headers={
            "Accept": "application/vnd.github+json",
            "Authorization": f"Bearer {_texto(token)}",
            "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": "catalog-control-center",
            "Content-Type": "application/json",
        },
    )
    try:
        with urlopen(peticion, timeout=int(timeout)) as respuesta:
            return 200 <= int(respuesta.status) < 300
    except HTTPError as exc:
        detalle = exc.read().decode("utf-8", errors="replace")
        if exc.code in {401, 403}:
            raise ErrorCargaRemota(
                "GitHub rechazo el disparo por permisos. El token de cargas necesita "
                "«Actions: write» sobre el repositorio del workflow; el token de "
                "solicitudes solo tiene contenidos."
            ) from exc
        if exc.code == 404:
            raise ErrorCargaRemota(
                f"No encontre el workflow «{_texto(workflow)}» en {_texto(owner)}/{_texto(repo)} "
                f"(rama {_texto(ref)}). Tiene que estar mergeado en esa rama para poder dispararse."
            ) from exc
        raise ErrorCargaRemota(
            f"GitHub respondio {exc.code} al disparar la carga: {texto_publico(detalle, 300)}"
        ) from exc


# --- adaptador que se enchufa en TicketService ----------------------------

class AdaptadorCargaActions:
    """El `jobs=` de TicketService, ejecutando de verdad.

    `start(ticket)` crea el registro del job en el repositorio de datos,
    dispara el workflow y devuelve el diccionario que `start_load` guarda en
    `ticket["job"]`. Como el ticket se persiste, al reabrir la app la solicitud
    sabe sola que job mirar: no hace falta guardar nada en `st.session_state`,
    que es justo lo que no sobrevivia al cierre de sesion.

    **Nunca levanta una excepcion desde `start`.** Un fallo al disparar no
    puede tumbar ni deshacer la transicion de la solicitud --misma regla que
    los correos--: devuelve un job en estado `not_dispatched` con el motivo, y
    la pantalla ofrece reintentar.
    """

    def __init__(self, almacen, *, owner, repo, workflow, ref="main", token="",
                 batch_size=PRODUCTOS_POR_BLOQUE, disparador=None):
        self.almacen = almacen
        self.owner = _texto(owner)
        self.repo = _texto(repo)
        self.workflow = _texto(workflow)
        self.ref = _texto(ref) or "main"
        self.token = _texto(token)
        self.batch_size = max(1, int(batch_size or PRODUCTOS_POR_BLOQUE))
        # Inyectable para poder probar el adaptador sin salir a la red.
        self._disparar = disparador or disparar_workflow

    def dry_run(self, ticket):
        """La simulacion sigue siendo local: no llama a Shopify ni a Actions.

        Es exactamente lo que tiene que hacer un dry run, y mandarlo a un
        runner solo agregaria minutos de cola a un paso que hoy es inmediato.
        """
        resumen = ticket.get("summary") if isinstance(ticket.get("summary"), dict) else {}
        return {
            "id": f"DRY-{uuid.uuid4().hex[:12].upper()}",
            "status": "completed",
            "created_at": ahora_utc(),
            "mode": "local",
            "new_products": int(resumen.get("new_products", 0) or 0),
            "updated_products": int(resumen.get("updated_products", 0) or 0),
            "blocked": 0,
            "message": "Simulación local completada. No se llamó a Shopify.",
        }

    def start(self, ticket):
        codigo = _texto(ticket.get("code"))
        matrixify = ticket.get("matrixify") if isinstance(ticket.get("matrixify"), dict) else {}
        ruta = _texto(matrixify.get("path"))
        if not ruta:
            # Sin Matrixify adjunto no hay nada que cargar. Se avisa aqui en vez
            # de disparar un runner que arrancaria solo para morir leyendo un
            # archivo que no existe, gastando minutos y ensuciando el historial.
            return self._job_sin_disparar(
                codigo,
                "La solicitud no tiene un Matrixify adjunto. Genéralo en Carga completa "
                "(Analizar input) y vuelve a ejecutar la carga.",
            )

        claves = [clave for clave in (matrixify.get("product_keys") or []) if _texto(clave)]
        job = nuevo_registro_job(
            codigo_solicitud=codigo,
            site_key=_texto(ticket.get("site_key")) or _texto(matrixify.get("site_key")),
            matrixify_path=ruta,
            claves_producto=claves,
            batch_size=self.batch_size,
            creado_por=_texto(ticket.get("assigned_to")) or _texto(ticket.get("requested_by")),
            marca=_texto(ticket.get("brand")),
        )
        agregar_evento(job, "Creado", f"{len(claves):,} productos por cargar")

        try:
            self.almacen.guardar(job, mensaje=f"catalog: job {job['id']} creado")
        except Exception as exc:
            return self._job_sin_disparar(
                codigo, f"No pude guardar el registro de la carga: {texto_publico(exc)}"
            )

        try:
            self._disparar(
                owner=self.owner,
                repo=self.repo,
                workflow=self.workflow,
                ref=self.ref,
                token=self.token,
                inputs={"job_id": job["id"], "site_key": job["site_key"], "ticket": codigo},
            )
        except Exception as exc:
            job["status"] = JOB_SIN_DISPARAR
            job["error"] = texto_publico(exc, 500)
            job["message"] = f"No se pudo iniciar la carga en GitHub Actions: {job['error']}"
            agregar_evento(job, "Sin disparar", job["error"])
            try:
                self.almacen.guardar(job, mensaje=f"catalog: job {job['id']} sin disparar")
            except Exception:
                pass
            return self._resumen_para_ticket(job)

        return self._resumen_para_ticket(job)

    def start_suelto(self, *, site_key, matrixify_bytes, filename="",
                     claves_producto=(), creado_por="", marca="", modo="complete"):
        """Lanza una carga remota que NO sale de una solicitud.

        Por que existe
        --------------
        `start(ticket)` necesita una solicitud porque el job cuelga de ella: el
        Matrixify es un adjunto del ticket y de ahi lo lee el runner. Eso
        dejaba fuera el caso mas comun de todos: **subir un Excel a mano y
        cargarlo**. En ese camino la carga se hacia dentro de la sesion de
        Streamlit, asi que cerrar la pestana la detenia -- justo lo que la
        carga remota existe para evitar.

        Aqui el Matrixify se sube al repositorio de datos por su cuenta, al
        lado del registro del job, y el resto del recorrido es EL MISMO: mismo
        registro, mismo workflow, mismo worker, mismo avance por bloques y
        misma reanudacion. No hay un segundo motor de carga.

        Nunca levanta: devuelve el job en `not_dispatched` con el motivo, igual
        que `start`. Un fallo al disparar no puede tumbar la pantalla.
        """
        site_key = _texto(site_key)
        claves = [clave for clave in (claves_producto or []) if _texto(clave)]
        if not matrixify_bytes:
            return self._job_sin_disparar(
                "", "No hay un Matrixify que cargar. Pulsa «Analizar input» primero.")
        if not site_key:
            return self._job_sin_disparar("", "La carga no dice a que sitio va.")

        # El codigo es sintetico y se ve como lo que es: no hay solicitud, y
        # inventar un CAT-#### haria creer que existe una.
        codigo = f"{CODIGO_CARGA_SUELTA}-{site_key.upper()}-{sello_de_tiempo('%Y%m%d-%H%M%S')}"
        job = nuevo_registro_job(
            codigo_solicitud=codigo,
            site_key=site_key,
            matrixify_path="",
            claves_producto=claves,
            batch_size=self.batch_size,
            creado_por=_texto(creado_por),
            marca=_texto(marca),
        )
        job["mode"] = _texto(modo) or "complete"
        job["sin_solicitud"] = True

        # El archivo va PRIMERO. Con el registro guardado y el archivo no, el
        # runner arrancaria para morir leyendo una ruta que no existe.
        try:
            ruta = self.almacen.ruta_de_matrixify(job["id"], filename)
            self.almacen.guardar_archivo(
                ruta, matrixify_bytes, mensaje=f"catalog: matrixify de {job['id']}")
            job["matrixify_path"] = ruta
        except Exception as exc:
            return self._job_sin_disparar(
                codigo, f"No pude subir el Matrixify al repositorio de datos: {texto_publico(exc)}")

        agregar_evento(job, "Creado", f"{len(claves):,} productos por cargar (carga suelta)")
        try:
            self.almacen.guardar(job, mensaje=f"catalog: job {job['id']} creado")
        except Exception as exc:
            return self._job_sin_disparar(
                codigo, f"No pude guardar el registro de la carga: {texto_publico(exc)}")

        try:
            self._disparar(
                owner=self.owner, repo=self.repo, workflow=self.workflow, ref=self.ref,
                token=self.token,
                inputs={"job_id": job["id"], "site_key": job["site_key"], "ticket": ""},
            )
        except Exception as exc:
            job["status"] = JOB_SIN_DISPARAR
            job["error"] = texto_publico(exc, 500)
            job["message"] = f"No se pudo iniciar la carga en GitHub Actions: {job['error']}"
            agregar_evento(job, "Sin disparar", job["error"])
            try:
                self.almacen.guardar(job, mensaje=f"catalog: job {job['id']} sin disparar")
            except Exception:
                pass
            return self._resumen_para_ticket(job)
        return self._resumen_para_ticket(job)

    def _job_sin_disparar(self, codigo, motivo):
        return {
            "id": "",
            "status": JOB_SIN_DISPARAR,
            "created_at": ahora_utc(),
            "mode": "github_actions",
            "progress": 0,
            "ticket": codigo,
            "message": motivo,
            "error": motivo,
        }

    def _resumen_para_ticket(self, job):
        """Lo que queda guardado DENTRO del ticket.

        Solo el puntero y un titular. El avance detallado --pendientes,
        resultados, eventos-- vive en el registro del job: meterlo en el ticket
        lo haria crecer sin techo y cada escritura de la solicitud arrastraria
        el catalogo entero.
        """
        return {
            "id": _texto(job.get("id")),
            "status": _texto(job.get("status")),
            "created_at": _texto(job.get("created_at")),
            "mode": "github_actions",
            "progress": 0,
            "total": int(job.get("total_products") or 0),
            "ticket": _texto(job.get("ticket")),
            "run_url": _texto(job.get("run_url")),
            "message": _texto(job.get("message")),
        }
