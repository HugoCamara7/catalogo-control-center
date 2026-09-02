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
from engines import s3_uploader as s3          # noqa: E402

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


class TestValidacionDelVideo(unittest.TestCase):
    """Se comprueba ANTES de subir. Un archivo de 1,4 GB sube durante minutos y
    recien despues Shopify lo marca FAILED: es el peor lugar para enterarse."""

    def test_solo_mp4(self):
        errores, _ = vm.validar_video("video.mov", 5_000_000)
        self.assertTrue(errores)

    def test_un_mp4_normal_pasa_sin_avisos(self):
        errores, avisos = vm.validar_video("video.mp4", 5_000_000)
        self.assertEqual(errores, [])
        self.assertEqual(avisos, [])

    def test_el_archivo_vacio_se_rechaza(self):
        errores, _ = vm.validar_video("video.mp4", 0)
        self.assertTrue(errores)

    def test_por_encima_del_tope_de_shopify_se_rechaza(self):
        errores, _ = vm.validar_video("video.mp4", vm.VIDEO_MAX_BYTES + 1)
        self.assertTrue(errores)

    def test_un_video_pesado_avisa_pero_no_frena(self):
        errores, avisos = vm.validar_video("video.mp4", vm.VIDEO_AVISO_BYTES + 1)
        self.assertEqual(errores, [])
        self.assertTrue(avisos)

    def test_sin_archivo_hay_error(self):
        errores, _ = vm.validar_video("", 0)
        self.assertTrue(errores)

    def test_faltan_datos_del_producto(self):
        self.assertTrue(vm.validar_datos_del_producto("", "2044361", "6RX"))
        self.assertTrue(vm.validar_datos_del_producto("COLUMBIA", "", "6RX"))
        self.assertTrue(vm.validar_datos_del_producto("COLUMBIA", "2044361", ""))
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


class TestCargaMasiva(unittest.TestCase):
    """Mismo motor y mismo nombre que el modo individual. Solo cambia el origen."""

    FILAS = [
        {"Marca": "COLUMBIA", "Modelo": "2044361", "Color": "6RX", "Video": "video1.mp4"},
        {"Marca": "COLUMBIA", "Modelo": "2045001", "Color": "010", "Video": "video2.mp4"},
    ]

    def test_cada_fila_trae_nombre_ruta_y_url_resueltos(self):
        trabajos, descartados = vm.trabajos_de_carga_masiva(self.FILAS)
        self.assertEqual(len(trabajos), 2)
        self.assertEqual(descartados, [])
        self.assertEqual(trabajos[0]["Nombre generado"], "2044361_6RX_2.mp4")
        self.assertEqual(trabajos[0]["Clave S3"], "COLUMBIA/2044361_6RX_2.mp4")
        self.assertEqual(trabajos[1]["Nombre generado"], "2045001_010_2.mp4")

    def test_el_nombre_masivo_es_el_mismo_que_el_individual(self):
        trabajos, _ = vm.trabajos_de_carga_masiva(self.FILAS)
        self.assertEqual(trabajos[0]["Nombre generado"], vm.nombre_de_video("2044361", "6RX"))
        self.assertEqual(trabajos[0]["URL"], vm.url_de_video("COLUMBIA", "2044361", "6RX"))

    def test_las_filas_repetidas_se_descartan_con_su_motivo(self):
        trabajos, descartados = vm.trabajos_de_carga_masiva(self.FILAS + [self.FILAS[0]])
        self.assertEqual(len(trabajos), 2)
        self.assertEqual(len(descartados), 1)
        self.assertIn("Repetido", descartados[0]["Motivo"])

    def test_una_fila_sin_color_se_descarta_y_se_explica(self):
        trabajos, descartados = vm.trabajos_de_carga_masiva(
            [{"Marca": "COLUMBIA", "Modelo": "2044361", "Color": "", "Video": "v.mp4"}]
        )
        self.assertEqual(trabajos, [])
        self.assertIn("color", descartados[0]["Motivo"].lower())

    def test_sin_columna_marca_se_usa_la_elegida_en_pantalla(self):
        trabajos, _ = vm.trabajos_de_carga_masiva(
            [{"Modelo": "2044361", "Color": "6RX", "Video": "v.mp4"}],
            marca_por_defecto="PATAGONIA",
        )
        self.assertEqual(trabajos[0]["Clave S3"], "PATAGONIA/2044361_6RX_2.mp4")

    def test_un_archivo_sin_columnas_utiles_no_devuelve_trabajos(self):
        trabajos, descartados = vm.trabajos_de_carga_masiva([{"Comentario": "hola"}])
        self.assertEqual(trabajos, [])
        self.assertTrue(descartados)

    def test_un_archivo_vacio_lo_dice(self):
        trabajos, descartados = vm.trabajos_de_carga_masiva([])
        self.assertEqual(trabajos, [])
        self.assertTrue(descartados)

    def test_los_videos_se_emparejan_por_nombre(self):
        class Archivo:
            def __init__(self, name):
                self.name = name

        trabajos, _ = vm.trabajos_de_carga_masiva(self.FILAS)
        emparejados, sin_archivo = vm.emparejar_videos_con_trabajos(
            trabajos, [Archivo("video2.mp4"), Archivo("video1.mp4")]
        )
        self.assertEqual(len(emparejados), 2)
        self.assertEqual(sin_archivo, [])
        self.assertEqual(emparejados[0]["archivo"].name, "video1.mp4")

    def test_un_trabajo_sin_su_archivo_se_reporta_y_no_se_publica(self):
        # Subir un video al producto equivocado es peor que no subirlo.
        class Archivo:
            def __init__(self, name):
                self.name = name

        trabajos, _ = vm.trabajos_de_carga_masiva(self.FILAS)
        emparejados, sin_archivo = vm.emparejar_videos_con_trabajos(trabajos, [Archivo("video1.mp4")])
        self.assertEqual(len(emparejados), 1)
        self.assertEqual(len(sin_archivo), 1)


