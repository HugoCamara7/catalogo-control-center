"""Pruebas del motor de notificaciones por correo.

Ninguna prueba sale a la red: se usa el transporte de consola y transportes
falsos que registran o revientan a proposito.
"""

import os
import sys
import tempfile
import unittest
from datetime import timedelta
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import ticket_system as ts
from engines import notify as motor
from engines.notify import (
    EVENTO_CAMBIO_ESTADO,
    EVENTO_CARGA_PRECIOS,
    MOTIVO_APAGADO,
    MOTIVO_DUPLICADO,
    MOTIVO_SIN_CAMBIO,
    MOTIVO_SIN_DESTINO,
    RESULTADO_ERROR,
    RESULTADO_OK,
    RESULTADO_OMITIDO,
    AdaptadorCorreoTickets,
    MotorNotificaciones,
    NotifyError,
    TransporteConsola,
    TransporteGraph,
    TransporteSMTP,
    ahora_lima,
    clave_evento,
    construir_mensaje,
    contexto_desde_ticket,
    correos_validos,
    crear_transporte,
    es_duplicado,
    hay_cambio_de_estado,
)

TICKET = {
    "code": "CAT-2026-000123",
    "brand": "Columbia",
    "sites": ["Columbia.pe"],
    "requester": "clara.gallastegui@forus.pe",
    "requester_name": "Clara Gallastegui",
    "assignee": "hugo.camara@forus.pe",
    "status": ts.STATE_LOAD_APPROVED,
    "filename": "input.xlsx",
    "summary": {"products": 40},
    "model_colors": ["IM5678-011", "IM5678-012"],
    "notifications": [],
}


class TransporteQueRevienta:
    nombre = "roto"
    entrega_real = True

    def enviar(self, mensaje, remitente, remitente_nombre=""):
        raise RuntimeError("el servidor dijo que no")


def motor_de_prueba(**kwargs):
    opciones = dict(remitente="catalogo@forus.pe", transporte=TransporteConsola())
    opciones.update(kwargs)
    return MotorNotificaciones(**opciones)


class TestSinStreamlit(unittest.TestCase):
    def test_no_importa_streamlit(self):
        self.assertNotIn("import streamlit", Path(motor.__file__).read_text(encoding="utf-8"))


class TestCorreos(unittest.TestCase):
    def test_normaliza_y_ordena(self):
        self.assertEqual(
            correos_validos(["B@forus.pe", "a@forus.pe", "a@forus.pe"]),
            ["a@forus.pe", "b@forus.pe"],
        )

    def test_descarta_lo_que_no_es_correo(self):
        self.assertEqual(correos_validos(["sin arroba", "", None, "a@forus.pe"]), ["a@forus.pe"])

    def test_acepta_una_cadena_separada(self):
        self.assertEqual(correos_validos("a@forus.pe; b@forus.pe"), ["a@forus.pe", "b@forus.pe"])

    def test_entrada_vacia(self):
        self.assertEqual(correos_validos(None), [])


class TestContexto(unittest.TestCase):
    def test_trae_lo_que_pide_el_correo(self):
        ctx = contexto_desde_ticket(
            TICKET, estado_anterior=ts.STATE_DIGITAL_REVIEW, estado_nuevo=ts.STATE_LOAD_APPROVED,
            responsable="hugo.camara@forus.pe", observacion="Falta la foto",
            etiquetas=ts.STATE_LABELS,
        )
        self.assertEqual(ctx["solicitud"], "CAT-2026-000123")
        self.assertEqual(ctx["marca"], "Columbia")
        self.assertEqual(ctx["estado_anterior_label"], "Revisión Digital")
        self.assertEqual(ctx["estado_nuevo_label"], "Aprobada para carga")
        self.assertEqual(ctx["responsable"], "hugo.camara@forus.pe")
        self.assertEqual(ctx["observacion"], "Falta la foto")
        self.assertEqual(ctx["modelos_color"], 2)
        self.assertEqual(ctx["productos"], 40)
        self.assertTrue(ctx["fecha"])

    def test_sin_etiquetas_usa_el_estado_crudo(self):
        ctx = contexto_desde_ticket(TICKET, estado_nuevo="loading")
        self.assertEqual(ctx["estado_nuevo_label"], "loading")

    def test_ticket_vacio_no_revienta(self):
        ctx = contexto_desde_ticket(None)
        self.assertEqual(ctx["solicitud"], "")
        self.assertEqual(ctx["marca"], "Sin marca")

    def test_el_responsable_cae_al_asignado(self):
        self.assertEqual(contexto_desde_ticket(TICKET)["responsable"], "hugo.camara@forus.pe")


