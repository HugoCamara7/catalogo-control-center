"""Motor de auditoria de acciones de usuario.

Sin dependencias de Streamlit: es logica pura y testeable.

Diseno
------
- Append-only. Un evento nunca se edita ni se borra desde la app.
- Un archivo por mes (audit/YYYY-MM.jsonl) para acotar el tamano y el numero
  de escrituras contra GitHub.
- Dos backends con la misma interfaz, igual que ticket_system:
    LocalAuditStore  -> disco (EFIMERO en Streamlit Cloud)
    GitHubAuditStore -> rama del repositorio (persistente)
- Nunca se guardan contrasenas, tokens ni credenciales: sanitize_value() las
  reemplaza antes de escribir.
- Se registran acciones explicitas del usuario, nunca reruns ni renders.
"""

import json
import re
from datetime import datetime, timedelta, timezone
from urllib.error import HTTPError
from urllib.parse import quote
from urllib.request import Request, urlopen

LIMA = timezone(timedelta(hours=-5))

# --- catalogo de acciones -----------------------------------------------
MODULO_SOLICITUDES = "Solicitudes"
MODULO_INPUT = "Input comercial"
MODULO_CARGA = "Carga de catalogo"
MODULO_SESION = "Sesion"
MODULO_CONFIG = "Configuracion"

ACCIONES = {
    "login": ("Inicio de sesion", MODULO_SESION),
    "logout": ("Cierre de sesion", MODULO_SESION),
    "ticket_create": ("Crear solicitud", MODULO_SOLICITUDES),
    "ticket_submit": ("Enviar solicitud", MODULO_SOLICITUDES),
    "ticket_take": ("Tomar solicitud", MODULO_SOLICITUDES),
    "ticket_assign": ("Asignar o reasignar", MODULO_SOLICITUDES),
    "ticket_state": ("Cambiar estado", MODULO_SOLICITUDES),
    "ticket_observe": ("Observar solicitud", MODULO_SOLICITUDES),
    "ticket_finish": ("Finalizar solicitud", MODULO_SOLICITUDES),
    "ticket_reopen": ("Reabrir solicitud", MODULO_SOLICITUDES),
    "ticket_delete": ("Eliminar solicitud", MODULO_SOLICITUDES),
    "file_upload": ("Subir archivo", MODULO_INPUT),
    "file_validate": ("Validar archivo", MODULO_INPUT),
    "file_download": ("Descargar archivo", MODULO_INPUT),
    "template_download": ("Descargar formato", MODULO_INPUT),
    "load_select": ("Seleccionar solicitud para carga", MODULO_CARGA),
    "load_start": ("Iniciar carga", MODULO_CARGA),
    "load_complete": ("Completar carga", MODULO_CARGA),
    "load_fail": ("Carga fallida", MODULO_CARGA),
    "report_download": ("Descargar reporte", MODULO_CARGA),
    "config_change": ("Cambiar configuracion", MODULO_CONFIG),
    "user_change": ("Cambiar usuarios", MODULO_CONFIG),
}

RESULTADOS = ("ok", "error", "warning")

COLUMNAS_EXPORT = [
    "Fecha y hora (Peru)", "Usuario", "Correo", "Rol", "Accion", "Modulo",
    "Solicitud", "Valor anterior", "Valor nuevo", "Resultado", "Detalle",
]

# Claves cuyo VALOR nunca debe quedar registrado.
_CLAVES_SENSIBLES = re.compile(
    r"(pass|clave|secret|token|credential|authorization|api[_-]?key|private[_-]?key)",
    re.I,
)
_VALORES_SENSIBLES = re.compile(
    r"(ghp_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{20,}|shpat_[A-Za-z0-9]{20,}"
    r"|-----BEGIN [A-Z ]*PRIVATE KEY-----)",
)
OCULTO = "[oculto]"


def _texto(valor):
    if valor is None:
        return ""
    if isinstance(valor, float) and valor != valor:
        return ""
    return str(valor).strip()


def sanitize_value(valor, clave=""):
    """Evita que una contrasena o un token termine en el log."""
    if isinstance(valor, dict):
        return {k: sanitize_value(v, k) for k, v in valor.items()}
    texto = _texto(valor)
    if not texto:
        return ""
    if clave and _CLAVES_SENSIBLES.search(str(clave)):
        return OCULTO
    if _VALORES_SENSIBLES.search(texto):
        return OCULTO
    return texto


def ahora_lima():
    return datetime.now(LIMA)


def formato_lima(momento):
    if isinstance(momento, str):
        try:
            momento = datetime.fromisoformat(momento)
        except ValueError:
            return momento
    if momento.tzinfo is None:
        momento = momento.replace(tzinfo=timezone.utc)
    return momento.astimezone(LIMA).strftime("%d/%m/%Y %H:%M:%S")


