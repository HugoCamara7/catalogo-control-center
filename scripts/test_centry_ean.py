# -*- coding: utf-8 -*-
"""Pruebas del EAN de Centry: por que faltaba y como se resuelve ahora.

Origen: la carga Centry salia bien, pero seguian apareciendo variantes con la
columna "Codigo de barra variante (EAN/UPC/ISBN)" vacia. Cuatro causas
distintas, ninguna visible en el resultado:

1. **El maestro guardaba la fila equivocada.** `build_centry_arti_lookup` usaba
   `setdefault`. Como el maestro trae varias filas por SKU (una por bodega), si
   la primera venia sin CodBarras el SKU se quedaba sin EAN aunque otra fila
   del mismo SKU si lo tuviera.

2. **El SKU no emparejaba por formato.** El maestro devuelve "12345" donde
   Shopify tiene "0012345", o "12345.0" cuando Excel lo leyo como numero. La
   comparacion era por cadena exacta.

3. **El EAN llegaba roto y pasaba el control.** Excel guarda el codigo como
   numero y lo devuelve como "7.79871E+12" o "7798712345678.0". No es vacio,
   asi que se colaba hasta Centry convertido en basura.

4. **Solo se miraban dos fuentes.** El EAN que venia en el propio input no se
   leia: era `first_non_empty(maestro, Variant Barcode)` y nada mas.

Ejecutar:  python scripts/test_centry_ean.py
"""
import sys
import types
import unittest
from pathlib import Path

import pandas as pd

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


def fila(**valores):
    """Una fila de Matrixify con las columnas que mira el resolutor."""
    base = {
        "Variant SKU": "",
        "Variant Barcode": "",
        "Option1 Value": "",
    }
    base.update(valores)
    return pd.Series(base)


class TestNormalizarEan(unittest.TestCase):
    def test_deja_pasar_un_ean_correcto(self):
        self.assertEqual(app.centry_normalizar_ean("7798712345678"), "7798712345678")

    def test_arregla_la_notacion_cientifica_de_excel(self):
        """Regresion: "7.79871E+12" no es vacio, asi que llegaba a Centry."""
        self.assertEqual(app.centry_normalizar_ean("7.798712345678E+12"), "7798712345678")

    def test_quita_el_punto_cero_de_los_float(self):
        self.assertEqual(app.centry_normalizar_ean("7798712345678.0"), "7798712345678")
        self.assertEqual(app.centry_normalizar_ean(7798712345678.0), "7798712345678")

    def test_no_recorta_un_decimal_de_verdad(self):
        """Si hay decimales reales no es un EAN: se limpia, no se inventa."""
        self.assertEqual(app.centry_normalizar_ean("123.45"), "12345")

    def test_los_rellenos_cuentan_como_vacio(self):
        for valor in ["", "   ", None, "0", "00000000", "#N/D", "-"]:
            self.assertEqual(app.centry_normalizar_ean(valor), "", repr(valor))

    def test_limpia_espacios_y_guiones(self):
        self.assertEqual(app.centry_normalizar_ean(" 7798-7123 45678 "), "7798712345678")


class TestClaveDeSku(unittest.TestCase):
    def test_ignora_formato_y_mayusculas(self):
        self.assertEqual(app.centry_clave_sku(" rk-5470311 "), "RK5470311")
        self.assertEqual(app.centry_clave_sku("5470311.0"), "5470311")

    def test_la_variante_sin_ceros_empareja_con_el_maestro(self):
        self.assertEqual(app.centry_clave_sku_sin_ceros("0012345"),
                         app.centry_clave_sku_sin_ceros("12345"))


class TestIndiceDelMaestro(unittest.TestCase):
    def test_una_fila_sin_ean_no_tapa_a_la_que_si_lo_trae(self):
        """Regresion 1: el maestro trae una fila por bodega.

        La primera venia sin CodBarras y `setdefault` la dejaba fija, asi que
        el SKU se quedaba sin EAN para siempre.
        """
        arti = pd.DataFrame([
            {"CODINT_MA": "5470311", "COD MOD COL": "RK21101121-085",
             "TALNUM_MA": "37", "CodBarras": "", "ColorNombre": "Negro"},
            {"CODINT_MA": "5470311", "COD MOD COL": "RK21101121-085",
             "TALNUM_MA": "37", "CodBarras": "7800160712101", "ColorNombre": "Negro"},
        ])
        lookup = app.build_centry_arti_lookup(arti)
        self.assertEqual(lookup["by_sku"]["5470311"]["barcode"], "7800160712101")

    def test_conserva_talla_y_color_al_completar_el_ean(self):
        arti = pd.DataFrame([
            {"CODINT_MA": "5470311", "COD MOD COL": "RK21101121-085",
             "TALNUM_MA": "37", "CodBarras": "", "ColorNombre": "Negro"},
            {"CODINT_MA": "5470311", "COD MOD COL": "RK21101121-085",
             "TALNUM_MA": "37", "CodBarras": "7800160712101", "ColorNombre": ""},
        ])
        item = app.build_centry_arti_lookup(arti)["by_sku"]["5470311"]
        self.assertEqual(item["barcode"], "7800160712101")
        self.assertEqual(item["color_name"], "Negro")

    def test_indexa_tambien_sin_ceros_a_la_izquierda(self):
        arti = pd.DataFrame([
            {"CODINT_MA": "12345", "COD MOD COL": "HP1-NEG",
             "TALNUM_MA": "38", "CodBarras": "7798712345678", "ColorNombre": ""},
        ])
        lookup = app.build_centry_arti_lookup(arti)
        self.assertIn("12345", lookup["by_sku"])

    def test_el_ean_del_maestro_se_normaliza_al_indexar(self):
        arti = pd.DataFrame([
            {"CODINT_MA": "12345", "COD MOD COL": "HP1-NEG",
             "TALNUM_MA": "38", "CodBarras": "7.798712345678E+12", "ColorNombre": ""},
        ])
        lookup = app.build_centry_arti_lookup(arti)
        self.assertEqual(lookup["by_sku"]["12345"]["barcode"], "7798712345678")