class TestNoDuplicar(unittest.TestCase):
    def test_sin_cambio_de_estado_no_hay_aviso(self):
        self.assertFalse(hay_cambio_de_estado("loading", "loading"))
        self.assertFalse(hay_cambio_de_estado("LOADING", "loading"))
        self.assertFalse(hay_cambio_de_estado("loading", ""))

    def test_con_cambio_si(self):
        self.assertTrue(hay_cambio_de_estado("loading", "completed"))
        self.assertTrue(hay_cambio_de_estado("", "completed"))

    def test_el_motor_no_envia_si_el_estado_no_cambio(self):
        m = motor_de_prueba()
        ctx = contexto_desde_ticket(TICKET, estado_anterior="loading", estado_nuevo="loading")
        registro = m.enviar(EVENTO_CAMBIO_ESTADO, ctx, ["a@forus.pe"])
        self.assertEqual(registro["resultado"], RESULTADO_OMITIDO)
        self.assertEqual(registro["motivo"], MOTIVO_SIN_CAMBIO)
        self.assertEqual(m.transporte.enviados, [])

    def test_la_clave_es_estable(self):
        ctx = contexto_desde_ticket(TICKET, estado_anterior="a", estado_nuevo="b")
        primera = clave_evento(EVENTO_CAMBIO_ESTADO, ctx, ["a@forus.pe"])
        segunda = clave_evento(EVENTO_CAMBIO_ESTADO, ctx, ["A@FORUS.PE"])
        self.assertEqual(primera, segunda)

    def test_la_clave_cambia_con_el_salto_de_estado(self):
        base = contexto_desde_ticket(TICKET, estado_anterior="a", estado_nuevo="b")
        otro = contexto_desde_ticket(TICKET, estado_anterior="b", estado_nuevo="c")
        self.assertNotEqual(
            clave_evento(EVENTO_CAMBIO_ESTADO, base, ["a@forus.pe"]),
            clave_evento(EVENTO_CAMBIO_ESTADO, otro, ["a@forus.pe"]),
        )

    def test_un_aviso_reciente_es_duplicado(self):
        historial = [{"clave": "abc", "created_at": ahora_lima().isoformat(), "resultado": RESULTADO_OK}]
        self.assertTrue(es_duplicado(historial, "abc", 300))

    def test_un_aviso_viejo_no_bloquea(self):
        viejo = (ahora_lima() - timedelta(hours=2)).isoformat()
        historial = [{"clave": "abc", "created_at": viejo, "resultado": RESULTADO_OK}]
        self.assertFalse(es_duplicado(historial, "abc", 300))

    def test_un_intento_fallido_no_bloquea_el_reintento(self):
        historial = [{"clave": "abc", "created_at": ahora_lima().isoformat(), "resultado": RESULTADO_ERROR}]
        self.assertFalse(es_duplicado(historial, "abc", 300))

    def test_sin_ventana_la_clave_vale_para_siempre(self):
        viejo = (ahora_lima() - timedelta(days=30)).isoformat()
        historial = [{"clave": "abc", "created_at": viejo, "resultado": RESULTADO_OK}]
        self.assertTrue(es_duplicado(historial, "abc", 0))

    def test_historial_con_basura(self):
        self.assertFalse(es_duplicado(["texto", None, {}], "abc", 300))
        self.assertFalse(es_duplicado(None, "abc", 300))

    def test_el_motor_no_reenvia_dentro_de_la_ventana(self):
        m = motor_de_prueba()
        ctx = contexto_desde_ticket(TICKET, estado_anterior="a", estado_nuevo="b")
        primero = m.enviar(EVENTO_CAMBIO_ESTADO, ctx, ["a@forus.pe"])
        self.assertEqual(primero["resultado"], RESULTADO_OK)
        segundo = m.enviar(EVENTO_CAMBIO_ESTADO, ctx, ["a@forus.pe"], historial=[primero])
        self.assertEqual(segundo["resultado"], RESULTADO_OMITIDO)
        self.assertEqual(segundo["motivo"], MOTIVO_DUPLICADO)
        self.assertEqual(len(m.transporte.enviados), 1)

    def test_forzar_salta_la_deduplicacion(self):
        m = motor_de_prueba()
        ctx = contexto_desde_ticket(TICKET, estado_anterior="a", estado_nuevo="b")
        primero = m.enviar(EVENTO_CAMBIO_ESTADO, ctx, ["a@forus.pe"])
        segundo = m.enviar(EVENTO_CAMBIO_ESTADO, ctx, ["a@forus.pe"], historial=[primero], forzar=True)
        self.assertEqual(segundo["resultado"], RESULTADO_OK)


class TestPlantillas(unittest.TestCase):
    def _mensaje(self, evento=EVENTO_CAMBIO_ESTADO, **kwargs):
        ctx = contexto_desde_ticket(
            TICKET, estado_anterior=ts.STATE_DIGITAL_REVIEW, estado_nuevo=ts.STATE_LOAD_APPROVED,
            responsable="hugo.camara@forus.pe", etiquetas=ts.STATE_LABELS, **kwargs,
        )
        return construir_mensaje(evento, ctx, ["clara.gallastegui@forus.pe"], "https://app.forus.pe")

    def test_el_correo_de_estado_trae_todo_lo_pedido(self):
        mensaje = self._mensaje(observacion="Revisar la talla 8.5")
        for esperado in ["CAT-2026-000123", "Columbia", "Revisión Digital",
                         "Aprobada para carga", "hugo.camara@forus.pe", "Revisar la talla 8.5"]:
            self.assertIn(esperado, mensaje["html"], esperado)
            self.assertIn(esperado, mensaje["texto"], esperado)

    def test_sin_observacion_no_aparece_el_bloque(self):
        self.assertNotIn("Observacion", self._mensaje()["html"])

    def test_el_asunto_identifica_la_solicitud(self):
        asunto = self._mensaje()["asunto"]
        self.assertIn("CAT-2026-000123", asunto)
        self.assertIn("Columbia", asunto)

    def test_el_correo_de_precios_trae_las_cantidades(self):
        mensaje = self._mensaje(EVENTO_CARGA_PRECIOS)
        self.assertIn("Modelos-color procesados", mensaje["html"])
        self.assertIn("precios", mensaje["asunto"].casefold())
        self.assertIn("2", mensaje["texto"])

    def test_el_html_escapa_lo_que_escribe_el_usuario(self):
        mensaje = self._mensaje(observacion="<script>alert(1)</script>")
        self.assertNotIn("<script>", mensaje["html"])
        self.assertIn("&lt;script&gt;", mensaje["html"])

    def test_un_evento_desconocido_cae_en_cambio_de_estado(self):
        ctx = contexto_desde_ticket(TICKET, etiquetas=ts.STATE_LABELS)
        self.assertIn("CAT-2026-000123", construir_mensaje("inventado", ctx, ["a@forus.pe"])["asunto"])


