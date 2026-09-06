"""Pruebas del motor de la carga MANUAL a VTEX.

Origen: Forus tambien vende en VTEX (supermallpe) y ahi la carga no va por API,
se suben cuatro planillas a mano. El riesgo del cruce no es armar el Excel: es
CREAR DUPLICADOS. VTEX identifica por ID numerico y un producto que se genera
con el `Product ID` en blanco se crea de nuevo, con otra URL y otro ID, aunque
la referencia ya exista. Por eso la mitad de estas pruebas miran una sola cosa:
que un ID que esta en el catalogo maestro se REUTILICE y nunca se reemplace.

La estructura de las cuatro planillas sale de las exportaciones reales de
supermallpe (septiembre 2026). Los datos de ejemplo de aqui son los de esa
exportacion: producto 2 (HP102011307-251) con sus SKUs 310669/310670.

Ejecutar:  python scripts/test_engines_vtex_catalog.py
"""
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from engines import vtex_catalog as vtex  # noqa: E402


# --- Datos de ejemplo, con la forma EXACTA de la exportacion -------------
#
# Primera fila vacia y cabecera en la segunda, que es como VTEX entrega el
# archivo. Si el lector asumiera la fila 1, leeria la cabecera como un producto.

def _hoja(columnas, filas):
    hoja = [[""] * len(columnas), list(columnas)]
    for fila in filas:
        hoja.append([fila.get(columna, "") for columna in columnas])
    return hoja


def _fila_maestro(producto_id, referencia, sku_id, sku_nombre, **extra):
    fila = {
        "Product ID": producto_id,
        "Product Name": "ZAPATO HUSH PUPPIES STANFORD II PARA HOMBRE",
        "Active product": "Yes",
        "Description": "Slip on de cuero.",
        "Brand ID": "2000008",
        "Brand": "Hush Puppies",
        "Department ID": "25",
        "Department": "Hombre",
        "Category ID": "41",
        "Category": "Zapatos",
        "Sales channels": "1, 4",
        "Product URL": "zapato-hush-puppies-stanford-ii-para-hombre-hp102011307-251",
        "Page Title": "ZAPATO HUSH PUPPIES STANFORD II PARA HOMBRE 251",
        "Product reference code": referencia,
        "SKU ID": sku_id,
        "SKU name": sku_nombre,
        "SKU reference code": sku_id,
        "Active SKU": "Yes",
        "Package weight": "800",
        "Package width": "34",
        "Package height": "49.5",
        "Package length": "14",
        "Cubic Weight": "4.9088",
        "Unit of measure": "un",
        "Unit multiplier": "1",
        "Commercial condition": "Padrão",
    }
    fila.update(extra)
    return fila


MAESTRO = _hoja(vtex.COLUMNAS_PRODUCTOS_Y_SKUS, [
    _fila_maestro("2", "HP102011307-251", "310669", "TALLA 39"),
    _fila_maestro("2", "HP102011307-251", "310670", "TALLA 40"),
    _fila_maestro("7", "FM7048-GT4", "425933", "TALLA L",
                  **{"Product Name": "CAMISA PFG", "Department ID": "25", "Department": "Hombre",
                     "Category ID": "44", "Category": "Camisas", "Brand ID": "2000009",
                     "Brand": "Columbia", "Product URL": "camisa-pfg-fm7048-gt4"}),
])

ESPEC_PRODUCTO = _hoja(vtex.COLUMNAS_ESPECIFICACIONES_PRODUCTO, [
    {"ID del producto": "2", "Código de referencia del producto": "HP102011307-251",
     "Departamento": "Hombre", "Categoría": "Zapatos",
     "ID de campo": "24", "Nombre del campo": "Género", "Tipo de campo": "CheckBox",
     "IDs de valores de campo": "56,60,62,430", "Valores de campo": "Hombre|Mujer,Mujer,Hombre,Unisex",
     "IDs de especificación": "62", "Valores de especificación": "Hombre"},
    {"ID del producto": "2", "Código de referencia del producto": "HP102011307-251",
     "Departamento": "Hombre", "Categoría": "Zapatos",
     "ID de campo": "80", "Nombre del campo": "Modelo", "Tipo de campo": "Texto",
     "IDs de especificación": "586682", "Valores de especificación": "HP102011307"},
    {"ID del producto": "2", "Código de referencia del producto": "HP102011307-251",
     "Departamento": "Hombre", "Categoría": "Zapatos",
     "ID de campo": "89", "Nombre del campo": "Color", "Tipo de campo": "Texto",
     "Valores de especificación": "Rojo"},
])

