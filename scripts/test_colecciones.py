#!/usr/bin/env python3
"""Diccionario de colecciones por marca, y el diccionario UNICO de tipos.

Lo que fijan estas pruebas:

- El motor de colecciones evalua las reglas de Shopify como Shopify, y cuando
  NO puede evaluarlas lo dice en vez de contestar que no.
- El generador no pisa el vocabulario curado a mano ni borra los sitios que no
  leyo esta vez.
- Los dos diccionarios de tipos de prenda son UNO: coinciden en los 523 nombres
  y ninguno apunta a dos prendas.
"""

import ast
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAIZ))

from engines import colecciones as motor  # noqa: E402
from engines import garment_types as tipos  # noqa: E402
import catalog_rules as reglas  # noqa: E402
import shopify_api  # noqa: E402

DICCIONARIO = RAIZ / "data" / "colecciones_por_marca.json"


def coleccion(handle, reglas_=(), disyuntiva=False, automatica=None):
    return {
        "handle": handle,
        "titulo": handle.title(),
        "automatica": bool(reglas_) if automatica is None else automatica,
        "disyuntiva": disyuntiva,
        "reglas": [dict(zip(("campo", "relacion", "valor"), r)) for r in reglas_],
    }


class TestCodigoModeloColor(unittest.TestCase):
    """1.069 de los 1.175 tags de Columbia.pe son el codigo del propio
    producto. Contarlos como vocabulario haria creer que la tienda tiene mil
    criterios de clasificacion."""

    def test_por_forma(self):
        for tag in ["2086961-TYA", "1-16504-00-7-GIE", "CSC-029-7XK", "PFG-047-356-8KX"]:
            self.assertTrue(motor.es_codigo_modelo_color(tag), tag)

    def test_lo_que_no_es_codigo(self):
        for tag in ["Omni-Shield™", "NEW ARRIVALS", "PFG", "Hiking", "Ski/Nieve", ""]:
            self.assertFalse(motor.es_codigo_modelo_color(tag), tag)

    def test_por_identidad_cuando_la_forma_no_alcanza(self):
        """`AM8004-yFO` esta en el catalogo real con una minuscula.

        La forma sola se lo pierde; con la lista de codigos del catalogo se
        reconoce sin adivinar.
        """
        self.assertFalse(motor.es_codigo_modelo_color("AM8004-yFO"))
        self.assertTrue(motor.es_codigo_modelo_color("AM8004-yFO", ["AM8004-YFO"]))


class TestFamiliasDeTag(unittest.TestCase):
    def test_las_estructurales_no_necesitan_diccionario(self):
        self.assertEqual(motor.familia_de_tag("Hombre"), "genero")
        self.assertEqual(motor.familia_de_tag("Vestuario"), "clase")
        self.assertEqual(motor.familia_de_tag("Casaca"), "tipo")
        self.assertEqual(motor.familia_de_tag("2086961-TYA"), "codigo")

    def test_lo_que_nadie_declaro_sale_sin_clasificar(self):
        self.assertEqual(motor.familia_de_tag("Everyday Outdoor"), "sin_clasificar")

    def test_lo_declarado_por_la_tienda_manda(self):
        """`Impermeable` esta en 149 productos de Columbia como ATRIBUTO, pero
        el diccionario maestro lo reconoce como el TIPO "Impermeables". El dato
        curado gana; la inferencia es el respaldo."""
        self.assertEqual(motor.familia_de_tag("Impermeable"), "tipo")
        self.assertEqual(
            motor.familia_de_tag("Impermeable", {"atributo": ["Impermeable"]}), "atributo")

    def test_clasificar_no_repite_ni_pierde_el_orden(self):
        salida = motor.clasificar_tags(
            ["Hiking", "Hombre", "hiking", "Casaca"], {"actividad": ["Hiking"]})
        self.assertEqual(salida["actividad"], ["Hiking"])
        self.assertEqual(salida["genero"], ["Hombre"])
        self.assertEqual(salida["tipo"], ["Casaca"])


