"""Diagnostico del almacenamiento de solicitudes y auditoria.

Sin dependencias de Streamlit.

Motivo: get_ticket_service() devuelve backend="github" en cuanto la seccion
[ticketing] dice "github", aunque el token sea invalido, la rama no exista o
falte permiso de escritura. La app cree que persiste y en realidad no escribe
nada. Este modulo lo comprueba de verdad, paso a paso.

Nunca registra ni devuelve el token.
"""

import base64
import json
from urllib.error import HTTPError, URLError
from urllib.parse import quote
from urllib.request import Request, urlopen

OK = "ok"
FALLA = "error"
AVISO = "aviso"

API = "https://api.github.com"


def _peticion(metodo, url, token, payload=None, timeout=15):
    """Devuelve (codigo, datos). Nunca lanza por HTTP."""
    cuerpo = json.dumps(payload).encode("utf-8") if payload is not None else None
    peticion = Request(url, data=cuerpo, method=metodo, headers={
        "Accept": "application/vnd.github+json",
        "Authorization": f"Bearer {token}",
        "X-GitHub-Api-Version": "2022-11-28",
        "User-Agent": "catalog-control-center-check",
        "Content-Type": "application/json",
    })
    try:
        with urlopen(peticion, timeout=timeout) as respuesta:
            texto = respuesta.read().decode("utf-8", errors="replace")
            return respuesta.status, (json.loads(texto) if texto else {})
    except HTTPError as exc:
        texto = exc.read().decode("utf-8", errors="replace")
        try:
            return exc.code, json.loads(texto)
        except json.JSONDecodeError:
            return exc.code, {"message": texto[:200]}
    except (URLError, TimeoutError, OSError) as exc:
        return 0, {"message": f"sin conexion: {exc}"}


def _paso(nombre, estado, detalle, arreglo=""):
    return {"paso": nombre, "estado": estado, "detalle": detalle, "arreglo": arreglo}


