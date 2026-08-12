"""Motor de notificaciones por correo.

Sin dependencias de Streamlit.

Que hace
--------
1. Arma el mensaje (asunto, HTML y texto plano) a partir de un evento y su
   contexto. Las plantillas viven aqui, no repartidas por las pantallas.
2. Decide si hay que enviar: si el estado no cambio de verdad, no envia.
3. Evita reenvios por doble clic o por rerun de Streamlit con una clave de
   idempotencia y una ventana de tiempo.
4. Entrega por el transporte configurado (SMTP, Microsoft Graph o consola).
5. Devuelve un registro del envio para que quien llame lo guarde en la
   auditoria y en el historial de la solicitud.

Que NO hace
-----------
No escribe en la solicitud ni en la auditoria: devuelve el registro y el
llamador decide. Asi el motor se puede probar sin backend.

Nunca lanza hacia arriba desde enviar(): un fallo de correo no puede tumbar un
cambio de estado que ya se guardo. El error queda en el registro devuelto, con
resultado "error".
"""

import base64
import hashlib
import json
import re
import smtplib
import ssl
from datetime import datetime, timedelta, timezone
from email.message import EmailMessage
from email.utils import formataddr
from html import escape
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

LIMA = timezone(timedelta(hours=-5))

# --- eventos -------------------------------------------------------------
EVENTO_CAMBIO_ESTADO = "cambio_estado"
EVENTO_CARGA_PRECIOS = "solicitud_carga_precios"
EVENTO_SIAL_TERMINADA = "carga_sial_terminada"
EVENTO_COMPLETADA = "solicitud_completada"

EVENTOS = (EVENTO_CAMBIO_ESTADO, EVENTO_SIAL_TERMINADA, EVENTO_CARGA_PRECIOS,
           EVENTO_COMPLETADA)

# Ventana por defecto para considerar un envio repetido. Cubre el doble clic y
# el rerun de Streamlit sin bloquear un ida y vuelta legitimo mas tarde.
VENTANA_DUPLICADO_SEGUNDOS = 300

RESULTADO_OK = "ok"
RESULTADO_ERROR = "error"
RESULTADO_OMITIDO = "omitido"

# Tope de adjuntos. Por encima de esto no se adjunta: se manda el correo igual
# avisando que el archivo se descarga desde la app. Un correo que rebota por
# tamano es peor que un correo sin adjunto, porque nadie se entera.
LIMITE_ADJUNTO_BYTES = 8 * 1024 * 1024
# Graph mete el adjunto dentro del propio JSON de sendMail, en base64, y ahi el
# limite practico es bastante menor.
LIMITE_ADJUNTO_GRAPH_BYTES = 3 * 1024 * 1024

TIPO_XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
TIPOS_POR_EXTENSION = {
    ".xlsx": TIPO_XLSX,
    ".xls": "application/vnd.ms-excel",
    ".csv": "text/csv",
    ".pdf": "application/pdf",
    ".zip": "application/zip",
}

MOTIVO_SIN_CAMBIO = "el estado no cambio"
MOTIVO_DUPLICADO = "ya se envio el mismo aviso hace poco"
MOTIVO_SIN_DESTINO = "no hay destinatarios"
MOTIVO_APAGADO = "las notificaciones estan desactivadas"


def _texto(valor):
    if valor is None:
        return ""
    if isinstance(valor, float) and valor != valor:
        return ""
    return str(valor).strip()


def _entero(valor, defecto=0):
    try:
        return int(float(_texto(valor) or defecto))
    except (TypeError, ValueError):
        return defecto


_CORREO = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def correos_validos(valores):
    """Normaliza y ordena una lista de correos, sin repetidos ni basura.

    Un destinatario invalido se descarta en silencio: es preferible enviar a
    los que si son validos que fallar el envio completo.
    """
    if isinstance(valores, (str, bytes)):
        valores = re.split(r"[;,\s]+", _texto(valores))
    salida = set()
    for valor in valores or []:
        correo = _texto(valor).casefold()
        if correo and _CORREO.match(correo):
            salida.add(correo)
    return sorted(salida)


def tipo_por_extension(nombre):
    nombre = _texto(nombre).casefold()
    for extension, tipo in TIPOS_POR_EXTENSION.items():
        if nombre.endswith(extension):
            return tipo
    return "application/octet-stream"