class TestReglasDeColeccion(unittest.TestCase):
    def test_un_tag_igual(self):
        col = coleccion("hiking", [("TAG", "EQUALS", "Hiking")])
        self.assertIs(motor.producto_en_coleccion({"tags": ["Hiking"]}, col), True)
        self.assertIs(motor.producto_en_coleccion({"tags": ["Pesca"]}, col), False)

    def test_ignora_mayusculas_y_tildes(self):
        col = coleccion("nino", [("TAG", "EQUALS", "Niños")])
        self.assertIs(motor.producto_en_coleccion({"tags": ["ninos"]}, col), True)

    def test_todas_las_reglas_and(self):
        col = coleccion("hombre-hiking", [("TAG", "EQUALS", "Hiking"), ("TAG", "EQUALS", "Hombre")])
        self.assertIs(motor.producto_en_coleccion({"tags": ["Hiking", "Hombre"]}, col), True)
        self.assertIs(motor.producto_en_coleccion({"tags": ["Hiking"]}, col), False)

    def test_basta_una_or(self):
        col = coleccion("outdoor", [("TAG", "EQUALS", "Hiking"), ("TAG", "EQUALS", "Camping")],
                        disyuntiva=True)
        self.assertIs(motor.producto_en_coleccion({"tags": ["Camping"]}, col), True)
        self.assertIs(motor.producto_en_coleccion({"tags": ["Pesca"]}, col), False)

    def test_negativa(self):
        col = coleccion("sin-quiebre", [("TAG", "NOT_EQUALS", "Quiebre")])
        self.assertIs(motor.producto_en_coleccion({"tags": ["Hiking"]}, col), True)
        self.assertIs(motor.producto_en_coleccion({"tags": ["Quiebre"]}, col), False)

    def test_por_tipo_y_por_vendor(self):
        col = coleccion("casacas", [("TYPE", "EQUALS", "Casacas")])
        self.assertIs(motor.producto_en_coleccion({"tipo": "Casacas"}, col), True)
        col = coleccion("vans", [("VENDOR", "CONTAINS", "vans")])
        self.assertIs(motor.producto_en_coleccion({"vendor": "Vans"}, col), True)


class TestLoQueNoSePuedeEvaluarNoEsUnNo(unittest.TestCase):
    """Devolver False cuando la respuesta es "no se sabe" deja al producto
    fuera de la coleccion sin que nadie se entere. Es el error silencioso."""

    def test_una_regla_por_precio_no_se_puede_responder_con_tags(self):
        col = coleccion("ofertas", [("VARIANT_PRICE", "LESS_THAN", "100")])
        self.assertIsNone(motor.producto_en_coleccion({"tags": ["Hiking"]}, col))
        self.assertFalse(motor.coleccion_evaluable(col))

    def test_una_coleccion_manual_no_se_deduce_de_los_tags(self):
        col = coleccion("destacados", (), automatica=False)
        self.assertIsNone(motor.producto_en_coleccion({"tags": ["Hiking"]}, col))

    def test_un_no_seguro_gana_sobre_un_no_se_sabe(self):
        """Con AND, una regla que falla deja al producto fuera aunque otra no
        se pueda evaluar: ahi la respuesta SI se sabe."""
        col = coleccion("x", [("TAG", "EQUALS", "Hiking"), ("VARIANT_PRICE", "LESS_THAN", "100")])
        self.assertIs(motor.producto_en_coleccion({"tags": ["Pesca"]}, col), False)
        self.assertIsNone(motor.producto_en_coleccion({"tags": ["Hiking"]}, col))

    def test_las_dos_listas_van_separadas(self):
        cols = [coleccion("a", [("TAG", "EQUALS", "Hiking")]),
                coleccion("b", [("VARIANT_PRICE", "LESS_THAN", "100")])]
        dentro, dudosas = motor.colecciones_de_producto({"tags": ["Hiking"]}, cols)
        self.assertEqual((dentro, dudosas), (["a"], ["b"]))


