"""Los accesorios de talla unica llegaban a la Carga Sial y no a Shopify.

Ejecutar:  python scripts/test_talla_unica_y_duplicadas.py

Reportado con una carga real de Rockford: *"tengo una carga que no esta
haciendo el match completo para subirlo a shopify pero si me arma bien la carga
sial [...] solo estan subiendo 78 productos pero son mas, y no solo pasa en
rockford esta pasando en varias marcas"*.

Medido con el input del usuario (181 accesorios) y el maestro completado con el
perfil real de `data/arti.zip`:

                                  antes      ahora
    Productos en el Matrixify        81        181
    Productos en la Carga Sial      181        181
    Tallas duplicadas                27          0

Eran DOS fallos, los dos invisibles en la hoja Carga Sial:

1. **`category_blocks_zero_size` contradecia al diccionario de tipos.**
   Respondia "a este producto no le corresponde talla unica" buscando
   SUBCADENAS ("media", "ropa"...) en la categoria, el tipo y los TAGS
   concatenados, mientras `_talla_unica_bloqueada` -- que responde la MISMA
   pregunta y cuyo docstring exige la misma respuesta -- la resuelve con la
   clase del diccionario. Cuando discrepan, la talla se renombra a "Talla
   Única" y despues `final_variant_filter` borra el producto ENTERO. Las
   Medias son Accesorios en el diccionario maestro, asi que las 100 de esa
   carga desaparecian; y con "ropa" dentro de "Europa" podia caer cualquier
   producto por un tag.

2. **Dos SKU con la misma talla.** El maestro trae la reposicion de un modelo
   con un CODINT nuevo y la misma talla -- 47.532 de los 117.161 modelo-color
   de `data/arti.zip` tienen alguna talla repetida --, y salian como dos
   variantes con el mismo `Option1 Value`. Shopify rechaza el producto ENTERO,
   asi que no se crea ninguna de las dos. En la hoja Carga Sial, que es por
   SKU, las dos filas son legitimas: por eso la Sial salia bien.

Las pruebas EJECUTAN el motor con el maestro REAL -- no leen su codigo: es la
leccion de `start_suelto`, que tenia ocho pruebas leyendo su fuente y ninguna
la llamaba.
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pandas as pd  # noqa: E402

import app_matrixify as app  # noqa: E402
import generate_columbia_matrixify as g  # noqa: E402

ROCKFORD = g.get_brand_config("rockford")
COLUMBIA = g.get_brand_config("columbia")

COLUMNAS_CATALOGO = list(
    pd.read_excel("data/matrixify_modelo.xlsx", sheet_name=0, nrows=3).columns
)

COLUMNAS_ARTI = [
    "CODINT_MA", "COD MOD COL", "TALNUM_MA", "MARCA_MA", "Precio", "CodBarras",
    "Mod-Col", "NombreModelo", "DescripcionWeb", "Caracteristicas", "Material",
    "Cuidado", "TipoProducto", "Categoria", "SubCategoria", "Genero",
    "ColorNombre", "Temporada", "Coleccion", "Ocasion", "Deporte", "Tecnologia",
    "Imagen",
]


def maestro(filas):
    """Un ARTI minimo. `filas` son (mod_col, talla, sku, codigo_de_barras)."""
    registros = []
    for mod_col, talla, sku, barras in filas:
        registro = {columna: "" for columna in COLUMNAS_ARTI}
        registro.update({
            "CODINT_MA": str(sku), "COD MOD COL": mod_col, "TALNUM_MA": talla,
            "MARCA_MA": "ROCKFORD", "CodBarras": barras, "Mod-Col": mod_col,
        })
        registros.append(registro)
    return pd.DataFrame(registros, columns=COLUMNAS_ARTI)


def entrada(productos):
    """Un input comercial minimo. `productos` son (mod_col, tipo, clase)."""
    filas = []
    for indice, (mod_col, tipo, clase) in enumerate(productos):
        filas.append({
            "Mod-Col": mod_col, "Marca": "Rockford", "Genero": "HOMBRE",
            "Clase": clase, "Tipo de prenda": tipo, "Color Comercial": "NEGRO",
            "MODELO": f"MODELO {indice}",
            "Nombre de Producto": f"Producto de prueba {indice}",
            "Descripcion": "Una descripcion de prueba suficientemente larga.",
            "Caracteristicas": "Composicion: 100% Cuero",
            "Materiales": "Cuero", "PUBLICAR_ROCKFORD_PE": "SI",
        })
    return pd.DataFrame(filas)


def problemas_de(observaciones):
    if observaciones is None or observaciones.empty or "Problema" not in observaciones:
        return ""
    return " ".join(observaciones["Problema"].astype(str))


def cargar(productos, filas_arti, brand_config=ROCKFORD):
    salida = g.build_columbia_matrixify(
        entrada(productos), maestro(filas_arti), COLUMNAS_CATALOGO,
        brand_config=brand_config,
    )
    matrixify, _resumen, observaciones, _tipos, _omitidos, sial = salida
    return matrixify, sial, observaciones


def codigos_del_matrixify(matrixify):
    columna = matrixify["Metafield: custom.codigo_modelo_color [id]"]
    return {g.clean(valor).upper() for valor in columna if g.clean(valor)}


def tallas_repetidas(matrixify):
    """Pares (producto, talla) que salen mas de una vez. Shopify los rechaza."""
    if matrixify.empty:
        return {}
    handle = matrixify["Handle"].map(g.clean).replace("", pd.NA).ffill().fillna("")
    talla = matrixify["Option1 Value"].map(g.clean)
    pares = pd.DataFrame({"handle": handle, "talla": talla})
    pares = pares[pares["talla"] != ""]
    cuenta = pares.groupby(["handle", "talla"]).size()
    return {clave: int(veces) for clave, veces in cuenta[cuenta > 1].items()}


class LaMismaPreguntaDaLaMismaRespuesta(unittest.TestCase):
    """`_talla_unica_bloqueada` y `category_blocks_zero_size` no pueden discrepar.

    Lo dice el docstring de la primera desde que se escribio: si una dice que
    si y la otra que no, el producto se renombra a "Talla Única" y despues el
    filtro final lo borra. Nadie lo comprobaba.
    """

    def test_los_sesenta_tipos_del_diccionario_coinciden(self):
        from engines.garment_types import TIPOS

        discrepan = []
        for regla in TIPOS:
            tipo = regla["tipo"]
            por_tipo = g._talla_unica_bloqueada(tipo)
            por_fila = g.category_blocks_zero_size({"Type": tipo})
            if por_tipo != por_fila:
                discrepan.append((tipo, g.clase_de_tipo(tipo), por_tipo, por_fila))
        self.assertEqual(discrepan, [], f"tipos con respuestas contrarias: {discrepan}")

    def test_medias_son_accesorios_y_admiten_talla_unica(self):
        self.assertEqual(g.clase_de_tipo("Medias"), "Accesorios")
        self.assertFalse(g._talla_unica_bloqueada("Medias"))
        self.assertFalse(g.category_blocks_zero_size({"Type": "Medias"}))

    def test_el_vestuario_y_el_calzado_siguen_bloqueados(self):
        for tipo in ("Poleras", "Casacas", "Pantalones", "Zapatilla", "Bota"):
            with self.subTest(tipo=tipo):
                self.assertTrue(g.category_blocks_zero_size({"Type": tipo}), tipo)
                self.assertTrue(g._talla_unica_bloqueada(tipo), tipo)

    def test_la_clase_declarada_tambien_bloquea(self):
        """Un tipo que el diccionario no conoce, pero con la clase escrita."""
        self.assertTrue(g.category_blocks_zero_size({"Clase": "Vestuario", "Type": "XYZ"}))
        self.assertTrue(g.category_blocks_zero_size({"Clase": "Calzado", "Type": "XYZ"}))
        self.assertFalse(g.category_blocks_zero_size({"Clase": "Accesorios", "Type": "XYZ"}))

    def test_una_polera_declarada_accesorio_sigue_bloqueada(self):
        """Bloquea si CUALQUIERA de las dos fuentes lo dice: una talla unica
        inventada en una polera borra el producto mas adelante."""
        self.assertTrue(
            g.category_blocks_zero_size({"Clase": "Accesorios", "Type": "Poleras"})
        )

    def test_las_dos_leen_la_misma_lista_de_clases(self):
        self.assertEqual(g.CLASES_SIN_TALLA_UNICA, ("calzado", "vestuario"))
        for clase in g.CLASES_SIN_TALLA_UNICA:
            self.assertTrue(g.clase_bloquea_talla_unica(clase.upper()))
        self.assertFalse(g.clase_bloquea_talla_unica("Accesorios"))
        self.assertFalse(g.clase_bloquea_talla_unica(""))


class ElRespaldoPorTextoVaPorPalabra(unittest.TestCase):
    """Solo se usa cuando no hay clase por ningun lado, y nunca por subcadena."""

    def test_un_tag_europa_no_bloquea_por_la_palabra_ropa(self):
        self.assertFalse(
            g.category_blocks_zero_size({"Type": "COOLER WR", "Tags": "Europa, verano"})
        )

    def test_intermedia_no_bloquea_por_la_palabra_media(self):
        self.assertFalse(
            g.category_blocks_zero_size({"Type": "ARTICULO XYZ", "Tags": "capa intermedia"})
        )

    def test_un_tipo_desconocido_de_vestuario_si_bloquea(self):
        self.assertTrue(g.category_blocks_zero_size({"Type": "CHAQUETA IMPOSIBLE XYZ"}))
        self.assertTrue(g.category_blocks_zero_size({"Type": "ZAPATOS RAROS XYZ"}))

    def test_el_plural_tambien_cuenta(self):
        self.assertTrue(g.category_blocks_zero_size({"Type": "BOTAS XYZ RARAS"}))
        self.assertTrue(g.category_blocks_zero_size({"Type": "SHORTS XYZ RAROS"}))

    def test_medias_ya_no_esta_entre_los_terminos_bloqueados(self):
        """El diccionario maestro dice Accesorios, que es el dato confirmado."""
        for termino in ("media", "medias", "calcetin", "calcetines"):
            self.assertNotIn(termino, g.TERMINOS_SIN_TALLA_UNICA)


class ElAccesorioDeTallaUnicaLlegaAShopify(unittest.TestCase):
    """El fallo tal como lo vio el usuario: en la Sial si, en el Matrixify no."""

    def test_una_media_con_una_sola_talla_cero_sale_en_las_dos_hojas(self):
        matrixify, sial, _ = cargar(
            [("RK110031850-HCB", "Medias", "Accesorios")],
            [("RK110031850-HCB", "0", 9000001, "7800100000001")],
        )
        self.assertEqual(codigos_del_matrixify(matrixify), {"RK110031850-HCB"})
        self.assertEqual(list(matrixify["Option1 Value"]), ["Talla Única"])
        self.assertEqual(len(sial), 1)

    def test_una_media_con_talla_os_sale_en_las_dos_hojas(self):
        matrixify, sial, _ = cargar(
            [("RK110031853-ZNN", "Medias", "Accesorios")],
            [("RK110031853-ZNN", "0", 9000002, ""),
             ("RK110031853-ZNN", "O/S", 9000003, "7800100000002")],
        )
        self.assertEqual(codigos_del_matrixify(matrixify), {"RK110031853-ZNN"})
        self.assertEqual(list(matrixify["Option1 Value"]), ["Talla Única"])
        self.assertEqual(len(sial), 1)

    def test_los_tipos_de_accesorio_de_la_carga_real_no_se_pierden(self):
        tipos = ["Medias", "CARTERA", "GORRO", "BILLETERA", "MALETÍN",
                 "CINTURONES", "BOINA", "MOCHILA", "PAÑUELO", "BOTELLA",
                 "BUFF", "NECESER", "SOMBRERO"]
        productos, filas = [], []
        for indice, tipo in enumerate(tipos):
            codigo = f"RK11003{indice:04d}-645"
            productos.append((codigo, tipo, "Accesorios"))
            filas.append((codigo, "0", 9100000 + indice, f"78001{indice:08d}"))
        matrixify, sial, _ = cargar(productos, filas)
        self.assertEqual(len(codigos_del_matrixify(matrixify)), len(tipos))
        self.assertEqual(len(matrixify), len(tipos))
        self.assertEqual(len(sial), len(tipos))

    def test_una_zapatilla_de_una_sola_talla_sigue_sin_crear_talla_unica(self):
        """No es una regresion del arreglo: ahi el dato esta incompleto y
        publicar "Talla Única" es peor que no publicar."""
        matrixify, _sial, _ = cargar(
            [("RK102039999-645", "Zapatilla", "Calzado")],
            [("RK102039999-645", "0", 9000004, "7800100000003")],
        )
        self.assertTrue(matrixify.empty)


class NoSalenDosVariantesConLaMismaTalla(unittest.TestCase):
    """Shopify rechaza el producto ENTERO, no solo la variante repetida."""

    def test_dos_sku_con_la_misma_talla_dejan_una_sola_variante(self):
        matrixify, _sial, _ = cargar(
            [("RK11003110-645", "Medias", "Accesorios")],
            [("RK11003110-645", "0", 3153531, ""),
             ("RK11003110-645", "0", 3153532, "7800135242718")],
        )
        self.assertEqual(len(matrixify), 1)
        self.assertEqual(tallas_repetidas(matrixify), {})

    def test_gana_la_fila_que_trae_codigo_de_barras(self):
        """Es el dato que usan el almacen y el ERP."""
        matrixify, _sial, _ = cargar(
            [("RK11003110-645", "Medias", "Accesorios")],
            [("RK11003110-645", "0", 3153531, ""),
             ("RK11003110-645", "0", 3153532, "7800135242718")],
        )
        self.assertEqual(list(matrixify["Variant SKU"]), ["3153532"])
        self.assertEqual(list(matrixify["Variant Barcode"]), ["7800135242718"])

    def test_sin_codigo_de_barras_gana_la_primera_y_es_determinista(self):
        filas = [("RK11003111-645", "0", 4000001, ""),
                 ("RK11003111-645", "0", 4000002, "")]
        primero = cargar([("RK11003111-645", "Medias", "Accesorios")], filas)[0]
        segundo = cargar([("RK11003111-645", "Medias", "Accesorios")], filas)[0]
        self.assertEqual(list(primero["Variant SKU"]), ["4000001"])
        self.assertEqual(list(primero["Variant SKU"]), list(segundo["Variant SKU"]))

    def test_una_talla_real_repetida_tampoco_duplica(self):
        """El caso del maestro: una reposicion entra con un CODINT nuevo."""
        matrixify, _sial, _ = cargar(
            [("RK6860-BEK", "Chompas", "Vestuario")],
            [("RK6860-BEK", "35-38", 3138340, "78001"),
             ("RK6860-BEK", "35-38", 2868637, "78002"),
             ("RK6860-BEK", "39-42", 3138339, "78003"),
             ("RK6860-BEK", "39-42", 2868635, "78004")],
        )
        self.assertEqual(tallas_repetidas(matrixify), {})
        self.assertEqual(sorted(matrixify["Option1 Value"]), ["35-38", "39-42"])

    def test_la_hoja_carga_sial_conserva_las_dos_filas(self):
        """La Sial es por SKU y ahi las dos son legitimas: el almacen las tiene."""
        _matrixify, sial, _ = cargar(
            [("RK11003110-645", "Medias", "Accesorios")],
            [("RK11003110-645", "0", 3153531, ""),
             ("RK11003110-645", "0", 3153532, "7800135242718")],
        )
        self.assertEqual(len(sial), 2)

    def test_se_reporta_en_las_observaciones(self):
        """Un descarte silencioso es como se pierde un dato sin que nadie se entere."""
        _matrixify, _sial, observaciones = cargar(
            [("RK11003110-645", "Medias", "Accesorios")],
            [("RK11003110-645", "0", 3153531, ""),
             ("RK11003110-645", "0", 3153532, "7800135242718")],
        )
        problemas = problemas_de(observaciones)
        self.assertIn("una sola variante por talla", problemas)

    def test_un_producto_sin_tallas_repetidas_no_pierde_ninguna_fila(self):
        matrixify, _sial, observaciones = cargar(
            [("RK6861-BEK", "Chompas", "Vestuario")],
            [("RK6861-BEK", "S", 1, "78001"), ("RK6861-BEK", "M", 2, "78002"),
             ("RK6861-BEK", "L", 3, "78003"), ("RK6861-BEK", "XL", 4, "78004")],
        )
        self.assertEqual(sorted(matrixify["Option1 Value"]), ["L", "M", "S", "XL"])
        problemas = problemas_de(observaciones)
        self.assertNotIn("una sola variante por talla", problemas)


class LaValidacionLoAvisaAntesDeSubir(unittest.TestCase):
    """La red por si el archivo llega por otra via."""

    def test_dos_variantes_con_la_misma_talla_bloquean(self):
        matrixify = pd.DataFrame([
            {"Handle": "un-producto", "Title": "Un producto", "Type": "Medias",
             "Variant SKU": "1", "Option1 Value": "Talla Única",
             "Metafield: custom.codigo_modelo_color [id]": "RK1-645"},
            {"Handle": "un-producto", "Title": "", "Type": "",
             "Variant SKU": "2", "Option1 Value": "Talla Única",
             "Metafield: custom.codigo_modelo_color [id]": ""},
        ])
        hallazgos = app.validar_matrixify(matrixify)
        textos = " ".join(hallazgos["Problema"].astype(str))
        self.assertIn("comparten el valor de la opcion", textos)
        self.assertIn(app.VALIDACION_BLOQUEA, set(hallazgos["Gravedad"]))

    def test_un_producto_sano_no_genera_ese_hallazgo(self):
        matrixify = pd.DataFrame([
            {"Handle": "un-producto", "Title": "Un producto", "Type": "Chompas",
             "Variant SKU": "1", "Option1 Value": "S",
             "Metafield: custom.codigo_modelo_color [id]": "RK1-645"},
            {"Handle": "un-producto", "Title": "", "Type": "",
             "Variant SKU": "2", "Option1 Value": "M",
             "Metafield: custom.codigo_modelo_color [id]": ""},
        ])
        hallazgos = app.validar_matrixify(matrixify)
        textos = " ".join(hallazgos["Problema"].astype(str))
        self.assertNotIn("comparten el valor de la opcion", textos)


CLAVE_MOD_COL = "Metafield: custom.codigo_modelo_color [id]"


def catalogo_de_origen(codigos, tipo):
    return pd.DataFrame([{
        "Handle": f"viejo-{codigo.lower()}", "ID": "", "Title": f"Producto {indice}",
        "Body HTML": "<p>t</p>", "Type": tipo, "Tags": "Rockford",
        "Vendor": "rockfordpe", CLAVE_MOD_COL: codigo,
        "Metafield: custom.color [single_line_text_field]": "NEGRO",
    } for indice, codigo in enumerate(codigos)])


def maestro_por_codigos(codigos, tallas):
    return pd.DataFrame([{
        "Mod-Col": codigo, "COD MOD COL": codigo,
        "CODINT_MA": f"SKU{codigo}-{k}", "TALNUM_MA": str(talla),
        "MARCA_MA": "ROCKFORD", "Precio": "99.90",
        "CodBarras": (f"77{indice}{k}" if k else ""),
    } for indice, codigo in enumerate(codigos) for k, talla in enumerate(tallas)])


def por_codigos(codigos, tipo, tallas):
    """La ruta de Centry, la Carga Sial parcial y Carga Supermall."""
    salida, _issues = app.build_centry_matrixify_from_master(
        codigos, catalogo_de_origen(codigos, tipo),
        maestro_por_codigos(codigos, tallas), ROCKFORD,
        destino_matrixify_df=pd.DataFrame(columns=list(app.MATRIXIFY_COLUMNS)),
    )
    return salida


class LaCargaPorCodigosTieneElMismoArreglo(unittest.TestCase):
    """Centry, Carga Sial parcial y Carga Supermall pasan por el MISMO
    `final_variant_filter`, asi que perdian los mismos productos."""

    def test_los_accesorios_de_talla_unica_salen(self):
        for tallas in (("0",), ("0", "0"), ("0", "O/S")):
            with self.subTest(tallas=tallas):
                salida = por_codigos(["RK1100311-645", "RK1100312-645"], "Medias", tallas)
                self.assertEqual(len(codigos_del_matrixify(salida)), 2)
                self.assertEqual(len(salida), 2)
                self.assertEqual(list(salida["Option1 Value"]), ["Talla Única"] * 2)

    def test_no_se_emiten_dos_variantes_con_la_misma_talla(self):
        salida = por_codigos(["RK1100311-645", "RK1100312-645"], "Chompas", ("S", "M", "M"))
        self.assertEqual(tallas_repetidas(salida), {})
        self.assertEqual(len(salida), 4)


class ContraElMaestroReal(unittest.TestCase):
    """Con `data/arti.zip`, que es de donde salio el numero del usuario."""

    @classmethod
    def setUpClass(cls):
        arti, _ = g.read_arti_source(brand_config=ROCKFORD)
        # Solo las marcas que Rockford.pe carga: el resto las descarta el
        # filtro de marca y la prueba estaria midiendo otra cosa.
        permitidas = {m.upper() for m in ROCKFORD["allowed_arti_brands"]}
        marca = arti["MARCA_MA"].map(lambda v: g.clean(v).upper())
        cls.arti = arti[marca.isin(permitidas)].copy()
        cls.clave = cls.arti["Mod-Col"].map(lambda v: g.clean(v).upper())

    def codigos_con_curva(self, curva, cuantos):
        tallas = self.arti["TALNUM_MA"].map(lambda v: g.clean(v))
        por_codigo = tallas.groupby(self.clave).apply(lambda s: tuple(sorted(set(s))))
        return [k for k, v in por_codigo.items() if v == curva][:cuantos]

    def test_los_accesorios_de_solo_talla_cero_ya_no_desaparecen(self):
        codigos = self.codigos_con_curva(("0",), 15)
        self.assertTrue(codigos, "el maestro deberia traer accesorios de talla unica")
        salida = g.build_columbia_matrixify(
            entrada([(c, "Medias", "Accesorios") for c in codigos]),
            self.arti, COLUMNAS_CATALOGO, brand_config=ROCKFORD,
        )
        matrixify, _resumen, _obs, _tipos, _omit, sial = salida
        self.assertEqual(len(codigos_del_matrixify(matrixify)), len(codigos))
        self.assertEqual(tallas_repetidas(matrixify), {})
        # El sintoma del usuario: la Sial completa y el Matrixify no.
        en_sial = {g.clean(v).upper() for v in sial["Mod-Col"] if g.clean(v)}
        self.assertEqual(codigos_del_matrixify(matrixify), en_sial)

    def test_los_accesorios_con_cero_y_os_tampoco(self):
        codigos = self.codigos_con_curva(("0", "O/S"), 15)
        self.assertTrue(codigos)
        salida = g.build_columbia_matrixify(
            entrada([(c, "CARTERA", "Accesorios") for c in codigos]),
            self.arti, COLUMNAS_CATALOGO, brand_config=ROCKFORD,
        )
        matrixify = salida[0]
        self.assertEqual(len(codigos_del_matrixify(matrixify)), len(codigos))
        self.assertEqual(tallas_repetidas(matrixify), {})

    def test_una_carga_de_vestuario_no_pierde_ni_una_talla(self):
        """Lo que ya funcionaba tiene que salir igual."""
        codigos = self.codigos_con_curva(("0", "L", "M", "S"), 10)
        self.assertTrue(codigos)
        salida = g.build_columbia_matrixify(
            entrada([(c, "Chompas", "Vestuario") for c in codigos]),
            self.arti, COLUMNAS_CATALOGO, brand_config=ROCKFORD,
        )
        matrixify = salida[0]
        self.assertEqual(len(codigos_del_matrixify(matrixify)), len(codigos))
        self.assertEqual(len(matrixify), 3 * len(codigos))
        self.assertEqual(tallas_repetidas(matrixify), {})


if __name__ == "__main__":
    unittest.main(verbosity=1)
