"""Pruebas de engines/metrics.py — metricas por Codigo Modelo-Color.

Lo critico: "productos sin foto" cuenta PRODUCTOS sin NINGUNA imagen. Ni
imagenes faltantes, ni variantes, ni filas del maestro.
"""

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from engines import metrics as motor
from engines.metrics import (
    contar_fotos,
    productos_sin_foto,
    ratio,
    resumen_modelo_color,
)
from engines.metrics import filas_desde_dataframe


class TestArquitectura(unittest.TestCase):
    def test_no_importa_streamlit_ni_pandas(self):
        fuente = (ROOT / "engines" / "metrics.py").read_text(encoding="utf-8")
        self.assertNotIn("import streamlit", fuente)
        self.assertNotIn("import pandas", fuente)


class TestContarFotos(unittest.TestCase):
    def test_numero(self):
        self.assertEqual(contar_fotos(3), 3)
        self.assertEqual(contar_fotos(0), 0)
        self.assertEqual(contar_fotos("2"), 2)

    def test_urls_separadas(self):
        self.assertEqual(contar_fotos("a.jpg;b.jpg;c.jpg"), 3)
        self.assertEqual(contar_fotos("a.jpg"), 1)

    def test_vacios(self):
        for valor in ("", None, "   ", ";;", float("nan")):
            self.assertEqual(contar_fotos(valor), 0, repr(valor))

    def test_lista(self):
        self.assertEqual(contar_fotos(["a.jpg", "", "b.jpg"]), 2)

    def test_negativo_es_cero(self):
        self.assertEqual(contar_fotos(-4), 0)


class TestProductosSinFoto(unittest.TestCase):
    def test_cuenta_productos_no_imagenes(self):
        """Un producto con 8 tallas y sin fotos cuenta 1, no 8."""
        filas = [{"mod_col": "A-1", "fotos": 0} for _ in range(8)]
        filas += [{"mod_col": "B-2", "fotos": 3}]
        r = productos_sin_foto(filas)
        self.assertEqual(r["sin_foto"], 1)
        self.assertEqual(r["total"], 2)

    def test_si_alguna_fila_tiene_fotos_el_producto_tiene_fotos(self):
        r = productos_sin_foto([
            {"mod_col": "A-1", "fotos": 0},
            {"mod_col": "A-1", "fotos": 3},
        ])
        self.assertEqual(r["sin_foto"], 0)
        self.assertEqual(r["con_foto"], 1)

    def test_ratio_legible(self):
        filas = [{"mod_col": f"M-{i}", "fotos": 0 if i < 12 else 2} for i in range(185)]
        r = productos_sin_foto(filas)
        self.assertEqual(r["sin_foto"], 12)
        self.assertEqual(r["total"], 185)
        self.assertEqual(r["ratio"], "12 / 185 productos")

    def test_porcentaje(self):
        r = productos_sin_foto([{"mod_col": "A-1", "fotos": 0}, {"mod_col": "B-2", "fotos": 1},
                                {"mod_col": "C-3", "fotos": 1}, {"mod_col": "D-4", "fotos": 1}])
        self.assertEqual(r["porcentaje"], 25.0)

    def test_detalle_dice_cuales(self):
        r = productos_sin_foto([{"mod_col": "A-1", "fotos": 0, "marca": "COLUMBIA"},
                                {"mod_col": "B-2", "fotos": 2}])
        self.assertEqual([d["mod_col"] for d in r["detalle"]], ["A-1"])
        self.assertEqual(r["detalle"][0]["marca"], "COLUMBIA")

    def test_sin_foto_pero_con_stock_es_lo_urgente(self):
        r = productos_sin_foto([{"mod_col": "A-1", "fotos": 0, "con_stock": True},
                                {"mod_col": "B-2", "fotos": 0, "con_stock": False}])
        self.assertEqual(r["sin_foto"], 2)
        self.assertEqual(r["sin_foto_con_stock"], 1)

    def test_normaliza_el_modelo(self):
        r = productos_sin_foto([{"mod_col": " a-1 ", "fotos": 0}, {"mod_col": "A-1", "fotos": 0}])
        self.assertEqual(r["total"], 1)

    def test_entrada_vacia(self):
        r = productos_sin_foto([])
        self.assertEqual(r["sin_foto"], 0)
        self.assertEqual(r["total"], 0)
        self.assertEqual(r["porcentaje"], 0.0)

    def test_filas_sin_modelo_se_descartan(self):
        r = productos_sin_foto([{"mod_col": "", "fotos": 0}, {"mod_col": "A-1", "fotos": 0}])
        self.assertEqual(r["total"], 1)

    def test_basura_no_revienta(self):
        self.assertEqual(productos_sin_foto(["texto", None, 5])["total"], 0)
        self.assertEqual(productos_sin_foto(None)["total"], 0)


