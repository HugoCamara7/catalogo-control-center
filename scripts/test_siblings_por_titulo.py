"""Los siblings de Vans salen por el TITULO, no por el codigo de modelo.

Ejecutar:  python scripts/test_siblings_por_titulo.py

Reportado por el usuario: "los siblings estan jalando mal, en el caso de vans
los codigos son todos diferentes entonces tenemos que buscar segun el nombre
del producto"; y a continuacion, "en las otras marcas es solo si son iguales
los codigos modelo, o sea el valor antes del guion donde comienza el codigo
color".

Medido sobre `data/arti.zip` (653.431 filas) antes de tocar nada:

    marca           mod-col   modelos   modelos con UN SOLO color
    VANS              1.616     1.255     1.132  (90,2 %)
    COLUMBIA         19.055     5.395     1.497  (27,7 %)

O sea que nueve de cada diez productos de Vans se quedaban sin un solo hermano.

Las pruebas EJECUTAN las cinco superficies que agrupan hermanos -- no leen su
codigo: es la leccion de `start_suelto`, que tenia ocho pruebas leyendo su
fuente y ninguna la llamaba.
"""
import ast
import inspect
import textwrap
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pandas as pd  # noqa: E402

import app_matrixify as app  # noqa: E402
import generate_columbia_matrixify as g  # noqa: E402

VANS = g.get_brand_config("vans")
COLUMBIA = g.get_brand_config("columbia")
SUPERMALL = g.get_brand_config("supermall")

SIBLINGS = "Metafield: theme.siblings [single_line_text_field]"
CUSTOM_SIBLINGS = "Metafield: custom.siblings [single_line_text_field]"
CLAVE = "Metafield: custom.codigo_modelo_color [id]"
MARCA = "Metafield: custom.marca [single_line_text_field]"

# Codigos REALES del maestro. En Vans el codigo cambia entero de un color a
# otro: `VN-018BGIC-BIV` y `VN-018BGIE-GB8` no comparten ni el modelo.
OLD_SKOOL = {"VN-018BGIC-BIV": "Zapatilla Old Skool", "VN-018BGIE-GB8": "Zapatilla Old Skool"}
SK8 = {"VN-018BGXP-KGB": "Zapatilla Sk8-Hi", "VN-018BGYU-SB1": "Zapatilla Sk8-Hi"}
# En Columbia el mismo titulo puede estar en dos modelos distintos: medido en el
# catalogo real (2.401 productos), 72 titulos abarcan mas de un modelo.
POWDER = {"AB1234-010": "Casaca Powder Lite", "AB1234-011": "Casaca Powder Lite",
          "ZZ9999-010": "Casaca Powder Lite"}


def entrada(codigos, marca):
    return pd.DataFrame([{
        "Mod-Col": codigo, "Marca": marca, "Genero": "HOMBRE", "Clase": "Calzado",
        "Tipo de prenda": "ZAPATILLA", "Color web/filtro": "NEGRO",
        "Nombre de Producto": titulo, "Descripcion": "Texto.",
    } for codigo, titulo in codigos.items()])


def maestro(codigos, marca):
    return pd.DataFrame([{
        "Mod-Col": codigo, "COD MOD COL": codigo, "CODINT_MA": f"SKU{i}",
        "TALNUM_MA": "390", "MARCA_MA": marca, "Precio": "100", "CodBarras": "",
        "NombreModelo": titulo, "TipoProducto": "ZAPATILLA", "Genero": "HOMBRE",
        "ColorNombre": "NEGRO",
    } for i, (codigo, titulo) in enumerate(codigos.items(), 1)])


def hermanos_de(matrixify_df, columna=SIBLINGS):
    """`{handle: [hermanos]}` leyendo SOLO la fila de producto.

    Matrixify repite el handle en cada fila de variante y deja los campos de
    producto vacios en las de abajo: quedarse con la ultima fila de un handle
    devuelve la vacia, no el valor.
    """
    salida = {}
    for _, fila in matrixify_df.iterrows():
        handle = g.clean(fila.get("Handle"))
        valor = g.clean(fila.get(columna))
        if handle and valor and handle not in salida:
            salida[handle] = [h for h in (x.strip() for x in valor.split(",")) if h]
    return salida


def carga_completa(codigos, brand_config, marca, catalogo=None):
    return g.build_columbia_matrixify(
        entrada(codigos, marca), maestro(codigos, marca),
        catalogo if catalogo is not None else pd.DataFrame(columns=["Handle"]),
        brand_config)[0]


