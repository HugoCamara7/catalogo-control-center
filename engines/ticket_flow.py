"""Motor de flujo simplificado de solicitudes.

Sin dependencias de Streamlit.

Que hace
--------
1. Traduce los 19 estados internos de ticket_system a 4 estados visibles.
2. Dice que acciones puede ejecutar cada rol en cada estado.

Que NO hace
-----------
No toca la maquina de estados ni los permisos de ticket_system. Los 19 estados
siguen existiendo en el almacenamiento: las solicitudes historicas se leen sin
migracion y sin perder informacion. Esto es una capa de presentacion.

Los estados terminales negativos (rechazada, cancelada) se muestran como
"Finalizada" con un matiz, y "fallida" como "Observada", porque en ambos casos
lo que el usuario necesita saber es si el caso sigue abierto o no.
"""

# --- estados internos (mismos literales que ticket_system) ---------------
DRAFT = "draft"
REQUEST_RECEIVED = "request_received"
PENDING_ASSIGNMENT = "pending_assignment"
ASSIGNED = "assigned"
DIGITAL_REVIEW = "digital_review"
OBSERVED = "observed"
WAITING_BRAND = "waiting_brand_correction"
CORRECTION_RECEIVED = "correction_received"
LOAD_APPROVED = "load_approved"
PREPARING = "preparing_catalog"
DRY_RUN = "dry_run"
READY_EXECUTE = "ready_execute"
LOADING = "loading"
VALIDATING = "validating_results"
COMPLETED = "completed"
COMPLETED_OBS = "completed_with_observations"
FAILED = "failed"
REJECTED = "rejected"
CANCELED = "canceled"

# --- estados visibles ----------------------------------------------------
PENDIENTE = "pendiente_revision"
LISTA = "lista_ejecutar"
EJECUCION = "en_ejecucion"
FINALIZADA = "finalizada"
OBSERVADA = "observada"

ETIQUETAS = {
    PENDIENTE: "Pendiente de revisión",
    LISTA: "Lista para ejecutar",
    EJECUCION: "En ejecución",
    FINALIZADA: "Finalizada",
    OBSERVADA: "Observada",
}

TONOS = {
    PENDIENTE: "amber",
    LISTA: "blue",
    EJECUCION: "blue",
    FINALIZADA: "green",
    OBSERVADA: "red",
}

ORDEN = [PENDIENTE, LISTA, EJECUCION, FINALIZADA]

# Todo estado interno tiene que estar aqui. El test lo verifica.
MAPA = {
    DRAFT: PENDIENTE,
    REQUEST_RECEIVED: PENDIENTE,
    PENDING_ASSIGNMENT: PENDIENTE,
    ASSIGNED: PENDIENTE,
    DIGITAL_REVIEW: PENDIENTE,
    CORRECTION_RECEIVED: PENDIENTE,
    OBSERVED: OBSERVADA,
    WAITING_BRAND: OBSERVADA,
    FAILED: OBSERVADA,
    LOAD_APPROVED: LISTA,
    PREPARING: LISTA,
    DRY_RUN: LISTA,
    READY_EXECUTE: LISTA,
    LOADING: EJECUCION,
    VALIDATING: EJECUCION,
    COMPLETED: FINALIZADA,
    COMPLETED_OBS: FINALIZADA,
    REJECTED: FINALIZADA,
    CANCELED: FINALIZADA,
}

# Matiz que se conserva para no perder informacion al agrupar.
MATICES = {
    COMPLETED_OBS: "con observaciones",
    REJECTED: "rechazada",
    CANCELED: "cancelada",
    FAILED: "con incidencia",
    WAITING_BRAND: "esperando corrección",
}

TERMINALES = {COMPLETED, COMPLETED_OBS, REJECTED, CANCELED}


def _texto(valor):
    return "" if valor is None else str(valor).strip()


def estado_visible(estado_interno):
    return MAPA.get(_texto(estado_interno), PENDIENTE)


def etiqueta(estado_interno):
    """Etiqueta lista para mostrar, con matiz si lo hay."""
    visible = estado_visible(estado_interno)
    base = ETIQUETAS[visible]
    matiz = MATICES.get(_texto(estado_interno))
    return f"{base} ({matiz})" if matiz else base


def tono(estado_interno):
    return TONOS[estado_visible(estado_interno)]


def paso_actual(estado_interno):
    """Posicion en la barra de progreso de 4 pasos (1..4). Observada no avanza."""
    visible = estado_visible(estado_interno)
    if visible == OBSERVADA:
        return 1
    return ORDEN.index(visible) + 1


def es_terminal(estado_interno):
    return _texto(estado_interno) in TERMINALES


