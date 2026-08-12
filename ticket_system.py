"""Persistent catalog ticket domain for Catalog Control Center.

The module has no Streamlit dependency. Production can persist metadata and
validated files in a dedicated GitHub branch; tests and local development use
the filesystem backend. External effects are behind adapters and default to
safe mocks.
"""

from __future__ import annotations

import base64
import hashlib
import json
import os
import re
import tempfile
import threading
import time
import uuid
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.error import HTTPError
from urllib.parse import quote
from urllib.request import Request, urlopen


ROLE_BRAND = "brand"
ROLE_OPERATOR = "operator"
ROLE_ADMIN = "admin"
ROLE_SYSTEM = "system"

STATE_DRAFT = "draft"
STATE_REQUEST_RECEIVED = "request_received"
STATE_PENDING_ASSIGNMENT = "pending_assignment"
STATE_ASSIGNED = "assigned"
STATE_DIGITAL_REVIEW = "digital_review"
STATE_OBSERVED = "observed"
STATE_WAITING_BRAND = "waiting_brand_correction"
STATE_CORRECTION_RECEIVED = "correction_received"
STATE_LOAD_APPROVED = "load_approved"
STATE_PREPARING = "preparing_catalog"
STATE_DRY_RUN = "dry_run"
STATE_READY_EXECUTE = "ready_execute"
STATE_LOADING = "loading"
STATE_VALIDATING = "validating_results"
# Etapas del cierre de carga. Se agregaron sin tocar las anteriores: una
# solicitud historica nunca pasa por aqui y su recorrido sigue siendo valido.
# Cadena objetivo: Carga SIAL -> Carga de precios -> Validacion precio/stock
# -> Shopify -> Finalizada.
STATE_SIAL_LOADED = "sial_loaded"
STATE_PRICE_REQUESTED = "price_load_requested"
STATE_PRICE_VALIDATION = "price_stock_validation"
STATE_READY_CLOSE = "ready_to_close"
STATE_COMPLETED = "completed"
STATE_COMPLETED_OBS = "completed_with_observations"
STATE_FAILED = "failed"
STATE_REJECTED = "rejected"
STATE_CANCELED = "canceled"

# Backward-compatible public names used by the existing Streamlit UI.
STATE_PENDING = STATE_PENDING_ASSIGNMENT
STATE_REVIEW = STATE_DIGITAL_REVIEW
STATE_CORRECTED = STATE_CORRECTION_RECEIVED
STATE_APPROVED = STATE_LOAD_APPROVED

STATE_LABELS = {
    STATE_DRAFT: "Borrador",
    STATE_REQUEST_RECEIVED: "Solicitud recibida",
    STATE_PENDING_ASSIGNMENT: "Pendiente de asignación",
    STATE_ASSIGNED: "Asignada",
    STATE_DIGITAL_REVIEW: "Revisión Digital",
    STATE_OBSERVED: "Observada",
    STATE_WAITING_BRAND: "Esperando corrección de la marca",
    STATE_CORRECTION_RECEIVED: "Corrección recibida",
    STATE_LOAD_APPROVED: "Aprobada para carga",
    STATE_PREPARING: "Preparando catálogo",
    STATE_DRY_RUN: "Validación previa en proceso",
    STATE_READY_EXECUTE: "Lista para ejecutar",
    STATE_LOADING: "Cargando Shopify",
    STATE_VALIDATING: "Validando resultados",
    STATE_SIAL_LOADED: "SIAL cargado · Esperando carga de precios",
    STATE_PRICE_REQUESTED: "Carga de precios solicitada",
    STATE_PRICE_VALIDATION: "Validando precio y stock en Shopify",
    STATE_READY_CLOSE: "Lista para cierre",
    STATE_COMPLETED: "Completada",
    STATE_COMPLETED_OBS: "Completada con incidencias",
    STATE_FAILED: "Fallida",
    STATE_REJECTED: "Rechazada",
    STATE_CANCELED: "Cancelada",
}

LEGACY_STATE_MAP = {
    "pending_review": STATE_PENDING_ASSIGNMENT,
    "in_review": STATE_DIGITAL_REVIEW,
    "corrected": STATE_CORRECTION_RECEIVED,
    "approved": STATE_LOAD_APPROVED,
}

BRAND_STATE_LABELS = {
    STATE_DRAFT: ("Borrador", 5, "Completa y valida el archivo."),
    STATE_REQUEST_RECEIVED: ("Recibida", 10, "El equipo recibió tu solicitud."),
    STATE_PENDING_ASSIGNMENT: ("Recibida", 15, "Pendiente de asignación interna."),
    STATE_ASSIGNED: ("En validación", 25, "La solicitud ya tiene responsable."),
    STATE_DIGITAL_REVIEW: ("En validación", 35, "El equipo está revisando la información."),
    STATE_OBSERVED: ("Observada", 40, "Revisa las observaciones y carga una corrección."),
    STATE_WAITING_BRAND: ("Esperando corrección", 40, "Carga la versión corregida."),
    STATE_CORRECTION_RECEIVED: ("Corrección recibida", 50, "El equipo revisará la nueva versión."),
    STATE_LOAD_APPROVED: ("Aprobada", 60, "La solicitud está aprobada para preparación."),
    STATE_PREPARING: ("En preparación", 70, "Se está preparando el catálogo."),
    STATE_DRY_RUN: ("En preparación", 75, "Se está validando antes de ejecutar."),
    STATE_READY_EXECUTE: ("Aprobada", 80, "La carga está lista para ejecutar."),
    STATE_LOADING: ("En proceso", 88, "La carga se está procesando."),
    STATE_VALIDATING: ("En proceso", 95, "Se están validando los resultados."),
    STATE_SIAL_LOADED: ("En proceso", 90, "La carga SIAL terminó. Sigue la carga de precios."),
    STATE_PRICE_REQUESTED: ("En proceso", 92, "El Área de Producto está cargando los precios."),
    STATE_PRICE_VALIDATION: ("En proceso", 96, "Se está validando precio y stock antes de publicar."),
    STATE_READY_CLOSE: ("Lista para cierre", 98, "Todo validado. El equipo cerrará la solicitud."),
    STATE_COMPLETED: ("Completada", 100, "La solicitud finalizó correctamente."),
    STATE_COMPLETED_OBS: ("Completada", 100, "La solicitud finalizó con observaciones."),
    STATE_FAILED: ("Requiere atención", 85, "El equipo está revisando una incidencia."),
    STATE_REJECTED: ("Requiere atención", 100, "La solicitud fue rechazada."),
    STATE_CANCELED: ("Cancelada", 100, "La solicitud fue cancelada."),
}

PRIORITIES = ("low", "normal", "high", "urgent")
PRIORITY_LABELS = {
    "low": "Baja",
    "normal": "Normal",
    "high": "Alta",
    "urgent": "Urgente",
}