class TestResumenModeloColor(unittest.TestCase):
    def test_vendible_exige_las_cuatro_cosas(self):
        filas = [
            {"mod_col": "A-1", "fotos": 2, "con_stock": True, "con_precio": True, "creado": True},
            {"mod_col": "B-2", "fotos": 0, "con_stock": True, "con_precio": True, "creado": True},
            {"mod_col": "C-3", "fotos": 2, "con_stock": False, "con_precio": True, "creado": True},
        ]
        r = resumen_modelo_color(filas)
        self.assertEqual(r["total"], 3)
        self.assertEqual(r["vendibles"], 1)
        self.assertEqual(r["sin_foto"], 1)
        self.assertEqual(r["sin_stock"], 1)

    def test_consolida_varias_filas(self):
        r = resumen_modelo_color([
            {"mod_col": "A-1", "fotos": 0, "con_stock": False},
            {"mod_col": "A-1", "fotos": 3, "con_stock": True},
        ])
        self.assertEqual(r["total"], 1)
        self.assertEqual(r["con_foto"], 1)
        self.assertEqual(r["con_stock"], 1)

    def test_vacio(self):
        self.assertEqual(resumen_modelo_color([])["total"], 0)


class TestRatio(unittest.TestCase):
    def test_formato(self):
        self.assertEqual(ratio(12, 185), "12 / 185 productos")

    def test_miles_con_punto(self):
        self.assertEqual(ratio(120, 1850), "120 / 1.850 productos")

    def test_sustantivo(self):
        self.assertEqual(ratio(3, 9, "modelos"), "3 / 9 modelos")


class TestDesdeDataFrame(unittest.TestCase):
    def setUp(self):
        try:
            import pandas as pd
        except ImportError:  # pragma: no cover
            self.skipTest("pandas no disponible")
        self.pd = pd

    def test_lee_el_catalogo_de_shopify(self):
        df = self.pd.DataFrame([
            {"Mod-Col": "A-1", "Fotos": 0},
            {"Mod-Col": "B-2", "Fotos": 4},
        ])
        r = productos_sin_foto(filas_desde_dataframe(df, "Mod-Col", columna_fotos="Fotos"))
        self.assertEqual(r["ratio"], "1 / 2 productos")

    def test_columnas_opcionales_ausentes(self):
        df = self.pd.DataFrame([{"Mod-Col": "A-1", "Fotos": 0}])
        filas = filas_desde_dataframe(df, "Mod-Col", columna_fotos="Fotos",
                                      columna_marca="NO_EXISTE")
        self.assertEqual(len(filas), 1)
        self.assertNotIn("marca", filas[0])

    def test_vacio(self):
        self.assertEqual(filas_desde_dataframe(self.pd.DataFrame(), "Mod-Col"), [])
        self.assertEqual(filas_desde_dataframe(None, "Mod-Col"), [])

    def test_falta_la_columna_clave(self):
        df = self.pd.DataFrame([{"Otra": 1}])
        self.assertEqual(filas_desde_dataframe(df, "Mod-Col"), [])


if __name__ == "__main__":
    unittest.main(verbosity=2)