class TestSubidaAlBucket(unittest.TestCase):
    """La app siempre LEYO del bucket; escribir en el es nuevo.

    Sin la seccion [s3] en Secrets no se inventa una subida: se dice que falta.
    """

    class ClienteFalso:
        def __init__(self):
            self.llamadas = []

        def put_object(self, **kwargs):
            self.llamadas.append(kwargs)

    def test_sin_bucket_ni_credenciales_no_esta_configurado(self):
        self.assertFalse(s3.s3_esta_configurado({}))

    def test_con_llave_a_medias_no_esta_configurado(self):
        config = s3.configuracion_s3({"aws_access_key_id": "AKIA"})
        self.assertFalse(s3.s3_esta_configurado(config))

    def test_con_las_dos_llaves_esta_configurado(self):
        config = s3.configuracion_s3({"aws_access_key_id": "AKIA", "aws_secret_access_key": "x"})
        self.assertTrue(s3.s3_esta_configurado(config))

    def test_el_bucket_por_defecto_es_el_que_ya_usa_la_app(self):
        self.assertEqual(s3.configuracion_s3({})["bucket"], "ecom-imagenes.forus-digital.xyz.peru")
        self.assertIn(s3.BUCKET_POR_DEFECTO, vm.host_de_imagenes())

    def test_se_escribe_en_la_ruta_de_la_marca(self):
        cliente = self.ClienteFalso()
        config = s3.configuracion_s3({"aws_access_key_id": "AKIA", "aws_secret_access_key": "x"})
        clave = s3.subir_bytes(
            config, vm.clave_s3("COLUMBIA", "2044361", "6RX"), b"datos",
            content_type=vm.MIME_VIDEO, cliente=cliente,
        )
        self.assertEqual(clave, "COLUMBIA/2044361_6RX_2.mp4")
        self.assertEqual(cliente.llamadas[0]["Key"], "COLUMBIA/2044361_6RX_2.mp4")
        self.assertEqual(cliente.llamadas[0]["ContentType"], "video/mp4")

    def test_el_acl_solo_se_manda_si_secrets_lo_pide(self):
        # Muchos buckets tienen "bucket owner enforced" y ahi cualquier ACL es
        # un 400: mandarlo siempre romperia la subida en esos buckets.
        cliente = self.ClienteFalso()
        config = s3.configuracion_s3({"aws_access_key_id": "A", "aws_secret_access_key": "x"})
        s3.subir_bytes(config, "COLUMBIA/a.mp4", b"d", cliente=cliente)
        self.assertNotIn("ACL", cliente.llamadas[0])

        cliente2 = self.ClienteFalso()
        config2 = s3.configuracion_s3(
            {"aws_access_key_id": "A", "aws_secret_access_key": "x", "acl": "public-read"}
        )
        s3.subir_bytes(config2, "COLUMBIA/a.mp4", b"d", cliente=cliente2)
        self.assertEqual(cliente2.llamadas[0]["ACL"], "public-read")

    def test_un_archivo_vacio_no_llega_al_bucket(self):
        cliente = self.ClienteFalso()
        config = s3.configuracion_s3({"aws_access_key_id": "A", "aws_secret_access_key": "x"})
        with self.assertRaises(s3.S3Error):
            s3.subir_bytes(config, "COLUMBIA/a.mp4", b"", cliente=cliente)
        self.assertEqual(cliente.llamadas, [])

    def test_boto3_esta_declarado_en_requirements(self):
        # La clase de fallo del 24/08/2026: libreria usada y no declarada.
        self.assertIn("boto3", (ROOT / "requirements.txt").read_text(encoding="utf-8"))


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
            "render_video_maintainer", "render_video_masivo", "render_video_resultado",
            "render_video_galeria", "render_video_pasos", "video_publicar",
            "video_buscar_producto", "video_subir_a_s3", "video_publicar_en_shopify",
            "video_colocar_en_posicion", "video_reemplazar_existente",
            "video_esperar_procesado", "video_leer_galeria", "video_registrar_auditoria",
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
        for archivo in ("engines/video_media.py", "engines/s3_uploader.py"):
            fuente = (ROOT / archivo).read_text(encoding="utf-8")
            self.assertNotIn("import streamlit", fuente, archivo)



