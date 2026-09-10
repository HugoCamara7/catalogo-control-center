#!/usr/bin/env python3
"""Los metacampos van en UNA llamada, no en veinte.

Reportado como *"¿por qué la carga es tan lenta?"*, con 4.500 de 8.100
productos cargados. Medido antes de tocar nada:

    metacampos del producto  |  viajes a Shopify por producto
                     3       |  18
                     6       |  23
                    12       |  32

Escala 1 a 1, porque `apply_full_product_updates` hacia
`for metafield in metafields: metafields_set(config, [metafield])` -- **un
viaje por cada metacampo, por cada producto** -- y `metafields_set` recibe una
lista desde siempre. La app sabe escribir 26 metacampos.

Y el tiempo de carga es casi todo esperar a la red: de 21 viajes medidos, 21
son red; nuestro CPU son **16 ms por producto**. O sea que quitar viajes es lo
unico que la hace mas rapida.

Por que NO se vuelve al lote a secas
------------------------------------
`metafieldsSet` es **todo o nada**: un solo tipo que no coincida con la
definicion de la tienda deja los 25 sin escribir. Eso ya paso con
`theme.siblings` (seccion 9 del CLAUDE.md), y es la razon por la que se habian
separado uno por uno.

El respaldo conserva esa propiedad entera, y es lo que fijan estas pruebas: si
el lote falla se reintenta **uno por uno**, se escriben todos los buenos y el
informe dice cual es el malo -- exactamente lo que hacia antes.
"""

from __future__ import annotations

import inspect
import sys
import unittest
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
if str(RAIZ) not in sys.path:
    sys.path.insert(0, str(RAIZ))

import pandas as pd  # noqa: E402


def metacampos(cuantos, namespace="custom"):
    return [
        {"ownerId": "gid://shopify/Product/1", "namespace": namespace,
         "key": f"campo_{i}", "type": "single_line_text_field", "value": f"valor {i}"}
        for i in range(cuantos)
    ]


class _Shopify:
    """Un Shopify falso que cuenta llamadas y puede rechazar una clave."""

    def __init__(self, rechaza=()):
        self.llamadas = []
        self.escritos = []
        self.rechaza = set(rechaza)

    def metafields_set(self, config, lote):
        self.llamadas.append([m["key"] for m in lote])
        malos = [m["key"] for m in lote if m["key"] in self.rechaza]
        if malos:
            # Todo o nada: si uno no cuadra, NINGUNO se escribe.
            raise RuntimeError(f"tipo invalido en {', '.join(malos)}")
        self.escritos.extend((m["namespace"], m["key"], m["type"], m["value"]) for m in lote)
        return []


class _ConShopifyFalso(unittest.TestCase):
    def _correr(self, metas, rechaza=(), tamano=None):
        import app_matrixify as app
        falso = _Shopify(rechaza)
        previo = app.metafields_set
        app.metafields_set = falso.metafields_set
        try:
            extra = {} if tamano is None else {"tamano": tamano}
            ok, errores = app._escribir_metafields_en_lote({"shop_domain": "x"}, metas, **extra)
        finally:
            app.metafields_set = previo
        return falso, ok, errores


