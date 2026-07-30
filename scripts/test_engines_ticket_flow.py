"""Pruebas del motor engines/ticket_flow.py

Lo critico: ningun estado historico puede quedar sin traduccion, y ningun rol
puede ver una accion que ticket_system le negaria.

Ejecutar:  python scripts/test_engines_ticket_flow.py
"""
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import ticket_system as ts
from engines import ticket_flow as flujo


class TestArquitectura(unittest.TestCase):
    def test_no_importa_streamlit(self):
        fuente = (ROOT / "engines" / "ticket_flow.py").read_text(encoding="utf-8")
        self.assertNotIn("import streamlit", fuente)


class TestCompatibilidadHistorica(unittest.TestCase):
    """Ninguna solicitud vieja puede quedarse sin estado visible."""

    def _estados_internos(self):
        return {
            valor for nombre, valor in vars(ts).items()
            if nombre.startswith("STATE_") and isinstance(valor, str)
        }

    def test_todos_los_estados_de_ticket_system_estan_mapeados(self):
        faltan = sorted(self._estados_internos() - set(flujo.MAPA))
        self.assertEqual(faltan, [], f"estados sin mapear: {faltan}")

    def test_el_mapa_no_inventa_estados(self):
        sobran = sorted(set(flujo.MAPA) - self._estados_internos())
        self.assertEqual(sobran, [], f"estados que no existen en ticket_system: {sobran}")

    def test_son_19_estados(self):
        self.assertEqual(len(flujo.MAPA), 19)

    def test_un_estado_desconocido_no_revienta(self):
        self.assertEqual(flujo.estado_visible("estado_de_2019"), flujo.PENDIENTE)
        self.assertEqual(flujo.estado_visible(""), flujo.PENDIENTE)
        self.assertEqual(flujo.estado_visible(None), flujo.PENDIENTE)

    def test_los_alias_de_compatibilidad_funcionan(self):
        for alias in [ts.STATE_PENDING, ts.STATE_REVIEW, ts.STATE_CORRECTED, ts.STATE_APPROVED]:
            self.assertIn(alias, flujo.MAPA, alias)


class TestEstadosVisibles(unittest.TestCase):
    def test_son_cinco(self):
        self.assertEqual(len(flujo.ETIQUETAS), 5)

    def test_el_flujo_pedido(self):
        self.assertEqual(flujo.estado_visible(ts.STATE_PENDING_ASSIGNMENT), flujo.PENDIENTE)
        self.assertEqual(flujo.estado_visible(ts.STATE_LOAD_APPROVED), flujo.LISTA)
        self.assertEqual(flujo.estado_visible(ts.STATE_LOADING), flujo.EJECUCION)
        self.assertEqual(flujo.estado_visible(ts.STATE_COMPLETED), flujo.FINALIZADA)
        self.assertEqual(flujo.estado_visible(ts.STATE_OBSERVED), flujo.OBSERVADA)

    def test_los_terminales_negativos_no_quedan_como_pendientes(self):
        for estado in [ts.STATE_REJECTED, ts.STATE_CANCELED]:
            self.assertEqual(flujo.estado_visible(estado), flujo.FINALIZADA, estado)

    def test_fallida_pide_atencion(self):
        self.assertEqual(flujo.estado_visible(ts.STATE_FAILED), flujo.OBSERVADA)

    def test_el_matiz_conserva_la_informacion(self):
        self.assertIn("rechazada", flujo.etiqueta(ts.STATE_REJECTED))
        self.assertIn("cancelada", flujo.etiqueta(ts.STATE_CANCELED))
        self.assertIn("observaciones", flujo.etiqueta(ts.STATE_COMPLETED_OBS))
        self.assertEqual(flujo.etiqueta(ts.STATE_COMPLETED), "Finalizada")

    def test_paso_en_la_barra(self):
        self.assertEqual(flujo.paso_actual(ts.STATE_PENDING_ASSIGNMENT), 1)
        self.assertEqual(flujo.paso_actual(ts.STATE_LOAD_APPROVED), 2)
        self.assertEqual(flujo.paso_actual(ts.STATE_LOADING), 3)
        self.assertEqual(flujo.paso_actual(ts.STATE_COMPLETED), 4)
        self.assertEqual(flujo.paso_actual(ts.STATE_OBSERVED), 1)

    def test_terminal(self):
        self.assertTrue(flujo.es_terminal(ts.STATE_COMPLETED))
        self.assertTrue(flujo.es_terminal(ts.STATE_REJECTED))
        self.assertFalse(flujo.es_terminal(ts.STATE_LOADING))

    def test_todo_estado_tiene_tono(self):
        for estado in flujo.MAPA:
            self.assertIn(flujo.tono(estado), {"amber", "blue", "green", "red"}, estado)


