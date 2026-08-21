# -*- coding: utf-8 -*-
"""Pruebas del Centry: herencia entre productos y clase Calzado.

Origen: el Centry generado el 19/08/2026 sacó RK110021743 (una alpargata que
no existe en Shopify) como "Vestuario / Ropa Masculina / Alpargatas", con la
descripción de OTRO modelo y la guía de tallas de vestuario.

Dos fallos encadenados:

1. `build_centry_from_matrixify` arrastraba Title, Body HTML, Type, Tags y los
   metafields con un `ffill()` sobre TODO el archivo, sin agrupar por producto.
   Matrixify escribe ese bloque solo en la primera fila de cada producto, así
   que un producto que llegaba SIN tipo heredaba el del producto ANTERIOR.

2. `centry_is_footwear` buscaba seis palabras ("calzado", "zapatilla",
   "zapato", "botin", "bota", "sandalia") dentro de Type/Tags/Title. Una
   alpargata no trae ninguna: si Shopify no le había puesto el tag "Calzado",
   salía como Vestuario.

Y un tercero, del panel: un precio 0 no contaba como precio faltante, así que
un archivo con los 1.121 precios en 0 salía en verde.

Ejecutar:  python scripts/test_centry_contaminacion.py
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

DESCRIPCION_AJENA = "Alpargata Espanola Adra con aparado y forro de algodon organico."
MARCA = {"label": "Rockford"}
CONFIG_ROCKFORD = g.get_brand_config("rockford")


def fila(**valores):
    base = {columna: "" for columna in app.MATRIXIFY_COLUMNS}
    base.update(valores)
    return base


def matrixify_dos_productos():
    """Un producto completo seguido de otro SIN tipo ni descripción.

    Es la forma exacta que tiene el archivo real: el bloque de producto solo
    aparece en la primera fila de cada producto.
    """
    return pd.DataFrame([
        fila(**{
            "Handle": "alpargata-mujer",
            "Title": "Alpargata Algodon Mujer Rockford",
            "Body HTML": DESCRIPCION_AJENA,
            "Vendor": "Rockford",
            "Type": "Alpargatas",
            "Tags": "Rockford, Calzado",
            "Image Src": "https://ejemplo/1.jpg",
            "Variant SKU": "5470311",
            "Variant Barcode": "7800160712101",
            "Variant Price": "199",
            "Option1 Value": "37",
            "Metafield: custom.codigo_modelo_color [id]": "RK21101121-085",
            "Metafield: custom.genero [single_line_text_field]": "MUJER",
        }),
        fila(**{
            "Handle": "alpargata-mujer",
            "Variant SKU": "5470312",
            "Variant Barcode": "7800160712102",
            "Variant Price": "199",
            "Option1 Value": "38",
        }),
        # El que no existe en Shopify: sin Body HTML y sin Type.
        fila(**{
            "Handle": "rk110021743-5zv",
            "Title": "RK110021743-5ZV",
            "Vendor": "Rockford",
            "Tags": "Rockford",
            "Image Src": "https://ejemplo/2.jpg",
            "Variant SKU": "5486079",
            "Variant Price": "0",
            "Option1 Value": "40",
            "Metafield: custom.codigo_modelo_color [id]": "RK110021743-5ZV",
            "Metafield: custom.genero [single_line_text_field]": "HOMBRE",
        }),
    ])


def centry():
    return app.build_centry_from_matrixify(matrixify_dos_productos(), MARCA)


def fila_de(df, mod_col):
    return df[df["SKU del producto"] == mod_col].iloc[0]


class TestSinHerenciaEntreProductos(unittest.TestCase):
    """Lo que falta se queda vacío; nunca se copia del producto anterior."""

    def test_no_hereda_el_tipo(self):
        salida, _ = centry()
        huerfano = fila_de(salida, "RK110021743-5ZV")
        self.assertNotIn("Alpargata", str(huerfano["Base de categoría"]))

    def test_no_hereda_la_descripcion(self):
        salida, _ = centry()
        huerfano = fila_de(salida, "RK110021743-5ZV")
        self.assertEqual(str(huerfano["Descripcion"]).strip(), "")

    def test_el_producto_completo_si_conserva_su_bloque(self):
        """El arrastre dentro del MISMO producto tiene que seguir vivo."""
        salida, _ = centry()
        variantes = salida[salida["SKU del producto"] == "RK21101121-085"]
        self.assertEqual(len(variantes), 2)
        for _, variante in variantes.iterrows():
            self.assertIn("Adra", str(variante["Descripcion"]))
            self.assertEqual(str(variante["Marca"]), "Rockford")

    def test_avisa_del_producto_sin_tipo(self):
        _, avisos = centry()
        texto = " ".join(avisos["Problema"].astype(str))
        self.assertIn("Sin tipo de prenda", texto)


class TestClaseCalzadoPorDiccionario(unittest.TestCase):
    """La clase la decide el diccionario de tipos, no seis palabras sueltas."""

    def test_alpargata_sin_tag_calzado_es_calzado(self):
        salida, _ = app.build_centry_from_matrixify(
            pd.DataFrame([
                fila(**{
                    "Handle": "alpargata-hombre",
                    "Title": "Alpargata Cuero Hombre Rockford",
                    "Vendor": "Rockford",
                    "Type": "Alpargatas",
                    "Tags": "Rockford",
                    "Image Src": "https://ejemplo/1.jpg",
                    "Variant SKU": "1",
                    "Variant Price": "199",
                    "Option1 Value": "40",
                    "Metafield: custom.codigo_modelo_color [id]": "RK102011405-085",
                    "Metafield: custom.genero [single_line_text_field]": "HOMBRE",
                })
            ]),
            MARCA,
        )
        self.assertEqual(str(salida["Clase"].iloc[0]), "Calzado")
        self.assertTrue(str(salida["Categoría"].iloc[0]).startswith("Calzados"))
        self.assertEqual(str(salida["Guía de tallas"].iloc[0]), "HombrecalzadoRockford")

    def test_los_otros_calzados_del_diccionario(self):
        for tipo in ("Mocasines", "Suecos", "Slip Ons", "Sandalias", "Zapatillas"):
            with self.subTest(tipo=tipo):
                self.assertTrue(app.centry_is_footwear(pd.Series({"Type": tipo})))

    def test_el_vestuario_sigue_siendo_vestuario(self):
        for tipo in ("Camisas", "Polos", "Pantalones", "Blusas"):
            with self.subTest(tipo=tipo):
                self.assertFalse(app.centry_is_footwear(pd.Series({"Type": tipo})))


class TestPrecioCero(unittest.TestCase):
    """El precio NO es obligatorio en Centry.

    El helper sigue existiendo porque lo usan otras pantallas, pero el Centry
    dejo de tratarlo como problema: no bloquea, no es error y no genera
    advertencias. Con 2.297 variantes sin precio, ese aviso tapaba los
    hallazgos que de verdad hay que mirar.
    """

    def test_el_helper_sigue_distinguiendo_un_precio_vacio(self):
        for valor in ("0", "0.0", "", "0,00"):
            with self.subTest(valor=valor):
                self.assertTrue(app.centry_price_is_missing(valor))

    def test_un_precio_real_no_falta(self):
        for valor in ("199", "199.90", "1,50"):
            with self.subTest(valor=valor):
                self.assertFalse(app.centry_price_is_missing(valor))

    def test_ya_no_genera_ninguna_observacion(self):
        _, avisos = centry()
        texto = " ".join(avisos["Problema"].astype(str))
        self.assertNotIn("Sin precio", texto)

    def test_tampoco_es_un_hallazgo_de_la_validacion(self):
        centry_df, _ = centry()
        validacion = centry_df.attrs.get("validacion")
        campos = set(validacion["Campo"]) if validacion is not None and not validacion.empty else set()
        self.assertNotIn("Precio", campos)


class TestTipoDesdeElMaestro(unittest.TestCase):
    """Sin tipo en Shopify ni en TipoProducto, se mira la subcategoría."""

    CODIGO = "RK110021743-5ZV"

    def _arti(self, **extra):
        base = {
            "Mod-Col": self.CODIGO, "COD MOD COL": self.CODIGO, "CODINT_MA": "5486079",
            "TALNUM_MA": "40", "MARCA_MA": "ROCKFORD", "Precio": "0", "CodBarras": "",
        }
        base.update(extra)
        return pd.DataFrame([base])

    def _construir(self, **extra):
        return app.build_centry_matrixify_from_master(
            [self.CODIGO],
            pd.DataFrame(columns=app.MATRIXIFY_COLUMNS),
            self._arti(**extra),
            CONFIG_ROCKFORD,
        )

    def test_usa_la_subcategoria_si_el_diccionario_la_reconoce(self):
        salida, avisos = self._construir(SubCategoria="Alpargatas")
        self.assertEqual(str(salida["Type"].iloc[0]), "Alpargatas")
        self.assertIn("subcategoria del maestro", " ".join(avisos["Problema"].astype(str)))

    def test_no_acepta_una_subcategoria_que_no_es_un_tipo(self):
        salida, avisos = self._construir(SubCategoria="Linea Verano")
        self.assertEqual(str(salida["Type"].iloc[0]), "")
        self.assertIn(
            "Sin tipo de prenda en Shopify ni en BigQuery/ARTI",
            " ".join(avisos["Problema"].astype(str)),
        )

    def test_avisa_cuando_el_nombre_es_el_codigo(self):
        _, avisos = self._construir(SubCategoria="Alpargatas")
        self.assertIn("Sin nombre de producto", " ".join(avisos["Problema"].astype(str)))


if __name__ == "__main__":
    unittest.main(verbosity=2)
