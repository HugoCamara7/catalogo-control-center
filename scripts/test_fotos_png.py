# -*- coding: utf-8 -*-
"""Pruebas del Mantenedor Fotos PNG y de que el motor normal no cambió.

La regla que estas pruebas protegen: **la carga normal busca SOLO .jpg**.
Buscar las dos extensiones duplicaría las peticiones HEAD por producto y
alargaría cada carga del catálogo completo. El PNG es una herramienta manual,
aparte, para los casos en que la foto solo existe en ese formato
(Hush Puppies).

Ejecutar:  python scripts/test_fotos_png.py
"""
import inspect
import re
import sys
import types
import unittest
from pathlib import Path

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

CONFIG = g.get_brand_config("hush_puppies")
CODIGO = "HP1234567-001"
BASE = CONFIG["image_base_url"]


class TestElMotorNormalNoCambio(unittest.TestCase):
    """La carga normal sigue siendo JPG y nada más."""

    def test_image_candidates_solo_jpg(self):
        urls = g.image_candidates(CODIGO, CONFIG)
        self.assertEqual(len(urls), g.MAX_IMAGES_PER_PRODUCT)
        self.assertTrue(all(url.endswith(".jpg") for url in urls))
        self.assertNotIn("png", " ".join(urls).lower())

    def test_el_generador_no_sabe_de_png(self):
        """Ninguna función de fotos del motor menciona PNG."""
        for funcion in (g.image_candidates, g.build_image_lookup, g.url_is_image):
            with self.subTest(funcion=funcion.__name__):
                self.assertNotIn("png", inspect.getsource(funcion).lower())

    def test_la_carga_parcial_de_fotos_tampoco(self):
        """`build_matrixify_updates` arma las fotos sin tocar el camino PNG."""
        self.assertNotIn("png", inspect.getsource(app.build_matrixify_updates).lower())

    def test_el_mantenedor_no_reutiliza_la_funcion_del_motor(self):
        """Son caminos distintos a propósito: uno no puede arrastrar al otro.

        `png_image_candidates` sí vale; lo que no puede aparecer es una llamada
        a `image_candidates`, la del motor rápido.
        """
        fuente = inspect.getsource(app.png_probe_views)
        self.assertIsNone(re.search(r"\bimage_candidates\(", fuente))
        self.assertIn("png_image_candidates(", fuente)


class TestCandidatasPng(unittest.TestCase):
    """Diez vistas, en orden, con el mismo nombre que el motor JPG."""

    def test_diez_vistas_en_orden(self):
        urls = app.png_image_candidates(CODIGO, CONFIG)
        self.assertEqual(len(urls), app.PNG_MAX_VISTAS)
        self.assertEqual(urls[0], f"{BASE}/HP1234567_001_1.png")
        self.assertEqual(urls[-1], f"{BASE}/HP1234567_001_10.png")
        self.assertTrue(all(url.endswith(".png") for url in urls))

    def test_mismo_nombre_que_el_jpg(self):
        jpg = g.image_candidates(CODIGO, CONFIG)
        png = app.png_image_candidates(CODIGO, CONFIG)
        self.assertEqual(
            [url.rsplit(".", 1)[0] for url in jpg],
            [url.rsplit(".", 1)[0] for url in png],
        )

    def test_un_codigo_sin_color_no_da_nada(self):
        self.assertEqual(app.png_image_candidates("HP1234567", CONFIG), [])
        self.assertEqual(app.png_image_candidates("", CONFIG), [])


