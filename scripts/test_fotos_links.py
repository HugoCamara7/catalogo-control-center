# -*- coding: utf-8 -*-
"""Pruebas de "Fotos 10 vistas" con links propios.

La opción nueva de la pantalla de fotos deja subir un Excel con el código
modelo color y los links de las fotos nuevas, para cuando la foto no vive en el
bucket de la marca y no hay forma de armar la URL desde el código.

Lo que estas pruebas protegen:

1. Con links, las URLs salen del Excel tal cual: no se arma ninguna candidata
   por código ni se toca `image_candidates`.
2. **Sin archivo, el modo links no puede caer al catálogo completo.** El modo
   bucket sí lo hace (revisa todo el sitio), y ahí es correcto; con links sería
   generar un REPLACE sin fotos para cada producto del catálogo.
3. El modo bucket de siempre no cambió: 10 vistas .jpg armadas por código.

Ejecutar:  python scripts/test_fotos_links.py
"""
import inspect
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

import pandas as pd  # noqa: E402

import app_matrixify as app  # noqa: E402
import generate_columbia_matrixify as g  # noqa: E402

CONFIG = g.get_brand_config("hush_puppies")
CODIGO = "HP1234567-001"
LINK_1 = "https://cdn.otrositio.com/campania/hp1234567_frente.jpg"
LINK_2 = "https://cdn.otrositio.com/campania/hp1234567_lateral.png"
LINK_3 = "https://cdn.otrositio.com/campania/hp1234567_detalle.webp"

PRODUCTOS = [
    {
        "Mod-Col": CODIGO,
        "Product ID": "gid://shopify/Product/111",
        "Legacy ID": "111",
        "Handle": "zapato-hp1234567-001",
        "Title": "Zapato de prueba",
        "Image Src": "https://bucket.forus.com/HP1234567_001_1.jpg",
        "Media IDs": "gid://shopify/MediaImage/1; gid://shopify/MediaImage/2",
        "Vendor": "Hush Puppies",
        "Variants": [],
    },
    {
        "Mod-Col": "HP7654321-002",
        "Product ID": "gid://shopify/Product/222",
        "Legacy ID": "222",
        "Handle": "zapato-hp7654321-002",
        "Title": "Otro zapato",
        "Image Src": "",
        "Media IDs": "",
        "Vendor": "Hush Puppies",
        "Variants": [],
    },
]

BRAND_CONFIG = dict(CONFIG)
BRAND_CONFIG.setdefault("site_label", "Hush Puppies")
BRAND_CONFIG.setdefault("site_key", "hush_puppies")


def preview(update_df, photo_source, image_mode="replace", only_missing_images=False):
    return app.build_shopify_update_preview(
        PRODUCTOS,
        update_df,
        "photos",
        BRAND_CONFIG,
        image_mode=image_mode,
        only_missing_images=only_missing_images,
        photo_source=photo_source,
    )


class TestLecturaDeLinks(unittest.TestCase):
    """Sacar las URLs de una celda cualquiera del Excel."""

    def test_separa_por_coma_punto_y_coma_y_espacio(self):
        celda = f"{LINK_1}, {LINK_2}; {LINK_3}"
        self.assertEqual(g.split_photo_links(celda), [LINK_1, LINK_2, LINK_3])

    def test_ignora_lo_que_no_es_url(self):
        self.assertEqual(g.split_photo_links("pendiente de foto"), [])
        self.assertEqual(g.split_photo_links(""), [])
        self.assertEqual(g.split_photo_links(None), [])

    def test_limpia_comillas_y_parentesis_pegados(self):
        self.assertEqual(g.split_photo_links(f'"{LINK_1}"'), [LINK_1])
        self.assertEqual(g.split_photo_links(f"<{LINK_1}>"), [LINK_1])

    def test_reconoce_las_cabeceras_de_fotos(self):
        for cabecera in ("Foto 1", "FOTO_2", "Imagen", "URL Imagen", "Image Src", "Link foto", "Vista 3"):
            with self.subTest(cabecera=cabecera):
                self.assertTrue(g.is_photo_link_column(cabecera))

    def test_no_confunde_el_link_de_la_ficha_con_una_foto(self):
        """Una columna 'URL del producto' no es una foto.

        Sin este filtro, el link de la ficha de Shopify entraría a la galería.
        """
        for cabecera in ("URL del producto", "Handle", "Link de la página", "Guía de tallas"):
            with self.subTest(cabecera=cabecera):
                self.assertFalse(g.is_photo_link_column(cabecera))

    def test_solo_lee_las_columnas_de_fotos_cuando_existen(self):
        fila = pd.Series({"Foto 1": LINK_1, "URL del producto": "https://tienda.com/products/x"})
        self.assertEqual(g.photo_links_from_row(fila), [LINK_1])

    def test_sin_columnas_reconocibles_rescata_lo_que_parezca_url(self):
        fila = pd.Series({"Columna sin nombre util": f"{LINK_1} {LINK_2}"})
        self.assertEqual(g.photo_links_from_row(fila), [LINK_1, LINK_2])

    def test_no_repite_links(self):
        fila = pd.Series({"Foto 1": LINK_1, "Foto 2": LINK_1, "Foto 3": LINK_2})
        self.assertEqual(g.photo_links_from_row(fila), [LINK_1, LINK_2])