TRANSITIONS = {
    ROLE_BRAND: {
        STATE_DRAFT: {STATE_REQUEST_RECEIVED, STATE_CANCELED},
        STATE_REQUEST_RECEIVED: {STATE_PENDING_ASSIGNMENT, STATE_CANCELED},
        STATE_OBSERVED: {STATE_WAITING_BRAND, STATE_CANCELED},
        STATE_WAITING_BRAND: {STATE_CORRECTION_RECEIVED, STATE_CANCELED},
        STATE_PENDING_ASSIGNMENT: {STATE_CANCELED},
    },
    ROLE_OPERATOR: {
        STATE_PENDING_ASSIGNMENT: {STATE_ASSIGNED, STATE_DIGITAL_REVIEW, STATE_CANCELED},
        STATE_ASSIGNED: {STATE_DIGITAL_REVIEW, STATE_PENDING_ASSIGNMENT, STATE_CANCELED},
        STATE_DIGITAL_REVIEW: {STATE_OBSERVED, STATE_LOAD_APPROVED, STATE_REJECTED, STATE_CANCELED},
        STATE_OBSERVED: {STATE_WAITING_BRAND, STATE_DIGITAL_REVIEW, STATE_CANCELED},
        STATE_CORRECTION_RECEIVED: {STATE_DIGITAL_REVIEW, STATE_OBSERVED, STATE_LOAD_APPROVED, STATE_CANCELED},
        STATE_LOAD_APPROVED: {STATE_PREPARING, STATE_DRY_RUN, STATE_CANCELED},
        STATE_PREPARING: {STATE_DRY_RUN, STATE_CANCELED},
        STATE_DRY_RUN: {STATE_READY_EXECUTE, STATE_FAILED, STATE_CANCELED},
        STATE_READY_EXECUTE: {STATE_LOADING, STATE_CANCELED},
        STATE_FAILED: {STATE_DRY_RUN, STATE_READY_EXECUTE, STATE_LOADING, STATE_CANCELED},
        # Cierre de carga por etapas. Ninguna de estas transiciones quita
        # las que ya existian: cerrar directo desde loading sigue valiendo.
        STATE_LOADING: {STATE_SIAL_LOADED, STATE_CANCELED},
        STATE_VALIDATING: {STATE_SIAL_LOADED, STATE_CANCELED},
        STATE_SIAL_LOADED: {STATE_PRICE_REQUESTED, STATE_FAILED, STATE_CANCELED},
        STATE_PRICE_REQUESTED: {STATE_PRICE_VALIDATION, STATE_FAILED, STATE_CANCELED},
        STATE_PRICE_VALIDATION: {STATE_READY_CLOSE, STATE_LOADING, STATE_FAILED, STATE_CANCELED},
        STATE_READY_CLOSE: {STATE_PRICE_VALIDATION, STATE_FAILED, STATE_CANCELED},
    },
    ROLE_ADMIN: {
        STATE_PENDING_ASSIGNMENT: {STATE_ASSIGNED, STATE_DIGITAL_REVIEW, STATE_REJECTED, STATE_CANCELED},
        STATE_ASSIGNED: {STATE_DIGITAL_REVIEW, STATE_PENDING_ASSIGNMENT, STATE_CANCELED},
        STATE_DIGITAL_REVIEW: {STATE_OBSERVED, STATE_LOAD_APPROVED, STATE_REJECTED, STATE_CANCELED},
        STATE_OBSERVED: {STATE_WAITING_BRAND, STATE_DIGITAL_REVIEW, STATE_REJECTED, STATE_CANCELED},
        STATE_WAITING_BRAND: {STATE_DIGITAL_REVIEW, STATE_REJECTED, STATE_CANCELED},
        STATE_CORRECTION_RECEIVED: {STATE_DIGITAL_REVIEW, STATE_OBSERVED, STATE_LOAD_APPROVED, STATE_REJECTED},
        STATE_LOAD_APPROVED: {STATE_PREPARING, STATE_DRY_RUN, STATE_CANCELED},
        STATE_PREPARING: {STATE_DRY_RUN, STATE_CANCELED},
        STATE_DRY_RUN: {STATE_READY_EXECUTE, STATE_FAILED, STATE_CANCELED},
        STATE_READY_EXECUTE: {STATE_LOADING, STATE_CANCELED},
        STATE_FAILED: {STATE_DRY_RUN, STATE_READY_EXECUTE, STATE_LOADING, STATE_CANCELED},
        STATE_LOADING: {STATE_SIAL_LOADED, STATE_CANCELED},
        STATE_VALIDATING: {STATE_SIAL_LOADED, STATE_CANCELED},
        STATE_SIAL_LOADED: {STATE_PRICE_REQUESTED, STATE_FAILED, STATE_REJECTED, STATE_CANCELED},
        STATE_PRICE_REQUESTED: {STATE_PRICE_VALIDATION, STATE_FAILED, STATE_REJECTED, STATE_CANCELED},
        STATE_PRICE_VALIDATION: {STATE_READY_CLOSE, STATE_LOADING, STATE_FAILED, STATE_REJECTED, STATE_CANCELED},
        STATE_READY_CLOSE: {STATE_PRICE_VALIDATION, STATE_FAILED, STATE_REJECTED, STATE_CANCELED},
    },
    ROLE_SYSTEM: {
        STATE_LOADING: {STATE_VALIDATING, STATE_COMPLETED, STATE_COMPLETED_OBS, STATE_FAILED},
        STATE_VALIDATING: {STATE_COMPLETED, STATE_COMPLETED_OBS, STATE_FAILED},
        # Dentro de la cadena de cierre, "Completada" SOLO se alcanza desde
        # "Lista para cierre". Antes se podia cerrar en cuanto terminaba el
        # SIAL, que es justo el error que habia que corregir: la solicitud
        # quedaba completada sin precios cargados ni validados.
        STATE_SIAL_LOADED: {STATE_FAILED},
        STATE_PRICE_REQUESTED: {STATE_FAILED},
        STATE_PRICE_VALIDATION: {STATE_FAILED},
        STATE_READY_CLOSE: {STATE_COMPLETED, STATE_COMPLETED_OBS, STATE_FAILED},
    },
}

# Etapas del cierre de carga, en orden. La interfaz las usa para saber cual es
# el siguiente paso sin repetir la cadena en cada pantalla.
CADENA_CIERRE_CARGA = (
    STATE_LOADING,
    STATE_SIAL_LOADED,
    STATE_PRICE_REQUESTED,
    STATE_PRICE_VALIDATION,
    STATE_READY_CLOSE,
    STATE_COMPLETED,
)


class TicketError(RuntimeError):
    pass


class TicketPermissionError(TicketError):
    pass


class TicketConflictError(TicketError):
    pass


class TicketValidationError(TicketError):
    pass


def utc_now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def normalize_text(value):
    return str(value or "").strip()


def normalize_key(value):
    value = normalize_text(value).casefold()
    return re.sub(r"[^a-z0-9]+", "", value)


def internal_state(value):
    return LEGACY_STATE_MAP.get(normalize_text(value), normalize_text(value) or STATE_DRAFT)


def brand_state(ticket):
    state = internal_state((ticket or {}).get("status"))
    label, progress, next_step = BRAND_STATE_LABELS.get(
        state,
        (STATE_LABELS.get(state, state or "Sin estado"), 0, "Consulta al equipo de catálogo."),
    )
    return {
        "state": state,
        "label": label,
        "progress": int(progress),
        "next_step": next_step,
        "updated_at": normalize_text((ticket or {}).get("updated_at")),
        "responsible": normalize_text((ticket or {}).get("assignee")) or "Equipo de catálogo",
    }


def upgrade_ticket(ticket):
    """Migrate old persisted tickets in memory without requiring a destructive migration."""
    if not isinstance(ticket, dict):
        return ticket
    upgraded = deepcopy(ticket)
    upgraded["schema_version"] = max(2, int(upgraded.get("schema_version", 1) or 1))
    upgraded["status"] = internal_state(upgraded.get("status"))
    upgraded.setdefault("requester_name", normalize_text(upgraded.get("requester")).split("@")[0].replace(".", " ").title())
    upgraded.setdefault("requested_date", normalize_text(upgraded.get("created_at"))[:10])
    upgraded.setdefault("assignment_history", [])
    upgraded.setdefault("comments", [])
    upgraded.setdefault("notifications", [])
    upgraded.setdefault("events", [])
    upgraded.setdefault("observations", [])
    upgraded.setdefault("versions", [])
    upgraded.setdefault("dry_run", {})
    upgraded.setdefault("sial", {})
    upgraded.setdefault("price_load", {})
    upgraded.setdefault("price_check", {})
    upgraded.setdefault("job", {})
    upgraded.setdefault("result", {})
    upgraded.setdefault("public_result", {})
    for comment in upgraded["comments"]:
        comment.setdefault("visibility", "public")
        comment.setdefault("model_color", comment.get("product", ""))
        comment.setdefault("row", "")
    for notification in upgraded["notifications"]:
        notification.setdefault("read_by", [])
        notification.setdefault("link", f"ticket:{upgraded.get('code', '')}")
    return upgraded


def _payload_bytes(payload):
    """Normalize uploaded files and in-memory buffers before persistence."""
    if payload is None:
        return b""
    if isinstance(payload, bytes):
        return payload
    if isinstance(payload, bytearray):
        return bytes(payload)
    if isinstance(payload, memoryview):
        return payload.tobytes()

    getvalue = getattr(payload, "getvalue", None)
    if callable(getvalue):
        return _payload_bytes(getvalue())

    reader = getattr(payload, "read", None)
    if callable(reader):
        current_position = None
        try:
            teller = getattr(payload, "tell", None)
            if callable(teller):
                current_position = teller()
            seeker = getattr(payload, "seek", None)
            if callable(seeker):
                seeker(0)
            value = reader()
            if current_position is not None and callable(seeker):
                seeker(current_position)
            return _payload_bytes(value)
        except (OSError, TypeError, ValueError) as exc:
            raise TicketValidationError("No se pudo leer el archivo adjunto.") from exc

    raise TicketValidationError("El adjunto no tiene un formato de archivo v\u00e1lido.")


def file_sha256(payload):
    return hashlib.sha256(_payload_bytes(payload)).hexdigest()


def _safe_name(value):
    return re.sub(r"[^A-Za-z0-9._-]+", "_", normalize_text(value)).strip("._") or "archivo"


def _actor(user, role, brands=None):
    return {
        "user": normalize_text(user).casefold(),
        "role": normalize_text(role).casefold(),
        "brands": sorted({normalize_key(item) for item in (brands or []) if normalize_key(item)}),
    }