class TestTagsQueAlimentan(unittest.TestCase):
    def test_solo_las_positivas_por_tag(self):
        col = coleccion("x", [("TAG", "EQUALS", "Hiking"), ("TAG", "NOT_EQUALS", "Quiebre"),
                              ("TYPE", "EQUALS", "Casacas")])
        self.assertEqual(motor.tags_de_coleccion(col), ["Hiking"])

    def test_sin_repetidos(self):
        col = coleccion("x", [("TAG", "EQUALS", "Hiking"), ("TAG", "EQUALS", "hiking")])
        self.assertEqual(motor.tags_de_coleccion(col), ["Hiking"])


class TestEvaluarCatalogo(unittest.TestCase):
    def test_huerfanos_y_indeterminados_no_se_mezclan(self):
        cols = [coleccion("hiking", [("TAG", "EQUALS", "Hiking")]),
                coleccion("manual", (), automatica=False)]
        productos = [{"clave": "A", "tags": ["Hiking"]}, {"clave": "B", "tags": ["Pesca"]}]
        salida = motor.evaluar_catalogo(productos, cols)
        self.assertEqual(salida["por_coleccion"]["hiking"], 1)
        # B no cae en hiking, pero la coleccion manual no se puede descartar:
        # no es huerfano, es indeterminado.
        self.assertEqual([p["clave"] for p in salida["indeterminados"]], ["B"])
        self.assertEqual(salida["huerfanos"], [])

    def test_un_producto_sin_ninguna_coleccion_es_huerfano(self):
        cols = [coleccion("hiking", [("TAG", "EQUALS", "Hiking")])]
        salida = motor.evaluar_catalogo([{"clave": "B", "tags": ["Pesca"]}], cols)
        self.assertEqual([p["clave"] for p in salida["huerfanos"]], ["B"])

    def test_las_vacias_se_reportan(self):
        cols = [coleccion("hiking", [("TAG", "EQUALS", "Hiking")]),
                coleccion("pesca", [("TAG", "EQUALS", "Pesca")])]
        salida = motor.evaluar_catalogo([{"tags": ["Hiking"]}], cols)
        self.assertEqual(salida["vacias"], ["pesca"])


class TestVocabularioDelCatalogo(unittest.TestCase):
    def test_cuenta_y_clasifica(self):
        productos = [
            {"mod_col": "2086961-TYA", "tags": ["Hiking", "Hombre", "2086961-TYA"]},
            {"mod_col": "2086941-VJP", "tags": ["Hiking", "Mujer", "2086941-VJP"]},
        ]
        filas = {f["tag"]: f for f in motor.vocabulario_de_catalogo(productos, {"actividad": ["Hiking"]})}
        self.assertEqual(filas["Hiking"]["productos"], 2)
        self.assertEqual(filas["Hiking"]["familia"], "actividad")
        self.assertEqual(filas["2086961-TYA"]["familia"], "codigo")

    def test_tags_en_dos_cajas(self):
        """Shopify trata `Mochila` y `mochila` como tags DISTINTOS, asi que una
        coleccion por uno se deja fuera los del otro. Los dos estan en el
        catalogo real de Columbia.pe."""
        productos = [{"tags": ["Mochila"]}, {"tags": ["mochila"]}, {"tags": ["Hiking"]}]
        self.assertEqual(motor.tags_en_dos_cajas(productos), [["Mochila", "mochila"]])


