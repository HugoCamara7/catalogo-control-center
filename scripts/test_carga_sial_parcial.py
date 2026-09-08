"""Pruebas de la Carga Sial por codigos Modelo-Color (carga parcial).

Lo que fijan:

1. La hoja sale en el formato DEL SITIO -- el mismo que entrega la carga
   completa -- y no en el de Centry, que trae la cola de Supermall/Rockford
   escrita a mano y seria la hoja equivocada en cuatro de los cinco sitios.
2. Las 40 columnas del medio se arman UNA sola vez (`_filas_sial_desde_matrixify`)
   y la cola tambien (`sial_tail_row`, la misma de `build_sial_row`). Con dos
   copias, un arreglo entra en una hoja y se olvida en la otra.
3. La hoja de Centry no cambio con el refactor.
4. Un codigo que no dejo ninguna fila se avisa: pedir 50 y recibir 38 se ve
   igual de bien que recibir los 50 si nadie dice cuales faltan.

Ejecutar:  python scripts/test_carga_sial_parcial.py
"""
import ast
import sys
import types
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def _identity(*a, **k):
    if a and callable(a[0]):
        return a[0]
    return lambda f: f


class _Stub(types.ModuleType):
    session_state = {}
    secrets = {}
    cache_data = staticmethod(_identity)
    cache_resource = staticmethod(_identity)

    def __getattr__(self, name):
        return lambda *a, **k: None


if "streamlit" not in sys.modules:
    s = _Stub("streamlit")
    c = types.ModuleType("streamlit.components")
    v = types.ModuleType("streamlit.components.v1")
    s.__path__ = []
    c.__path__ = []
    c.v1 = v
    s.components = c
    sys.modules["streamlit"] = s
    sys.modules["streamlit.components"] = c
    sys.modules["streamlit.components.v1"] = v

import pandas as pd  # noqa: E402

import app_matrixify as app  # noqa: E402
import generate_columbia_matrixify as gen  # noqa: E402

FUENTE_APP = (ROOT / "app_matrixify.py").read_text(encoding="utf-8-sig")
FUENTE_GEN = (ROOT / "generate_columbia_matrixify.py").read_text(encoding="utf-8-sig")


def fila_matrixify(mod_col, sku, talla, shopify_id=""):
    """Una fila del Matrixify que arma `build_centry_matrixify_from_master`."""
    return {
        "ID": shopify_id,
        "Handle": mod_col.lower(),
        "Title": "Casaca de prueba",
        "Body HTML": "<p>Descripcion</p>",
        "Vendor": "Columbia",
        "Type": "Casaca",
        "Tags": "Casaca, Hombre",
        "Image Src": "https://ecom-imagenes/COLUMBIA/foto_1.jpg",
        "Variant SKU": sku,
        "Option1 Value": talla,
        "__CENTRY_RAW_SIZE": talla,
        "Metafield: custom.codigo_modelo_color [id]": mod_col,
        "Metafield: custom.genero [single_line_text_field]": "Hombre",
    }


def matrixify_de_prueba():
    return pd.DataFrame([
        fila_matrixify("2044361-6RX", "SKU-M", "M", "310669"),
        fila_matrixify("2044361-6RX", "SKU-L", "L", "310669"),
        fila_matrixify("9999999-999", "SKU-S", "S"),
    ])


def columnas_esperadas(brand_config):
    """Los nombres EXACTOS de la plantilla, con su espacio final incluido.

    Esta funcion daba por buena la perdida del espacio -- decia que la hoja
    pasa por `repair_mojibake_dataframe` "y ahi los nombres pierden el espacio
    del final" -- y con eso congelaba el fallo: 16 cabeceras de la plantilla
    (`Categoria `, `Talla Web `, `Tecnologias `, `Product Name `,
    `Adicional 2 `...) salian sin el espacio que SIAL espera, y la hoja de la
    carga completa, que no pasa por ahi, salia con el nombre correcto. Las dos
    hojas tenian cabeceras distintas para la misma columna.

    Un nombre de columna es una LLAVE: se compara contra la plantilla, no
    contra lo que la app hace hoy con el.
    """
    return list(gen.get_sial_columns(brand_config))