def nombre_desde_correo(correo):
    correo = _texto(correo).casefold()
    if not correo:
        return "Usuario"
    local = correo.split("@", 1)[0]
    partes = [p for p in re.split(r"[._-]+", local) if p]
    return " ".join(p.capitalize() for p in partes) or correo


def build_event(accion, usuario, rol="", solicitud="", valor_anterior="",
                valor_nuevo="", resultado="ok", detalle="", modulo="",
                nombre="", momento=None):
    """Construye un evento normalizado y ya saneado."""
    etiqueta, modulo_por_defecto = ACCIONES.get(accion, (accion, "Otro"))
    momento = momento or ahora_lima()
    resultado = _texto(resultado).casefold() or "ok"
    if resultado not in RESULTADOS:
        resultado = "ok"
    correo = _texto(usuario).casefold()
    return {
        "ts": momento.astimezone(LIMA).isoformat(timespec="seconds"),
        "accion": _texto(accion),
        "accion_label": etiqueta,
        "modulo": _texto(modulo) or modulo_por_defecto,
        "usuario": correo,
        "nombre": _texto(nombre) or nombre_desde_correo(correo),
        "rol": _texto(rol),
        "solicitud": _texto(solicitud),
        "valor_anterior": sanitize_value(valor_anterior),
        "valor_nuevo": sanitize_value(valor_nuevo),
        "resultado": resultado,
        "detalle": sanitize_value(detalle),
    }


# --- almacenamiento ------------------------------------------------------
class AuditError(RuntimeError):
    pass


class LocalAuditStore:
    """Disco local. EFIMERO en Streamlit Cloud: se borra en cada redespliegue."""

    persistente = False
    nombre = "local"

    def __init__(self, root):
        from pathlib import Path

        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)

    def _archivo(self, periodo):
        return self.root / f"{periodo}.jsonl"

    def append(self, evento):
        periodo = evento["ts"][:7]
        with self._archivo(periodo).open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(evento, ensure_ascii=False) + "\n")
        return evento

    def read_period(self, periodo):
        archivo = self._archivo(periodo)
        if not archivo.exists():
            return []
        salida = []
        for linea in archivo.read_text(encoding="utf-8").splitlines():
            linea = linea.strip()
            if linea:
                try:
                    salida.append(json.loads(linea))
                except json.JSONDecodeError:
                    continue
        return salida

    def periods(self):
        return sorted(p.stem for p in self.root.glob("*.jsonl"))


class GitHubAuditStore:
    """Rama del repositorio. Persistente entre redespliegues."""

    persistente = True
    nombre = "github"

    def __init__(self, owner, repo, token, branch="catalog-tickets",
                 prefix="catalog_tickets/audit", timeout=30):
        if not all([owner, repo, token, branch]):
            raise AuditError("Configuracion GitHub incompleta para auditoria.")
        self.owner, self.repo, self.token = owner, repo, token
        self.branch = branch
        self.prefix = prefix.strip("/")
        self.timeout = int(timeout)
        self.base = f"https://api.github.com/repos/{quote(owner)}/{quote(repo)}/contents"

    def _request(self, method, path, payload=None, ref=True):
        url = f"{self.base}/{quote(path, safe='/')}"
        if method == "GET" and ref:
            url += f"?ref={quote(self.branch)}"
        body = json.dumps(payload).encode("utf-8") if payload is not None else None
        peticion = Request(url, data=body, method=method, headers={
            "Accept": "application/vnd.github+json",
            "Authorization": f"Bearer {self.token}",
            "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": "catalog-control-center-audit",
            "Content-Type": "application/json",
        })
        try:
            with urlopen(peticion, timeout=self.timeout) as respuesta:
                return json.loads(respuesta.read().decode("utf-8"))
        except HTTPError as exc:
            if exc.code == 404:
                return None
            detalle = exc.read().decode("utf-8", errors="replace")
            raise AuditError(f"GitHub respondio {exc.code}: {detalle[:300]}") from exc

    def _ruta(self, periodo):
        return f"{self.prefix}/{periodo}.jsonl"

    def _leer(self, periodo):
        import base64

        datos = self._request("GET", self._ruta(periodo))
        if not isinstance(datos, dict) or "content" not in datos:
            return "", None
        crudo = base64.b64decode(datos["content"]).decode("utf-8", errors="replace")
        return crudo, datos.get("sha")

    def append(self, evento, reintentos=3):
        import base64

        periodo = evento["ts"][:7]
        linea = json.dumps(evento, ensure_ascii=False)
        for intento in range(reintentos):
            actual, sha = self._leer(periodo)
            nuevo = (actual + linea + "\n") if actual else (linea + "\n")
            carga = {
                "message": f"audit: {evento['accion']} {evento.get('solicitud') or ''}".strip(),
                "content": base64.b64encode(nuevo.encode("utf-8")).decode("ascii"),
                "branch": self.branch,
            }
            if sha:
                carga["sha"] = sha
            try:
                self._request("PUT", self._ruta(periodo), carga, ref=False)
                return evento
            except AuditError:
                if intento == reintentos - 1:
                    raise
        return evento

    def read_period(self, periodo):
        crudo, _ = self._leer(periodo)
        salida = []
        for linea in crudo.splitlines():
            linea = linea.strip()
            if linea:
                try:
                    salida.append(json.loads(linea))
                except json.JSONDecodeError:
                    continue
        return salida

    def periods(self):
        datos = self._request("GET", self.prefix)
        if not isinstance(datos, list):
            return []
        return sorted(
            item["name"][:-6] for item in datos
            if isinstance(item, dict) and item.get("name", "").endswith(".jsonl")
        )


