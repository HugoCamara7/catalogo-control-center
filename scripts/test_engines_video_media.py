# -*- coding: utf-8 -*-
"""Pruebas del Mantenedor de Videos.

Lo que estas pruebas fijan, y por que cada una:

- El nombre y la ruta se arman SOLOS a partir de Marca + Modelo + Color. El
  usuario nunca los escribe, asi que si se rompen nadie lo ve hasta que el
  video queda con el nombre equivocado en la carpeta equivocada.
- **La carpeta la manda la MARCA, no el sitio.** Rockford.pe vende Columbia,
  Patagonia y Sorel: tomar la carpeta del sitio dejaria los videos de tres
  marcas en `ROCKFORD/`.
- **La posicion 2 se cuenta desde 1 para la persona y desde 0 para Shopify.**
  `productReorderMedia` usa indices que empiezan en 0: confundirlos deja el
  video TERCERO, que es exactamente el error que el modulo existe para evitar.
- Nunca se crean videos duplicados en silencio.

Ejecutar:  python scripts/test_engines_video_media.py
"""
import ast
import re
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from engines import video_media as vm          # noqa: E402

FUENTE_APP = (ROOT / "app_matrixify.py").read_text(encoding="utf-8-sig")
FUENTE_API = (ROOT / "shopify_api.py").read_text(encoding="utf-8-sig")


def foto(media_id, url="foto.jpg"):
    return {"id": media_id, "mediaContentType": "IMAGE", "status": "READY",
            "image": {"url": f"https://cdn.shopify.com/{url}"}}


def video(media_id, url="2044361_6RX_2.mp4", estado="READY"):
    return {"id": media_id, "mediaContentType": "VIDEO", "status": estado,
            "sources": [{"url": f"https://cdn.shopify.com/videos/{url}"}]}


class TestNombreYRuta(unittest.TestCase):
    """Marca + Modelo + Color -> nombre, ruta y URL. Sin que nadie los escriba."""

    def test_el_nombre_lleva_el_sufijo_de_la_posicion(self):
        self.assertEqual(vm.nombre_de_video("2044361", "6RX"), "2044361_6RX_2.mp4")

    def test_el_sufijo_es_la_posicion_del_video(self):
        # El `_2` del nombre y la posicion 2 de la galeria son el MISMO numero
        # a proposito: el nombre dice donde va a quedar el video.
        self.assertEqual(vm.SUFIJO_VIDEO, str(vm.POSICION_VIDEO))
        self.assertEqual(vm.POSICION_VIDEO, 2)

    def test_el_nombre_normaliza_lo_que_escribe_el_usuario(self):
        self.assertEqual(vm.nombre_de_video(" 2044361 ", "6rx"), "2044361_6RX_2.mp4")

    def test_el_modelo_pegado_al_color_no_se_duplica(self):
        # Si alguien pega "2044361-6RX" en Modelo, el color no puede salir dos
        # veces en el nombre del archivo.
        self.assertEqual(vm.nombre_de_video("2044361-6RX", "6RX"), "2044361_6RX_2.mp4")

    def test_sin_modelo_o_sin_color_no_hay_nombre(self):
        self.assertEqual(vm.nombre_de_video("", "6RX"), "")
        self.assertEqual(vm.nombre_de_video("2044361", ""), "")

    def test_el_codigo_modelo_color_es_el_de_la_app(self):
        self.assertEqual(vm.codigo_modelo_color("2044361", "6rx"), "2044361-6RX")

    def test_la_url_es_la_del_requerimiento(self):
        self.assertEqual(
            vm.url_de_video("COLUMBIA", "2044361", "6RX"),
            "https://ecom-imagenes.forus-digital.xyz.peru.s3.amazonaws.com/COLUMBIA/2044361_6RX_2.mp4",
        )

    def test_la_clave_s3_es_carpeta_mas_nombre(self):
        self.assertEqual(vm.clave_s3("COLUMBIA", "2044361", "6RX"), "COLUMBIA/2044361_6RX_2.mp4")


class TestLaCarpetaLaMandaLaMarca(unittest.TestCase):
    """El fallo que esta clase evita: los videos de tres marcas en un cajon.

    Rockford.pe vende Columbia, Patagonia, Sorel y Mountain Hardwear. Si la
    carpeta saliera del sitio, todos esos videos irian a `ROCKFORD/` y ninguno
    se encontraria despues.
    """

    def test_cada_marca_tiene_su_carpeta(self):
        esperado = {
            "COLUMBIA": "COLUMBIA",
            "ROCKFORD": "ROCKFORD",
            "HUSH PUPPIES": "HUSHPUPPIES",
            "VANS": "VANS",
            "PATAGONIA": "PATAGONIA",
            "SOREL": "SOREL",
            "MOUNTAIN HARDWEAR": "MOUNTAINHARDWEAR",
        }
        for marca, carpeta in esperado.items():
            self.assertEqual(vm.carpeta_de_marca(marca), carpeta, marca)

    def test_la_url_cambia_de_carpeta_con_la_marca(self):
        for marca, carpeta in (("COLUMBIA", "COLUMBIA"), ("PATAGONIA", "PATAGONIA"),
                               ("HUSH PUPPIES", "HUSHPUPPIES")):
            self.assertIn(f"/{carpeta}/", vm.url_de_video(marca, "2044361", "6RX"), marca)

    def test_se_lee_del_diccionario_de_las_fotos_y_no_de_una_copia(self):
        # No puede haber una segunda lista de marcas que mantener: el dia que
        # se agregue una, tiene que servir para fotos y para videos.
        from generate_columbia_matrixify import BRAND_IMAGE_FOLDERS

        self.assertEqual(vm.marcas_disponibles(), sorted(BRAND_IMAGE_FOLDERS))

    def test_las_variantes_del_nombre_caen_en_la_misma_carpeta(self):
        # "Hush Puppies Kids" y "Accesorios HP" van al mismo cajon que la marca.
        self.assertEqual(vm.carpeta_de_marca("HUSH PUPPIES KIDS"), "HUSHPUPPIES")
        self.assertEqual(vm.carpeta_de_marca("ACCESORIOS HP"), "HUSHPUPPIES")

    def test_el_host_es_el_mismo_que_usan_las_fotos(self):
        from generate_columbia_matrixify import DEFAULT_IMAGE_HOST

        self.assertEqual(vm.host_de_imagenes(), DEFAULT_IMAGE_HOST.rstrip("/"))