class TestElCaminoFeliz(_ConShopifyFalso):
    def test_doce_metacampos_cuestan_UNA_llamada(self):
        falso, ok, errores = self._correr(metacampos(12))
        self.assertEqual(len(falso.llamadas), 1)
        self.assertEqual(ok, 12)
        self.assertEqual(errores, [])

    def test_se_escriben_TODOS_y_con_su_valor(self):
        metas = metacampos(12)
        falso, _, _ = self._correr(metas)
        self.assertEqual(
            sorted(falso.escritos),
            sorted((m["namespace"], m["key"], m["type"], m["value"]) for m in metas))

    def test_uno_solo_no_arma_lote(self):
        """Con un metacampo el lote no ahorra nada y agregaria una rama."""
        falso, ok, _ = self._correr(metacampos(1))
        self.assertEqual(len(falso.llamadas), 1)
        self.assertEqual(ok, 1)

    def test_sin_metacampos_no_llama_a_nadie(self):
        falso, ok, errores = self._correr([])
        self.assertEqual(falso.llamadas, [])
        self.assertEqual((ok, errores), (0, []))

    def test_respeta_el_tope_de_25_de_Shopify(self):
        """No es una eleccion nuestra: es el maximo de `metafieldsSet`."""
        falso, ok, _ = self._correr(metacampos(36))
        self.assertEqual([len(l) for l in falso.llamadas], [25, 11])
        self.assertEqual(ok, 36)

    def test_el_tope_sale_de_una_constante_con_nombre(self):
        import app_matrixify as app
        self.assertEqual(app.METAFIELDS_POR_LLAMADA, 25)


class TestElAislamientoDelFalloSEConserva(_ConShopifyFalso):
    """Lo que protegia el bucle de uno en uno, y no se puede perder.

    `metafieldsSet` es todo o nada: sin el respaldo, un `theme.siblings` con el
    tipo equivocado dejaria al producto sin NINGUN metacampo -- que es
    exactamente el fallo de la seccion 9.
    """

    def test_un_metacampo_malo_no_se_lleva_a_los_demas(self):
        falso, ok, errores = self._correr(metacampos(12), rechaza={"campo_3"})
        self.assertEqual(ok, 11)
        self.assertEqual(len(errores), 1)
        self.assertNotIn("campo_3", [k for _, k, _, _ in falso.escritos])
        self.assertEqual(len(falso.escritos), 11)

    def test_el_error_NOMBRA_el_metacampo(self):
        """"Error metafields" a secas obliga a adivinar cual de los 26 es."""
        _, _, errores = self._correr(metacampos(12), rechaza={"campo_3"})
        self.assertTrue(errores[0].startswith("custom.campo_3: "), errores)

    def test_el_reintento_es_uno_POR_UNO(self):
        falso, _, _ = self._correr(metacampos(6), rechaza={"campo_2"})
        self.assertEqual(len(falso.llamadas[0]), 6, "el primer intento tiene que ser el lote")
        self.assertTrue(all(len(l) == 1 for l in falso.llamadas[1:]))
        self.assertEqual(len(falso.llamadas), 7)

    def test_dos_malos_se_reportan_los_dos(self):
        _, ok, errores = self._correr(metacampos(6), rechaza={"campo_1", "campo_4"})
        self.assertEqual(ok, 4)
        self.assertEqual(len(errores), 2)

    def test_si_TODOS_fallan_no_se_escribe_nada_y_se_dicen_todos(self):
        falso, ok, errores = self._correr(
            metacampos(4), rechaza={f"campo_{i}" for i in range(4)})
        self.assertEqual((ok, falso.escritos), (0, []))
        self.assertEqual(len(errores), 4)

    def test_el_fallo_del_LOTE_no_ensucia_el_informe(self):
        """El error del lote no dice cual fallo, y el reintento va a nombrarlo.
        Anotarlo tambien llenaria la hoja de un mensaje que no se puede
        accionar."""
        _, _, errores = self._correr(metacampos(6), rechaza={"campo_2"})
        self.assertEqual(len(errores), 1, errores)