def por_codigos(codigos, brand_config, marca):
    mx, _ = app.build_centry_matrixify_from_master(
        list(codigos), pd.DataFrame(), maestro(codigos, marca), brand_config)
    return mx


def producto_shopify(mod_col, handle, title, marca):
    return {"Mod-Col": mod_col, "Handle": handle, "Title": title, "Marca": marca,
            "Product ID": f"gid://shopify/Product/{handle}",
            "Siblings": "", "Custom Siblings": ""}


def catalogo_matrixify(productos):
    return pd.DataFrame([{
        "Handle": p["Handle"], "Title": p["Title"], "ID": p["Product ID"],
        CLAVE: p["Mod-Col"], MARCA: p["Marca"],
    } for p in productos])


class TestLaRegla(unittest.TestCase):
    """`clave_de_siblings` es la UNICA regla, y la llaman las cinco superficies."""

    def test_vans_agrupa_por_titulo(self):
        primera = g.clave_de_siblings("VN-018BGIC-BIV", "Zapatilla Old Skool", "VANS")
        segunda = g.clave_de_siblings("VN-018BGIE-GB8", "Zapatilla Old Skool", "Vans")
        self.assertEqual(primera, segunda)
        self.assertTrue(primera.startswith(g.PREFIJO_SIBLINGS_POR_TITULO))

    def test_las_demas_marcas_siguen_por_codigo_de_modelo(self):
        """El valor ANTES del guion donde empieza el codigo de color."""
        for marca in ("COLUMBIA", "ROCKFORD", "HUSH PUPPIES", "SOREL", "KEDS", ""):
            self.assertEqual(
                g.clave_de_siblings("AB1234-010", "Casaca Powder Lite", marca), "AB1234", marca)
            self.assertEqual(
                g.clave_de_siblings("AB1234-011", "Casaca Powder Lite", marca), "AB1234", marca)
            self.assertNotEqual(
                g.clave_de_siblings("ZZ9999-010", "Casaca Powder Lite", marca), "AB1234", marca)

    def test_es_exactamente_model_code_donde_no_se_agrupa_por_titulo(self):
        """Lo que no es Vans tiene que dar EXACTAMENTE lo de siempre."""
        for codigo in ("AB1234-010", "HP202011180-244", "10001330-N11", "SINGUION",
                       "", "RK-11-1021393-176"):
            self.assertEqual(g.clave_de_siblings(codigo, "Un titulo", "COLUMBIA"),
                             g.model_code(codigo), codigo)

    def test_sin_titulo_Vans_cae_al_codigo_de_modelo(self):
        """Devolver vacio meteria a todos los productos sin nombre en el MISMO
        grupo: es el fallo de la cadena vacia de `clave_de_producto`."""
        self.assertEqual(g.clave_de_siblings("VN-018BGIC-BIV", "", "VANS"), "VN-018BGIC")
        self.assertEqual(g.clave_de_siblings("VN-018BGIC-BIV", None, "VANS"), "VN-018BGIC")

    def test_el_prefijo_impide_que_un_titulo_choque_con_un_codigo(self):
        """Sin prefijo, un titulo que se parezca a un codigo de modelo meteria
        dos productos distintos en el mismo grupo."""
        por_titulo = g.clave_de_siblings("VN-1-A", "AB1234", "VANS")
        por_modelo = g.clave_de_siblings("AB1234-010", "Otro", "COLUMBIA")
        self.assertNotEqual(por_titulo, por_modelo)

    def test_el_titulo_se_normaliza(self):
        """Acentos, mayusculas y el simbolo de marca registrada no separan a dos
        colores del mismo producto."""
        self.assertEqual(
            g.clave_de_siblings("VN-1-A", "Zapatilla Ántrax™", "VANS"),
            g.clave_de_siblings("VN-2-B", "zapatilla antrax", "VANS"))

    def test_la_marca_sale_de_la_fila_y_si_no_del_sitio_de_una_sola_marca(self):
        self.assertEqual(g.marca_para_siblings("Vans", COLUMBIA), "Vans")
        # Vans.pe lleva UNA marca: un producto sin `custom.marca` es Vans igual.
        self.assertEqual(g.marca_para_siblings("", VANS), "VANS")
        # Supermall lleva diez: ahi no hay UNA respuesta y no se adivina.
        self.assertEqual(g.marca_para_siblings("", SUPERMALL), "")
        self.assertEqual(g.marca_para_siblings("", None), "")