class TestValidacionDeLaDescarga(unittest.TestCase):
    """Se valida lo que el bucket devolvio, ANTES de darselo a Shopify.

    Un archivo enorme tarda minutos en subir y recien despues Shopify lo marca
    FAILED: es el peor lugar para enterarse de un tope que se sabia antes.
    """

    URL = "https://ecom-imagenes.forus-digital.xyz.peru.s3.amazonaws.com/COLUMBIA/2044361_6RX_2.mp4"

    def test_un_mp4_normal_pasa_sin_avisos(self):
        errores, avisos = vm.validar_descarga(self.URL, b"x" * 5_000_000, "video/mp4")
        self.assertEqual(errores, [])
        self.assertEqual(avisos, [])

    def test_el_archivo_vacio_se_rechaza(self):
        errores, _ = vm.validar_descarga(self.URL, b"", "video/mp4")
        self.assertTrue(errores)

    def test_por_encima_del_tope_de_shopify_se_rechaza(self):
        errores, _ = vm.validar_descarga(self.URL, b"x" * (vm.VIDEO_MAX_BYTES + 1), "video/mp4")
        self.assertTrue(errores)

    def test_un_video_pesado_avisa_pero_no_frena(self):
        errores, avisos = vm.validar_descarga(self.URL, b"x" * (vm.VIDEO_AVISO_BYTES + 1), "video/mp4")
        self.assertEqual(errores, [])
        self.assertTrue(avisos)

    def test_octet_stream_no_es_un_error(self):
        # S3 devuelve application/octet-stream para los mp4 a los que nadie les
        # puso el tipo. Tratarlo como error rechazaria videos que estan bien.
        errores, avisos = vm.validar_descarga(self.URL, b"x" * 5_000_000, "application/octet-stream")
        self.assertEqual(errores, [])
        self.assertEqual(avisos, [])

    def test_un_tipo_raro_avisa_pero_no_frena(self):
        errores, avisos = vm.validar_descarga(self.URL, b"x" * 5_000_000, "text/html")
        self.assertEqual(errores, [])
        self.assertTrue(avisos)

    def test_una_url_que_no_es_mp4_se_rechaza(self):
        errores, _ = vm.validar_descarga(self.URL.replace(".mp4", ".mov"), b"x" * 5_000_000, "video/quicktime")
        self.assertTrue(errores)

    def test_sin_url_hay_error(self):
        errores, _ = vm.validar_descarga("", b"x" * 5_000_000, "video/mp4")
        self.assertTrue(errores)

    def test_faltan_datos_del_producto(self):
        self.assertTrue(vm.validar_datos_del_producto("", "2044361", "6RX"))
        self.assertTrue(vm.validar_datos_del_producto("COLUMBIA", "", "6RX"))
        self.assertEqual(vm.validar_datos_del_producto("COLUMBIA", "2044361", "6RX"), [])


class TestPosicionDosEnLaGaleria(unittest.TestCase):
    """El punto critico del modulo.

    `productCreateMedia` SIEMPRE agrega el media al final y no acepta posicion.
    El video queda segundo por un segundo viaje, `productReorderMedia`, que
    trabaja con indices que EMPIEZAN EN 0: la posicion 2 que ve una persona es
    `newPosition: "1"`. Confundir las dos numeraciones deja el video tercero.
    """

    def setUp(self):
        # Como queda la galeria justo despues de crear el video: al final.
        self.media = [foto("f1"), foto("f2"), foto("f3"), foto("f4"), video("v1")]

    def test_el_movimiento_usa_indice_cero(self):
        movimientos = vm.plan_de_orden(self.media, "v1")
        self.assertEqual(movimientos, [{"id": "v1", "newPosition": "1"}])

    def test_la_posicion_es_texto_porque_la_mutacion_pide_UnsignedInt64(self):
        movimientos = vm.plan_de_orden(self.media, "v1")
        self.assertIsInstance(movimientos[0]["newPosition"], str)

    def test_el_video_queda_segundo_de_verdad(self):
        resultado = vm.orden_resultante(self.media, vm.plan_de_orden(self.media, "v1"))
        self.assertEqual([n["id"] for n in resultado], ["f1", "v1", "f2", "f3", "f4"])
        self.assertEqual(vm.posicion_de_media(resultado, "v1"), 2)

    def test_la_foto_principal_sigue_siendo_la_primera(self):
        resultado = vm.orden_resultante(self.media, vm.plan_de_orden(self.media, "v1"))
        self.assertEqual(resultado[0]["id"], "f1")

    def test_no_se_mueve_lo_que_ya_esta_en_su_sitio(self):
        # Mandar un reordenamiento que no mueve nada gasta una llamada y un job.
        ya_ordenado = [foto("f1"), video("v1"), foto("f2")]
        self.assertEqual(vm.plan_de_orden(ya_ordenado, "v1"), [])

    def test_un_media_que_no_esta_no_genera_movimiento(self):
        self.assertEqual(vm.plan_de_orden(self.media, "no-existe"), [])

    def test_con_una_sola_foto_el_video_queda_segundo(self):
        media = [foto("f1"), video("v1")]
        self.assertEqual(vm.plan_de_orden(media, "v1"), [])
        self.assertEqual(vm.posicion_de_media(media, "v1"), 2)

    def test_un_producto_sin_fotos_no_puede_tener_el_video_segundo(self):
        # Se dice, no se finge: con un solo media la posicion 2 no existe.
        media = [video("v1")]
        self.assertEqual(vm.plan_de_orden(media, "v1"), [])
        self.assertEqual(vm.posicion_de_media(media, "v1"), 1)