ESPEC_SKU = _hoja(vtex.COLUMNAS_ESPECIFICACIONES_SKU, [
    {"ID de SKU": "310669", "Nombre de SKU": "TALLA 39", "Código de referencia de SKU": "310669",
     "Departamento": "Hombre", "Categoría": "Zapatos",
     "ID de campo": "28", "Nombre del campo": "Talla", "Tipo de campo": "Radio",
     "IDs de valores de campo": "141,142,143", "Valores de campo": "39,40,41",
     "IDs de especificación": "141", "Valores de especificación": "39"},
    {"ID de SKU": "310669", "Nombre de SKU": "TALLA 39", "Código de referencia de SKU": "310669",
     "Departamento": "Hombre", "Categoría": "Zapatos",
     "ID de campo": "29", "Nombre del campo": "Color", "Tipo de campo": "Radio",
     "IDs de valores de campo": "67,78", "Valores de campo": "Negro,Rojo",
     "IDs de especificación": "78", "Valores de especificación": "Rojo"},
])

IMAGENES = _hoja(vtex.COLUMNAS_IMAGENES, [
    {"ID del producto": "2", "ID de SKU": "310669", "Nombre de SKU": "TALLA 39",
     "Código de referencia de SKU": "310669", "ID de la imagen": "641130",
     "Posición de la imagen": "0", "Label de la imagen": "1",
     "Ruta de la imagen": "https://supermallpe.vteximg.com.br/arquivos/ids/641130/TALLA-39.jpg"},
])


def maestro(productos=None, espec_producto=ESPEC_PRODUCTO, espec_sku=ESPEC_SKU, imagenes=IMAGENES):
    return vtex.CatalogoMaestroVTEX.desde_filas(
        productos if productos is not None else MAESTRO,
        espec_producto, espec_sku, imagenes,
    )


def entrada(mod_col="HP102011307-251", **extra):
    base = {
        "mod_col": mod_col,
        "nombre": "ZAPATO HUSH PUPPIES STANFORD II PARA HOMBRE",
        "descripcion": "Slip on de cuero.",
        "marca": "Hush Puppies",
        "departamento": "Hombre",
        "categoria": "Zapatos",
        "color_web": "Rojo",
        "genero": "Hombre",
        "modelo": mod_col.rsplit("-", 1)[0],
        "skus": [{"talla": "39", "ean": "779000111"}, {"talla": "40", "ean": "779000112"}],
        "imagenes": ["https://bucket/HUSHPUPPIES/HP102011307_251_1.jpg"],
    }
    base.update(extra)
    return base


class TestLectura(unittest.TestCase):
    def test_la_cabecera_se_busca_no_se_asume(self):
        # La exportacion deja la fila 1 vacia. Con un indice fijo, un archivo
        # reguardado sin esa fila leeria la cabecera como si fuera un producto.
        self.assertEqual(vtex.detectar_fila_encabezado(MAESTRO, vtex.COLUMNAS_PRODUCTOS_Y_SKUS), 1)
        sin_fila_vacia = MAESTRO[1:]
        self.assertEqual(vtex.detectar_fila_encabezado(sin_fila_vacia, vtex.COLUMNAS_PRODUCTOS_Y_SKUS), 0)

    def test_sin_cabecera_reconocible_no_inventa_una(self):
        basura = [["a", "b"], ["1", "2"]]
        self.assertEqual(vtex.detectar_fila_encabezado(basura, vtex.COLUMNAS_PRODUCTOS_Y_SKUS), -1)
        registros, _, faltantes = vtex.registros_desde_filas(basura, vtex.COLUMNAS_PRODUCTOS_Y_SKUS)
        self.assertEqual(registros, [])
        self.assertEqual(len(faltantes), len(vtex.COLUMNAS_PRODUCTOS_Y_SKUS))

    def test_la_cabecera_repetida_de_la_segunda_hoja_no_entra_como_dato(self):
        # VTEX parte los archivos grandes en varias hojas y repite la cabecera.
        # Pegadas una tras otra, esa segunda cabecera seria un producto llamado
        # "Product ID".
        pegadas = MAESTRO + MAESTRO
        registros, _, _ = vtex.registros_desde_filas(pegadas, vtex.COLUMNAS_PRODUCTOS_Y_SKUS)
        self.assertEqual(len(registros), 6)
        self.assertNotIn("Product ID", [registro["Product ID"] for registro in registros])

    def test_las_columnas_pueden_venir_en_otro_orden(self):
        columnas = list(reversed(vtex.COLUMNAS_PRODUCTOS_Y_SKUS))
        hoja = _hoja(columnas, [_fila_maestro("2", "HP102011307-251", "310669", "TALLA 39")])
        registros, _, faltantes = vtex.registros_desde_filas(hoja, vtex.COLUMNAS_PRODUCTOS_Y_SKUS)
        self.assertEqual(faltantes, [])
        self.assertEqual(registros[0]["Product ID"], "2")
        self.assertEqual(registros[0]["SKU ID"], "310669")

    def test_un_id_numerico_de_excel_no_se_convierte_en_310669_punto_cero(self):
        # Excel devuelve floats. Un ".0" pegado convierte una referencia valida
        # en una que no empareja con nada.
        self.assertEqual(vtex.texto(310669.0), "310669")
        self.assertEqual(vtex.normalizar_referencia(310669.0), "310669")
        self.assertEqual(vtex.texto(4.9088), "4.9088")