class TestNormalizarElExcel(unittest.TestCase):
    """Los dos formatos que salen naturalmente de un Excel."""

    def test_una_fila_con_varias_columnas_de_fotos(self):
        df = pd.DataFrame([{"Cod Mod Col": CODIGO, "Foto 1": LINK_1, "Foto 2": LINK_2, "Foto 3": LINK_3}])
        salida = app.normalize_photo_links_input(df)
        self.assertEqual(len(salida), 1)
        self.assertEqual(salida.iloc[0]["Mod-Col"], CODIGO)
        self.assertEqual(
            salida.iloc[0][app.PHOTO_LINKS_COLUMN],
            "; ".join([LINK_1, LINK_2, LINK_3]),
        )

    def test_una_fila_por_foto_repitiendo_el_codigo(self):
        df = pd.DataFrame(
            [
                {"Código Modelo Color": CODIGO, "Link": LINK_1},
                {"Código Modelo Color": CODIGO, "Link": LINK_2},
                {"Código Modelo Color": "HP7654321-002", "Link": LINK_3},
            ]
        )
        salida = app.normalize_photo_links_input(df)
        self.assertEqual(len(salida), 2)
        self.assertEqual(salida.iloc[0][app.PHOTO_LINKS_COLUMN], "; ".join([LINK_1, LINK_2]))
        self.assertEqual(salida.iloc[1][app.PHOTO_LINKS_COLUMN], LINK_3)

    def test_archivo_vacio_no_revienta(self):
        self.assertTrue(app.normalize_photo_links_input(None).empty)
        self.assertTrue(app.normalize_photo_links_input(pd.DataFrame()).empty)


class TestVistaPreviaConLinks(unittest.TestCase):
    """La vista previa arma el cambio con los links del Excel."""

    def test_usa_los_links_del_excel_y_no_el_bucket(self):
        df = pd.DataFrame([{"Mod-Col": CODIGO, "Foto 1": LINK_1, "Foto 2": LINK_2}])
        preview_df, issues_df, matrixify_df = preview(df, "links")
        self.assertEqual(len(preview_df), 1)
        fila = preview_df.iloc[0]
        self.assertEqual(fila["Valor nuevo"], "; ".join([LINK_1, LINK_2]))
        self.assertEqual(fila["Modo fotos"], "replace")
        self.assertNotIn(CONFIG["image_base_url"], fila["Valor nuevo"])
        self.assertTrue(issues_df.empty)
        self.assertEqual(matrixify_df.iloc[0]["Image Command"], "REPLACE")

    def test_respeta_el_orden_de_los_links(self):
        df = pd.DataFrame([{"Mod-Col": CODIGO, "Foto 1": LINK_2, "Foto 2": LINK_1}])
        preview_df, _, _ = preview(df, "links")
        self.assertEqual(preview_df.iloc[0]["Valor nuevo"], "; ".join([LINK_2, LINK_1]))

    def test_lo_que_se_aplica_es_exactamente_esa_lista(self):
        """El apply parte 'Valor nuevo' por punto y coma: debe recuperar los links."""
        df = pd.DataFrame([{"Mod-Col": CODIGO, "Foto 1": LINK_1, "Foto 2": LINK_2}])
        preview_df, _, _ = preview(df, "links")
        self.assertEqual(
            app._split_semicolon_values(preview_df.iloc[0]["Valor nuevo"]),
            [LINK_1, LINK_2],
        )

    def test_merge_no_borra_las_fotos_actuales(self):
        df = pd.DataFrame([{"Mod-Col": CODIGO, "Foto 1": LINK_1}])
        preview_df, _, matrixify_df = preview(df, "links", image_mode="merge")
        self.assertEqual(preview_df.iloc[0]["Modo fotos"], "merge")
        self.assertEqual(matrixify_df.iloc[0]["Image Command"], "MERGE")

    def test_reemplaza_aunque_el_producto_ya_tenga_fotos(self):
        """El filtro 'solo sin foto' no aplica: se piden estas fotos a propósito."""
        df = pd.DataFrame([{"Mod-Col": CODIGO, "Foto 1": LINK_1}])
        preview_df, _, _ = preview(df, "links", only_missing_images=True)
        self.assertEqual(len(preview_df), 1)

    def test_una_fila_sin_links_queda_como_observacion(self):
        df = pd.DataFrame([{"Mod-Col": CODIGO, "Foto 1": "pendiente"}])
        preview_df, issues_df, _ = preview(df, "links")
        self.assertTrue(preview_df.empty)
        self.assertEqual(len(issues_df), 1)
        self.assertIn("links", issues_df.iloc[0]["Problema"].lower())

    def test_codigo_que_no_esta_en_shopify_queda_como_observacion(self):
        df = pd.DataFrame([{"Mod-Col": "NOEXISTE-999", "Foto 1": LINK_1}])
        preview_df, issues_df, _ = preview(df, "links")
        self.assertTrue(preview_df.empty)
        self.assertEqual(len(issues_df), 1)

    def test_sin_archivo_no_toca_el_catalogo_completo(self):
        """Sin links no hay nada que aplicar: jamás el catálogo entero.

        En modo bucket, un archivo vacío significa "revisa todo el sitio". Si el
        modo links heredara eso, generaría un REPLACE sin fotos por cada
        producto del catálogo.
        """
        for vacio in (None, pd.DataFrame()):
            with self.subTest(vacio=type(vacio).__name__):
                preview_df, issues_df, matrixify_df = preview(vacio, "links")
                self.assertTrue(preview_df.empty)
                self.assertTrue(matrixify_df.empty)
                self.assertEqual(len(issues_df), 1)


