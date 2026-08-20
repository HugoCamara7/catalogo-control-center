"""Pruebas de la bandeja de solicitudes: tarjeta clickeable, acciones y lote.

Origen: la gestión pedía demasiados clicks. Para abrir una solicitud había que
elegirla en un selectbox debajo de la rejilla; las transiciones de estado
estaban duplicadas (barra de acciones arriba y "Gestión interna" abajo, con
reglas distintas); no se podía trabajar sobre varias a la vez; y "Completar
carga" estaba deshabilitado si el job no registraba productos procesados.

Ejecutar:  python scripts/test_bandeja_solicitudes.py
"""
import sys
import types
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def _identity_decorator(*args, **kwargs):
    if args and callable(args[0]):
        return args[0]

    def _decorator(func):
        return func

    return _decorator


class _Secrets(dict):
    def get(self, key, default=None):
        return super().get(key, default if default is not None else {})


class _StreamlitStub(types.ModuleType):
    session_state = {}
    secrets = _Secrets()
    cache_data = staticmethod(_identity_decorator)
    cache_resource = staticmethod(_identity_decorator)

    def __getattr__(self, name):
        def _noop(*args, **kwargs):
            return None

        return _noop


if "streamlit" not in sys.modules:
    stub = _StreamlitStub("streamlit")
    comp = types.ModuleType("streamlit.components")
    comp_v1 = types.ModuleType("streamlit.components.v1")
    stub.__path__ = []
    comp.__path__ = []
    comp.v1 = comp_v1
    stub.components = comp
    sys.modules["streamlit"] = stub
    sys.modules["streamlit.components"] = comp
    sys.modules["streamlit.components.v1"] = comp_v1

import app_matrixify as app  # noqa: E402
import engines.ticket_flow as flujo  # noqa: E402

OPERADOR = {"user": "hugo.camara@forus.pe", "role": "operator"}


def ticket(estado, asignada="", codigo="CAT-2026-000031", prioridad="urgent"):
    return {
        "code": codigo,
        "status": estado,
        "assignee": asignada,
        "brand": "Columbia",
        "priority": prioridad,
        "requester": "alejandro.mosqueira@forus.pe",
        "summary": {"products": 16},
        "created_at": "2026-08-17T10:00:00+00:00",
    }


class _ServicioFalso:
    """Registra las llamadas en vez de tocar el almacenamiento."""

    def __init__(self, falla=""):
        self.llamadas = []
        self.falla = falla

    def _registrar(self, nombre, *args, **kwargs):
        if self.falla:
            raise app.TicketError(self.falla)
        self.llamadas.append((nombre, args, kwargs))

    def assign(self, *a, **k):
        self._registrar("assign", *a, **k)

    def start_review(self, *a, **k):
        self._registrar("start_review", *a, **k)

    def approve(self, *a, **k):
        self._registrar("approve", *a, **k)

    def start_load(self, *a, **k):
        self._registrar("start_load", *a, **k)

    def record_job_result(self, *a, **k):
        self._registrar("record_job_result", *a, **k)

    def request_correction(self, *a, **k):
        self._registrar("request_correction", *a, **k)