class TestLaCargaCompletaEscribeLoMISMO(unittest.TestCase):
    """La prueba que de verdad importa: la salida no cambia.

    Comparado contra la version anterior con 5 productos de 12 metacampos:
    **cero diferencias** en los 60 metacampos escritos (namespace, key, tipo y
    valor), en las otras 108 llamadas y en el resultado por producto. Lo unico
    que cambia es que las 60 llamadas a `metafields_set` son ahora 5.
    """

    PRODUCTO = {
        "id": "gid://shopify/Product/1",
        "options": [{"id": "gid://o/1", "name": "Talla",
                     "optionValues": [{"id": "gid://ov/1", "name": "40"}]}],
        "variants": {"nodes": [
            {"id": "gid://v/1", "sku": "SKU-1",
             "selectedOptions": [{"name": "Talla", "value": "40"}],
             "inventoryItem": {"id": "gid://ii/1", "sku": "SKU-1", "tracked": True}}]},
    }

    def _cargar(self, n_metacampos):
        import app_matrixify as app
        llamadas = {"metafields_set": 0, "total": 0}
        escritos = []

        def espia(nombre, dev=None):
            def _f(*a, **k):
                llamadas["total"] += 1
                if nombre == "metafields_set":
                    llamadas["metafields_set"] += 1
                    escritos.extend((m["namespace"], m["key"], m["value"]) for m in a[1])
                return dev() if callable(dev) else dev
            return _f

        parches = {k: espia(k, v) for k, v in {
            "product_update": lambda: {"id": "gid://shopify/Product/1"},
            "product_create": lambda: {"id": "gid://shopify/Product/1"},
            "publishable_publish": None, "metafields_set": lambda: [],
            "fetch_product_options_and_variants": lambda: dict(self.PRODUCTO),
            "product_variants_bulk_update": lambda: [],
            "product_variants_bulk_create": lambda: [],
            "product_variants_bulk_reorder": None, "inventory_item_update": None,
            "inventory_bulk_activate": None, "inventory_activate": None,
            "inventory_item_active_locations": lambda: [],
            "fetch_locations": lambda: [{"id": "gid://l/1"}],
            "product_create_media": lambda: [], "product_delete_media": None,
            "product_options_reorder": None,
            # Hace un viaje REAL a Shopify si no se simula: se me colo en la
            # primera medicion y contamino la cifra de CPU.
            "fetch_metafield_definition": lambda: {"type": {"name": "single_line_text_field"}},
        }.items()}
        previos = {k: getattr(app, k, None) for k in parches}
        for k, v in parches.items():
            setattr(app, k, v)
        fila = {"Handle": "z-1", "Title": "Z", "Body HTML": "<p>x</p>", "Vendor": "vansperu",
                "Type": "Zapatillas", "Tags": "a", "Status": "active", "Published": "TRUE",
                "Option1 Name": "Talla", "Option1 Value": "40", "Variant SKU": "S1",
                "Variant Price": "199", "ID": "gid://shopify/Product/1"}
        for i in range(n_metacampos):
            fila[f"Metafield: custom.campo_{i} [single_line_text_field]"] = f"v{i}"
        try:
            app.apply_full_product_updates(
                {"shop_domain": "x", "admin_access_token": "y"}, pd.DataFrame([fila]))
        finally:
            for k, v in previos.items():
                if v is not None:
                    setattr(app, k, v)
        return llamadas, escritos

    def test_doce_metacampos_son_UNA_llamada_y_no_doce(self):
        llamadas, escritos = self._cargar(12)
        self.assertEqual(llamadas["metafields_set"], 1)
        self.assertGreaterEqual(len(escritos), 12)

    def test_los_viajes_totales_bajan(self):
        """Medido antes del cambio: 12 metacampos costaban 32 viajes."""
        con_12, _ = self._cargar(12)
        con_3, _ = self._cargar(3)
        self.assertLessEqual(con_12["total"], 22, "el ahorro se perdio")
        # Y ya casi no escala con los metacampos, que era el problema.
        self.assertLessEqual(con_12["total"] - con_3["total"], 6)

    def test_ya_no_queda_un_metafields_set_por_metacampo(self):
        import app_matrixify as app
        fuente = inspect.getsource(app.apply_full_product_updates)
        self.assertNotIn("for metafield in metafields:", fuente)
        self.assertIn("_escribir_metafields_en_lote(", fuente)


if __name__ == "__main__":
    unittest.main(verbosity=2)