# --- acciones contextuales ----------------------------------------------
# metodo -> el de TicketService. pide_comentario -> exige texto antes de ejecutar.
ACCIONES = [
    {
        "clave": "tomar",
        "etiqueta": "Tomar solicitud",
        "metodo": "assign",
        "ayuda": "Te asigna la solicitud y la pasa a revisión.",
        "roles": {"operator", "admin"},
        "estados": {PENDING_ASSIGNMENT, REQUEST_RECEIVED, DRAFT},
        "principal": True,
    },
    {
        "clave": "revisar",
        "etiqueta": "Iniciar revisión",
        "metodo": "start_review",
        "ayuda": "Marca que estás revisando el archivo.",
        "roles": {"operator", "admin"},
        "estados": {ASSIGNED, CORRECTION_RECEIVED},
        "principal": True,
    },
    {
        "clave": "observar",
        "etiqueta": "Observar",
        "metodo": "request_correction",
        "ayuda": "Devuelve la solicitud a la marca para que corrija.",
        "roles": {"operator", "admin"},
        "estados": {DIGITAL_REVIEW, ASSIGNED, CORRECTION_RECEIVED},
        "pide_comentario": True,
    },
    {
        # Desde CORRECTION_RECEIVED no se aprueba directo: primero hay que
        # revisar la version corregida. Asi cada estado tiene una sola
        # accion principal y el recorrido es lineal.
        "clave": "aprobar",
        "etiqueta": "Aprobar para carga",
        "metodo": "approve",
        "ayuda": "Deja la solicitud lista para ejecutar.",
        "roles": {"operator", "admin"},
        "estados": {DIGITAL_REVIEW},
        "principal": True,
    },
    {
        "clave": "ejecutar",
        "etiqueta": "Ejecutar carga",
        "metodo": "start_load",
        "ayuda": "Inicia la carga del catálogo en Shopify.",
        "roles": {"operator", "admin"},
        "estados": {LOAD_APPROVED, READY_EXECUTE, DRY_RUN, PREPARING},
        "principal": True,
    },
    {
        "clave": "finalizar",
        "etiqueta": "Finalizar solicitud",
        "metodo": "record_job_result",
        "ayuda": "Registra el resultado y cierra la solicitud.",
        "roles": {"operator", "admin"},
        "estados": {LOADING, VALIDATING},
        "principal": True,
    },
    {
        "clave": "reabrir",
        "etiqueta": "Reabrir",
        "metodo": "change_state",
        "destino": DIGITAL_REVIEW,
        "ayuda": "Vuelve a abrir una solicitud cerrada.",
        "roles": {"admin"},
        "estados": TERMINALES | {FAILED},
        "pide_comentario": True,
    },
    {
        "clave": "corregir",
        "etiqueta": "Enviar corrección",
        "metodo": "add_correction_version",
        "ayuda": "Sube una versión corregida del archivo.",
        "roles": {"brand"},
        "estados": {OBSERVED, WAITING_BRAND},
        "principal": True,
        "requiere_archivo": True,
    },
    {
        "clave": "cancelar",
        "etiqueta": "Cancelar solicitud",
        "metodo": "cancel_ticket",
        "ayuda": "Cancela la solicitud. No se puede deshacer.",
        "roles": {"admin"},
        "estados": set(MAPA) - TERMINALES,
        "pide_comentario": True,
        "destructiva": True,
    },
]


def acciones_disponibles(estado_interno, rol, asignada_a="", usuario=""):
    """Acciones que este rol puede ejecutar en este estado.

    Devuelve la lista en orden: primero la principal, despues el resto.
    Si no hay ninguna, la interfaz no debe mostrar botones de accion.
    """
    estado = _texto(estado_interno)
    rol = _texto(rol).casefold()
    salida = []
    for accion in ACCIONES:
        if rol not in accion["roles"]:
            continue
        if estado not in accion["estados"]:
            continue
        item = dict(accion)
        # "Tomar" no aplica si ya esta asignada a esta misma persona
        if accion["clave"] == "tomar" and _texto(asignada_a).casefold() == _texto(usuario).casefold() != "":
            continue
        salida.append(item)
    salida.sort(key=lambda a: (not a.get("principal"), a["etiqueta"]))
    return salida


def accion_principal(estado_interno, rol, asignada_a="", usuario=""):
    """La siguiente accion esperable, o None."""
    disponibles = acciones_disponibles(estado_interno, rol, asignada_a, usuario)
    for accion in disponibles:
        if accion.get("principal"):
            return accion
    return disponibles[0] if disponibles else None


def resumen_estados(estados):
    """Conteo por estado visible, para los KPIs."""
    conteo = {clave: 0 for clave in ETIQUETAS}
    for estado in estados:
        conteo[estado_visible(estado)] += 1
    return conteo