def adjuntos_validos(adjuntos):
    """Deja solo los adjuntos que se pueden mandar.

    Cada adjunto es un dict con 'nombre' y 'contenido' (bytes). Lo que no tenga
    contenido real se descarta en silencio: es preferible mandar el aviso sin
    archivo que no mandarlo.
    """
    salida = []
    for adjunto in adjuntos or []:
        if not isinstance(adjunto, dict):
            continue
        contenido = adjunto.get("contenido")
        if isinstance(contenido, (bytearray, memoryview)):
            contenido = bytes(contenido)
        if not isinstance(contenido, bytes) or not contenido:
            continue
        nombre = _texto(adjunto.get("nombre")) or "adjunto.xlsx"
        salida.append({
            "nombre": nombre,
            "contenido": contenido,
            "tipo": _texto(adjunto.get("tipo")) or tipo_por_extension(nombre),
            "bytes": len(contenido),
        })
    return salida


def tamano_legible(numero):
    numero = float(numero or 0)
    for unidad in ("B", "KB", "MB"):
        if numero < 1024 or unidad == "MB":
            return f"{numero:.0f} {unidad}" if unidad == "B" else f"{numero:.1f} {unidad}"
        numero /= 1024
    return f"{numero:.1f} MB"


def ahora_lima():
    return datetime.now(LIMA)


def formato_lima(valor):
    """Fecha y hora legible en horario de Peru."""
    if isinstance(valor, datetime):
        momento = valor if valor.tzinfo else valor.replace(tzinfo=timezone.utc)
        return momento.astimezone(LIMA).strftime("%d/%m/%Y %H:%M")
    texto = _texto(valor)
    if not texto:
        return ""
    try:
        momento = datetime.fromisoformat(texto.replace("Z", "+00:00"))
    except ValueError:
        return texto
    if not momento.tzinfo:
        momento = momento.replace(tzinfo=timezone.utc)
    return momento.astimezone(LIMA).strftime("%d/%m/%Y %H:%M")


# --- contexto ------------------------------------------------------------
def contexto_desde_ticket(ticket, estado_anterior="", estado_nuevo="",
                          responsable="", observacion="", etiquetas=None,
                          momento=None, extra=None):
    """Aplana lo que las plantillas necesitan de una solicitud.

    'etiquetas' es el diccionario estado interno -> nombre en castellano
    (STATE_LABELS de ticket_system). Se pasa como dato para no acoplar este
    motor a la maquina de estados.
    """
    ticket = ticket if isinstance(ticket, dict) else {}
    etiquetas = etiquetas or {}
    anterior = _texto(estado_anterior)
    nuevo = _texto(estado_nuevo) or _texto(ticket.get("status"))
    resumen = ticket.get("summary") if isinstance(ticket.get("summary"), dict) else {}
    modelos = [_texto(v) for v in (ticket.get("model_colors") or []) if _texto(v)]
    contexto = {
        "solicitud": _texto(ticket.get("code")),
        "marca": _texto(ticket.get("brand")) or "Sin marca",
        "sitios": ", ".join(_texto(s) for s in (ticket.get("sites") or []) if _texto(s)),
        "solicitante": _texto(ticket.get("requester")),
        "solicitante_nombre": _texto(ticket.get("requester_name")),
        "asignado": _texto(ticket.get("assignee")),
        "archivo": _texto(ticket.get("filename")),
        "estado_anterior": anterior,
        "estado_nuevo": nuevo,
        "estado_anterior_label": _texto(etiquetas.get(anterior)) or anterior or "Sin estado",
        "estado_nuevo_label": _texto(etiquetas.get(nuevo)) or nuevo or "Sin estado",
        "responsable": _texto(responsable) or _texto(ticket.get("assignee")) or "Equipo de catalogo",
        "observacion": _texto(observacion),
        "fecha": formato_lima(momento or ahora_lima()),
        "productos": _entero(resumen.get("products")),
        "modelos_color": len(modelos) or _entero(resumen.get("model_colors")),
    }
    if extra:
        for clave, valor in dict(extra).items():
            contexto[_texto(clave)] = valor
    return contexto


# --- deduplicacion -------------------------------------------------------
def hay_cambio_de_estado(anterior, nuevo):
    """False cuando el estado no cambio de verdad. Ahi no se manda correo."""
    anterior = _texto(anterior).casefold()
    nuevo = _texto(nuevo).casefold()
    if not nuevo:
        return False
    return anterior != nuevo


def clave_evento(evento, contexto, destinatarios):
    """Huella estable de un aviso concreto.

    Dos avisos con la misma huella son el mismo aviso: misma solicitud, mismo
    salto de estado y mismos destinatarios.
    """
    partes = [
        _texto(evento),
        _texto((contexto or {}).get("solicitud")),
        _texto((contexto or {}).get("estado_anterior")).casefold(),
        _texto((contexto or {}).get("estado_nuevo")).casefold(),
        "|".join(correos_validos(destinatarios)),
    ]
    return hashlib.sha256("::".join(partes).encode("utf-8")).hexdigest()[:32]