class TestVideoYaExistente(unittest.TestCase):
    """Nunca se crean duplicados automaticamente."""

    def test_se_detecta_el_video_del_producto(self):
        media = [foto("f1"), video("v1"), foto("f2")]
        self.assertIsNotNone(vm.video_existente(media, "2044361_6RX_2.mp4"))

    def test_un_producto_sin_video_devuelve_None(self):
        self.assertIsNone(vm.video_existente([foto("f1"), foto("f2")], "2044361_6RX_2.mp4"))

    def test_se_reconoce_aunque_shopify_le_pegue_un_sufijo(self):
        media = [foto("f1"), video("v1", "2044361_6RX_2_a1b2c3.mp4")]
        self.assertIsNotNone(vm.video_existente(media, "2044361_6RX_2.mp4"))

    def test_un_video_con_otro_nombre_tambien_cuenta(self):
        # El requerimiento es que el producto tenga UN video, no uno con ese
        # nombre: si tiene otro, hay que avisar igual antes de agregar el nuevo.
        media = [foto("f1"), video("v1", "otro_video.mp4")]
        self.assertIsNotNone(vm.video_existente(media, "2044361_6RX_2.mp4"))

    def test_el_nombre_del_archivo_sale_de_la_fuente_del_video(self):
        self.assertEqual(
            vm.nombre_de_archivo_de_media(video("v1", "2044361_6RX_2.mp4")),
            "2044361_6RX_2.mp4",
        )

    def test_el_nombre_ignora_los_parametros_de_la_url(self):
        nodo = {"id": "v1", "mediaContentType": "VIDEO",
                "sources": [{"url": "https://cdn.shopify.com/v/2044361_6RX_2.mp4?v=123"}]}
        self.assertEqual(vm.nombre_de_archivo_de_media(nodo), "2044361_6RX_2.mp4")


class TestLecturaDeLaGaleria(unittest.TestCase):

    def test_el_resumen_separa_fotos_de_videos(self):
        resumen = vm.resumen_de_media([foto("f1"), video("v1"), foto("f2")])
        self.assertEqual((resumen["imagenes"], resumen["videos"], resumen["total"]), (2, 1, 3))

    def test_las_filas_van_numeradas_desde_uno(self):
        filas = vm.filas_de_media([foto("f1"), video("v1")])
        self.assertEqual([f["Posición"] for f in filas], [1, 2])
        self.assertEqual([f["Tipo"] for f in filas], ["Foto", "Video"])

    def test_el_estado_fallido_trae_su_detalle(self):
        nodo = {"id": "v1", "status": "FAILED",
                "mediaErrors": [{"message": "El video excede la duración permitida"}]}
        estado, detalle = vm.estado_de_media(nodo)
        self.assertEqual(estado, "FAILED")
        self.assertIn("duración", detalle)

    def test_los_estados_en_curso_son_los_de_shopify(self):
        self.assertIn("PROCESSING", vm.ESTADOS_EN_CURSO)
        self.assertIn("UPLOADED", vm.ESTADOS_EN_CURSO)


class TestCargaDesdeCodigos(unittest.TestCase):
    """La unica entrada: un Excel con codigos. Ni un archivo de video."""

    def test_cada_codigo_trae_nombre_y_url_resueltos(self):
        trabajos, descartados = vm.trabajos_desde_codigos(
            ["2044361-6RX", "2045001-010"], marca_por_defecto="COLUMBIA"
        )
        self.assertEqual(len(trabajos), 2)
        self.assertEqual(descartados, [])
        self.assertEqual(trabajos[0]["Nombre"], "2044361_6RX_2.mp4")
        self.assertEqual(trabajos[1]["Nombre"], "2045001_010_2.mp4")
        self.assertIn("/COLUMBIA/2044361_6RX_2.mp4", trabajos[0]["URL"])

    def test_un_codigo_que_no_se_parte_se_descarta_y_se_explica(self):
        trabajos, descartados = vm.trabajos_desde_codigos(["SINGUION"], marca_por_defecto="COLUMBIA")
        self.assertEqual(trabajos, [])
        self.assertIn("modelo y color", descartados[0]["Motivo"])

    def test_la_marca_del_excel_manda_sobre_la_de_pantalla(self):
        trabajos, _ = vm.trabajos_desde_codigos(
            ["2044361-6RX"], marcas={"2044361-6RX": "PATAGONIA"}, marca_por_defecto="COLUMBIA"
        )
        self.assertIn("/PATAGONIA/", trabajos[0]["URL"])

    def test_sin_marca_la_url_queda_vacia_a_proposito(self):
        # No se adivina: se resuelve despues con el metacampo del producto.
        trabajos, _ = vm.trabajos_desde_codigos(["2044361-6RX"])
        self.assertEqual(trabajos[0]["Marca"], "")
        self.assertEqual(trabajos[0]["URL"], "")

    def test_una_lista_vacia_lo_dice(self):
        trabajos, descartados = vm.trabajos_desde_codigos([])
        self.assertEqual(trabajos, [])
        self.assertTrue(descartados)

    def test_el_destino_reune_nombre_carpeta_y_las_dos_direcciones(self):
        destino = vm.destino_del_video("COLUMBIA", "2044361", "6RX")
        self.assertEqual(destino["Nombre"], "2044361_6RX_2.mp4")
        self.assertEqual(destino["Carpeta"], "COLUMBIA")
        self.assertEqual(destino["Clave S3"], "COLUMBIA/2044361_6RX_2.mp4")
        self.assertIn("ecom-imagenes", destino["URL"])
        # La alterna existe porque el host principal contesta 403 anonimo.
        self.assertIn("s3.amazonaws.com/ecom-imagenes", destino["URL validación"])
        self.assertNotEqual(destino["URL"], destino["URL validación"])

    def test_el_nombre_de_la_lista_es_el_mismo_que_el_individual(self):
        trabajos, _ = vm.trabajos_desde_codigos(["2044361-6RX"], marca_por_defecto="COLUMBIA")
        self.assertEqual(trabajos[0]["Nombre"], vm.nombre_de_video("2044361", "6RX"))
        self.assertEqual(trabajos[0]["URL"], vm.url_de_video("COLUMBIA", "2044361", "6RX"))


