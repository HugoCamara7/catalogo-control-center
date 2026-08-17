"""Pruebas del enlace de productos relacionados y del tipo real del metacampo.

Origen: en la ficha de Shopify, `Siblings` y `Código Modelo Color` salían
vacíos aunque el Matrixify traía los valores.

- `custom.siblings` está declarado como `list.product_reference`: espera
  `gid://shopify/Product/...`. La carga completa le mandaba el handle en texto,
  Shopify lo rechazaba y el campo quedaba en blanco.
- El tipo se adivinaba desde la cabecera de Matrixify (`[id]`) o desde la tabla
  interna. Si no coincide con la definición de la tienda, Shopify también
  rechaza el valor. Ahora manda la definición real.

Ejecutar:  python scripts/test_siblings_referencias.py
"""
import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import app_matrixify as app  # noqa: E402

CONFIG = {"shop_domain": "prueba.myshopify.com", "token": "x"}


class _ShopifyFalso:
    """Rechaza un handle donde se espera una referencia de producto, igual que Shopify."""

    def __init__(self, definiciones=None):
        self.definiciones = definiciones or {}
        self.escritos = []

    def definicion(self, config, owner_type, namespace, key):
        tipo = self.definiciones.get((namespace, key))
        return {"type": {"name": tipo}} if tipo else {}

    def metafields_set(self, config, metafields):
        for metafield in metafields:
            if metafield["type"] in app.TIPOS_REFERENCIA_A_PRODUCTO:
                valor = metafield["value"]
                valores = json.loads(valor) if valor.startswith("[") else [valor]
                for item in valores:
                    if not str(item).startswith("gid://shopify/Product/"):
                        raise RuntimeError(f"Value error: {item} no es una referencia de producto")
            self.escritos.append(metafield)
        return {}


class _Sesion(dict):
    """st.session_state se usa como caché del tipo; un dict basta."""


class TestReferenciasAProducto(unittest.TestCase):
    def setUp(self):
        self.tienda = _ShopifyFalso()
        self._metafields_set = app.metafields_set
        self._session = app.st.session_state
        app.metafields_set = self.tienda.metafields_set
        app.st.session_state = _Sesion()

    def tearDown(self):
        app.metafields_set = self._metafields_set
        app.st.session_state = self._session

    def test_resuelve_los_handles_a_ids_de_producto(self):
        filas = {"mocasin-a": {"Resultado": "OK", "Mensaje": "Producto actualizado"}}
        app._escribir_referencias_a_producto(
            CONFIG,
            {"mocasin-a": [("custom", "siblings", "list.product_reference", ["mocasin-a", "mocasin-b"])]},
            {"mocasin-a": "gid://shopify/Product/1", "mocasin-b": "gid://shopify/Product/2"},
            filas,
        )
        # La relacion es del grupo: la misma lista se escribe en los dos.
        self.assertEqual(len(self.tienda.escritos), 2)
        self.assertEqual(
            {escrito["ownerId"] for escrito in self.tienda.escritos},
            {"gid://shopify/Product/1", "gid://shopify/Product/2"},
        )
        for escrito in self.tienda.escritos:
            self.assertEqual(escrito["type"], "list.product_reference")
            self.assertEqual(
                json.loads(escrito["value"]),
                ["gid://shopify/Product/1", "gid://shopify/Product/2"],
            )
        self.assertEqual(filas["mocasin-a"]["Resultado"], "OK")
        self.assertIn("2 relacionados", filas["mocasin-a"]["Mensaje"])

    def test_avisa_de_los_hermanos_que_no_existen(self):
        filas = {"mocasin-a": {"Resultado": "OK", "Mensaje": ""}}
        app._escribir_referencias_a_producto(
            CONFIG,
            {"mocasin-a": [("custom", "siblings", "list.product_reference", ["mocasin-a", "fantasma"])]},
            {"mocasin-a": "gid://shopify/Product/1"},
            filas,
        )
        self.assertEqual(len(self.tienda.escritos), 1)
        self.assertIn("1 sin resolver", filas["mocasin-a"]["Mensaje"])
        self.assertIn("fantasma", filas["mocasin-a"]["Mensaje"])

    def test_marca_parcial_si_no_resuelve_ninguno(self):
        filas = {"mocasin-a": {"Resultado": "OK", "Mensaje": ""}}
        app._escribir_referencias_a_producto(
            CONFIG,
            {"mocasin-a": [("custom", "siblings", "list.product_reference", ["fantasma"])]},
            {"mocasin-a": "gid://shopify/Product/1"},
            filas,
        )
        self.assertEqual(self.tienda.escritos, [])
        self.assertEqual(filas["mocasin-a"]["Resultado"], "PARCIAL")

    def test_referencia_simple_no_va_como_lista(self):
        filas = {"mocasin-a": {"Resultado": "OK", "Mensaje": ""}}
        app._escribir_referencias_a_producto(
            CONFIG,
            {"mocasin-a": [("custom", "principal", "product_reference", ["mocasin-b"])]},
            {"mocasin-a": "gid://shopify/Product/1", "mocasin-b": "gid://shopify/Product/2"},
            filas,
        )
        self.assertEqual(self.tienda.escritos[0]["value"], "gid://shopify/Product/2")

    def test_sin_pendientes_no_llama_a_shopify(self):
        app._escribir_referencias_a_producto(CONFIG, {}, {}, {})
        self.assertEqual(self.tienda.escritos, [])