class TestCargaCompleta(unittest.TestCase):

    def test_vans_dos_colores_con_codigos_distintos_quedan_hermanos(self):
        mx = carga_completa(OLD_SKOOL, VANS, "Vans")
        hermanos = hermanos_de(mx)
        self.assertEqual(len(hermanos), 2)
        for handle, lista in hermanos.items():
            self.assertEqual(len(lista), 2, handle)
            self.assertEqual(sorted(lista), sorted(hermanos))

    def test_vans_no_mezcla_dos_productos_distintos(self):
        codigos = dict(OLD_SKOOL)
        codigos.update(SK8)
        hermanos = hermanos_de(carga_completa(codigos, VANS, "Vans"))
        self.assertEqual(len(hermanos), 4)
        for handle, lista in hermanos.items():
            self.assertEqual(len(lista), 2, handle)
            esperado = "old-skool" if "old-skool" in handle else "sk8-hi"
            for hermano in lista:
                self.assertIn(esperado, hermano)

    def test_columbia_NO_se_agrupa_por_titulo(self):
        """Medido en el catalogo real: 72 titulos abarcan mas de un modelo."""
        hermanos = hermanos_de(carga_completa(POWDER, COLUMBIA, "Columbia"))
        self.assertEqual(len(hermanos["casaca-powder-lite-ab1234-010-negro"]), 2)
        self.assertEqual(len(hermanos["casaca-powder-lite-ab1234-011-negro"]), 2)
        self.assertEqual(len(hermanos["casaca-powder-lite-zz9999-010-negro"]), 1)

    def test_en_SUPERMALL_conviven_las_dos_reglas(self):
        """Supermall lleva todas las marcas: con una bandera de SITIO, una sola
        carga agruparia por titulo tambien a Columbia."""
        self.assertEqual(
            len(hermanos_de(carga_completa(OLD_SKOOL, SUPERMALL, "Vans"))[
                "zapatilla-old-skool-vn-018bgic-biv-negro"]), 2)
        hermanos = hermanos_de(carga_completa(POWDER, SUPERMALL, "Columbia"))
        self.assertEqual(len(hermanos["casaca-powder-lite-zz9999-010-negro"]), 1)

    def test_theme_y_custom_siblings_dicen_lo_MISMO(self):
        mx = carga_completa(OLD_SKOOL, VANS, "Vans")
        self.assertEqual(hermanos_de(mx, SIBLINGS), hermanos_de(mx, CUSTOM_SIBLINGS))


class TestSeReporta(unittest.TestCase):
    """Agrupar por nombre es mas laxo que agrupar por codigo. Si acaba juntando
    dos productos distintos, en la ficha se ve normal: tiene que verse en la
    hoja de Revision."""

    def _revision(self, codigos, brand_config, marca):
        return g.build_columbia_matrixify(
            entrada(codigos, marca), maestro(codigos, marca),
            pd.DataFrame(columns=["Handle"]), brand_config)[2]

    def test_una_carga_de_vans_dice_cuantos_grupos_salieron_del_nombre(self):
        codigos = dict(OLD_SKOOL)
        codigos.update(SK8)
        revision = self._revision(codigos, VANS, "Vans")
        avisos = [f for _, f in revision.iterrows()
                  if "Siblings por nombre" in str(f.get("Mod-Col", ""))]
        self.assertEqual(len(avisos), 1, "una fila, no una por grupo")
        self.assertIn("2 grupos", str(avisos[0].get("Problema")))
        self.assertIn("zapatilla-old-skool", str(avisos[0].get("Problema")))

    def test_una_carga_que_NO_agrupa_por_nombre_no_dice_nada(self):
        """Un aviso que salta siempre enseña a ignorar la hoja."""
        revision = self._revision(POWDER, COLUMBIA, "Columbia")
        self.assertEqual(
            [f for _, f in revision.iterrows()
             if "Siblings por nombre" in str(f.get("Mod-Col", ""))], [])