def es_duplicado(historial, clave, ventana_segundos=VENTANA_DUPLICADO_SEGUNDOS, ahora=None):
    """True si ese mismo aviso ya salio dentro de la ventana.

    El historial es la lista 'notifications' de la solicitud, que ya se
    persiste. No hace falta almacenamiento aparte.

    Sin ventana (0 o negativa) la clave vale para siempre: util para eventos
    que solo deben ocurrir una vez por solicitud.
    """
    clave = _texto(clave)
    if not clave:
        return False
    ahora = ahora or ahora_lima()
    ventana = float(ventana_segundos or 0)
    for registro in reversed(list(historial or [])):
        if not isinstance(registro, dict):
            continue
        if _texto(registro.get("clave")) != clave:
            continue
        if _texto(registro.get("resultado")) == RESULTADO_ERROR:
            # Un intento fallido no bloquea el reintento.
            continue
        if ventana <= 0:
            return True
        try:
            enviado = datetime.fromisoformat(_texto(registro.get("created_at")).replace("Z", "+00:00"))
        except ValueError:
            continue
        if not enviado.tzinfo:
            enviado = enviado.replace(tzinfo=timezone.utc)
        if (ahora - enviado).total_seconds() <= ventana:
            return True
    return False


# --- plantillas ----------------------------------------------------------
_ESTILO_BASE = (
    "font-family:Segoe UI,Helvetica,Arial,sans-serif;font-size:14px;"
    "color:#1f2a37;line-height:1.5;"
)


def _fila(etiqueta, valor):
    if not _texto(valor):
        return ""
    return (
        '<tr>'
        f'<td style="padding:6px 14px 6px 0;color:#64748b;white-space:nowrap;">{escape(etiqueta)}</td>'
        f'<td style="padding:6px 0;font-weight:600;">{escape(_texto(valor))}</td>'
        '</tr>'
    )


def _cuerpo_html(titulo, entradilla, filas, observacion="", url_app="", pie=""):
    tabla = "".join(_fila(etiqueta, valor) for etiqueta, valor in filas)
    bloque_obs = ""
    if _texto(observacion):
        bloque_obs = (
            '<div style="margin:18px 0;padding:12px 14px;background:#fff7ed;'
            'border-left:3px solid #f59e0b;border-radius:4px;">'
            '<div style="color:#92400e;font-size:12px;text-transform:uppercase;'
            'letter-spacing:.04em;margin-bottom:4px;">Observacion</div>'
            f'<div>{escape(_texto(observacion))}</div></div>'
        )
    boton = ""
    if _texto(url_app):
        boton = (
            f'<p style="margin:22px 0 0;"><a href="{escape(_texto(url_app))}" '
            'style="background:#1d4ed8;color:#ffffff;text-decoration:none;'
            'padding:10px 18px;border-radius:6px;display:inline-block;">'
            'Abrir Catalog Control Center</a></p>'
        )
    pie_html = ""
    if _texto(pie):
        pie_html = (
            '<p style="margin:24px 0 0;color:#94a3b8;font-size:12px;">'
            f'{escape(_texto(pie))}</p>'
        )
    return (
        f'<div style="{_ESTILO_BASE}max-width:620px;">'
        f'<h2 style="margin:0 0 6px;font-size:18px;color:#0f172a;">{escape(titulo)}</h2>'
        f'<p style="margin:0 0 16px;color:#475569;">{escape(entradilla)}</p>'
        f'<table style="border-collapse:collapse;">{tabla}</table>'
        f'{bloque_obs}{boton}{pie_html}'
        '</div>'
    )


def _cuerpo_texto(titulo, entradilla, filas, observacion="", url_app="", pie=""):
    lineas = [titulo, "", entradilla, ""]
    lineas += [f"{etiqueta}: {_texto(valor)}" for etiqueta, valor in filas if _texto(valor)]
    if _texto(observacion):
        lineas += ["", f"Observacion: {_texto(observacion)}"]
    if _texto(url_app):
        lineas += ["", _texto(url_app)]
    if _texto(pie):
        lineas += ["", _texto(pie)]
    return "\n".join(lineas)


def plantilla_cambio_estado(contexto, url_app=""):
    salto = f'{contexto.get("estado_anterior_label")} -> {contexto.get("estado_nuevo_label")}'
    filas = [
        ("Solicitud", contexto.get("solicitud")),
        ("Marca", contexto.get("marca")),
        ("Sitios", contexto.get("sitios")),
        ("Estado", salto),
        ("Responsable", contexto.get("responsable")),
        ("Fecha y hora", contexto.get("fecha")),
    ]
    titulo = f'Solicitud {contexto.get("solicitud")}: {contexto.get("estado_nuevo_label")}'
    return {
        "asunto": f'[Catalogo] {contexto.get("solicitud")} · {contexto.get("marca")} · {contexto.get("estado_nuevo_label")}',
        "html": _cuerpo_html(
            titulo,
            "Tu solicitud de carga de catalogo cambio de estado.",
            filas, contexto.get("observacion"), url_app,
            "Mensaje automatico de Catalog Control Center. No respondas a este correo.",
        ),
        "texto": _cuerpo_texto(
            titulo,
            "Tu solicitud de carga de catalogo cambio de estado.",
            filas, contexto.get("observacion"), url_app,
            "Mensaje automatico de Catalog Control Center.",
        ),
    }