class TestTarjetaClickeable(unittest.TestCase):
    def test_la_tarjeta_no_lleva_enlaces(self):
        """Regresión: pulsar una solicitud cerraba la sesión.

        La tarjeta llevaba dentro un <a href="?ticket=CODIGO"> estirado por
        CSS. Eso no es un rerun: el navegador carga la página de cero,
        Streamlit abre una sesión nueva, `st.session_state` queda vacío y
        `require_login` devuelve al login. Lo que se pulsa tiene que ser un
        `st.button`, no un enlace, así que en el HTML no puede quedar ninguno.
        """
        html = app._ticket_card_html(ticket(flujo.PENDING_ASSIGNMENT))
        self.assertNotIn("<a ", html)
        self.assertNotIn("href=", html)
        self.assertNotIn("?ticket=", html)
        self.assertNotIn("ticket-card-hit", html)

    def test_la_raiz_es_un_div(self):
        """El renderizador de Markdown de Streamlit cierra los elementos en
        línea antes del primer bloque: la tarjeta tiene que ser un <div> de
        principio a fin o sale rota en cajas sueltas."""
        html = app._ticket_card_html(ticket(flujo.PENDING_ASSIGNMENT))
        self.assertTrue(html.startswith('<div class="ticket-request-card'), html[:60])
        self.assertTrue(html.rstrip().endswith("</div>"))

    def test_la_clave_css_soporta_codigos_con_simbolos(self):
        """La clave del contenedor acaba en un nombre de clase (`st-key-...`),
        así que no puede llevar espacios ni barras."""
        self.assertEqual(app._clave_css("CAT-2026-000031"), "CAT-2026-000031")
        self.assertEqual(app._clave_css("CAT 2026/01"), "CAT-2026-01")
        self.assertEqual(app._clave_css(""), "sin-codigo")

    def test_trae_los_badges_de_estado_prioridad_y_responsable(self):
        html = app._ticket_card_html(ticket(flujo.PENDING_ASSIGNMENT, asignada="hugo.camara@forus.pe"))
        self.assertIn("Pendiente de revisión", html)
        self.assertIn("Urgente", html)
        self.assertIn("hugo.camara@forus.pe", html)

    def test_marca_las_que_no_tienen_responsable(self):
        html = app._ticket_card_html(ticket(flujo.PENDING_ASSIGNMENT))
        self.assertIn("Sin asignar", html)
        self.assertIn("tb-user sin", html)

    def test_la_seleccionada_se_resalta(self):
        self.assertIn("selected", app._ticket_card_html(ticket(flujo.PENDING_ASSIGNMENT), selected=True))
        self.assertNotIn("selected", app._ticket_card_html(ticket(flujo.PENDING_ASSIGNMENT)))

    def test_el_codigo_va_escapado_en_el_html(self):
        html = app._ticket_card_html(ticket(flujo.PENDING_ASSIGNMENT, codigo="CAT <2026>"))
        self.assertIn("CAT &lt;2026&gt;", html)
        self.assertNotIn("CAT <2026>", html)


class TestControlesEnLaTarjeta(unittest.TestCase):
    """La casilla y la accion rapida van dentro de la tarjeta, abajo."""

    def test_reserva_la_franja_cuando_hay_controles(self):
        html = app._ticket_card_html(ticket(flujo.PENDING_ASSIGNMENT), con_controles=True)
        self.assertIn("con-controles", html)

    def test_sin_controles_no_reserva_nada(self):
        html = app._ticket_card_html(ticket(flujo.PENDING_ASSIGNMENT))
        self.assertNotIn("con-controles", html)


class TestOrdenDelLote(unittest.TestCase):
    def test_las_etapas_salen_en_el_orden_del_recorrido(self):
        self.assertEqual(
            app.ORDEN_ACCIONES_LOTE[:5],
            ["tomar", "revisar", "aprobar", "ejecutar", "finalizar"],
        )

    def test_toda_accion_rapida_tiene_su_lugar(self):
        # Si se agrega una accion principal nueva al flujo y no se ordena aqui,
        # el boton de lote saldria al final sin criterio.
        principales = {
            a["clave"] for a in flujo.ACCIONES
            if a.get("principal") and not a.get("pide_comentario") and not a.get("requiere_archivo")
        }
        self.assertTrue(principales <= set(app.ORDEN_ACCIONES_LOTE), principales - set(app.ORDEN_ACCIONES_LOTE))