def can_view_ticket(actor, ticket):
    role = actor.get("role")
    if role == ROLE_ADMIN:
        return True
    if role == ROLE_BRAND:
        return (
            ticket.get("requester") == actor.get("user")
            and normalize_key(ticket.get("brand")) in set(actor.get("brands") or [])
        )
    if role == ROLE_OPERATOR:
        allowed = set(actor.get("brands") or [])
        return not allowed or normalize_key(ticket.get("brand")) in allowed
    return False


class LocalTicketStore:
    """Atomic filesystem persistence for tests and controlled local installs."""

    _lock = threading.RLock()

    def __init__(self, root):
        self.root = Path(root)
        self.ticket_dir = self.root / "tickets"
        self.artifact_dir = self.root / "artifacts"
        self.ticket_dir.mkdir(parents=True, exist_ok=True)
        self.artifact_dir.mkdir(parents=True, exist_ok=True)

    def allocate_code(self, year=None):
        year = int(year or datetime.now(timezone.utc).year)
        counter_path = self.root / "sequence.json"
        with self._lock:
            data = self._read_json(counter_path, {})
            next_value = int(data.get(str(year), 0)) + 1
            data[str(year)] = next_value
            self._atomic_json(counter_path, data)
        return f"CAT-{year}-{next_value:06d}"

    def list_tickets(self):
        tickets = []
        for path in sorted(self.ticket_dir.glob("CAT-*.json"), reverse=True):
            ticket = self._read_json(path, None)
            if ticket:
                ticket = upgrade_ticket(ticket)
                ticket["_revision"] = int(ticket.get("_revision", 1))
                tickets.append(ticket)
        return tickets

    def get_ticket(self, code):
        ticket = self._read_json(self.ticket_dir / f"{_safe_name(code)}.json", None)
        if ticket:
            ticket = upgrade_ticket(ticket)
            ticket["_revision"] = int(ticket.get("_revision", 1))
        return ticket

    def create_ticket(self, ticket):
        path = self.ticket_dir / f"{_safe_name(ticket['code'])}.json"
        with self._lock:
            if path.exists():
                raise TicketConflictError(f"El ticket {ticket['code']} ya existe.")
            saved = upgrade_ticket(ticket)
            saved["_revision"] = 1
            self._atomic_json(path, saved)
        return self.get_ticket(ticket["code"])

    def update_ticket(self, ticket, expected_revision):
        path = self.ticket_dir / f"{_safe_name(ticket['code'])}.json"
        with self._lock:
            current = self._read_json(path, None)
            if not current:
                raise TicketValidationError("Ticket no encontrado.")
            current_revision = int(current.get("_revision", 1))
            if int(expected_revision or 0) != current_revision:
                raise TicketConflictError("El ticket cambió en otra sesión. Recarga antes de continuar.")
            saved = upgrade_ticket(ticket)
            saved["_revision"] = current_revision + 1
            self._atomic_json(path, saved)
        return self.get_ticket(ticket["code"])

    def delete_ticket(self, code, expected_revision):
        """Remove a ticket record so it no longer appears in the operational inbox."""
        path = self.ticket_dir / f"{_safe_name(code)}.json"
        with self._lock:
            current = self._read_json(path, None)
            if not current:
                raise TicketValidationError("Ticket no encontrado.")
            current_revision = int(current.get("_revision", 1))
            if int(expected_revision or 0) != current_revision:
                raise TicketConflictError("El ticket cambió en otra sesión. Recarga antes de continuar.")
            path.unlink()
        return True

    def put_artifact(self, code, version, kind, filename, payload):
        payload = _payload_bytes(payload)
        folder = self.artifact_dir / _safe_name(code)
        folder.mkdir(parents=True, exist_ok=True)
        relative = Path("artifacts") / _safe_name(code) / f"v{int(version):03d}_{kind}_{_safe_name(filename)}"
        path = self.root / relative
        with self._lock:
            path.write_bytes(payload)
        return relative.as_posix()

    def get_artifact(self, path):
        target = (self.root / normalize_text(path)).resolve()
        if self.root.resolve() not in target.parents:
            raise TicketPermissionError("Ruta de archivo inválida.")
        return target.read_bytes()

    @staticmethod
    def _read_json(path, default):
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (FileNotFoundError, json.JSONDecodeError):
            return default

    @staticmethod
    def _atomic_json(path, data):
        path.parent.mkdir(parents=True, exist_ok=True)
        fd, temp_name = tempfile.mkstemp(prefix=path.name, suffix=".tmp", dir=str(path.parent))
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                json.dump(data, handle, ensure_ascii=False, indent=2)
            for attempt in range(5):
                try:
                    os.replace(temp_name, path)
                    break
                except PermissionError:
                    if attempt == 4:
                        # OneDrive/antivirus can briefly lock the destination on Windows.
                        path.write_text(
                            Path(temp_name).read_text(encoding="utf-8"),
                            encoding="utf-8",
                        )
                        break
                    time.sleep(0.05 * (attempt + 1))
        finally:
            if os.path.exists(temp_name):
                os.unlink(temp_name)


class GitHubTicketStore:
    """GitHub Contents persistence with SHA-based optimistic concurrency."""

    def __init__(self, owner, repo, token, branch="catalog-tickets", prefix="catalog_tickets", timeout=30):
        if not all([owner, repo, token, branch]):
            raise TicketValidationError("Configuración GitHub incompleta para tickets.")
        self.owner = owner
        self.repo = repo
        self.token = token
        self.branch = branch
        self.prefix = prefix.strip("/")
        self.timeout = int(timeout)
        self.base = f"https://api.github.com/repos/{quote(owner)}/{quote(repo)}/contents"

    def _request(self, method, path, payload=None, ref=True):
        url = f"{self.base}/{quote(path, safe='/')}"
        if method == "GET" and ref:
            url += f"?ref={quote(self.branch)}"
        body = json.dumps(payload).encode("utf-8") if payload is not None else None
        request = Request(
            url,
            data=body,
            method=method,
            headers={
                "Accept": "application/vnd.github+json",
                "Authorization": f"Bearer {self.token}",
                "X-GitHub-Api-Version": "2022-11-28",
                "User-Agent": "catalog-control-center",
                "Content-Type": "application/json",
            },
        )
        try:
            with urlopen(request, timeout=self.timeout) as response:
                return json.loads(response.read().decode("utf-8"))
        except HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            if exc.code == 404:
                return None
            if exc.code in {409, 422}:
                raise TicketConflictError("Conflicto de escritura en GitHub; vuelve a intentar.") from exc
            raise TicketError(f"GitHub respondió {exc.code}: {detail[:500]}") from exc

    def _get_file(self, path):
        data = self._request("GET", path)
        if not isinstance(data, dict):
            return None, None
        content = base64.b64decode(data.get("content", ""))
        return content, data.get("sha")

    def _put_file(self, path, payload, message, sha=None):
        body = {
            "message": message,
            "content": base64.b64encode(payload or b"").decode("ascii"),
            "branch": self.branch,
        }
        if sha:
            body["sha"] = sha
        data = self._request("PUT", path, body, ref=False)
        return (data or {}).get("content", {}).get("sha")

    def allocate_code(self, year=None):
        year = int(year or datetime.now(timezone.utc).year)
        path = f"{self.prefix}/sequence.json"
        for attempt in range(6):
            raw, sha = self._get_file(path)
            data = json.loads(raw.decode("utf-8")) if raw else {}
            next_value = int(data.get(str(year), 0)) + 1
            data[str(year)] = next_value
            try:
                self._put_file(path, json.dumps(data, indent=2).encode("utf-8"), "catalog: allocate ticket", sha)
                return f"CAT-{year}-{next_value:06d}"
            except TicketConflictError:
                time.sleep(0.15 * (attempt + 1))
        raise TicketConflictError("No se pudo reservar un código de ticket único.")

    def list_tickets(self):
        data = self._request("GET", f"{self.prefix}/tickets")
        if not isinstance(data, list):
            return []
        tickets = []
        for item in data:
            if item.get("type") != "file" or not item.get("name", "").endswith(".json"):
                continue
            raw, sha = self._get_file(item["path"])
            try:
                ticket = json.loads(raw.decode("utf-8"))
            except (AttributeError, json.JSONDecodeError):
                continue
            ticket = upgrade_ticket(ticket)
            ticket["_revision"] = sha
            tickets.append(ticket)
        return sorted(tickets, key=lambda item: item.get("created_at", ""), reverse=True)

    def get_ticket(self, code):
        path = f"{self.prefix}/tickets/{_safe_name(code)}.json"
        raw, sha = self._get_file(path)
        if not raw:
            return None
        ticket = upgrade_ticket(json.loads(raw.decode("utf-8")))
        ticket["_revision"] = sha
        return ticket

    def create_ticket(self, ticket):
        path = f"{self.prefix}/tickets/{_safe_name(ticket['code'])}.json"
        _, sha = self._get_file(path)
        if sha:
            raise TicketConflictError(f"El ticket {ticket['code']} ya existe.")
        saved = upgrade_ticket(ticket)
        saved.pop("_revision", None)
        revision = self._put_file(path, json.dumps(saved, ensure_ascii=False, indent=2).encode("utf-8"), f"catalog: create {ticket['code']}")
        saved["_revision"] = revision
        return saved

    def update_ticket(self, ticket, expected_revision):
        path = f"{self.prefix}/tickets/{_safe_name(ticket['code'])}.json"
        current, sha = self._get_file(path)
        if not current:
            raise TicketValidationError("Ticket no encontrado.")
        if sha != expected_revision:
            raise TicketConflictError("El ticket cambió en otra sesión. Recarga antes de continuar.")
        saved = upgrade_ticket(ticket)
        saved.pop("_revision", None)
        revision = self._put_file(path, json.dumps(saved, ensure_ascii=False, indent=2).encode("utf-8"), f"catalog: update {ticket['code']}", sha)
        saved["_revision"] = revision
        return saved

    def delete_ticket(self, code, expected_revision):
        path = f"{self.prefix}/tickets/{_safe_name(code)}.json"
        current, sha = self._get_file(path)
        if not current:
            raise TicketValidationError("Ticket no encontrado.")
        if sha != expected_revision:
            raise TicketConflictError("El ticket cambió en otra sesión. Recarga antes de continuar.")
        self._request(
            "DELETE",
            path,
            {
                "message": f"catalog: delete {code}",
                "sha": sha,
                "branch": self.branch,
            },
            ref=False,
        )
        return True

    def put_artifact(self, code, version, kind, filename, payload):
        payload = _payload_bytes(payload)
        if len(payload) > 90 * 1024 * 1024:
            raise TicketValidationError("El archivo supera 90 MB. Configura almacenamiento externo para adjuntos grandes.")
        path = f"{self.prefix}/artifacts/{_safe_name(code)}/v{int(version):03d}_{kind}_{_safe_name(filename)}"
        _, sha = self._get_file(path)
        self._put_file(path, payload, f"catalog: attach {code} v{version}", sha)
        return path

    def get_artifact(self, path):
        raw, _ = self._get_file(normalize_text(path))
        if raw is None:
            raise TicketValidationError("Archivo del ticket no encontrado.")
        return raw