class TestElArchivo(unittest.TestCase):
    def test_que_falte_no_es_un_error(self):
        vacio = motor.cargar_diccionario(RAIZ / "no" / "existe.json")
        self.assertEqual(vacio["marcas"], {})

    def test_un_archivo_roto_tampoco(self):
        with tempfile.TemporaryDirectory() as carpeta:
            ruta = Path(carpeta) / "roto.json"
            ruta.write_text("{esto no es json", encoding="utf-8")
            self.assertEqual(motor.cargar_diccionario(ruta)["marcas"], {})

    def test_ida_y_vuelta(self):
        with tempfile.TemporaryDirectory() as carpeta:
            ruta = Path(carpeta) / "d.json"
            datos = {"version": 1, "generado": "", "marcas": {"VANS": {"sitios": {}}}}
            motor.guardar_diccionario(ruta, datos)
            self.assertEqual(motor.cargar_diccionario(ruta), datos)

    def test_el_diccionario_del_repo_se_lee(self):
        datos = motor.cargar_diccionario(DICCIONARIO)
        self.assertIn("COLUMBIA", motor.marcas_del_diccionario(datos))
        vocabulario = motor.vocabulario_de(datos, "COLUMBIA", "columbia")
        self.assertIn("Hiking", vocabulario.get("actividad", []))
        self.assertIn("Omni-Tech™", vocabulario.get("tecnologia", []))

    def test_ningun_tag_declarado_en_dos_familias(self):
        """Un tag en dos familias hace que la familia dependa del orden de
        resolucion y no del dato."""
        datos = motor.cargar_diccionario(DICCIONARIO)
        for marca in motor.marcas_del_diccionario(datos):
            for sitio in motor.sitios_de_marca(datos, marca):
                visto = {}
                for familia, tags in motor.vocabulario_de(datos, marca, sitio).items():
                    for tag in tags:
                        k = motor.clave(tag)
                        self.assertNotIn(
                            k, visto, f"{marca}/{sitio}: {tag} en {visto.get(k)} y en {familia}")
                        visto[k] = familia


class TestTraduccionDesdeShopify(unittest.TestCase):
    def test_una_coleccion_automatica(self):
        registro = shopify_api.coleccion_a_registro({
            "handle": "hiking", "title": "Hiking",
            "productsCount": {"count": 383},
            "ruleSet": {"appliedDisjunctively": True,
                        "rules": [{"column": "TAG", "relation": "EQUALS", "condition": "Hiking"}]},
        })
        self.assertTrue(registro["automatica"])
        self.assertTrue(registro["disyuntiva"])
        self.assertEqual(registro["reglas"], [{"campo": "TAG", "relacion": "EQUALS", "valor": "Hiking"}])
        self.assertEqual(registro["productos_shopify"], 383)

    def test_una_coleccion_manual_no_es_un_hueco(self):
        registro = shopify_api.coleccion_a_registro({"handle": "destacados", "title": "Destacados"})
        self.assertFalse(registro["automatica"])
        self.assertEqual(registro["reglas"], [])

    def test_la_consulta_pide_la_regla(self):
        """Sin `ruleSet` el diccionario seria una lista de nombres y no podria
        responder que tag hay que ponerle al producto."""
        fuente = (RAIZ / "shopify_api.py").read_text(encoding="utf-8")
        consulta = fuente.split("def fetch_collections")[1].split("def ")[0]
        for campo in ("ruleSet", "appliedDisjunctively", "column", "relation", "condition"):
            self.assertIn(campo, consulta, campo)