class TestAccionRapida(unittest.TestCase):
    def test_una_sin_asignar_ofrece_tomar(self):
        accion = app._accion_rapida(ticket(flujo.PENDING_ASSIGNMENT), OPERADOR)
        self.assertIsNotNone(accion)
        self.assertEqual(accion["clave"], "tomar")

    def test_la_cadena_avanza_de_una_en_una(self):
        esperado = [
            # Sin asignar todavia: por eso "tomar" es lo primero.
            (flujo.PENDING_ASSIGNMENT, "tomar", ""),
            (flujo.ASSIGNED, "revisar", OPERADOR["user"]),
            (flujo.DIGITAL_REVIEW, "aprobar", OPERADOR["user"]),
            (flujo.LOAD_APPROVED, "ejecutar", OPERADOR["user"]),
            (flujo.LOADING, "finalizar", OPERADOR["user"]),
        ]
        for estado, clave, asignada in esperado:
            accion = app._accion_rapida(ticket(estado, asignada=asignada), OPERADOR)
            self.assertIsNotNone(accion, f"{estado} deberia tener accion rapida")
            self.assertEqual(accion["clave"], clave, estado)

    def test_completar_carga_es_el_cierre_manual(self):
        accion = app._accion_rapida(ticket(flujo.LOADING, asignada=OPERADOR["user"]), OPERADOR)
        self.assertEqual(accion["etiqueta"], "Completar carga")

    def test_no_ofrece_atajo_a_lo_que_pide_comentario(self):
        # "Observar" y "Cancelar" exigen texto: no pueden ser de un click.
        accion = app._accion_rapida(ticket(flujo.OBSERVED, asignada=OPERADOR["user"]), OPERADOR)
        self.assertIsNone(accion)

    def test_una_solicitud_cerrada_no_ofrece_atajo(self):
        self.assertIsNone(app._accion_rapida(ticket(flujo.COMPLETED), OPERADOR))


class TestEjecutarAccion(unittest.TestCase):
    def test_tomar_asigna_a_quien_pulsa(self):
        servicio = _ServicioFalso()
        accion = app._accion_rapida(ticket(flujo.PENDING_ASSIGNMENT), OPERADOR)
        ok, _ = app._ejecutar_accion_ticket(servicio, OPERADOR, "CAT-1", accion)
        self.assertTrue(ok)
        nombre, args, _ = servicio.llamadas[0]
        self.assertEqual(nombre, "assign")
        self.assertEqual(args[2], OPERADOR["user"], "se asigna al usuario que ejecuta")

    def test_completar_carga_no_depende_de_cantidades(self):
        servicio = _ServicioFalso()
        accion = app._accion_rapida(ticket(flujo.LOADING, asignada=OPERADOR["user"]), OPERADOR)
        ok, _ = app._ejecutar_accion_ticket(servicio, OPERADOR, "CAT-1", accion)
        self.assertTrue(ok)
        nombre, _, kwargs = servicio.llamadas[0]
        self.assertEqual(nombre, "record_job_result")
        self.assertTrue(kwargs["success"])
        # Sin "processed" ni "successful": el cierre es del responsable.
        self.assertNotIn("processed", kwargs["result"])
        self.assertNotIn("successful", kwargs["result"])

    def test_exige_comentario_cuando_toca(self):
        servicio = _ServicioFalso()
        observar = next(a for a in flujo.ACCIONES if a["clave"] == "observar")
        ok, mensaje = app._ejecutar_accion_ticket(servicio, OPERADOR, "CAT-1", observar, "")
        self.assertFalse(ok)
        self.assertIn("comentario", mensaje.lower())
        self.assertEqual(servicio.llamadas, [], "no debe llamar al servicio")

    def test_el_error_del_servicio_vuelve_como_mensaje(self):
        servicio = _ServicioFalso(falla="No tienes permiso")
        accion = app._accion_rapida(ticket(flujo.PENDING_ASSIGNMENT), OPERADOR)
        ok, mensaje = app._ejecutar_accion_ticket(servicio, OPERADOR, "CAT-1", accion)
        self.assertFalse(ok)
        self.assertIn("No tienes permiso", mensaje)


class TestPaginacion(unittest.TestCase):
    def test_muestra_nueve_por_pagina(self):
        self.assertEqual(app.TICKETS_POR_PAGINA, 9)

    def test_reparte_las_paginas(self):
        for total, paginas in [(0, 1), (1, 1), (9, 1), (10, 2), (18, 2), (19, 3)]:
            calculadas = max(1, (total + app.TICKETS_POR_PAGINA - 1) // app.TICKETS_POR_PAGINA)
            self.assertEqual(calculadas, paginas, f"{total} solicitudes")


if __name__ == "__main__":
    unittest.main(verbosity=2)