class TestFormatoDelSitio(unittest.TestCase):
    def test_cada_sitio_recibe_sus_columnas(self):
        for site_key, brand_config in gen.SITE_CONFIGS.items():
            with self.subTest(site=site_key):
                sial = app.build_sial_de_sitio_from_matrixify(matrixify_de_prueba(), brand_config)
                self.assertEqual(list(sial.columns), columnas_esperadas(brand_config))

    def test_la_cabecera_no_es_la_de_centry(self):
        sial = app.build_sial_de_sitio_from_matrixify(matrixify_de_prueba(), gen.SITE_CONFIGS["columbia"])
        self.assertEqual(list(sial.columns)[:3], ["Cod. Modelo", "Cod. Color", "Talla"])
        self.assertNotIn("Mod", list(sial.columns))
        self.assertNotIn("Tal", list(sial.columns))

    def test_modelo_y_color_salen_del_mod_col(self):
        sial = app.build_sial_de_sitio_from_matrixify(matrixify_de_prueba(), gen.SITE_CONFIGS["columbia"])
        primera = sial.iloc[0]
        self.assertEqual(primera["Cod. Modelo"], "2044361")
        self.assertEqual(primera["Cod. Color"], "6RX")
        self.assertEqual(primera["Mod-Col"], "2044361-6RX")
        self.assertEqual(primera["Sku - Sial"], "SKU-M")

    def test_el_que_ya_esta_en_shopify_se_actualiza_y_el_otro_se_crea(self):
        sial = app.build_sial_de_sitio_from_matrixify(matrixify_de_prueba(), gen.SITE_CONFIGS["columbia"])
        existente = sial[sial["Mod-Col"] == "2044361-6RX"].iloc[0]
        nuevo = sial[sial["Mod-Col"] == "9999999-999"].iloc[0]
        self.assertEqual(existente["Nuevo o Actualizar (Columbia.pe)"], "Actualizar")
        self.assertEqual(existente["Porduct Id - Columbia.pe"], "310669")
        self.assertEqual(nuevo["Nuevo o Actualizar (Columbia.pe)"], "Crear")
        self.assertEqual(nuevo["Porduct Id - Columbia.pe"], "")

    def test_el_product_id_solo_va_a_la_columna_de_su_tienda(self):
        sial = app.build_sial_de_sitio_from_matrixify(matrixify_de_prueba(), gen.SITE_CONFIGS["columbia"])
        existente = sial[sial["Mod-Col"] == "2044361-6RX"].iloc[0]
        self.assertEqual(existente["Porduct Id - Rockford.pe"], "")
        self.assertEqual(existente["Porduct Id - Supermall.pe"], "")

    def test_las_bodegas_del_sitio_quedan_prendidas(self):
        for site_key, brand_config in gen.SITE_CONFIGS.items():
            with self.subTest(site=site_key):
                sial = app.build_sial_de_sitio_from_matrixify(matrixify_de_prueba(), brand_config)
                for columna in brand_config.get("sial_active_columns", []):
                    self.assertEqual(int(sial.iloc[0][columna]), 1)

    def test_sin_matrixify_devuelve_la_hoja_vacia_con_sus_columnas(self):
        brand_config = gen.SITE_CONFIGS["rockford"]
        vacia = app.build_sial_de_sitio_from_matrixify(pd.DataFrame(), brand_config)
        self.assertTrue(vacia.empty)
        self.assertEqual(list(vacia.columns), gen.get_sial_columns(brand_config))

    def test_la_talla_interna_K_no_llega_a_la_hoja(self):
        # Mismo filtro central que Centry y la carga completa.
        df = pd.DataFrame([
            fila_matrixify("2044361-6RX", "SKU-M", "M"),
            fila_matrixify("2044361-6RX", "SKU-K", "K1"),
        ])
        sial = app.build_sial_de_sitio_from_matrixify(df, gen.SITE_CONFIGS["columbia"])
        self.assertEqual(sorted(sial["Talla"]), ["M"])