def plantilla_carga_precios(contexto, url_app=""):
    filas = [
        ("Solicitud", contexto.get("solicitud")),
        ("Marca", contexto.get("marca")),
        ("Sitios", contexto.get("sitios")),
        ("Modelos-color procesados", contexto.get("modelos_color")),
        ("Productos procesados", contexto.get("productos")),
        ("Archivo adjunto", contexto.get("adjunto")),
        ("Responsable de la carga", contexto.get("responsable")),
        ("Solicitado por", contexto.get("solicitante")),
        ("Fecha y hora", contexto.get("fecha")),
    ]
    titulo = f'Carga SIAL terminada: corresponde cargar precios ({contexto.get("marca")})'
    if _texto(contexto.get("adjunto")):
        entradilla = (
            "La carga SIAL de esta solicitud termino correctamente. Se adjunta el archivo "
            "Carga SIAL para que el Area de Producto cargue los precios."
        )
    else:
        entradilla = (
            "La carga SIAL de esta solicitud termino correctamente. "
            "El Area de Producto debe proceder con la carga de precios."
        )
    pie = _texto(contexto.get("adjunto_aviso")) or "Mensaje automatico de Catalog Control Center."
    return {
        "asunto": f'[Catalogo] Carga de precios pendiente · {contexto.get("solicitud")} · {contexto.get("marca")}',
        "html": _cuerpo_html(titulo, entradilla, filas, contexto.get("observacion"), url_app, pie),
        "texto": _cuerpo_texto(titulo, entradilla, filas, contexto.get("observacion"), url_app, pie),
    }


def plantilla_sial_terminada(contexto, url_app=""):
    filas = [
        ("Solicitud", contexto.get("solicitud")),
        ("Marca", contexto.get("marca")),
        ("Modelos-color procesados", contexto.get("modelos_color")),
        ("Productos procesados", contexto.get("productos")),
        ("Responsable", contexto.get("responsable")),
        ("Fecha y hora", contexto.get("fecha")),
    ]
    titulo = f'Carga SIAL terminada · {contexto.get("solicitud")}'
    entradilla = "La carga SIAL termino correctamente. El siguiente paso es la carga de precios."
    return {
        "asunto": f'[Catalogo] Carga SIAL terminada · {contexto.get("solicitud")} · {contexto.get("marca")}',
        "html": _cuerpo_html(titulo, entradilla, filas, contexto.get("observacion"), url_app,
                             "Mensaje automatico de Catalog Control Center."),
        "texto": _cuerpo_texto(titulo, entradilla, filas, contexto.get("observacion"), url_app,
                               "Mensaje automatico de Catalog Control Center."),
    }


def plantilla_completada(contexto, url_app=""):
    """Correo final a la marca. Cierra el circulo que abrio la solicitud."""
    filas = [
        ("Solicitud", contexto.get("solicitud")),
        ("Marca", contexto.get("marca")),
        ("Sitios", contexto.get("sitios")),
        ("Modelos-color cargados", contexto.get("modelos_color")),
        ("Productos cargados", contexto.get("productos")),
        ("Precio y stock", contexto.get("validacion")),
        ("Cerrada por", contexto.get("responsable")),
        ("Fecha y hora", contexto.get("fecha")),
    ]
    titulo = f'Carga completada · {contexto.get("solicitud")}'
    entradilla = ("Tu carga de catalogo termino correctamente. Los precios ya estan "
                  "cargados y validados en Shopify.")
    return {
        "asunto": f'[Catalogo] Carga completada · {contexto.get("solicitud")} · {contexto.get("marca")}',
        "html": _cuerpo_html(titulo, entradilla, filas, contexto.get("observacion"), url_app,
                             "Mensaje automatico de Catalog Control Center."),
        "texto": _cuerpo_texto(titulo, entradilla, filas, contexto.get("observacion"), url_app,
                               "Mensaje automatico de Catalog Control Center."),
    }


PLANTILLAS = {
    EVENTO_CAMBIO_ESTADO: plantilla_cambio_estado,
    EVENTO_CARGA_PRECIOS: plantilla_carga_precios,
    EVENTO_SIAL_TERMINADA: plantilla_sial_terminada,
    EVENTO_COMPLETADA: plantilla_completada,
}