class TestResolverEan(unittest.TestCase):
    """El orden de fuentes que pidio negocio, y que se recorra entero."""

    def setUp(self):
        self.arti = pd.DataFrame([
            {"CODINT_MA": "12345", "COD MOD COL": "HP1-NEG",
             "TALNUM_MA": "38", "CodBarras": "7798700000001", "ColorNombre": "Negro"},
        ])
        self.lookup = app.build_centry_arti_lookup(self.arti)

    def test_primero_el_input(self):
        row = fila(**{"Variant SKU": "12345",
                      "Código de barra variante (EAN/UPC/ISBN)": "7798799999999"})
        ean, fuente = app.centry_resolver_ean(row, {}, self.lookup, "HP1-NEG", "38")
        self.assertEqual(ean, "7798799999999")
        self.assertIn("Input", fuente)

    def test_despues_el_variant_barcode_de_shopify(self):
        row = fila(**{"Variant SKU": "12345", "Variant Barcode": "7798788888888"})
        ean, fuente = app.centry_resolver_ean(row, {}, self.lookup, "HP1-NEG", "38")
        self.assertEqual(ean, "7798788888888")
        self.assertEqual(fuente, "Shopify (Variant Barcode)")

    def test_luego_el_maestro_por_sku(self):
        row = fila(**{"Variant SKU": "12345"})
        item = self.lookup["by_sku"]["12345"]
        ean, fuente = app.centry_resolver_ean(row, item, self.lookup, "HP1-NEG", "38")
        self.assertEqual(ean, "7798700000001")
        self.assertIn("Maestro", fuente)

    def test_rescata_el_sku_con_ceros_a_la_izquierda(self):
        """Regresion 2: "0012345" contra "12345" del maestro.

        `centry_arti_item_for_row` empareja por cadena exacta y no lo
        encontraba, asi que la variante salia sin EAN.
        """
        row = fila(**{"Variant SKU": "0012345"})
        ean, fuente = app.centry_resolver_ean(row, {}, self.lookup, "", "")
        self.assertEqual(ean, "7798700000001")
        self.assertIn("normalizado", fuente)

    def test_ultimo_recurso_mod_col_mas_talla(self):
        row = fila(**{"Variant SKU": "SKU-QUE-NO-ESTA"})
        ean, fuente = app.centry_resolver_ean(row, {}, self.lookup, "HP1-NEG", "38")
        self.assertEqual(ean, "7798700000001")
        self.assertIn("Mod-Col", fuente)

    def test_sin_ninguna_fuente_queda_marcado_como_pendiente(self):
        """No se deja vacio en silencio: la fuente dice PENDIENTE."""
        row = fila(**{"Variant SKU": "SKU-QUE-NO-ESTA"})
        ean, fuente = app.centry_resolver_ean(row, {}, self.lookup, "OTRO-COD", "99")
        self.assertEqual(ean, "")
        self.assertEqual(fuente, app.CENTRY_EAN_SIN_RESOLVER)

    def test_un_ean_roto_en_el_input_no_bloquea_las_demas_fuentes(self):
        """Regresion 3: "0" o "#N/D" en el input contaban como valor."""
        row = fila(**{"Variant SKU": "12345", "Variant Barcode": "0"})
        ean, fuente = app.centry_resolver_ean(row, {}, self.lookup, "HP1-NEG", "38")
        self.assertEqual(ean, "7798700000001")
        self.assertIn("Maestro", fuente)

    def test_normaliza_el_ean_venga_de_donde_venga(self):
        row = fila(**{"Variant SKU": "12345", "Variant Barcode": "7.798788888888E+12"})
        ean, _ = app.centry_resolver_ean(row, {}, self.lookup, "HP1-NEG", "38")
        self.assertEqual(ean, "7798788888888")


if __name__ == "__main__":
    unittest.main(verbosity=2)