class TestLoYaPublicado(unittest.TestCase):
    """Lo publicado NO se pisa: un color que ya vive en la tienda tiene que
    seguir en el grupo aunque el input del dia no lo traiga."""

    def test_un_color_ya_publicado_entra_en_el_grupo_por_titulo(self):
        catalogo = catalogo_matrixify([
            producto_shopify("VN-01R1GI6-KGA", "old-skool-kga", "Zapatilla Old Skool", "Vans")])
        hermanos = hermanos_de(carga_completa(OLD_SKOOL, VANS, "Vans", catalogo=catalogo))
        for handle, lista in hermanos.items():
            self.assertIn("old-skool-kga", lista, handle)
            self.assertEqual(len(lista), 3, handle)

    def test_siblings_ya_publicados_agrupa_por_titulo_en_vans(self):
        catalogo = catalogo_matrixify([
            producto_shopify("VN-018BGIC-BIV", "old-skool-biv", "Zapatilla Old Skool", "Vans"),
            producto_shopify("VN-018BGIE-GB8", "old-skool-gb8", "Zapatilla Old Skool", "Vans"),
            producto_shopify("VN-018BGXP-KGB", "sk8-kgb", "Zapatilla Sk8-Hi", "Vans")])
        grupos = g.siblings_ya_publicados(catalogo, VANS)
        self.assertEqual(sorted(len(v) for v in grupos.values()), [1, 2])

    def test_sin_columna_de_marca_manda_la_UNICA_marca_del_sitio(self):
        """Sin ese respaldo, un producto de Vans.pe sin `custom.marca` se
        agruparia por modelo mientras sus hermanos lo hacen por titulo, y la
        relacion se partiria en dos."""
        catalogo = catalogo_matrixify([
            producto_shopify("VN-018BGIC-BIV", "old-skool-biv", "Zapatilla Old Skool", "Vans"),
            producto_shopify("VN-018BGIE-GB8", "old-skool-gb8", "Zapatilla Old Skool", "Vans")])
        grupos = g.siblings_ya_publicados(catalogo.drop(columns=[MARCA]), VANS)
        self.assertEqual([sorted(v) for v in grupos.values()],
                         [["old-skool-biv", "old-skool-gb8"]])

    def test_un_sitio_multimarca_sin_marca_en_la_fila_se_queda_por_modelo(self):
        catalogo = catalogo_matrixify([
            producto_shopify("VN-018BGIC-BIV", "old-skool-biv", "Zapatilla Old Skool", "Vans"),
            producto_shopify("VN-018BGIE-GB8", "old-skool-gb8", "Zapatilla Old Skool", "Vans")])
        grupos = g.siblings_ya_publicados(catalogo.drop(columns=[MARCA]), SUPERMALL)
        self.assertEqual(sorted(grupos), ["VN-018BGIC", "VN-018BGIE"])


class TestCargaPorCodigos(unittest.TestCase):
    """Centry, Carga Sial parcial y Carga Supermall."""

    def test_vans_queda_hermanado_por_titulo(self):
        hermanos = hermanos_de(por_codigos(OLD_SKOOL, VANS, "VANS"))
        self.assertEqual(len(hermanos), 2)
        for handle, lista in hermanos.items():
            self.assertEqual(len(lista), 2, handle)

    def test_columbia_sigue_por_modelo(self):
        codigos = {"AB1234-010": "Casaca Powder Lite", "ZZ9999-010": "Casaca Powder Lite"}
        for handle, lista in hermanos_de(por_codigos(codigos, COLUMBIA, "COLUMBIA")).items():
            self.assertEqual(len(lista), 1, handle)

    def test_da_lo_MISMO_que_la_carga_completa(self):
        """Dos caminos que agrupan distinto dejarian el mismo producto con unos
        hermanos u otros segun por donde pasara."""
        completa = {h: sorted(v) for h, v in hermanos_de(
            carga_completa(OLD_SKOOL, VANS, "Vans")).items()}
        codigos = {h: sorted(v) for h, v in hermanos_de(
            por_codigos(OLD_SKOOL, VANS, "VANS")).items()}
        self.assertEqual(completa, codigos)