def construir_mensaje(evento, contexto, destinatarios, url_app="", adjuntos=None):
    """Mensaje listo para entregar. Un evento desconocido cae en cambio de estado."""
    plantilla = PLANTILLAS.get(_texto(evento), plantilla_cambio_estado)
    cuerpo = plantilla(contexto or {}, url_app)
    return {
        "evento": _texto(evento),
        "destinatarios": correos_validos(destinatarios),
        "asunto": cuerpo["asunto"],
        "html": cuerpo["html"],
        "texto": cuerpo["texto"],
        "adjuntos": adjuntos_validos(adjuntos),
    }


# --- transportes ---------------------------------------------------------
class NotifyError(RuntimeError):
    pass


class TransporteConsola:
    """No sale a la red. Guarda lo enviado para pruebas y desarrollo local."""

    nombre = "consola"
    entrega_real = False
    limite_adjunto = LIMITE_ADJUNTO_BYTES

    def __init__(self):
        self.enviados = []

    def enviar(self, mensaje, remitente, remitente_nombre=""):
        self.enviados.append(dict(mensaje))
        adjuntos = mensaje.get("adjuntos") or []
        detalle = f'simulado a {len(mensaje.get("destinatarios") or [])} destinatario(s)'
        if adjuntos:
            detalle += f' con {len(adjuntos)} adjunto(s)'
        return {"detalle": detalle}


class TransporteSMTP:
    """Casilla corporativa por SMTP. Solo biblioteca estandar."""

    nombre = "smtp"
    entrega_real = True
    limite_adjunto = LIMITE_ADJUNTO_BYTES

    def __init__(self, host, usuario="", clave="", puerto=587, starttls=True, ssl_directo=False, timeout=20):
        if not _texto(host):
            raise NotifyError("Falta el host SMTP en la configuracion de notificaciones.")
        self.host = _texto(host)
        self.usuario = _texto(usuario)
        self.clave = _texto(clave)
        self.puerto = _entero(puerto, 587)
        self.starttls = bool(starttls)
        self.ssl_directo = bool(ssl_directo)
        self.timeout = _entero(timeout, 20)

    def _mensaje(self, mensaje, remitente, remitente_nombre):
        correo = EmailMessage()
        correo["Subject"] = mensaje["asunto"]
        correo["From"] = formataddr((remitente_nombre or "Catalog Control Center", remitente))
        correo["To"] = ", ".join(mensaje["destinatarios"])
        correo["Auto-Submitted"] = "auto-generated"
        correo.set_content(mensaje["texto"])
        correo.add_alternative(mensaje["html"], subtype="html")
        for adjunto in mensaje.get("adjuntos") or []:
            principal, _, secundario = adjunto["tipo"].partition("/")
            correo.add_attachment(
                adjunto["contenido"],
                maintype=principal or "application",
                subtype=secundario or "octet-stream",
                filename=adjunto["nombre"],
            )
        return correo

    def enviar(self, mensaje, remitente, remitente_nombre=""):
        correo = self._mensaje(mensaje, remitente, remitente_nombre)
        contexto_ssl = ssl.create_default_context()
        if self.ssl_directo:
            with smtplib.SMTP_SSL(self.host, self.puerto, timeout=self.timeout, context=contexto_ssl) as sesion:
                if self.usuario:
                    sesion.login(self.usuario, self.clave)
                sesion.send_message(correo)
        else:
            with smtplib.SMTP(self.host, self.puerto, timeout=self.timeout) as sesion:
                sesion.ehlo()
                if self.starttls:
                    sesion.starttls(context=contexto_ssl)
                    sesion.ehlo()
                if self.usuario:
                    sesion.login(self.usuario, self.clave)
                sesion.send_message(correo)
        return {"detalle": f"entregado por {self.host}:{self.puerto}"}