class TestElProcesoCompletoConShopifyFalso(unittest.TestCase):
    """Los 10 pasos encadenados, con una tienda de mentira.

    Las clases de arriba prueban el motor puro; esta prueba el ORQUESTADOR, que
    es donde de verdad aterriza la posicion 2: se comprueba que se llame a
    `productReorderMedia` con el movimiento correcto y que el video termine
    segundo en la galeria que devuelve la tienda.

    Importa `app_matrixify`, asi que necesita Streamlit instalado. Si no esta,
    la clase se salta en vez de fallar.
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
        }
        tienda = self.tienda

        def _fetch_product_media(config, product_gid, first=50):
            return {"id": product_gid, "title": "Chaqueta Columbia", "handle": "chaqueta",
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
                    "Mod-Col": mod_col}, "tienda falsa"

        self._originales = {}
        for nombre, doble in (
            ("fetch_product_media", _fetch_product_media),
            ("staged_upload_video", _staged_upload_video),
            ("product_create_video_media", _product_create_video_media),
            ("wait_video_media_ready", _wait_video_media_ready),
            ("product_reorder_media", _product_reorder_media),
            ("product_delete_media", _product_delete_media),
            ("video_buscar_producto", _buscar),
        ):
            self._originales[nombre] = getattr(self.app, nombre)
            setattr(self.app, nombre, doble)
        # Sin esto la prueba esperaria 1,5s por relectura de la galeria.
        self._sleep = self.app.time.sleep
        self.app.time.sleep = lambda *a, **k: None

    def tearDown(self):
        for nombre, original in self._originales.items():
            setattr(self.app, nombre, original)
        self.app.time.sleep = self._sleep

    class ArchivoFalso:
        name = "cualquier_nombre.mp4"

        def __init__(self, datos=b"x" * 50_000):
            self.datos = datos
            self.size = len(datos)

        def seek(self, *a):
            return 0

        def read(self):
            return self.datos

    def _publicar(self, **kwargs):
        return self.app.video_publicar(
            {"shop_domain": "prueba.myshopify.com", "admin_access_token": "t"},
            "columbia", "COLUMBIA", "2044361", "6RX", self.ArchivoFalso(), **kwargs
        )

    def test_el_video_termina_publicado_y_en_posicion_dos(self):
        resultado = self._publicar()
        self.assertTrue(resultado["ok"], resultado["Estado"])
        self.assertEqual(resultado["Posición"], 2)
        self.assertEqual(resultado["Nombre"], "2044361_6RX_2.mp4")
        self.assertEqual(
            resultado["URL"],
            "https://ecom-imagenes.forus-digital.xyz.peru.s3.amazonaws.com/COLUMBIA/2044361_6RX_2.mp4",
        )

    def test_se_reordena_con_el_indice_cero(self):
        self._publicar()
        self.assertEqual(self.tienda["reorder"], [[{"id": "v-nuevo", "newPosition": "1"}]])

    def test_la_galeria_final_deja_la_foto_principal_primera(self):
        self._publicar()
        self.assertEqual(
            [n["id"] for n in self.tienda["media"]], ["f1", "v-nuevo", "f2", "f3"]
        )

    def test_el_archivo_se_sube_con_el_nombre_generado_y_no_con_el_original(self):
        self._publicar()
        self.assertEqual(self.tienda["staged"][0][0], "2044361_6RX_2.mp4")
        self.assertEqual(self.tienda["staged"][0][1], "video/mp4")

    def test_los_diez_pasos_quedan_registrados(self):
        resultado = self._publicar()
        self.assertEqual(len(resultado["pasos"]), 10)
        self.assertNotIn("pendiente", [p["estado"] for p in resultado["pasos"].values()])

    def test_sin_credenciales_de_s3_avisa_pero_publica_igual(self):
        # El bucket es el respaldo con el nombre canonico; quien sirve el video
        # en la ficha es el CDN de Shopify.
        resultado = self._publicar()
        self.assertFalse(resultado["En S3"])
        self.assertEqual(resultado["pasos"]["s3"]["estado"], "aviso")
        self.assertTrue(resultado["ok"])

    def test_un_producto_con_video_no_se_duplica(self):
        self.tienda["media"].insert(1, video("v-viejo", "viejo.mp4"))
        resultado = self._publicar()
        self.assertFalse(resultado["ok"])
        self.assertIn("ya tiene un video", resultado["Estado"])
        self.assertEqual(self.tienda["staged"], [])   # ni siquiera se subio nada
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
        self.assertIn("no encontrado", resultado["Estado"])
        self.assertEqual(self.tienda["staged"], [])

    def test_si_shopify_rechaza_el_video_se_dice_en_que_paso(self):
        def _revienta(*a, **k):
            raise self.app.ShopifyApiError("Video demasiado largo")

        self.app.staged_upload_video = _revienta
        resultado = self._publicar()
        self.assertFalse(resultado["ok"])
        self.assertEqual(resultado["pasos"]["shopify"]["estado"], "error")
        self.assertIn("Video demasiado largo", resultado["Estado"])
        # Los pasos anteriores quedaron en ok: se ve exactamente donde se corto.
        self.assertEqual(resultado["pasos"]["nombre"]["estado"], "ok")

    def test_si_shopify_no_procesa_el_video_se_dice(self):
        self.app.wait_video_media_ready = lambda config, ids, **k: [
            {"id": ids[0], "status": "FAILED", "mediaErrors": [{"message": "formato no soportado"}]}
        ]
        resultado = self._publicar()
        self.assertFalse(resultado["ok"])
        self.assertEqual(resultado["pasos"]["procesado"]["estado"], "error")
        self.assertIn("formato no soportado", resultado["Estado"])

    def test_si_el_video_no_queda_segundo_se_reporta_como_fallo(self):
        # El peor error silencioso posible: publicado pero en la posicion
        # equivocada. Tiene que salir en rojo, no en verde.
        self.app.product_reorder_media = lambda *a, **k: {"id": "job", "done": True}
        resultado = self._publicar()
        self.assertFalse(resultado["ok"])
        self.assertEqual(resultado["pasos"]["posicion"]["estado"], "error")

    def test_un_archivo_que_no_es_mp4_no_llega_a_shopify(self):
        archivo = self.ArchivoFalso()
        archivo.name = "video.mov"
        resultado = self.app.video_publicar(
            {"shop_domain": "x", "admin_access_token": "t"},
            "columbia", "COLUMBIA", "2044361", "6RX", archivo,
        )
        self.assertFalse(resultado["ok"])
        self.assertEqual(resultado["pasos"]["archivo"]["estado"], "error")
        self.assertEqual(self.tienda["staged"], [])

if __name__ == "__main__":
    unittest.main(verbosity=2)