class TestUnSoloCuerpo(unittest.TestCase):
    """Las dos hojas Sial salen del mismo sitio o se separan sin que nadie lo vea."""

    def test_las_columnas_compartidas_dan_lo_mismo(self):
        brand_config = gen.SITE_CONFIGS["columbia"]
        df = matrixify_de_prueba()
        centry = app.build_centry_sial_from_matrixify(df, brand_config)
        sitio = app.build_sial_de_sitio_from_matrixify(df, brand_config)
        compartidas = [
            columna for columna in centry.columns
            if columna in set(sitio.columns) and columna not in {"Talla Web"}
        ]
        self.assertGreater(len(compartidas), 30)
        pd.testing.assert_frame_equal(
            centry[compartidas].reset_index(drop=True),
            sitio[compartidas].reset_index(drop=True),
        )

    def test_las_dos_hojas_llaman_al_mismo_nucleo(self):
        arbol = ast.parse(FUENTE_APP)
        for nombre in ("build_centry_sial_from_matrixify", "build_sial_de_sitio_from_matrixify"):
            funcion = next(
                nodo for nodo in ast.walk(arbol)
                if isinstance(nodo, ast.FunctionDef) and nodo.name == nombre
            )
            llamadas = {
                nodo.func.id for nodo in ast.walk(funcion)
                if isinstance(nodo, ast.Call) and isinstance(nodo.func, ast.Name)
            }
            self.assertIn("_filas_sial_desde_matrixify", llamadas, nombre)

    def test_la_carga_completa_no_reescribe_la_cola(self):
        cuerpo = FUENTE_GEN[FUENTE_GEN.index("def build_sial_row("):]
        cuerpo = cuerpo[:cuerpo.index("\ndef ", 10)]
        self.assertIn("sial_tail_row(brand_config, existing_id", cuerpo)
        self.assertNotIn('column.startswith("Nuevo o Actualizar")', cuerpo)

    def test_la_hoja_del_sitio_usa_esa_misma_cola(self):
        cuerpo = FUENTE_APP[FUENTE_APP.index("def build_sial_de_sitio_from_matrixify("):]
        cuerpo = cuerpo[:cuerpo.index("\ndef ", 10)]
        self.assertIn("sial_tail_row(", cuerpo)
        self.assertIn("get_sial_columns(brand_config)", cuerpo)

    def test_la_cola_conoce_los_cinco_sitios(self):
        for site_key, brand_config in gen.SITE_CONFIGS.items():
            with self.subTest(site=site_key):
                cola = gen.sial_tail_row(brand_config, "123", "SKU-1")
                self.assertEqual(sorted(cola), sorted(brand_config["sial_tail_columns"]))


class TestCentryNoCambio(unittest.TestCase):
    """El refactor no puede tocar la hoja que ya se entrega con el Centry."""

    def test_conserva_sus_columnas(self):
        centry = app.build_centry_sial_from_matrixify(matrixify_de_prueba(), gen.SITE_CONFIGS["columbia"])
        # Los nombres declarados, tal cual: ver `columnas_esperadas`.
        self.assertEqual(list(centry.columns), list(app.CENTRY_SIAL_COLUMNS))

    def test_conserva_su_cola_de_supermall(self):
        centry = app.build_centry_sial_from_matrixify(matrixify_de_prueba(), gen.SITE_CONFIGS["columbia"])
        primera = centry.iloc[0]
        self.assertEqual(primera["Nuevo o Actualizar (Rockford.pe)"], "Crear")
        self.assertEqual(primera["Sku - Supermall.pe"], "SKU-M")
        self.assertEqual(primera["Porduct Id - Supermall.pe"], "")
        self.assertEqual(primera["Mod"], "2044361")
        self.assertEqual(primera["Col"], "6RX")
        self.assertEqual(primera["Tal"], "M")

    def test_sin_matrixify_sigue_devolviendo_la_hoja_vacia(self):
        vacia = app.build_centry_sial_from_matrixify(pd.DataFrame(), gen.SITE_CONFIGS["columbia"])
        self.assertTrue(vacia.empty)
        self.assertEqual(list(vacia.columns), app.CENTRY_SIAL_COLUMNS)


class TestCodigosSinFilas(unittest.TestCase):
    def setUp(self):
        self.sial = app.build_sial_de_sitio_from_matrixify(matrixify_de_prueba(), gen.SITE_CONFIGS["columbia"])

    def test_avisa_del_codigo_que_no_salio(self):
        faltantes = app.sial_codigos_sin_filas(["2044361-6RX", "1111111-1"], self.sial)
        self.assertEqual(faltantes, ["1111111-1"])

    def test_un_modelo_suelto_cuenta_si_salio_alguno_de_sus_colores(self):
        self.assertEqual(app.sial_codigos_sin_filas(["2044361"], self.sial), [])

    def test_no_repite_ni_cuenta_vacios(self):
        faltantes = app.sial_codigos_sin_filas(["1111111-1", "1111111-1", "", None], self.sial)
        self.assertEqual(faltantes, ["1111111-1"])

    def test_sin_hoja_todos_faltan(self):
        self.assertEqual(app.sial_codigos_sin_filas(["A-1"], pd.DataFrame()), ["A-1"])