class TestElModoBucketNoCambio(unittest.TestCase):
    """La opción de siempre sigue armando las 10 vistas por código."""

    def test_sin_archivo_revisa_el_catalogo_entero(self):
        preview_df, _, _ = preview(None, "bucket")
        self.assertEqual(len(preview_df), len(PRODUCTOS))

    def test_las_urls_son_las_diez_del_motor(self):
        df = pd.DataFrame([{"Mod-Col": CODIGO}])
        preview_df, _, _ = preview(df, "bucket")
        urls = app._split_semicolon_values(preview_df.iloc[0]["Valor nuevo"])
        self.assertEqual(len(urls), g.MAX_IMAGES_PER_PRODUCT)
        self.assertTrue(all(url.endswith(".jpg") for url in urls))

    def test_el_valor_por_defecto_es_bucket(self):
        """Quien llame sin `photo_source` sigue teniendo el comportamiento viejo."""
        preview_df, _, _ = app.build_shopify_update_preview(
            PRODUCTOS,
            pd.DataFrame([{"Mod-Col": CODIGO}]),
            "photos",
            BRAND_CONFIG,
            only_missing_images=False,
        )
        urls = app._split_semicolon_values(preview_df.iloc[0]["Valor nuevo"])
        self.assertEqual(len(urls), g.MAX_IMAGES_PER_PRODUCT)


class TestDiagnostico(unittest.TestCase):
    """El panel de diagnóstico valida los links igual que las URLs del bucket."""

    def test_links_validos_quedan_listos(self):
        df = pd.DataFrame([{"Mod-Col": CODIGO, "Foto 1": LINK_1, "Foto 2": LINK_2}])
        preview_df, issues_df, _ = preview(df, "links")
        diagnostico = app.build_partial_diagnostic_table(preview_df, issues_df, "photos")
        self.assertEqual(diagnostico.iloc[0]["Estado validacion"], "Listo")
        self.assertEqual(diagnostico.iloc[0]["Cantidad fotos"], 2)


class TestLaPantallaEstaCableada(unittest.TestCase):
    """La opción existe en pantalla y llega hasta el motor.

    Ya pasó antes: lógica escrita y nunca invocada desde la pantalla. Esta
    prueba mira la fuente de `main` para que no vuelva a quedar suelta.
    """

    def setUp(self):
        self.fuente = inspect.getsource(app.main)

    def test_la_opcion_aparece_en_la_pantalla_de_fotos(self):
        self.assertIn("Links nuevos desde Excel", self.fuente)
        self.assertIn("update_photos_links", self.fuente)

    def test_el_modo_llega_a_las_dos_rutas(self):
        self.assertEqual(self.fuente.count("photo_source=photo_source"), 2)

    def test_sin_excel_no_deja_analizar(self):
        """`update_ready` exige archivo cuando el modo es links."""
        self.assertIn('update_operation == "photos" and photo_source != "links"', self.fuente)
        self.assertNotIn('update_operation in ("photos", "siblings"', self.fuente)


if __name__ == "__main__":
    unittest.main(verbosity=2)
