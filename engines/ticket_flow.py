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
SIAL_LOADED = "sial_loaded"
PRICE_REQUESTED = "price_load_requested"
PRICE_VALIDATION = "price_stock_validation"
READY_CLOSE = "ready_to_close"
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
    # El cierre por etapas (SIAL, precios, validacion) sigue siendo "En
    # ejecucion" para quien mira desde fuera: la solicitud no esta cerrada.
    # El matiz dice en que paso concreto va.
    SIAL_LOADED: EJECUCION,
    PRICE_REQUESTED: EJECUCION,
    PRICE_VALIDATION: EJECUCION,
    READY_CLOSE: EJECUCION,
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
    SIAL_LOADED: "carga SIAL lista",
    PRICE_REQUESTED: "esperando carga de precios",
    PRICE_VALIDATION: "validando precio y stock",
    READY_CLOSE: "lista para cierre",
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
        "queda_en": ASSIGNED,
        "ayuda": "Te asigna la solicitud y la pasa a revisión.",
        "roles": {"operator", "admin"},
        # Solo PENDING_ASSIGNMENT. `assign()` rechaza DRAFT y REQUEST_RECEIVED
        # ("La solicitud ya no esta disponible para asignacion") y TRANSITIONS
        # no tiene entrada de operador para ninguno de los dos: el boton se
        # dibujaba y fallaba siempre. Un boton que no puede funcionar es peor
        # que no tener boton.
        "estados": {PENDING_ASSIGNMENT},
        "principal": True,
    },
    {
        "clave": "revisar",
        "etiqueta": "Iniciar revisión",
        "metodo": "start_review",
        "queda_en": DIGITAL_REVIEW,
        "ayuda": "Marca que estás revisando el archivo.",
        "roles": {"operator", "admin"},
        "estados": {ASSIGNED, CORRECTION_RECEIVED},
        "principal": True,
    },
    {
        "clave": "observar",
        "etiqueta": "Observar",
        "metodo": "request_correction",
        "queda_en": OBSERVED,
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
        "queda_en": LOAD_APPROVED,
        "ayuda": "Deja la solicitud lista para ejecutar.",
        "roles": {"operator", "admin"},
        "estados": {DIGITAL_REVIEW},
        "principal": True,
    },
    {
        # La validacion previa (dry run) es OBLIGATORIA antes de cargar:
        # `start_load` la exige y revienta sin ella. Vivia solo en el panel de
        # "Cargas pendientes" de Carga completa, asi que "Ejecutar carga"
        # fallaba SIEMPRE desde "Lista para ejecutar" con "Ejecuta y revisa el
        # dry run antes de iniciar la carga". Aqui esta como accion del flujo
        # para que el atajo `ejecutar_carga` la pueda encadenar.
        "clave": "validacion_previa",
        "etiqueta": "Ejecutar validación previa",
        "metodo": "run_dry_run",
        "queda_en": READY_EXECUTE,
        "ayuda": "Simula la carga y la deja lista para ejecutar. Obligatoria antes de cargar.",
        "roles": {"operator", "admin"},
        "estados": {LOAD_APPROVED, PREPARING, FAILED},
    },
    {
        "clave": "ejecutar",
        "etiqueta": "Ejecutar carga",
        "metodo": "start_load",
        "queda_en": LOADING,
        "ayuda": "Inicia la carga del catálogo en Shopify.",
        "roles": {"operator", "admin"},
        "estados": {LOAD_APPROVED, READY_EXECUTE, DRY_RUN, PREPARING},
        "principal": True,
    },
    {
        "clave": "finalizar",
        "etiqueta": "Completar carga",
        "metodo": "record_job_result",
        "queda_en": COMPLETED,
        "ayuda": "Cierra la carga. Es manual: no depende de cuántos productos procesó el job.",
        "roles": {"operator", "admin"},
        "estados": {LOADING, VALIDATING},
        "principal": True,
    },
    {
        # El UNICO camino a "Completada" dentro de la cadena de cierre. No
        # aparece antes de "Lista para cierre" a proposito: cerrar con la carga
        # SIAL recien hecha, sin precios, era el error a corregir.
        "clave": "finalizar_solicitud",
        "etiqueta": "Finalizar solicitud",
        "metodo": "finalize_request",
        "queda_en": COMPLETED,
        "ayuda": "Precios cargados y validados: cierra la solicitud como completada.",
        "roles": {"operator", "admin"},
        "estados": {READY_CLOSE},
        "principal": True,
    },
    # Cierre por etapas. "Carga SIAL terminada" queda como accion secundaria en
    # ejecucion: el recorrido corto (cargar y finalizar) sigue siendo el
    # principal para quien no usa la cadena completa.
    {
        "clave": "sial_ok",
        "etiqueta": "Carga SIAL terminada",
        "metodo": "complete_sial_load",
        "queda_en": SIAL_LOADED,
        "ayuda": "Marca que la carga SIAL terminó correctamente.",
        "roles": {"operator", "admin"},
        "estados": {LOADING, VALIDATING},
    },
    {
        "clave": "solicitar_precios",
        "etiqueta": "Notificar a Producto",
        "metodo": "request_price_load",
        "queda_en": PRICE_REQUESTED,
        "ayuda": "Avisa al Área de Producto que ya puede cargar los precios.",
        "roles": {"operator", "admin"},
        "estados": {SIAL_LOADED},
        "principal": True,
    },
    {
        "clave": "validar_precio_stock",
        "etiqueta": "Precios cargados",
        "metodo": "start_price_validation",
        "queda_en": PRICE_VALIDATION,
        "ayuda": "Producto ya cargó los precios: pasa a validarlos en Shopify.",
        "roles": {"operator", "admin"},
        "estados": {PRICE_REQUESTED},
        "principal": True,
    },
    {
        "clave": "revalidar_shopify",
        "etiqueta": "Volver a sincronizar",
        "metodo": "change_state",
        "destino": LOADING,
        "ayuda": "Si la validación encontró diferencias, vuelve a cargar en Shopify.",
        "roles": {"operator", "admin"},
        "estados": {PRICE_VALIDATION, READY_CLOSE},
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
        "queda_en": CORRECTION_RECEIVED,
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
        "queda_en": CANCELED,
        "ayuda": "Cancela la solicitud. No se puede deshacer.",
        "roles": {"admin"},
        "estados": set(MAPA) - TERMINALES,
        "pide_comentario": True,
        "destructiva": True,
    },
]


