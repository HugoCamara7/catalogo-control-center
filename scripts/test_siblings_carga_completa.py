"""Pruebas de que los siblings se recalculan en CADA carga completa.

Origen: el input de una carga trae solo los colores de ese dia. Los siblings se
calculaban unicamente con eso, asi que un modelo con tres colores publicados que
recibia un color nuevo terminaba con la relacion reducida al color nuevo: se
borraban relaciones validas.

Y al reves: los colores que ya estaban publicados nunca se enteraban del nuevo,
porque no venian en el input y no se generaba fila para ellos.

Ejecutar:  python scripts/test_siblings_carga_completa.py
"""
import json
import sys
import unittest
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import app_matrixify as app  # noqa: E402
import generate_columbia_matrixify as g  # noqa: E402

CONFIG = {"shop_domain": "prueba.myshopify.com", "token": "x"}


class _Sesion(dict):
    pass


def columnas_matrixify():
    """Las columnas reales del export, desde la plantilla del repo."""
    plantilla = ROOT / app.DEFAULT_MATRIXIFY_PATH
    columnas = list(pd.read_excel(plantilla, sheet_name=0, nrows=0).columns)
    for obligatoria in ("Handle", "ID", g.PRODUCT_KEY_COLUMN, g.SIBLINGS_COLUMN, g.CUSTOM_SIBLINGS_COLUMN):
        if obligatoria not in columnas:
            columnas.append(obligatoria)
    return columnas


def catalogo(filas):
    """Catalogo Shopify de mentira, con las columnas reales del export."""
    columnas = columnas_matrixify()
    # Con `filas` vacio hay que fijar las columnas a mano: un DataFrame de una
    # lista vacia no tiene ninguna, y el generador necesita el juego completo.
    base = pd.DataFrame([{columna: "" for columna in columnas} for _ in filas], columns=columnas)
    for indice, fila in enumerate(filas):
        for columna, valor in fila.items():
            base.loc[indice, columna] = valor
    return base


class TestLeerSiblingsDelCatalogo(unittest.TestCase):
    def test_acepta_lista_json(self):
        self.assertEqual(g.handles_de_siblings(json.dumps(["uno", "dos"])), ["uno", "dos"])

    def test_acepta_texto_con_comas(self):
        self.assertEqual(g.handles_de_siblings("uno, dos"), ["uno", "dos"])

    def test_descarta_los_ids_de_producto(self):
        # custom.siblings es list.product_reference: el catalogo trae gid://.
        # Aqui se trabaja con handles; el id se resuelve al sincronizar.
        self.assertEqual(
            g.handles_de_siblings("gid://shopify/Product/1, gid://shopify/Product/2"), []
        )

    def test_vacio(self):
        self.assertEqual(g.handles_de_siblings(""), [])
        self.assertEqual(g.handles_de_siblings(None), [])

    def test_agrupa_por_modelo(self):
        publicados = g.siblings_ya_publicados(catalogo([
            {"Handle": "alpargata-089", g.PRODUCT_KEY_COLUMN: "RK110011501-089"},
            {"Handle": "alpargata-vl8", g.PRODUCT_KEY_COLUMN: "RK110011501-VL8"},
            {"Handle": "mocasin-645", g.PRODUCT_KEY_COLUMN: "RK202011432-645"},
        ]))
        self.assertEqual(
            sorted(publicados["RK110011501"]), ["alpargata-089", "alpargata-vl8"]
        )
        self.assertEqual(publicados["RK202011432"], ["mocasin-645"])

    def test_rescata_al_producto_sin_codigo_modelo_color(self):
        # Si un hermano tiene el metafield vacio, igual entra al grupo porque
        # otro producto del modelo ya lo declaraba como hermano.
        publicados = g.siblings_ya_publicados(catalogo([
            {
                "Handle": "alpargata-089",
                g.PRODUCT_KEY_COLUMN: "RK110011501-089",
                g.SIBLINGS_COLUMN: json.dumps(["alpargata-089", "alpargata-sin-codigo"]),
            },
        ]))
        self.assertIn("alpargata-sin-codigo", publicados["RK110011501"])


