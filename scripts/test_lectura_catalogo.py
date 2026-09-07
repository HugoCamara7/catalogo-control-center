"""La lectura del catalogo de un sitio.

Por que existe
--------------
Leer el catalogo de un sitio se habia vuelto imposible: "ni termina de leerlo".
La causa es el COSTO de la consulta paginada. Shopify cobra por consulta y una
pagina de productos con `variants(first: 100)` y `media(first: 10)` cuesta unos
430 puntos POR PRODUCTO; el maximo de una sola consulta son 1.000. Con eso, la
unica forma de que la consulta entre es bajar `products_page_size` a dos o tres
productos, y entonces un catalogo de 3.000 productos son mil viajes que ademas
pagan espera de balde en cada uno -el balde se recarga a 50 puntos por segundo-.

Una bulk operation no paga costo por consulta: Shopify la corre de su lado y
deja el catalogo entero en un JSONL. Estas pruebas fijan que la lectura masiva
sea la normal, que la paginada siga estando de respaldo, y sobre todo que las
dos traigan LO MISMO: dos lecturas del catalogo que se separan es el error que
este repositorio ya paga con las dos `normalize_size`.

Ejecutar:  python scripts/test_lectura_catalogo.py
"""
import ast
import gzip
import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import shopify_api  # noqa: E402


CONFIG = {"shop_domain": "vanspe.myshopify.com", "admin_access_token": "shpat_x"}


def producto_jsonl(numero, variantes=2, fotos=1):
    """Las lineas que Shopify deja en el JSONL para un producto."""
    gid = f"gid://shopify/Product/{numero}"
    lineas = [
        {
            "id": gid,
            "legacyResourceId": str(numero),
            "handle": f"zapato-{numero}",
            "title": f"ZAPATO {numero}",
            "descriptionHtml": "<p>x</p>",
            "tags": ["a", "b"],
            "vendor": "vanspe",
            "productType": "Zapatillas",
            "status": "ACTIVE",
            "onlineStoreUrl": f"https://vans.pe/p/{numero}",
            "publishedOnOnlineStore": True,
            "codigoModeloColor": {"value": f"VN{numero}-001"},
            "marca": {"value": "Vans"},
            "materialidad": None,
            "tecnologia": None,
            "logo": None,
            "siblings": {"value": "[\"a\"]"},
            "siblingsColor": None,
            "customSiblings": None,
            "customSiblingsColor": None,
        }
    ]
    for foto in range(fotos):
        lineas.append({
            "id": f"gid://shopify/MediaImage/{numero}{foto}",
            "image": {"url": f"https://cdn/{numero}-{foto}.jpg"},
            "__parentId": gid,
        })
    for variante in range(variantes):
        lineas.append({
            "id": f"gid://shopify/ProductVariant/{numero}{variante}",
            "legacyResourceId": f"{numero}{variante}",
            "sku": f"SKU-{numero}-{variante}",
            "barcode": f"77{numero}{variante}",
            "price": "199.00",
            "compareAtPrice": "249.00",
            "inventoryQuantity": 5,
            "selectedOptions": [{"name": "Talla", "value": str(38 + variante)}],
            "image": {"url": f"https://cdn/v{numero}-{variante}.jpg"},
            "inventoryItem": {"id": f"gid://shopify/InventoryItem/{numero}{variante}",
                              "legacyResourceId": f"9{numero}{variante}"},
            "__parentId": gid,
        })
    return lineas


def nodo_paginado(numero, variantes=2, fotos=1):
    """El MISMO producto como lo devuelve la consulta paginada."""
    lineas = producto_jsonl(numero, variantes=variantes, fotos=fotos)
    nodo = dict(lineas[0])
    nodo["media"] = {"nodes": [{k: v for k, v in l.items() if k != "__parentId"}
                               for l in lineas if "MediaImage" in l["id"]]}
    nodo["variants"] = {"nodes": [{k: v for k, v in l.items() if k != "__parentId"}
                                  for l in lineas if "ProductVariant" in l["id"]]}
    return nodo