class TestNormalizacion(unittest.TestCase):
    def test_la_talla_sale_del_nombre_del_sku(self):
        self.assertEqual(vtex.normalizar_talla("TALLA 39"), "39")
        self.assertEqual(vtex.normalizar_talla("Talla ST"), "ST")
        self.assertEqual(vtex.normalizar_talla("TALLA 10.5"), "10.5")
        self.assertEqual(vtex.normalizar_talla("10,5"), "10.5")
        self.assertEqual(vtex.normalizar_talla("40.0"), "40")
        self.assertEqual(vtex.normalizar_talla(""), "")

    def test_la_referencia_no_pierde_guiones_ni_ceros(self):
        # HP102011307-251 y HP102011307251 son productos distintos para VTEX.
        self.assertEqual(vtex.normalizar_referencia(" hp102011307-251 "), "HP102011307-251")
        self.assertNotEqual(vtex.normalizar_referencia("HP102011307-251"),
                            vtex.normalizar_referencia("HP102011307251"))
        self.assertEqual(vtex.normalizar_referencia("0310669"), "0310669")

    def test_peso_cubico_como_lo_calcula_la_tienda(self):
        # Verificado contra la exportacion real: 34 x 49.5 x 14 / 4800.
        self.assertEqual(vtex.peso_cubico("34", "49.5", "14"), "4.9088")
        self.assertEqual(vtex.peso_cubico("", "", ""), "")


class TestMaestro(unittest.TestCase):
    def test_indexa_referencias_ids_y_skus(self):
        m = maestro()
        self.assertEqual(m.producto("HP102011307-251")["Product ID"], "2")
        self.assertEqual(m.sku_por_referencia("310669")["SKU ID"], "310669")
        self.assertEqual({sku["SKU ID"] for sku in m.skus_de_producto("2")}, {"310669", "310670"})
        self.assertEqual(m.sku_por_talla("2", "39")["SKU ID"], "310669")
        self.assertIsNone(m.sku_por_talla("2", "45"))

    def test_conserva_la_relacion_producto_referencia_sku_referencia(self):
        m = maestro()
        for sku in m.skus_de_producto("2"):
            self.assertEqual(sku["_producto_id"], "2")
            self.assertEqual(sku["_referencia_producto"], "HP102011307-251")

    def test_marcas_y_categorias_salen_del_maestro(self):
        m = maestro()
        self.assertEqual(m.marca("hush puppies")["Brand ID"], "2000008")
        self.assertEqual(m.marca("HUSH PUPPIES")["Brand"], "Hush Puppies")
        self.assertIsNone(m.marca("Adidas"))
        self.assertEqual(m.categoria("Hombre", "Zapatos")["Category ID"], "41")
        self.assertIsNone(m.categoria("Hombre", "Paraguas"))

    def test_la_categoria_se_encuentra_aunque_el_departamento_no_calce(self):
        # El departamento es una suposicion (sale del genero); la categoria es
        # el dato. Una camisa que en VTEX vive en otro departamento tiene que
        # encontrarse igual y no quedarse sin ID.
        m = maestro()
        self.assertEqual(m.categoria("Niños", "Camisas")["Category ID"], "44")

    def test_referencia_repetida_en_dos_productos_queda_marcada(self):
        filas = MAESTRO + _hoja(
            vtex.COLUMNAS_PRODUCTOS_Y_SKUS,
            [_fila_maestro("99", "HP102011307-251", "999", "TALLA 41")],
        )[2:]
        m = maestro(productos=filas)
        self.assertIn("HP102011307-251", m.referencias_duplicadas)

    def test_los_valores_de_configuracion_se_copian_de_la_tienda(self):
        # "Padrão" es de esta tienda, no una constante del codigo.
        m = maestro()
        self.assertEqual(m.valor_por_defecto("Commercial condition", "x"), "Padrão")
        self.assertEqual(m.valor_por_defecto("Sales channels", "1"), "1, 4")
        self.assertEqual(m.valor_por_defecto("Columna que no existe", "respaldo"), "respaldo")


