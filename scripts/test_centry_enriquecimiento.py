# -*- coding: utf-8 -*-
"""Pruebas del enriquecimiento y la validacion del Centry.

Causa raiz: el indice del maestro SIAL/BigQuery se quedaba con CUATRO campos
(codigo de barras, talla, talla normalizada y color) y tiraba el resto. El ARTI
trae ademas NombreModelo, DescripcionWeb, Caracteristicas, Material, Cuidado,
TipoProducto, Categoria, SubCategoria, Genero, Temporada, Tecnologia, Coleccion,
Ocasion y Deporte. Por eso el Centry salia con Nombre, Descripcion, Genero,
Tipo, Materiales, Cuidados y Temporada vacios aunque el dato existiera.

Ademas, cuando el producto no estaba en Shopify, el nombre caia al codigo
modelo-color y Centry lo publicaba asi, teniendo `NombreModelo` a mano.

Aqui se comprueba:
  - el indice conserva el registro completo del maestro;
  - la etapa unica de enriquecimiento rellena SOLO lo que Shopify no trae;
  - el nombre nunca es el codigo modelo-color;
  - la validacion marca los campos vacios y los valores fuera de plantilla.

Ejecutar:  python scripts/test_centry_enriquecimiento.py
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

COD = "HP333333333-CCC"
CONFIG_HP = g.get_brand_config("hush_puppies")


def maestro_completo(sku="9001", talla="37", mod_col=COD, **extra):
    fila = {
        "CODINT_MA": sku,
        "COD MOD COL": mod_col,
        "TALNUM_MA": talla,
        "MARCA_MA": "HUSH PUPPIES",
        "CodBarras": "7798722222221",
        "ColorNombre": "Camel",
        "Precio": "179.90",
        "NombreModelo": "Botin Chelsea Mujer",
        "DescripcionWeb": "Botin chelsea de cuero.",
        "Caracteristicas": "Elastico lateral",
        "Material": "Cuero",
        "Cuidado": "Pano humedo",
        "TipoProducto": "Botines",
        "Categoria": "Calzado",
        "SubCategoria": "Botines",
        "Genero": "FEMENINO",
        "Temporada": "Otono",
    }
    fila.update(extra)
    return fila


def fila_matrixify(**valores):
    base = {columna: "" for columna in app.MATRIXIFY_COLUMNS}
    base.update(valores)
    return base


class TestIndiceDelMaestro(unittest.TestCase):
    def test_guarda_el_registro_completo(self):
        """Regresion: el indice se quedaba con cuatro campos y tiraba el resto."""
        lookup = app.build_centry_arti_lookup(pd.DataFrame([maestro_completo()]))
        maestro = lookup["by_sku"]["9001"]["maestro"]
        self.assertEqual(maestro["NombreModelo"], "Botin Chelsea Mujer")
        self.assertEqual(maestro["Genero"], "FEMENINO")
        self.assertEqual(maestro["TipoProducto"], "Botines")
        self.assertEqual(maestro["Cuidado"], "Pano humedo")
        self.assertEqual(maestro["Temporada"], "Otono")

    def test_completa_campo_a_campo_entre_filas_del_mismo_sku(self):
        """El maestro trae una fila por bodega: una puede tener el nombre y
        otra la descripcion. Ninguna de las dos puede tapar a la otra."""
        arti = pd.DataFrame([
            maestro_completo(NombreModelo="Botin Chelsea Mujer", DescripcionWeb=""),
            maestro_completo(NombreModelo="", DescripcionWeb="Botin chelsea de cuero."),
        ])
        maestro = app.build_centry_arti_lookup(arti)["by_sku"]["9001"]["maestro"]
        self.assertEqual(maestro["NombreModelo"], "Botin Chelsea Mujer")
        self.assertEqual(maestro["DescripcionWeb"], "Botin chelsea de cuero.")


class TestEtapaDeEnriquecimiento(unittest.TestCase):
    def test_rellena_lo_que_shopify_no_trae(self):
        fila = pd.Series(fila_matrixify(Handle="botin", **{"Variant SKU": "9001"}))
        maestro = app.build_centry_arti_lookup(
            pd.DataFrame([maestro_completo()])
        )["by_sku"]["9001"]["maestro"]
        fila, completados = app.centry_enriquecer_fila(fila, maestro)
        self.assertEqual(fila["Title"], "Botin Chelsea Mujer")
        self.assertEqual(fila["Body HTML"], "Botin chelsea de cuero.")
        self.assertEqual(fila["Type"], "Botines")
        self.assertEqual(fila["Genero"], "FEMENINO")
        self.assertEqual(fila["Cuidados"], "Pano humedo")
        self.assertEqual(fila["Temporada"], "Otono")
        self.assertTrue(completados)

    def test_shopify_manda_siempre(self):
        """El maestro es el respaldo, no el jefe. Un dato de Shopify no se pisa."""
        fila = pd.Series(fila_matrixify(
            Handle="botin", Title="Botin Mujer Hush Puppies", Type="Botas",
            **{"Variant SKU": "9001",
               "Metafield: custom.genero [single_line_text_field]": "Unisex"},
        ))
        maestro = app.build_centry_arti_lookup(
            pd.DataFrame([maestro_completo()])
        )["by_sku"]["9001"]["maestro"]
        fila, _ = app.centry_enriquecer_fila(fila, maestro)
        self.assertEqual(fila["Title"], "Botin Mujer Hush Puppies")
        self.assertEqual(fila["Type"], "Botas")
        self.assertEqual(fila["Metafield: custom.genero [single_line_text_field]"], "Unisex")

    def test_los_textos_cortos_de_hush_puppies_valen_como_nombre_y_descripcion(self):
        """Si el producto no tiene Title ni Body, `custom.nombre_corto` y
        `custom.descripcion_corta` son datos reales de la marca."""
        fila = pd.Series(fila_matrixify(**{
            "Variant SKU": "9001",
            "Metafield: custom.nombre_corto [single_line_text_field]": "Botin Chelsea",
            "Metafield: custom.descripcion_corta [single_line_text_field]": "Cuero y elastico.",
        }))
        fila, _ = app.centry_enriquecer_fila(fila, {})
        self.assertEqual(fila["Title"], "Botin Chelsea")
        self.assertEqual(fila["Body HTML"], "Cuero y elastico.")

    def test_sin_maestro_no_revienta(self):
        fila = pd.Series(fila_matrixify(Title="Botin"))
        fila, completados = app.centry_enriquecer_fila(fila, {})
        self.assertEqual(fila["Title"], "Botin")
        self.assertEqual(completados, [])

    def test_el_tipo_cae_a_la_subcategoria_solo_si_el_diccionario_la_reconoce(self):
        fila = pd.Series(fila_matrixify(**{"Variant SKU": "9001"}))
        fila, _ = app.centry_enriquecer_fila(
            fila, {"TipoProducto": "", "SubCategoria": "Botines"}
        )
        self.assertEqual(fila["Type"], "Botines")

        otra = pd.Series(fila_matrixify(**{"Variant SKU": "9001"}))
        otra, _ = app.centry_enriquecer_fila(
            otra, {"TipoProducto": "", "SubCategoria": "Texto libre inventado"}
        )
        self.assertEqual(otra["Type"], "")


class TestCentryCompletoDeExtremoAExtremo(unittest.TestCase):
    """El export de Shopify tiene huecos y el maestro los rellena."""

    def setUp(self):
        self.matrixify = pd.DataFrame([
            fila_matrixify(**{
                "Handle": "botin-mujer",
                "Title": "Botin Mujer Hush Puppies",
                "Vendor": "Hush Puppies",
                "Variant SKU": "0009001",
                "Option1 Value": "37",
                "Metafield: custom.codigo_modelo_color [id]": COD,
            }),
            fila_matrixify(**{
                "Handle": "botin-mujer",
                "Variant SKU": "0009002",
                "Option1 Value": "38",
                "Metafield: custom.codigo_modelo_color [id]": COD,
            }),
        ])
        self.arti = pd.DataFrame([
            maestro_completo(sku="9001", talla="37"),
            maestro_completo(sku="9002", talla="38", CodBarras="7798722222222"),
        ])

    def test_no_queda_ningun_campo_clave_vacio(self):
        centry, _ = app.build_centry_from_matrixify(
            self.matrixify, CONFIG_HP, arti_df=self.arti
        )
        self.assertEqual(len(centry), 2)
        for _, fila in centry.iterrows():
            for columna in ["Nombre del Producto", "Descripcion", "Género", "Categoría",
                            "Talla", "Color", "Precio", "SKU de la variante",
                            "Código de barra variante (EAN/UPC/ISBN)"]:
                self.assertTrue(str(fila.get(columna)).strip(), f"{columna} vacio")

    def test_el_ean_se_resuelve_con_el_sku_del_maestro_sin_ceros(self):
        """Shopify tiene 0009001 y el maestro 9001: antes no emparejaban."""
        centry, _ = app.build_centry_from_matrixify(
            self.matrixify, CONFIG_HP, arti_df=self.arti
        )
        eans = list(centry["Código de barra variante (EAN/UPC/ISBN)"])
        self.assertEqual(eans, ["7798722222221", "7798722222222"])

    def test_la_temporada_sale_del_maestro_y_no_verano_fijo(self):
        centry, _ = app.build_centry_from_matrixify(
            self.matrixify, CONFIG_HP, arti_df=self.arti
        )
        self.assertEqual(set(centry["Temporada"]), {"Otono"})

    def test_materiales_composicion_y_cuidados_llegan_al_listado(self):
        centry, _ = app.build_centry_from_matrixify(
            self.matrixify, CONFIG_HP, arti_df=self.arti
        )
        listado = str(centry.iloc[0].get("Listado de características"))
        for etiqueta in ["Material", "Composición", "Cuidados"]:
            self.assertIn(etiqueta, listado)

    def test_el_resumen_dice_que_completo_el_maestro(self):
        _, issues = app.build_centry_from_matrixify(
            self.matrixify, CONFIG_HP, arti_df=self.arti
        )
        textos = " ".join(str(v) for v in issues["Problema"])
        self.assertIn("Campos completados desde el maestro", textos)


class TestNombreNuncaEsElCodigo(unittest.TestCase):
    def test_sin_producto_en_shopify_usa_el_nombre_del_maestro(self):
        inter, _ = app.build_centry_matrixify_from_master(
            [COD], pd.DataFrame(), pd.DataFrame([maestro_completo()]), CONFIG_HP
        )
        self.assertEqual(list(inter["Title"])[0], "Botin Chelsea Mujer")

    def test_sin_nombre_en_ninguna_fuente_queda_vacio_y_avisa(self):
        """Regresion: Centry publicaba el codigo modelo-color como nombre."""
        maestro = maestro_completo(NombreModelo="")
        inter, issues = app.build_centry_matrixify_from_master(
            [COD], pd.DataFrame(), pd.DataFrame([maestro]), CONFIG_HP
        )
        self.assertEqual(list(inter["Title"])[0], "")
        textos = " ".join(str(v) for v in issues["Problema"])
        self.assertIn("Sin nombre de producto", textos)


class TestValidacionDelCentry(unittest.TestCase):
    def _centry(self, **valores):
        base = {columna: "" for columna in app.CENTRY_COLUMNS}
        base.update({
            "SKU del producto": COD,
            "SKU de la variante": "9001",
            "Código de barra variante (EAN/UPC/ISBN)": "7798722222221",
            "Nombre del Producto": "Botin Chelsea Mujer",
            "Descripcion": "Botin chelsea de cuero.",
            "Género": "Femenino",
            "Categoría": "Calzados / Calzados Femeninos / Botines",
            "Clase": "Calzado",
            "Talla": "37",
            "Color": "Camel",
            "Marca": "Hush Puppies",
            "Listado de características": "Material : Cuero |Composición : Cuero |Cuidados : Pano humedo",
        })
        base.update(valores)
        return pd.DataFrame([base])

    def test_una_fila_completa_no_da_hallazgos(self):
        val = app.centry_validar_salida(self._centry())
        self.assertTrue(val.empty, val.to_dict("records"))

    def test_marca_los_campos_obligatorios_vacios(self):
        val = app.centry_validar_salida(self._centry(**{
            "Código de barra variante (EAN/UPC/ISBN)": "",
            "Género": "",
            "Descripcion": "",
        }))
        campos = set(val["Campo"])
        self.assertIn("Código de barra variante (EAN/UPC/ISBN)", campos)
        self.assertIn("Género", campos)
        self.assertIn("Descripcion", campos)
        self.assertTrue((val["Severidad"] == "Bloqueante").all())

    def test_marca_el_nombre_que_es_el_codigo(self):
        val = app.centry_validar_salida(self._centry(**{"Nombre del Producto": COD}))
        self.assertIn("El nombre es el codigo modelo-color", set(val["Problema"]))

    def test_marca_materiales_composicion_y_cuidados_faltantes(self):
        val = app.centry_validar_salida(self._centry(**{"Listado de características": ""}))
        campos = set(val["Campo"])
        self.assertEqual({"Material", "Composicion", "Cuidados"} & campos,
                         {"Material", "Composicion", "Cuidados"})
        faltantes = val[val["Campo"].isin(["Material", "Composicion", "Cuidados"])]
        self.assertTrue((faltantes["Severidad"] == "Advertencia").all())

    def test_una_linea_por_producto_y_no_por_variante(self):
        """80 tallas sin EAN son un problema, no ochenta."""
        filas = pd.concat([self._centry(**{
            "SKU de la variante": str(9000 + i),
            "Código de barra variante (EAN/UPC/ISBN)": "",
        }) for i in range(80)], ignore_index=True)
        val = app.centry_validar_salida(filas)
        ean = val[val["Campo"] == "Código de barra variante (EAN/UPC/ISBN)"]
        self.assertEqual(len(ean), 1)
        self.assertEqual(safe := int(ean.iloc[0]["Variantes"]), 80)

    def test_el_centry_generado_trae_su_validacion_pegada(self):
        centry, _ = app.build_centry_from_matrixify(
            pd.DataFrame([fila_matrixify(**{
                "Handle": "botin-mujer", "Title": "Botin", "Vendor": "Hush Puppies",
                "Variant SKU": "9001", "Option1 Value": "37",
                "Metafield: custom.codigo_modelo_color [id]": COD,
            })]),
            CONFIG_HP,
        )
        self.assertIn("validacion", centry.attrs)
        self.assertIsInstance(centry.attrs["validacion"], pd.DataFrame)


class TestListadoDeCaracteristicas(unittest.TestCase):
    def test_reconoce_la_etiqueta_con_y_sin_tilde(self):
        listado = "Material : Cuero |Composición : Cuero |Cuidados : Pano humedo"
        self.assertTrue(app.centry_listado_tiene(listado, "Material"))
        self.assertTrue(app.centry_listado_tiene(listado, "Composición"))
        self.assertTrue(app.centry_listado_tiene(listado, "Composicion"))

    def test_una_etiqueta_sin_valor_no_cuenta(self):
        self.assertFalse(app.centry_listado_tiene("Material : |Color : Negro", "Material"))

    def test_listado_vacio(self):
        self.assertFalse(app.centry_listado_tiene("", "Material"))


if __name__ == "__main__":
    unittest.main(verbosity=2)