ACCION_POR_CLAVE = {accion["clave"]: accion for accion in ACCIONES}


def destino_de(accion):
    """En que estado deja la solicitud esta accion.

    `queda_en` para las acciones con un metodo propio; `destino` para las que
    usan `change_state`. Hay una prueba que compara estos destinos contra la
    tabla TRANSITIONS de ticket_system, para que los dos no se separen.
    """
    accion = accion or {}
    return _texto(accion.get("queda_en") or accion.get("destino"))


# --- atajos: varias acciones del flujo en un solo boton ------------------
# Por que existen: llegar de "recien llegada" a "lista para ejecutar" pedia
# TRES clics en tres pantallas (Tomar solicitud, Iniciar revision, Aprobar para
# carga), y ninguno de los tres es una decision distinta: quien toma la
# solicitud para revisarla ya decidio revisarla. El atajo las ejecuta en orden
# y para en la primera que falle.
#
# Lo que NO se atajo, a proposito: la cadena de cierre (SIAL -> precios ->
# validacion -> cierre). Ahi cada paso SI espera algo real -- que el Area de
# Producto cargue los precios, que la validacion contra Shopify no traiga
# bloqueos -- y saltarselos es exactamente el error que se corrigio en agosto
# de 2026. Ademas "Carga SIAL terminada" necesita el archivo SIAL, que solo
# tiene la pantalla: encadenarla desde aqui mandaria el correo al Area de
# Producto SIN adjunto.
ATAJOS = [
    {
        "clave": "aceptar_carga",
        "etiqueta": "Aceptar carga",
        "ayuda": "Toma la solicitud, la marca como revisada y la deja lista para ejecutar.",
        "roles": {"operator", "admin"},
        "hasta": LOAD_APPROVED,
        "pasos": ("tomar", "revisar", "aprobar"),
        # Al terminar, la pantalla lleva sola a la Carga completa: aceptar una
        # carga y no poder ejecutarla sin buscar el menu no tiene sentido.
        "va_a": "carga_completa",
        "principal": True,
        "reemplaza": ("tomar", "revisar", "aprobar"),
    },
    {
        # Conserva el nombre del boton que ya existia, porque el problema no
        # era el nombre: era que "Ejecutar carga" desde "Lista para ejecutar"
        # fallaba siempre por la validacion previa que faltaba.
        "clave": "ejecutar_carga",
        "etiqueta": "Ejecutar carga",
        "ayuda": "Corre la validación previa y arranca la carga del catálogo.",
        "roles": {"operator", "admin"},
        "hasta": LOADING,
        "pasos": ("validacion_previa", "ejecutar"),
        "principal": True,
        "reemplaza": ("validacion_previa", "ejecutar"),
    },
]