class MockNotificationAdapter:
    """Adaptador por defecto: registra el aviso pero no sale a la red.

    Acepta kwargs extra (estado anterior, responsable, observacion) para que un
    adaptador real como engines.notify.AdaptadorCorreoTickets pueda usarlos sin
    cambiar el punto de llamada.
    """

    def notify(self, ticket, event, recipients=None, message="", **extra):
        return {
            "id": uuid.uuid4().hex,
            "created_at": utc_now(),
            "event": event,
            "recipients": list(recipients or []),
            "message": normalize_text(message),
            "channel": "internal",
            "email_status": "prepared_mock",
            "read_by": [],
            "link": f"ticket:{ticket.get('code', '')}",
        }


class MockJobAdapter:
    def dry_run(self, ticket):
        summary = ticket.get("summary", {})
        return {
            "id": f"DRY-{uuid.uuid4().hex[:12].upper()}",
            "status": "completed",
            "created_at": utc_now(),
            "mode": "mock",
            "new_products": int(summary.get("new_products", 0)),
            "updated_products": int(summary.get("updated_products", 0)),
            "blocked": 0,
            "message": "Simulación local completada. No se llamó a Shopify.",
        }

    def start(self, ticket):
        return {
            "id": f"MOCK-{uuid.uuid4().hex[:12].upper()}",
            "status": "in_progress",
            "created_at": utc_now(),
            "mode": "mock",
            "progress": 0,
            "message": "Carga iniciada. Pendiente de cierre por el equipo de catalogo.",
        }


