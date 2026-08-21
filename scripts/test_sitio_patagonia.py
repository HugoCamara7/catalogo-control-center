# -*- coding: utf-8 -*-
"""Patagonia.pe como sitio propio, con todas las funciones.

Hasta ahora Patagonia era una MARCA dentro de Rockford.pe: sus productos se
cargaban en esa tienda. Con tienda propia pasa a ser un SITIO, y eso tiene que
alcanzar a todo: selector, fotos, input comercial, Centry, SIAL y solicitudes.

Casi todo sale de una sola entrada en `SITE_CONFIGS`, que es de donde leen
`sites_for_commercial_brand`, `configured_commercial_brands`,
`publication_column_for_site` y el selector de sitio. Estas pruebas comprueban
que la activacion llego a cada sitio, no solo al diccionario.

Durante la transicion Patagonia sigue apareciendo en Rockford.pe, porque ese
sitio la mantiene en `allowed_arti_brands`: la plantilla trae las DOS columnas
de publicacion y se decide producto por producto.

Ejecutar:  python scripts/test_sitio_patagonia.py
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
from engines import garment_types as gt  # noqa: E402

COD = "PT12345-NEG"
BODY = (
    '<div class="nweb__Materiales"><ul>'
    '<li>Material exterior: 100% Nylon</li><li>Forro: 100% Poliester</li>'
    '</ul></div>'
    '<div class="nweb__Cuidados"><ul><li>Lavar a mano</li></ul></div>'
)


def fila(**valores):
    base = {columna: "" for columna in app.MATRIXIFY_COLUMNS}
    base.update(valores)
    return base


def centry_patagonia():
    cfg = g.get_brand_config("patagonia")
    mx = pd.DataFrame([
        fila(**{
            "Handle": "casaca", "Title": "Casaca Patagonia", "Body HTML": BODY,
            "Vendor": "Patagonia", "Type": "Casacas", "Image Src": "https://cdn/f.jpg",
            "Variant SKU": "8001", "Option1 Value": "M", "Variant Price": "499",
            "Metafield: custom.codigo_modelo_color [id]": COD,
            "Metafield: custom.genero [single_line_text_field]": "Masculino",
        }),
        fila(**{
            "Handle": "casaca", "Variant SKU": "8002", "Option1 Value": "L",
            "Metafield: custom.codigo_modelo_color [id]": COD,
        }),
    ])
    arti = pd.DataFrame([
        {"CODINT_MA": "8001", "COD MOD COL": COD, "TALNUM_MA": "M", "MARCA_MA": "PATAGONIA",
         "CodBarras": "7798780000001", "ColorNombre": "Negro", "Precio": "499",
         "Genero": "MASCULINO", "TipoProducto": "Casacas"},
        {"CODINT_MA": "8002", "COD MOD COL": COD, "TALNUM_MA": "L", "MARCA_MA": "PATAGONIA",
         "CodBarras": "7798780000002", "ColorNombre": "Negro", "Precio": "499",
         "Genero": "MASCULINO", "TipoProducto": "Casacas"},
    ])
    return cfg, app.build_centry_from_matrixify(mx, cfg, arti_df=arti)


class TestElSitioExiste(unittest.TestCase):
    def test_esta_en_la_configuracion_de_sitios(self):
        self.assertIn("patagonia", g.SITE_CONFIGS)

    def test_sale_en_el_selector_de_sitio(self):
        etiquetas = {config["site_label"] for config in g.SITE_CONFIGS.values()}
        self.assertIn("Patagonia.pe", etiquetas)

    def test_tiene_su_propia_ficha(self):
        cfg = g.get_brand_config("patagonia")
        self.assertEqual(cfg["label"], "Patagonia")
        self.assertEqual(cfg["site_label"], "Patagonia.pe")
        self.assertEqual(cfg["store_domain"], "Patagonia.pe")
        self.assertEqual(cfg["allowed_arti_brands"], ["PATAGONIA"])

    def test_no_rompe_los_sitios_que_ya_estaban(self):
        for clave in ("columbia", "rockford", "hush_puppies", "vans"):
            with self.subTest(sitio=clave):
                self.assertIn(clave, g.SITE_CONFIGS)


class TestFotos(unittest.TestCase):
    def test_usa_su_carpeta_del_bucket(self):
        cfg = g.get_brand_config("patagonia")
        self.assertTrue(cfg["image_base_url"].endswith("/PATAGONIA"))

    def test_el_motor_normal_arma_sus_jpg(self):
        cfg = g.get_brand_config("patagonia")
        urls = g.image_candidates(COD, cfg)
        self.assertEqual(len(urls), g.MAX_IMAGES_PER_PRODUCT)
        self.assertTrue(urls[0].endswith("PT12345_NEG_1.jpg"))

    def test_el_mantenedor_arma_sus_png_y_jpeg(self):
        cfg = g.brand_image_config("Patagonia", g.get_brand_config("patagonia"))
        self.assertTrue(app.png_image_candidates(COD, cfg, "png")[0].endswith("PT12345_NEG_1.png"))
        self.assertTrue(app.png_image_candidates(COD, cfg, "jpeg")[0].endswith("PT12345_NEG_1.jpeg"))

    def test_tiene_logo(self):
        self.assertTrue(app.brand_logo_path_for_name("Patagonia"))


class TestInputComercial(unittest.TestCase):
    def test_la_marca_apunta_a_su_sitio(self):
        perfil = app.commercial_input_profile_for_brand("Patagonia")
        self.assertEqual(perfil["site_profile"], "Patagonia.pe")

    def test_trae_la_columna_de_publicacion_de_patagonia(self):
        columnas = app.commercial_input_columns_for_brand("Patagonia")
        self.assertIn("PUBLICAR_PATAGONIA_PE", columnas)

    def test_conserva_rockford_durante_la_transicion(self):
        """Patagonia sigue en `allowed_arti_brands` de Rockford.pe a proposito:
        asi se puede publicar en los dos sitios mientras dura el cambio."""
        columnas = app.commercial_input_columns_for_brand("Patagonia")
        self.assertIn("PUBLICAR_ROCKFORD_PE", columnas)

    def test_la_marca_figura_en_los_dos_sitios(self):
        sitios = {s["site_label"] for s in app.sites_for_commercial_brand("Patagonia")}
        self.assertEqual(sitios, {"Rockford.pe", "Patagonia.pe"})

    def test_esta_entre_las_marcas_comerciales(self):
        self.assertIn("Patagonia", app.configured_commercial_brands())

    def test_conserva_sus_clases(self):
        self.assertEqual(
            app.commercial_allowed_classes_for_brand("Patagonia"), ["Vestuario", "Accesorios"]
        )

    def test_la_plantilla_en_blanco_se_genera(self):
        df = app._commercial_input_blank_df("Patagonia", rows=2)
        self.assertIn("PUBLICAR_PATAGONIA_PE", df.columns)
        self.assertIn("Mod-Col", df.columns)


class TestTiposDePrenda(unittest.TestCase):
    def test_un_sitio_nuevo_usa_el_nombre_canonico(self):
        """No se inventa una nomenclatura propia: hasta que Patagonia declare
        la suya, cada tipo sale con su nombre canonico."""
        self.assertEqual(gt.tipo_para_sitio("Casacas", "patagonia"), "Casacas")
        self.assertEqual(gt.tipo_para_sitio("Polares", "patagonia"), "Polares")

    def test_no_se_toco_la_nomenclatura_de_los_demas(self):
        self.assertEqual(gt.tipo_para_sitio("Bastones", "columbia"), "Bastones")


class TestCentryDePatagonia(unittest.TestCase):
    def test_genera_una_fila_por_variante(self):
        _, (centry, _) = centry_patagonia()
        self.assertEqual(len(centry), 2)

    def test_sin_hallazgos_bloqueantes(self):
        _, (centry, _) = centry_patagonia()
        validacion = centry.attrs.get("validacion")
        if validacion is None or validacion.empty:
            return
        bloqueantes = validacion[validacion["Severidad"] == "Bloqueante"]
        self.assertEqual(len(bloqueantes), 0, list(bloqueantes["Campo"]))

    def test_cada_variante_con_su_sku_y_su_ean(self):
        _, (centry, _) = centry_patagonia()
        self.assertEqual(list(centry["SKU de la variante"]), ["8001", "8002"])
        self.assertEqual(
            list(centry["Código de barra variante (EAN/UPC/ISBN)"]),
            ["7798780000001", "7798780000002"],
        )

    def test_el_genero_sale_con_el_valor_de_la_plantilla(self):
        _, (centry, _) = centry_patagonia()
        self.assertEqual(
            centry.iloc[0]["Género de vestuario - Ropa y accesorios (Falabella GSC Perú)"],
            "Hombre",
        )

    def test_los_materiales_del_body_llegan(self):
        _, (centry, _) = centry_patagonia()
        fila_centry = centry.iloc[0]
        self.assertEqual(
            fila_centry["Material de vestuario - Ropa y accesorios (Falabella GSC Perú)"],
            "100% Nylon",
        )
        self.assertIn("Material", str(fila_centry["Listado de características"]))

    def test_la_guia_de_tallas_es_la_suya(self):
        _, (centry, _) = centry_patagonia()
        self.assertEqual(centry.iloc[0]["Guía de tallas"], "HombrevestuarioPatagonia")


class TestCargaSial(unittest.TestCase):
    def test_la_cola_sial_tiene_su_product_id(self):
        cfg = g.get_brand_config("patagonia")
        self.assertIn("Porduct Id - Patagonia.pe", cfg["sial_tail_columns"])

    def test_genera_filas(self):
        cfg = g.get_brand_config("patagonia")
        mx = pd.DataFrame([fila(**{
            "Handle": "casaca", "Title": "Casaca Patagonia", "Vendor": "Patagonia",
            "Type": "Casacas", "Variant SKU": "8001", "Option1 Value": "M",
            "Metafield: custom.codigo_modelo_color [id]": COD,
        })])
        self.assertEqual(len(app.build_centry_sial_from_matrixify(mx, cfg)), 1)


if __name__ == "__main__":
    unittest.main(verbosity=2)