class TransporteGraph:
    """Microsoft 365 por Graph con credenciales de aplicacion.

    Es el camino recomendado cuando la organizacion tiene desactivada la
    autenticacion basica de SMTP AUTH, que es lo habitual en Microsoft 365
    desde 2023. Requiere un registro de aplicacion en Entra ID con el permiso
    de aplicacion Mail.Send, y conviene acotarlo por politica a la casilla de
    envio. Solo biblioteca estandar.
    """

    nombre = "graph"
    entrega_real = True
    limite_adjunto = LIMITE_ADJUNTO_GRAPH_BYTES

    def __init__(self, tenant_id, client_id, client_secret, usuario_envio, timeout=20):
        faltan = [n for n, v in [("tenant_id", tenant_id), ("client_id", client_id),
                                 ("client_secret", client_secret), ("usuario_envio", usuario_envio)]
                  if not _texto(v)]
        if faltan:
            raise NotifyError(f"Configuracion Graph incompleta: falta {', '.join(faltan)}.")
        self.tenant_id = _texto(tenant_id)
        self.client_id = _texto(client_id)
        self.client_secret = _texto(client_secret)
        self.usuario_envio = _texto(usuario_envio)
        self.timeout = _entero(timeout, 20)

    def _token(self):
        url = f"https://login.microsoftonline.com/{self.tenant_id}/oauth2/v2.0/token"
        datos = urlencode({
            "client_id": self.client_id,
            "client_secret": self.client_secret,
            "scope": "https://graph.microsoft.com/.default",
            "grant_type": "client_credentials",
        }).encode("utf-8")
        peticion = Request(url, data=datos, method="POST", headers={
            "Content-Type": "application/x-www-form-urlencoded",
        })
        with urlopen(peticion, timeout=self.timeout) as respuesta:
            cuerpo = json.loads(respuesta.read().decode("utf-8"))
        token = _texto(cuerpo.get("access_token"))
        if not token:
            raise NotifyError("Microsoft Graph no devolvio un token de acceso.")
        return token

    def enviar(self, mensaje, remitente, remitente_nombre=""):
        token = self._token()
        url = f"https://graph.microsoft.com/v1.0/users/{self.usuario_envio}/sendMail"
        cuerpo = {
            "message": {
                "subject": mensaje["asunto"],
                "body": {"contentType": "HTML", "content": mensaje["html"]},
                "toRecipients": [{"emailAddress": {"address": correo}}
                                 for correo in mensaje["destinatarios"]],
            },
            "saveToSentItems": True,
        }
        adjuntos = mensaje.get("adjuntos") or []
        if adjuntos:
            # Graph mete el archivo en el propio JSON, en base64.
            cuerpo["message"]["attachments"] = [{
                "@odata.type": "#microsoft.graph.fileAttachment",
                "name": adjunto["nombre"],
                "contentType": adjunto["tipo"],
                "contentBytes": base64.b64encode(adjunto["contenido"]).decode("ascii"),
            } for adjunto in adjuntos]
        peticion = Request(url, data=json.dumps(cuerpo).encode("utf-8"), method="POST", headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        })
        try:
            with urlopen(peticion, timeout=self.timeout) as respuesta:
                respuesta.read()
        except HTTPError as exc:
            detalle = exc.read().decode("utf-8", errors="replace")[:300]
            raise NotifyError(f"Graph respondio {exc.code}: {detalle}") from exc
        except URLError as exc:
            raise NotifyError(f"No se pudo contactar a Microsoft Graph: {exc.reason}") from exc
        return {"detalle": f"entregado por Graph como {self.usuario_envio}"}


def crear_transporte(config):
    """Construye el transporte segun la configuracion. Nunca lanza.

    Ante cualquier problema devuelve el transporte de consola, de modo que la
    app arranca igual y el motivo queda visible en el registro de envios.
    """
    config = dict(config or {})
    tipo = _texto(config.get("transporte")).casefold() or "consola"
    try:
        if tipo == "smtp":
            smtp = dict(config.get("smtp") or {})
            return TransporteSMTP(
                host=smtp.get("host"), usuario=smtp.get("usuario"), clave=smtp.get("clave"),
                puerto=smtp.get("puerto", 587), starttls=smtp.get("starttls", True),
                ssl_directo=smtp.get("ssl_directo", False), timeout=smtp.get("timeout", 20),
            ), ""
        if tipo == "graph":
            graph = dict(config.get("graph") or {})
            return TransporteGraph(
                tenant_id=graph.get("tenant_id"), client_id=graph.get("client_id"),
                client_secret=graph.get("client_secret"),
                usuario_envio=graph.get("usuario_envio") or config.get("remitente"),
                timeout=graph.get("timeout", 20),
            ), ""
    except NotifyError as exc:
        return TransporteConsola(), str(exc)
    if tipo not in {"consola", ""}:
        return TransporteConsola(), f'Transporte desconocido: "{tipo}". Se usa consola.'
    return TransporteConsola(), ""