class TestMapeoDeIds(unittest.TestCase):
    def test_un_producto_que_existe_reutiliza_su_id(self):
        plan = vtex.plan_de_carga([entrada()], maestro())
        producto = plan["productos"][0]
        self.assertEqual(producto["producto_id"], "2")
        self.assertEqual(producto["estado"], vtex.ESTADO_EXISTENTE)
        self.assertEqual(plan["resumen"]["Productos existentes"], 1)
        self.assertEqual(plan["resumen"]["Productos nuevos"], 0)

    def test_un_producto_que_no_existe_va_con_el_id_en_blanco(self):
        plan = vtex.plan_de_carga([entrada("HP999999999-000")], maestro())
        producto = plan["productos"][0]
        self.assertEqual(producto["producto_id"], "")
        self.assertEqual(producto["estado"], vtex.ESTADO_NUEVO)
        self.assertTrue(any(alerta["Código"] == "producto_sin_id" for alerta in plan["alertas"]))

    def test_los_skus_que_existen_reutilizan_su_sku_id(self):
        plan = vtex.plan_de_carga([entrada()], maestro())
        ids = {sku["talla"]: sku["sku_id"] for sku in plan["productos"][0]["skus"]}
        self.assertEqual(ids, {"39": "310669", "40": "310670"})
        self.assertEqual(plan["resumen"]["SKUs nuevos"], 0)

    def test_una_talla_nueva_de_un_producto_existente_es_un_sku_nuevo(self):
        # El caso mas comun al ampliar la curva: el producto ya existe y solo
        # falta una talla.
        datos = entrada(skus=[{"talla": "39"}, {"talla": "41"}])
        plan = vtex.plan_de_carga([datos], maestro())
        por_talla = {sku["talla"]: sku for sku in plan["productos"][0]["skus"]}
        self.assertEqual(por_talla["39"]["sku_id"], "310669")
        self.assertEqual(por_talla["41"]["sku_id"], "")
        self.assertEqual(por_talla["41"]["referencia"], "HP102011307-251-41")
        self.assertEqual(plan["productos"][0]["producto_id"], "2")

    def test_nunca_se_reemplaza_un_id_existente_por_uno_generado(self):
        plan = vtex.plan_de_carga([entrada()], maestro())
        archivos = vtex.construir_archivos(plan, maestro())
        for fila in archivos[vtex.ARCHIVO_PRODUCTOS]["filas"]:
            self.assertEqual(fila["Product ID"], "2")
            self.assertIn(fila["SKU ID"], {"310669", "310670"})
            self.assertEqual(fila["SKU reference code"], fila["SKU ID"])

    def test_un_sku_de_otro_producto_no_se_reutiliza(self):
        # La referencia declarada apunta a un SKU que cuelga de otro producto:
        # reutilizarlo lo movería de ficha.
        datos = entrada(skus=[{"talla": "L", "referencia": "425933"}])
        plan = vtex.plan_de_carga([datos], maestro())
        sku = plan["productos"][0]["skus"][0]
        self.assertEqual(sku["sku_id"], "")
        self.assertTrue(any(alerta["Código"] == "sku_inconsistente" for alerta in plan["alertas"]))

    def test_el_patron_de_referencia_de_sku_nuevo_es_configurable(self):
        datos = entrada("XX1-A", skus=[{"talla": "39", "ean": "77911"}])
        plan = vtex.plan_de_carga([datos], maestro(),
                                  {"patron_referencia_sku": "{modelo}-{color}-{talla}"})
        self.assertEqual(plan["productos"][0]["skus"][0]["referencia"], "XX1-A-39")
        plan = vtex.plan_de_carga([datos], maestro(), {"patron_referencia_sku": "{ean}"})
        self.assertEqual(plan["productos"][0]["skus"][0]["referencia"], "77911")

    def test_un_patron_con_un_campo_que_no_existe_no_revienta(self):
        datos = entrada("XX1-A", skus=[{"talla": "39"}])
        plan = vtex.plan_de_carga([datos], maestro(), {"patron_referencia_sku": "{inventado}"})
        self.assertEqual(plan["productos"][0]["skus"][0]["referencia"], "XX1-A-39")


