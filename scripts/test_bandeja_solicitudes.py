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
    """Registra las llamadas en vez de tocar el almacenamiento.

    `falla` rompe TODOS los metodos; `falla_en` rompe solo uno, que es lo que
    hace falta para probar un atajo que se corta a mitad de la cadena.
    """

    def __init__(self, falla="", falla_en=""):
        self.llamadas = []
        self.falla = falla
        self.falla_en = falla_en

    def _registrar(self, nombre, *args, **kwargs):
        if self.falla:
            raise app.TicketError(self.falla)
        if self.falla_en and nombre == self.falla_en:
            raise app.TicketError(f"{nombre} no se puede aplicar ahora.")
        self.llamadas.append((nombre, args, kwargs))

    def run_dry_run(self, *a, **k):
        self._registrar("run_dry_run", *a, **k)

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
        """El atajo va JUNTO a la etapa que cubre, no al final de la lista."""
        orden = app.ORDEN_ACCIONES_LOTE
        self.assertLess(orden.index("aceptar_carga"), orden.index("ejecutar_carga"))
        self.assertLess(orden.index("ejecutar_carga"), orden.index("finalizar"))
        for atajo, cubierta in (("aceptar_carga", "aprobar"), ("ejecutar_carga", "ejecutar")):
            self.assertLess(orden.index(atajo), orden.index(cubierta), atajo)
        self.assertLess(orden.index("finalizar"), orden.index("finalizar_solicitud"))

    def test_toda_accion_rapida_tiene_su_lugar(self):
        # Si se agrega una accion principal nueva al flujo y no se ordena aqui,
        # el boton de lote saldria al final sin criterio. Vale igual para los
        # atajos, que ahora tambien pueden ser la accion rapida de un ticket.
        principales = {
            a["clave"] for a in flujo.ACCIONES
            if a.get("principal") and not a.get("pide_comentario") and not a.get("requiere_archivo")
        }
        principales |= {a["clave"] for a in flujo.ATAJOS}
        self.assertTrue(principales <= set(app.ORDEN_ACCIONES_LOTE), principales - set(app.ORDEN_ACCIONES_LOTE))