class TestEnvio(unittest.TestCase):
    def test_envio_correcto(self):
        m = motor_de_prueba()
        ctx = contexto_desde_ticket(TICKET, estado_anterior="a", estado_nuevo="b")
        registro = m.enviar(EVENTO_CAMBIO_ESTADO, ctx, ["clara.gallastegui@forus.pe"])
        self.assertEqual(registro["resultado"], RESULTADO_OK)
        self.assertEqual(registro["destinatarios"], ["clara.gallastegui@forus.pe"])
        self.assertTrue(registro["asunto"])
        self.assertTrue(registro["clave"])

    def test_sin_destinatarios_no_envia(self):
        m = motor_de_prueba()
        ctx = contexto_desde_ticket({}, estado_anterior="a", estado_nuevo="b")
        registro = m.enviar(EVENTO_CAMBIO_ESTADO, ctx, [])
        self.assertEqual(registro["motivo"], MOTIVO_SIN_DESTINO)

    def test_apagado(self):
        m = motor_de_prueba(activo=False)
        ctx = contexto_desde_ticket(TICKET, estado_anterior="a", estado_nuevo="b")
        registro = m.enviar(EVENTO_CAMBIO_ESTADO, ctx, ["a@forus.pe"])
        self.assertEqual(registro["motivo"], MOTIVO_APAGADO)

    def test_un_fallo_del_transporte_no_lanza(self):
        m = motor_de_prueba(transporte=TransporteQueRevienta())
        ctx = contexto_desde_ticket(TICKET, estado_anterior="a", estado_nuevo="b")
        registro = m.enviar(EVENTO_CAMBIO_ESTADO, ctx, ["a@forus.pe"])
        self.assertEqual(registro["resultado"], RESULTADO_ERROR)
        self.assertIn("RuntimeError", registro["motivo"])

    def test_sin_remitente_es_error_de_configuracion(self):
        m = MotorNotificaciones(transporte=TransporteConsola(), remitente="")
        ctx = contexto_desde_ticket(TICKET, estado_anterior="a", estado_nuevo="b")
        registro = m.enviar(EVENTO_CAMBIO_ESTADO, ctx, ["a@forus.pe"])
        self.assertEqual(registro["resultado"], RESULTADO_ERROR)

    def test_destinatarios_por_defecto(self):
        m = motor_de_prueba()
        ctx = contexto_desde_ticket(TICKET, estado_anterior="a", estado_nuevo="b")
        self.assertEqual(
            m.destinatarios_para(EVENTO_CAMBIO_ESTADO, ctx),
            ["clara.gallastegui@forus.pe", "hugo.camara@forus.pe"],
        )

    def test_el_evento_de_precios_suma_al_area_de_producto(self):
        m = motor_de_prueba()
        ctx = contexto_desde_ticket(TICKET, extra={"area_producto": ["producto@forus.pe"]})
        self.assertIn("producto@forus.pe", m.destinatarios_para(EVENTO_CARGA_PRECIOS, ctx))

    def test_la_copia_siempre_se_agrega(self):
        m = motor_de_prueba(copia_siempre=["auditoria@forus.pe"])
        ctx = contexto_desde_ticket(TICKET)
        self.assertIn("auditoria@forus.pe", m.destinatarios_para(EVENTO_CAMBIO_ESTADO, ctx))

    def test_el_registro_tiene_siempre_las_mismas_claves(self):
        m = motor_de_prueba()
        ctx = contexto_desde_ticket(TICKET, estado_anterior="a", estado_nuevo="b")
        enviado = m.enviar(EVENTO_CAMBIO_ESTADO, ctx, ["a@forus.pe"])
        omitido = m.enviar(EVENTO_CAMBIO_ESTADO, ctx, [])
        self.assertEqual(set(enviado), set(omitido))


