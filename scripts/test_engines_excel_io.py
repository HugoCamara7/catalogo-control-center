"""Pruebas del motor engines/excel_io.py

Cubre en particular el fallo "IndexError: At least one sheet must be visible",
que openpyxl lanza al guardar un libro sin hojas visibles y que tumbaba la app
completa.

Ejecutar:  python scripts/test_engines_excel_io.py
"""
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import pandas as pd

from engines.excel_io import (
    columbia_to_excel_bytes,
    dataframe_to_excel_bytes,
    read_excel,
    update_to_excel_bytes,
)


def hojas_de(buffer):
    buffer.seek(0)
    return pd.ExcelFile(buffer).sheet_names


class TestMotorNoImportaStreamlit(unittest.TestCase):
    def test_sin_streamlit(self):
        fuente = (ROOT / "engines" / "excel_io.py").read_text(encoding="utf-8")
        self.assertNotIn("import streamlit", fuente)

    def test_todos_los_nombres_estan_resueltos(self):
        """Evita el NameError por imports faltantes al extraer el motor."""
        import ast
        import builtins

        import engines.excel_io as motor

        arbol = ast.parse((ROOT / "engines" / "excel_io.py").read_text(encoding="utf-8"))
        llamados = {
            n.func.id for n in ast.walk(arbol)
            if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)
        }
        for nombre in llamados:
            if hasattr(builtins, nombre):
                continue
            self.assertTrue(
                hasattr(motor, nombre),
                f"'{nombre}' se usa en engines/excel_io.py pero no esta importado ni definido",
            )


class TestSinHojasVisibles(unittest.TestCase):
    """El fallo que tumbaba la app: libro sin ninguna hoja."""

    def test_dict_vacio_no_revienta(self):
        buffer = dataframe_to_excel_bytes({})
        self.assertGreater(len(buffer.getvalue()), 0)
        self.assertEqual(hojas_de(buffer), ["Sin datos"])

    def test_none_no_revienta(self):
        buffer = dataframe_to_excel_bytes(None)
        self.assertEqual(hojas_de(buffer), ["Sin datos"])

    def test_la_hoja_informativa_explica_el_motivo(self):
        buffer = dataframe_to_excel_bytes({})
        buffer.seek(0)
        df = pd.read_excel(buffer, sheet_name="Sin datos")
        self.assertIn("Detalle", df.columns)
        self.assertGreater(len(df), 0)


class TestDataframeToExcelBytes(unittest.TestCase):
    def test_una_hoja(self):
        buffer = dataframe_to_excel_bytes({"Datos": pd.DataFrame({"A": [1, 2]})})
        self.assertEqual(hojas_de(buffer), ["Datos"])

    def test_varias_hojas_conservan_el_orden(self):
        buffer = dataframe_to_excel_bytes({
            "Resumen": pd.DataFrame({"A": [1]}),
            "Detalle": pd.DataFrame({"B": [2]}),
            "Errores": pd.DataFrame({"C": [3]}),
        })
        self.assertEqual(hojas_de(buffer), ["Resumen", "Detalle", "Errores"])

    def test_dataframe_vacio_igual_crea_la_hoja(self):
        buffer = dataframe_to_excel_bytes({"Vacia": pd.DataFrame()})
        self.assertEqual(hojas_de(buffer), ["Vacia"])

    def test_nombre_de_hoja_se_recorta_a_31(self):
        buffer = dataframe_to_excel_bytes({"N" * 60: pd.DataFrame({"A": [1]})})
        self.assertEqual(len(hojas_de(buffer)[0]), 31)

    def test_contenido_se_conserva(self):
        original = pd.DataFrame({"Mod-Col": ["AB-1", "CD-2"], "Talla": ["M", "L"]})
        buffer = dataframe_to_excel_bytes({"Products": original})
        buffer.seek(0)
        leido = pd.read_excel(buffer, sheet_name="Products")
        self.assertEqual(list(leido.columns), ["Mod-Col", "Talla"])
        self.assertEqual(leido["Mod-Col"].tolist(), ["AB-1", "CD-2"])
        self.assertEqual(leido["Talla"].tolist(), ["M", "L"])

    def test_congela_la_fila_de_encabezado(self):
        import openpyxl

        buffer = dataframe_to_excel_bytes({"Datos": pd.DataFrame({"A": [1]})})
        buffer.seek(0)
        wb = openpyxl.load_workbook(buffer)
        self.assertEqual(wb["Datos"].freeze_panes, "A2")


class TestColumbiaToExcelBytes(unittest.TestCase):
    def setUp(self):
        self.df = pd.DataFrame({"Mod-Col": ["AB-1"], "Talla": ["M"]})

    def test_hojas_minimas(self):
        buffer = columbia_to_excel_bytes(self.df, self.df, self.df)
        self.assertEqual(hojas_de(buffer), ["Products", "Resumen", "Revision"])

    def test_con_sial_y_centry(self):
        buffer = columbia_to_excel_bytes(
            self.df, self.df, self.df, sial_df=self.df, centry_df=self.df,
        )
        hojas = hojas_de(buffer)
        for esperada in ["Products", "Resumen", "Revision", "Carga Sial", "Centry", "Revision Centry"]:
            self.assertIn(esperada, hojas)

    def test_con_todas_las_hojas(self):
        buffer = columbia_to_excel_bytes(
            self.df, self.df, self.df,
            type_warnings_df=self.df, skipped_df=self.df, sial_df=self.df,
            centry_df=self.df, centry_issues_df=self.df,
        )
        hojas = hojas_de(buffer)
        self.assertIn("Tipos nuevos", hojas)
        self.assertIn("Omitidos sin cambios", hojas)

    def test_products_conserva_los_datos(self):
        buffer = columbia_to_excel_bytes(self.df, self.df, self.df)
        buffer.seek(0)
        leido = pd.read_excel(buffer, sheet_name="Products")
        self.assertEqual(leido["Mod-Col"].tolist(), ["AB-1"])


class TestUpdateToExcelBytes(unittest.TestCase):
    def test_hojas(self):
        df = pd.DataFrame({"A": [1]})
        self.assertEqual(hojas_de(update_to_excel_bytes(df, df)), ["Products", "Revision"])


class TestReadExcel(unittest.TestCase):
    def test_ida_y_vuelta(self):
        original = pd.DataFrame({"Mod-Col": ["AB-1", "CD-2"]})
        buffer = dataframe_to_excel_bytes({"Hoja": original})
        buffer.seek(0)
        self.assertEqual(read_excel(buffer)["Mod-Col"].tolist(), ["AB-1", "CD-2"])

    def test_descarta_filas_totalmente_vacias(self):
        buffer = dataframe_to_excel_bytes({"Hoja": pd.DataFrame({"A": [1, None, 3]})})
        buffer.seek(0)
        self.assertEqual(len(read_excel(buffer)), 2)


if __name__ == "__main__":
    unittest.main(verbosity=2)
