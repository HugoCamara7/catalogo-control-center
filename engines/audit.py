"""Motor de auditoria de acciones de usuario.

Sin dependencias de Streamlit.

Compatibilidad
--------------
Sustituye el almacenamiento de log_user_activity() conservando su firma y sus
8 campos originales (fecha, usuario, nombre, rol, accion, modulo, sitio,
detalle). Los registros antiguos se leen sin problema: los campos nuevos
quedan vacios.

Campos nuevos: marca, solicitud, estado_anterior, estado_nuevo, resultado.

Diseno
------
- Append-only. Un evento nunca se edita ni se borra desde la app.
- Un archivo por mes para acotar tamano y numero de escrituras.
- Dos backends con la misma interfaz:
    LocalAuditStore  -> disco (EFIMERO en Streamlit Cloud)
    GitHubAuditStore -> rama del repositorio (persistente)
- Nunca guarda contrasenas, tokens ni credenciales.
"""

import base64
import json
import re
from datetime import datetime, timedelta, timezone
from urllib.error import HTTPError, URLError
from urllib.parse import quote
from urllib.request import Request, urlopen

LIMA = timezone(timedelta(hours=-5))

# Campos originales de log_user_activity, en su orden. No cambiar.
CAMPOS_LEGADO = ["fecha", "usuario", "nombre", "rol", "accion", "modulo", "sitio", "detalle"]
# Campos que agrega este motor.
CAMPOS_NUEVOS = ["marca", "solicitud", "estado_anterior", "estado_nuevo", "resultado"]
CAMPOS = CAMPOS_LEGADO + CAMPOS_NUEVOS

MODULO_SESION = "Sesion"
MODULO_SOLICITUDES = "Solicitudes"
MODULO_INPUT = "Input comercial"
MODULO_CARGA = "Carga de catalogo"
MODULO_KPIS = "KPIs de catalogo"
MODULO_CONFIG = "Configuracion"

RESULTADOS = ("ok", "error", "aviso")

COLUMNAS_EXPORT = [
    "Fecha y hora (Peru)", "Usuario", "Correo", "Rol", "Marca", "Modulo",
    "Solicitud", "Accion", "Estado anterior", "Estado nuevo", "Resultado", "Detalle",
]

_CLAVES_SENSIBLES = re.compile(
    r"(pass|clave|secret|token|credential|authorization|api[_-]?key|private[_-]?key)", re.I)
_VALORES_SENSIBLES = re.compile(
    r"(ghp_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{20,}|shpat_[A-Za-z0-9]{20,}"
    r"|-----BEGIN [A-Z ]*PRIVATE KEY-----)")
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
    if isinstance(valor, (list, tuple)):
        return [sanitize_value(v) for v in valor]
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


def formato_lima(valor):
    if isinstance(valor, datetime):
        return valor.astimezone(LIMA).strftime("%d/%m/%Y %H:%M:%S")
    texto = _texto(valor)
    if not texto:
        return ""
    for patron in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S"):
        try:
            return datetime.strptime(texto[:19], patron).strftime("%d/%m/%Y %H:%M:%S")
        except ValueError:
            continue
    try:
        return datetime.fromisoformat(texto).astimezone(LIMA).strftime("%d/%m/%Y %H:%M:%S")
    except ValueError:
        return texto


def nombre_desde_correo(correo):
    correo = _texto(correo).casefold()
    if not correo:
        return "Usuario"
    local = correo.split("@", 1)[0]
    partes = [p for p in re.split(r"[._-]+", local) if p]
    return " ".join(p.capitalize() for p in partes) or correo


def build_event(accion, usuario, nombre="", rol="", modulo="", sitio="", marca="",
                solicitud="", estado_anterior="", estado_nuevo="", resultado="ok",
                detalle="", momento=None, extra=None):
    """Construye un evento normalizado y saneado.

    'fecha' conserva el formato original de log_user_activity para que los
    registros viejos y nuevos convivan en el mismo archivo.
    """
    momento = (momento or ahora_lima()).astimezone(LIMA)
    resultado = _texto(resultado).casefold() or "ok"
    if resultado not in RESULTADOS:
        resultado = "ok"
    correo = _texto(usuario).casefold()
    evento = {
        "fecha": momento.strftime("%Y-%m-%d %H:%M:%S"),
        "usuario": correo,
        "nombre": _texto(nombre) or nombre_desde_correo(correo),
        "rol": _texto(rol),
        "accion": _texto(accion),
        "modulo": _texto(modulo),
        "sitio": _texto(sitio),
        "detalle": sanitize_value(detalle),
        "marca": _texto(marca),
        "solicitud": _texto(solicitud),
        "estado_anterior": _texto(estado_anterior),
        "estado_nuevo": _texto(estado_nuevo),
        "resultado": resultado,
    }
    if extra:
        evento["extra"] = sanitize_value(extra)
    return evento