class TestAdjuntos(unittest.TestCase):
    EXCEL = b"PK\x03\x04" + b"x" * 500

    def _enviar(self, adjuntos, transporte=None):
        m = motor_de_prueba(transporte=transporte or TransporteConsola())
        ctx = contexto_desde_ticket(TICKET, estado_anterior="sial_loaded",
                                    estado_nuevo="price_load_requested", etiquetas=ts.STATE_LABELS)
        registro = m.enviar(EVENTO_CARGA_PRECIOS, ctx, ["producto@forus.pe"], adjuntos=adjuntos)
        return m, registro

    def test_el_archivo_llega_al_mensaje(self):
        m, registro = self._enviar([{"nombre": "Carga_SIAL.xlsx", "contenido": self.EXCEL}])
        enviado = m.transporte.enviados[-1]
        self.assertEqual(len(enviado["adjuntos"]), 1)
        self.assertEqual(enviado["adjuntos"][0]["contenido"], self.EXCEL)
        self.assertEqual(enviado["adjuntos"][0]["tipo"], motor.TIPO_XLSX)
        self.assertEqual(registro["resultado"], RESULTADO_OK)

    def test_el_registro_guarda_el_nombre_no_los_bytes(self):
        """El registro se guarda dentro del ticket, que es un JSON."""
        import json
        _, registro = self._enviar([{"nombre": "Carga_SIAL.xlsx", "contenido": self.EXCEL}])
        self.assertEqual(registro["adjuntos"], ["Carga_SIAL.xlsx"])
        json.dumps(registro)  # revienta si quedaron bytes dentro

    def test_el_correo_menciona_el_adjunto(self):
        m, _ = self._enviar([{"nombre": "Carga_SIAL.xlsx", "contenido": self.EXCEL}])
        enviado = m.transporte.enviados[-1]
        self.assertIn("Carga_SIAL.xlsx", enviado["html"])
        self.assertIn("adjunt", enviado["texto"].casefold())

    def test_sin_adjunto_no_aparece_la_fila(self):
        m, _ = self._enviar([])
        self.assertNotIn("Archivo adjunto", m.transporte.enviados[-1]["html"])

    def test_un_archivo_enorme_no_bloquea_el_aviso(self):
        grande = b"x" * (motor.LIMITE_ADJUNTO_BYTES + 1)
        m, registro = self._enviar([{"nombre": "Gigante.xlsx", "contenido": grande}])
        self.assertEqual(registro["resultado"], RESULTADO_OK)
        self.assertEqual(registro["adjuntos"], [])
        self.assertIn("supera el limite", m.transporte.enviados[-1]["html"])

    def test_graph_tiene_un_tope_mas_bajo(self):
        class GraphFalso(TransporteConsola):
            nombre = "graph"
            limite_adjunto = motor.LIMITE_ADJUNTO_GRAPH_BYTES

        mediano = b"x" * (motor.LIMITE_ADJUNTO_GRAPH_BYTES + 1)
        _, registro = self._enviar([{"nombre": "Medio.xlsx", "contenido": mediano}],
                                   transporte=GraphFalso())
        self.assertEqual(registro["adjuntos"], [])
        self.assertEqual(registro["resultado"], RESULTADO_OK)

    def test_adjuntos_invalidos_se_descartan(self):
        from engines.notify import adjuntos_validos
        self.assertEqual(adjuntos_validos([{"nombre": "a.xlsx", "contenido": b""}]), [])
        self.assertEqual(adjuntos_validos([{"nombre": "a.xlsx", "contenido": "texto"}]), [])
        self.assertEqual(adjuntos_validos(["basura", None]), [])
        self.assertEqual(adjuntos_validos(None), [])

    def test_un_adjunto_sin_nombre_recibe_uno(self):
        from engines.notify import adjuntos_validos
        self.assertEqual(adjuntos_validos([{"contenido": b"x"}])[0]["nombre"], "adjunto.xlsx")

    def test_el_mensaje_smtp_lleva_el_archivo(self):
        transporte = TransporteSMTP(host="smtp.forus.pe")
        mensaje = construir_mensaje(
            EVENTO_CARGA_PRECIOS,
            contexto_desde_ticket(TICKET, etiquetas=ts.STATE_LABELS),
            ["producto@forus.pe"], "",
            [{"nombre": "Carga_SIAL.xlsx", "contenido": self.EXCEL}],
        )
        correo = transporte._mensaje(mensaje, "catalogo@forus.pe", "Catalogo")
        adjuntos = list(correo.iter_attachments())
        self.assertEqual(len(adjuntos), 1)
        self.assertEqual(adjuntos[0].get_filename(), "Carga_SIAL.xlsx")
        self.assertEqual(adjuntos[0].get_payload(decode=True), self.EXCEL)