class TicketService:
    def __init__(self, store, notifier=None, jobs=None, sla_hours=None, operator_users=None,
                 product_area_users=None, brand_recipients=None):
        self.store = store
        self.notifier = notifier or MockNotificationAdapter()
        self.jobs = jobs or MockJobAdapter()
        self.sla_hours = {"low": 120, "normal": 72, "high": 24, "urgent": 8}
        self.sla_hours.update(sla_hours or {})
        self.operator_users = {
            normalize_text(user).casefold()
            for user in (operator_users or [])
            if normalize_text(user)
        }
        # Como saber que correos estan asociados a una marca. Se inyecta porque
        # esa informacion vive en la configuracion de accesos de la app, no en
        # el dominio de solicitudes. Sin resolver, avisa solo al solicitante.
        self.brand_recipients = brand_recipients
        # Area de Producto: quienes reciben el aviso de "toca cargar precios".
        self.product_area_users = sorted({
            normalize_text(user).casefold()
            for user in (product_area_users or [])
            if normalize_text(user)
        })

    @staticmethod
    def actor(user, role, brands=None):
        return _actor(user, role, brands)

    def list_tickets(self, actor, filters=None, search=""):
        filters = filters or {}
        search_key = normalize_key(search)
        result = []
        for ticket in self.store.list_tickets():
            # Canceled records from older releases are tombstones. They must
            # never return to the operational inbox or brand history.
            if internal_state(ticket.get("status")) == STATE_CANCELED:
                continue
            if not can_view_ticket(actor, ticket):
                continue
            if filters.get("brand") and normalize_key(ticket.get("brand")) != normalize_key(filters["brand"]):
                continue
            if filters.get("status") and ticket.get("status") != filters["status"]:
                continue
            if filters.get("priority") and ticket.get("priority") != filters["priority"]:
                continue
            if filters.get("assignee") and ticket.get("assignee") != filters["assignee"]:
                continue
            if filters.get("load_type") and ticket.get("load_type") != filters["load_type"]:
                continue
            if filters.get("site") and normalize_key(filters["site"]) not in {normalize_key(x) for x in ticket.get("sites", [])}:
                continue
            created_date = normalize_text(ticket.get("created_at"))[:10]
            if filters.get("date_from") and created_date < normalize_text(filters["date_from"]):
                continue
            if filters.get("date_to") and created_date > normalize_text(filters["date_to"]):
                continue
            if search_key:
                haystack = " ".join([
                    ticket.get("code", ""), ticket.get("filename", ""), ticket.get("requester", ""),
                    " ".join(ticket.get("model_colors", [])),
                ])
                if search_key not in normalize_key(haystack):
                    continue
            result.append(ticket)
        return result

    def get_ticket(self, actor, code):
        ticket = self.store.get_ticket(code)
        if not ticket or internal_state(ticket.get("status")) == STATE_CANCELED:
            raise TicketValidationError("Ticket no encontrado.")
        if not can_view_ticket(actor, ticket):
            raise TicketPermissionError("No tienes acceso a esta solicitud.")
        return ticket

    def create_ticket(
        self,
        actor,
        *,
        brand,
        sites,
        filename,
        input_bytes,
        report_bytes=b"",
        template_version="1",
        load_type="complete",
        summary=None,
        warnings=None,
        comment="",
        model_colors=None,
        priority="normal",
        requester_name="",
        requested_date="",
    ):
        if actor.get("role") not in {ROLE_BRAND, ROLE_ADMIN}:
            raise TicketPermissionError("Tu rol no puede crear solicitudes Brand.")
        if actor.get("role") == ROLE_BRAND and normalize_key(brand) not in set(actor.get("brands") or []):
            raise TicketPermissionError("La marca del archivo no pertenece a tu cuenta.")
        if priority not in PRIORITIES:
            raise TicketValidationError("Prioridad inválida.")
        summary = dict(summary or {})
        if int(summary.get("products", 0)) <= 0:
            raise TicketValidationError("No existen productos válidos para solicitar la carga.")
        if int(summary.get("blocked", 0)) > 0:
            raise TicketValidationError("El archivo aún tiene errores bloqueantes.")
        normalized_sites = sorted({normalize_text(site) for site in sites if normalize_text(site)})
        if not normalized_sites:
            raise TicketValidationError("Selecciona al menos un sitio con valor SI.")
        digest = file_sha256(input_bytes)
        duplicate_key = file_sha256(f"{normalize_key(brand)}|{template_version}|{digest}".encode("utf-8"))
        nuevos_mod_col = {normalize_key(v) for v in (model_colors or []) if normalize_key(v)}
        abiertos = [
            t for t in self.store.list_tickets()
            if internal_state(t.get("status")) not in {STATE_REJECTED, STATE_CANCELED}
        ]
        for existing in abiertos:
            if existing.get("duplicate_key") == duplicate_key:
                raise TicketConflictError(f"Este archivo ya fue enviado en {existing.get('code')}.")
        # El control por hash solo detecta el MISMO archivo byte a byte: basta con
        # volver a guardar el Excel para esquivarlo. Por eso se compara tambien
        # que productos trae, que es lo que de verdad identifica una solicitud.
        #
        # Solo cuenta contra solicitudes EN CURSO. Si la anterior ya se cargo,
        # reenviar los mismos productos es legitimo: es una actualizacion.
        terminados = {STATE_COMPLETED, STATE_COMPLETED_OBS, STATE_REJECTED, STATE_CANCELED}
        en_curso = [t for t in abiertos if internal_state(t.get("status")) not in terminados]
        if nuevos_mod_col:
            for existing in en_curso:
                if normalize_key(existing.get("brand")) != normalize_key(brand):
                    continue
                previos = {normalize_key(v) for v in (existing.get("model_colors") or []) if normalize_key(v)}
                if not previos:
                    continue
                repetidos = nuevos_mod_col & previos
                if not repetidos:
                    continue
                porcentaje = len(repetidos) * 100 // len(nuevos_mod_col)
                if porcentaje >= 80:
                    muestra = ", ".join(sorted(repetidos)[:5]).upper()
                    etiqueta = STATE_LABELS.get(internal_state(existing.get("status")), "")
                    raise TicketConflictError(
                        f"Esta solicitud repite {porcentaje}% de los productos de {existing.get('code')}"
                        + (f" ({etiqueta})" if etiqueta else "")
                        + f". Repetidos: {muestra}"
                        + (" y otros." if len(repetidos) > 5 else "")
                        + " Si de verdad necesitas cargarlos otra vez, cierra o cancela la solicitud anterior."
                    )
        code = self.store.allocate_code()
        now = utc_now()
        deadline = (datetime.now(timezone.utc) + timedelta(hours=float(self.sla_hours[priority]))).isoformat(timespec="seconds")
        input_path = self.store.put_artifact(code, 1, "input", filename, input_bytes)
        report_path = self.store.put_artifact(code, 1, "validation", "reporte_validacion.xlsx", report_bytes) if report_bytes else ""
        ticket = {
            "schema_version": 2,
            "code": code,
            "created_at": now,
            "updated_at": now,
            "deadline_at": deadline,
            "requester": actor.get("user"),
            "requester_name": normalize_text(requester_name) or actor.get("user", "").split("@")[0].replace(".", " ").title(),
            "requested_date": normalize_text(requested_date) or now[:10],
            "brand": normalize_text(brand),
            "sites": normalized_sites,
            "filename": normalize_text(filename),
            "template_version": normalize_text(template_version) or "1",
            "file_hash": digest,
            "duplicate_key": duplicate_key,
            "load_type": normalize_text(load_type) or "complete",
            "summary": summary,
            "warnings": list(warnings or []),
            "priority": priority,
            "brand_comment": normalize_text(comment),
            "assignee": "",
            "status": STATE_PENDING_ASSIGNMENT,
            "model_colors": sorted({normalize_text(value) for value in (model_colors or []) if normalize_text(value)}),
            "versions": [{
                "number": 1, "created_at": now, "created_by": actor.get("user"), "hash": digest,
                "filename": normalize_text(filename), "input_path": input_path, "report_path": report_path,
                "validation": summary,
            }],
            "comments": [],
            "observations": [],
            "assignment_history": [],
            "events": [],
            "notifications": [],
            "dry_run": {},
            "job": {},
            "result": {},
            "public_result": {},
        }
        self._event(ticket, actor, "request_received", "", STATE_REQUEST_RECEIVED, comment)
        self._event(ticket, actor, "pending_assignment", STATE_REQUEST_RECEIVED, STATE_PENDING_ASSIGNMENT, "")
        recipients = sorted(self.operator_users)
        self._notify(ticket, "new_ticket", recipients=recipients, message=f"Nueva solicitud {code} de {brand}.")
        return self.store.create_ticket(ticket)

    def add_correction_version(self, actor, code, filename, input_bytes, report_bytes, summary, comment=""):
        ticket = self.get_ticket(actor, code)
        if actor.get("role") != ROLE_BRAND or ticket.get("requester") != actor.get("user"):
            raise TicketPermissionError("Solo el Brand solicitante puede adjuntar la corrección.")
        if internal_state(ticket.get("status")) not in {STATE_OBSERVED, STATE_WAITING_BRAND}:
            raise TicketValidationError("Solo se puede corregir una solicitud observada.")
        if int((summary or {}).get("blocked", 0)) > 0:
            raise TicketValidationError("La nueva versión aún contiene bloqueos.")
        if int((summary or {}).get("products", 0)) <= 0:
            raise TicketValidationError("La nueva versión no contiene productos válidos.")
        digest = file_sha256(input_bytes)
        if any(item.get("hash") == digest for item in ticket.get("versions", [])):
            raise TicketConflictError("Esta versión del archivo ya está registrada en el ticket.")
        version = len(ticket.get("versions", [])) + 1
        input_path = self.store.put_artifact(code, version, "input", filename, input_bytes)
        report_path = self.store.put_artifact(code, version, "validation", "reporte_validacion.xlsx", report_bytes) if report_bytes else ""
        ticket.setdefault("versions", []).append({
            "number": version, "created_at": utc_now(), "created_by": actor.get("user"), "hash": digest,
            "filename": filename, "input_path": input_path, "report_path": report_path,
            "validation": dict(summary or {}),
        })
        ticket["filename"] = filename
        ticket["file_hash"] = digest
        ticket["summary"] = dict(summary or {})
        for observation in ticket.get("observations", []):
            if observation.get("status", "open") == "open":
                observation["status"] = "corrected"
                observation["corrected_at"] = utc_now()
                observation["corrected_by"] = actor.get("user")
        saved = self._transition(ticket, actor, STATE_CORRECTION_RECEIVED, comment or "Nueva versión validada")
        return saved

    def assign(self, actor, code, assignee, expected_revision=None, reason=""):
        ticket = self.get_ticket(actor, code)
        if actor.get("role") not in {ROLE_OPERATOR, ROLE_ADMIN}:
            raise TicketPermissionError("Tu rol no puede asignar solicitudes.")
        self._assert_operator_roster(actor)
        assignee = normalize_text(assignee).casefold()
        if not assignee:
            raise TicketValidationError("Selecciona un responsable de carga.")
        if self.operator_users and assignee not in self.operator_users:
            raise TicketPermissionError("El responsable seleccionado no pertenece al equipo de carga.")
        active_states = {
            STATE_PENDING_ASSIGNMENT, STATE_ASSIGNED, STATE_DIGITAL_REVIEW, STATE_OBSERVED,
            STATE_WAITING_BRAND, STATE_CORRECTION_RECEIVED, STATE_LOAD_APPROVED, STATE_PREPARING,
            STATE_DRY_RUN, STATE_READY_EXECUTE, STATE_FAILED,
            STATE_SIAL_LOADED, STATE_PRICE_REQUESTED, STATE_PRICE_VALIDATION,
            STATE_READY_CLOSE,
        }
        if ticket.get("status") not in active_states:
            raise TicketValidationError("La solicitud ya no está disponible para asignación.")
        before = ticket.get("assignee", "")
        ticket["assignee"] = assignee
        previous_status = ticket.get("status")
        if previous_status == STATE_PENDING_ASSIGNMENT:
            ticket["status"] = STATE_ASSIGNED
        assignment = {
            "created_at": utc_now(),
            "changed_by": actor.get("user"),
            "from": before,
            "to": assignee,
            "reason": normalize_text(reason) or ("Asignación inicial" if not before else "Reasignación operativa"),
        }
        ticket.setdefault("assignment_history", []).append(assignment)
        self._event(ticket, actor, "assigned", previous_status, ticket.get("status"), json.dumps(assignment, ensure_ascii=False))
        self._notify(
            ticket, "ticket_assigned", recipients=[ticket["assignee"]],
            message=f"Se asignó {code}.",
            estado_anterior=previous_status,
            estado_nuevo=ticket.get("status"),
            responsable=normalize_text(actor.get("user")),
            observacion=normalize_text(reason),
        )
        # assign() no pasa por _transition: cambia el estado a mano. Sin este
        # aviso la marca no se enteraba de que su solicitud ya tenia
        # responsable, que es justo el primer cambio que le importa.
        if previous_status != ticket.get("status"):
            self._notify(
                ticket, f"status_{ticket.get('status')}",
                message=f"{ticket['code']}: {STATE_LABELS.get(ticket.get('status'), ticket.get('status'))}",
                estado_anterior=previous_status,
                estado_nuevo=ticket.get("status"),
                responsable=normalize_text(actor.get("user")),
                observacion=normalize_text(reason),
            )
        return self._save(ticket, expected_revision)

    def start_review(self, actor, code):
        ticket = self.get_ticket(actor, code)
        if actor.get("role") not in {ROLE_OPERATOR, ROLE_ADMIN}:
            raise TicketPermissionError("Tu rol no puede iniciar revisiones.")
        self._assert_internal_owner(actor, ticket, allow_take_unassigned=True)
        if not ticket.get("assignee"):
            ticket["assignee"] = actor.get("user")
        return self._transition(ticket, actor, STATE_DIGITAL_REVIEW, "Revisión iniciada")

    def request_correction(self, actor, code, comment, observations=None):
        if not normalize_text(comment):
            raise TicketValidationError("Describe la corrección solicitada.")
        ticket = self.get_ticket(actor, code)
        self._assert_internal_owner(actor, ticket)
        prepared = []
        for observation in list(observations or []):
            prepared.append({
                "id": uuid.uuid4().hex,
                "created_at": utc_now(),
                "created_by": actor.get("user"),
                "status": "open",
                **dict(observation or {}),
            })
        ticket.setdefault("observations", []).extend(prepared)
        self._transition(ticket, actor, STATE_OBSERVED, comment)
        ticket = self.get_ticket(actor, code)
        saved = self._transition(ticket, actor, STATE_WAITING_BRAND, "Pendiente de respuesta del Brand")
        return saved

    def approve(self, actor, code, comment=""):
        ticket = self.get_ticket(actor, code)
        if actor.get("user") == ticket.get("requester"):
            raise TicketPermissionError("El solicitante no puede aprobar su propia solicitud.")
        self._assert_internal_owner(actor, ticket)
        return self._transition(ticket, actor, STATE_LOAD_APPROVED, comment or "Validación interna aprobada")

    def reject(self, actor, code, comment):
        if not normalize_text(comment):
            raise TicketValidationError("Indica el motivo del rechazo.")
        ticket = self.get_ticket(actor, code)
        self._assert_internal_owner(actor, ticket)
        return self._transition(ticket, actor, STATE_REJECTED, comment)

    def add_comment(self, actor, code, message, product="", field="", visibility="public", row=""):
        ticket = self.get_ticket(actor, code)
        if not normalize_text(message):
            raise TicketValidationError("El comentario está vacío.")
        visibility = normalize_text(visibility).casefold() or "public"
        if visibility not in {"public", "internal"}:
            raise TicketValidationError("Visibilidad de comentario inválida.")
        if actor.get("role") == ROLE_BRAND and visibility != "public":
            raise TicketPermissionError("El Brand solo puede publicar comentarios visibles.")
        ticket.setdefault("comments", []).append({
            "id": uuid.uuid4().hex, "created_at": utc_now(), "user": actor.get("user"),
            "role": actor.get("role"), "message": normalize_text(message),
            "product": normalize_text(product), "field": normalize_text(field),
            "model_color": normalize_text(product), "row": normalize_text(row),
            "visibility": visibility,
        })
        self._event(ticket, actor, "comment_added", ticket.get("status"), ticket.get("status"), message)
        return self._save(ticket)

    def set_priority(self, actor, code, priority):
        if actor.get("role") not in {ROLE_OPERATOR, ROLE_ADMIN}:
            raise TicketPermissionError("Tu rol no puede cambiar la prioridad.")
        self._assert_operator_roster(actor)
        if priority not in PRIORITIES:
            raise TicketValidationError("Prioridad inválida.")
        ticket = self.get_ticket(actor, code)
        ticket["priority"] = priority
        ticket["deadline_at"] = (datetime.now(timezone.utc) + timedelta(hours=float(self.sla_hours[priority]))).isoformat(timespec="seconds")
        self._event(ticket, actor, "priority_changed", ticket.get("status"), ticket.get("status"), priority)
        return self._save(ticket)

    def run_dry_run(self, actor, code):
        ticket = self.get_ticket(actor, code)
        if actor.get("role") not in {ROLE_OPERATOR, ROLE_ADMIN}:
            raise TicketPermissionError("Tu rol no puede ejecutar simulaciones.")
        if internal_state(ticket.get("status")) not in {STATE_LOAD_APPROVED, STATE_PREPARING, STATE_FAILED}:
            raise TicketValidationError("La solicitud debe estar aprobada antes del dry run.")
        self._assert_internal_owner(actor, ticket)
        if ticket.get("status") == STATE_LOAD_APPROVED:
            ticket = self._transition(ticket, actor, STATE_PREPARING, "Preparando catálogo")
        ticket = self.get_ticket(actor, code)
        ticket = self._transition(ticket, actor, STATE_DRY_RUN, "Iniciando simulación")
        ticket = self.get_ticket(actor, code)
        ticket["dry_run"] = self.jobs.dry_run(ticket)
        self._event(ticket, actor, "dry_run_completed", STATE_DRY_RUN, STATE_READY_EXECUTE, ticket["dry_run"].get("message"))
        ticket["status"] = STATE_READY_EXECUTE
        return self._save(ticket)

    def start_load(self, actor, code):
        ticket = self.get_ticket(actor, code)
        if actor.get("role") not in {ROLE_OPERATOR, ROLE_ADMIN}:
            raise TicketPermissionError("Tu rol no puede iniciar cargas.")
        if internal_state(ticket.get("status")) not in {STATE_READY_EXECUTE, STATE_FAILED, STATE_LOAD_APPROVED}:
            raise TicketValidationError("La solicitud no está lista para cargar.")
        self._assert_internal_owner(actor, ticket)
        if ticket.get("status") in {STATE_READY_EXECUTE, STATE_LOAD_APPROVED} and ticket.get("dry_run", {}).get("status") != "completed":
            raise TicketValidationError("Ejecuta y revisa el dry run antes de iniciar la carga.")
        ticket["job"] = self.jobs.start(ticket)
        return self._transition(ticket, actor, STATE_LOADING, ticket["job"].get("message"))

    # --- cierre de carga por etapas --------------------------------------
    # Carga SIAL -> Carga de precios -> Validacion precio/stock -> Shopify.
    # Cada paso es un metodo con su propia transicion, para que la interfaz
    # solo tenga que ofrecer un boton y no repetir reglas.

    def complete_sial_load(self, actor, code, *, processed=0, model_colors=0, note="",
                           sial_bytes=b"", sial_filename=""):
        """Marca que la carga SIAL termino bien y deja lista la solicitud.

        Guarda cuanto se proceso y, si se le pasa, **el archivo Carga SIAL**.
        El archivo queda como adjunto de la solicitud, no en memoria de la
        sesion: de ahi lo toma request_price_load para mandarselo al Area de
        Producto, y de ahi se puede volver a descargar meses despues.
        """
        if actor.get("role") not in {ROLE_OPERATOR, ROLE_ADMIN}:
            raise TicketPermissionError("Tu rol no puede cerrar la carga SIAL.")
        ticket = self.get_ticket(actor, code)
        self._assert_internal_owner(actor, ticket, allow_take_unassigned=True)
        estado = internal_state(ticket.get("status"))
        if estado not in {STATE_LOADING, STATE_VALIDATING}:
            raise TicketValidationError(
                "La carga SIAL solo se cierra cuando la solicitud está en ejecución."
            )
        resumen = ticket.get("summary") if isinstance(ticket.get("summary"), dict) else {}
        procesados = int(processed or 0) or int(resumen.get("products", 0) or 0)
        modelos = int(model_colors or 0) or len(ticket.get("model_colors") or [])
        contenido = _payload_bytes(sial_bytes) if sial_bytes else b""
        ruta = ""
        nombre = normalize_text(sial_filename) or f"Carga_SIAL_{code}.xlsx"
        if contenido:
            version = len(ticket.get("versions") or []) or 1
            ruta = self.store.put_artifact(code, version, "sial", nombre, contenido)
        ticket["sial"] = {
            "completed_at": utc_now(),
            "completed_by": actor.get("user"),
            "processed": procesados,
            "model_colors": modelos,
            "note": normalize_text(note),
            "filename": nombre if contenido else "",
            "path": ruta,
            "bytes": len(contenido),
        }
        return self._transition(ticket, actor, STATE_SIAL_LOADED,
                                normalize_text(note) or "Carga SIAL finalizada")

    def request_price_load(self, actor, code, note="", recipients=None):
        """Solicita al Area de Producto que cargue los precios.

        Manda dos avisos en la MISMA escritura de la solicitud: uno al Area de
        Producto con el detalle de lo cargado, y el de cambio de estado que
        recibe la marca. Hacerlo en una sola escritura evita un segundo viaje
        al almacenamiento y el conflicto de revision que eso provocaba.
        """
        if actor.get("role") not in {ROLE_OPERATOR, ROLE_ADMIN}:
            raise TicketPermissionError("Tu rol no puede solicitar la carga de precios.")
        ticket = self.get_ticket(actor, code)
        self._assert_internal_owner(actor, ticket, allow_take_unassigned=True)
        if internal_state(ticket.get("status")) != STATE_SIAL_LOADED:
            raise TicketValidationError(
                "Primero hay que cerrar la carga SIAL para poder solicitar los precios."
            )
        destino = sorted({
            normalize_text(item).casefold()
            for item in (recipients if recipients is not None else self.product_area_users)
            if normalize_text(item)
        })
        if not destino:
            raise TicketValidationError(
                "No hay destinatarios del Área de Producto configurados en [notificaciones]."
            )
        sial = ticket.get("sial") if isinstance(ticket.get("sial"), dict) else {}
        resumen = ticket.get("summary") if isinstance(ticket.get("summary"), dict) else {}
        procesados = int(sial.get("processed", 0) or resumen.get("products", 0) or 0)
        modelos = int(sial.get("model_colors", 0) or len(ticket.get("model_colors") or []))
        anterior = ticket.get("status")

        # El archivo Carga SIAL viaja adjunto: el Area de Producto tiene que
        # poder cargar precios sin entrar a la app ni pedirle el Excel a nadie.
        # Si no se pudo leer, el aviso sale igual sin adjunto y diciendo que se
        # descargue desde la solicitud. Quedarse sin avisar seria peor.
        adjuntos = []
        ruta_sial = normalize_text(sial.get("path"))
        if ruta_sial:
            try:
                adjuntos.append({
                    "nombre": normalize_text(sial.get("filename")) or f"Carga_SIAL_{code}.xlsx",
                    "contenido": self.store.get_artifact(ruta_sial),
                })
            except Exception:
                adjuntos = []

        ticket["price_load"] = {
            "requested_at": utc_now(),
            "requested_by": actor.get("user"),
            "recipients": destino,
            "note": normalize_text(note),
            "processed": procesados,
            "model_colors": modelos,
            "attached": bool(adjuntos),
        }
        self._notify(
            ticket, "solicitud_carga_precios",
            recipients=destino,
            message=f"{ticket['code']}: carga SIAL terminada, corresponde cargar precios.",
            estado_anterior=anterior,
            estado_nuevo=STATE_PRICE_REQUESTED,
            responsable=normalize_text(actor.get("user")),
            observacion=normalize_text(note),
            contexto={"productos": procesados, "modelos_color": modelos},
            adjuntos=adjuntos,
        )
        self._event(ticket, actor, "price_load_requested", anterior, STATE_PRICE_REQUESTED,
                    normalize_text(note) or f"Aviso enviado a {', '.join(destino)}")
        return self._transition(
            ticket, actor, STATE_PRICE_REQUESTED,
            normalize_text(note) or "Carga de precios solicitada al Área de Producto",
        )

    def start_price_validation(self, actor, code, note=""):
        """Producto confirma que ya cargo los precios: pasa a validarse."""
        if actor.get("role") not in {ROLE_OPERATOR, ROLE_ADMIN}:
            raise TicketPermissionError("Tu rol no puede confirmar la carga de precios.")
        ticket = self.get_ticket(actor, code)
        self._assert_internal_owner(actor, ticket, allow_take_unassigned=True)
        if internal_state(ticket.get("status")) != STATE_PRICE_REQUESTED:
            raise TicketValidationError("La solicitud no está esperando la carga de precios.")
        ticket["price_load"] = {
            **(ticket.get("price_load") if isinstance(ticket.get("price_load"), dict) else {}),
            "confirmed_at": utc_now(),
            "confirmed_by": actor.get("user"),
        }
        return self._transition(ticket, actor, STATE_PRICE_VALIDATION,
                                normalize_text(note) or "Precios cargados: validando en Shopify")

    def record_price_validation(self, actor, code, *, resultado=None, note=""):
        """Guarda el resultado de validar precio y stock contra Shopify.

        Si no quedan bloqueos, la solicitud pasa a "Lista para cierre". Si los
        hay, se queda donde esta: la validacion no aprueba sola. Cerrar una
        solicitud cuyos precios no llegaron a Shopify es exactamente el error
        que este flujo existe para evitar.
        """
        if actor.get("role") not in {ROLE_OPERATOR, ROLE_ADMIN}:
            raise TicketPermissionError("Tu rol no puede registrar la validación de precio y stock.")
        ticket = self.get_ticket(actor, code)
        self._assert_internal_owner(actor, ticket, allow_take_unassigned=True)
        if internal_state(ticket.get("status")) != STATE_PRICE_VALIDATION:
            raise TicketValidationError("La solicitud no está en validación de precio y stock.")
        resultado = dict(resultado or {})
        bloqueos = int(resultado.get("bloqueos", 0) or 0)
        ticket["price_check"] = {
            "checked_at": utc_now(),
            "checked_by": actor.get("user"),
            "revisados": int(resultado.get("revisados", 0) or 0),
            "conformes": int(resultado.get("conformes", 0) or 0),
            "bloqueos": bloqueos,
            "detalle": normalize_text(resultado.get("detalle")),
            "note": normalize_text(note),
        }
        if bloqueos > 0:
            self._event(ticket, actor, "price_check_failed", ticket.get("status"), ticket.get("status"),
                        normalize_text(note) or f"{bloqueos} modelo-color con precio o stock incorrecto")
            return self._save(ticket)
        return self._transition(ticket, actor, STATE_READY_CLOSE,
                                normalize_text(note) or "Precio y stock validados en Shopify")

    def finalize_request(self, actor, code, note="", observations=False):
        """Cierre manual del ticket. Es el UNICO camino a "Completada".

        Deja quien cerro y cuando, y dispara el correo final a la marca por el
        mismo motor que el resto de avisos.
        """
        if actor.get("role") not in {ROLE_OPERATOR, ROLE_ADMIN}:
            raise TicketPermissionError("Tu rol no puede finalizar solicitudes.")
        ticket = self.get_ticket(actor, code)
        self._assert_internal_owner(actor, ticket, allow_take_unassigned=True)
        if internal_state(ticket.get("status")) != STATE_READY_CLOSE:
            raise TicketValidationError(
                "Solo se puede finalizar una solicitud que esté en «Lista para cierre». "
                "Antes hay que cargar los precios y validarlos en Shopify."
            )
        verificacion = ticket.get("price_check") if isinstance(ticket.get("price_check"), dict) else {}
        resumen = ticket.get("summary") if isinstance(ticket.get("summary"), dict) else {}
        sial = ticket.get("sial") if isinstance(ticket.get("sial"), dict) else {}
        return self.record_job_result(
            actor, code,
            success=True,
            observations=bool(observations),
            result={
                "processed": int(sial.get("processed", 0) or resumen.get("products", 0) or 0),
                "model_colors": int(sial.get("model_colors", 0) or len(ticket.get("model_colors") or [])),
                "errors": 0,
                "message": normalize_text(note) or "Carga completada: precios cargados y validados en Shopify.",
                "closed_by": actor.get("user"),
                "closed_at": utc_now(),
                "price_check": verificacion,
            },
        )

    def record_job_result(self, actor, code, *, success, observations=False, result=None, error=""):
        if actor.get("role") not in {ROLE_SYSTEM, ROLE_OPERATOR, ROLE_ADMIN}:
            raise TicketPermissionError("Tu rol no puede cerrar una carga.")
        if actor.get("role") == ROLE_SYSTEM:
            ticket = self.get_ticket(self.actor(actor.get("user"), ROLE_ADMIN), code)
        else:
            self._assert_operator_roster(actor)
            ticket = self.get_ticket(actor, code)
            self._assert_internal_owner(actor, ticket)
        if ticket.get("status") == STATE_LOADING:
            ticket = self._transition(ticket, {**actor, "role": ROLE_SYSTEM}, STATE_VALIDATING, "Validando resultado del job")
        target = STATE_COMPLETED_OBS if success and observations else STATE_COMPLETED if success else STATE_FAILED
        ticket["result"] = dict(result or {})
        ticket["public_result"] = {
            "status": "Completada con observaciones" if success and observations else "Completada" if success else "Requiere atención",
            "processed": int(ticket["result"].get("processed", ticket.get("summary", {}).get("products", 0)) or 0),
            "errors": int(ticket["result"].get("errors", 0) or 0),
            "message": normalize_text(ticket["result"].get("message")) or ("Carga finalizada." if success else "El equipo revisará la incidencia."),
        }
        if error:
            ticket["result"]["error"] = normalize_text(error)
        return self._transition(ticket, {**actor, "role": ROLE_SYSTEM}, target, error or "Job finalizado")

    def mark_notification_read(self, actor, code, notification_id):
        ticket = self.get_ticket(actor, code)
        changed = False
        for notification in ticket.get("notifications", []):
            if notification.get("id") == notification_id and actor.get("user") in notification.get("recipients", []):
                readers = set(notification.get("read_by", []))
                readers.add(actor.get("user"))
                notification["read_by"] = sorted(readers)
                changed = True
        return self._save(ticket) if changed else ticket

    def mark_all_notifications_read(self, actor, code):
        ticket = self.get_ticket(actor, code)
        changed = False
        for notification in ticket.get("notifications", []):
            if actor.get("user") in notification.get("recipients", []):
                readers = set(notification.get("read_by", []))
                if actor.get("user") not in readers:
                    readers.add(actor.get("user"))
                    notification["read_by"] = sorted(readers)
                    changed = True
        return self._save(ticket) if changed else ticket

    def cancel_ticket(self, actor, code, comment):
        if actor.get("role") not in {ROLE_OPERATOR, ROLE_ADMIN}:
            raise TicketPermissionError("Tu rol no puede eliminar solicitudes.")
        self._assert_operator_roster(actor)
        if not normalize_text(comment):
            raise TicketValidationError("Indica el motivo de la eliminación.")
        ticket = self.get_ticket(actor, code)
        self._event(
            ticket,
            actor,
            "ticket_deleted",
            ticket.get("status"),
            "",
            f"Solicitud eliminada por Operaciones: {normalize_text(comment)}",
        )
        self.store.delete_ticket(ticket["code"], ticket.get("_revision"))
        return {"code": ticket["code"], "deleted": True}

    def change_state(self, actor, code, target, comment=""):
        ticket = self.get_ticket(actor, code)
        return self._transition(ticket, actor, target, comment)

    def _transition(self, ticket, actor, target, detail=""):
        current = ticket.get("status")
        allowed = TRANSITIONS.get(actor.get("role"), {}).get(current, set())
        if target not in allowed:
            raise TicketPermissionError(
                f"Transición no permitida para {actor.get('role')}: {STATE_LABELS.get(current, current)} -> {STATE_LABELS.get(target, target)}."
            )
        ticket["status"] = target
        if target == STATE_REVIEW and not ticket.get("review_started_at"):
            ticket["review_started_at"] = utc_now()
        if target == STATE_LOADING:
            ticket["load_started_at"] = utc_now()
        if target in {STATE_COMPLETED, STATE_COMPLETED_OBS, STATE_FAILED, STATE_REJECTED, STATE_CANCELED}:
            ticket["resolved_at"] = utc_now()
        self._event(ticket, actor, "status_changed", current, target, detail)
        # El cierre tiene su propio correo. Da igual por que camino se llegue:
        # asi la marca siempre recibe el mismo aviso final.
        evento = ("solicitud_completada"
                  if target in {STATE_COMPLETED, STATE_COMPLETED_OBS}
                  else f"status_{target}")
        self._notify(
            ticket, evento,
            message=f"{ticket['code']}: {STATE_LABELS.get(target, target)}",
            estado_anterior=current,
            estado_nuevo=target,
            responsable=normalize_text(actor.get("user")),
            observacion=normalize_text(detail),
        )
        return self._save(ticket)

    def _save(self, ticket, expected_revision=None, intentos=3):
        """Guarda el ticket reintentando si la revision quedo desfasada.

        Con el backend de GitHub la revision es el SHA del archivo, y la API de
        contenidos es eventualmente consistente: una lectura hecha justo
        despues de una escritura puede devolver el SHA anterior. Como una sola
        accion encadena varias escrituras, la ultima salia con un SHA viejo y
        el ticket quedaba trabado con "cambio en otra sesion" sin que nadie mas
        lo hubiera tocado.

        Al reintentar se relee la revision vigente y se vuelve a guardar este
        contenido. Es "gana el ultimo": correcto para el caso real, donde el
        conflicto es contra una escritura propia anterior.
        """
        revision = expected_revision if expected_revision is not None else ticket.get("_revision")
        ticket["updated_at"] = utc_now()
        ultimo_error = None
        for intento in range(1, max(1, int(intentos)) + 1):
            try:
                return self.store.update_ticket(ticket, revision)
            except TicketConflictError as exc:
                ultimo_error = exc
                if intento >= intentos:
                    break
                time.sleep(0.4 * intento)
                try:
                    vigente = self.store.get_ticket(ticket["code"])
                except Exception:
                    break
                if not vigente:
                    break
                revision = vigente.get("_revision")
                ticket["updated_at"] = utc_now()
        raise ultimo_error

    def set_status_manual(self, actor, code, target, note=""):
        """Cambia el estado a mano, sin pasar por la maquina de transiciones.

        Sirve cuando la carga ya se ejecuto de verdad pero el ticket quedo
        atrasado: los botones de cierre solo aparecen en loading/validating, asi
        que sin esto no habia forma de finalizarlo. Queda registrado en el
        historial como cambio manual, con quien lo hizo y por que.
        """
        if actor.get("role") not in {ROLE_OPERATOR, ROLE_ADMIN}:
            raise TicketPermissionError("Tu rol no puede cambiar el estado a mano.")
        target = internal_state(target)
        if target not in STATE_LABELS:
            raise TicketValidationError(f"Estado desconocido: {target}")
        ticket = self.get_ticket(actor, code)
        self._assert_internal_owner(actor, ticket, allow_take_unassigned=True)
        anterior = ticket.get("status")
        if anterior == target:
            return ticket
        ticket["status"] = target
        if target == STATE_LOADING and not ticket.get("load_started_at"):
            ticket["load_started_at"] = utc_now()
        if target in {STATE_COMPLETED, STATE_COMPLETED_OBS, STATE_FAILED, STATE_REJECTED, STATE_CANCELED}:
            ticket["resolved_at"] = utc_now()
        detalle = normalize_text(note) or "Cambio manual de estado"
        self._event(ticket, actor, "status_changed_manual", anterior, target, detalle)
        self._notify(
            ticket, f"status_{target}",
            message=f"{ticket['code']}: {STATE_LABELS.get(target, target)}",
            estado_anterior=anterior,
            estado_nuevo=target,
            responsable=normalize_text(actor.get("user")),
            observacion=detalle,
        )
        return self._save(ticket)

    @staticmethod
    def _event(ticket, actor, action, from_state, to_state, detail=""):
        ticket.setdefault("events", []).append({
            "id": uuid.uuid4().hex,
            "created_at": utc_now(),
            "user": actor.get("user"),
            "role": actor.get("role"),
            "action": action,
            "from_state": from_state,
            "to_state": to_state,
            "detail": normalize_text(detail),
        })

    def _notify(self, ticket, event, recipients=None, message="", **extra):
        """Punto unico de aviso. El adaptador decide si sale un correo.

        Se le pasa el estado anterior y quien ejecuta la accion porque el
        correo tiene que decir "de que estado a que estado y por obra de
        quien". Sin esto, cada pantalla tendria que armar su propio mensaje.

        Nunca lanza: un fallo de notificacion no puede deshacer un cambio de
        estado que ya se aplico.
        """
        if recipients is None:
            recipients = [ticket.get("requester"), ticket.get("assignee")]
            recipients += self._brand_users(ticket.get("brand"))
        recipients = sorted({normalize_text(item).casefold() for item in recipients if normalize_text(item)})
        try:
            registro = self.notifier.notify(ticket, event, recipients, message, **extra)
        except TypeError:
            # Adaptador antiguo, sin kwargs. Se llama con la firma historica.
            registro = self.notifier.notify(ticket, event, recipients, message)
        except Exception:
            return
        if registro:
            ticket.setdefault("notifications", []).append(registro)

    def _brand_users(self, brand):
        """Correos asociados a la marca. Nunca lanza: sin resolver, lista vacia."""
        if not self.brand_recipients or not normalize_text(brand):
            return []
        try:
            return [normalize_text(item) for item in (self.brand_recipients(brand) or [])
                    if normalize_text(item)]
        except Exception:
            return []

    def _assert_operator_roster(self, actor):
        user = normalize_text(actor.get("user")).casefold()
        if self.operator_users and user not in self.operator_users:
            raise TicketPermissionError("Solo los responsables de carga autorizados pueden gestionar solicitudes.")

    def _assert_internal_owner(self, actor, ticket, allow_take_unassigned=False):
        if actor.get("role") not in {ROLE_OPERATOR, ROLE_ADMIN}:
            raise TicketPermissionError("Tu rol no puede ejecutar esta acción interna.")
        self._assert_operator_roster(actor)
        if actor.get("role") == ROLE_ADMIN:
            return
        assignee = normalize_text(ticket.get("assignee")).casefold()
        if not assignee and allow_take_unassigned:
            return
        if not assignee:
            raise TicketValidationError("Asígnate la solicitud antes de continuar.")
        if assignee != actor.get("user"):
            raise TicketConflictError("La solicitud está asignada a otro operador.")


def ticket_is_overdue(ticket, now=None):
    if ticket.get("status") in {STATE_COMPLETED, STATE_COMPLETED_OBS, STATE_REJECTED, STATE_CANCELED}:
        return False
    try:
        deadline = datetime.fromisoformat(ticket.get("deadline_at", "").replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return False
    return (now or datetime.now(timezone.utc)) > deadline


def ticket_age_hours(ticket, now=None):
    try:
        created = datetime.fromisoformat(ticket.get("created_at", "").replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return 0.0
    return max(0.0, ((now or datetime.now(timezone.utc)) - created).total_seconds() / 3600)
