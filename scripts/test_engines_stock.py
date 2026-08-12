"""Pruebas del motor de consolidacion de stock por Codigo Modelo-Color."""

import os
import sys
import unittest
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from engines import stock as motor
from engines.stock import (
    COLAPSO_PRIMERO,
    COLAPSO_SUMA,
    POLITICA_MINIMO,
    POLITICA_TODAS,
    clave_modelo_color,
    clave_talla,
    clave_variante,
    consolidar_por_modelo_color,
    filas_desde_dataframe,
    indice_por_modelo_color,
    resumen_consolidado,
)


def fila(mod_col, talla, unidades, marca="COLUMBIA", sku=""):
    return {"mod_col": mod_col, "talla": talla, "unidades": unidades, "marca": marca, "sku": sku}


class TestSinStreamlit(unittest.TestCase):
    def test_no_importa_streamlit(self):
        origen = Path(motor.__file__).read_text(encoding="utf-8")
        self.assertNotIn("import streamlit", origen)

    def test_no_importa_pandas(self):
        origen = Path(motor.__file__).read_text(encoding="utf-8")
        self.assertNotIn("import pandas", origen)


class TestClaves(unittest.TestCase):
    def test_modelo_color_en_mayusculas_y_sin_espacios_sobrantes(self):
        self.assertEqual(clave_modelo_color("  im5678-011  "), "IM5678-011")
        self.assertEqual(clave_modelo_color("im5678   011"), "IM5678 011")

    def test_los_guiones_del_codigo_se_respetan(self):
        self.assertNotEqual(clave_modelo_color("IM5678-011"), clave_modelo_color("IM5678011"))

    def test_talla_sin_espacios(self):
        self.assertEqual(clave_talla(" 8.5 "), "8.5")
        self.assertEqual(clave_talla("X L"), "XL")

    def test_clave_variante_necesita_las_dos_partes(self):
        self.assertEqual(clave_variante("IM5678-011", "8.5"), "IM5678-011-8.5")
        self.assertEqual(clave_variante("IM5678-011", ""), "")
        self.assertEqual(clave_variante("", "8.5"), "")

    def test_valores_vacios_no_revientan(self):
        self.assertEqual(clave_modelo_color(None), "")
        self.assertEqual(clave_talla(None), "")
        self.assertEqual(clave_modelo_color(float("nan")), "")