# --- servicio ------------------------------------------------------------
class AuditService:
    def __init__(self, store):
        self.store = store

    @property
    def persistente(self):
        return bool(getattr(self.store, "persistente", False))

    def record(self, accion, usuario, **kwargs):
        """Registra un evento. Nunca lanza: la auditoria no debe tumbar la app."""
        try:
            return self.store.append(build_event(accion, usuario, **kwargs))
        except Exception:
            return None

    def all_events(self, periodos=None):
        periodos = periodos or self.store.periods()
        eventos = []
        for periodo in periodos:
            eventos.extend(self.store.read_period(periodo))
        eventos.sort(key=lambda e: e.get("ts", ""), reverse=True)
        return eventos

    def query(self, eventos=None, usuario="", rol="", accion="", modulo="",
              resultado="", desde=None, hasta=None, buscar=""):
        filas = list(eventos if eventos is not None else self.all_events())

        def coincide(evento):
            if usuario and _texto(evento.get("usuario")).casefold() != _texto(usuario).casefold():
                return False
            if rol and _texto(evento.get("rol")).casefold() != _texto(rol).casefold():
                return False
            if accion and evento.get("accion") != accion:
                return False
            if modulo and evento.get("modulo") != modulo:
                return False
            if resultado and evento.get("resultado") != resultado:
                return False
            ts = _texto(evento.get("ts"))[:10]
            if desde and ts < _texto(desde)[:10]:
                return False
            if hasta and ts > _texto(hasta)[:10]:
                return False
            if buscar:
                aguja = _texto(buscar).casefold()
                campos = " ".join(_texto(evento.get(k)) for k in (
                    "nombre", "usuario", "accion_label", "modulo", "solicitud",
                    "valor_anterior", "valor_nuevo", "detalle",
                )).casefold()
                if aguja not in campos:
                    return False
            return True

        return [e for e in filas if coincide(e)]

    @staticmethod
    def paginate(eventos, pagina=1, por_pagina=30):
        total = len(eventos)
        paginas = max(1, (total + por_pagina - 1) // por_pagina)
        pagina = max(1, min(int(pagina or 1), paginas))
        inicio = (pagina - 1) * por_pagina
        return {
            "filas": eventos[inicio:inicio + por_pagina],
            "pagina": pagina,
            "paginas": paginas,
            "total": total,
            "desde": inicio + 1 if total else 0,
            "hasta": min(inicio + por_pagina, total),
        }

    @staticmethod
    def kpis(eventos):
        return {
            "total": len(eventos),
            "usuarios": len({e.get("usuario") for e in eventos if e.get("usuario")}),
            "solicitudes": len({e.get("solicitud") for e in eventos if e.get("solicitud")}),
            "errores": sum(1 for e in eventos if e.get("resultado") == "error"),
        }

    @staticmethod
    def to_export_rows(eventos):
        """Filas listas para Excel, con encabezados en espanol."""
        return [{
            "Fecha y hora (Peru)": formato_lima(e.get("ts", "")),
            "Usuario": e.get("nombre", ""),
            "Correo": e.get("usuario", ""),
            "Rol": e.get("rol", ""),
            "Accion": e.get("accion_label", e.get("accion", "")),
            "Modulo": e.get("modulo", ""),
            "Solicitud": e.get("solicitud", ""),
            "Valor anterior": e.get("valor_anterior", ""),
            "Valor nuevo": e.get("valor_nuevo", ""),
            "Resultado": e.get("resultado", ""),
            "Detalle": e.get("detalle", ""),
        } for e in eventos]
