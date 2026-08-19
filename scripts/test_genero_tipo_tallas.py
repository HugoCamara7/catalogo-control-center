"""Pruebas de Género, Tipo de prenda y talla 0 en la carga parcial.

Origen: dos fallos reportados sobre el catálogo generado.

1. El Género salía vacío. La carga parcial solo miraba Shopify y, si el producto
   no estaba o no tenía el metafield, no completaba nada — aunque BigQuery/ARTI
   sí trae `Genero` y `TipoProducto` en ARTI_OPTIONAL_COLUMNS.

2. Productos de Vestuario y Accesorios con tallas reales (S/M/L/XL) salían
   ADEMAS con una variante de talla 0, que terminaba publicada en Shopify. La
   carga completa ya lo filtraba con `final_variant_filter`; la parcial armaba
   su Matrixify por su cuenta y nunca pasaba por ese filtro.

Ejecutar:  python scripts/test_genero_tipo_tallas.py
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
import generate_columbia_matrixify as g  # noqa: E402

CONFIG = g.get_brand_config("columbia")
CODIGO = "CB100-001"


def arti(tallas, **extra):
    """Maestro BigQuery/ARTI con las tallas dadas."""
    return pd.DataFrame([
        {
            "Mod-Col": CODIGO, "COD MOD COL": CODIGO, "CODINT_MA": f"SKU{indice}",
            "TALNUM_MA": talla, "MARCA_MA": "COLUMBIA", "Precio": "10",
            "CodBarras": "7790000000001", **extra,
        }
        for indice, talla in enumerate(tallas, start=1)
    ])


def shopify_vacio():
    return pd.DataFrame(columns=app.MATRIXIFY_COLUMNS)


def construir(tallas, shopify=None, **extra):
    return app.build_centry_matrixify_from_master(
        [CODIGO], shopify if shopify is not None else shopify_vacio(), arti(tallas, **extra), CONFIG
    )


def tallas_de(df):
    return [str(valor).strip() for valor in df["Option1 Value"]] if len(df) else []


class TestNoCrearTallaCero(unittest.TestCase):
    """Si hay cualquier talla real, nunca se crea la talla 0."""

    def test_letras_no_generan_cero(self):
        salida, _ = construir(["0", "S", "M", "L", "XL"])
        self.assertEqual(tallas_de(salida), ["S", "M", "L", "XL"])
        self.assertNotIn("0", tallas_de(salida))

    def test_rango_completo_de_letras(self):
        salida, _ = construir(["0", "XS", "S", "M", "L", "XL", "XXL"])
        self.assertEqual(tallas_de(salida), ["XS", "S", "M", "L", "XL", "XXL"])

    def test_numeros_no_generan_cero(self):
        salida, _ = construir(["0", "36", "37", "38", "39"])
        self.assertEqual(tallas_de(salida), ["36", "37", "38", "39"])

    def test_el_cero_al_final_tampoco_pasa(self):
        # El orden en que llega del maestro no debe cambiar el resultado.
        salida, _ = construir(["S", "M", "L", "0"])
        self.assertNotIn("0", tallas_de(salida))

    def test_talla_unica_real_si_se_conserva(self):
        """Sin ninguna talla real, el 0 es la talla única legítima."""
        salida, _ = construir(["0"])
        self.assertEqual(tallas_de(salida), ["0"])

    def test_avisa_de_lo_que_descarto(self):
        _, avisos = construir(["0", "S", "M"])
        texto = " ".join(avisos["Problema"].astype(str))
        self.assertIn("descartaron", texto)


class TestGeneroYTipoNuncaVacios(unittest.TestCase):
    """Shopify manda; si no tiene el dato, se completa desde BigQuery/ARTI."""

    def test_los_toma_de_bigquery_si_shopify_no_esta(self):
        salida, _ = construir(["S", "M"], Genero="MUJER", TipoProducto="Casacas")
        self.assertEqual(
            salida["Metafield: custom.genero [single_line_text_field]"].iloc[0], "MUJER"
        )
        self.assertEqual(salida["Type"].iloc[0], "Casacas")

    def test_deja_constancia_de_la_fuente(self):
        _, avisos = construir(["S"], Genero="MUJER", TipoProducto="Casacas")
        texto = " ".join(avisos["Problema"].astype(str))
        self.assertIn("Genero completado desde BigQuery/ARTI", texto)

    def test_shopify_tiene_prioridad(self):
        shopify = pd.DataFrame([{columna: "" for columna in app.MATRIXIFY_COLUMNS}])
        shopify.loc[0, "Handle"] = "casaca-cb100-001"
        shopify.loc[0, "Metafield: custom.codigo_modelo_color [id]"] = CODIGO
        shopify.loc[0, "Metafield: custom.genero [single_line_text_field]"] = "HOMBRE"
        shopify.loc[0, "Type"] = "Chaquetas"
        salida, _ = construir(["S"], shopify=shopify, Genero="MUJER", TipoProducto="Casacas")
        self.assertEqual(
            salida["Metafield: custom.genero [single_line_text_field]"].iloc[0], "HOMBRE"
        )
        self.assertEqual(salida["Type"].iloc[0], "Chaquetas")

    def test_avisa_cuando_no_esta_en_ninguna_fuente(self):
        _, avisos = construir(["S"])
        texto = " ".join(avisos["Problema"].astype(str))
        self.assertIn("Sin genero en Shopify ni en BigQuery/ARTI", texto)
        self.assertIn("Sin tipo de prenda en Shopify ni en BigQuery/ARTI", texto)


class TestReglaCentral(unittest.TestCase):
    """La regla vive en el motor, no en un parche de Centry."""

    def test_la_parcial_usa_el_mismo_filtro_que_la_completa(self):
        entrada = pd.DataFrame([
            {"Handle": "casaca", "Option1 Value": talla, "Variant SKU": f"SKU{i}",
             "Type": "Casacas", "Tags": "Vestuario"}
            for i, talla in enumerate(["0", "S", "M"], start=1)
        ])
        salida, _, _ = g.final_variant_filter(entrada, pd.DataFrame(), pd.DataFrame())
        self.assertEqual([str(v) for v in salida["Option1 Value"]], ["S", "M"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