class TestAccionesContextuales(unittest.TestCase):
    def test_operador_toma_una_pendiente(self):
        acciones = flujo.acciones_disponibles(ts.STATE_PENDING_ASSIGNMENT, "operator")
        self.assertIn("tomar", [a["clave"] for a in acciones])

    def test_no_ofrece_tomar_si_ya_es_suya(self):
        acciones = flujo.acciones_disponibles(
            ts.STATE_PENDING_ASSIGNMENT, "operator",
            asignada_a="hugo@forus.pe", usuario="hugo@forus.pe")
        self.assertNotIn("tomar", [a["clave"] for a in acciones])

    def test_la_marca_no_puede_aprobar_ni_ejecutar(self):
        for estado in flujo.MAPA:
            claves = {a["clave"] for a in flujo.acciones_disponibles(estado, "brand")}
            self.assertNotIn("aprobar", claves, estado)
            self.assertNotIn("ejecutar", claves, estado)
            self.assertNotIn("tomar", claves, estado)

    def test_la_marca_solo_corrige_cuando_esta_observada(self):
        self.assertIn("corregir", [a["clave"] for a in flujo.acciones_disponibles(ts.STATE_OBSERVED, "brand")])
        self.assertEqual(flujo.acciones_disponibles(ts.STATE_LOADING, "brand"), [])

    def test_solo_admin_reabre(self):
        self.assertIn("reabrir", [a["clave"] for a in flujo.acciones_disponibles(ts.STATE_COMPLETED, "admin")])
        self.assertNotIn("reabrir", [a["clave"] for a in flujo.acciones_disponibles(ts.STATE_COMPLETED, "operator")])

    def test_solo_admin_cancela(self):
        self.assertIn("cancelar", [a["clave"] for a in flujo.acciones_disponibles(ts.STATE_ASSIGNED, "admin")])
        self.assertNotIn("cancelar", [a["clave"] for a in flujo.acciones_disponibles(ts.STATE_ASSIGNED, "operator")])

    def test_no_se_cancela_algo_ya_cerrado(self):
        for estado in flujo.TERMINALES:
            claves = {a["clave"] for a in flujo.acciones_disponibles(estado, "admin")}
            self.assertNotIn("cancelar", claves, estado)

    def test_una_finalizada_no_ofrece_acciones_de_avance(self):
        for rol in ["operator", "brand"]:
            claves = {a["clave"] for a in flujo.acciones_disponibles(ts.STATE_COMPLETED, rol)}
            self.assertNotIn("ejecutar", claves)
            self.assertNotIn("aprobar", claves)

    def test_observar_y_reabrir_exigen_comentario(self):
        for estado, rol, clave in [(ts.STATE_DIGITAL_REVIEW, "operator", "observar"),
                                   (ts.STATE_COMPLETED, "admin", "reabrir")]:
            accion = next(a for a in flujo.acciones_disponibles(estado, rol) if a["clave"] == clave)
            self.assertTrue(accion.get("pide_comentario"), clave)

    def test_hay_una_sola_accion_principal_por_estado_y_rol(self):
        for estado in flujo.MAPA:
            for rol in ["operator", "admin", "brand"]:
                principales = [a for a in flujo.acciones_disponibles(estado, rol) if a.get("principal")]
                self.assertLessEqual(len(principales), 1, f"{estado}/{rol}: {principales}")

    def test_accion_principal_del_recorrido_feliz(self):
        recorrido = [
            (ts.STATE_PENDING_ASSIGNMENT, "operator", "tomar"),
            (ts.STATE_ASSIGNED, "operator", "revisar"),
            (ts.STATE_DIGITAL_REVIEW, "operator", "aprobar"),
            (ts.STATE_LOAD_APPROVED, "operator", "ejecutar"),
            (ts.STATE_LOADING, "operator", "finalizar"),
        ]
        for estado, rol, esperada in recorrido:
            principal = flujo.accion_principal(estado, rol)
            self.assertIsNotNone(principal, estado)
            self.assertEqual(principal["clave"], esperada, estado)

    def test_toda_accion_apunta_a_un_metodo_real_de_ticketservice(self):
        for accion in flujo.ACCIONES:
            self.assertTrue(hasattr(ts.TicketService, accion["metodo"]),
                            f"{accion['clave']} -> {accion['metodo']} no existe")

    def test_un_rol_desconocido_no_ve_nada(self):
        self.assertEqual(flujo.acciones_disponibles(ts.STATE_ASSIGNED, "curioso"), [])
        self.assertEqual(flujo.acciones_disponibles(ts.STATE_ASSIGNED, ""), [])


class TestResumen(unittest.TestCase):
    def test_conteo_para_los_kpis(self):
        estados = [ts.STATE_PENDING_ASSIGNMENT, ts.STATE_ASSIGNED, ts.STATE_LOADING,
                   ts.STATE_COMPLETED, ts.STATE_COMPLETED_OBS, ts.STATE_OBSERVED]
        r = flujo.resumen_estados(estados)
        self.assertEqual(r[flujo.PENDIENTE], 2)
        self.assertEqual(r[flujo.EJECUCION], 1)
        self.assertEqual(r[flujo.FINALIZADA], 2)
        self.assertEqual(r[flujo.OBSERVADA], 1)

    def test_la_suma_cuadra(self):
        estados = list(flujo.MAPA)
        self.assertEqual(sum(flujo.resumen_estados(estados).values()), len(estados))


if __name__ == "__main__":
    unittest.main(verbosity=2)