class FalsoShopify:
    """Contesta como Shopify sin salir a la red."""

    def __init__(self, productos=3, estados=None, errores_usuario=None):
        self.productos = productos
        self.estados = list(estados or ["COMPLETED"])
        self.errores_usuario = errores_usuario or []
        self.consultas = []
        self.url = "https://storage.googleapis.com/resultado.jsonl"

    def graphql_request(self, shop_domain, token, query, variables=None, **kwargs):
        self.consultas.append((query, variables or {}))
        if "bulkOperationRunQuery" in query:
            if self.errores_usuario:
                return {"bulkOperationRunQuery": {"bulkOperation": None,
                                                  "userErrors": self.errores_usuario}}
            return {"bulkOperationRunQuery": {
                "bulkOperation": {"id": "gid://shopify/BulkOperation/1", "status": "CREATED"},
                "userErrors": []}}
        if "EstadoLecturaMasiva" in query:
            estado = self.estados.pop(0) if len(self.estados) > 1 else self.estados[0]
            nodo = {"id": "gid://shopify/BulkOperation/1", "status": estado,
                    "objectCount": "10", "errorCode": None}
            if estado == "COMPLETED":
                nodo["url"] = self.url
            return {"node": nodo}
        if "ProductsForMatrixify" in query:
            nodos = [nodo_paginado(n) for n in range(1, self.productos + 1)]
            return {"products": {"pageInfo": {"hasNextPage": False, "endCursor": None},
                                 "nodes": nodos}}
        if "Publications" in query:
            return {"publications": {"nodes": []}}
        return {}

    def jsonl(self):
        lineas = []
        for numero in range(1, self.productos + 1):
            lineas.extend(producto_jsonl(numero))
        return "".join(json.dumps(l) + "\n" for l in lineas)


class Base(unittest.TestCase):
    def montar(self, falso, comprimir=False):
        self.falso = falso
        self.carpeta = tempfile.TemporaryDirectory()
        self.addCleanup(self.carpeta.cleanup)
        ruta = Path(self.carpeta.name) / "resultado.jsonl"
        datos = falso.jsonl().encode("utf-8")
        if comprimir:
            ruta.write_bytes(gzip.compress(datos))
        else:
            ruta.write_bytes(datos)

        def descargar(url, destino, timeout=120):
            Path(destino).write_bytes(ruta.read_bytes())
            return False

        self._parchar(shopify_api, "graphql_request", falso.graphql_request)
        self._parchar(shopify_api, "_bulk_descargar", descargar)
        self._parchar(shopify_api, "online_store_publication_id",
                      lambda config: "gid://shopify/Publication/1")

    def _parchar(self, modulo, nombre, valor):
        anterior = getattr(modulo, nombre)
        setattr(modulo, nombre, valor)
        self.addCleanup(setattr, modulo, nombre, anterior)