class TestNoSeSubeNingunArchivo(unittest.TestCase):
    """El video YA ESTA en el bucket, igual que las fotos.

    La app no escribe en S3 y no recibe archivos: solo lee. Estas pruebas
    impiden que vuelva a aparecer una subida por la puerta de atras.
    """

    def test_no_existe_el_motor_de_escritura_en_s3(self):
        self.assertFalse((ROOT / "engines" / "s3_uploader.py").exists())

    def test_boto3_no_se_declara_porque_no_se_usa(self):
        self.assertNotIn("boto3", (ROOT / "requirements.txt").read_text(encoding="utf-8"))

    def test_la_pantalla_no_pide_archivos_de_video(self):
        bloque = FUENTE_APP[FUENTE_APP.index("def render_video_maintainer"):]
        bloque = bloque[:bloque.index("\ndef ", 10) if "\ndef " in bloque[10:] else len(bloque)]
        self.assertNotIn('type=["mp4"]', bloque)
        self.assertNotIn("accept_multiple_files", bloque)
        # El unico uploader que queda es el del Excel de codigos.
        self.assertEqual(bloque.count("st.file_uploader"), 1)
        self.assertIn('type=["xlsx", "xls"]', bloque)

    def test_el_motor_no_sabe_escribir_en_el_bucket(self):
        fuente = (ROOT / "engines" / "video_media.py").read_text(encoding="utf-8")
        for prohibido in ("put_object", "upload_fileobj", "boto3"):
            self.assertNotIn(prohibido, fuente, prohibido)


class TestLaApiDeShopifyEsLaCorrecta(unittest.TestCase):
    """Un video de producto NO se resuelve como una foto.

    Con las fotos alcanza con darle a Shopify la URL publica y el la descarga.
    Con los videos NO: `originalSource` de un media VIDEO solo acepta el
    `resourceUrl` de un staged upload. Estas pruebas fijan que el codigo tome
    ese camino y no el de las fotos.
    """

    def test_el_staged_upload_de_video_pide_resource_VIDEO(self):
        bloque = FUENTE_API[FUENTE_API.index("def staged_upload_video"):]
        bloque = bloque[:bloque.index("\ndef ", 10)]
        self.assertIn('"resource": "VIDEO"', bloque)

    def test_el_staged_upload_de_video_manda_fileSize(self):
        # `fileSize` es OBLIGATORIO para VIDEO: sin el, la mutacion falla.
        bloque = FUENTE_API[FUENTE_API.index("def staged_upload_video"):]
        bloque = bloque[:bloque.index("\ndef ", 10)]
        self.assertIn('"fileSize"', bloque)

    def test_el_video_sube_por_POST_multipart_y_no_por_PUT(self):
        # El destino que devuelve Shopify para video es una politica firmada de
        # Google Cloud Storage: PUT (lo que usan las fotos) no sirve.
        bloque = FUENTE_API[FUENTE_API.index("def staged_upload_video"):]
        bloque = bloque[:bloque.index("\ndef ", 10)]
        self.assertIn('"httpMethod": "POST"', bloque)
        self.assertIn("_multipart_body", bloque)

    def test_el_campo_file_va_al_final_del_multipart(self):
        # GCS exige que `file` vaya despues de todos los parametros firmados.
        bloque = FUENTE_API[FUENTE_API.index("def _multipart_body"):]
        bloque = bloque[:bloque.index("\ndef ", 10)]
        self.assertLess(bloque.index("for nombre, valor in campos"), bloque.index('name="file"'))

    def test_el_video_se_asocia_al_producto_y_no_a_los_archivos(self):
        # `fileCreate` deja el mp4 en Contenido > Archivos y ahi se queda.
        bloque = FUENTE_API[FUENTE_API.index("def product_create_video_media"):]
        bloque = bloque[:bloque.index("\ndef ", 10)]
        self.assertIn("productCreateMedia", bloque)
        self.assertIn('"mediaContentType": "VIDEO"', bloque)
        # El docstring nombra fileCreate para explicar por que NO se usa:
        # se mira el codigo, no la explicacion.
        codigo = bloque[bloque.index('"""', bloque.index('"""') + 3) + 3:]
        self.assertNotIn("fileCreate", codigo)

    def test_existe_el_reordenamiento_de_media(self):
        self.assertIn("def product_reorder_media", FUENTE_API)
        self.assertIn("productReorderMedia", FUENTE_API)
        self.assertIn("MoveInput", FUENTE_API)

    def test_la_espera_de_video_lee_el_fragmento_de_Video(self):
        # `fetch_media_statuses` solo abre `... on MediaImage`: con un video
        # devuelve el nodo sin `status` y la espera cree que ya esta listo.
        bloque = FUENTE_API[FUENTE_API.index("def fetch_video_media_statuses"):]
        bloque = bloque[:bloque.index("\ndef ", 10)]
        self.assertIn("... on Video", bloque)
        self.assertIn("... on Media", bloque)

    def test_la_espera_de_video_es_mas_larga_que_la_de_fotos(self):
        # Un mp4 tarda decenas de segundos: los 6x3s de las fotos devolverian
        # PROCESSING casi siempre y la pantalla diria "no se pudo".
        firma = re.search(r"def wait_video_media_ready\(([^)]*)\)", FUENTE_API).group(1)
        self.assertIn("attempts=20", firma)
        self.assertIn("delay_seconds=6", firma)

    def test_la_galeria_se_pide_en_orden_y_completa(self):
        # La posicion se cuenta sobre la galeria entera: pedir solo los videos
        # daria siempre "posicion 1".
        bloque = FUENTE_API[FUENTE_API.index("def fetch_product_media"):]
        bloque = bloque[:bloque.index("\ndef ", 10)]
        self.assertIn("media(first: $first)", bloque)
        self.assertIn("... on MediaImage", bloque)
        self.assertIn("... on Video", bloque)