class TestTransportes(unittest.TestCase):
    def test_consola_por_defecto(self):
        transporte, aviso = crear_transporte({})
        self.assertIsInstance(transporte, TransporteConsola)
        self.assertEqual(aviso, "")

    def test_smtp_bien_configurado(self):
        transporte, aviso = crear_transporte({
            "transporte": "smtp",
            "smtp": {"host": "smtp.office365.com", "usuario": "a@forus.pe", "clave": "x"},
        })
        self.assertIsInstance(transporte, TransporteSMTP)
        self.assertEqual(transporte.puerto, 587)
        self.assertEqual(aviso, "")

    def test_smtp_sin_host_cae_a_consola_con_aviso(self):
        transporte, aviso = crear_transporte({"transporte": "smtp", "smtp": {}})
        self.assertIsInstance(transporte, TransporteConsola)
        self.assertIn("host", aviso.casefold())

    def test_graph_incompleto_cae_a_consola_con_aviso(self):
        transporte, aviso = crear_transporte({"transporte": "graph", "graph": {"tenant_id": "x"}})
        self.assertIsInstance(transporte, TransporteConsola)
        self.assertIn("client_id", aviso)

    def test_graph_bien_configurado(self):
        transporte, aviso = crear_transporte({
            "transporte": "graph",
            "graph": {"tenant_id": "t", "client_id": "c", "client_secret": "s",
                      "usuario_envio": "catalogo@forus.pe"},
        })
        self.assertIsInstance(transporte, TransporteGraph)
        self.assertEqual(aviso, "")

    def test_transporte_desconocido_avisa(self):
        transporte, aviso = crear_transporte({"transporte": "paloma"})
        self.assertIsInstance(transporte, TransporteConsola)
        self.assertIn("paloma", aviso)

    def test_el_mensaje_smtp_lleva_texto_y_html(self):
        transporte = TransporteSMTP(host="smtp.forus.pe")
        mensaje = construir_mensaje(EVENTO_CAMBIO_ESTADO,
                                    contexto_desde_ticket(TICKET, etiquetas=ts.STATE_LABELS),
                                    ["a@forus.pe"])
        correo = transporte._mensaje(mensaje, "catalogo@forus.pe", "Catalogo")
        self.assertTrue(correo.is_multipart())
        tipos = {parte.get_content_type() for parte in correo.walk()}
        self.assertIn("text/plain", tipos)
        self.assertIn("text/html", tipos)

    def test_smtp_sin_host_lanza(self):
        with self.assertRaises(NotifyError):
            TransporteSMTP(host="")

    def test_desde_config(self):
        m = MotorNotificaciones.desde_config({
            "activo": True, "transporte": "consola", "remitente": "catalogo@forus.pe",
            "url_app": "https://app.forus.pe",
        })
        self.assertTrue(m.activo)
        self.assertEqual(m.remitente, "catalogo@forus.pe")


class TestAdaptador(unittest.TestCase):
    def _adaptador(self, **kwargs):
        opciones = dict(motor=motor_de_prueba(), etiquetas=ts.STATE_LABELS,
                        area_producto=["producto@forus.pe"])
        opciones.update(kwargs)
        return AdaptadorCorreoTickets(**opciones)

    def test_conserva_las_claves_historicas(self):
        adaptador = self._adaptador()
        registro = adaptador.notify(TICKET, "status_loading", ["a@forus.pe"], "mensaje",
                                    estado_anterior="ready_execute", estado_nuevo="loading")
        for clave in ["id", "event", "recipients", "message", "channel", "email_status", "read_by", "link"]:
            self.assertIn(clave, registro, clave)
        self.assertEqual(registro["link"], "ticket:CAT-2026-000123")

    def test_envia_cuando_el_estado_cambia(self):
        adaptador = self._adaptador()
        registro = adaptador.notify(TICKET, "status_loading", ["a@forus.pe"], "",
                                    estado_anterior="ready_execute", estado_nuevo="loading")
        self.assertEqual(registro["email_status"], RESULTADO_OK)
        self.assertEqual(len(adaptador.motor.transporte.enviados), 1)

    def test_no_envia_cuando_el_estado_no_cambia(self):
        adaptador = self._adaptador()
        registro = adaptador.notify(TICKET, "status_loading", ["a@forus.pe"], "",
                                    estado_anterior="loading", estado_nuevo="loading")
        self.assertEqual(registro["email_status"], RESULTADO_OMITIDO)
        self.assertEqual(adaptador.motor.transporte.enviados, [])

    def test_el_evento_de_precios_llega_al_area_de_producto(self):
        adaptador = self._adaptador()
        registro = adaptador.notify(TICKET, "solicitud_carga_precios", ["producto@forus.pe"], "",
                                    estado_anterior="sial_loaded", estado_nuevo="price_load_requested")
        self.assertIn("producto@forus.pe", registro["recipients"])
        self.assertIn("precios", registro["asunto"].casefold())

    def test_llama_al_registrador(self):
        registrados = []
        adaptador = self._adaptador(registrar=registrados.append)
        adaptador.notify(TICKET, "status_loading", ["a@forus.pe"], "",
                         estado_anterior="ready_execute", estado_nuevo="loading")
        self.assertEqual(len(registrados), 1)
        self.assertEqual(registrados[0]["resultado"], RESULTADO_OK)

    def test_si_el_registrador_revienta_el_aviso_sigue_valiendo(self):
        def registrador_roto(_registro):
            raise RuntimeError("auditoria caida")

        adaptador = self._adaptador(registrar=registrador_roto)
        registro = adaptador.notify(TICKET, "status_loading", ["a@forus.pe"], "",
                                    estado_anterior="ready_execute", estado_nuevo="loading")
        self.assertEqual(registro["email_status"], RESULTADO_OK)

    def test_con_cola_no_envia_en_linea(self):
        """Con cola, el transporte NO se toca: si no, el aviso sale dos veces."""
        encolados = []
        adaptador = self._adaptador(encolar=lambda *args: encolados.append(args))
        registro = adaptador.notify(TICKET, "status_loading", ["a@forus.pe"], "",
                                    estado_anterior="ready_execute", estado_nuevo="loading")
        self.assertEqual(len(encolados), 1)
        self.assertEqual(registro["detalle"], "encolado")
        self.assertEqual(adaptador.motor.transporte.enviados, [])

    def test_con_cola_el_adjunto_viaja_hasta_la_cola(self):
        encolados = []
        adaptador = self._adaptador(encolar=lambda *args: encolados.append(args))
        adaptador.notify(TICKET, "solicitud_carga_precios", ["producto@forus.pe"], "",
                         estado_anterior="sial_loaded", estado_nuevo="price_load_requested",
                         adjuntos=[{"nombre": "Carga_SIAL.xlsx", "contenido": b"PK\x03\x04datos"}])
        self.assertEqual(len(encolados), 1)
        self.assertEqual(encolados[0][-1][0]["nombre"], "Carga_SIAL.xlsx")

    def test_con_cola_tampoco_encola_lo_que_no_cambia(self):
        encolados = []
        adaptador = self._adaptador(encolar=lambda *args: encolados.append(args))
        adaptador.notify(TICKET, "status_loading", ["a@forus.pe"], "",
                         estado_anterior="loading", estado_nuevo="loading")
        self.assertEqual(encolados, [])