class TestLecturaMasiva(Base):
    def test_devuelve_el_catalogo_reensamblado(self):
        self.montar(FalsoShopify(productos=3))
        registros = shopify_api.fetch_products(CONFIG)
        self.assertEqual(len(registros), 3)
        primero = registros[0]
        self.assertEqual(primero["Handle"], "zapato-1")
        self.assertEqual(primero["Mod-Col"], "VN1-001")
        self.assertEqual(primero["Marca"], "Vans")
        self.assertEqual(len(primero["Variants"]), 2)
        self.assertEqual(primero["Variants"][0]["Variant SKU"], "SKU-1-0")
        self.assertEqual(primero["Published Online Store"], "SI")

    def test_da_exactamente_lo_mismo_que_la_lectura_paginada(self):
        """La razon de ser de la prueba: dos lecturas que se separan sin que
        nadie lo note es el error que este repositorio ya paga dos veces."""
        self.montar(FalsoShopify(productos=4))
        masiva = shopify_api.fetch_products_bulk(CONFIG)
        paginada = shopify_api.fetch_products_paginado(CONFIG)
        orden = lambda filas: sorted(filas, key=lambda fila: fila["Handle"])
        self.assertEqual(orden(masiva), orden(paginada))

    def test_una_variante_huerfana_no_se_pierde_ni_revienta(self):
        """El JSONL no garantiza que el hijo venga despues del padre."""
        lineas = producto_jsonl(1)
        revuelto = lineas[1:] + lineas[:1]
        registros = shopify_api._bulk_reensamblar(json.dumps(l) + "\n" for l in revuelto)
        self.assertEqual(len(registros), 1)
        self.assertEqual(len(registros[0]["Variants"]), 2)

    def test_una_linea_sin_padre_conocido_no_tumba_la_lectura(self):
        lineas = producto_jsonl(1) + [{"id": "gid://shopify/ProductVariant/999",
                                       "sku": "HUERFANA", "__parentId": "gid://shopify/Product/404"}]
        registros = shopify_api._bulk_reensamblar(json.dumps(l) + "\n" for l in lineas)
        self.assertEqual(len(registros), 1)
        self.assertNotIn("HUERFANA", json.dumps(registros))

    def test_una_linea_rota_se_salta(self):
        lineas = [json.dumps(l) for l in producto_jsonl(1)]
        lineas.insert(1, "{esto no es json")
        registros = shopify_api._bulk_reensamblar(linea + "\n" for linea in lineas)
        self.assertEqual(len(registros), 1)

    def test_respeta_el_tope_de_productos(self):
        self.montar(FalsoShopify(productos=5))
        self.assertEqual(len(shopify_api.fetch_products(CONFIG, max_products=2)), 2)

    def test_lee_el_jsonl_comprimido(self):
        falso = FalsoShopify(productos=2)
        self.montar(falso, comprimir=True)
        self.assertEqual(len(shopify_api.fetch_products(CONFIG)), 2)

    def test_un_catalogo_vacio_no_es_un_error(self):
        falso = FalsoShopify(productos=0)
        self.montar(falso)
        self.falso.url = ""
        self.assertEqual(shopify_api.fetch_products(CONFIG), [])

    def test_espera_hasta_que_shopify_termina(self):
        falso = FalsoShopify(productos=1, estados=["CREATED", "RUNNING", "RUNNING", "COMPLETED"])
        self.montar(falso)
        dormidas = []
        self._parchar(shopify_api, "time", shopify_api.time)
        url = shopify_api._bulk_esperar(
            "vanspe.myshopify.com", "t", "2026-04", "gid://shopify/BulkOperation/1",
            dormir=dormidas.append,
        )
        self.assertEqual(url, falso.url)
        self.assertEqual(len(dormidas), 3)
        self.assertGreater(dormidas[-1], dormidas[0], "la espera tiene que crecer")

    def test_una_lectura_fallida_se_dice_y_no_se_devuelve_a_medias(self):
        falso = FalsoShopify(productos=1, estados=["FAILED"])
        self.montar(falso)
        with self.assertRaises(shopify_api.ShopifyApiError):
            shopify_api._bulk_esperar("vanspe.myshopify.com", "t", "2026-04",
                                      "gid://shopify/BulkOperation/1", dormir=lambda _: None)


class TestRespaldoPaginado(Base):
    def test_si_ya_hay_otra_lectura_masiva_se_sigue_paginando(self):
        """Shopify solo admite UNA bulk operation por app y tienda a la vez.
        Dos personas leyendo el mismo sitio no pueden quedarse sin catalogo."""
        falso = FalsoShopify(productos=3, errores_usuario=[
            {"field": None, "message": "A bulk query operation for this app and shop is already in progress"}])
        self.montar(falso)
        avisos = []
        registros = shopify_api.fetch_products(CONFIG, progreso=avisos.append)
        self.assertEqual(len(registros), 3)
        self.assertTrue(any("pagina" in aviso.lower() for aviso in avisos), avisos)

    def test_se_puede_apagar_desde_secrets(self):
        falso = FalsoShopify(productos=2)
        self.montar(falso)
        registros = shopify_api.fetch_products(dict(CONFIG, bulk_products="no"))
        self.assertEqual(len(registros), 2)
        self.assertFalse(any("bulkOperationRunQuery" in consulta for consulta, _ in falso.consultas))

    def test_el_tamano_de_pagina_y_de_variantes_sale_de_secrets(self):
        falso = FalsoShopify(productos=1)
        self.montar(falso)
        shopify_api.fetch_products_paginado(dict(CONFIG, products_page_size="25", variants_page_size="30"))
        consulta, variables = falso.consultas[-1]
        self.assertEqual(variables["first"], 25)
        self.assertIn("variants(first: 30)", consulta)

    def test_por_defecto_sigue_pidiendo_las_100_variantes_de_siempre(self):
        falso = FalsoShopify(productos=1)
        self.montar(falso)
        shopify_api.fetch_products_paginado(CONFIG)
        consulta, _ = falso.consultas[-1]
        self.assertIn("variants(first: 100)", consulta)