ATAJO_POR_CLAVE = {atajo["clave"]: atajo for atajo in ATAJOS}


def pasos_del_atajo(clave, estado_interno, rol, asignada_a="", usuario=""):
    """Las acciones a ejecutar, en orden, para completar el atajo.

    Se recorre `pasos` simulando el estado tras cada accion, asi que desde un
    estado intermedio devuelve solo lo que falta: desde "En revision digital"
    es un solo paso, desde "Pendiente de asignacion" son tres.

    Devuelve [] si desde este estado y con este rol el atajo no llega a
    `hasta`. Una lista vacia significa "no ofrezcas el boton", nunca "el atajo
    no hace nada".
    """
    atajo = ATAJO_POR_CLAVE.get(_texto(clave))
    if not atajo:
        return []
    rol = _texto(rol).casefold()
    if rol not in atajo["roles"]:
        return []
    actual = _texto(estado_interno)
    pasos = []
    for clave_paso in atajo["pasos"]:
        accion = ACCION_POR_CLAVE.get(clave_paso)
        if not accion or rol not in accion["roles"]:
            continue
        if actual not in accion["estados"]:
            # Ya paso esta etapa (o no aplica desde aqui): se salta.
            continue
        if accion.get("pide_comentario") or accion.get("requiere_archivo"):
            # Un atajo no puede pedir texto ni archivo a mitad de camino.
            return []
        pasos.append(accion)
        actual = destino_de(accion)
        if actual == atajo["hasta"]:
            break
    return pasos if actual == atajo["hasta"] else []


def atajos_disponibles(estado_interno, rol, asignada_a="", usuario=""):
    """Atajos ofrecibles ahora, ya con sus pasos resueltos.

    Solo se ofrece el atajo cuando ahorra al menos un clic: con un unico paso
    pendiente la accion normal ya dice lo mismo, y dos botones para lo mismo
    con nombres distintos confunden mas de lo que ayudan.
    """
    salida = []
    for atajo in ATAJOS:
        pasos = pasos_del_atajo(atajo["clave"], estado_interno, rol, asignada_a, usuario)
        if len(pasos) < 2:
            continue
        item = dict(atajo)
        item["pasos_resueltos"] = pasos
        salida.append(item)
    return salida