class TestIntegracionConTicketService(unittest.TestCase):
    """El correo tiene que salir solo, desde el propio servicio de solicitudes."""

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.motor = motor_de_prueba()
        self.registros = []
        self.adaptador = AdaptadorCorreoTickets(
            motor=self.motor, etiquetas=ts.STATE_LABELS,
            area_producto=["producto@forus.pe"], registrar=self.registros.append,
        )
        self.service = ts.TicketService(
            ts.LocalTicketStore(self.temp.name),
            notifier=self.adaptador,
            operator_users=["hugo.camara@forus.pe"],
            product_area_users=["producto@forus.pe"],
        )
        self.marca = ts.TicketService.actor("clara.gallastegui@forus.pe", ts.ROLE_BRAND, ["Columbia"])
        self.operador = ts.TicketService.actor("hugo.camara@forus.pe", ts.ROLE_OPERATOR)
        self.ticket = self.service.create_ticket(
            self.marca, brand="Columbia", sites=["Columbia.pe"], filename="input.xlsx",
            input_bytes=b"contenido", summary={"products": 40, "blocked": 0},
            model_colors=["IM5678-011", "IM5678-012"],
        )
        self.codigo = self.ticket["code"]

    def _hasta_carga(self):
        self.service.assign(self.operador, self.codigo, "hugo.camara@forus.pe")
        self.service.start_review(self.operador, self.codigo)
        self.service.approve(self.operador, self.codigo)
        self.service.run_dry_run(self.operador, self.codigo)
        return self.service.start_load(self.operador, self.codigo)

    def test_cada_transicion_manda_un_correo(self):
        antes = len(self.motor.transporte.enviados)
        self.service.assign(self.operador, self.codigo, "hugo.camara@forus.pe")
        self.assertGreater(len(self.motor.transporte.enviados), antes)

    def test_el_correo_dice_de_que_estado_a_que_estado(self):
        self.service.assign(self.operador, self.codigo, "hugo.camara@forus.pe")
        self.service.start_review(self.operador, self.codigo)
        ultimo = self.motor.transporte.enviados[-1]
        self.assertIn("Revisión Digital", ultimo["html"])
        self.assertIn("Asignada", ultimo["html"])

    def test_la_marca_recibe_el_aviso(self):
        self.service.assign(self.operador, self.codigo, "hugo.camara@forus.pe")
        destinatarios = set()
        for enviado in self.motor.transporte.enviados:
            destinatarios.update(enviado["destinatarios"])
        self.assertIn("clara.gallastegui@forus.pe", destinatarios)

    def test_el_historial_de_la_solicitud_guarda_cada_aviso(self):
        ticket = self.service.assign(self.operador, self.codigo, "hugo.camara@forus.pe")
        self.assertTrue(ticket["notifications"])
        self.assertEqual(ticket["notifications"][-1]["channel"], "email")

    def test_el_archivo_sial_viaja_adjunto_al_area_de_producto(self):
        """Lo que pidio Hugo: que Producto reciba el Excel, no solo el aviso."""
        excel = b"PK\x03\x04" + b"contenido de la hoja Carga Sial" * 20
        self._hasta_carga()
        ticket = self.service.complete_sial_load(
            self.operador, self.codigo, processed=120, model_colors=8,
            sial_bytes=excel, sial_filename="Carga_SIAL_COLUMBIA.xlsx",
        )
        self.assertEqual(ticket["sial"]["filename"], "Carga_SIAL_COLUMBIA.xlsx")
        self.assertTrue(ticket["sial"]["path"])
        # El archivo queda guardado en la solicitud, no en memoria de sesion.
        self.assertEqual(self.service.store.get_artifact(ticket["sial"]["path"]), excel)

        ticket = self.service.request_price_load(self.operador, self.codigo)
        self.assertTrue(ticket["price_load"]["attached"])
        precios = [e for e in self.motor.transporte.enviados
                   if "carga de precios pendiente" in e["asunto"].casefold()]
        self.assertEqual(len(precios), 1)
        self.assertEqual(len(precios[0]["adjuntos"]), 1)
        self.assertEqual(precios[0]["adjuntos"][0]["contenido"], excel)
        self.assertIn("Carga_SIAL_COLUMBIA.xlsx", precios[0]["html"])

    def test_sin_archivo_el_aviso_sale_igual(self):
        self._hasta_carga()
        self.service.complete_sial_load(self.operador, self.codigo)
        ticket = self.service.request_price_load(self.operador, self.codigo)
        self.assertFalse(ticket["price_load"]["attached"])
        precios = [e for e in self.motor.transporte.enviados
                   if "carga de precios pendiente" in e["asunto"].casefold()]
        self.assertEqual(len(precios), 1)
        self.assertEqual(precios[0]["adjuntos"], [])

    def test_la_solicitud_sigue_siendo_json(self):
        """Los bytes del Excel no pueden acabar dentro del ticket."""
        import json
        self._hasta_carga()
        self.service.complete_sial_load(self.operador, self.codigo,
                                        sial_bytes=b"PK\x03\x04xx", sial_filename="a.xlsx")
        ticket = self.service.request_price_load(self.operador, self.codigo)
        json.dumps(ticket)

    def test_carga_sial_y_solicitud_de_precios(self):
        self._hasta_carga()
        ticket = self.service.complete_sial_load(self.operador, self.codigo, processed=120, model_colors=8)
        self.assertEqual(ticket["status"], ts.STATE_SIAL_LOADED)
        self.assertEqual(ticket["sial"]["processed"], 120)
        self.assertEqual(ticket["sial"]["model_colors"], 8)

        ticket = self.service.request_price_load(self.operador, self.codigo, note="Precios de temporada")
        self.assertEqual(ticket["status"], ts.STATE_PRICE_REQUESTED)

        # Solo el aviso al Area de Producto. El de cambio de estado tambien
        # dice "precios" en el asunto, pero es otro correo y va a la marca.
        precios = [e for e in self.motor.transporte.enviados
                   if "carga de precios pendiente" in e["asunto"].casefold()]
        self.assertEqual(len(precios), 1)
        self.assertIn("producto@forus.pe", precios[0]["destinatarios"])
        for esperado in ["8", "120", "hugo.camara@forus.pe", "Precios de temporada", "Columbia"]:
            self.assertIn(esperado, precios[0]["html"], esperado)

    def test_la_marca_tambien_recibe_el_cambio_de_estado_al_pedir_precios(self):
        self._hasta_carga()
        self.service.complete_sial_load(self.operador, self.codigo)
        antes = len(self.motor.transporte.enviados)
        self.service.request_price_load(self.operador, self.codigo)
        nuevos = self.motor.transporte.enviados[antes:]
        destinatarios = set()
        for enviado in nuevos:
            destinatarios.update(enviado["destinatarios"])
        self.assertIn("clara.gallastegui@forus.pe", destinatarios)
        self.assertIn("producto@forus.pe", destinatarios)

    def test_los_dos_avisos_se_guardan_en_una_sola_escritura(self):
        self._hasta_carga()
        self.service.complete_sial_load(self.operador, self.codigo)
        antes = self.service.get_ticket(self.operador, self.codigo)
        ticket = self.service.request_price_load(self.operador, self.codigo)
        self.assertEqual(len(ticket["notifications"]) - len(antes["notifications"]), 2)

    def test_no_se_pueden_pedir_precios_sin_cerrar_el_sial(self):
        self._hasta_carga()
        with self.assertRaises(ts.TicketValidationError):
            self.service.request_price_load(self.operador, self.codigo)

    def test_sin_area_de_producto_no_se_puede_pedir(self):
        servicio = ts.TicketService(
            ts.LocalTicketStore(self.temp.name), notifier=self.adaptador,
            operator_users=["hugo.camara@forus.pe"], product_area_users=[],
        )
        self._hasta_carga()
        servicio.complete_sial_load(self.operador, self.codigo)
        with self.assertRaises(ts.TicketValidationError):
            servicio.request_price_load(self.operador, self.codigo)

    def test_la_cadena_completa_llega_a_validacion(self):
        self._hasta_carga()
        self.service.complete_sial_load(self.operador, self.codigo)
        self.service.request_price_load(self.operador, self.codigo)
        ticket = self.service.start_price_validation(self.operador, self.codigo)
        self.assertEqual(ticket["status"], ts.STATE_PRICE_VALIDATION)
        ticket = self.service.change_state(self.operador, self.codigo, ts.STATE_LOADING, "Validado")
        self.assertEqual(ticket["status"], ts.STATE_LOADING)

    # --- el cierre no puede llegar antes de tiempo -----------------------
    def _hasta_sial(self):
        self._hasta_carga()
        return self.service.complete_sial_load(self.operador, self.codigo,
                                               processed=120, model_colors=8)

    def test_no_se_completa_recien_terminado_el_sial(self):
        """El error que habia que corregir: cerrar sin precios cargados."""
        self._hasta_sial()
        with self.assertRaises(ts.TicketError):
            self.service.record_job_result(self.operador, self.codigo, success=True)
        with self.assertRaises(ts.TicketValidationError):
            self.service.finalize_request(self.operador, self.codigo)
        self.assertEqual(self.service.get_ticket(self.operador, self.codigo)["status"],
                         ts.STATE_SIAL_LOADED)

    def test_no_se_completa_esperando_precios(self):
        self._hasta_sial()
        self.service.request_price_load(self.operador, self.codigo)
        with self.assertRaises(ts.TicketError):
            self.service.finalize_request(self.operador, self.codigo)

    def test_no_se_completa_mientras_se_valida(self):
        self._hasta_sial()
        self.service.request_price_load(self.operador, self.codigo)
        self.service.start_price_validation(self.operador, self.codigo)
        with self.assertRaises(ts.TicketError):
            self.service.finalize_request(self.operador, self.codigo)

    def test_la_validacion_con_bloqueos_no_habilita_el_cierre(self):
        self._hasta_sial()
        self.service.request_price_load(self.operador, self.codigo)
        self.service.start_price_validation(self.operador, self.codigo)
        ticket = self.service.record_price_validation(
            self.operador, self.codigo,
            resultado={"revisados": 8, "conformes": 5, "bloqueos": 3,
                       "detalle": "3 modelo-color sin precio en Shopify"})
        self.assertEqual(ticket["status"], ts.STATE_PRICE_VALIDATION)
        self.assertEqual(ticket["price_check"]["bloqueos"], 3)
        with self.assertRaises(ts.TicketError):
            self.service.finalize_request(self.operador, self.codigo)

    def test_el_recorrido_completo_llega_a_completada(self):
        self._hasta_sial()
        self.service.request_price_load(self.operador, self.codigo)
        self.service.start_price_validation(self.operador, self.codigo)
        ticket = self.service.record_price_validation(
            self.operador, self.codigo,
            resultado={"revisados": 8, "conformes": 8, "bloqueos": 0})
        self.assertEqual(ticket["status"], ts.STATE_READY_CLOSE)

        ticket = self.service.finalize_request(self.operador, self.codigo, note="Todo conforme")
        self.assertEqual(ticket["status"], ts.STATE_COMPLETED)
        self.assertEqual(ticket["result"]["closed_by"], "hugo.camara@forus.pe")
        self.assertTrue(ticket["result"]["closed_at"])
        self.assertTrue(ticket["resolved_at"])

    def test_el_cierre_manda_el_correo_final_a_la_marca(self):
        self._hasta_sial()
        self.service.request_price_load(self.operador, self.codigo)
        self.service.start_price_validation(self.operador, self.codigo)
        self.service.record_price_validation(self.operador, self.codigo,
                                             resultado={"revisados": 8, "conformes": 8, "bloqueos": 0})
        antes = len(self.motor.transporte.enviados)
        self.service.finalize_request(self.operador, self.codigo)
        finales = [e for e in self.motor.transporte.enviados[antes:]
                   if "carga completada" in e["asunto"].casefold()]
        self.assertEqual(len(finales), 1)
        self.assertIn("clara.gallastegui@forus.pe", finales[0]["destinatarios"])

    def test_los_correos_de_la_marca_van_a_todo_su_equipo(self):
        servicio = ts.TicketService(
            ts.LocalTicketStore(self.temp.name), notifier=self.adaptador,
            operator_users=["hugo.camara@forus.pe"],
            brand_recipients=lambda marca: ["equipo.columbia@forus.pe", "jefe.columbia@forus.pe"],
        )
        servicio.assign(self.operador, self.codigo, "hugo.camara@forus.pe")
        destinatarios = set()
        for enviado in self.motor.transporte.enviados:
            destinatarios.update(enviado["destinatarios"])
        self.assertIn("equipo.columbia@forus.pe", destinatarios)
        self.assertIn("jefe.columbia@forus.pe", destinatarios)
        self.assertIn("clara.gallastegui@forus.pe", destinatarios)

    def test_un_resolver_de_marca_roto_no_tumba_la_transicion(self):
        def roto(_marca):
            raise RuntimeError("secrets caido")

        servicio = ts.TicketService(
            ts.LocalTicketStore(self.temp.name), notifier=self.adaptador,
            operator_users=["hugo.camara@forus.pe"], brand_recipients=roto,
        )
        ticket = servicio.assign(self.operador, self.codigo, "hugo.camara@forus.pe")
        self.assertEqual(ticket["status"], ts.STATE_ASSIGNED)

    def test_la_marca_no_puede_cerrar_la_carga_sial(self):
        self._hasta_carga()
        with self.assertRaises(ts.TicketPermissionError):
            self.service.complete_sial_load(self.marca, self.codigo)

    def test_todo_envio_queda_registrado(self):
        self.service.assign(self.operador, self.codigo, "hugo.camara@forus.pe")
        self.assertTrue(self.registros)
        ultimo = self.registros[-1]
        for clave in ["solicitud", "marca", "estado_anterior", "estado_nuevo", "responsable", "resultado"]:
            self.assertIn(clave, ultimo, clave)
        self.assertEqual(ultimo["solicitud"], self.codigo)

    def test_un_notificador_roto_no_tumba_la_transicion(self):
        class Roto:
            def notify(self, *args, **kwargs):
                raise RuntimeError("caido")

        servicio = ts.TicketService(
            ts.LocalTicketStore(self.temp.name), notifier=Roto(),
            operator_users=["hugo.camara@forus.pe"],
        )
        ticket = servicio.assign(self.operador, self.codigo, "hugo.camara@forus.pe")
        self.assertEqual(ticket["status"], ts.STATE_ASSIGNED)

    def test_un_notificador_con_la_firma_antigua_sigue_funcionando(self):
        class Antiguo:
            def __init__(self):
                self.vistos = []

            def notify(self, ticket, event, recipients=None, message=""):
                self.vistos.append(event)
                return {"id": "1", "event": event, "recipients": list(recipients or [])}

        antiguo = Antiguo()
        servicio = ts.TicketService(
            ts.LocalTicketStore(self.temp.name), notifier=antiguo,
            operator_users=["hugo.camara@forus.pe"],
        )
        servicio.assign(self.operador, self.codigo, "hugo.camara@forus.pe")
        self.assertTrue(antiguo.vistos)


if __name__ == "__main__":
    unittest.main(verbosity=2)
