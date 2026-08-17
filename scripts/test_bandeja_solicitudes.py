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
    def test_la_tarjeta_entera_es_clickeable(self):
        html = app._ticket_card_html(ticket(flujo.PENDING_ASSIGNMENT))
        self.assertIn('<a class="ticket-card-hit"', html)
        self.assertIn('href="?ticket=CAT-2026-000031"', html)
        self.assertIn('target="_self"', html)

    def test_el_enlace_va_vacio_y_la_raiz_es_un_div(self):
        """Regresión: la tarjeta se rompió en cajas sueltas.

        El renderizador de Markdown de Streamlit cierra los elementos en línea
        antes del primer bloque. Con los <div> envueltos en un <a>, cada bloque
        salía como una caja aparte, apilada. El enlace tiene que ir vacío y
        estirado por CSS sobre una tarjeta que sigue siendo un <div>.
        """
        html = app._ticket_card_html(ticket(flujo.PENDING_ASSIGNMENT))
        self.assertTrue(html.startswith('<div class="ticket-request-card'), html[:60])
        self.assertTrue(html.rstrip().endswith("</div>"))
        self.assertIn("></a>", html, "el <a> debe cerrarse vacío, sin contenido dentro")
        # Ningún <div> puede quedar entre la apertura y el cierre del enlace.
        entre = html[html.index("<a class="):html.index("</a>")]
        self.assertNotIn("<div", entre)
        self.assertNotIn("<span", entre)

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

    def test_el_codigo_va_escapado_en_la_url(self):
        html = app._ticket_card_html(ticket(flujo.PENDING_ASSIGNMENT, codigo="CAT 2026/01"))
        self.assertIn("href=\"?ticket=CAT+2026%2F01\"", html)


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