class TestValidaciones(unittest.TestCase):
    def _codigos(self, plan):
        return {alerta["Código"] for alerta in plan["alertas"]}

    def test_una_categoria_que_no_existe_en_vtex_bloquea(self):
        plan = vtex.plan_de_carga([entrada("NUEVO-1", categoria="Paraguas")], maestro())
        self.assertIn("producto_sin_categoria", self._codigos(plan))
        self.assertTrue(plan["bloqueado"])

    def test_una_marca_que_no_existe_en_vtex_bloquea(self):
        plan = vtex.plan_de_carga([entrada("NUEVO-1", marca="Adidas")], maestro())
        self.assertIn("producto_sin_marca", self._codigos(plan))
        self.assertTrue(plan["bloqueado"])

    def test_un_producto_sin_tallas_bloquea(self):
        plan = vtex.plan_de_carga([entrada(skus=[])], maestro())
        self.assertIn("sin_tallas", self._codigos(plan))
        self.assertTrue(plan["bloqueado"])

    def test_un_codigo_sin_datos_bloquea(self):
        plan = vtex.plan_de_carga([entrada(encontrado=False)], maestro())
        self.assertIn("codigo_no_encontrado", self._codigos(plan))
        self.assertTrue(plan["bloqueado"])

    def test_una_referencia_duplicada_en_el_maestro_bloquea(self):
        filas = MAESTRO + _hoja(vtex.COLUMNAS_PRODUCTOS_Y_SKUS,
                                [_fila_maestro("99", "HP102011307-251", "999", "TALLA 41")])[2:]
        plan = vtex.plan_de_carga([entrada()], maestro(productos=filas))
        self.assertIn("referencia_duplicada", self._codigos(plan))
        self.assertTrue(plan["bloqueado"])

    def test_dos_codigos_que_generan_la_misma_referencia_de_sku_bloquean(self):
        datos = [entrada("AA1-B", skus=[{"talla": "39"}]),
                 entrada("AA1-B ", skus=[{"talla": "39"}])]
        # El segundo es el mismo codigo con un espacio: se descarta como
        # duplicado y solo avisa.
        plan = vtex.plan_de_carga(datos, maestro())
        self.assertIn("codigo_duplicado", self._codigos(plan))
        self.assertEqual(len(plan["productos"]), 1)

    def test_un_producto_sin_fotos_solo_avisa(self):
        plan = vtex.plan_de_carga([entrada(imagenes=[])], maestro())
        self.assertIn("imagen_faltante", self._codigos(plan))
        self.assertFalse(plan["bloqueado"])

    def test_la_categoria_de_vtex_manda_sobre_la_que_propone_la_app(self):
        # El producto ya existe en Zapatos y la app propone Camisas: se respeta
        # VTEX y se avisa. Cambiarla movería el producto de sitio en la web.
        plan = vtex.plan_de_carga([entrada(categoria="Camisas")], maestro())
        self.assertEqual(plan["productos"][0]["categoria"]["Category ID"], "41")
        self.assertIn("producto_inconsistente", self._codigos(plan))
        self.assertFalse(plan["bloqueado"])

    def test_la_marca_de_vtex_manda_sobre_la_que_propone_la_app(self):
        plan = vtex.plan_de_carga([entrada(marca="Columbia")], maestro())
        self.assertEqual(plan["productos"][0]["marca"]["Brand ID"], "2000008")
        self.assertIn("producto_inconsistente", self._codigos(plan))

    def test_los_avisos_no_bloquean_y_los_errores_si(self):
        plan = vtex.plan_de_carga([entrada("NUEVO-1", categoria="Zapatos")], maestro())
        self.assertEqual(self._codigos(plan) & {"producto_sin_id", "sku_sin_id"},
                         {"producto_sin_id", "sku_sin_id"})
        self.assertFalse(plan["bloqueado"])

    def test_el_resumen_cuenta_lo_que_dice_la_vista_previa(self):
        plan = vtex.plan_de_carga([entrada(), entrada("NUEVO-1", categoria="Zapatos")], maestro())
        resumen = plan["resumen"]
        self.assertEqual(resumen["Productos encontrados"], 2)
        self.assertEqual(resumen["Productos existentes"], 1)
        self.assertEqual(resumen["Productos nuevos"], 1)
        self.assertEqual(resumen["SKUs encontrados"], len(plan["filas"]))
        self.assertEqual(resumen["SKUs existentes"] + resumen["SKUs nuevos"],
                         resumen["SKUs encontrados"])