class TestConsolidacion(unittest.TestCase):
    def test_suma_las_tallas_de_un_modelo(self):
        salida = consolidar_por_modelo_color([
            fila("IM5678-011", "8", 3),
            fila("IM5678-011", "8.5", 2),
            fila("IM5678-011", "9", 0),
        ])
        self.assertEqual(len(salida), 1)
        modelo = salida[0]
        self.assertEqual(modelo["unidades"], 5)
        self.assertEqual(modelo["tallas_total"], 3)
        self.assertEqual(modelo["tallas_con_stock"], 2)
        self.assertEqual(modelo["tallas_sin_stock"], 1)
        self.assertTrue(modelo["con_stock"])

    def test_una_talla_repetida_no_se_cuenta_dos_veces(self):
        """El punto del motor: dos filas de la misma talla son la misma existencia."""
        salida = consolidar_por_modelo_color([
            fila("IM5678-011", "8.5", 4, sku="A1"),
            fila("IM5678-011", "8.5", 4, sku="A2"),
        ])
        self.assertEqual(salida[0]["unidades"], 4)
        self.assertEqual(salida[0]["tallas_total"], 1)
        self.assertEqual(salida[0]["filas_leidas"], 2)
        self.assertEqual(salida[0]["filas_colapsadas"], 1)

    def test_la_talla_repetida_se_queda_con_el_valor_mayor(self):
        salida = consolidar_por_modelo_color([
            fila("IM5678-011", "8.5", 1),
            fila("IM5678-011", "8.5", 7),
        ])
        self.assertEqual(salida[0]["unidades"], 7)

    def test_colapso_por_suma_cuando_se_pide(self):
        salida = consolidar_por_modelo_color([
            fila("IM5678-011", "8.5", 1),
            fila("IM5678-011", "8.5", 7),
        ], colapso=COLAPSO_SUMA)
        self.assertEqual(salida[0]["unidades"], 8)

    def test_colapso_por_primero(self):
        salida = consolidar_por_modelo_color([
            fila("IM5678-011", "8.5", 1),
            fila("IM5678-011", "8.5", 7),
        ], colapso=COLAPSO_PRIMERO)
        self.assertEqual(salida[0]["unidades"], 1)

    def test_separa_modelos_distintos(self):
        salida = consolidar_por_modelo_color([
            fila("IM5678-011", "8", 3),
            fila("IM5678-012", "8", 1),
        ])
        self.assertEqual([m["mod_col"] for m in salida], ["IM5678-011", "IM5678-012"])

    def test_el_mismo_modelo_en_distinto_formato_es_uno_solo(self):
        salida = consolidar_por_modelo_color([
            fila(" im5678-011 ", "8", 3),
            fila("IM5678-011", "9", 1),
        ])
        self.assertEqual(len(salida), 1)
        self.assertEqual(salida[0]["unidades"], 4)

    def test_filas_sin_modelo_o_sin_talla_se_descartan(self):
        salida = consolidar_por_modelo_color([
            fila("", "8", 3),
            fila("IM5678-011", "", 3),
            fila("IM5678-011", "8", 3),
        ])
        self.assertEqual(len(salida), 1)
        self.assertEqual(salida[0]["filas_leidas"], 1)

    def test_unidades_negativas_se_tratan_como_cero(self):
        salida = consolidar_por_modelo_color([fila("IM5678-011", "8", -5)])
        self.assertEqual(salida[0]["unidades"], 0)
        self.assertFalse(salida[0]["con_stock"])

    def test_unidades_en_texto_con_coma_decimal(self):
        salida = consolidar_por_modelo_color([fila("IM5678-011", "8", "2,5")])
        self.assertEqual(salida[0]["unidades"], 2.5)

    def test_unidades_no_numericas_no_revientan(self):
        salida = consolidar_por_modelo_color([fila("IM5678-011", "8", "sin dato")])
        self.assertEqual(salida[0]["unidades"], 0)

    def test_entrada_vacia(self):
        self.assertEqual(consolidar_por_modelo_color([]), [])
        self.assertEqual(consolidar_por_modelo_color(None), [])

    def test_entradas_que_no_son_diccionarios_se_ignoran(self):
        salida = consolidar_por_modelo_color(["basura", None, fila("IM5678-011", "8", 1)])
        self.assertEqual(len(salida), 1)

    def test_cobertura(self):
        salida = consolidar_por_modelo_color([
            fila("IM5678-011", "8", 1),
            fila("IM5678-011", "9", 0),
            fila("IM5678-011", "10", 1),
            fila("IM5678-011", "11", 1),
        ])
        self.assertEqual(salida[0]["cobertura"], 75.0)

    def test_se_conservan_los_skus_del_modelo(self):
        salida = consolidar_por_modelo_color([
            fila("IM5678-011", "8", 1, sku="1001"),
            fila("IM5678-011", "9", 1, sku="1002"),
        ])
        self.assertEqual(salida[0]["skus"], ["1001", "1002"])


class TestPoliticasDeVisibilidad(unittest.TestCase):
    def test_por_defecto_basta_una_talla_con_stock(self):
        salida = consolidar_por_modelo_color([
            fila("IM5678-011", "8", 0),
            fila("IM5678-011", "9", 1),
        ])
        self.assertTrue(salida[0]["debe_estar_visible"])

    def test_sin_ninguna_talla_con_stock_no_se_muestra(self):
        salida = consolidar_por_modelo_color([
            fila("IM5678-011", "8", 0),
            fila("IM5678-011", "9", 0),
        ])
        self.assertFalse(salida[0]["debe_estar_visible"])
        self.assertFalse(salida[0]["con_stock"])

    def test_politica_todas_las_tallas(self):
        completo = consolidar_por_modelo_color(
            [fila("A-1", "8", 1), fila("A-1", "9", 1)], politica=POLITICA_TODAS)
        incompleto = consolidar_por_modelo_color(
            [fila("A-1", "8", 1), fila("A-1", "9", 0)], politica=POLITICA_TODAS)
        self.assertTrue(completo[0]["debe_estar_visible"])
        self.assertFalse(incompleto[0]["debe_estar_visible"])

    def test_politica_minimo_de_tallas(self):
        filas = [fila("A-1", "8", 1), fila("A-1", "9", 1), fila("A-1", "10", 0)]
        con_dos = consolidar_por_modelo_color(filas, politica=POLITICA_MINIMO, minimo_tallas=2)
        con_tres = consolidar_por_modelo_color(filas, politica=POLITICA_MINIMO, minimo_tallas=3)
        self.assertTrue(con_dos[0]["debe_estar_visible"])
        self.assertFalse(con_tres[0]["debe_estar_visible"])

    def test_una_politica_desconocida_cae_en_la_de_por_defecto(self):
        salida = consolidar_por_modelo_color([fila("A-1", "8", 1)], politica="inventada")
        self.assertTrue(salida[0]["debe_estar_visible"])

    def test_umbral_de_unidades(self):
        salida = consolidar_por_modelo_color([fila("A-1", "8", 2)], umbral_unidades=2)
        self.assertFalse(salida[0]["con_stock"])
        self.assertEqual(salida[0]["tallas_sin_stock"], 1)