# --- motor ---------------------------------------------------------------
class MotorNotificaciones:
    """Punto unico de envio. Todo correo de la app pasa por aqui."""

    def __init__(self, transporte=None, remitente="", remitente_nombre="Catalog Control Center",
                 url_app="", copia_siempre=(), activo=True, ventana_duplicado=VENTANA_DUPLICADO_SEGUNDOS,
                 aviso_config=""):
        self.transporte = transporte or TransporteConsola()
        self.remitente = _texto(remitente)
        self.remitente_nombre = _texto(remitente_nombre) or "Catalog Control Center"
        self.url_app = _texto(url_app)
        self.copia_siempre = correos_validos(copia_siempre)
        self.activo = bool(activo)
        self.ventana_duplicado = ventana_duplicado
        self.aviso_config = _texto(aviso_config)

    @classmethod
    def desde_config(cls, config):
        """Crea el motor desde la seccion [notificaciones] de Secrets."""
        config = dict(config or {})
        transporte, aviso = crear_transporte(config)
        return cls(
            transporte=transporte,
            remitente=config.get("remitente"),
            remitente_nombre=config.get("remitente_nombre"),
            url_app=config.get("url_app"),
            copia_siempre=config.get("copia_siempre"),
            activo=config.get("activo", True),
            ventana_duplicado=config.get("ventana_duplicado", VENTANA_DUPLICADO_SEGUNDOS),
            aviso_config=aviso,
        )

    def destinatarios_para(self, evento, contexto, destinatarios=None):
        """Quien recibe. El evento de precios suma al Area de Producto."""
        contexto = contexto or {}
        base = list(destinatarios or [])
        if not base:
            base = [contexto.get("solicitante"), contexto.get("asignado")]
        if evento == EVENTO_CARGA_PRECIOS:
            base += list(contexto.get("area_producto") or [])
        return correos_validos(base + list(self.copia_siempre))

    def preparar(self, evento, contexto, destinatarios=None, historial=(), forzar=False, adjuntos=None):
        """Decide si toca enviar y arma el mensaje. NO entrega nada.

        Devuelve (registro, mensaje). Con mensaje None no hay que enviar, y el
        registro dice por que.

        Existe separado de enviar() porque con la cola hay que decidir en el
        hilo de la pantalla y entregar en el de correo. Si se usara enviar()
        para decidir, el aviso saldria dos veces: una en linea y otra al
        desencolar.

        El registro tiene siempre las mismas claves, se haya enviado o no, para
        que la auditoria y el historial de la solicitud lo guarden sin ramas.

        Del adjunto solo queda el NOMBRE en el registro. El registro se guarda
        dentro de la solicitud, que es un JSON: meterle los bytes del Excel lo
        haria imposible de serializar y multiplicaria su tamano.
        """
        contexto = dict(contexto or {})
        evento = _texto(evento) or EVENTO_CAMBIO_ESTADO
        destino = self.destinatarios_para(evento, contexto, destinatarios)
        adjuntos = adjuntos_validos(adjuntos)
        # El tope depende del transporte: Graph aguanta menos que SMTP.
        tope = getattr(self.transporte, "limite_adjunto", LIMITE_ADJUNTO_BYTES)
        pesados = [a for a in adjuntos if a["bytes"] > tope]
        if pesados:
            adjuntos = [a for a in adjuntos if a["bytes"] <= tope]
            contexto["adjunto_aviso"] = (
                f'El archivo {pesados[0]["nombre"]} ({tamano_legible(pesados[0]["bytes"])}) '
                f'supera el limite de {tamano_legible(tope)} y no se adjunto. '
                "Descargalo desde la solicitud en Catalog Control Center."
            )
        if adjuntos:
            contexto["adjunto"] = ", ".join(
                f'{a["nombre"]} ({tamano_legible(a["bytes"])})' for a in adjuntos
            )
        registro = {
            "created_at": ahora_lima().isoformat(timespec="seconds"),
            "evento": evento,
            "canal": "email",
            "transporte": getattr(self.transporte, "nombre", "consola"),
            "solicitud": _texto(contexto.get("solicitud")),
            "marca": _texto(contexto.get("marca")),
            "estado_anterior": _texto(contexto.get("estado_anterior")),
            "estado_nuevo": _texto(contexto.get("estado_nuevo")),
            "responsable": _texto(contexto.get("responsable")),
            "observacion": _texto(contexto.get("observacion")),
            "destinatarios": destino,
            "asunto": "",
            "clave": "",
            "adjuntos": [a["nombre"] for a in adjuntos],
            "resultado": RESULTADO_OMITIDO,
            "motivo": "",
            "detalle": "",
        }

        if not self.activo:
            registro["motivo"] = MOTIVO_APAGADO
            return registro, None
        if evento == EVENTO_CAMBIO_ESTADO and not forzar and not hay_cambio_de_estado(
            contexto.get("estado_anterior"), contexto.get("estado_nuevo")
        ):
            registro["motivo"] = MOTIVO_SIN_CAMBIO
            return registro, None
        if not destino:
            registro["motivo"] = MOTIVO_SIN_DESTINO
            return registro, None

        clave = clave_evento(evento, contexto, destino)
        registro["clave"] = clave
        if not forzar and es_duplicado(historial, clave, self.ventana_duplicado):
            registro["motivo"] = MOTIVO_DUPLICADO
            return registro, None

        mensaje = construir_mensaje(evento, contexto, destino, self.url_app, adjuntos)
        registro["asunto"] = mensaje["asunto"]
        if not self.remitente:
            registro["resultado"] = RESULTADO_ERROR
            registro["motivo"] = "falta el remitente en la configuracion"
            return registro, None
        return registro, mensaje

    def enviar(self, evento, contexto, destinatarios=None, historial=(), forzar=False, adjuntos=None):
        """Decide, arma y entrega. Nunca lanza."""
        registro, mensaje = self.preparar(evento, contexto, destinatarios, historial, forzar, adjuntos)
        if mensaje is None:
            return registro
        try:
            salida = self.transporte.enviar(mensaje, self.remitente, self.remitente_nombre) or {}
            registro["resultado"] = RESULTADO_OK
            registro["detalle"] = _texto(salida.get("detalle"))
        except Exception as exc:  # el correo nunca puede tumbar la accion
            registro["resultado"] = RESULTADO_ERROR
            registro["motivo"] = f"{type(exc).__name__}: {exc}"[:300]
        return registro


