"""Pruebas de resolve_product_type — el tipo lo manda el brand.

El fallo que fijan: TYPE_COLUMNS mezclaba "Type"/"Product Type" ANTES de
"Tipo de prenda", y ademas metia "Categoria" en la misma lista. Como
row_alias_value() devuelve el primer alias no vacio, Patagonia cargado en
Rockford salia como "Outdoor", que es su CATEGORIA, no una prenda.
"""
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import pandas as pd
from generate_columbia_matrixify import (
    TYPE_COLUMNS,
    TYPE_FALLBACK_COLUMNS,
    resolve_product_type,
)


def tipo(fila):
    return resolve_product_type(pd.Series(fila))


class TestElBrandManda(unittest.TestCase):
    def test_patagonia_en_rockford_no_sale_outdoor(self):
        """El caso reportado: la categoria Outdoor ganaba al tipo de prenda."""
        valor, origen = tipo({"Tipo de prenda": "Chaquetas", "Categoria": "Outdoor",
                              "Marca": "Patagonia"})
        self.assertEqual(valor, "Chaquetas")
        self.assertEqual(origen, "input")

    def test_type_heredado_no_gana(self):
        """Una columna Type de un Matrixify reexportado no pisa al brand."""
        valor, origen = tipo({"Type": "Outdoor", "Tipo de prenda": "Poleras"})
        self.assertEqual(valor, "Poleras")
        self.assertEqual(origen, "input")

    def test_product_type_tampoco_gana(self):
        self.assertEqual(tipo({"Product Type": "Outdoor", "Tipo de prenda": "Polerones"})[0],
                         "Polerones")

    def test_alias_del_input(self):
        for alias in ("Tipo de prenda", "Tipo de Prenda", "Tipo prenda", "Tipo"):
            self.assertEqual(tipo({alias: "Chalecos"}), ("Chalecos", "input"), alias)

    def test_el_metafield_tambien_vale(self):
        valor, origen = tipo({"Metafield: custom.tipo [single_line_text_field]": "Sweaters"})
        self.assertEqual((valor, origen), ("Sweaters", "input"))


class TestLaCategoriaEsLaClaseNoElTipo(unittest.TestCase):
    """Categoria = clase. Subcategoria = tipo de prenda. En los cuatro sitios."""

    def test_la_subcategoria_es_el_tipo_de_prenda(self):
        self.assertEqual(tipo({"Categoria": "Vestuario", "Subcategoria": "Chalecos"}),
                         ("Chalecos", "input"))

    def test_patagonia_con_subcategoria(self):
        self.assertEqual(tipo({"Categoria": "Outdoor", "Subcategoria": "Chaquetas"})[0],
                         "Chaquetas")

    def test_la_categoria_nunca_es_el_tipo(self):
        """Sin tipo se devuelve vacio: mejor avisar que publicar 'Outdoor'."""
        self.assertEqual(tipo({"Categoria": "Outdoor"}), ("", ""))
        self.assertEqual(tipo({"Categoria": "Vestuario"}), ("", ""))

    def test_la_categoria_no_esta_en_ninguna_lista(self):
        for columna in ("Categoria", "Categoría", "Category"):
            self.assertNotIn(columna, TYPE_COLUMNS, columna)
            self.assertNotIn(columna, TYPE_FALLBACK_COLUMNS, columna)

    def test_la_subcategoria_si_esta_y_antes_que_type(self):
        self.assertLess(TYPE_COLUMNS.index("Subcategoria"), TYPE_COLUMNS.index("Type"))

    def test_la_clase_se_deriva_del_tipo(self):
        import catalog_rules
        self.assertEqual(catalog_rules.normalize_product_type("Chalecos")["category"], "Vestuario")
        self.assertEqual(catalog_rules.normalize_product_type("Zapatillas")["category"], "Calzado")
        self.assertIsNone(catalog_rules.normalize_product_type("Outdoor"),
                          "Outdoor es una clase, no una prenda")

    def test_type_va_despues_del_tipo_de_prenda(self):
        self.assertLess(TYPE_COLUMNS.index("Tipo de prenda"), TYPE_COLUMNS.index("Type"))
        self.assertLess(TYPE_COLUMNS.index("Tipo de prenda"), TYPE_COLUMNS.index("Product Type"))


class TestBordes(unittest.TestCase):
    def test_sin_nada(self):
        self.assertEqual(tipo({}), ("", ""))

    def test_vacios_no_cuentan(self):
        self.assertEqual(tipo({"Tipo de prenda": "  ", "Subcategoria": "Chalecos"}),
                         ("Chalecos", "input"))


if __name__ == "__main__":
    unittest.main(verbosity=2)