class TestIntegracionConLaApp(unittest.TestCase):
    """El mantenedor es una opcion mas de la Carga parcial y reutiliza lo que hay."""

    def setUp(self):
        self.arbol = ast.parse(FUENTE_APP)
        self.funciones = {n.name for n in ast.walk(self.arbol) if isinstance(n, ast.FunctionDef)}

    def test_esta_en_el_selector_de_la_carga_parcial(self):
        self.assertIn('"Mantenedor de Videos": "videos"', FUENTE_APP)

    def test_la_carga_parcial_lo_enruta(self):
        self.assertIn('if update_operation == "videos":', FUENTE_APP)
        self.assertIn("render_video_maintainer(brand_config, shopify_config)", FUENTE_APP)

    def test_existen_las_funciones_del_flujo(self):
        for nombre in (
            "render_video_maintainer", "render_video_resultados", "render_video_galeria",
            "render_video_pasos", "video_publicar", "video_buscar_producto",
            "video_marca_del_producto", "video_marcas_del_excel",
            "video_descargar_del_bucket", "video_publicar_en_shopify",
            "video_colocar_en_posicion", "video_reemplazar_existente",
            "video_esperar_procesado", "video_leer_galeria", "video_registrar_auditoria",
            "video_fila_de_resultado", "video_detalle_de_pasos",
        ):
            self.assertIn(nombre, self.funciones, nombre)

    def test_ninguna_funcion_nueva_queda_sin_llamador(self):
        # Ya paso dos veces en este proyecto: se define un panel y nunca se
        # invoca. Se verifica por AST antes de entregar.
        usadas = {n.id for n in ast.walk(self.arbol)
                  if isinstance(n, ast.Name) and isinstance(n.ctx, ast.Load)}
        usadas |= {n.attr for n in ast.walk(self.arbol) if isinstance(n, ast.Attribute)}
        nuevas = {f for f in self.funciones
                  if f.startswith("video_") or f.startswith("render_video")}
        self.assertEqual(sorted(nuevas - usadas), [])

    def test_reutiliza_la_lectura_de_codigos_del_mantenedor_de_fotos(self):
        # `png_codigos_desde_excel` ya quita vacios y repetidos y explica cada
        # descarte. Escribir una segunda lectura seria dos formas de leer el
        # mismo Excel, que se separan sin que nadie lo note.
        bloque = FUENTE_APP[FUENTE_APP.index("def render_video_maintainer"):]
        self.assertIn("png_codigos_desde_excel", bloque)

    def test_reutiliza_las_urls_del_bucket_del_mantenedor_de_fotos(self):
        # `png_urls_a_probar` arma las mismas direcciones que usa la carga de
        # fotos, incluida la del host alterno para el 403 anonimo.
        bloque = FUENTE_APP[FUENTE_APP.index("def video_descargar_del_bucket"):]
        bloque = bloque[:bloque.index("\ndef ", 10)]
        self.assertIn("png_urls_a_probar", bloque)

    def test_reutiliza_la_busqueda_del_mantenedor_de_fotos(self):
        # `png_find_product` ya cruza el catalogo contra el metacampo: no se
        # escribe una segunda busqueda que se pueda separar de aquella.
        bloque = FUENTE_APP[FUENTE_APP.index("def video_buscar_producto"):]
        bloque = bloque[:bloque.index("\ndef ", 10)]
        self.assertIn("png_find_product", bloque)
        self.assertIn("session_shopify_products", bloque)

    def test_nunca_crea_productos(self):
        bloque = FUENTE_APP[FUENTE_APP.index("def video_publicar("):]
        bloque = bloque[:bloque.index("\ndef ", 10)]
        self.assertNotIn("product_create(", bloque)

    def test_los_diez_pasos_estan_declarados(self):
        # Los 10 pasos del requerimiento. Si se agrega o quita uno, la pantalla
        # de errores deja de coincidir con lo pedido.
        inicio = FUENTE_APP.index("VIDEO_PASOS = (")
        bloque = FUENTE_APP[inicio:FUENTE_APP.index("\n)\n", inicio)]
        pasos = re.findall(r'\("(\w+)", (?:f?)"([^"]+)"\)', bloque)
        self.assertEqual(len(pasos), 10, pasos)
        self.assertEqual(pasos[0][0], "producto")
        self.assertEqual(pasos[-1][0], "resultado")

    def test_el_intento_queda_en_la_auditoria_salga_bien_o_mal(self):
        bloque = FUENTE_APP[FUENTE_APP.index("def video_registrar_auditoria"):]
        bloque = bloque[:bloque.index("\ndef ", 10)]
        self.assertIn("log_user_activity", bloque)
        self.assertIn('resultado="ok" if resultado.get("ok") else "error"', bloque)

    def test_el_motor_no_importa_streamlit(self):
        # Regla de arquitectura del proyecto: engines/ nunca importa Streamlit.
        for archivo in ("engines/video_media.py",):
            fuente = (ROOT / archivo).read_text(encoding="utf-8")
            self.assertNotIn("import streamlit", fuente, archivo)



