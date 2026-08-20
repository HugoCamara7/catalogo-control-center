# -*- coding: utf-8 -*-
"""Pruebas del enriquecimiento de atributos (engines/enrich.py).

Origen: en el Centry seguían saliendo vacíos Materiales, Composición,
Cuidados, Género y Tipo de prenda.

Causas encontradas:

1. El Body HTML del producto trae CUATRO secciones rotuladas
   (`nweb__Descripcion`, `nweb__Caracteristicas`, `nweb__Materiales`,
   `nweb__Cuidados`) y la app **solo leía la de Características**. Los
   materiales y los cuidados estaban escritos en el producto desde siempre y
   nadie los recogía.

2. `build_centry_matrixify_from_master` completaba materialidad y tecnología
   **solo desde Shopify**. Un producto que no está en Shopify salía sin
   ninguno de los cuatro campos aunque BigQuery/ARTI los trajera en
   `Material`, `Cuidado`, `Caracteristicas` y `DescripcionWeb`.

3. Cada camino de carga tenía su propia lista de columnas, así que el mismo
   producto salía completo en una carga y vacío en otra.

Ejecutar:  python scripts/test_enriquecimiento.py
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
from engines import centry_map  # noqa: E402
from engines import enrich  # noqa: E402

CONFIG_ROCKFORD = g.get_brand_config("rockford")
CODIGO = "RK102011405-085"

BODY = (
    '<section class="nweb" data-titulo="Informacion del producto" id="nombre-web-section">'
    '<div class="nweb__Descripcion" data-titulo="Descripción">'
    '<h3 class="nweb__Descripcion-titulo">Descripción</h3>'
    '<p>Alpargata de verano en cuero.</p></div>'
    '<div class="nweb__Caracteristicas" data-titulo="Características">'
    '<h3 class="nweb__Caracteristicas-titulo">Características</h3>'
    '<ul><li>Capellada: 100% Cuero</li><li>Forro: 100% Yute</li>'
    '<li>Suela: 100% Goma</li></ul></div>'
    '<div class="nweb__Materiales" data-titulo="Materiales">'
    '<h3 class="nweb__Materiales-titulo">Materiales</h3>'
    '<ul><li>Composición: 100% Cuero</li></ul></div>'
    '<div class="nweb__Cuidados" data-titulo="Cuidados">'
    '<h3 class="nweb__Cuidados-titulo">Cuidados</h3>'
    '<ul><li>Limpiar con paño húmedo</li><li>Secar a la sombra</li></ul></div>'
    '</section>'
)


def fila(**valores):
    base = {columna: "" for columna in app.MATRIXIFY_COLUMNS}
    base.update(valores)
    return base


def centry_de(**extra):
    valores = {
        "Handle": "alpargata-cuero-hombre",
        "Title": "Alpargata Cuero Hombre Rockford",
        "Body HTML": BODY,
        "Vendor": "Rockford",
        "Type": "Alpargatas",
        "Tags": "Rockford",
        "Image Src": "https://ejemplo/1.jpg",
        "Variant SKU": "5470311",
        "Variant Price": "199",
        "Option1 Value": "40",
        "Metafield: custom.codigo_modelo_color [id]": CODIGO,
        "Metafield: custom.genero [single_line_text_field]": "HOMBRE",
    }
    valores.update(extra)
    salida, avisos = app.build_centry_from_matrixify(
        pd.DataFrame([fila(**valores)]), {"label": "Rockford"}
    )
    return salida.iloc[0], avisos


class TestSeccionesDelBody(unittest.TestCase):
    """Las cuatro secciones del Body, no solo Características."""

    def test_lee_cada_seccion(self):
        esperado = {
            "Descripcion": "Alpargata de verano en cuero.",
            "Caracteristicas": "Capellada: 100% Cuero|Forro: 100% Yute|Suela: 100% Goma",
            "Materiales": "Composición: 100% Cuero",
            "Cuidados": "Limpiar con paño húmedo|Secar a la sombra",
        }
        for seccion, texto in esperado.items():
            with self.subTest(seccion=seccion):
                self.assertEqual(centry_map.seccion_del_body(BODY, seccion), texto)

    def test_una_seccion_que_no_esta_devuelve_vacio(self):
        cuerpo = '<div class="nweb__Descripcion"><p>Solo descripción</p></div>'
        self.assertEqual(centry_map.seccion_del_body(cuerpo, "Cuidados"), "")

    def test_la_funcion_de_siempre_sigue_igual(self):
        """`caracteristicas_del_body` no puede cambiar: la usa el motor."""
        self.assertEqual(
            centry_map.caracteristicas_del_body(BODY),
            centry_map.seccion_del_body(BODY, "Caracteristicas"),
        )


class TestCadenaCentral(unittest.TestCase):
    """El orden de prioridad es la regla del negocio, y está escrito."""

    def test_shopify_manda_sobre_el_maestro(self):
        shopify = {"Metafield: custom.genero [single_line_text_field]": "HOMBRE"}
        maestro = {"GENERO_MA": "MUJER"}
        valor, _ = enrich.resolver("genero", [shopify, maestro])
        self.assertEqual(valor, "HOMBRE")

    def test_el_maestro_entra_cuando_shopify_esta_vacio(self):
        shopify = {"Metafield: custom.genero [single_line_text_field]": ""}
        maestro = {"GENERO_MA": "MUJER"}
        valor, _ = enrich.resolver("genero", [shopify, maestro])
        self.assertEqual(valor, "MUJER")

    def test_el_tipo_sigue_el_mismo_orden(self):
        self.assertEqual(enrich.resolver("tipo", [{"Type": "Camisas"}])[0], "Camisas")
        self.assertEqual(enrich.resolver("tipo", [{"TipoProducto": "Camisas"}])[0], "Camisas")

    def test_las_etiquetas_son_el_ultimo_recurso(self):
        valor, origen = enrich.resolver("material", [{}], ["Capellada: 100% Cuero"])
        self.assertEqual(valor, "100% Cuero")
        self.assertIn("etiqueta", origen)

    def test_una_columna_gana_a_una_etiqueta(self):
        valor, origen = enrich.resolver(
            "material", [{"Materiales": "Cuero Graso"}], ["Capellada: 100% Cuero"]
        )
        self.assertEqual(valor, "Cuero Graso")
        self.assertIn("columna", origen)

    def test_no_aplica_no_es_un_valor(self):
        """Un 'No Aplica' no puede dar el atributo por resuelto."""
        valor, _ = enrich.resolver(
            "material", [{"Materiales": "No Aplica"}, {"Material": "Cuero"}]
        )
        self.assertEqual(valor, "Cuero")

    def test_no_inventa(self):
        self.assertEqual(enrich.resolver("cuidados", [{}], [])[0], "")
        self.assertEqual(enrich.faltantes(enrich.resolver_todos([{}])), sorted(enrich.ATRIBUTOS))


class TestResolutorPorArchivo(unittest.TestCase):
    """El atajo de rendimiento tiene que estar realmente activo.

    `Resolutor` fija las columnas del archivo una vez para no preguntar por
    columnas que no existen en cada fila. La primera versión hacía
    `tuple(columnas or ())`, y con un Index de pandas ese `or` lanza "truth
    value of an Index is ambiguous": el resolutor moría dentro de un `except`
    y todo volvía a la búsqueda lenta **sin que nada lo dijera**.
    """

    def test_se_construye_con_columnas_de_pandas(self):
        df = pd.DataFrame(columns=["Body HTML", "Materiales"])
        self.assertIsNotNone(app.centry_resolutor(df))
        self.assertIsNotNone(enrich.Resolutor(df.columns))

    def test_solo_pregunta_por_columnas_que_existen(self):
        resolutor = enrich.Resolutor(
            ["Metafield: custom.materialidad [single_line_text_field]", "Tags"]
        )
        self.assertEqual(
            resolutor.claves("material"),
            ("Metafield: custom.materialidad [single_line_text_field]",),
        )
        self.assertEqual(resolutor.claves("cuidados"), ())

    def test_da_el_mismo_resultado_que_la_busqueda_completa(self):
        """El atajo no puede cambiar la respuesta, solo el tiempo."""
        fuente = {"Materiales": "Cuero", "Tags": "Rockford"}
        resolutor = enrich.Resolutor(list(fuente))
        for atributo in ("material", "composicion", "cuidados", "genero", "tipo"):
            with self.subTest(atributo=atributo):
                self.assertEqual(
                    resolutor.resolver(atributo, [fuente])[0],
                    enrich.resolver(atributo, [fuente])[0],
                )


class TestCentrySeCompleta(unittest.TestCase):
    """Lo que estaba escrito en el producto ahora llega al archivo."""

    def test_material_y_composicion(self):
        producto, _ = centry_de()
        self.assertTrue(str(producto["Listado de características"]).find("Material :") >= 0)
        self.assertIn("Cuero", str(producto["Listado de características"]))

    def test_cuidados_entran_al_listado(self):
        producto, _ = centry_de()
        self.assertIn("Cuidados :", str(producto["Listado de características"]))
        self.assertIn("Limpiar con paño húmedo", str(producto["Listado de características"]))

    def test_genero_y_tipo_no_quedan_vacios(self):
        producto, _ = centry_de()
        self.assertEqual(str(producto["Género"]), "Masculino")
        self.assertEqual(str(producto["Clase"]), "Calzado")

    def test_los_atributos_de_marketplace_se_llenan(self):
        producto, _ = centry_de()
        self.assertEqual(
            str(producto["Material de la suela - Calzado (Falabella GSC Perú)"]), "100% Goma"
        )

    def test_sin_body_no_se_inventa_nada(self):
        producto, _ = centry_de(**{"Body HTML": ""})
        self.assertNotIn("Cuidados :", str(producto["Listado de características"]))


class TestMaestroCompletaLoQueShopifyNoTiene(unittest.TestCase):
    """Un producto que no está en Shopify se completa con BigQuery/ARTI."""

    CODIGO_HUERFANO = "RK110021743-5ZV"

    def _construir(self, **extra):
        base = {
            "Mod-Col": self.CODIGO_HUERFANO, "COD MOD COL": self.CODIGO_HUERFANO,
            "CODINT_MA": "5486079", "TALNUM_MA": "40", "MARCA_MA": "ROCKFORD",
            "Precio": "199", "CodBarras": "7800160712101",
        }
        base.update(extra)
        return app.build_centry_matrixify_from_master(
            [self.CODIGO_HUERFANO],
            pd.DataFrame(columns=app.MATRIXIFY_COLUMNS),
            pd.DataFrame([base]),
            CONFIG_ROCKFORD,
        )

    def test_materialidad_desde_el_maestro(self):
        salida, _ = self._construir(Material="Cuero")
        self.assertEqual(
            str(salida["Metafield: custom.materialidad [single_line_text_field]"].iloc[0]),
            "Cuero",
        )

    def test_cuidados_y_composicion_viajan_al_constructor(self):
        salida, _ = self._construir(Cuidado="Limpiar con paño húmedo", Composicion="100% Cuero")
        self.assertEqual(str(salida["Cuidados"].iloc[0]), "Limpiar con paño húmedo")
        self.assertEqual(str(salida["Composición"].iloc[0]), "100% Cuero")

    def test_la_descripcion_tambien_sale_del_maestro(self):
        salida, _ = self._construir(DescripcionWeb="Alpargata de verano")
        self.assertEqual(str(salida["Body HTML"].iloc[0]), "Alpargata de verano")

    def test_llegan_hasta_la_hoja_centry(self):
        matrixify, _ = self._construir(
            Material="Cuero", Cuidado="Limpiar con paño húmedo", SubCategoria="Alpargatas"
        )
        centry, _ = app.build_centry_from_matrixify(matrixify, CONFIG_ROCKFORD)
        listado = str(centry["Listado de características"].iloc[0])
        self.assertIn("Material : Cuero", listado)
        self.assertIn("Cuidados : Limpiar con paño húmedo", listado)


if __name__ == "__main__":
    unittest.main(verbosity=2)