# --- adaptador para TicketService ----------------------------------------
class AdaptadorCorreoTickets:
    """Reemplaza a MockNotificationAdapter conservando su interfaz.

    TicketService ya llama a notifier.notify() en cada transicion, asi que
    enchufando esto el correo sale desde las 18 pantallas sin tocar ninguna.

    El envio se delega a 'encolar' cuando se le pasa uno, para no sumar el
    viaje SMTP al tiempo de respuesta de la pantalla. Sin 'encolar' envia en
    linea, que es lo que hacen las pruebas.
    """

    def __init__(self, motor, etiquetas=None, area_producto=(), encolar=None, registrar=None):
        self.motor = motor or MotorNotificaciones()
        self.etiquetas = dict(etiquetas or {})
        self.area_producto = correos_validos(area_producto)
        self.encolar = encolar
        self.registrar = registrar

    def _evento_de(self, event, contexto):
        event = _texto(event)
        if event in EVENTOS:
            return event
        # TicketService manda "status_<estado>"; todos son cambios de estado.
        return EVENTO_CAMBIO_ESTADO

    def notify(self, ticket, event, recipients=None, message="", **extra):
        """Interfaz historica del adaptador. Devuelve el registro a guardar."""
        contexto = contexto_desde_ticket(
            ticket,
            estado_anterior=extra.get("estado_anterior", ""),
            estado_nuevo=extra.get("estado_nuevo", "") or _texto((ticket or {}).get("status")),
            responsable=extra.get("responsable", ""),
            observacion=extra.get("observacion", "") or _texto(message),
            etiquetas=self.etiquetas,
            extra={"area_producto": self.area_producto, **dict(extra.get("contexto") or {})},
        )
        evento = self._evento_de(event, contexto)
        historial = (ticket or {}).get("notifications") or []
        destino = list(recipients or [])
        adjuntos = adjuntos_validos(extra.get("adjuntos"))

        if self.encolar:
            # preparar(), no enviar(): decidir aqui y entregar en la cola. Con
            # enviar() el aviso salia DOS veces, una en linea y otra al
            # desencolar.
            registro, mensaje = self.motor.preparar(evento, contexto, destino, historial,
                                                    forzar=False, adjuntos=adjuntos)
            if mensaje is None:
                # No hay nada que mandar: se anota igual, sin ocupar la cola.
                return self._registro_ticket(registro, ticket, event, message)
            self.encolar(self.motor, evento, contexto, destino, self.registrar, adjuntos)
            registro["detalle"] = "encolado"
            return self._registro_ticket(registro, ticket, event, message)

        registro = self.motor.enviar(evento, contexto, destino, historial, adjuntos=adjuntos)
        if self.registrar:
            try:
                self.registrar(registro)
            except Exception:
                pass
        return self._registro_ticket(registro, ticket, event, message)

    @staticmethod
    def _registro_ticket(registro, ticket, event, message):
        """Forma que espera el historial 'notifications' de la solicitud.

        Conserva las claves que ya usaba MockNotificationAdapter (id, event,
        recipients, message, channel, email_status, read_by, link) para que las
        solicitudes antiguas y las pantallas actuales sigan funcionando.
        """
        salida = dict(registro)
        salida.update({
            "id": registro.get("clave") or hashlib.sha256(
                f'{registro.get("created_at")}{registro.get("evento")}'.encode("utf-8")
            ).hexdigest()[:32],
            "event": _texto(event),
            "recipients": list(registro.get("destinatarios") or []),
            "message": _texto(message),
            "channel": "email",
            "email_status": registro.get("resultado"),
            "read_by": [],
            "link": f'ticket:{(ticket or {}).get("code", "")}',
        })
        return salida