class TestGenerador(unittest.TestCase):
    """El generador no puede perder trabajo hecho a mano ni borrar lo que no
    leyo esta vez."""

    def setUp(self):
        import importlib
        self.gen = importlib.import_module("generar_diccionario_colecciones")

    def test_conserva_el_vocabulario_curado(self):
        anterior = {"actividad": ["Hiking"], "tecnologia": ["Omni-Tech™"]}
        salida = self.gen.vocabulario_fusionado(anterior, ["Hiking", "Omni-Tech™", "Regalo"])
        self.assertEqual(salida["actividad"], ["Hiking"])
        self.assertEqual(salida["sin_clasificar"], ["Regalo"])

    def test_no_borra_un_tag_que_ya_no_esta_en_la_tienda(self):
        salida = self.gen.vocabulario_fusionado({"linea": ["Star Wars™"]}, ["Hiking"])
        self.assertEqual(salida["linea"], ["Star Wars™"])

    def test_un_tag_ya_estructural_no_entra_como_sin_clasificar(self):
        salida = self.gen.vocabulario_fusionado({}, ["Hombre", "Casaca", "Regalo"])
        self.assertEqual(salida.get("sin_clasificar"), ["Regalo"])

    def test_un_sitio_caido_no_tumba_a_los_demas(self):
        def explota(config, **kwargs):
            raise RuntimeError("token vencido")

        original = shopify_api.fetch_collections
        shopify_api.fetch_collections = explota
        try:
            cols, productos, error = self.gen.leer_sitio("vans", {"shop_domain": "x"}, 10)
        finally:
            shopify_api.fetch_collections = original
        self.assertEqual((cols, productos), ([], []))
        self.assertIn("token vencido", error)

    def test_agrupa_por_marca_y_no_reparte_las_colecciones_ajenas(self):
        """Una coleccion automatica sin un solo producto de la marca no es
        suya. Listarla en todas haria creer que comparten colecciones."""
        cols = [{"handle": "hiking", "title": "Hiking",
                 "ruleSet": {"appliedDisjunctively": False,
                             "rules": [{"column": "TAG", "relation": "EQUALS", "condition": "Hiking"}]}},
                {"handle": "surf", "title": "Surf",
                 "ruleSet": {"appliedDisjunctively": False,
                             "rules": [{"column": "TAG", "relation": "EQUALS", "condition": "Surf"}]}}]
        productos = [
            {"Handle": "a", "Mod-Col": "A-1", "Marca": "COLUMBIA", "Tags": "Hiking, Hombre", "Type": "Casacas"},
            {"Handle": "b", "Mod-Col": "B-1", "Marca": "VANS", "Tags": "Surf", "Type": "Zapatillas"},
        ]
        originales = (shopify_api.fetch_collections, shopify_api.fetch_products)
        shopify_api.fetch_collections = lambda config, **k: cols
        shopify_api.fetch_products = lambda config, **k: productos
        entorno = dict(os.environ)
        os.environ["ROCKFORD_SHOP_DOMAIN"] = "x.myshopify.com"
        os.environ["ROCKFORD_ADMIN_API_ACCESS_TOKEN"] = "shpat_x"
        try:
            datos = self.gen.construir(["rockford"], 100, {"marcas": {}})
        finally:
            shopify_api.fetch_collections, shopify_api.fetch_products = originales
            os.environ.clear()
            os.environ.update(entorno)
        columbia = datos["marcas"]["COLUMBIA"]["sitios"]["rockford"]["colecciones"]
        self.assertEqual([c["handle"] for c in columbia], ["hiking"])
        vans = datos["marcas"]["VANS"]["sitios"]["rockford"]["colecciones"]
        self.assertEqual([c["handle"] for c in vans], ["surf"])
        self.assertEqual(columbia[0]["tags"], ["Hiking"])
        self.assertEqual(columbia[0]["productos_de_la_marca"], 1)

    def test_no_escribe_nada_en_shopify(self):
        """Es un lector. Cualquier mutacion aqui cambiaria el catalogo de las
        seis tiendas de una sola corrida."""
        fuente = (RAIZ / "scripts" / "generar_diccionario_colecciones.py").read_text(encoding="utf-8")
        for prohibido in ("product_update", "product_create", "metafields_set", "publishable_publish",
                          "product_delete_media", "product_variants_bulk"):
            self.assertNotIn(prohibido, fuente, prohibido)


