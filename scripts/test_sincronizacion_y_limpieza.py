"""Dos cosas: la carga se encadena sola, y la auditoria se puede limpiar.

Por que existe
--------------
1. **"¿Por que la sincronizacion es por bloques? deberia ser completa."** Los
   bloques no eran un limite: la opcion "Todos pendientes" ya existia, pero era
   la ULTIMA de seis y el valor por defecto era 50, asi que nadie la
   encontraba. Y lo que de verdad molestaba no eran los bloques, era tener que
   pulsar "Continuar siguiente bloque" veinte veces.

2. El registro de auditoria crece **un archivo por mes** y nunca se limpiaba.

Ejecutar:  python scripts/test_sincronizacion_y_limpieza.py
"""
import ast
import sys
import tempfile
import unittest
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from engines import audit  # noqa: E402

FUENTE = (ROOT / "app_matrixify.py").read_text(encoding="utf-8-sig")
ARBOL = ast.parse(FUENTE)


def cuerpo_de(nombre):
    return ast.get_source_segment(FUENTE, next(
        n for n in ast.walk(ARBOL)
        if isinstance(n, ast.FunctionDef) and n.name == nombre))


class TestCargaSinParar(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.panel = cuerpo_de("render_persistent_sync_job_panel")

    def test_la_carga_completa_es_la_opcion_por_defecto(self):
        """Estaba la ultima de seis y el defecto era 50: la carga completa
        existia pero se veia como que la app solo cargaba de 50 en 50."""
        self.assertIn('["Todos pendientes", "10", "20", "30", "50", "Otro"]', self.panel)
        self.assertIn("index=0", self.panel)

    def test_hay_un_boton_que_encadena_los_bloques(self):
        self.assertIn("Cargar todo sin parar", self.panel)
        self.assertIn("st.rerun()", self.panel)

    def test_el_boton_de_parar_se_dibuja_antes_de_procesar(self):
        """Durante el bloque el script sigue corriendo: lo que venga DESPUES
        todavia no existe en pantalla, asi que un boton de parar dibujado
        despues no se ve nunca."""
        parar = self.panel.index("Detener la carga")
        procesar = self.panel.index("process_sync_job_next_block(", parar - 4000)
        self.assertLess(parar, self.panel.index("process_sync_job_next_block(", parar),
                        "el boton de parar quedo despues del trabajo")

    def test_parar_no_depende_de_acertar_el_momento(self):
        """Con `on_click` la bandera se limpia antes del cuerpo del script en
        el rerun siguiente; con un `if boton:` habria que pulsarlo justo en el
        hueco entre bloques."""
        self.assertIn("on_click=lambda clave=auto_key", self.panel)

    def test_el_bucle_para_si_un_bloque_no_avanza(self):
        """`process_sync_job_next_block` saca el producto de pendientes aunque
        falle, asi que el bucle termina solo. La guarda es por si eso cambia:
        repetir un bloque que no avanza seria un bucle infinito que escribe en
        Shopify."""
        self.assertIn("completados_antes", self.panel)
        self.assertIn("<= completados_antes", self.panel)

    def test_el_avance_sigue_guardandose_por_bloques(self):
        """La red no se quita: encadenar los bloques no puede convertir la
        carga en un todo o nada."""
        self.assertIn("process_sync_job_next_block(", self.panel)
        self.assertNotIn("while ", self.panel,
                         "un while dentro del rerun bloquea la pantalla entera")

    def test_crear_un_proceso_nuevo_apaga_el_automatico(self):
        inicio = self.panel.index("Crear nuevo proceso")
        self.assertIn("auto_key", self.panel[inicio:inicio + 400])


class TestLimpiezaDeAuditoria(unittest.TestCase):
    def setUp(self):
        self.carpeta = tempfile.TemporaryDirectory()
        self.addCleanup(self.carpeta.cleanup)
        self.store = audit.LocalAuditStore(self.carpeta.name)
        self.servicio = audit.AuditService(self.store)
        for periodo, cuantos in (("2024-01", 3), ("2026-06", 2), ("2026-09", 4)):
            for numero in range(cuantos):
                self.store.append({"fecha": f"{periodo}-15 10:0{numero}",
                                   "accion": "Prueba", "usuario": "x@forus.pe"})

    def test_borra_un_mes_entero_y_dice_cuantos_eventos_se_llevo(self):
        self.assertEqual(self.store.delete_period("2024-01"), 3)
        self.assertNotIn("2024-01", self.store.periods())
        self.assertEqual(len(self.store.read_period("2026-06")), 2)

    def test_borrar_un_mes_que_no_existe_no_revienta(self):
        self.assertEqual(self.store.delete_period("1999-01"), 0)

    def test_el_mes_en_curso_nunca_se_ofrece(self):
        """Se estaria borrando lo que se acaba de registrar, incluida la propia
        limpieza."""
        hoy = datetime(2026, 9, 7)
        limpiables = self.servicio.periodos_limpiables(conservar_meses=0, hoy=hoy)
        self.assertNotIn("2026-09", limpiables)

    def test_conserva_los_meses_pedidos(self):
        hoy = datetime(2026, 9, 7)
        self.assertEqual(self.servicio.periodos_limpiables(conservar_meses=12, hoy=hoy), ["2024-01"])
        self.assertEqual(self.servicio.periodos_limpiables(conservar_meses=36, hoy=hoy), [])
        self.assertEqual(
            sorted(self.servicio.periodos_limpiables(conservar_meses=1, hoy=hoy)),
            ["2024-01", "2026-06"],
        )

    def test_un_mes_que_falla_no_corta_la_limpieza_de_los_demas(self):
        class StoreRoto(audit.LocalAuditStore):
            def delete_period(self, periodo):
                if periodo == "2026-06":
                    raise RuntimeError("GitHub dijo que no")
                return super().delete_period(periodo)

        servicio = audit.AuditService(StoreRoto(self.carpeta.name))
        resultados = servicio.limpiar_periodos(["2024-01", "2026-06"])
        self.assertEqual([(p, n) for p, n, e in resultados if not e], [("2024-01", 3)])
        self.assertEqual([p for p, _, e in resultados if e], ["2026-06"])

    def test_un_almacen_que_no_sabe_borrar_lo_dice(self):
        class SinBorrar:
            def periods(self):
                return []
        resultados = audit.AuditService(SinBorrar()).limpiar_periodos(["2024-01"])
        self.assertTrue(resultados[0][2])

    def test_el_calculo_de_meses_cruza_el_ano(self):
        self.assertEqual(audit._mes_menos("2026-01", 1), "2025-12")
        self.assertEqual(audit._mes_menos("2026-09", 12), "2025-09")
        self.assertEqual(audit._mes_menos("2026-09", 0), "2026-09")
        self.assertEqual(audit._mes_menos("basura", 3), "basura")


class TestPantallaDeLimpieza(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.pantalla = cuerpo_de("render_limpieza_auditoria")

    def test_pide_confirmacion_antes_de_borrar(self):
        """Borrar el registro no se puede deshacer."""
        self.assertIn("st.checkbox(", self.pantalla)
        self.assertIn("disabled=not confirmado", self.pantalla)

    def test_la_limpieza_queda_registrada(self):
        """Un borrado que no deja rastro convierte la auditoria en un adorno:
        el registro no podria explicar por que le falta un tramo."""
        self.assertIn("log_user_activity(", self.pantalla)

    def test_avisa_cuando_el_almacen_es_efimero(self):
        """Sin backend persistente no hay nada que limpiar y ofrecerlo
        confundiria."""
        self.assertIn("servicio.persistente", self.pantalla)

    def test_tiene_llamador(self):
        self.assertIn("render_limpieza_auditoria(servicio)", FUENTE)

    def test_no_borra_nada_sin_que_se_pulse_el_boton(self):
        borrar = self.pantalla.index("limpiar_periodos(")
        boton = self.pantalla.index('st.button("Borrar esos meses"')
        self.assertLess(boton, borrar, "se limpia antes de que nadie lo pida")


if __name__ == "__main__":
    unittest.main(verbosity=2)