class TestMantenedorDeSiblings(unittest.TestCase):
    """Las dos rutas de Carga parcial: Shopify API y Respaldo Excel."""

    def setUp(self):
        self.vans = [
            producto_shopify("VN-018BGIC-BIV", "old-skool-biv", "Zapatilla Old Skool", "Vans"),
            producto_shopify("VN-018BGIE-GB8", "old-skool-gb8", "Zapatilla Old Skool", "Vans"),
            producto_shopify("VN-018BGXP-KGB", "sk8-kgb", "Zapatilla Sk8-Hi", "Vans")]
        self.columbia = [
            producto_shopify("AB1234-010", "powder-010", "Casaca Powder Lite", "Columbia"),
            producto_shopify("AB1234-011", "powder-011", "Casaca Powder Lite", "Columbia"),
            producto_shopify("ZZ9999-010", "powder-zz", "Casaca Powder Lite", "Columbia")]

    def test_por_shopify_api_vans_va_por_titulo(self):
        grupos = app.siblings_by_model_from_shopify(self.vans, VANS)
        self.assertEqual(sorted(grupos.values()),
                         ["old-skool-biv, old-skool-gb8", "sk8-kgb"])

    def test_por_shopify_api_columbia_va_por_modelo(self):
        grupos = app.siblings_by_model_from_shopify(self.columbia, COLUMBIA)
        self.assertEqual(sorted(grupos), ["AB1234", "ZZ9999"])

    def test_en_una_tienda_multimarca_cada_marca_con_su_regla(self):
        grupos = app.siblings_by_model_from_shopify(self.vans + self.columbia, SUPERMALL)
        self.assertEqual(sorted(grupos), [
            "AB1234", "TITULO:zapatilla-old-skool", "TITULO:zapatilla-sk8-hi", "ZZ9999"])

    def test_el_respaldo_excel_agrupa_IGUAL_que_shopify_api(self):
        """Si una ruta agrupara distinto, el mismo archivo se aplicaria distinto
        segun la fuente elegida arriba."""
        for productos, config in ((self.vans, VANS), (self.columbia, COLUMBIA),
                                  (self.vans + self.columbia, SUPERMALL)):
            por_api = app.siblings_by_model_from_shopify(productos, config)
            filas, _ = g.build_matrixify_updates(
                catalogo_matrixify(productos), operation="siblings", brand_config=config)
            por_excel = {
                g.clean(fila["Handle"]): g.clean(fila.get(g.SIBLINGS_COLUMN))
                for _, fila in filas.iterrows() if g.clean(fila.get("Handle"))
            }
            esperado = {}
            for producto in productos:
                clave = g.clave_de_siblings(
                    producto["Mod-Col"], producto["Title"],
                    g.marca_para_siblings(producto["Marca"], config))
                esperado[producto["Handle"]] = por_api[clave]
            self.assertEqual(por_excel, esperado, config.get("site_key"))

    def test_arrastrar_los_publicados_al_matrixify_usa_la_misma_regla(self):
        mx = pd.DataFrame([{
            "Handle": "old-skool-biv", "Title": "Zapatilla Old Skool",
            CLAVE: "VN-018BGIC-BIV", MARCA: "Vans", SIBLINGS: "", CUSTOM_SIBLINGS: "",
        }])
        salida = app.apply_shopify_siblings_to_matrixify(mx, self.vans, VANS)
        self.assertEqual(g.clean(salida.iloc[0][SIBLINGS]), "old-skool-biv, old-skool-gb8")


class TestLaReglaEstaEscritaUnaVez(unittest.TestCase):
    """Escrita en cada superficie, el mismo producto caeria en un grupo distinto
    segun por donde pasara: es la trampa de las dos `normalize_size`."""

    FUENTES = (
        (g, "build_columbia_matrixify"),
        (g, "siblings_ya_publicados"),
        (g, "build_matrixify_updates"),
        (app, "build_centry_matrixify_from_master"),
        (app, "siblings_by_model_from_shopify"),
        (app, "apply_shopify_siblings_to_matrixify"),
        (app, "build_shopify_update_preview"),
    )

    def test_ninguna_superficie_parte_el_codigo_a_mano(self):
        """`rsplit("-", 1)` escrito en la funcion es una segunda regla."""
        for modulo, nombre in self.FUENTES:
            fuente = inspect.getsource(getattr(modulo, nombre))
            arbol = ast.parse(textwrap.dedent(fuente))
            for nodo in ast.walk(arbol):
                if (isinstance(nodo, ast.Call)
                        and isinstance(nodo.func, ast.Attribute)
                        and nodo.func.attr == "rsplit"):
                    # Solo se vigila lo que parte por el guion del codigo color.
                    literales = [a.value for a in nodo.args if isinstance(a, ast.Constant)]
                    self.assertNotIn("-", literales, f"{nombre} parte el codigo a mano")

    def test_todas_llaman_a_la_misma_funcion(self):
        for modulo, nombre in self.FUENTES:
            fuente = inspect.getsource(getattr(modulo, nombre))
            self.assertTrue(
                "clave_de_siblings(" in fuente
                or "_clave_de_siblings_de_producto(" in fuente
                or "siblings_ya_publicados(" in fuente,
                f"{nombre} no usa la regla compartida")

    def test_la_lista_de_marcas_va_por_marca_y_no_por_sitio(self):
        """Una bandera de SITIO convertiria todo Supermall, que lleva diez
        marcas, o nada."""
        self.assertEqual(g.MARCAS_SIBLINGS_POR_TITULO, ("VANS",))
        for config in (VANS, COLUMBIA, SUPERMALL):
            self.assertNotIn("siblings_por_titulo", config)


if __name__ == "__main__":
    unittest.main(verbosity=1)