def normalizar(evento):
    """Completa los campos que falten. Permite leer registros antiguos."""
    fila = {campo: _texto(evento.get(campo)) for campo in CAMPOS}
    if not fila["nombre"]:
        fila["nombre"] = nombre_desde_correo(fila["usuario"])
    if not fila["resultado"]:
        fila["resultado"] = "ok"
    return fila


# --- almacenamiento ------------------------------------------------------
class AuditError(RuntimeError):
    pass


class LocalAuditStore:
    """Disco local. EFIMERO en Streamlit Cloud."""

    persistente = False
    nombre = "local"

    def __init__(self, root):
        from pathlib import Path

        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)

    def _archivo(self, periodo):
        return self.root / f"{periodo}.jsonl"

    def append(self, evento):
        with self._archivo(evento["fecha"][:7]).open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(evento, ensure_ascii=False, default=str) + "\n")
        return evento

    def read_period(self, periodo):
        archivo = self._archivo(periodo)
        if not archivo.exists():
            return []
        salida = []
        for linea in archivo.read_text(encoding="utf-8").splitlines():
            linea = linea.strip()
            if not linea:
                continue
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

    def _request(self, metodo, ruta, payload=None, ref=True):
        url = f"{self.base}/{quote(ruta, safe='/')}"
        if metodo == "GET" and ref:
            url += f"?ref={quote(self.branch)}"
        cuerpo = json.dumps(payload).encode("utf-8") if payload is not None else None
        peticion = Request(url, data=cuerpo, method=metodo, headers={
            "Accept": "application/vnd.github+json",
            "Authorization": f"Bearer {self.token}",
            "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": "catalog-control-center-audit",
            "Content-Type": "application/json",
        })
        try:
            with urlopen(peticion, timeout=self.timeout) as respuesta:
                texto = respuesta.read().decode("utf-8")
                return json.loads(texto) if texto else {}
        except HTTPError as exc:
            if exc.code == 404:
                return None
            detalle = exc.read().decode("utf-8", errors="replace")
            raise AuditError(f"GitHub respondio {exc.code}: {detalle[:200]}") from exc
        except (URLError, TimeoutError, OSError) as exc:
            raise AuditError(f"Sin conexion con GitHub: {exc}") from exc

    def _ruta(self, periodo):
        return f"{self.prefix}/{periodo}.jsonl"

    def _leer(self, periodo):
        datos = self._request("GET", self._ruta(periodo))
        if not isinstance(datos, dict) or "content" not in datos:
            return "", None
        crudo = base64.b64decode(datos["content"]).decode("utf-8", errors="replace")
        return crudo, datos.get("sha")

    def append(self, evento, reintentos=3):
        periodo = evento["fecha"][:7]
        linea = json.dumps(evento, ensure_ascii=False, default=str)
        ultimo = None
        for intento in range(reintentos):
            actual, sha = self._leer(periodo)
            nuevo = (actual if actual.endswith("\n") or not actual else actual + "\n") + linea + "\n"
            carga = {
                "message": f"audit: {evento.get('accion', '')} {evento.get('solicitud', '')}".strip(),
                "content": base64.b64encode(nuevo.encode("utf-8")).decode("ascii"),
                "branch": self.branch,
            }
            if sha:
                carga["sha"] = sha
            try:
                self._request("PUT", self._ruta(periodo), carga, ref=False)
                return evento
            except AuditError as exc:
                ultimo = exc
                if intento == reintentos - 1:
                    raise
        if ultimo:
            raise ultimo
        return evento

    def read_period(self, periodo):
        crudo, _ = self._leer(periodo)
        salida = []
        for linea in crudo.splitlines():
            linea = linea.strip()
            if not linea:
                continue
            try:
                salida.append(json.loads(linea))
            except json.JSONDecodeError:
                continue
        return salida

    def periods(self):
        datos = self._request("GET", self.prefix)
        if not isinstance(datos, list):
            return []
        return sorted(i["name"][:-6] for i in datos
                      if isinstance(i, dict) and i.get("name", "").endswith(".jsonl"))


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
        try:
            periodos = periodos or self.store.periods()
        except Exception:
            return []
        eventos = []
        for periodo in periodos:
            try:
                eventos.extend(self.store.read_period(periodo))
            except Exception:
                continue
        filas = [normalizar(e) for e in eventos]
        filas.sort(key=lambda e: e.get("fecha", ""), reverse=True)
        return filas

    def query(self, eventos=None, usuario="", rol="", accion="", modulo="", marca="",
              solicitud="", resultado="", desde=None, hasta=None, buscar=""):
        filas = list(eventos if eventos is not None else self.all_events())

        def igual(valor, esperado):
            return not esperado or _texto(valor).casefold() == _texto(esperado).casefold()

        def coincide(e):
            if not igual(e.get("usuario"), usuario):
                return False
            if not igual(e.get("rol"), rol):
                return False
            if not igual(e.get("accion"), accion):
                return False
            if not igual(e.get("modulo"), modulo):
                return False
            if not igual(e.get("marca"), marca):
                return False
            if not igual(e.get("solicitud"), solicitud):
                return False
            if not igual(e.get("resultado"), resultado):
                return False
            dia = _texto(e.get("fecha"))[:10]
            if desde and dia < _texto(desde)[:10]:
                return False
            if hasta and dia > _texto(hasta)[:10]:
                return False
            if buscar:
                aguja = _texto(buscar).casefold()
                campos = " ".join(_texto(e.get(c)) for c in CAMPOS).casefold()
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
            "pagina": pagina, "paginas": paginas, "total": total,
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
    def por_usuario(eventos):
        """Resumen por usuario para la vista de auditoria por persona."""
        agrupado = {}
        for e in eventos:
            correo = e.get("usuario") or "(sin usuario)"
            fila = agrupado.setdefault(correo, {
                "usuario": correo, "nombre": e.get("nombre") or nombre_desde_correo(correo),
                "rol": e.get("rol", ""), "acciones": 0, "solicitudes": set(),
                "modulos": set(), "errores": 0, "ultima": "",
            })
            fila["acciones"] += 1
            if e.get("solicitud"):
                fila["solicitudes"].add(e["solicitud"])
            if e.get("modulo"):
                fila["modulos"].add(e["modulo"])
            if e.get("resultado") == "error":
                fila["errores"] += 1
            if e.get("fecha", "") > fila["ultima"]:
                fila["ultima"] = e.get("fecha", "")
                if e.get("rol"):
                    fila["rol"] = e["rol"]
        salida = []
        for fila in agrupado.values():
            salida.append({
                "Usuario": fila["nombre"], "Correo": fila["usuario"], "Rol": fila["rol"],
                "Acciones": fila["acciones"], "Solicitudes": len(fila["solicitudes"]),
                "Modulos": len(fila["modulos"]), "Errores": fila["errores"],
                "Ultima actividad": formato_lima(fila["ultima"]),
            })
        salida.sort(key=lambda f: f["Acciones"], reverse=True)
        return salida

    @staticmethod
    def to_export_rows(eventos):
        """Filas listas para Excel o CSV, con encabezados en espanol."""
        return [{
            "Fecha y hora (Peru)": formato_lima(e.get("fecha", "")),
            "Usuario": e.get("nombre", ""),
            "Correo": e.get("usuario", ""),
            "Rol": e.get("rol", ""),
            "Marca": e.get("marca", ""),
            "Modulo": e.get("modulo", ""),
            "Solicitud": e.get("solicitud", ""),
            "Accion": e.get("accion", ""),
            "Estado anterior": e.get("estado_anterior", ""),
            "Estado nuevo": e.get("estado_nuevo", ""),
            "Resultado": e.get("resultado", ""),
            "Detalle": e.get("detalle", ""),
        } for e in eventos]