class TestElProcesoCompletoConShopifyFalso(unittest.TestCase):
    """Los 10 pasos encadenados, con una tienda y un bucket de mentira.

    Las clases de arriba prueban el motor puro; esta prueba el ORQUESTADOR, que
    es donde aterriza la posicion 2 y donde se decide de que carpeta se baja el
    video. Importa `app_matrixify`, asi que necesita Streamlit instalado; si no
    esta, la clase se salta en vez de fallar.
    """

    @classmethod
    def setUpClass(cls):
        try:
            import app_matrixify  # noqa: F401
        except Exception as exc:  # pragma: no cover - depende del entorno
            raise unittest.SkipTest(f"No se pudo importar app_matrixify: {exc}")
        cls.app = sys.modules["app_matrixify"]

    def setUp(self):
        self.app = type(self).app
        self.tienda = {
            "media": [foto("f1"), foto("f2"), foto("f3")],
            "reorder": [],
            "borrados": [],
            "staged": [],
            "descargas": [],
        }
        tienda = self.tienda
        self.marca_del_producto = "COLUMBIA"

        def _fetch_product_media(config, product_gid, first=50):
            return {"id": product_gid, "title": "Chaqueta Columbia",
                    "modCol": "2044361-6RX", "media": list(tienda["media"])}

        def _staged_upload_video(config, filename, mime, contenido, timeout=600):
            tienda["staged"].append((filename, mime, len(contenido)))
            return "https://shopify-staged/tmp/2044361_6RX_2.mp4"

        def _product_create_video_media(config, gid, resource_url, alt="", filename=""):
            nodo = video("v-nuevo", filename or "2044361_6RX_2.mp4", estado="UPLOADED")
            tienda["media"].append(nodo)          # Shopify SIEMPRE agrega al final.
            return [nodo]

        def _wait_video_media_ready(config, ids, **kwargs):
            return [{"id": i, "status": "READY", "mediaContentType": "VIDEO"} for i in ids]

        def _product_reorder_media(config, gid, moves):
            tienda["reorder"].append(moves)
            tienda["media"] = vm.orden_resultante(tienda["media"], moves)
            return {"id": "job", "done": True}

        def _product_delete_media(config, gid, ids):
            tienda["media"] = [n for n in tienda["media"] if n["id"] not in ids]
            tienda["borrados"].extend(ids)
            return list(ids)

        def _buscar(shopify_config, site_key, mod_col, force_refresh=False):
            return {"Product ID": "gid://shopify/Product/1", "Title": "Chaqueta Columbia",
                    "Mod-Col": mod_col, "Marca": self.marca_del_producto}, "tienda falsa"

        def _descargar(url, timeout=120):
            tienda["descargas"].append(url)
            nombre = url.rsplit("/", 1)[-1]
            return b"x" * 50_000, "video/mp4", nombre, url

        self._originales = {}
        for nombre, doble in (
            ("fetch_product_media", _fetch_product_media),
            ("staged_upload_video", _staged_upload_video),
            ("product_create_video_media", _product_create_video_media),
            ("wait_video_media_ready", _wait_video_media_ready),
            ("product_reorder_media", _product_reorder_media),
            ("product_delete_media", _product_delete_media),
            ("video_buscar_producto", _buscar),
            ("video_descargar_del_bucket", _descargar),
        ):
            self._originales[nombre] = getattr(self.app, nombre)
            setattr(self.app, nombre, doble)
        self._sleep = self.app.time.sleep
        self.app.time.sleep = lambda *a, **k: None

    def tearDown(self):
        for nombre, original in self._originales.items():
            setattr(self.app, nombre, original)
        self.app.time.sleep = self._sleep

    def _publicar(self, codigo="2044361-6RX", **kwargs):
        kwargs.setdefault("marca_pantalla", "COLUMBIA")
        return self.app.video_publicar(
            {"shop_domain": "prueba.myshopify.com", "admin_access_token": "t"},
            "columbia", codigo, **kwargs
        )

    def test_el_video_termina_publicado_y_en_posicion_dos(self):
        resultado = self._publicar()
        self.assertTrue(resultado["ok"], resultado["Estado"])
        self.assertEqual(resultado["Posición"], 2)
        self.assertEqual(resultado["Nombre"], "2044361_6RX_2.mp4")

    def test_se_baja_del_bucket_en_la_carpeta_de_la_marca(self):
        self._publicar()
        self.assertEqual(
            self.tienda["descargas"],
            ["https://ecom-imagenes.forus-digital.xyz.peru.s3.amazonaws.com/COLUMBIA/2044361_6RX_2.mp4"],
        )

    def test_la_carpeta_sale_del_metacampo_del_producto_y_no_de_la_pantalla(self):
        # Rockford.pe vende cuatro marcas: la de la barra lateral seria la
        # misma para todas y mandaria los videos al cajon equivocado.
        self.marca_del_producto = "PATAGONIA"
        resultado = self._publicar(marca_pantalla="ROCKFORD")
        self.assertEqual(resultado["Carpeta"], "PATAGONIA")
        self.assertIn("/PATAGONIA/", self.tienda["descargas"][0])

    def test_la_marca_del_excel_manda_sobre_el_metacampo(self):
        self.marca_del_producto = "COLUMBIA"
        resultado = self._publicar(marca_excel="SOREL", marca_pantalla="ROCKFORD")
        self.assertEqual(resultado["Carpeta"], "SOREL")

    def test_la_pantalla_es_el_ultimo_respaldo(self):
        self.marca_del_producto = ""
        resultado = self._publicar(marca_pantalla="VANS")
        self.assertEqual(resultado["Carpeta"], "VANS")

    def test_se_reordena_con_el_indice_cero(self):
        self._publicar()
        self.assertEqual(self.tienda["reorder"], [[{"id": "v-nuevo", "newPosition": "1"}]])

    def test_la_galeria_final_deja_la_foto_principal_primera(self):
        self._publicar()
        self.assertEqual([n["id"] for n in self.tienda["media"]], ["f1", "v-nuevo", "f2", "f3"])

    def test_se_entrega_a_shopify_con_el_nombre_canonico(self):
        self._publicar()
        self.assertEqual(self.tienda["staged"][0][0], "2044361_6RX_2.mp4")
        self.assertEqual(self.tienda["staged"][0][1], "video/mp4")

    def test_los_diez_pasos_quedan_registrados(self):
        resultado = self._publicar()
        self.assertEqual(len(resultado["pasos"]), 10)
        self.assertNotIn("pendiente", [p["estado"] for p in resultado["pasos"].values()])

    def test_un_producto_con_video_no_se_duplica(self):
        self.tienda["media"].insert(1, video("v-viejo", "viejo.mp4"))
        resultado = self._publicar()
        self.assertFalse(resultado["ok"])
        self.assertIn("ya tiene un video", resultado["Estado"])
        # Ni siquiera se gasta la descarga del bucket.
        self.assertEqual(self.tienda["descargas"], [])
        self.assertEqual(len(vm.videos_del_producto(self.tienda["media"])), 1)

    def test_reemplazar_borra_el_anterior_y_deja_uno_solo_en_posicion_dos(self):
        self.tienda["media"].insert(1, video("v-viejo", "viejo.mp4"))
        resultado = self._publicar(reemplazar=True)
        self.assertTrue(resultado["ok"], resultado["Estado"])
        self.assertEqual(self.tienda["borrados"], ["v-viejo"])
        self.assertEqual(len(vm.videos_del_producto(self.tienda["media"])), 1)
        self.assertEqual(resultado["Posición"], 2)

    def test_un_producto_que_no_existe_para_en_el_paso_uno(self):
        self.app.video_buscar_producto = lambda *a, **k: (None, "no está en este sitio")
        resultado = self._publicar()
        self.assertFalse(resultado["ok"])
        self.assertEqual(resultado["pasos"]["producto"]["estado"], "error")
        self.assertEqual(self.tienda["descargas"], [])

    def test_un_codigo_mal_escrito_no_llega_a_shopify(self):
        resultado = self._publicar("SINGUION")
        self.assertFalse(resultado["ok"])
        self.assertEqual(resultado["pasos"]["producto"]["estado"], "error")

    def test_si_el_video_no_esta_en_el_bucket_se_dice_en_su_paso(self):
        def _revienta(url, timeout=120):
            raise self.app.ShopifyApiError("HTTP 404 (no existe en el bucket)")

        self.app.video_descargar_del_bucket = _revienta
        resultado = self._publicar()
        self.assertFalse(resultado["ok"])
        self.assertEqual(resultado["pasos"]["descarga"]["estado"], "error")
        self.assertIn("404", resultado["Estado"])
        # Los pasos previos quedaron en ok: se ve exactamente donde se corto.
        self.assertEqual(resultado["pasos"]["url"]["estado"], "ok")
        self.assertEqual(self.tienda["staged"], [])

    def test_si_shopify_rechaza_el_video_se_dice_en_que_paso(self):
        def _revienta(*a, **k):
            raise self.app.ShopifyApiError("Video demasiado largo")

        self.app.staged_upload_video = _revienta
        resultado = self._publicar()
        self.assertFalse(resultado["ok"])
        self.assertEqual(resultado["pasos"]["shopify"]["estado"], "error")
        self.assertIn("Video demasiado largo", resultado["Estado"])

    def test_si_shopify_no_procesa_el_video_se_dice(self):
        self.app.wait_video_media_ready = lambda config, ids, **k: [
            {"id": ids[0], "status": "FAILED", "mediaErrors": [{"message": "formato no soportado"}]}
        ]
        resultado = self._publicar()
        self.assertFalse(resultado["ok"])
        self.assertEqual(resultado["pasos"]["procesado"]["estado"], "error")

    def test_si_el_video_no_queda_segundo_se_reporta_como_fallo(self):
        # El peor error silencioso posible: publicado pero en la posicion
        # equivocada. Tiene que salir en rojo, no en verde.
        self.app.product_reorder_media = lambda *a, **k: {"id": "job", "done": True}
        resultado = self._publicar()
        self.assertFalse(resultado["ok"])
        self.assertEqual(resultado["pasos"]["posicion"]["estado"], "error")

    def test_la_fila_de_resultado_resume_lo_que_paso(self):
        fila = self.app.video_fila_de_resultado(self._publicar())
        self.assertEqual(fila["Resultado"], "Publicado")
        self.assertEqual(fila["Posición"], 2)
        self.assertEqual(fila["Código Modelo Color"], "2044361-6RX")

    def test_el_detalle_lista_los_diez_pasos_de_cada_codigo(self):
        filas = self.app.video_detalle_de_pasos([self._publicar()])
        self.assertEqual(len(filas), 10)
        self.assertEqual(filas[0]["Código Modelo Color"], "2044361-6RX")