class TestReglasDelCodigo(unittest.TestCase):
    """Lo que no se puede volver a hacer, comprobado sobre el codigo."""

    @classmethod
    def setUpClass(cls):
        cls.fuente = (ROOT / "shopify_api.py").read_text(encoding="utf-8")
        cls.arbol = ast.parse(cls.fuente)

    def test_las_dos_lecturas_usan_la_misma_lista_de_campos(self):
        """Si una trae un campo que la otra no, el catalogo cambia segun por
        donde se leyo. Los campos se escriben UNA vez."""
        for nombre in ("_bulk_query", "fetch_products_paginado"):
            cuerpo = ast.get_source_segment(
                self.fuente,
                next(n for n in ast.walk(self.arbol)
                     if isinstance(n, ast.FunctionDef) and n.name == nombre),
            )
            for campo in ("CAMPOS_PRODUCTO", "CAMPOS_MEDIA", "CAMPOS_VARIANTE"):
                self.assertIn(campo, cuerpo, f"{nombre} no usa {campo}")
            self.assertNotIn("codigo_modelo_color", cuerpo,
                             f"{nombre} escribe campos a mano en vez de usar la lista comun")

    def test_la_consulta_masiva_no_lleva_argumentos_de_paginacion(self):
        """Una bulk operation los rechaza: `first`, `after`, variables."""
        consulta = shopify_api._bulk_query({"publication_id": "gid://shopify/Publication/1"})
        for prohibido in ("first:", "after:", "$first", "$after", "pageInfo"):
            self.assertNotIn(prohibido, consulta, f"la consulta masiva no puede llevar '{prohibido}'")
        self.assertIn("edges", consulta)
        self.assertIn('publicationId: "gid://shopify/Publication/1"', consulta)

    def test_el_jsonl_no_se_materializa_en_memoria(self):
        """La regla del proyecto: ningun archivo del usuario entra entero."""
        for nombre in ("_bulk_descargar", "_bulk_reensamblar", "fetch_products_bulk"):
            cuerpo = ast.get_source_segment(
                self.fuente,
                next(n for n in ast.walk(self.arbol)
                     if isinstance(n, ast.FunctionDef) and n.name == nombre),
            )
            for prohibido in (".readlines()", ".read().decode(", "list(archivo", "list(lineas"):
                self.assertNotIn(prohibido, cuerpo,
                                 f"{nombre} usa '{prohibido}' y eso carga el archivo entero")

    def test_el_reensamblado_va_soltando_los_nodos(self):
        """Armar la lista sin soltar el diccionario deja el catalogo dos veces
        en memoria, y son cientos de MB en los sitios grandes."""
        cuerpo = ast.get_source_segment(
            self.fuente,
            next(n for n in ast.walk(self.arbol)
                 if isinstance(n, ast.FunctionDef) and n.name == "_bulk_reensamblar"),
        )
        self.assertIn("productos.pop(", cuerpo)

    def test_el_aviso_de_progreso_nunca_puede_tumbar_la_lectura(self):
        llamadas = []

        def revienta(mensaje):
            llamadas.append(mensaje)
            raise RuntimeError("la pantalla se fue")

        shopify_api._avisar(revienta, "hola")
        self.assertEqual(llamadas, ["hola"])

    def test_el_archivo_temporal_se_borra(self):
        cuerpo = ast.get_source_segment(
            self.fuente,
            next(n for n in ast.walk(self.arbol)
                 if isinstance(n, ast.FunctionDef) and n.name == "fetch_products_bulk"),
        )
        self.assertIn("finally:", cuerpo)
        self.assertIn("os.remove(", cuerpo)