def claves_reemplazadas(estado_interno, rol, asignada_a="", usuario=""):
    """Acciones que la interfaz NO debe dibujar porque un atajo ya las cubre.

    Sin esto quedan dos botones para lo mismo -- "Aceptar carga" al lado de
    "Tomar solicitud" -- y el usuario no puede saber cual usar.
    """
    claves = set()
    for atajo in atajos_disponibles(estado_interno, rol, asignada_a, usuario):
        claves |= set(atajo.get("reemplaza") or ())
    return claves


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


# --- seguimiento visual de la carga --------------------------------------
# Las seis etapas que ve el usuario, en orden. Se devuelven como DATOS: la
# pantalla solo las dibuja. Sin porcentajes: lo unico que hace falta saber es
# en que etapa se esta y que falta.
ETAPAS_CARGA = [
    {"clave": "procesando", "titulo": "Procesando catálogo",
     "detalle": "Se está generando el catálogo.",
     "estados": {LOAD_APPROVED, PREPARING, DRY_RUN, READY_EXECUTE, LOADING, VALIDATING}},
    {"clave": "sial", "titulo": "Carga SIAL realizada",
     "detalle": "SIAL cargado · Esperando carga de precios.",
     "estados": {SIAL_LOADED}},
    {"clave": "precios", "titulo": "Pendiente carga de precios",
     "detalle": "Producto tiene el archivo y está cargando los precios.",
     "estados": {PRICE_REQUESTED}},
    {"clave": "validacion", "titulo": "Validando precio/stock en Shopify",
     "detalle": "Se comprueba que los precios llegaron correctamente.",
     "estados": {PRICE_VALIDATION}},
    {"clave": "cierre", "titulo": "Lista para cierre",
     "detalle": "Todo validado. Falta el cierre del responsable.",
     "estados": {READY_CLOSE}},
    {"clave": "completada", "titulo": "Completada",
     "detalle": "La carga terminó correctamente.",
     "estados": {COMPLETED, COMPLETED_OBS}},
]

_ETAPA_POR_ESTADO = {
    estado: indice
    for indice, etapa in enumerate(ETAPAS_CARGA)
    for estado in etapa["estados"]
}


def etapa_indice(estado_interno):
    """Posicion en la cadena de 6 etapas. -1 si la solicitud aun no llego."""
    return _ETAPA_POR_ESTADO.get(_texto(estado_interno), -1)


def seguimiento_carga(estado_interno):
    """Las 6 etapas con su situacion, listas para dibujar.

    situacion: "hecha" | "actual" | "pendiente". Con la solicitud detenida
    (observada, fallida, rechazada) ninguna etapa queda como actual y se marca
    'detenida', para no dar a entender que sigue avanzando.
    """
    estado = _texto(estado_interno)
    actual = etapa_indice(estado)
    detenida = estado in {OBSERVED, WAITING_BRAND, FAILED, REJECTED, CANCELED}
    etapas = []
    for indice, etapa in enumerate(ETAPAS_CARGA):
        if actual < 0:
            situacion = "pendiente"
        elif indice < actual:
            situacion = "hecha"
        elif indice == actual:
            situacion = "actual"
        else:
            situacion = "pendiente"
        etapas.append({
            "clave": etapa["clave"],
            "titulo": etapa["titulo"],
            "detalle": etapa["detalle"],
            "situacion": situacion,
            "numero": indice + 1,
        })
    return {
        "etapas": etapas,
        "indice_actual": actual,
        "detenida": detenida,
        "titulo_actual": ETAPAS_CARGA[actual]["titulo"] if actual >= 0 else "Sin iniciar",
        "detalle_actual": ETAPAS_CARGA[actual]["detalle"] if actual >= 0 else
                          "La solicitud todavía no entró en carga.",
        "completada": estado in {COMPLETED, COMPLETED_OBS},
    }


def resumen_estados(estados):
    """Conteo por estado visible, para los KPIs."""
    conteo = {clave: 0 for clave in ETIQUETAS}
    for estado in estados:
        conteo[estado_visible(estado)] += 1
    return conteo