class TestArchivos(unittest.TestCase):
    def setUp(self):
        self.maestro = maestro()
        self.plan = vtex.plan_de_carga([entrada()], self.maestro)
        self.archivos = vtex.construir_archivos(self.plan, self.maestro)

    def test_son_cuatro_y_con_las_columnas_exactas_de_la_plantilla(self):
        self.assertEqual(set(self.archivos), set(vtex.ORDEN_ARCHIVOS))
        for nombre, tabla in self.archivos.items():
            self.assertEqual(tuple(tabla["columnas"]), vtex.COLUMNAS_POR_ARCHIVO[nombre])
            for fila in tabla["filas"]:
                # Ni una columna de mas ni una de menos, y en el mismo orden.
                self.assertEqual(list(fila), list(tabla["columnas"]))

    def test_los_cuatro_archivos_usan_los_mismos_ids(self):
        productos = self.archivos[vtex.ARCHIVO_PRODUCTOS]["filas"]
        ids_producto = {fila["Product ID"] for fila in productos}
        ids_sku = {fila["SKU ID"] for fila in productos}
        for fila in self.archivos[vtex.ARCHIVO_ESPEC_PRODUCTO]["filas"]:
            self.assertIn(fila["ID del producto"], ids_producto)
        for fila in self.archivos[vtex.ARCHIVO_ESPEC_SKU]["filas"]:
            self.assertIn(fila["ID de SKU"], ids_sku)
        for fila in self.archivos[vtex.ARCHIVO_IMAGENES]["filas"]:
            self.assertIn(fila["ID del producto"], ids_producto)
            self.assertIn(fila["ID de SKU"], ids_sku)

    def test_las_referencias_tambien_son_consistentes(self):
        referencias = {fila["SKU ID"]: fila["SKU reference code"]
                       for fila in self.archivos[vtex.ARCHIVO_PRODUCTOS]["filas"]}
        for fila in self.archivos[vtex.ARCHIVO_ESPEC_SKU]["filas"]:
            self.assertEqual(fila["Código de referencia de SKU"], referencias[fila["ID de SKU"]])
        for fila in self.archivos[vtex.ARCHIVO_IMAGENES]["filas"]:
            self.assertEqual(fila["Código de referencia de SKU"], referencias[fila["ID de SKU"]])

    def test_hay_una_fila_por_sku_no_una_por_producto(self):
        self.assertEqual(len(self.archivos[vtex.ARCHIVO_PRODUCTOS]["filas"]), 2)

    def test_un_producto_que_ya_existe_no_se_reescribe(self):
        # Reescribir el nombre, la URL o la meta description de un producto
        # publicado le cambia el SEO sin que nadie lo haya pedido.
        plan = vtex.plan_de_carga([entrada(nombre="OTRO NOMBRE")], self.maestro)
        fila = vtex.construir_archivos(plan, self.maestro)[vtex.ARCHIVO_PRODUCTOS]["filas"][0]
        self.assertEqual(fila["Product Name"], "ZAPATO HUSH PUPPIES STANFORD II PARA HOMBRE")
        self.assertEqual(fila["Product URL"],
                         "zapato-hush-puppies-stanford-ii-para-hombre-hp102011307-251")

    def test_con_actualizar_existentes_si_se_reescribe_el_nombre(self):
        plan = vtex.plan_de_carga([entrada(nombre="OTRO NOMBRE")], self.maestro,
                                  {"actualizar_existentes": True})
        fila = vtex.construir_archivos(plan, self.maestro)[vtex.ARCHIVO_PRODUCTOS]["filas"][0]
        self.assertEqual(fila["Product Name"], "OTRO NOMBRE")
        # Pero la URL de un producto publicado sigue siendo la de VTEX.
        self.assertEqual(fila["Product URL"],
                         "zapato-hush-puppies-stanford-ii-para-hombre-hp102011307-251")

    def test_un_producto_nuevo_arma_url_titulo_y_meta_como_la_tienda(self):
        plan = vtex.plan_de_carga(
            [entrada("HP999-251", nombre="ZAPATO NUEVO", categoria="Zapatos")], self.maestro)
        fila = vtex.construir_archivos(plan, self.maestro)[vtex.ARCHIVO_PRODUCTOS]["filas"][0]
        self.assertEqual(fila["Product ID"], "")
        self.assertEqual(fila["Product URL"], "zapato-nuevo-hp999-251")
        self.assertEqual(fila["Page Title"], "ZAPATO NUEVO 251")
        self.assertIn("HP999-251", fila["Meta description"])
        self.assertEqual(fila["Brand ID"], "2000008")
        self.assertEqual(fila["Category ID"], "41")
        self.assertEqual(fila["Sales channels"], "1, 4")

    def test_las_medidas_de_un_sku_existente_salen_del_maestro(self):
        fila = self.archivos[vtex.ARCHIVO_PRODUCTOS]["filas"][0]
        self.assertEqual(fila["Package weight"], "800")
        self.assertEqual(fila["Cubic Weight"], "4.9088")

    def test_una_talla_nueva_hereda_las_medidas_de_sus_hermanas(self):
        # Se despacha en la misma caja. Sin esto sale sin peso y VTEX no puede
        # cotizar el envio de ese SKU.
        plan = vtex.plan_de_carga([entrada(skus=[{"talla": "41"}])], self.maestro)
        fila = vtex.construir_archivos(plan, self.maestro)[vtex.ARCHIVO_PRODUCTOS]["filas"][0]
        self.assertEqual(fila["SKU ID"], "")
        self.assertEqual(fila["Package weight"], "800")
        self.assertEqual(fila["Cubic Weight"], "4.9088")

    def test_el_peso_cubico_de_un_sku_nuevo_se_calcula(self):
        datos = entrada("HP999-251", categoria="Zapatos",
                        paquete={"weight": "800", "width": "34", "height": "49.5", "length": "14"})
        plan = vtex.plan_de_carga([datos], self.maestro)
        fila = vtex.construir_archivos(plan, self.maestro)[vtex.ARCHIVO_PRODUCTOS]["filas"][0]
        self.assertEqual(fila["Cubic Weight"], "4.9088")

    def test_las_imagenes_van_una_por_foto_con_su_orden(self):
        datos = entrada(imagenes=["https://bucket/a.jpg", "https://bucket/b.jpg"])
        plan = vtex.plan_de_carga([datos], self.maestro)
        filas = vtex.construir_archivos(plan, self.maestro)[vtex.ARCHIVO_IMAGENES]["filas"]
        # Dos SKUs por dos fotos.
        self.assertEqual(len(filas), 4)
        self.assertEqual([fila["Label de la imagen"] for fila in filas], ["1", "2", "1", "2"])
        self.assertEqual({fila["Posición de la imagen"] for fila in filas}, {"0"})
        self.assertEqual([fila["URL de importación de la imagen"] for fila in filas[:2]],
                         ["https://bucket/a.jpg", "https://bucket/b.jpg"])
        self.assertEqual({fila["ID de la imagen"] for fila in filas}, {""})

    def test_se_pueden_saltar_los_skus_que_ya_tienen_fotos(self):
        plan = vtex.plan_de_carga([entrada()], self.maestro, {"solo_sin_imagenes": True})
        filas = vtex.construir_archivos(plan, self.maestro)[vtex.ARCHIVO_IMAGENES]["filas"]
        # 310669 ya tiene una foto en el maestro; 310670 no.
        self.assertEqual({fila["ID de SKU"] for fila in filas}, {"310670"})

    def test_la_hoja_deja_la_fila_en_blanco_y_la_cabecera_en_la_segunda(self):
        filas = vtex.filas_para_hoja(vtex.ARCHIVO_PRODUCTOS, self.archivos[vtex.ARCHIVO_PRODUCTOS])
        self.assertEqual(filas[0], [""] * len(vtex.COLUMNAS_PRODUCTOS_Y_SKUS))
        self.assertEqual(filas[1], list(vtex.COLUMNAS_PRODUCTOS_Y_SKUS))
        self.assertEqual(filas[2][0], "2")

    def test_lo_generado_se_puede_volver_a_leer(self):
        # Si el archivo generado no se puede releer como maestro, el flujo se
        # rompe la siguiente vez que se exporte VTEX.
        filas = vtex.filas_para_hoja(vtex.ARCHIVO_PRODUCTOS, self.archivos[vtex.ARCHIVO_PRODUCTOS])
        releido = vtex.CatalogoMaestroVTEX.desde_filas(filas)
        self.assertEqual(releido.producto("HP102011307-251")["Product ID"], "2")