class TestCatalogoGuardadoEnDisco(unittest.TestCase):
    """La sesion sola no alcanzaba: un reinicio del contenedor o una persona
    nueva volvian a pagar los minutos de la lectura entera."""

    def setUp(self):
        import app_matrixify as app
        self.app = app
        self.carpeta = tempfile.TemporaryDirectory()
        self.addCleanup(self.carpeta.cleanup)
        self.sesion_previa = app.st.session_state
        app.st.session_state = {}
        self.addCleanup(lambda: setattr(app.st, "session_state", self.sesion_previa))
        ruta = Path(self.carpeta.name) / "catalogo.pkl"
        self.ruta_previa = app._ruta_catalogo_en_disco
        app._ruta_catalogo_en_disco = lambda site_key: ruta
        self.addCleanup(lambda: setattr(app, "_ruta_catalogo_en_disco", self.ruta_previa))
        self.ruta = ruta

    def test_lo_guardado_se_recupera_sin_ir_a_shopify(self):
        productos = [{"Handle": "zapato-1"}]
        self.app.guardar_shopify_products("vans", CONFIG, productos)
        self.app.st.session_state.clear()  # como si el contenedor se hubiera reiniciado
        self.assertEqual(self.app.shopify_products_en_cache("vans", CONFIG), productos)

    def test_el_catalogo_de_otra_tienda_no_se_reusa(self):
        """Devolver el catalogo de Rockford cuando se pidio el de Vans seria
        peor que no tener cache: decide que producto se crea y cual se actualiza."""
        self.app.guardar_shopify_products("vans", CONFIG, [{"Handle": "zapato-1"}])
        self.app.st.session_state.clear()
        otra = dict(CONFIG, shop_domain="rockfordpe.myshopify.com")
        self.assertIsNone(self.app.shopify_products_en_cache("vans", otra))

    def test_un_catalogo_viejo_se_descarta(self):
        self.app.guardar_shopify_products("vans", CONFIG, [{"Handle": "zapato-1"}])
        productos, _ = self.app.catalogo_en_disco("vans", CONFIG, minutos=0)
        self.assertIsNone(productos)

    def test_un_archivo_corrupto_no_tumba_la_pantalla(self):
        self.ruta.write_bytes(b"esto no es un pickle")
        self.assertIsNone(self.app.shopify_products_en_cache("vans", CONFIG))

    def test_volver_a_leer_borra_tambien_el_de_disco(self):
        """Si solo se limpiara la sesion, el boton "Volver a leer" devolveria
        el mismo catalogo viejo desde el disco."""
        self.app.guardar_shopify_products("vans", CONFIG, [{"Handle": "zapato-1"}])
        self.assertTrue(self.ruta.exists())
        self.app.clear_shopify_products_cache("vans")
        self.assertFalse(self.ruta.exists())
        self.assertIsNone(self.app.shopify_products_en_cache("vans", CONFIG))

    def test_la_fecha_de_lectura_queda_a_la_vista(self):
        self.app.guardar_shopify_products("vans", CONFIG, [{"Handle": "zapato-1"}])
        self.assertIsNotNone(self.app.catalogo_leido_en("vans"))

    def test_la_pantalla_pide_el_catalogo_avisando_por_donde_va(self):
        fuente = (ROOT / "app_matrixify.py").read_text(encoding="utf-8-sig")
        arbol = ast.parse(fuente)
        cuerpo = ast.get_source_segment(fuente, next(
            n for n in ast.walk(arbol)
            if isinstance(n, ast.FunctionDef) and n.name == "leer_catalogo_del_sitio"))
        self.assertIn("progreso=", cuerpo)
        self.assertIn("session_shopify_products(", cuerpo)
        # Y la Carga completa tiene que usar esa, no la muda.
        self.assertIn("leer_catalogo_del_sitio(brand_config[\"site_key\"], shopify_config)", fuente)


if __name__ == "__main__":
    unittest.main(verbosity=2)