class TestElAnalisisPrevio(unittest.TestCase):
    """FASE 1: mirar antes de escribir, igual que el mantenedor de fotos.

    Sin esto, en una lista de 50 codigos se empieza a publicar y uno se entera
    a mitad de camino de que 30 videos no estaban en el bucket. El de fotos
    trabaja en dos tiempos por esta misma razon.
    """

    @classmethod
    def setUpClass(cls):
        try:
            import app_matrixify  # noqa: F401
        except Exception as exc:  # pragma: no cover - depende del entorno
            raise unittest.SkipTest(f"No se pudo importar app_matrixify: {exc}")
        cls.app = sys.modules["app_matrixify"]

    def setUp(self):
        self.app = type(self).app
        self.catalogo = {
            "2044361-6RX": {"Product ID": "gid://p/1", "Title": "Chaqueta",
                            "Mod-Col": "2044361-6RX", "Marca": "COLUMBIA"},
            "2045001-010": {"Product ID": "gid://p/2", "Title": "Casaca",
                            "Mod-Col": "2045001-010", "Marca": "PATAGONIA"},
        }
        # True existe, False no existe, None = el bucket no deja saberlo (403).
        self.bucket = {
            "COLUMBIA/2044361_6RX_2.mp4": True,
            "PATAGONIA/2045001_010_2.mp4": False,
        }
        self.consultas = []
        self._orig = (self.app.video_buscar_producto, self.app.video_comprobar_en_bucket)

        def _buscar(cfg, sk, cod, force_refresh=False):
            producto = self.catalogo.get(cod)
            return (producto, "doble") if producto else (None, "no está en este sitio")

        def _bucket(url, timeout=8):
            self.consultas.append(url)
            clave = "/".join(url.split("/")[-2:])
            existe = self.bucket.get(clave)
            if existe is True:
                return True, ""
            if existe is False:
                return False, "404 en el bucket"
            return None, "403 anónimo"

        self.app.video_buscar_producto = _buscar
        self.app.video_comprobar_en_bucket = _bucket

    def tearDown(self):
        self.app.video_buscar_producto, self.app.video_comprobar_en_bucket = self._orig

    def _analizar(self, codigos, marca_pantalla="ROCKFORD", marcas_excel=None):
        trabajos, _ = vm.trabajos_desde_codigos(codigos, marca_por_defecto="")
        for trabajo in trabajos:
            trabajo["Marca Excel"] = (marcas_excel or {}).get(trabajo["Código Modelo Color"], "")
        return self.app.video_analizar_codigos({}, "columbia", trabajos, marca_pantalla)

    def test_separa_lo_que_se_puede_cargar_de_lo_que_no(self):
        filas = self._analizar(["2044361-6RX", "2045001-010", "9999999-ZZZ"])
        estados = {f["Código Modelo Color"]: f["Estado"] for f in filas}
        self.assertEqual(estados["2044361-6RX"], vm.ESTADO_LISTO_PARA_CARGAR)
        self.assertEqual(estados["2045001-010"], vm.ESTADO_SIN_VIDEO)
        self.assertEqual(estados["9999999-ZZZ"], vm.ESTADO_SIN_PRODUCTO)

    def test_solo_se_publica_lo_que_esta_listo(self):
        filas = self._analizar(["2044361-6RX", "2045001-010", "9999999-ZZZ"])
        self.assertEqual(
            [f["Código Modelo Color"] for f in vm.publicables(filas)], ["2044361-6RX"]
        )

    def test_sin_confirmar_SI_se_intenta(self):
        # El bucket contesta 403 a las consultas anonimas y eso NO es "no
        # existe": tratarlo como tal dejaria fuera videos que si estan.
        self.bucket = {}
        filas = self._analizar(["2044361-6RX"])
        self.assertEqual(filas[0]["Estado"], vm.ESTADO_SIN_CONFIRMAR)
        self.assertEqual(len(vm.publicables(filas)), 1)

    def test_la_carpeta_sale_del_metacampo_de_cada_producto(self):
        # Dos marcas distintas en el mismo Excel y en el mismo sitio: es el
        # caso de Rockford.pe, que vende cuatro marcas.
        filas = self._analizar(["2044361-6RX", "2045001-010"])
        carpetas = {f["Código Modelo Color"]: f["Carpeta"] for f in filas}
        self.assertEqual(carpetas["2044361-6RX"], "COLUMBIA")
        self.assertEqual(carpetas["2045001-010"], "PATAGONIA")

    def test_la_marca_del_excel_manda_sobre_el_metacampo(self):
        filas = self._analizar(["2044361-6RX"], marcas_excel={"2044361-6RX": "SOREL"})
        self.assertEqual(filas[0]["Carpeta"], "SOREL")
        self.assertIn("Excel", filas[0]["Origen de la marca"])

    def test_no_se_gasta_una_consulta_en_un_codigo_sin_producto(self):
        self._analizar(["9999999-ZZZ"])
        self.assertEqual(self.consultas, [])

    def test_se_consulta_la_url_de_la_carpeta_correcta(self):
        self._analizar(["2045001-010"])
        self.assertEqual(len(self.consultas), 1)
        self.assertIn("/PATAGONIA/2045001_010_2.mp4", self.consultas[0])

    def test_el_resumen_cuenta_por_estado(self):
        filas = self._analizar(["2044361-6RX", "2045001-010", "9999999-ZZZ"])
        resumen = vm.resumen_del_analisis(filas)
        self.assertEqual(resumen[vm.ESTADO_LISTO_PARA_CARGAR], 1)
        self.assertEqual(resumen[vm.ESTADO_SIN_VIDEO], 1)
        self.assertEqual(resumen[vm.ESTADO_SIN_PRODUCTO], 1)

    def test_el_analisis_no_escribe_nada_en_shopify(self):
        # Lo mas importante de la fase 1: se puede pulsar Revisar sin miedo.
        fuente = FUENTE_APP[FUENTE_APP.index("def video_analizar_codigos"):]
        fuente = fuente[:fuente.index("\ndef ", 10)]
        for mutacion in ("product_create_video_media", "product_reorder_media",
                         "product_delete_media", "staged_upload_video", "video_publicar("):
            self.assertNotIn(mutacion, fuente, mutacion)