class TestUnionEnCargaCompleta(unittest.TestCase):
    def test_el_color_nuevo_hereda_los_ya_publicados(self):
        entrada = pd.DataFrame([{
            "Mod-Col": "RK110011501-WSA", "Marca": "Rockford", "Genero": "HOMBRE",
            "Clase": "Calzado", "Tipo de prenda": "ALPARGATA", "Color web/filtro": "BLANCO",
            "Nombre de Producto": "Alpargata Hombre Rockford", "Descripcion": "Texto.",
            "Caracteristicas": "A|B", "Materiales": "ALGODON", "Tecnologia": "NO APLICA",
        }])
        arti = pd.DataFrame([
            {"Mod-Col": "RK110011501-WSA", "COD MOD COL": "RK110011501-WSA",
             "CODINT_MA": f"SKU{i}", "TALNUM_MA": str(talla), "MARCA_MA": "ROCKFORD",
             "Precio": "", "CodBarras": ""}
            for i, talla in enumerate([400, 410, 420], 1)
        ])
        existente = catalogo([
            {"Handle": "alpargata-089", g.PRODUCT_KEY_COLUMN: "RK110011501-089"},
            {"Handle": "alpargata-vl8", g.PRODUCT_KEY_COLUMN: "RK110011501-VL8"},
        ])

        salida = g.build_columbia_matrixify(
            entrada, arti, existente, g.get_brand_config("rockford"))[0]
        cabecera = salida[salida["Top Row"].map(g.clean).str.upper() == "TRUE"].iloc[0]
        relacionados = g.handles_de_siblings(cabecera[g.SIBLINGS_COLUMN])

        self.assertIn("alpargata-089", relacionados)
        self.assertIn("alpargata-vl8", relacionados)
        self.assertEqual(len(relacionados), 3, "el nuevo mas los dos publicados")


class TestPropagacionAlGrupo(unittest.TestCase):
    """Cargar un color nuevo debe actualizar tambien a los ya publicados."""

    def setUp(self):
        self._metafields_set = app.metafields_set
        self._fetch = app.fetch_product_id_by_handle
        self._session = app.st.session_state
        app.st.session_state = _Sesion()
        self.escritos = []
        app.metafields_set = lambda cfg, ms: self.escritos.extend(ms) or {}
        app.fetch_product_id_by_handle = lambda cfg, h: {
            "nuevo-wsa": "gid://shopify/Product/3",
            "viejo-089": "gid://shopify/Product/1",
            "viejo-vl8": "gid://shopify/Product/2",
        }.get(str(h).lower(), "")

    def tearDown(self):
        app.metafields_set = self._metafields_set
        app.fetch_product_id_by_handle = self._fetch
        app.st.session_state = self._session

    def _correr(self, pendientes):
        filas = {"nuevo-wsa": {"Resultado": "OK", "Mensaje": ""}}
        app._escribir_referencias_a_producto(
            CONFIG, {"nuevo-wsa": pendientes},
            {"nuevo-wsa": "gid://shopify/Product/3"}, filas)
        return filas

    def test_escribe_en_todos_los_hermanos(self):
        grupo = ["nuevo-wsa", "viejo-089", "viejo-vl8"]
        self._correr([("custom", "siblings", "list.product_reference", grupo)])

        propietarios = {m["ownerId"] for m in self.escritos}
        self.assertEqual(len(propietarios), 3, "los tres productos se actualizan")
        for metafield in self.escritos:
            self.assertEqual(
                json.loads(metafield["value"]),
                ["gid://shopify/Product/3", "gid://shopify/Product/1", "gid://shopify/Product/2"],
            )

    def test_el_tema_recibe_handles_y_el_custom_recibe_ids(self):
        grupo = ["nuevo-wsa", "viejo-089", "viejo-vl8"]
        self._correr([
            ("custom", "siblings", "list.product_reference", grupo),
            ("theme", "siblings", "list.single_line_text_field", grupo),
        ])
        por_clave = {}
        for metafield in self.escritos:
            por_clave.setdefault(f"{metafield['namespace']}.{metafield['key']}", []).append(metafield)

        self.assertEqual(len(por_clave["custom.siblings"]), 3)
        self.assertEqual(len(por_clave["theme.siblings"]), 3)
        self.assertTrue(
            all("gid://" in m["value"] for m in por_clave["custom.siblings"]))
        self.assertEqual(json.loads(por_clave["theme.siblings"][0]["value"]), grupo)

    def test_un_metafield_que_no_es_siblings_solo_va_al_propietario(self):
        self._correr([("custom", "principal", "product_reference", ["viejo-089"])])
        self.assertEqual(len(self.escritos), 1)
        self.assertEqual(self.escritos[0]["ownerId"], "gid://shopify/Product/3")

    def test_el_hermano_que_no_existe_no_rompe_al_resto(self):
        grupo = ["nuevo-wsa", "viejo-089", "fantasma"]
        filas = self._correr([("custom", "siblings", "list.product_reference", grupo)])
        self.assertEqual(len({m["ownerId"] for m in self.escritos}), 2)
        self.assertIn("fantasma", filas["nuevo-wsa"]["Mensaje"])