class TestUnSoloDiccionarioDeTipos(unittest.TestCase):
    """Eran dos tablas escritas a mano y se habian separado en 186 nombres."""

    def test_ningun_nombre_apunta_a_dos_prendas(self):
        """El indice es "gana el primero": un choque no revienta, manda uno de
        los dos en silencio. Destapo dos errores del propio maestro."""
        self.assertEqual(tipos.conflictos(), [])

    def test_las_dos_capas_dicen_lo_mismo_de_los_523_nombres(self):
        nombres = [n for regla in tipos.TIPOS for n in tipos.nombres_de(regla)]
        self.assertGreater(len(nombres), 500)
        for regla in tipos.TIPOS:
            for nombre in tipos.nombres_de(regla):
                salida = reglas.normalize_product_type(nombre)
                self.assertIsNotNone(salida, nombre)
                self.assertEqual(salida["normalized"], regla["singular"], nombre)
                self.assertEqual(salida["category"], regla["categoria"], nombre)
                self.assertEqual(salida["size_guide_group"], regla["grupo_talla"], nombre)
                self.assertEqual(salida["can_one_size"], regla["talla_unica"], nombre)

    def test_solo_el_vestuario_lleva_grupo_de_guia(self):
        for regla in tipos.TIPOS:
            self.assertEqual(bool(regla["grupo_talla"]), regla["categoria"] == "Vestuario", regla["tipo"])
            self.assertIn(regla["grupo_talla"], ("", "TOPS", "BOTTOMS"), regla["tipo"])

    def test_solo_los_accesorios_admiten_talla_unica(self):
        for regla in tipos.TIPOS:
            self.assertEqual(regla["talla_unica"], regla["categoria"] == "Accesorios", regla["tipo"])

    def test_el_hueco_de_agosto_esta_cerrado(self):
        """Sin grupo, las guias de TOPS y BOTTOMS empatan en prioridad 95 y la
        elegida depende del orden de la lista, no del producto."""
        for tipo, grupo in [("Chompas", "TOPS"), ("Jeans", "BOTTOMS"), ("Enterizos", "TOPS"),
                            ("Blusas", "TOPS"), ("Chaleco Polar", "TOPS"), ("Faldas", "BOTTOMS"),
                            ("Leggings", "BOTTOMS"), ("Vestidos", "TOPS")]:
            self.assertEqual(tipos.grupo_talla_de(tipo), grupo, tipo)

    def test_los_nombres_que_solo_conocia_catalog_rules(self):
        for nombre, esperado in [("jogger", "Pantalones"), ("parka", "Casacas"),
                                 ("morral", "Mochilas"), ("navaja", "Cuchillas"),
                                 ("balaclava", "Pasamontañas"), ("bootie", "Botines"),
                                 ("guilleminas", "Ballerinas"), ("miton", "Guantes"),
                                 ("micropolar", "Polares"), ("sweatshirt", "Polerones"),
                                 ("portalata", "Fundas Para Latas"), ("portafolio", "Maletines"),
                                 ("banano", "Canguros"), ("gorro andino", "Chullos"),
                                 ("gafa", "Lentes De Sol"), ("trekking poles", "Bastones")]:
            self.assertEqual(tipos.tipo_canonico(nombre), esperado, nombre)

    def test_donde_se_contradecian_manda_el_maestro(self):
        for nombre, esperado in [("buzo", "Polerones"), ("falda", "Faldas"), ("beanie", "Chullos"),
                                 ("cartera", "Carteras"), ("jockey", "Gorros"),
                                 ("leggings", "Leggings"), ("bandana", "Pañuelos"),
                                 ("overol", "Overol"), ("chompa", "Chompas"), ("boot", "Botines")]:
            self.assertEqual(tipos.tipo_canonico(nombre), esperado, nombre)

    def test_hoody_estaba_en_91_productos_vivos_y_no_se_reconocia(self):
        self.assertEqual(tipos.tipo_canonico("Hoody"), "Polerones")

    def test_la_clase_no_es_un_tipo(self):
        """"calzado" mapeado a Zapatilla convertia una sandalia declarada como
        "calzado" en una zapatilla. Sin mapeo, la validacion lo avisa."""
        for nombre in ("calzado", "footwear", "outdoor", "vestuario"):
            self.assertIsNone(reglas.normalize_product_type(nombre), nombre)

    def test_los_tipos_del_catalogo_real_se_reconocen(self):
        import pandas as pd

        ruta = RAIZ / "data" / "tipos_shopify.xlsx"
        if not ruta.exists():
            self.skipTest("data/tipos_shopify.xlsx no esta")
        for valor in pd.read_excel(ruta)["Tipo"].dropna().astype(str):
            self.assertIsNotNone(tipos.resolver(valor), valor)


