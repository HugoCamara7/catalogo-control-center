"""El Centry tardaba mas que todo lo demas junto, y una fila como dict lo vaciaba.

Ejecutar:  python scripts/test_centry_rendimiento.py

Reportado con una sola frase -- *"mucho demora"* -- sobre "Analizar input".
Medido a la escala real (1.008 productos contra un catalogo de 4.000 en la
tienda), el analisis eran 95 s y **`build_centry_from_matrixify` se llevaba 69**.
Y crecia con el tamano del CATALOGO, no con el de la carga, que es la senal de
que algo recorre de mas.

Lo que fija este archivo
------------------------

1. **La fila como dict no puede vaciar el EAN.** `centry_ean_de_la_fila` hacia
   `set(getattr(row, "index", []))`. Con un dict eso devuelve **un conjunto
   vacio sin fallar**: ninguna columna se encontraba nunca, la funcion
   contestaba "no hay EAN en la fila" y el codigo se caia al maestro. Un
   producto cuyo EAN solo esta en el export de Shopify se publicaria SIN codigo
   de barras y la hoja de revision culparia al maestro. Es el error que no
   revienta, y lo destapo comparar la salida antes y despues.

2. **`_fila_tiene_columna` responde igual para `Series` y para dict.** Cuatro
   funciones preguntaban `if columna in row.index`, que con un dict **revienta**.

3. **`normalizar` va cacheado por TEXTO, nunca por valor.** Con el valor como
   clave, `1`, `1.0` y `True` comparten hash y entrada de cache
   (`hash(1) == hash(1.0) == hash(True)`), asi que un booleano se llevaria la
   respuesta de un numero. Lo mismo para `centry_master_key`.

4. **El indice de valores permitidos vive DENTRO de la plantilla memoizada**,
   asi que recargarla lo tira sola. Un indice que sobreviviera a la recarga
   contestaria con el diccionario viejo.

5. **`centry_lookup_category` devuelve una COPIA.** Va cacheada; si devolviera
   el dict de la cache, quien lo tocara contaminaria el resto de la carga.

6. **`centry_validar_salida` conserva el ORDEN de los hallazgos.** Se
   vectorizaron las mascaras, pero la hoja de revision se compara con la del
   analisis anterior: reordenarla la vuelve inutil para comparar.

Las pruebas EJECUTAN: arman un Matrixify y lo pasan por el motor de verdad.
Leer el codigo no es ejecutarlo.
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pandas as pd  # noqa: E402

import app_matrixify as app  # noqa: E402
from engines import centry_map as cm  # noqa: E402


SITIO = app.get_brand_config("vans")
TALLAS = ("70", "80", "90")


def matrixify_de_prueba(modelos=3, barcode_en_shopify=True):
    """Un Matrixify con la forma que recibe el Centry: producto + variantes."""
    filas = []
    for i in range(modelos):
        mod = f"VN000{i:05d}-011"
        for pos, talla in enumerate(TALLAS):
            filas.append({
                "Handle": f"zapatilla-{i}", "Title": f"Zapatilla {i}" if pos == 0 else "",
                "Body HTML": "<p>Zapatilla de lona</p>" if pos == 0 else "",
                "Vendor": "Vans" if pos == 0 else "", "Type": "Zapatillas" if pos == 0 else "",
                "Tags": "Vans, Calzado" if pos == 0 else "", "Status": "active" if pos == 0 else "",
                "Published": "TRUE" if pos == 0 else "",
                "Image Src": "https://x/1.jpg" if pos == 0 else "",
                "Option1 Name": "Talla" if pos == 0 else "", "Option1 Value": talla,
                "Variant SKU": f"SKU{i}{pos}", "Variant Price": "299",
                "Variant Barcode": f"779870000{i}{pos}0" if barcode_en_shopify else "",
                "Metafield: custom.codigo_modelo_color [id]": mod if pos == 0 else "",
                "Metafield: custom.genero [single_line_text_field]": "Masculino" if pos == 0 else "",
                "Metafield: custom.color [single_line_text_field]": "Negro" if pos == 0 else "",
            })
    return pd.DataFrame(filas)


def maestro_de_prueba(modelos=3, con_barcode=True):
    filas = []
    for i in range(modelos):
        mod = f"VN000{i:05d}-011"
        for pos, talla in enumerate(TALLAS):
            filas.append({
                "Mod-Col": mod, "COD MOD COL": mod, "CODINT_MA": f"SKU{i}{pos}",
                "TALNUM_MA": talla, "MARCA_MA": "VANS", "Precio": "299",
                "CodBarras": f"111100000{i}{pos}0" if con_barcode else "",
                "NombreModelo": f"Zapatilla {i}", "TipoProducto": "ZAPATILLA",
                "Genero": "HOMBRE", "ColorNombre": "NEGRO",
            })
    return pd.DataFrame(filas)


# --- 1. el EAN y la fila como dict ---------------------------------------
class TestElEanNoSePierdeConUnaFilaDict(unittest.TestCase):
    """`set(getattr(row, "index", []))` devolvia un conjunto VACIO con un dict."""

    CAMPOS = {"Variant SKU": "SKU00", "Variant Barcode": "7798788888888"}

    def test_series_y_dict_encuentran_el_mismo_ean(self):
        como_series = app.centry_ean_de_la_fila(pd.Series(self.CAMPOS))
        como_dict = app.centry_ean_de_la_fila(dict(self.CAMPOS))
        self.assertEqual(como_series, ("7798788888888", "Variant Barcode"))
        self.assertEqual(como_dict, como_series)

    def test_la_fuente_sigue_siendo_shopify_con_un_dict(self):
        lookup = app.build_centry_arti_lookup(maestro_de_prueba())
        ean, fuente = app.centry_resolver_ean(dict(self.CAMPOS), {}, lookup, "VN000000000-011", "70")
        self.assertEqual(ean, "7798788888888")
        self.assertEqual(fuente, "Shopify (Variant Barcode)")

    def test_el_motor_completo_reporta_shopify_cuando_el_ean_solo_esta_alli(self):
        """El caso que se perdia: el maestro NO trae codigo de barras."""
        centry, _ = app.build_centry_from_matrixify(
            matrixify_de_prueba(), SITIO, arti_df=maestro_de_prueba(con_barcode=False))
        codigos = [c for c in centry["Código de barra variante (EAN/UPC/ISBN)"] if str(c).strip()]
        self.assertEqual(len(codigos), len(TALLAS) * 3, "se perdieron codigos de barra")
        self.assertTrue(all(c.startswith("7798") for c in codigos), codigos[:3])

    def test_sin_ean_en_ninguna_fuente_queda_pendiente_y_no_revienta(self):
        centry, _ = app.build_centry_from_matrixify(
            matrixify_de_prueba(barcode_en_shopify=False), SITIO,
            arti_df=maestro_de_prueba(con_barcode=False))
        self.assertEqual(len(centry), len(TALLAS) * 3)


class TestUnaColumnaSeBuscaIgualEnLasDosFormas(unittest.TestCase):
    def test_series_y_dict(self):
        for fila in (pd.Series({"Type": "Zapatillas"}), {"Type": "Zapatillas"}):
            self.assertTrue(app._fila_tiene_columna(fila, "Type"))
            self.assertFalse(app._fila_tiene_columna(fila, "Clase"))

    def test_las_funciones_que_la_usan_contestan_igual(self):
        campos = {"Clase": "Accesorios", "Type": "Mochilas",
                  "Tags": "Color: Negro", "Listado de características": ""}
        for funcion in (app.centry_output_is_accessory, app.centry_output_blocks_zero_size):
            self.assertEqual(funcion(pd.Series(campos)), funcion(dict(campos)), funcion.__name__)
        self.assertEqual(
            app.centry_tag_value(pd.Series(campos), "Color"),
            app.centry_tag_value(dict(campos), "Color"),
        )


# --- 2. las caches, por texto y no por valor ------------------------------
class TestLasCachesVanPorTextoNoPorValor(unittest.TestCase):
    """`hash(1) == hash(1.0) == hash(True)`: con el valor como clave, un
    booleano se lleva la respuesta de un numero."""

    def test_normalizar_distingue_1_de_True(self):
        self.assertEqual(cm.normalizar(1), "1")
        self.assertEqual(cm.normalizar(True), "true")
        self.assertEqual(cm.normalizar(1), "1", "la cache contesto lo del booleano")
        # El punto es puntuacion y siempre se convirtio en espacio: lo que se
        # comprueba aqui es que 1.0 NO comparte respuesta con 1 ni con True.
        self.assertEqual(cm.normalizar(1.0), "1 0")

    def test_normalizar_sigue_quitando_tildes_y_puntuacion(self):
        self.assertEqual(cm.normalizar("MOCASÍN"), "mocasin")
        self.assertEqual(cm.normalizar("  Polo   Manga,Corta "), "polo manga corta")
        self.assertEqual(cm.normalizar(None), "")

    def test_centry_master_key_distingue_1_de_True(self):
        self.assertEqual(app.centry_master_key(1), app.centry_master_key("1"))
        self.assertNotEqual(app.centry_master_key(True), app.centry_master_key(1))

    def test_centry_master_key_ignora_los_vacios_como_antes(self):
        self.assertEqual(app.centry_master_key("Zapatillas", "", "Hombre"),
                         app.centry_master_key("Zapatillas", "Hombre"))


class TestElIndiceDeLaPlantilla(unittest.TestCase):
    def test_valor_valido_devuelve_la_ortografia_de_la_plantilla(self):
        restringidas = app.centry_columnas_con_diccionario()
        self.assertTrue(restringidas, "la plantilla no trae columnas con diccionario")
        columna, permitidos = next(iter(restringidas.items()))
        esperado = permitidos[0]
        for escrito in (esperado, esperado.upper(), esperado.lower()):
            valor, ok = cm.valor_valido(columna, escrito)
            self.assertTrue(ok, f"{columna}={escrito!r}")
            self.assertEqual(valor, esperado)

    def test_un_valor_que_no_esta_se_reporta_como_invalido(self):
        restringidas = app.centry_columnas_con_diccionario()
        columna = next(iter(restringidas))
        valor, ok = cm.valor_valido(columna, "esto-no-existe-en-la-plantilla")
        self.assertFalse(ok)
        self.assertEqual(valor, "esto-no-existe-en-la-plantilla")

    def test_una_columna_sin_diccionario_es_texto_libre(self):
        self.assertEqual(cm.valor_valido("Columna Inventada", "lo que sea"), ("lo que sea", True))

    def test_el_indice_vive_dentro_de_la_plantilla_y_la_recarga_lo_tira(self):
        restringidas = app.centry_columnas_con_diccionario()
        columna = next(iter(restringidas))
        cm.valor_valido(columna, restringidas[columna][0])
        self.assertIn("__indices__", cm.cargar_plantilla())
        plantilla = cm.cargar_plantilla(recargar=True)
        self.assertEqual(plantilla.get("__indices__", {}), {},
                         "el indice sobrevivio a la recarga y contestaria con el diccionario viejo")


class TestLaCategoriaCacheadaDevuelveUnaCopia(unittest.TestCase):
    def test_tocar_el_resultado_no_contamina_la_siguiente_llamada(self):
        primera = app.centry_lookup_category("Zapatillas", "Hombre", "Vans", "Calzado")
        primera["category"] = "CONTAMINADO"
        segunda = app.centry_lookup_category("Zapatillas", "Hombre", "Vans", "Calzado")
        self.assertNotEqual(segunda.get("category"), "CONTAMINADO")

    def test_devuelve_lo_mismo_que_antes_para_un_tipo_desconocido(self):
        record = app.centry_lookup_category("TipoQueNoExiste", "Hombre", "Vans", "Calzado")
        self.assertEqual(record.get("category"), "Calzado")


# --- 3. la validacion: mismo contenido y mismo ORDEN ----------------------
class TestLaValidacionConservaElOrden(unittest.TestCase):
    def centry(self):
        return app.build_centry_from_matrixify(
            matrixify_de_prueba(modelos=4), SITIO, arti_df=maestro_de_prueba(modelos=4))[0]

    def test_los_hallazgos_salen_agrupados_por_producto_y_en_orden_del_archivo(self):
        centry = self.centry()
        validacion = app.centry_validar_salida(centry)
        if validacion.empty:
            self.skipTest("esta carga no deja hallazgos")
        orden_centry = list(dict.fromkeys(
            app.clean_value(v) for v in centry["SKU del producto"] if app.clean_value(v)))
        orden_hallazgos = list(dict.fromkeys(validacion["Mod-Col"]))
        esperado = [m for m in orden_centry if m in set(orden_hallazgos)]
        self.assertEqual(orden_hallazgos, esperado,
                         "la hoja de revision cambio de orden y deja de compararse con la anterior")

    def test_un_campo_obligatorio_vacio_se_reporta_con_sus_SKU(self):
        centry = self.centry()
        centry.loc[centry.index[:2], "Descripcion"] = ""
        validacion = app.centry_validar_salida(centry, revisar_valores=False)
        filas = validacion[validacion["Campo"] == "Descripcion"]
        self.assertFalse(filas.empty, "no reporto la descripcion vacia")
        self.assertEqual(int(filas.iloc[0]["Variantes"]), 2)
        for sku in centry.loc[centry.index[:2], "SKU de la variante"]:
            self.assertIn(app.clean_value(sku), filas.iloc[0]["SKUs"])

    def test_el_nombre_igual_al_codigo_sigue_bloqueando(self):
        centry = self.centry()
        primer_codigo = app.clean_value(centry.iloc[0]["SKU del producto"])
        centry.loc[centry["SKU del producto"] == primer_codigo, "Nombre del Producto"] = primer_codigo
        validacion = app.centry_validar_salida(centry, revisar_valores=False)
        filas = validacion[validacion["Campo"] == "Nombre del Producto"]
        self.assertFalse(filas.empty)
        self.assertEqual(app.clean_value(filas.iloc[0]["Severidad"]), "Bloqueante")

    def test_un_centry_vacio_no_revienta(self):
        vacio = app.centry_validar_salida(pd.DataFrame())
        self.assertTrue(vacio.empty)


# --- 4. el motor entero sigue dando lo mismo ------------------------------
class TestElCentryCompletoNoCambio(unittest.TestCase):
    def test_una_fila_por_variante_con_su_SKU_y_su_talla(self):
        centry, _ = app.build_centry_from_matrixify(
            matrixify_de_prueba(modelos=2), SITIO, arti_df=maestro_de_prueba(modelos=2))
        self.assertEqual(len(centry), len(TALLAS) * 2)
        self.assertEqual(sorted(centry["SKU de la variante"]),
                         sorted(f"SKU{i}{p}" for i in range(2) for p in range(len(TALLAS))))
        self.assertTrue(all(app.clean_value(v) for v in centry["Talla"]))

    def test_el_nombre_y_la_marca_llegan_a_todas_las_variantes(self):
        """El `forward_fill` del bloque de producto: sin el, solo la primera."""
        centry, _ = app.build_centry_from_matrixify(
            matrixify_de_prueba(modelos=2), SITIO, arti_df=maestro_de_prueba(modelos=2))
        self.assertTrue(all(app.clean_value(v) for v in centry["Nombre del Producto"]))
        self.assertTrue(all(app.clean_value(v) for v in centry["Marca"]))

    def test_sin_maestro_sigue_saliendo_el_archivo(self):
        centry, _ = app.build_centry_from_matrixify(matrixify_de_prueba(modelos=2), SITIO)
        self.assertEqual(len(centry), len(TALLAS) * 2)


# --- 5. el filtro de tallas de la hoja -----------------------------------
class TestElFiltroDeTallasNoCambio(unittest.TestCase):
    """Se vectorizo (`_mascara_por_valor` y los dos `apply(axis=1)`), asi que
    hay que comprobar que sigue quitando y conservando exactamente lo mismo."""

    def hoja(self, filas):
        return pd.DataFrame(filas)

    def test_quita_las_tallas_internas_K_y_lo_que_no_es_talla(self):
        hoja = self.hoja([
            {"Mod": "A-1", "Talla": "38", "Clase": "Calzado", "Type": "Zapatillas"},
            {"Mod": "A-1", "Talla": "K901", "Clase": "Calzado", "Type": "Zapatillas"},
            {"Mod": "A-1", "Talla": "REGRH", "Clase": "Calzado", "Type": "Zapatillas"},
        ])
        issues = []
        salida, issues = app.filter_centry_size_rows(hoja, issues, "Talla")
        self.assertEqual(list(salida["Talla"]), ["38"])
        self.assertTrue(any("no es una" in i["Problema"] for i in issues), issues)

    def test_la_talla_0_se_borra_en_calzado_cuando_hay_tallas_reales(self):
        hoja = self.hoja([
            {"Mod": "A-1", "Talla": "0", "Clase": "Calzado", "Type": "Zapatillas"},
            {"Mod": "A-1", "Talla": "38", "Clase": "Calzado", "Type": "Zapatillas"},
        ])
        salida, _ = app.filter_centry_size_rows(hoja, [], "Talla")
        self.assertEqual(list(salida["Talla"]), ["38"])

    def test_un_producto_de_UNA_sola_talla_0_no_desaparece(self):
        """Borrarla dejaba el producto entero fuera del archivo, sin decir nada."""
        hoja = self.hoja([{"Mod": "A-1", "Talla": "0", "Clase": "Calzado", "Type": "Zapatillas"}])
        salida, _ = app.filter_centry_size_rows(hoja, [], "Talla")
        self.assertEqual(len(salida), 1)

    def test_en_accesorios_la_0_se_quita_solo_si_hay_una_talla_real(self):
        con_real = self.hoja([
            {"Mod": "A-1", "Talla": "0", "Clase": "Accesorios", "Type": "Mochilas"},
            {"Mod": "A-1", "Talla": "S", "Clase": "Accesorios", "Type": "Mochilas"},
        ])
        salida, _ = app.filter_centry_size_rows(con_real, [], "Talla")
        self.assertEqual(list(salida["Talla"]), ["S"])

        sola = self.hoja([{"Mod": "A-1", "Talla": "0", "Clase": "Accesorios", "Type": "Mochilas"}])
        salida, _ = app.filter_centry_size_rows(sola, [], "Talla")
        self.assertEqual(len(salida), 1)

    def test_la_talla_unica_se_escribe_O_S(self):
        hoja = self.hoja([{"Mod": "A-1", "Talla": "UNICA", "Clase": "Accesorios", "Type": "Mochilas"}])
        salida, _ = app.filter_centry_size_rows(hoja, [], "Talla")
        self.assertEqual(list(salida["Talla"]), ["O/S"])

    def test_una_hoja_vacia_no_revienta(self):
        salida, issues = app.filter_centry_size_rows(pd.DataFrame(), [], "Talla")
        self.assertTrue(salida.empty)
        self.assertEqual(issues, [])


class TestLaMascaraPorValor(unittest.TestCase):
    def test_da_lo_mismo_que_map_y_pregunta_una_vez_por_valor(self):
        llamadas = []

        def predicado(valor):
            llamadas.append(valor)
            return str(valor).startswith("3")

        serie = pd.Series(["38", "38", "40", "38", "40"])
        salida = app._mascara_por_valor(serie, predicado)
        self.assertEqual(list(salida), list(serie.map(lambda v: str(v).startswith("3"))))
        self.assertEqual(sorted(llamadas), ["38", "40"], "pregunto mas de una vez por valor")

    def test_una_serie_vacia_devuelve_una_serie_vacia(self):
        self.assertTrue(app._mascara_por_valor(pd.Series([], dtype=object), bool).empty)


if __name__ == "__main__":
    unittest.main(verbosity=2)
