#!/usr/bin/env python3
"""Los tres mantenedores "directos": el codigo modelo color y el dato ya hecho.

Pedido del usuario, septiembre de 2026, en una sola frase para los tres:

- **Videos**: *"poder dar el link del video en el Excel"*. El mantenedor solo
  sabia buscar el mp4 en el bucket con su nombre canonico
  (`MARCA/MODELO_COLOR_2.mp4`), asi que un video con otro nombre o en otro
  sitio no habia forma de publicarlo: tocaba renombrar el archivo en el bucket.
- **Tallas**: *"quisiera subir el codigo modelo color y los skus y su variant
  opcion con la talla que quiero que salga"*. El mantenedor decidia la talla
  por REGLA -- la guia de la marca, el genero, la escala del sitio -- y eso
  resuelve el catalogo entero, pero no el caso suelto: una curva que la guia no
  cubre, un producto mal tipificado. Ahi la persona ya sabe lo que tiene que
  decir cada variante y no habia como decirselo a la app.
- **Body HTML**: *"que pueda subir el codigo modelo color y ya listo con el
  body html hecho"*. `build_body_html` ARMA la ficha con sus partes, asi que un
  HTML ya terminado salia envuelto en una seccion `Descripción` que nadie
  pidio.

Estas pruebas EJECUTAN el codigo, no lo leen. Es la leccion de `start_suelto`
(seccion 5 duotrigies): sus ocho pruebas miraban el codigo fuente con
`inspect.getsource` y ninguna lo llamaba, asi que un `AttributeError` que hacia
imposible ejecutarlo no lo vio nadie. **Leer el codigo no es ejecutarlo.**

Shopify es falso: no se sale a la red.
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
if str(RAIZ) not in sys.path:
    sys.path.insert(0, str(RAIZ))

import pandas as pd  # noqa: E402

import app_matrixify as app  # noqa: E402
import generate_columbia_matrixify as gen  # noqa: E402
from engines import orden_tallas, video_media  # noqa: E402


# =========================================================================
# 1. Mantenedor de Videos: el link del Excel
# =========================================================================

class TestElLinkDelExcelMandaSobreElBucket(unittest.TestCase):
    def test_sin_link_se_arma_la_direccion_de_siempre(self):
        """La regresion que importa: lo que ya funcionaba no cambia."""
        destino = video_media.destino_del_video("COLUMBIA", "2044361", "6RX")
        self.assertTrue(destino["URL"].endswith("/COLUMBIA/2044361_6RX_2.mp4"))
        self.assertEqual(destino["Carpeta"], "COLUMBIA")
        self.assertEqual(destino["Origen"], video_media.ORIGEN_BUCKET)

    def test_con_link_se_usa_tal_cual(self):
        destino = video_media.destino_del_video(
            "COLUMBIA", "2044361", "6RX",
            url_explicita="https://otro.sitio/videos/el-video-bueno.mp4")
        self.assertEqual(destino["URL"], "https://otro.sitio/videos/el-video-bueno.mp4")
        self.assertEqual(destino["Origen"], video_media.ORIGEN_EXCEL)

    def test_el_nombre_del_media_sigue_siendo_el_canonico(self):
        """No es cosmetico: es con lo que `video_existente` reconoce el video
        de este producto. Con el nombre del link, el mismo video se podria
        publicar dos veces."""
        destino = video_media.destino_del_video(
            "COLUMBIA", "2044361", "6RX",
            url_explicita="https://otro.sitio/videos/cualquier-nombre.mp4")
        self.assertEqual(destino["Nombre"], "2044361_6RX_2.mp4")

    def test_con_link_no_hace_falta_la_marca(self):
        """Lo unico que salia de la marca era la carpeta del bucket. Exigirla
        dejaria fuera un codigo cuyo video la persona ya nos dio."""
        trabajos, descartes = video_media.trabajos_desde_codigos(
            ["2044361-6RX"], marcas={}, marca_por_defecto="",
            urls={"2044361-6RX": "https://otro.sitio/v.mp4"})
        self.assertEqual(descartes, [])
        self.assertEqual(trabajos[0]["URL"], "https://otro.sitio/v.mp4")
        self.assertEqual(trabajos[0]["Marca"], "")

    def test_sin_link_y_sin_marca_no_hay_url(self):
        """Lo de antes, intacto: sin marca no hay carpeta que armar."""
        trabajos, _ = video_media.trabajos_desde_codigos(["2044361-6RX"])
        self.assertEqual(trabajos[0]["URL"], "")

    def test_un_valor_que_no_es_url_se_descarta_diciendo_por_que(self):
        """Seguir adelante publicaria el video del BUCKET cuando la persona
        pidio otro archivo. Es peor que no hacer nada."""
        trabajos, descartes = video_media.trabajos_desde_codigos(
            ["2044361-6RX"], urls={"2044361-6RX": "el_video.mp4"})
        self.assertEqual(trabajos, [])
        self.assertEqual(len(descartes), 1)
        self.assertIn("no es una dirección", descartes[0]["Motivo"])

    def test_es_url_solo_acepta_http(self):
        self.assertTrue(video_media.es_url("https://x/y.mp4"))
        self.assertTrue(video_media.es_url("http://x/y.mp4"))
        self.assertFalse(video_media.es_url("COLUMBIA/y.mp4"))
        self.assertFalse(video_media.es_url(""))


class TestLaColumnaDeLinkSeLee(unittest.TestCase):
    def test_lee_la_columna_url(self):
        df = pd.DataFrame([{"Código Modelo Color": "2044361-6RX", "URL": "https://x/v.mp4"}])
        self.assertEqual(app.video_urls_del_excel(df), {"2044361-6RX": "https://x/v.mp4"})

    def test_tambien_se_puede_llamar_link(self):
        df = pd.DataFrame([{"Mod-Col": "2044361-6RX", "Link del video": "https://x/v.mp4"}])
        self.assertEqual(app.video_urls_del_excel(df), {"2044361-6RX": "https://x/v.mp4"})

    def test_sin_la_columna_devuelve_vacio(self):
        """La columna es OPCIONAL: lo normal es no traerla."""
        df = pd.DataFrame([{"Código Modelo Color": "2044361-6RX", "Marca": "COLUMBIA"}])
        self.assertEqual(app.video_urls_del_excel(df), {})

    def test_una_columna_llamada_video_no_se_confunde_con_un_link(self):
        """"Video" a secas suele traer el NOMBRE del archivo, no su direccion.
        Leerla como link publicaria cualquier cosa."""
        df = pd.DataFrame([{"Mod-Col": "2044361-6RX", "Video": "2044361_6RX_2.mp4"}])
        self.assertEqual(app.video_urls_del_excel(df), {})


class ShopifyFalsoDeVideos:
    """Lo minimo para que `video_publicar` llegue hasta el final."""

    def __init__(self):
        self.bajado_de = ""
        self.media_creado = {}


def _parchar_video(test, tienda, producto=None):
    """Sustituye los viajes de red de `video_publicar`. Devuelve el original."""
    producto = producto or {
        "Title": "Casaca", "Product ID": "gid://shopify/Product/1", "Marca": "",
    }

    def _descargar(url, timeout=120):
        tienda.bajado_de = url
        return b"x" * 5000, "video/mp4", "v.mp4", url

    def _publicar_en_shopify(config, gid, nombre, contenido, alt=""):
        tienda.media_creado = {"nombre": nombre, "bytes": len(contenido)}
        return {"id": "gid://shopify/MediaImage/9"}, "ok"

    originales = {
        "video_buscar_producto": app.video_buscar_producto,
        "video_descargar_del_bucket": app.video_descargar_del_bucket,
        "video_publicar_en_shopify": app.video_publicar_en_shopify,
        "video_leer_galeria": app.video_leer_galeria,
        "video_esperar_procesado": app.video_esperar_procesado,
        "video_colocar_en_posicion": app.video_colocar_en_posicion,
    }
    app.video_buscar_producto = lambda *a, **k: (producto, "catálogo")
    app.video_descargar_del_bucket = _descargar
    app.video_publicar_en_shopify = _publicar_en_shopify
    app.video_leer_galeria = lambda *a, **k: ({"media": []}, "")
    app.video_esperar_procesado = lambda *a, **k: (video_media.ESTADO_LISTO, "")
    app.video_colocar_en_posicion = lambda *a, **k: (video_media.POSICION_VIDEO, "posición 2", True)

    def _restaurar():
        for nombre, funcion in originales.items():
            setattr(app, nombre, funcion)

    test.addCleanup(_restaurar)


class TestVideoPublicarConLink(unittest.TestCase):
    """Se EJECUTA `video_publicar`, que es lo que pulsa el boton."""

    def test_baja_el_link_del_excel_y_no_el_del_bucket(self):
        tienda = ShopifyFalsoDeVideos()
        _parchar_video(self, tienda)
        resultado = app.video_publicar(
            {}, "columbia", "2044361-6RX", marca_pantalla="COLUMBIA",
            url_excel="https://otro.sitio/el-bueno.mp4")
        self.assertTrue(resultado["ok"], resultado["pasos"])
        self.assertEqual(tienda.bajado_de, "https://otro.sitio/el-bueno.mp4")

    def test_sin_marca_de_ningun_lado_publica_igual_si_hay_link(self):
        """El caso que antes moria en "Falta la marca."."""
        tienda = ShopifyFalsoDeVideos()
        _parchar_video(self, tienda)
        resultado = app.video_publicar(
            {}, "columbia", "2044361-6RX", url_excel="https://otro.sitio/el-bueno.mp4")
        self.assertTrue(resultado["ok"], resultado["pasos"])
        self.assertEqual(resultado["pasos"]["marca"]["estado"], "ok")

    def test_sin_marca_y_sin_link_sigue_fallando_en_la_marca(self):
        """La regresion: sin link, la marca sigue siendo obligatoria porque de
        ella sale la carpeta del bucket."""
        tienda = ShopifyFalsoDeVideos()
        _parchar_video(self, tienda)
        resultado = app.video_publicar({}, "columbia", "2044361-6RX")
        self.assertFalse(resultado["ok"])
        self.assertEqual(resultado["pasos"]["marca"]["estado"], "error")

    def test_el_media_se_crea_con_el_nombre_canonico(self):
        tienda = ShopifyFalsoDeVideos()
        _parchar_video(self, tienda)
        app.video_publicar({}, "columbia", "2044361-6RX",
                           url_excel="https://otro.sitio/cualquier-cosa.mp4")
        self.assertEqual(tienda.media_creado["nombre"], "2044361_6RX_2.mp4")

    def test_un_link_que_no_es_url_no_cae_al_bucket_en_silencio(self):
        tienda = ShopifyFalsoDeVideos()
        _parchar_video(self, tienda)
        resultado = app.video_publicar({}, "columbia", "2044361-6RX",
                                       marca_pantalla="COLUMBIA", url_excel="no-es-url")
        self.assertFalse(resultado["ok"])
        self.assertEqual(tienda.bajado_de, "")

    def test_sin_link_se_comporta_igual_que_antes(self):
        tienda = ShopifyFalsoDeVideos()
        _parchar_video(self, tienda)
        resultado = app.video_publicar({}, "columbia", "2044361-6RX", marca_pantalla="COLUMBIA")
        self.assertTrue(resultado["ok"], resultado["pasos"])
        self.assertIn("/COLUMBIA/2044361_6RX_2.mp4", tienda.bajado_de)


class TestElLinkLlegaAlRunner(unittest.TestCase):
    """Sin esto el runner rearmaria la direccion del bucket y publicaria un
    video distinto del que se reviso en pantalla -- o ninguno."""

    def test_la_vista_previa_lleva_el_link(self):
        filas = [{
            "Código Modelo Color": "2044361-6RX", "Marca": "COLUMBIA",
            "Origen de la marca": "metacampo", "URL": "https://x/v.mp4",
            "URL Excel": "https://x/v.mp4", "Estado": video_media.ESTADO_LISTO_PARA_CARGAR,
            "Origen del video": video_media.ORIGEN_EXCEL,
        }]
        previa = app.video_vista_previa(filas, {"site_label": "Vans.pe", "site_key": "vans"})
        self.assertEqual(previa.iloc[0]["URL excel"], "https://x/v.mp4")

    def test_apply_shopify_preview_se_lo_pasa_a_video_publicar(self):
        """Se EJECUTA la rama del aplicador, que es la que corre en el runner."""
        vistos = {}
        original = app.video_publicar

        def _falso(config, site_key, mod_col, **kwargs):
            vistos.update(kwargs)
            return {"ok": True, "pasos": {}, "Posición": video_media.POSICION_VIDEO}

        app.video_publicar = _falso
        self.addCleanup(lambda: setattr(app, "video_publicar", original))
        previa = pd.DataFrame([{
            "Operacion": "videos", "Site key": "vans", "Mod-Col": "2044361-6RX",
            "Handle": "x", "URL excel": "https://x/v.mp4",
            "Marca excel": "", "Marca pantalla": "VANS", "Reemplazar": "NO",
        }])
        app.apply_shopify_preview({}, previa)
        self.assertEqual(vistos.get("url_excel"), "https://x/v.mp4")


# =========================================================================
# 2. Mantenedor de Tallas: la talla que yo indico
# =========================================================================

def _producto_con_tallas(pares, mod_col="AB123-001", tipo="Zapatillas"):
    """`pares` es [(SKU, talla)] en el orden en que estan hoy en la ficha."""
    return {
        "Mod-Col": mod_col, "Handle": "h", "Title": "Bota", "Marca": "COLUMBIA",
        "Type": tipo, "Genero": "Masculino", "Product ID": "gid://shopify/Product/1",
        "Variants": [
            {"Variant GID": f"gid://shopify/ProductVariant/{i}",
             "Variant SKU": sku, "Option1 Name": "Talla", "Option1 Value": talla}
            for i, (sku, talla) in enumerate(pares, start=1)
        ],
    }


class TestElExcelDeTallas(unittest.TestCase):
    def test_una_fila_por_variante(self):
        df = pd.DataFrame([
            {"Código Modelo Color": "AB123-001", "SKU": "S1", "Talla": "40"},
            {"Código Modelo Color": "AB123-001", "SKU": "S2", "Talla": "41"},
        ])
        pedidas, descartes = app.tallas_pedidas_desde_excel(df)
        self.assertEqual(pedidas, {"AB123-001": {"S1": "40", "S2": "41"}})
        self.assertEqual(descartes, [])

    def test_el_codigo_repetido_no_se_dedupica(self):
        """`png_codigos_desde_excel` dedupica codigos, y por eso NO se usa aqui:
        la segunda talla del mismo producto se perderia."""
        df = pd.DataFrame([
            {"Mod-Col": "AB123-001", "SKU": "S1", "Option1 Value": "40"},
            {"Mod-Col": "AB123-001", "SKU": "S2", "Option1 Value": "41"},
            {"Mod-Col": "AB123-001", "SKU": "S3", "Option1 Value": "42"},
        ])
        pedidas, _ = app.tallas_pedidas_desde_excel(df)
        self.assertEqual(len(pedidas["AB123-001"]), 3)

    def test_nombra_la_columna_que_falta(self):
        """"Faltan columnas" obliga a adivinar cual de las tres."""
        df = pd.DataFrame([{"Mod-Col": "AB123-001", "Talla": "40"}])
        pedidas, descartes = app.tallas_pedidas_desde_excel(df)
        self.assertEqual(pedidas, {})
        self.assertIn("SKU", descartes[0]["Motivo"])

    def test_una_talla_vacia_no_borra(self):
        df = pd.DataFrame([
            {"Mod-Col": "AB123-001", "SKU": "S1", "Talla": "40"},
            {"Mod-Col": "AB123-001", "SKU": "S2", "Talla": ""},
        ])
        pedidas, descartes = app.tallas_pedidas_desde_excel(df)
        self.assertEqual(pedidas, {"AB123-001": {"S1": "40"}})
        self.assertIn("no borra", " ".join(d["Motivo"] for d in descartes))

    def test_el_sku_repetido_se_reporta(self):
        df = pd.DataFrame([
            {"Mod-Col": "AB123-001", "SKU": "S1", "Talla": "40"},
            {"Mod-Col": "AB123-001", "SKU": "S1", "Talla": "41"},
        ])
        pedidas, descartes = app.tallas_pedidas_desde_excel(df)
        self.assertEqual(pedidas["AB123-001"]["S1"], "40")
        self.assertTrue(descartes)


class TestElPlanDeTallasPedidas(unittest.TestCase):
    def test_renombra_la_talla_del_sku_pedido(self):
        productos = [_producto_con_tallas([("S1", "8"), ("S2", "9")])]
        planes, sin_producto = app.tallas_planificar_pedidas(
            productos, {"AB123-001": {"S1": "40.5", "S2": "42"}})
        self.assertEqual(sin_producto, [])
        self.assertEqual(planes[0]["Renombrar"], {"8": "40.5", "9": "42"})
        self.assertTrue(planes[0]["Cambia_escala"])

    def test_ordena_sobre_las_tallas_NUEVAS(self):
        """Ordenar antes de renombrar dejaria las etiquetas nuevas en las
        posiciones viejas. Es la misma regla del automatico, heredada."""
        productos = [_producto_con_tallas([("S1", "8"), ("S2", "9")])]
        planes, _ = app.tallas_planificar_pedidas(
            productos, {"AB123-001": {"S1": "42", "S2": "40"}})
        self.assertEqual(planes[0]["Propuesto"], ["40", "42"])

    def test_dos_tallas_que_caen_en_la_misma_no_se_renombran(self):
        """Serian dos valores iguales en la misma opcion y Shopify lo rechaza.
        No se elige cual sobra: se avisa."""
        productos = [_producto_con_tallas([("S1", "8"), ("S2", "9")])]
        planes, _ = app.tallas_planificar_pedidas(
            productos, {"AB123-001": {"S1": "40", "S2": "40"}})
        self.assertEqual(planes[0]["Renombrar"], {})
        self.assertIn("repetidas", planes[0]["Nota"])

    def test_dos_sku_con_la_misma_talla_pidiendo_cosas_distintas_se_avisa(self):
        """Lo que se escribe es el VALOR de la opcion, y ese lo comparten las
        dos variantes: eso no es un renombre, es partir una variante en dos."""
        productos = [_producto_con_tallas([("S1", "8"), ("S2", "8")])]
        planes, _ = app.tallas_planificar_pedidas(
            productos, {"AB123-001": {"S1": "40", "S2": "41"}})
        self.assertEqual(planes[0]["Renombrar"], {})
        self.assertIn("dos valores distintos", planes[0]["Nota"])

    def test_un_sku_que_el_producto_no_tiene_se_reporta(self):
        productos = [_producto_con_tallas([("S1", "8")])]
        planes, _ = app.tallas_planificar_pedidas(
            productos, {"AB123-001": {"S1": "40", "NOEXISTE": "41"}})
        self.assertIn("NOEXISTE", planes[0]["Nota"])

    def test_un_codigo_que_no_esta_en_el_sitio_se_lista_aparte(self):
        """Pedir 50 y ver 38 en la tabla se lee igual de bien que ver las 50."""
        planes, sin_producto = app.tallas_planificar_pedidas(
            [_producto_con_tallas([("S1", "8")])], {"OTRO-999": {"S9": "40"}})
        self.assertEqual(planes, [])
        self.assertEqual(sin_producto[0]["Código Modelo Color"], "OTRO-999")

    def test_una_talla_igual_a_la_que_ya_tiene_no_cambia_nada(self):
        productos = [_producto_con_tallas([("S1", "40"), ("S2", "41")])]
        planes, _ = app.tallas_planificar_pedidas(
            productos, {"AB123-001": {"S1": "40", "S2": "41"}})
        self.assertFalse(planes[0]["Cambia_escala"])
        self.assertFalse(planes[0]["Cambia_orden"])


class TestLoPedidoViajaHastaLaEscritura(unittest.TestCase):
    def test_ida_y_vuelta_del_texto(self):
        """El plan viaja al runner DENTRO de una hoja de Excel, y ahi una celda
        es texto."""
        pedidas = {"S1": "40.5", "S2": "42"}
        texto = orden_tallas.tallas_pedidas_a_texto(pedidas)
        self.assertEqual(orden_tallas.tallas_pedidas_desde_texto(texto), pedidas)

    def test_la_vista_previa_lleva_las_tallas_pedidas(self):
        productos = [_producto_con_tallas([("S1", "8")])]
        planes, _ = app.tallas_planificar_pedidas(productos, {"AB123-001": {"S1": "40.5"}})
        previa = app.tallas_vista_previa(planes, {"site_label": "Vans.pe", "site_key": "vans"})
        self.assertIn("S1=40.5", previa.iloc[0]["Tallas pedidas"])

    def test_el_registro_releido_trae_el_SKU(self):
        """Sin el, una talla pedida se buscaria por su etiqueta vieja."""
        registro = app.tallas_producto_como_registro({
            "variants": {"nodes": [
                {"id": "gid://v/1", "sku": "S1",
                 "selectedOptions": [{"name": "Talla", "value": "8"}]},
            ]}
        })
        self.assertEqual(registro["Variants"][0][orden_tallas.CAMPO_SKU], "S1")


class TestAplicarLasTallasPedidas(unittest.TestCase):
    """Se EJECUTA `tallas_aplicar_producto`, que es lo que escribe en Shopify
    tanto desde la pantalla como desde el runner."""

    def _parchar(self, variantes):
        self.renombrado = []
        self.reordenado = []
        producto = {
            "options": [{"id": "gid://opt/1", "name": "Talla", "optionValues": [
                {"id": f"gid://val/{i}", "name": talla}
                for i, talla in enumerate(dict.fromkeys(t for _, t in variantes), start=1)
            ]}],
            "variants": {"nodes": [
                {"id": f"gid://v/{i}", "sku": sku,
                 "selectedOptions": [{"name": "Talla", "value": talla}]}
                for i, (sku, talla) in enumerate(variantes, start=1)
            ]},
        }
        originales = {
            "fetch_product_options_and_variants": app.fetch_product_options_and_variants,
            "product_option_update": app.product_option_update,
            "product_variants_bulk_reorder": app.product_variants_bulk_reorder,
        }
        app.fetch_product_options_and_variants = lambda *a, **k: producto
        app.product_option_update = lambda c, p, o, cambios: self.renombrado.extend(cambios)
        app.product_variants_bulk_reorder = lambda c, p, pos: self.reordenado.extend(pos)
        self.addCleanup(lambda: [setattr(app, n, f) for n, f in originales.items()])
        return producto

    def test_escribe_exactamente_la_talla_pedida(self):
        self._parchar([("S1", "8"), ("S2", "9")])
        plan = {
            "Product ID": "gid://shopify/Product/1", "Mod-Col": "AB123-001",
            "Title": "Bota", "Marca": "COLUMBIA", "Handle": "h",
            "Type": "Zapatillas", "Genero": "Masculino",
            "Tallas pedidas": "S1=40.5 | S2=42",
        }
        ok, pasos = app.tallas_aplicar_producto({}, plan, {"site_key": "vans", "label": "VANS"})
        self.assertTrue(ok, pasos)
        self.assertEqual(
            sorted(c["name"] for c in self.renombrado), ["40.5", "42"])

    def test_al_replanificar_manda_lo_pedido_y_NO_el_conversor_automatico(self):
        """El fallo que este campo existe para impedir. Antes de escribir se
        RELEE el producto y se replanifica: sin lo pedido en el plan, el
        segundo pase preguntaria a la guia de la marca y escribiria otra talla
        -- que es exactamente lo que le paso al Type y al Genero en su dia."""
        self._parchar([("S1", "8")])
        llamadas = []
        original = app.tallas_convertidor_para
        app.tallas_convertidor_para = lambda p, b: llamadas.append(1)
        self.addCleanup(lambda: setattr(app, "tallas_convertidor_para", original))
        plan = {
            "Product ID": "gid://shopify/Product/1", "Mod-Col": "AB123-001",
            "Title": "Bota", "Marca": "COLUMBIA", "Handle": "h",
            "Type": "Zapatillas", "Genero": "Masculino", "Tallas pedidas": "S1=33",
        }
        ok, pasos = app.tallas_aplicar_producto({}, plan, {"site_key": "vans", "label": "VANS"})
        self.assertTrue(ok, pasos)
        self.assertEqual(llamadas, [], "se preguntó al conversor automático")
        self.assertEqual([c["name"] for c in self.renombrado], ["33"])

    def test_sin_tallas_pedidas_sigue_mandando_el_automatico(self):
        """La regresion: el modo de siempre no cambia."""
        self._parchar([("S1", "8")])
        llamadas = []
        original = app.tallas_convertidor_para

        def _espia(producto, brand_config):
            llamadas.append(1)
            return original(producto, brand_config)

        app.tallas_convertidor_para = _espia
        self.addCleanup(lambda: setattr(app, "tallas_convertidor_para", original))
        plan = {
            "Product ID": "gid://shopify/Product/1", "Mod-Col": "AB123-001",
            "Title": "Bota", "Marca": "COLUMBIA", "Handle": "h",
            "Type": "Zapatillas", "Genero": "Masculino",
        }
        app.tallas_aplicar_producto({}, plan, {"site_key": "vans", "label": "VANS"})
        self.assertEqual(len(llamadas), 1)

    def test_una_carga_que_SI_escribio_no_se_reporta_omitida(self):
        """`apply_shopify_preview` traduce cualquier paso en "aviso" a OMITIDO.
        Un SKU que el producto no tiene es algo que contar, no una omision."""
        self._parchar([("S1", "8")])
        plan = {
            "Product ID": "gid://shopify/Product/1", "Mod-Col": "AB123-001",
            "Title": "Bota", "Marca": "COLUMBIA", "Handle": "h",
            "Type": "Zapatillas", "Genero": "Masculino",
            "Tallas pedidas": "S1=33 | NOEXISTE=44",
        }
        ok, pasos = app.tallas_aplicar_producto({}, plan, {"site_key": "vans", "label": "VANS"})
        self.assertTrue(ok)
        paso = [p for p in pasos if p["Paso"] == "Tallas pedidas"][0]
        self.assertEqual(paso["Estado"], "ok")
        self.assertIn("NOEXISTE", paso["Detalle"])


# =========================================================================
# 3. Body HTML ya hecho
# =========================================================================

HTML_HECHO = "<div class='mio'><h2>Casaca</h2><p>Impermeable y liviana.</p></div>"


class TestElBodyHtmlSePublicaTalCual(unittest.TestCase):
    def test_lo_que_ya_trae_etiquetas_no_se_toca(self):
        self.assertEqual(gen.body_html_tal_cual({"Body HTML": HTML_HECHO}), HTML_HECHO)

    def test_no_lo_envuelve_en_la_seccion_Descripcion(self):
        """El fallo exacto: `build_body_html` mete lo que reciba dentro de un
        `nweb__Descripcion` con su titulo."""
        armado = gen.build_body_html({"Body HTML": HTML_HECHO})
        self.assertIn("nweb__Descripcion", armado)
        self.assertNotIn("nweb__Descripcion", gen.body_html_tal_cual({"Body HTML": HTML_HECHO}))

    def test_un_texto_plano_se_convierte_a_parrafos(self):
        """Un texto plano se publicaria en una sola tira, y un `&` suelto rompe
        el marcado de la ficha."""
        salida = gen.body_html_tal_cual({"Body HTML": "Casaca liviana & abrigada"})
        self.assertEqual(salida, "<p>Casaca liviana &amp; abrigada</p>")

    def test_vacio_devuelve_vacio(self):
        self.assertEqual(gen.body_html_tal_cual({"Body HTML": ""}), "")

    def test_la_columna_puede_llamarse_de_varias_formas(self):
        for nombre in ("Body HTML", "Descripción HTML", "Body (HTML)"):
            self.assertEqual(gen.body_html_tal_cual({nombre: HTML_HECHO}), HTML_HECHO, nombre)


def _catalogo_body(body_actual=""):
    return [{
        "Mod-Col": "AB123-001", "Handle": "casaca-ab123-001",
        "Product ID": "gid://shopify/Product/1", "Title": "Casaca",
        "Body HTML": body_actual,
    }]


class TestLaVistaPreviaDeBodyTalCual(unittest.TestCase):
    def _previa(self, df, body_mode="as_is", actual=""):
        return app.build_shopify_update_preview(
            _catalogo_body(actual), df, "body",
            {"site_label": "Vans.pe", "site_key": "vans"}, body_mode=body_mode)

    def test_el_valor_nuevo_es_el_html_del_excel(self):
        df = pd.DataFrame([{"Mod-Col": "AB123-001", "Body HTML": HTML_HECHO}])
        previa, issues, _ = self._previa(df)
        self.assertEqual(len(previa), 1)
        self.assertEqual(previa.iloc[0]["Valor nuevo"], HTML_HECHO)

    def test_una_celda_vacia_no_borra_la_ficha(self):
        df = pd.DataFrame([{"Mod-Col": "AB123-001", "Body HTML": ""}])
        previa, issues, _ = self._previa(df, actual=HTML_HECHO)
        self.assertTrue(previa.empty)
        self.assertIn("no borra", " ".join(issues["Problema"].tolist()))

    def test_lo_que_ya_dice_lo_mismo_no_se_reescribe(self):
        df = pd.DataFrame([{"Mod-Col": "AB123-001", "Body HTML": HTML_HECHO}])
        previa, issues, _ = self._previa(df, actual=HTML_HECHO)
        self.assertTrue(previa.empty)
        self.assertIn("Sin cambios", " ".join(issues["Problema"].tolist()))

    def test_el_modo_de_siempre_sigue_armando_la_ficha(self):
        """La regresion: `from_input` no cambia."""
        df = pd.DataFrame([{"Mod-Col": "AB123-001", "Caracteristicas": "Liviana|Abrigada"}])
        previa, _, _ = self._previa(df, body_mode="from_input")
        self.assertIn("nweb__Caracteristicas", previa.iloc[0]["Valor nuevo"])


class TestLaRutaDeRespaldoExcelEntiendeElMismoModo(unittest.TestCase):
    """Si solo lo entendiera una de las dos, el mismo archivo se aplicaria
    distinto segun la fuente elegida arriba -- que es lo que ya paso con
    "Operacion no soportada: short_texts"."""

    def _catalogo(self, actual=""):
        # El catalogo de esta ruta es un export Matrixify: la identidad sale
        # del metacampo del codigo modelo color, no de una columna "Mod-Col".
        return pd.DataFrame([{
            gen.PRODUCT_KEY_COLUMN: "AB123-001",
            "Handle": "casaca-ab123-001", "Title": "Casaca",
            "ID": "1", "Body HTML": actual, "Command": "UPDATE",
        }])

    def test_publica_el_html_tal_cual(self):
        entrada = pd.DataFrame([{"Mod-Col": "AB123-001", "Body HTML": HTML_HECHO}])
        filas, _ = gen.build_matrixify_updates(
            self._catalogo(), entrada, operation="body", body_mode="as_is")
        self.assertEqual(filas.iloc[0]["Body HTML"], HTML_HECHO)

    def test_vacio_no_borra(self):
        entrada = pd.DataFrame([{"Mod-Col": "AB123-001", "Body HTML": ""}])
        filas, issues = gen.build_matrixify_updates(
            self._catalogo(HTML_HECHO), entrada, operation="body", body_mode="as_is")
        self.assertTrue(filas.empty)
        self.assertIn("no borra", " ".join(issues["Problema"].tolist()))

    def test_lo_igual_no_se_reescribe(self):
        entrada = pd.DataFrame([{"Mod-Col": "AB123-001", "Body HTML": HTML_HECHO}])
        filas, issues = gen.build_matrixify_updates(
            self._catalogo(HTML_HECHO), entrada, operation="body", body_mode="as_is")
        self.assertTrue(filas.empty)
        self.assertIn("Sin cambios", " ".join(issues["Problema"].tolist()))


class TestElDiagnosticoNoSeComeElHtmlPropio(unittest.TestCase):
    """La trampa que dejaba todo esto sin efecto.

    `filter_preview_by_diagnostic_ready` solo deja pasar lo que esta "Listo", y
    el validador exigia las secciones Caracteristicas / Materiales / Cuidados
    -- que son las que arma `build_body_html`, no un requisito de una ficha
    valida --. Un HTML escrito por fuera quedaba en "Observación", el archivo se
    subia, la vista previa lo mostraba **y no se escribia nada**.
    """

    def test_no_exige_secciones_cuando_el_html_es_de_la_persona(self):
        estado, _ = app.validate_partial_body_html(
            HTML_HECHO + "<p>Un texto suficientemente largo para pasar el minimo.</p>",
            exigir_secciones=False)
        self.assertEqual(estado, "Listo")

    def test_las_sigue_exigiendo_en_el_modo_de_siempre(self):
        estado, problema = app.validate_partial_body_html(
            HTML_HECHO + "<p>Un texto suficientemente largo para pasar el minimo.</p>")
        self.assertEqual(estado, "Observación")
        self.assertIn("Faltan secciones", problema)

    def test_las_demas_reglas_se_siguen_aplicando(self):
        """Vacio, demasiado corto y scripts hablan de la ficha, no del formato
        de `build_body_html`: esas no se relajan."""
        self.assertEqual(
            app.validate_partial_body_html("<p>corto</p>", exigir_secciones=False)[0],
            "Bloqueado")
        self.assertEqual(
            app.validate_partial_body_html("", exigir_secciones=False)[0], "Bloqueado")

    def test_de_punta_a_punta_la_fila_sobrevive_al_filtro(self):
        """La prueba que de verdad importa: el HTML propio llega a la escritura."""
        largo = HTML_HECHO + "<p>Casaca impermeable con capucha ajustable y bolsillos.</p>"
        df = pd.DataFrame([{"Mod-Col": "AB123-001", "Body HTML": largo}])
        previa, issues, _ = app.build_shopify_update_preview(
            _catalogo_body(), df, "body",
            {"site_label": "Vans.pe", "site_key": "vans"}, body_mode="as_is")
        diagnostico = app.build_partial_diagnostic_table(previa, issues, "body", body_mode="as_is")
        escribibles = app.filter_preview_by_diagnostic_ready(previa, diagnostico)
        self.assertEqual(len(escribibles), 1, diagnostico.to_dict("records"))
        self.assertEqual(escribibles.iloc[0]["Valor nuevo"], largo)




# =========================================================================
# 4. Las pantallas: que se pueda entregar el archivo
# =========================================================================
# Este repositorio ya se llevo tres fallos que vivian SOLO en el pegamento con
# la pantalla y que ninguna prueba del motor vio: la clave con tilde de
# `render_status_de_carga`, los tres que dejaron el Mantenedor de Tallas sin
# efecto, y la opcion de textos cortos que no dibujaba su `file_uploader`.
#
# Un motor perfecto al que no se le puede entregar el archivo no sirve para
# nada, asi que estas pruebas ENTRAN A LA APP y miran lo que se dibuja.

from streamlit.testing.v1 import AppTest  # noqa: E402

APP = str(RAIZ / "app_matrixify.py")
TIEMPO = 300

SHOPIFY_FALSO = {
    "shop_domain": "prueba.myshopify.com",
    "admin_access_token": "token-de-prueba",
    "api_version": "2024-10",
}
MARCA_FALSA = {"site_key": "vans", "site_label": "Vans.pe", "label": "VANS",
               "allowed_arti_brands": ["VANS"]}


def _excel(filas):
    """Un .xlsx de verdad en memoria, que es lo que recibe la pantalla."""
    import io
    buffer = io.BytesIO()
    pd.DataFrame(filas).to_excel(buffer, index=False, engine="xlsxwriter")
    return ("datos.xlsx", buffer.getvalue(),
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")


def _pantalla_de_tallas():
    """El Mantenedor de Tallas con un Shopify configurado.

    Se llama a la funcion de pantalla directamente y no a la app entera: sin
    Secrets, `is_shopify_configured` es falso y la pantalla corta con su aviso
    antes de dibujar nada -- que es correcto, pero entonces no hay nada que
    mirar.
    """
    guion = (
        "import sys; sys.path.insert(0, %r)\n"
        "import app_matrixify as app\n"
        "app.render_mantenedor_tallas(%r, %r)\n"
    ) % (str(RAIZ), MARCA_FALSA, SHOPIFY_FALSO)
    at = AppTest.from_string(guion, default_timeout=TIEMPO)
    at.session_state["authenticated"] = True
    at.session_state["auth_user"] = "hugo"
    return at.run()


class TestLaPantallaDeTallasPideElExcel(unittest.TestCase):
    def test_ofrece_el_modo_de_Excel(self):
        at = _pantalla_de_tallas()
        self.assertEqual([str(e.value)[:300] for e in at.exception], [])
        modos = [r for r in at.radio if "Cómo se deciden" in (r.label or "")]
        self.assertTrue(modos, "no hay selector de modo en el Mantenedor de Tallas")
        self.assertIn(app.TALLAS_MODO_PEDIDAS, list(modos[0].options))

    def test_el_automatico_sigue_siendo_el_de_por_defecto(self):
        """La regresion: quien entra a revisar el catalogo no tiene que elegir
        nada nuevo."""
        at = _pantalla_de_tallas()
        modos = [r for r in at.radio if "Cómo se deciden" in (r.label or "")]
        self.assertEqual(modos[0].value, app.TALLAS_MODO_AUTOMATICO)

    def test_al_elegir_Excel_aparece_donde_subirlo(self):
        """El fallo que esta prueba existe para impedir: una opcion en el menu
        que no dibuja por donde darle los datos."""
        at = _pantalla_de_tallas()
        modo = [r for r in at.radio if "Cómo se deciden" in (r.label or "")][0]
        at = modo.set_value(app.TALLAS_MODO_PEDIDAS).run()
        self.assertEqual([str(e.value)[:300] for e in at.exception], [])
        etiquetas = [u.proto.label.lower() for u in at.get("file_uploader")]
        self.assertTrue(etiquetas, "no hay donde subir el Excel de tallas")
        self.assertTrue(
            any("sku" in e and "talla" in e for e in etiquetas),
            f"el subidor no dice que columnas espera: {etiquetas}")

    def test_dice_que_no_toca_SKU_ni_precios_ni_inventario(self):
        at = _pantalla_de_tallas()
        modo = [r for r in at.radio if "Cómo se deciden" in (r.label or "")][0]
        at = modo.set_value(app.TALLAS_MODO_PEDIDAS).run()
        pantalla = " ".join(str(c.value) for c in at.caption).lower()
        self.assertIn("no se tocan sku", pantalla)


def _carga_parcial(opcion, fuente="Shopify API"):
    at = AppTest.from_file(APP, default_timeout=TIEMPO)
    at.session_state["authenticated"] = True
    at.session_state["auth_user"] = "hugo"
    at.session_state["operation_area_choice"] = "Carga de catálogo"
    at.session_state["operation_mode_choice"] = "Carga parcial"
    at.run()
    selector = [s for s in at.selectbox if s.label == "Que quieres actualizar"][0]
    at = selector.set_value(opcion).run()
    for radio in at.radio:
        if "Fuente de datos" in (radio.label or ""):
            at = radio.set_value(fuente).run()
            break
    return at


class TestLaPantallaDeBodyHtml(unittest.TestCase):
    def test_el_subidor_nombra_el_codigo_y_el_body_html(self):
        at = _carga_parcial("Mantención Body HTML")
        self.assertEqual([str(e.value)[:300] for e in at.exception], [])
        etiquetas = " ".join(u.proto.label.lower() for u in at.get("file_uploader"))
        self.assertIn("código modelo color", etiquetas)
        self.assertIn("body html", etiquetas)

    def test_con_archivo_aparece_el_selector_de_modo(self):
        at = _carga_parcial("Mantención Body HTML")
        subidor = [u for u in at.get("file_uploader") if "body html" in u.proto.label.lower()][0]
        at = subidor.set_value(
            _excel([{"Mod-Col": "AB123-001", "Body HTML": HTML_HECHO}])).run()
        self.assertEqual([str(e.value)[:300] for e in at.exception], [])
        modos = [r for r in at.radio if "Qué hacer con el archivo" in (r.label or "")]
        self.assertTrue(modos, "sin selector no hay forma de pedir el HTML tal cual")
        self.assertEqual(modos[0].value, app.BODY_MODO_TAL_CUAL)

    def test_sin_archivo_sigue_corrigiendo_el_catalogo(self):
        """La regresion: el modo de siempre sin archivo no cambia."""
        at = _carga_parcial("Mantención Body HTML")
        self.assertEqual(
            [r for r in at.radio if "Qué hacer con el archivo" in (r.label or "")], [])
        pantalla = " ".join(str(c.value) for c in at.caption).lower()
        self.assertIn("sin archivo", pantalla)


def _pantalla_de_videos():
    """Igual que la de tallas: sin Shopify configurado la pantalla corta con su
    aviso antes de dibujar el subidor."""
    guion = (
        "import sys; sys.path.insert(0, %r)\n"
        "import app_matrixify as app\n"
        "app.render_video_maintainer(%r, %r)\n"
    ) % (str(RAIZ), MARCA_FALSA, SHOPIFY_FALSO)
    at = AppTest.from_string(guion, default_timeout=TIEMPO)
    at.session_state["authenticated"] = True
    at.session_state["auth_user"] = "hugo"
    return at.run()


class TestLaPantallaDeVideosNombraElLink(unittest.TestCase):
    def test_dice_que_se_puede_dar_la_URL_en_el_Excel(self):
        """Una columna que existe y que nadie menciona en pantalla no la usa
        nadie."""
        at = _pantalla_de_videos()
        self.assertEqual([str(e.value)[:300] for e in at.exception], [])
        texto = " ".join(
            [u.proto.label for u in at.get("file_uploader")]
            + [u.help for u in at.get("file_uploader")]
            + [str(c.value) for c in at.caption]
        ).lower()
        self.assertIn("url", texto, "la pantalla no dice que se puede dar el link")

    def test_sigue_ofreciendo_el_camino_del_bucket(self):
        """La regresion: quien ya trabaja con el bucket no tiene que cambiar
        nada."""
        at = _pantalla_de_videos()
        texto = " ".join(str(c.value) for c in at.caption).lower()
        self.assertIn("bucket", texto)




class TestCambiarDeModoTiraElPlanAnterior(unittest.TestCase):
    """Con el plan del automatico en pantalla y el modo puesto en Excel, el
    boton Aplicar escribiria lo que NO se pidio."""

    def test_el_plan_no_sobrevive_al_cambio_de_modo(self):
        at = _pantalla_de_tallas()
        clave = "tallas_plan_vans"
        at.session_state[clave] = [{"Mod-Col": "AB123-001", "Situacion": "Escala equivocada"}]
        at.session_state[f"{clave}_modo"] = app.TALLAS_MODO_AUTOMATICO
        modo = [r for r in at.radio if "Cómo se deciden" in (r.label or "")][0]
        at = modo.set_value(app.TALLAS_MODO_PEDIDAS).run()
        self.assertNotIn(clave, at.session_state)


if __name__ == "__main__":
    unittest.main(verbosity=2)