class TestEspecificaciones(unittest.TestCase):
    def setUp(self):
        self.maestro = maestro()

    def test_los_campos_salen_del_diccionario_de_la_tienda(self):
        plan = vtex.plan_de_carga([entrada()], self.maestro)
        filas = vtex.construir_archivos(plan, self.maestro)[vtex.ARCHIVO_ESPEC_PRODUCTO]["filas"]
        campos = {fila["Nombre del campo"]: fila for fila in filas}
        self.assertIn("Género", campos)
        self.assertIn("Modelo", campos)
        self.assertEqual(campos["Género"]["ID de campo"], "24")
        self.assertEqual(campos["Género"]["Valores de especificación"], "Hombre")

    def test_un_valor_que_no_esta_en_la_lista_avisa_y_no_se_emite(self):
        # Un Radio con un valor que la tienda no tiene no se carga: hay que
        # avisarlo ANTES de bajar el ZIP, no cuando VTEX rechace la fila.
        plan = vtex.plan_de_carga([entrada(genero="Marciano")], self.maestro)
        self.assertTrue(any(alerta["Código"] == "valor_fuera_de_lista" for alerta in plan["alertas"]))
        filas = vtex.construir_archivos(plan, self.maestro)[vtex.ARCHIVO_ESPEC_PRODUCTO]["filas"]
        self.assertNotIn("Género", {fila["Nombre del campo"] for fila in filas})
        self.assertFalse(plan["bloqueado"])

    def test_el_id_del_valor_sale_de_la_lista_del_campo(self):
        plan = vtex.plan_de_carga([entrada()], self.maestro)
        filas = vtex.construir_archivos(plan, self.maestro)[vtex.ARCHIVO_ESPEC_SKU]["filas"]
        talla_39 = [fila for fila in filas
                    if fila["Nombre del campo"] == "Talla" and fila["ID de SKU"] == "310669"][0]
        self.assertEqual(talla_39["IDs de especificación"], "141")
        self.assertEqual(talla_39["Valores de especificación"], "39")

    def test_cada_sku_lleva_su_talla_no_la_del_vecino(self):
        plan = vtex.plan_de_carga([entrada()], self.maestro)
        filas = vtex.construir_archivos(plan, self.maestro)[vtex.ARCHIVO_ESPEC_SKU]["filas"]
        por_sku = {}
        for fila in filas:
            if fila["Nombre del campo"] == "Talla":
                por_sku[fila["ID de SKU"]] = fila["Valores de especificación"]
        self.assertEqual(por_sku, {"310669": "39", "310670": "40"})

    def test_sin_el_diccionario_no_se_inventan_ids_de_campo(self):
        # Los ID de campo son propios de cada cuenta de VTEX. Sin la
        # exportacion de especificaciones, el archivo sale vacio a proposito.
        m = maestro(espec_producto=None, espec_sku=None)
        plan = vtex.plan_de_carga([entrada()], m)
        archivos = vtex.construir_archivos(plan, m)
        self.assertEqual(archivos[vtex.ARCHIVO_ESPEC_PRODUCTO]["filas"], [])
        self.assertEqual(archivos[vtex.ARCHIVO_ESPEC_SKU]["filas"], [])
        # Y las otras dos planillas se generan igual.
        self.assertTrue(archivos[vtex.ARCHIVO_PRODUCTOS]["filas"])