def check_github_store(owner, repo, token, branch="catalog-tickets",
                       prefix="catalog_tickets", escribir_prueba=False, timeout=15):
    """Comprueba de punta a punta que se puede persistir en GitHub.

    escribir_prueba=True hace un PUT real de un archivo .keep. Es la unica
    forma de confirmar el permiso de escritura sin ambiguedad.
    """
    pasos = []

    faltantes = [n for n, v in [("owner", owner), ("repo", repo), ("token", token), ("branch", branch)] if not v]
    if faltantes:
        pasos.append(_paso(
            "Configuracion", FALLA,
            f"Faltan valores en [ticketing]: {', '.join(faltantes)}.",
            'Completa [ticketing] en Secrets: backend, repository = "owner/repo", token, branch.',
        ))
        return {"pasos": pasos, "persistente": False}
    pasos.append(_paso("Configuracion", OK, f"{owner}/{repo}, rama {branch}, carpeta {prefix}/"))

    codigo, datos = _peticion("GET", f"{API}/user", token, timeout=timeout)
    if codigo == 200:
        pasos.append(_paso("Token", OK, f"Valido. Cuenta: {datos.get('login', '?')}"))
    elif codigo == 401:
        pasos.append(_paso("Token", FALLA, "GitHub lo rechaza (401).",
                           "El token expiro o esta mal copiado. Genera uno nuevo y pegalo en Secrets."))
        return {"pasos": pasos, "persistente": False}
    else:
        pasos.append(_paso("Token", FALLA, f"Respuesta {codigo}: {datos.get('message', '')}",
                           "Revisa el token en Secrets."))
        return {"pasos": pasos, "persistente": False}

    codigo, datos = _peticion("GET", f"{API}/repos/{quote(owner)}/{quote(repo)}", token, timeout=timeout)
    if codigo != 200:
        pasos.append(_paso("Repositorio", FALLA, f"No accesible ({codigo}): {datos.get('message', '')}",
                           f'Revisa que repository sea exactamente "{owner}/{repo}" y que el token alcance ese repo.'))
        return {"pasos": pasos, "persistente": False}
    permisos = datos.get("permissions", {}) or {}
    pasos.append(_paso("Repositorio", OK, f"Accesible. Privado: {'si' if datos.get('private') else 'no'}"))

    if permisos.get("push"):
        pasos.append(_paso("Permiso de escritura", OK, "El token puede escribir."))
    else:
        pasos.append(_paso(
            "Permiso de escritura", FALLA,
            "El token es de solo lectura.",
            "Genera un token con permiso Contents: Read and write sobre este repositorio.",
        ))
        return {"pasos": pasos, "persistente": False}

    codigo, datos = _peticion(
        "GET", f"{API}/repos/{quote(owner)}/{quote(repo)}/branches/{quote(branch)}", token, timeout=timeout)
    if codigo == 200:
        pasos.append(_paso("Rama", OK, f"'{branch}' existe."))
    elif codigo == 404:
        pasos.append(_paso("Rama", FALLA, f"La rama '{branch}' no existe.",
                           f"Creala en GitHub, o corrige 'branch' en [ticketing]."))
        return {"pasos": pasos, "persistente": False}
    else:
        pasos.append(_paso("Rama", FALLA, f"Respuesta {codigo}: {datos.get('message', '')}"))
        return {"pasos": pasos, "persistente": False}

    ruta_tickets = f"{prefix}/tickets"
    codigo, datos = _peticion(
        "GET", f"{API}/repos/{quote(owner)}/{quote(repo)}/contents/{quote(ruta_tickets, safe='/')}?ref={quote(branch)}",
        token, timeout=timeout)
    if codigo == 200 and isinstance(datos, list):
        pasos.append(_paso("Solicitudes guardadas", OK, f"{len(datos)} solicitudes en {ruta_tickets}/"))
    else:
        pasos.append(_paso(
            "Solicitudes guardadas", AVISO,
            f"Todavia no existe {ruta_tickets}/. Se creara con la primera solicitud.",
            "Si ya creaste solicitudes y esta carpeta sigue vacia, no se estaban guardando.",
        ))

    if escribir_prueba:
        ruta = f"{prefix}/.diagnostico"
        url = f"{API}/repos/{quote(owner)}/{quote(repo)}/contents/{quote(ruta, safe='/')}"
        codigo_get, datos_get = _peticion("GET", f"{url}?ref={quote(branch)}", token, timeout=timeout)
        carga = {
            "message": "catalog: prueba de escritura del diagnostico",
            "content": base64.b64encode(b"ok\n").decode("ascii"),
            "branch": branch,
        }
        if codigo_get == 200 and isinstance(datos_get, dict) and datos_get.get("sha"):
            carga["sha"] = datos_get["sha"]
        codigo_put, datos_put = _peticion("PUT", url, token, carga, timeout=timeout)
        if codigo_put in (200, 201):
            pasos.append(_paso("Escritura real", OK, f"Se escribio {ruta} correctamente."))
        else:
            pasos.append(_paso("Escritura real", FALLA,
                               f"Respuesta {codigo_put}: {datos_put.get('message', '')}",
                               "El token no puede escribir en esta rama."))
            return {"pasos": pasos, "persistente": False}

    persistente = all(p["estado"] != FALLA for p in pasos)
    return {"pasos": pasos, "persistente": persistente}


def check_local_store(root):
    """El backend local NO es persistente en Streamlit Cloud."""
    from pathlib import Path

    ruta = Path(root)
    pasos = [_paso(
        "Backend", FALLA,
        f"Almacenamiento local en {ruta}. Streamlit Cloud borra esta carpeta "
        "en cada redespliegue, reinicio o suspension por inactividad.",
        'Configura [ticketing] con backend = "github" en Secrets.',
    )]
    if ruta.exists():
        tickets = list((ruta / "tickets").glob("*.json")) if (ruta / "tickets").exists() else []
        pasos.append(_paso("Contenido actual", AVISO,
                           f"{len(tickets)} solicitudes en disco. Se perderan en el proximo redespliegue."))
    return {"pasos": pasos, "persistente": False}


def resumen(resultado):
    """Una linea para la interfaz."""
    if resultado.get("persistente"):
        return OK, "Almacenamiento persistente"
    if any(p["estado"] == FALLA for p in resultado.get("pasos", [])):
        return FALLA, "Almacenamiento sin persistir"
    return AVISO, "Almacenamiento por confirmar"