class TestNoRepetirFotos(unittest.TestCase):
    """Una foto que el producto ya tiene no se vuelve a subir."""

    def test_reconoce_la_misma_foto(self):
        self.assertTrue(app.png_already_uploaded("hp1234567_001_1", {"hp1234567_001_1"}))

    def test_acepta_el_sufijo_que_agrega_shopify(self):
        self.assertTrue(app.png_already_uploaded("hp1234567_001_1", {"hp1234567_001_1_a1b2c3"}))

    def test_la_vista_1_no_se_confunde_con_la_10(self):
        """El error clásico de comparar con startswith."""
        self.assertFalse(app.png_already_uploaded("hp1234567_001_1", {"hp1234567_001_10"}))

    def test_la_extension_no_importa_para_comparar(self):
        stem = app.png_file_stem(f"{BASE}/HP1234567_001_1.png")
        existente = app.png_file_stem("https://cdn.shopify.com/s/files/1/HP1234567_001_1.jpg?v=17")
        self.assertEqual(stem, existente)


class TestEstadoDeCadaVista(unittest.TestCase):
    """Encontrada / Ya existente / No existe / Error, vista por vista."""

    def setUp(self):
        self.original = g.url_is_image
        # Solo existen en PNG las vistas 1, 2 y 3.
        g.url_is_image = lambda url, timeout=4, brand_config=None: any(
            url.endswith(f"_{numero}.png") for numero in (1, 2, 3)
        )

    def tearDown(self):
        g.url_is_image = self.original

    def test_marca_las_que_existen(self):
        filas = app.png_probe_views(CODIGO, CONFIG)
        estados = [fila["Estado"] for fila in filas]
        self.assertEqual(estados[:3], ["Encontrada"] * 3)
        self.assertEqual(set(estados[3:]), {"No existe"})

    def test_marca_las_que_el_producto_ya_tiene(self):
        actuales = ["https://cdn.shopify.com/s/files/1/HP1234567_001_2.png?v=1"]
        filas = app.png_probe_views(CODIGO, CONFIG, actuales)
        por_vista = {fila["Vista"]: fila["Estado"] for fila in filas}
        self.assertEqual(por_vista[1], "Encontrada")
        self.assertEqual(por_vista[2], "Ya existente")
        self.assertEqual(por_vista[3], "Encontrada")

    def test_solo_se_suben_las_encontradas_y_en_orden(self):
        actuales = ["https://cdn.shopify.com/s/files/1/HP1234567_001_2.png"]
        subir = app.png_views_to_upload(app.png_probe_views(CODIGO, CONFIG, actuales))
        self.assertEqual(subir, [f"{BASE}/HP1234567_001_1.png", f"{BASE}/HP1234567_001_3.png"])

    def test_nunca_mas_de_diez(self):
        g.url_is_image = lambda url, timeout=4, brand_config=None: True
        filas = app.png_probe_views(CODIGO, CONFIG)
        self.assertEqual(len(filas), app.PNG_MAX_VISTAS)
        self.assertLessEqual(len(app.png_views_to_upload(filas)), 10)

    def test_un_fallo_de_red_queda_como_error(self):
        def revienta(url, timeout=4, brand_config=None):
            raise OSError("timeout")

        g.url_is_image = revienta
        filas = app.png_probe_views(CODIGO, CONFIG)
        self.assertEqual({fila["Estado"] for fila in filas}, {"Error"})
        self.assertEqual(app.png_views_to_upload(filas), [])


class TestBuscarElProducto(unittest.TestCase):
    def test_encuentra_por_codigo_modelo_color(self):
        productos = [{"Mod-Col": "HP0000000-999"}, {"Mod-Col": CODIGO, "Handle": "zapato"}]
        self.assertEqual(app.png_find_product(productos, CODIGO)["Handle"], "zapato")

    def test_no_distingue_mayusculas(self):
        productos = [{"Mod-Col": CODIGO}]
        self.assertIsNotNone(app.png_find_product(productos, CODIGO.lower()))

    def test_devuelve_none_si_no_esta(self):
        self.assertIsNone(app.png_find_product([{"Mod-Col": "OTRO-001"}], CODIGO))
        self.assertIsNone(app.png_find_product([], ""))


if __name__ == "__main__":
    unittest.main(verbosity=2)