class TestAccionRapida(unittest.TestCase):
    """Antes avanzaba de una en una; ahora prefiere el atajo cuando existe.

    Es un cambio pedido: llegar de "recien llegada" a "cargando" costaba cinco
    clics y ninguno era una decision distinta de la anterior. La garantia de
    que no se salta ningun paso NO se afloja -- se mueve a
    `test_el_atajo_pasa_por_los_mismos_pasos`, que comprueba que el atajo
    ejecuta exactamente las mismas acciones del flujo, en el mismo orden.
    """

    def test_una_sin_asignar_ofrece_aceptar_carga(self):
        accion = app._accion_rapida(ticket(flujo.PENDING_ASSIGNMENT), OPERADOR)
        self.assertIsNotNone(accion)
        self.assertEqual(accion["clave"], "aceptar_carga")

    def test_el_atajo_pasa_por_los_mismos_pasos(self):
        """Encadenar no es saltarse: se ejecutan las mismas acciones, en orden."""
        accion = app._accion_rapida(ticket(flujo.PENDING_ASSIGNMENT), OPERADOR)
        self.assertEqual([p["clave"] for p in accion["pasos_resueltos"]],
                         ["tomar", "revisar", "aprobar"])

    def test_la_cadena_avanza_hasta_donde_puede(self):
        esperado = [
            # Sin asignar todavia: el atajo arranca por "tomar".
            (flujo.PENDING_ASSIGNMENT, "aceptar_carga", ""),
            (flujo.ASSIGNED, "aceptar_carga", OPERADOR["user"]),
            # Un solo paso pendiente: la accion suelta ya dice lo mismo.
            (flujo.DIGITAL_REVIEW, "aprobar", OPERADOR["user"]),
            (flujo.LOAD_APPROVED, "ejecutar_carga", OPERADOR["user"]),
            (flujo.READY_EXECUTE, "ejecutar", OPERADOR["user"]),
            # La cadena de cierre NO se ataja: cada paso espera algo real.
            (flujo.LOADING, "finalizar", OPERADOR["user"]),
            (flujo.SIAL_LOADED, "solicitar_precios", OPERADOR["user"]),
            (flujo.PRICE_REQUESTED, "validar_precio_stock", OPERADOR["user"]),
            (flujo.READY_CLOSE, "finalizar_solicitud", OPERADOR["user"]),
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


class TestEjecutarAtajo(unittest.TestCase):
    """Un atajo ejecuta varias acciones del flujo con un solo clic.

    Lo importante no es que funcione cuando todo va bien, sino que cuando algo
    falla a mitad de camino la solicitud quede en un estado intermedio VALIDO y
    el mensaje diga que se alcanzo a aplicar. Un atajo que falla en silencio
    deja al usuario sin saber si tiene que repetir todo o solo el final.
    """

    def _atajo(self, estado, clave="aceptar_carga"):
        pasos = flujo.pasos_del_atajo(clave, estado, "operator")
        atajo = dict(flujo.ATAJO_POR_CLAVE[clave])
        atajo["pasos_resueltos"] = pasos
        return atajo

    def test_aceptar_carga_llama_a_los_tres_metodos_en_orden(self):
        servicio = _ServicioFalso()
        atajo = self._atajo(flujo.PENDING_ASSIGNMENT)
        ok, mensaje = app._ejecutar_accion_ticket(servicio, OPERADOR, "CAT-1", atajo)
        self.assertTrue(ok, mensaje)
        self.assertEqual([c[0] for c in servicio.llamadas],
                         ["assign", "start_review", "approve"])

    def test_ejecutar_carga_corre_la_validacion_previa_antes_de_cargar(self):
        servicio = _ServicioFalso()
        atajo = self._atajo(flujo.LOAD_APPROVED, "ejecutar_carga")
        ok, mensaje = app._ejecutar_accion_ticket(servicio, OPERADOR, "CAT-1", atajo)
        self.assertTrue(ok, mensaje)
        self.assertEqual([c[0] for c in servicio.llamadas], ["run_dry_run", "start_load"])

    def test_tomar_sigue_asignando_a_quien_pulsa(self):
        """El primer paso del atajo no pierde el trato especial de "tomar"."""
        servicio = _ServicioFalso()
        atajo = self._atajo(flujo.PENDING_ASSIGNMENT)
        app._ejecutar_accion_ticket(servicio, OPERADOR, "CAT-1", atajo)
        nombre, args, _ = servicio.llamadas[0]
        self.assertEqual(nombre, "assign")
        self.assertEqual(args[-1], OPERADOR["user"])

    def test_si_falla_el_primer_paso_no_se_ejecuta_ninguno_mas(self):
        servicio = _ServicioFalso(falla_en="assign")
        atajo = self._atajo(flujo.PENDING_ASSIGNMENT)
        ok, mensaje = app._ejecutar_accion_ticket(servicio, OPERADOR, "CAT-1", atajo)
        self.assertFalse(ok)
        self.assertEqual(servicio.llamadas, [])
        self.assertNotIn("Se aplicó", mensaje)

    def test_si_falla_a_mitad_dice_lo_que_alcanzo_a_aplicar(self):
        servicio = _ServicioFalso(falla_en="approve")
        atajo = self._atajo(flujo.PENDING_ASSIGNMENT)
        ok, mensaje = app._ejecutar_accion_ticket(servicio, OPERADOR, "CAT-1", atajo)
        self.assertFalse(ok)
        # Los dos primeros SI se aplicaron: la solicitud queda en revision.
        self.assertEqual([c[0] for c in servicio.llamadas], ["assign", "start_review"])
        self.assertIn("Se aplicó", mensaje)
        self.assertIn("Tomar solicitud", mensaje)

    def test_un_atajo_sin_pasos_no_toca_el_servicio(self):
        servicio = _ServicioFalso()
        atajo = dict(flujo.ATAJO_POR_CLAVE["aceptar_carga"])
        atajo["pasos_resueltos"] = []
        ok, mensaje = app._ejecutar_accion_ticket(servicio, OPERADOR, "CAT-1", atajo)
        self.assertFalse(ok)
        self.assertEqual(servicio.llamadas, [])

    def test_el_mensaje_de_exito_nombra_cada_paso(self):
        servicio = _ServicioFalso()
        atajo = self._atajo(flujo.PENDING_ASSIGNMENT)
        _, mensaje = app._ejecutar_accion_ticket(servicio, OPERADOR, "CAT-1", atajo)
        for etiqueta in ("Tomar solicitud", "Aprobar para carga"):
            self.assertIn(etiqueta, mensaje)


class TestNavegacionAutomatica(unittest.TestCase):
    """Aceptar una carga tiene que dejar la app EN la pantalla de carga.

    Antes habia que ir a la barra lateral y elegir "Carga completa" a mano: la
    solicitud quedaba aprobada y el usuario, en la bandeja, sin nada que hacer
    ahi.
    """

    def setUp(self):
        app.st.session_state.clear()

    def test_deja_marcada_la_pantalla_y_el_modo(self):
        app.ir_a_carga_completa()
        self.assertEqual(app.st.session_state["operation_area_choice"], "Carga de catálogo")
        self.assertEqual(app.st.session_state["operation_mode_choice"], "Carga completa")

    def test_los_valores_son_los_mismos_que_usa_el_menu(self):
        """Si no coinciden, la barra lateral queda marcada en otra opcion."""
        fuente = (ROOT / "app_matrixify.py").read_text(encoding="utf-8-sig")
        self.assertIn('"operation_area_choice": "Carga de catálogo"', fuente)

    def test_preselecciona_la_solicitud_aceptada(self):
        app.ir_a_carga_completa("CAT-2026-000012")
        self.assertEqual(app.st.session_state["carga_solicitud_preseleccionada"],
                         "CAT-2026-000012")

    def test_sin_codigo_no_preselecciona_nada(self):
        app.ir_a_carga_completa("")
        self.assertNotIn("carga_solicitud_preseleccionada", app.st.session_state)


class TestEtiquetaDeSolicitudParaCarga(unittest.TestCase):
    """La etiqueta del selector tiene que distinguir aprobada de en curso.

    La lista mezcla las dos: sin el estado, dos lineas identicas pueden ser una
    lista para ejecutar y una que ya se cargo.
    """

    def test_una_aprobada_se_marca_como_aprobada(self):
        etiqueta = app.etiqueta_solicitud_para_carga(
            {"code": "CAT-1", "brand": "Columbia", "summary": {"products": 12},
             "requested_by": "ana", "status": flujo.LOAD_APPROVED})
        self.assertTrue(etiqueta.startswith("[APROBADA]"), etiqueta)
        self.assertIn("CAT-1", etiqueta)
        self.assertIn("12 productos", etiqueta)

    def test_una_en_curso_se_marca_distinto(self):
        etiqueta = app.etiqueta_solicitud_para_carga(
            {"code": "CAT-2", "brand": "Vans", "status": flujo.PRICE_REQUESTED})
        self.assertTrue(etiqueta.startswith("[EN CURSO]"), etiqueta)

    def test_las_aprobadas_van_primero(self):
        aprobadas = [flujo.LOAD_APPROVED, flujo.PREPARING, flujo.DRY_RUN, flujo.READY_EXECUTE]
        for estado in aprobadas:
            self.assertTrue(app.solicitud_esta_aprobada_sin_cargar({"status": estado}), estado)
        for estado in (flujo.LOADING, flujo.SIAL_LOADED, flujo.PRICE_REQUESTED, flujo.FAILED):
            self.assertFalse(app.solicitud_esta_aprobada_sin_cargar({"status": estado}), estado)

    def test_un_ticket_vacio_no_revienta(self):
        self.assertFalse(app.solicitud_esta_aprobada_sin_cargar({}))
        self.assertFalse(app.solicitud_esta_aprobada_sin_cargar(None))
        self.assertIn("[EN CURSO]", app.etiqueta_solicitud_para_carga({}))


class TestStepperDiceLaVerdad(unittest.TestCase):
    """El estado de cada paso sale de `current_step`, no del indice.

    Antes el paso 2 decia siempre "OK" y el 3 siempre "Revisar": con la
    pantalla recien abierta y sin un archivo cargado, la barra afirmaba que
    BigQuery ya estaba resuelto y que habia algo que revisar.
    """

    def _dibujado(self, paso):
        capturado = {}
        original = app.render_html
        app.render_html = lambda html, **k: capturado.setdefault("html", html)
        try:
            app.render_stepper({"primary_color": "#000", "accent_color": "#111"}, current_step=paso)
        finally:
            app.render_html = original
        return capturado.get("html", "")

    def test_en_el_primer_paso_nada_esta_ok(self):
        html = self._dibujado(1)
        self.assertEqual(html.count(">OK<"), 0)
        self.assertEqual(html.count(">Actual<"), 1)
        self.assertEqual(html.count(">Pend.<"), 3)

    def test_no_queda_ningun_revisar_fijo(self):
        for paso in (1, 2, 3, 4):
            self.assertNotIn(">Revisar<", self._dibujado(paso), paso)

    def test_los_pasos_anteriores_quedan_ok(self):
        html = self._dibujado(3)
        self.assertEqual(html.count(">OK<"), 2)
        self.assertEqual(html.count(">Actual<"), 1)
        self.assertEqual(html.count(">Pend.<"), 1)

    def test_en_el_ultimo_paso_no_queda_nada_pendiente(self):
        html = self._dibujado(4)
        self.assertEqual(html.count(">OK<"), 3)
        self.assertEqual(html.count(">Actual<"), 1)
        self.assertEqual(html.count(">Pend.<"), 0)


if __name__ == "__main__":
    unittest.main(verbosity=2)