class TestLaPantalla(unittest.TestCase):
    """Las pruebas cubrian el motor y nadie tocaba la funcion que dibuja. Es lo
    que dejo un KeyError en produccion con el Status de carga."""

    @classmethod
    def setUpClass(cls):
        cls.fuente = (RAIZ / "app_matrixify.py").read_text(encoding="utf-8-sig")
        cls.arbol = ast.parse(cls.fuente)

    def _funcion(self, nombre):
        for nodo in ast.walk(self.arbol):
            if isinstance(nodo, ast.FunctionDef) and nodo.name == nombre:
                return nodo
        self.fail(f"{nombre} no existe")

    def test_la_pantalla_tiene_llamador(self):
        cuerpo = ast.dump(self._funcion("main"))
        self.assertIn("render_diccionario_colecciones", cuerpo)

    def test_el_boton_del_menu_esta_en_las_cinco_listas_de_selectores(self):
        """Un boton nuevo hay que registrarlo en CINCO listas y darle su icono.
        Nada en el codigo lo obliga: "Status de carga" salio sin icono."""
        self.assertEqual(self.fuente.count("div.st-key-operation_nav_colecciones"), 6)

    def test_la_pantalla_no_escribe_en_shopify(self):
        cuerpo = ast.dump(self._funcion("render_diccionario_colecciones"))
        for prohibido in ("product_update", "product_create", "metafields_set", "publishable_publish"):
            self.assertNotIn(prohibido, cuerpo, prohibido)

    def test_el_stat_va_fuera_de_la_cache(self):
        """La firma lleva (mtime, size) y no se usa dentro: esta ahi para que
        regenerar el archivo invalide la cache sola. Con el `stat` DENTRO
        habria que reiniciar la app para ver el diccionario nuevo."""
        cacheada = self._funcion("_diccionario_colecciones")
        self.assertEqual([a.arg for a in cacheada.args.args], ["mtime_ns", "size"])
        # Sin el docstring: ahi la palabra aparece explicando justamente esto.
        cuerpo = [n for n in cacheada.body if not (
            isinstance(n, ast.Expr) and isinstance(n.value, ast.Constant))]
        self.assertNotIn("stat", "".join(ast.dump(n) for n in cuerpo))
        self.assertIn("stat", ast.dump(self._funcion("cargar_diccionario_colecciones")))

    def test_las_claves_que_pide_la_pantalla_las_devuelve_el_motor(self):
        """El motor no usa tildes en ninguna clave; la pantalla las lee. Es el
        KeyError que tumbo el Status de carga en produccion."""
        col = {"handle": "h", "titulo": "T", "automatica": True, "disyuntiva": False,
               "reglas": [], "tags": [], "evaluable": True, "productos_de_la_marca": 0,
               "productos_shopify": 0}
        import app_matrixify

        tabla = app_matrixify._tabla_colecciones([col])
        self.assertEqual(len(tabla), 1)
        registro = shopify_api.coleccion_a_registro({"handle": "h", "title": "T"})
        for clave in ("handle", "titulo", "automatica", "disyuntiva", "reglas"):
            self.assertIn(clave, registro, clave)

    def test_la_tabla_de_tipos_trae_una_columna_por_sitio(self):
        import app_matrixify

        tabla = app_matrixify._tabla_tipos_de_prenda()
        self.assertEqual(len(tabla), len(tipos.TIPOS))
        for config in app_matrixify.SITE_CONFIGS.values():
            self.assertIn(config["site_label"], tabla.columns)


if __name__ == "__main__":
    sys.path.insert(0, str(RAIZ / "scripts"))
    unittest.main(verbosity=2)