class TestDescripcionParaCentry(unittest.TestCase):
    """Centry publicaba 'Caracteristicas Cinturon ajustable para...'.

    Los <h3> del Body HTML son rotulos de seccion, no contenido: al aplanar el
    HTML se quedaban pegados delante del texto.
    """

    def setUp(self):
        self.cuerpo = g.build_body_html({
            "Descripcion": "El mocasin Auckland es la eleccion perfecta.",
            "Caracteristicas": "Capellada: 100% Cuero|Forro: 100% Cuero",
            "Materiales": "CUERO",
            "Cuidados": "",
        })

    def test_no_empieza_con_el_rotulo(self):
        texto = g.texto_plano_de_body(self.cuerpo)
        self.assertTrue(texto.startswith("El mocasin Auckland"), texto[:60])

    def test_no_menciona_ningun_rotulo(self):
        texto = g.texto_plano_de_body(self.cuerpo)
        for rotulo in ("Descripción", "Descripcion", "Características", "Caracteristicas", "Materiales"):
            self.assertNotIn(rotulo, texto)

    def test_los_bullets_no_se_pegan(self):
        # Antes salia "Capellada: 100% Cuero Forro: 100% Cuero".
        texto = g.texto_plano_de_body(self.cuerpo)
        self.assertIn("Capellada: 100% Cuero. Forro: 100% Cuero", texto)

    def test_conserva_todo_el_contenido(self):
        texto = g.texto_plano_de_body(self.cuerpo)
        self.assertIn("El mocasin Auckland es la eleccion perfecta", texto)
        self.assertIn("Cuero", texto)

    def test_no_deja_puntos_repetidos(self):
        texto = g.texto_plano_de_body(self.cuerpo)
        self.assertNotIn("..", texto)
        self.assertNotIn(" .", texto)

    def test_vacio(self):
        self.assertEqual(g.texto_plano_de_body(""), "")
        self.assertEqual(g.texto_plano_de_body(None), "")

    def test_texto_sin_html_pasa_igual(self):
        self.assertEqual(g.texto_plano_de_body("Solo texto plano"), "Solo texto plano")


class TestSkuYEanEnCentry(unittest.TestCase):
    """El EAN se metia en la columna del SKU de la variante.

    `variant_centry_sku = barcode or variant_sku` daba igual mientras BigQuery
    no devolvia codigos de barra. Al configurar la tabla de EAN, el codigo de
    barras empezo a llegar y tapaba el codigo interno del producto.
    """

    def _centry(self, con_ean):
        entrada = pd.DataFrame([{
            "Mod-Col": "RK202011432-645", "Marca": "Rockford", "Genero": "MUJER",
            "Clase": "Calzado", "Tipo de prenda": "MOCASIN", "Color web/filtro": "MARRON",
            "Nombre de Producto": "Mocasin Cuero Mujer", "Descripcion": "Texto.",
            "Caracteristicas": "A|B", "Materiales": "CUERO", "Tecnologia": "NO APLICA",
        }])
        arti = pd.DataFrame([
            {"Mod-Col": "RK202011432-645", "COD MOD COL": "RK202011432-645",
             "CODINT_MA": "5455311", "TALNUM_MA": "350", "MARCA_MA": "ROCKFORD",
             "Precio": "", "CodBarras": "7790000000002" if con_ean else ""},
        ])
        config = g.get_brand_config("rockford")
        salida = g.build_columbia_matrixify(entrada, arti, catalogo([]), config)[0]
        centry, _ = app.build_centry_from_matrixify(salida, config, arti_df=arti)
        return salida, centry

    def _columna(self, df, fragmento):
        return next(c for c in df.columns if fragmento in str(c))

    def test_el_ean_no_pisa_el_sku_de_la_variante(self):
        _, centry = self._centry(con_ean=True)
        sku = g.clean(centry.iloc[0][self._columna(centry, "SKU de la variante")])
        ean = g.clean(centry.iloc[0][self._columna(centry, "barra variante")])
        self.assertEqual(sku, "5455311")
        self.assertEqual(ean, "7790000000002")
        self.assertNotEqual(sku, ean)

    def test_sin_ean_el_sku_sigue_estando(self):
        _, centry = self._centry(con_ean=False)
        sku = g.clean(centry.iloc[0][self._columna(centry, "SKU de la variante")])
        self.assertEqual(sku, "5455311")

    def test_el_matrixify_tambien_los_separa(self):
        salida, _ = self._centry(con_ean=True)
        fila = salida.iloc[0]
        self.assertEqual(g.clean(fila["Variant SKU"]), "5455311")
        self.assertEqual(g.clean(fila["Variant Barcode"]), "7790000000002")


class TestTextoPlanoSinCss(unittest.TestCase):
    def test_el_css_no_se_cuela_como_texto(self):
        cuerpo = '<div><style>.p{margin:0;padding:2px}</style><p>Zapatilla de cuero.</p></div>'
        self.assertEqual(g.strip_html(cuerpo), "Zapatilla de cuero.")

    def test_tampoco_el_script(self):
        cuerpo = '<div><script>var x = 1;</script><p>Texto.</p></div>'
        self.assertEqual(g.strip_html(cuerpo), "Texto.")

    def test_el_html_normal_sigue_igual(self):
        self.assertEqual(g.strip_html("<p>Hola <b>mundo</b></p>"), "Hola mundo")


if __name__ == "__main__":
    unittest.main(verbosity=2)