class TestResumenEIndice(unittest.TestCase):
    def test_resumen(self):
        consolidado = consolidar_por_modelo_color([
            fila("A-1", "8", 3),
            fila("A-1", "8", 3),
            fila("A-1", "9", 0),
            fila("B-2", "M", 0),
        ])
        resumen = resumen_consolidado(consolidado)
        self.assertEqual(resumen["modelos_color"], 2)
        self.assertEqual(resumen["modelos_con_stock"], 1)
        self.assertEqual(resumen["modelos_sin_stock"], 1)
        self.assertEqual(resumen["unidades"], 3)
        self.assertEqual(resumen["tallas"], 3)
        self.assertEqual(resumen["filas_leidas"], 4)
        self.assertEqual(resumen["filas_colapsadas"], 1)

    def test_resumen_vacio(self):
        self.assertEqual(resumen_consolidado([])["modelos_color"], 0)

    def test_indice_por_modelo(self):
        indice = indice_por_modelo_color(consolidar_por_modelo_color([fila("A-1", "8", 3)]))
        self.assertEqual(indice["A-1"]["unidades"], 3)


class TestDesdeDataFrame(unittest.TestCase):
    """El motor no depende de pandas, pero tiene que poder leer un DataFrame."""

    def setUp(self):
        try:
            import pandas as pd
        except ImportError:  # pragma: no cover
            self.skipTest("pandas no disponible")
        self.pd = pd

    def test_lee_un_dataframe(self):
        df = self.pd.DataFrame([
            {"Mod-Col KPI": "A-1", "Talla KPI": "8", "stock_total": 3, "MARCA_MA": "COLUMBIA", "SKU": "1"},
            {"Mod-Col KPI": "A-1", "Talla KPI": "9", "stock_total": 0, "MARCA_MA": "COLUMBIA", "SKU": "2"},
        ])
        filas = filas_desde_dataframe(df, "Mod-Col KPI", "Talla KPI", "stock_total",
                                      columna_marca="MARCA_MA", columna_sku="SKU")
        salida = consolidar_por_modelo_color(filas)
        self.assertEqual(salida[0]["unidades"], 3)
        self.assertEqual(salida[0]["marca"], "COLUMBIA")

    def test_dataframe_vacio(self):
        self.assertEqual(filas_desde_dataframe(self.pd.DataFrame(), "a", "b", "c"), [])
        self.assertEqual(filas_desde_dataframe(None, "a", "b", "c"), [])

    def test_falta_una_columna_obligatoria(self):
        df = self.pd.DataFrame([{"Mod-Col KPI": "A-1", "Talla KPI": "8"}])
        self.assertEqual(filas_desde_dataframe(df, "Mod-Col KPI", "Talla KPI", "stock_total"), [])

    def test_las_columnas_opcionales_pueden_faltar(self):
        df = self.pd.DataFrame([{"Mod-Col KPI": "A-1", "Talla KPI": "8", "stock_total": 2}])
        filas = filas_desde_dataframe(df, "Mod-Col KPI", "Talla KPI", "stock_total",
                                      columna_marca="NO_EXISTE", columna_sku="TAMPOCO")
        self.assertEqual(len(filas), 1)
        self.assertEqual(filas[0]["marca"], "")


if __name__ == "__main__":
    unittest.main(verbosity=2)
