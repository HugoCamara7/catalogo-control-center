"""Pruebas de engines/price_check.py — validacion de precio y stock.

Lo critico: nada puede aprobarse si el precio no llego a Shopify. Ese es el
error que este motor existe para impedir.
"""

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from engines.price_check import (
    MOTIVO_PRECIO_CERO,
    MOTIVO_PRECIO_DISTINTO,
    MOTIVO_SIN_PRECIO,
    MOTIVO_SIN_SHOPIFY,
    MOTIVO_SIN_STOCK,
    SEVERIDAD_AVISO,
    SEVERIDAD_BLOQUEO,
    filas_para_informe,
    validar,
)


class TestArquitectura(unittest.TestCase):
    def test_no_importa_streamlit_ni_pandas(self):
        fuente = (ROOT / "engines" / "price_check.py").read_text(encoding="utf-8")
        self.assertNotIn("import streamlit", fuente)
        self.assertNotIn("import pandas", fuente)


class TestValidacion(unittest.TestCase):
    def test_todo_correcto_aprueba(self):
        r = validar(
            [{"mod_col": "A-1", "precio": 199.9}],
            [{"mod_col": "A-1", "precio": 199.9, "stock": 5}],
        )
        self.assertTrue(r["aprobado"])
        self.assertEqual(r["bloqueos"], 0)
        self.assertEqual(r["conformes"], 1)

    def test_no_llego_a_shopify_bloquea(self):
        r = validar([{"mod_col": "A-1", "precio": 100}], [])
        self.assertFalse(r["aprobado"])
        self.assertEqual(r["bloqueos"], 1)
        self.assertEqual(r["problemas"][0]["motivo"], MOTIVO_SIN_SHOPIFY)

    def test_sin_precio_bloquea(self):
        r = validar([{"mod_col": "A-1"}], [{"mod_col": "A-1", "precio": "", "stock": 3}])
        self.assertFalse(r["aprobado"])
        self.assertEqual(r["problemas"][0]["motivo"], MOTIVO_SIN_PRECIO)

    def test_precio_en_cero_bloquea(self):
        r = validar([{"mod_col": "A-1"}], [{"mod_col": "A-1", "precio": 0, "stock": 3}])
        self.assertFalse(r["aprobado"])
        self.assertEqual(r["problemas"][0]["motivo"], MOTIVO_PRECIO_CERO)

    def test_precio_distinto_solo_avisa(self):
        r = validar([{"mod_col": "A-1", "precio": 199.9}],
                    [{"mod_col": "A-1", "precio": 149.9, "stock": 2}])
        self.assertTrue(r["aprobado"])
        self.assertEqual(r["avisos"], 1)
        self.assertEqual(r["problemas"][0]["motivo"], MOTIVO_PRECIO_DISTINTO)
        self.assertEqual(r["problemas"][0]["severidad"], SEVERIDAD_AVISO)

    def test_el_redondeo_no_avisa(self):
        r = validar([{"mod_col": "A-1", "precio": 199.90}],
                    [{"mod_col": "A-1", "precio": "199.90", "stock": 1}])
        self.assertEqual(r["avisos"], 0)

    def test_sin_stock_avisa_pero_no_bloquea(self):
        r = validar([{"mod_col": "A-1", "precio": 100}],
                    [{"mod_col": "A-1", "precio": 100, "stock": 0}])
        self.assertTrue(r["aprobado"])
        self.assertEqual(r["problemas"][0]["motivo"], MOTIVO_SIN_STOCK)
        self.assertEqual(r["problemas"][0]["severidad"], SEVERIDAD_AVISO)

    def test_sin_stock_bloquea_si_se_exige(self):
        r = validar([{"mod_col": "A-1", "precio": 100}],
                    [{"mod_col": "A-1", "precio": 100, "stock": 0}],
                    exigir_stock=True)
        self.assertFalse(r["aprobado"])
        self.assertEqual(r["problemas"][0]["severidad"], SEVERIDAD_BLOQUEO)

    def test_suma_el_stock_de_las_variantes(self):
        r = validar([{"mod_col": "A-1", "precio": 100, "stock": 8}],
                    [{"mod_col": "A-1", "precio": 100, "stock": 5},
                     {"mod_col": "A-1", "precio": 100, "stock": 3}])
        self.assertEqual(r["avisos"], 0)

    def test_precio_con_simbolo_y_coma(self):
        r = validar([{"mod_col": "A-1", "precio": 1299.50}],
                    [{"mod_col": "A-1", "precio": "S/ 1,299.50", "stock": 1}])
        self.assertEqual(r["avisos"], 0)

    def test_no_repite_el_mismo_modelo(self):
        r = validar([{"mod_col": "A-1", "precio": 100}, {"mod_col": "A-1", "precio": 100}],
                    [{"mod_col": "A-1", "precio": 100, "stock": 1}])
        self.assertEqual(r["revisados"], 1)

    def test_normaliza_el_modelo(self):
        r = validar([{"mod_col": " a-1 ", "precio": 100}],
                    [{"mod_col": "A-1", "precio": 100, "stock": 1}])
        self.assertTrue(r["aprobado"])

    def test_sin_nada_que_revisar_no_aprueba(self):
        """Aprobar por vacio dejaria cerrar una solicitud sin validar nada."""
        r = validar([], [])
        self.assertFalse(r["aprobado"])
        self.assertEqual(r["revisados"], 0)

    def test_conformes_no_cuenta_dos_veces_el_mismo_modelo(self):
        r = validar([{"mod_col": "A-1"}, {"mod_col": "B-2"}],
                    [{"mod_col": "A-1", "precio": 0, "stock": 0},
                     {"mod_col": "B-2", "precio": 10, "stock": 2}])
        self.assertEqual(r["revisados"], 2)
        self.assertEqual(r["conformes"], 1)
        self.assertEqual(r["modelos_bloqueados"], ["A-1"])

    def test_basura_no_revienta(self):
        r = validar(["texto", None, {"mod_col": "A-1"}], ["basura", {"mod_col": "A-1", "precio": 9, "stock": 1}])
        self.assertEqual(r["revisados"], 1)

    def test_detalle_explica(self):
        r = validar([{"mod_col": "A-1"}], [])
        self.assertIn("No se puede cerrar", r["detalle"])


class TestInforme(unittest.TestCase):
    def test_filas_para_informe(self):
        r = validar([{"mod_col": "A-1", "marca": "COLUMBIA", "precio": 100}], [])
        filas = filas_para_informe(r)
        self.assertEqual(len(filas), 1)
        self.assertEqual(filas[0]["Mod-Col"], "A-1")
        self.assertEqual(filas[0]["Severidad"], "Bloqueo")
        self.assertEqual(filas[0]["Marca"], "COLUMBIA")

    def test_informe_vacio(self):
        self.assertEqual(filas_para_informe(None), [])
        self.assertEqual(filas_para_informe({}), [])


if __name__ == "__main__":
    unittest.main(verbosity=2)