class TestSeProcesaPorBloques(unittest.TestCase):
    """Cada bloque termina, se GUARDA y la barra avanza.

    Es la misma proteccion de la carga parcial y del mantenedor de fotos: si
    Shopify deja de responder en el bloque 4, lo de los tres primeros ya esta
    publicado y su resultado no se pierde.
    """

    @classmethod
    def setUpClass(cls):
        try:
            import app_matrixify  # noqa: F401
        except Exception as exc:  # pragma: no cover - depende del entorno
            raise unittest.SkipTest(f"No se pudo importar app_matrixify: {exc}")
        cls.app = sys.modules["app_matrixify"]

    def test_se_reutiliza_el_partidor_de_bloques_de_las_fotos(self):
        # No se escribe un segundo partidor: es `png_bloques`, el mismo.
        self.assertIn("png_bloques(listos, VIDEO_MODELOS_POR_BLOQUE)", FUENTE_APP)
        self.assertIn("png_bloques(list(trabajos or []), VIDEO_MODELOS_POR_BLOQUE)", FUENTE_APP)

    def test_el_bloque_de_video_es_mas_chico_que_el_de_fotos(self):
        # Una foto son diez HEAD; un video es bajar decenas de MB y volver a
        # subirlos. Bloques mas chicos guardan mas seguido.
        self.assertLess(self.app.VIDEO_MODELOS_POR_BLOQUE, self.app.PNG_MODELOS_POR_BLOQUE)

    def test_los_bloques_parten_bien_la_lista(self):
        tamanos = [len(b) for b in self.app.png_bloques(list(range(12)),
                                                        self.app.VIDEO_MODELOS_POR_BLOQUE)]
        self.assertEqual(sum(tamanos), 12)
        self.assertTrue(all(t <= self.app.VIDEO_MODELOS_POR_BLOQUE for t in tamanos))

    def test_se_guarda_al_cerrar_cada_bloque_y_no_al_final(self):
        bloque = FUENTE_APP[FUENTE_APP.index("bloques = png_bloques(listos"):]
        bloque = bloque[:bloque.index("render_video_resultados")]
        guardado = bloque.index("st.session_state[clave_resultados] = list(resultados)")
        cierre_del_for = bloque.index("barra.empty()")
        self.assertLess(guardado, cierre_del_for,
                        "El guardado tiene que estar DENTRO del bucle de bloques")


class TestLaComprobacionDelBucketReutilizaLaDeFotos(unittest.TestCase):
    """`png_comprobar_url` ya resuelve lo dificil: los tres estados y el 403."""

    @classmethod
    def setUpClass(cls):
        try:
            import app_matrixify  # noqa: F401
        except Exception as exc:  # pragma: no cover - depende del entorno
            raise unittest.SkipTest(f"No se pudo importar app_matrixify: {exc}")
        cls.app = sys.modules["app_matrixify"]

    def test_se_apoya_en_png_comprobar_url(self):
        bloque = FUENTE_APP[FUENTE_APP.index("def video_comprobar_en_bucket"):]
        bloque = bloque[:bloque.index("\ndef ", 10)]
        self.assertIn("png_comprobar_url", bloque)

    def test_acepta_octet_stream_como_video(self):
        # S3 devuelve application/octet-stream para los mp4 a los que nadie les
        # puso el tipo. Rechazarlo dejaria fuera videos bien subidos.
        self.assertIn("application/octet-stream", vm.TIPOS_DE_VIDEO)
        self.assertIn("video/", vm.TIPOS_DE_VIDEO)

    def test_las_fotos_no_cambian_de_comportamiento(self):
        # El parametro nuevo trae por defecto el tipo de las fotos, asi que
        # `png_comprobar_url` sigue haciendo exactamente lo mismo para ellas.
        import inspect

        firma = inspect.signature(self.app.png_comprobar_url)
        self.assertEqual(firma.parameters["tipos"].default, ("image/",))

if __name__ == "__main__":
    unittest.main(verbosity=2)