class TestVistaPrevia(unittest.TestCase):
    def test_trae_las_columnas_que_pide_la_pantalla(self):
        plan = vtex.plan_de_carga([entrada()], maestro())
        for fila in plan["filas"]:
            for columna in ("Modelo", "Color", "Product Ref", "Product ID",
                            "SKU Ref", "SKU ID", "Talla", "Fotos", "Estado", "Detalle"):
                self.assertIn(columna, fila)

    def test_una_talla_nueva_se_ve_como_NUEVO_aunque_el_producto_exista(self):
        # Verla como "EXISTENTE" esconde justo lo que se va a crear.
        plan = vtex.plan_de_carga([entrada(skus=[{"talla": "39"}, {"talla": "41"}])], maestro())
        por_talla = {fila["Talla"]: fila["Estado"] for fila in plan["filas"]}
        self.assertEqual(por_talla["39"], vtex.ESTADO_EXISTENTE)
        self.assertEqual(por_talla["41"], vtex.ESTADO_NUEVO)

    def test_el_estado_es_uno_de_los_cuatro(self):
        datos = [entrada(), entrada("NUEVO-1", categoria="Zapatos"), entrada("X-1", marca="Adidas")]
        plan = vtex.plan_de_carga(datos, maestro())
        validos = {vtex.ESTADO_EXISTENTE, vtex.ESTADO_NUEVO, vtex.ESTADO_ERROR, vtex.ESTADO_WARNING}
        self.assertTrue({fila["Estado"] for fila in plan["filas"]} <= validos)


class TestIntegracionConLaPantalla(unittest.TestCase):
    """Lo que la pantalla le pide al motor tiene que existir.

    Es la misma leccion del Status de carga: las pruebas cubrian el motor y
    nadie tocaba la funcion que dibuja, asi que una clave mal escrita tumbaba
    la pantalla entera en produccion.
    """

    def setUp(self):
        self.fuente = (ROOT / "app_matrixify.py").read_text(encoding="utf-8-sig")

    def test_todo_lo_que_la_pantalla_pide_al_motor_existe(self):
        import re
        pedidos = set(re.findall(r"vtex_motor\.([A-Za-z_][A-Za-z0-9_]*)", self.fuente))
        self.assertTrue(pedidos, "La pantalla no usa el motor.")
        for nombre in sorted(pedidos):
            self.assertTrue(hasattr(vtex, nombre), f"El motor no expone {nombre}")

    def test_la_pantalla_tiene_llamador(self):
        # Ya paso dos veces: se define un panel y nunca se invoca.
        self.assertIn("def render_vtex_export(", self.fuente)
        self.assertIn("render_vtex_export(brand_config, shopify_config)", self.fuente)

    def test_la_opcion_esta_en_el_menu_de_carga_parcial(self):
        self.assertIn("VTEX_LABEL: \"vtex\"", self.fuente)
        self.assertIn('if update_operation == "vtex":', self.fuente)

    def test_la_cache_del_maestro_tiene_la_firma_en_la_clave(self):
        """`firma` sin guion bajo, `_archivos` con guion bajo.

        Streamlit ignora los parametros que empiezan con guion bajo al armar la
        clave de cache. Los archivos van asi a proposito (hashear 100 MB en cada
        rerun costaria mas que la lectura), pero si la firma tambien llevara
        guion bajo la clave seria SIEMPRE la misma: subir un maestro nuevo
        devolveria el anterior, con los IDs viejos, y nadie se enteraria.
        """
        import ast as _ast
        arbol = _ast.parse(self.fuente)
        definicion = [nodo for nodo in _ast.walk(arbol)
                      if isinstance(nodo, _ast.FunctionDef) and nodo.name == "vtex_maestro_cacheado"]
        self.assertEqual(len(definicion), 1)
        nombres = [argumento.arg for argumento in definicion[0].args.args]
        self.assertEqual(nombres, ["firma", "_archivos"])

    def test_el_maestro_se_lee_sin_cargar_el_excel_entero(self):
        # 100 MB con `pd.read_excel` no caben en Streamlit Cloud.
        inicio = self.fuente.index("def vtex_hojas_de_archivo(")
        fin = self.fuente.index("def vtex_filas_de_archivo(")
        cuerpo = self.fuente[inicio:fin]
        self.assertIn("read_only=True", cuerpo)

    def test_el_motor_no_importa_streamlit_ni_pandas(self):
        fuente = (ROOT / "engines" / "vtex_catalog.py").read_text(encoding="utf-8")
        self.assertNotIn("import streamlit", fuente)
        self.assertNotIn("import pandas", fuente)

    def test_la_pantalla_no_escribe_en_vtex(self):
        # La app NO se conecta a VTEX: genera archivos. Si alguien mete una
        # llamada HTTP en esta pantalla, esto lo delata.
        inicio = self.fuente.index("def render_vtex_export(")
        fin = self.fuente.index("\ndef main():")
        cuerpo = self.fuente[inicio:fin]
        for prohibido in ("urlopen", "requests.", "vtexcommercestable", "http://", "api.vtex"):
            self.assertNotIn(prohibido, cuerpo)


if __name__ == "__main__":
    unittest.main(verbosity=2)
