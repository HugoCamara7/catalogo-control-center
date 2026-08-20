# -*- coding: utf-8 -*-
"""Pruebas de los metafields Nombre corto y Descripcion corta de Hush Puppies.

Los dos metafields ya existian en el registro, pero el dato que escribia la
marca no llegaba a Shopify por tres motivos:

1. **Las columnas no estaban en el input de Hush Puppies.** El validador arma
   la fila normalizada solo con `commercial_input_columns_for_brand`, asi que
   una columna que no este ahi no se lee, no se valida y no se ve en la vista
   previa.

2. **"Descripcion corta" era alias de Caracteristicas.** Estaba en la lista
   `features` de catalog_rules y en `FEATURE_COLUMNS` del motor: la frase de la
   PLP se publicaba como bullets del Body HTML y el metafield salia vacio.

3. **Una columna vacia se rellenaba con la descripcion larga.** Se resolvia con
   `row_first_existing`, que devuelve el primer valor no vacio de la lista, y
   la lista terminaba en "Descripcion". La PLP mostraba el parrafo entero.

Ejecutar:  python scripts/test_hush_nombre_descripcion_corta.py
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
import catalog_rules  # noqa: E402
import generate_columbia_matrixify as g  # noqa: E402
from engines import catalog_map  # noqa: E402

MARCAS_HP = ["Hush Puppies", "Hush Puppies Kids", "Accesorios HP"]


class TestColumnasDelInput(unittest.TestCase):
    def test_las_marcas_hush_puppies_declaran_las_dos_columnas(self):
        for marca in MARCAS_HP:
            columnas = app.commercial_input_columns_for_brand(marca)
            self.assertIn("Nombre corto", columnas, marca)
            self.assertIn("Descripcion corta", columnas, marca)

    def test_las_demas_marcas_no_cambian(self):
        """Solo Hush Puppies las envia; el resto sigue igual que antes."""
        for marca in ["Columbia", "Vans", "Patagonia", "Rockford"]:
            columnas = app.commercial_input_columns_for_brand(marca)
            self.assertNotIn("Nombre corto", columnas, marca)
            self.assertNotIn("Descripcion corta", columnas, marca)

    def test_la_plantilla_en_blanco_las_trae(self):
        df = app._commercial_input_blank_df("Hush Puppies", rows=2)
        self.assertIn("Nombre corto", df.columns)
        self.assertIn("Descripcion corta", df.columns)


class TestDiccionarioDeLaPlantilla(unittest.TestCase):
    def test_el_diccionario_dice_a_que_metafield_van(self):
        filas = app._commercial_dictionary_rows("Hush Puppies")
        por_columna = {fila["Nombre exacto"]: fila for fila in filas.to_dict("records")}
        self.assertEqual(por_columna["Nombre corto"]["Campo de Shopify"], "custom.nombre_corto")
        self.assertEqual(por_columna["Descripcion corta"]["Campo de Shopify"], "custom.descripcion_corta")
        self.assertEqual(por_columna["Nombre corto"]["Key"], "nombre_corto")
        self.assertEqual(por_columna["Descripcion corta"]["Namespace"], "custom")

    def test_no_bloquean_la_carga_si_vienen_vacias(self):
        """Se cargan siempre que vengan informadas; vacias no borran Shopify."""
        filas = app._commercial_dictionary_rows("Hush Puppies").to_dict("records")
        por_columna = {fila["Nombre exacto"]: fila for fila in filas}
        for columna in ["Nombre corto", "Descripcion corta"]:
            self.assertEqual(por_columna[columna]["Obligatorio"], "NO", columna)
            self.assertIn("No actualiza", por_columna[columna]["Comportamiento si esta vacio"])

    def test_la_hoja_de_metafields_deja_de_decir_que_los_deriva_la_app(self):
        filas = app.commercial_input_metafields_for_brand("Hush Puppies").to_dict("records")
        por_key = {fila["Key"]: fila for fila in filas}
        self.assertEqual(por_key["nombre_corto"]["Aparece en input"], "SI")
        self.assertEqual(por_key["descripcion_corta"]["Aparece en input"], "SI")
        self.assertIn("del input", por_key["nombre_corto"]["Regla"])

    def test_para_una_marca_que_no_los_envia_sigue_diciendo_que_los_deriva(self):
        filas = app.commercial_input_metafields_for_brand("Columbia").to_dict("records")
        por_key = {fila["Key"]: fila for fila in filas}
        self.assertEqual(por_key["nombre_corto"]["Aparece en input"], "NO")
        self.assertIn("deriva", por_key["nombre_corto"]["Regla"])


class TestNoSeConfundenConOtrosCampos(unittest.TestCase):
    def test_descripcion_corta_ya_no_es_alias_de_caracteristicas(self):
        """Regresion 2: la frase de PLP se publicaba como bullets."""
        alias = {valor.casefold() for valor in catalog_rules.CATALOG_FIELD_ALIASES["features"]}
        self.assertNotIn("descripcion corta", alias)
        self.assertNotIn("descripción corta", alias)

    def test_catalog_rules_les_da_entrada_propia(self):
        self.assertIn("short_description", catalog_rules.CATALOG_FIELD_ALIASES)
        self.assertIn("short_name", catalog_rules.CATALOG_FIELD_ALIASES)

    def test_el_motor_no_mete_la_descripcion_corta_en_los_bullets(self):
        columnas = {valor.casefold() for valor in g.FEATURE_COLUMNS}
        self.assertNotIn(
            "metafield: custom.descripcion_corta [single_line_text_field]", columnas
        )

    def test_el_nombre_de_producto_le_gana_al_nombre_corto_en_el_title(self):
        indice = {valor: posicion for posicion, valor in enumerate(g.TITLE_COLUMNS)}
        self.assertLess(indice["Nombre de Producto"], indice["Nombre corto"])


class TestValorQueLlegaAShopify(unittest.TestCase):
    def fila(self, **valores):
        base = {"Mod-Col": "HP1234567-001",
                "Nombre de Producto": "Zapatilla Urbana Mujer Modelo X",
                "Descripcion": "Parrafo largo de la ficha comercial del producto."}
        base.update(valores)
        return pd.Series(base)

    def test_manda_lo_que_escribe_la_marca(self):
        fila = self.fila(**{"Nombre corto": "Zapatilla Urbana",
                            "Descripcion corta": "Suela flexible."})
        self.assertEqual(
            g.short_text_metafield(fila, g.SHORT_NAME_COLUMNS, ["Nombre de Producto"]),
            "Zapatilla Urbana",
        )
        self.assertEqual(
            g.short_text_metafield(fila, g.SHORT_DESCRIPTION_COLUMNS, ["Descripcion"]),
            "Suela flexible.",
        )

    def test_una_columna_vacia_no_se_rellena_con_la_descripcion_larga(self):
        """Regresion 3: la PLP terminaba mostrando el parrafo entero."""
        fila = self.fila(**{"Nombre corto": "", "Descripcion corta": ""})
        self.assertEqual(g.short_text_metafield(fila, g.SHORT_DESCRIPTION_COLUMNS, ["Descripcion"]), "")
        self.assertEqual(g.short_text_metafield(fila, g.SHORT_NAME_COLUMNS, ["Nombre de Producto"]), "")

    def test_sin_la_columna_se_sigue_derivando_como_siempre(self):
        """Las marcas que no envian estos campos no cambian de comportamiento."""
        fila = self.fila()
        self.assertEqual(
            g.short_text_metafield(fila, g.SHORT_NAME_COLUMNS, ["Nombre de Producto"]),
            "Zapatilla Urbana Mujer Modelo X",
        )

    def test_acepta_la_columna_con_tilde_y_mayuscula(self):
        fila = self.fila(**{"Descripción Corta": "Con tilde."})
        self.assertEqual(
            g.short_text_metafield(fila, g.SHORT_DESCRIPTION_COLUMNS, ["Descripcion"]),
            "Con tilde.",
        )


class TestCargaPorApiDirecta(unittest.TestCase):
    def test_los_dos_metafields_salen_por_la_api(self):
        metafields = catalog_map.build_metafields(
            {"Mod-Col": "HP1234567-001",
             "Nombre corto": "Zapatilla Urbana",
             "Descripción Corta": "Suela flexible."},
            "hush_puppies",
        )
        por_key = {item["key"]: item for item in metafields}
        self.assertEqual(por_key["nombre_corto"]["value"], "Zapatilla Urbana")
        self.assertEqual(por_key["descripcion_corta"]["value"], "Suela flexible.")
        self.assertTrue(por_key["nombre_corto"]["escribible_por_api"])
        self.assertEqual(por_key["descripcion_corta"]["type"], catalog_map.TEXTO)


if __name__ == "__main__":
    unittest.main(verbosity=2)