class TestPantallaCargaParcial(unittest.TestCase):
    RAMA = FUENTE_APP[
        FUENTE_APP.index('                if update_operation == "sial":'):
        FUENTE_APP.index('                if update_operation == "centry":')
    ]

    def test_la_opcion_esta_en_el_desplegable(self):
        self.assertIn('CARGA_SIAL_LABEL: "sial",', FUENTE_APP)
        self.assertIn('CARGA_SIAL_LABEL = "Carga Sial"', FUENTE_APP)

    def test_el_excel_de_codigos_sirve_a_las_dos_entregas(self):
        self.assertIn('if update_operation in ("centry", "sial"):', FUENTE_APP)
        # Un Excel de solo codigos no trae columna Marca: el control de marcas
        # del archivo lo dejaria en cero y cortaria la pantalla.
        self.assertIn('update_operation not in ("centry", "sial")', FUENTE_APP)

    def test_el_tramo_comun_no_esta_escrito_dos_veces(self):
        self.assertIn("matrixify_desde_codigos_modelo_color(codes, brand_config, shopify_config)", self.RAMA)
        arbol = ast.parse(FUENTE_APP)
        llamadas = sum(
            1 for nodo in ast.walk(arbol)
            if isinstance(nodo, ast.Call)
            and isinstance(nodo.func, ast.Name)
            and nodo.func.id == "build_centry_matrixify_from_master"
        )
        self.assertEqual(llamadas, 1, "el maestro se cruza en un solo lugar")

    def test_la_rama_no_escribe_en_shopify(self):
        # Genera un Excel y nada mas: aqui no se toca el catalogo.
        for prohibido in (
            "apply_full_product_updates",
            "apply_shopify_preview",
            "metafieldsSet",
            "productCreateMedia",
            "update_product",
        ):
            self.assertNotIn(prohibido, self.RAMA)

    def test_exige_shopify_api(self):
        self.assertIn('if update_operation == "sial" and effective_update_source != "Shopify API":', FUENTE_APP)

    def test_el_excel_lleva_la_hoja_carga_sial(self):
        self.assertIn('"Carga Sial": sial_df,', self.RAMA)
        self.assertIn('file_name=f"carga_sial_{brand_config[\'site_key\']}.xlsx"', self.RAMA)

    def test_limpia_su_estado_al_cambiar_de_operacion(self):
        for clave in (
            "sial_maintainer_df",
            "sial_maintainer_issues_df",
            "sial_maintainer_codes",
            "sial_maintainer_excel_bytes",
        ):
            self.assertIn(f'"{clave}",', FUENTE_APP)

    def test_el_id_de_shopify_viaja_en_el_matrixify(self):
        cuerpo = FUENTE_APP[FUENTE_APP.index("def build_centry_matrixify_from_master("):]
        cuerpo = cuerpo[:cuerpo.index("\ndef ", 10)]
        self.assertIn('"ID": clean_value(fila_destino.get("ID")) if fila_destino is not None else "",', cuerpo)

    def test_el_id_sale_del_catalogo_del_DESTINO(self):
        """El ID decide si el producto se crea o se actualiza, asi que tiene
        que ser el de la tienda a la que se carga. Con Supermall.pe origen y
        destino son tiendas distintas: usar el ID de Vans.pe haria un MERGE
        contra un producto que no es. Cuando son la misma tienda -- Centry,
        Carga Sial -- `fila_destino` es la misma fila que `product_row`."""
        cuerpo = FUENTE_APP[FUENTE_APP.index("def build_centry_matrixify_from_master("):]
        cuerpo = cuerpo[:cuerpo.index("\ndef ", 10)]
        self.assertIn("fila_destino = destino_lookup.get(key)", cuerpo)
        self.assertNotIn('"ID": clean_value(product_row.get("ID"))', cuerpo)
        # La preparacion de los dos catalogos se saco a `preparar_contexto_de_codigos`
        # para que no se rehiciera una vez POR BLOQUE (medido: 22,4 s por bloque,
        # 20,5 minutos con 11.000 codigos). El "sin destino, el destino ES el
        # origen" se comprueba ahi, que es donde vive ahora.
        prep = FUENTE_APP[FUENTE_APP.index("def preparar_contexto_de_codigos("):]
        prep = prep[:prep.index("\ndef ", 10)]
        self.assertIn("destino_df = shopify_df", prep)

    def test_sin_destino_el_destino_es_el_origen(self):
        """Comprobado sobre el RESULTADO, no solo leyendo el codigo."""
        contexto = app.preparar_contexto_de_codigos(
            pd.DataFrame([{"Handle": "h", "Mod-Col": "AB-1", "ID": "gid://9"}]),
            pd.DataFrame(), {"label": "X"},
        )
        self.assertIs(contexto["destino_df"], contexto["shopify_df"])
        self.assertEqual(set(contexto["destino_lookup"]), set(contexto["product_lookup"]))


if __name__ == "__main__":
    unittest.main(verbosity=2)