class TestResolverHandleContraShopify(unittest.TestCase):
    """La carga procesa un producto por llamada: los hermanos hay que buscarlos."""

    def setUp(self):
        self._fetch = app.fetch_product_id_by_handle
        self._session = app.st.session_state
        app.st.session_state = _Sesion()

    def tearDown(self):
        app.fetch_product_id_by_handle = self._fetch
        app.st.session_state = self._session

    def test_la_tanda_manda_sobre_shopify(self):
        app.fetch_product_id_by_handle = lambda cfg, h: "gid://shopify/Product/999"
        gid = app._gid_de_producto_por_handle(
            CONFIG, "mocasin-a", {"mocasin-a": "gid://shopify/Product/1"}
        )
        self.assertEqual(gid, "gid://shopify/Product/1")

    def test_pregunta_a_shopify_si_no_esta_en_la_tanda(self):
        app.fetch_product_id_by_handle = lambda cfg, h: "gid://shopify/Product/7"
        self.assertEqual(
            app._gid_de_producto_por_handle(CONFIG, "hermano-de-otra-tanda", {}),
            "gid://shopify/Product/7",
        )

    def test_solo_cachea_los_aciertos(self):
        # Un hermano que aun no existe debe poder resolverse cuando se cree.
        existentes = {}
        app.fetch_product_id_by_handle = lambda cfg, h: existentes.get(h, "")
        self.assertEqual(app._gid_de_producto_por_handle(CONFIG, "todavia-no", {}), "")
        existentes["todavia-no"] = "gid://shopify/Product/5"
        self.assertEqual(
            app._gid_de_producto_por_handle(CONFIG, "todavia-no", {}),
            "gid://shopify/Product/5",
        )

    def test_recordar_evita_volver_a_preguntar(self):
        llamadas = []

        def contar(cfg, h):
            llamadas.append(h)
            return ""

        app.fetch_product_id_by_handle = contar
        app._recordar_gid_de_handle("Mocasin-A", "gid://shopify/Product/3")
        gid = app._gid_de_producto_por_handle(CONFIG, "mocasin-a", {})
        self.assertEqual(gid, "gid://shopify/Product/3")
        self.assertEqual(llamadas, [])

    def test_si_shopify_falla_no_rompe_la_carga(self):
        def explota(cfg, h):
            raise RuntimeError("sin red")

        app.fetch_product_id_by_handle = explota
        self.assertEqual(app._gid_de_producto_por_handle(CONFIG, "mocasin-a", {}), "")


class TestTipoDesdeLaDefinicion(unittest.TestCase):
    def setUp(self):
        self._fetch = app.fetch_metafield_definition
        self._session = app.st.session_state
        app.st.session_state = _Sesion()

    def tearDown(self):
        app.fetch_metafield_definition = self._fetch
        app.st.session_state = self._session

    def test_manda_la_definicion_de_la_tienda(self):
        tienda = _ShopifyFalso({("custom", "codigo_modelo_color"): "single_line_text_field"})
        app.fetch_metafield_definition = tienda.definicion
        tipo = app._tipo_metafield_de_la_tienda(CONFIG, "custom", "codigo_modelo_color")
        self.assertEqual(tipo, "single_line_text_field")

    def test_se_cachea_y_no_vuelve_a_preguntar(self):
        llamadas = []

        def contar(config, owner_type, namespace, key):
            llamadas.append((namespace, key))
            return {"type": {"name": "single_line_text_field"}}

        app.fetch_metafield_definition = contar
        for _ in range(4):
            app._tipo_metafield_de_la_tienda(CONFIG, "custom", "tipo")
        self.assertEqual(len(llamadas), 1)

    def test_si_no_hay_definicion_devuelve_vacio(self):
        app.fetch_metafield_definition = lambda *a, **k: {}
        self.assertEqual(app._tipo_metafield_de_la_tienda(CONFIG, "custom", "loquesea"), "")

    def test_si_la_consulta_falla_no_rompe_la_carga(self):
        def explota(*a, **k):
            raise RuntimeError("sin red")

        app.fetch_metafield_definition = explota
        self.assertEqual(app._tipo_metafield_de_la_tienda(CONFIG, "custom", "tipo"), "")


if __name__ == "__main__":
    unittest.main(verbosity=2)
