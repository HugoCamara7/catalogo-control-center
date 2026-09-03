# -*- coding: utf-8 -*-
"""Motor del Mantenedor de Videos.

Sin Streamlit. Todo lo que se puede decidir sin tocar la red vive aqui, para
que se pueda probar sin tienda y sin bucket.

Como funciona, y por que
------------------------
**Igual que las fotos: el video YA ESTA en el bucket.** Nadie sube un archivo
desde la app. El usuario entrega un Excel con los codigos que quiere cargar y
la app arma la direccion, la busca y la publica:

    2044361-6RX  ->  COLUMBIA/2044361_6RX_2.mp4
                 ->  https://ecom-imagenes.../COLUMBIA/2044361_6RX_2.mp4

El `_2` del nombre ES la posicion en la galeria: el video va inmediatamente
despues de la foto principal. No es un numero de version.

Shopify no se baja el video solo
--------------------------------
Con una foto alcanza con pasarle la URL publica y el la descarga. Con un video
NO: `originalSource` de un media VIDEO solo acepta el `resourceUrl` de un
staged upload. Asi que la app hace de intermediaria — baja el mp4 del bucket y
se lo entrega a Shopify — igual que ya hace `_sync_product_photos_direct` con
las fotos. Para quien usa la pantalla es lo mismo que las fotos: solo codigos.

La carpeta la manda la MARCA, no el sitio
-----------------------------------------
Rockford.pe vende Columbia, Patagonia, Sorel y Mountain Hardwear: tomar la
carpeta del sitio dejaria los videos de cuatro marcas en `ROCKFORD/`. Se lee
de `BRAND_IMAGE_FOLDERS`, el mismo diccionario de las fotos: aqui NO se copia,
se importa.

La marca de cada codigo sale, en este orden: de la columna Marca del Excel si
viene, del metacampo `custom.marca` del propio producto (la fuente
autoritativa), y por ultimo de la marca elegida en pantalla.

La posicion 2 no es decoracion
------------------------------
Shopify NO deja elegir la posicion al crear el media: siempre lo agrega al
final. Por eso hay un segundo paso obligatorio (`productReorderMedia`) y por
eso `plan_de_orden()` existe: traduce "quiero el video segundo" a la lista de
movimientos que espera la mutacion, que trabaja con indices que empiezan en 0.
"""

import re

# La posicion, contada como la ve una persona: 1 es la foto principal.
POSICION_VIDEO = 2

# El sufijo del nombre del archivo. Es el MISMO numero que la posicion a
# proposito: el nombre dice donde va a quedar el video.
SUFIJO_VIDEO = str(POSICION_VIDEO)

EXTENSION_VIDEO = "mp4"
MIME_VIDEO = "video/mp4"

# Extensiones que se aceptan al subir. El nombre que se genera SIEMPRE es .mp4
# porque es lo unico que Shopify publica sin recodificar del lado del usuario.
EXTENSIONES_ACEPTADAS = ("mp4",)

# Tope de Shopify para un video de producto. Por encima, la subida se acepta y
# el media termina en FAILED varios minutos despues, que es el peor momento
# para enterarse.
VIDEO_MAX_BYTES = 1024 * 1024 * 1024          # 1 GB
# Aviso, no bloqueo: por encima de esto la subida tarda y el procesamiento de
# Shopify tambien, pero es legal.
VIDEO_AVISO_BYTES = 100 * 1024 * 1024         # 100 MB
VIDEO_MIN_BYTES = 1024                        # menos que esto no es un video

# Content-Type que cuentan como "hay un video ahi". El bucket devuelve
# octet-stream para los mp4 a los que nadie les puso el tipo: tratarlo como
# "no existe" dejaria fuera videos perfectamente subidos.
TIPOS_DE_VIDEO = ("video/", "application/octet-stream")

# Estado de un codigo tras ANALIZAR, sin haber escrito nada todavia. Son tres y
# no dos por la misma razon que en las fotos: el bucket contesta 403 a las
# consultas anonimas, y eso NO es "no existe".
ESTADO_LISTO_PARA_CARGAR = "Listo para cargar"
ESTADO_SIN_CONFIRMAR = "Sin confirmar"
ESTADO_SIN_VIDEO = "Sin video en el bucket"
ESTADO_SIN_PRODUCTO = "No está en Shopify"
ESTADO_YA_TIENE = "Ya tiene video"

# Los que se mandan a publicar. "Sin confirmar" entra a proposito: el bucket no
# deja comprobar de forma anonima, y quien de verdad baja el archivo es la app,
# que devuelve el error exacto si no esta.
ESTADOS_PUBLICABLES = (ESTADO_LISTO_PARA_CARGAR, ESTADO_SIN_CONFIRMAR)

# Tipos de media de Shopify.
MEDIA_VIDEO = "VIDEO"
MEDIA_IMAGEN = "IMAGE"
MEDIA_VIDEO_EXTERNO = "EXTERNAL_VIDEO"

# Estados de un media de Shopify. El procesamiento es asincrono: un video
# recien creado sale UPLOADED, pasa por PROCESSING y recien despues es READY.
ESTADO_LISTO = "READY"
ESTADO_FALLIDO = "FAILED"
ESTADOS_EN_CURSO = ("UPLOADED", "PROCESSING")


def texto(valor):
    if valor is None:
        return ""
    return str(valor).strip()


def normalizar_modelo(valor):
    """El modelo, en mayusculas y sin separadores sueltos.

    Se aceptan `2044361`, ` 2044361 ` y `2044361-6RX` pegado por error: en ese
    ultimo caso se queda con el tramo del modelo, porque el color viene aparte
    en su propio campo y quedaria duplicado en el nombre del archivo.
    """
    limpio = re.sub(r"\s+", "", texto(valor)).upper()
    if "-" in limpio:
        limpio = limpio.rsplit("-", 1)[0]
    return re.sub(r"[^A-Z0-9]", "", limpio)


def normalizar_color(valor):
    """El color, en mayusculas y sin separadores. `6rx` -> `6RX`."""
    limpio = re.sub(r"\s+", "", texto(valor)).upper()
    if "-" in limpio:
        limpio = limpio.rsplit("-", 1)[-1]
    return re.sub(r"[^A-Z0-9]", "", limpio)


def codigo_modelo_color(modelo, color):
    """`2044361` + `6RX` -> `2044361-6RX`, la clave con la que busca la app.

    Es el mismo formato del metacampo `custom.codigo_modelo_color` y el mismo
    que usa el mantenedor de fotos, para que la busqueda del producto sea
    exactamente la que ya existe.
    """
    modelo = normalizar_modelo(modelo)
    color = normalizar_color(color)
    if not modelo or not color:
        return ""
    return f"{modelo}-{color}"


def carpeta_de_marca(marca, respaldo=""):
    """La carpeta del bucket para esa marca comercial.

    Se lee del MISMO diccionario que usan las fotos. No se copia aqui: el dia
    que se agregue una marca, se agrega en un solo lugar y las fotos y los
    videos van juntos a la carpeta nueva.
    """
    from generate_columbia_matrixify import BRAND_IMAGE_FOLDERS, normalize_brand_name

    clave = normalize_brand_name(marca)
    carpeta = BRAND_IMAGE_FOLDERS.get(clave, "")
    if carpeta:
        return carpeta
    # Una marca que no esta en el diccionario todavia se puede resolver: el
    # bucket usa el nombre en mayusculas y sin espacios.
    propuesta = re.sub(r"[^A-Z0-9]", "", clave)
    return propuesta or texto(respaldo).upper()


def marcas_disponibles():
    """Las marcas que tienen carpeta en el bucket, ordenadas y sin repetir.

    Es lo que alimenta el selector de marca de la pantalla. Sale del mismo
    diccionario de las fotos, asi que no hay una segunda lista que mantener.
    """
    from generate_columbia_matrixify import BRAND_IMAGE_FOLDERS

    return sorted(dict.fromkeys(BRAND_IMAGE_FOLDERS))


def host_de_imagenes():
    """El host publico del bucket, tal como lo usa el motor de fotos."""
    from generate_columbia_matrixify import DEFAULT_IMAGE_HOST

    return DEFAULT_IMAGE_HOST.rstrip("/")


def host_de_validacion():
    """El host alterno del bucket. El principal contesta 403 a consultas
    anonimas y eso NO significa que el archivo no exista."""
    from generate_columbia_matrixify import DEFAULT_IMAGE_VALIDATION_HOST

    return DEFAULT_IMAGE_VALIDATION_HOST.rstrip("/")


def nombre_de_video(modelo, color, extension=EXTENSION_VIDEO):
    """`2044361` + `6RX` -> `2044361_6RX_2.mp4`.

    El usuario nunca escribe esto. El `_2` es la posicion en la galeria, no un
    numero de version: el video va inmediatamente despues de la foto principal.
    """
    modelo = normalizar_modelo(modelo)
    color = normalizar_color(color)
    if not modelo or not color:
        return ""
    extension = texto(extension).lstrip(".").lower() or EXTENSION_VIDEO
    return f"{modelo}_{color}_{SUFIJO_VIDEO}.{extension}"


def clave_s3(marca, modelo, color, extension=EXTENSION_VIDEO):
    """`COLUMBIA/2044361_6RX_2.mp4`: la ruta dentro del bucket."""
    nombre = nombre_de_video(modelo, color, extension)
    carpeta = carpeta_de_marca(marca)
    if not nombre or not carpeta:
        return ""
    return f"{carpeta}/{nombre}"


def url_de_video(marca, modelo, color, extension=EXTENSION_VIDEO):
    """La URL publica final.

    `https://ecom-imagenes.forus-digital.xyz.peru.s3.amazonaws.com/COLUMBIA/2044361_6RX_2.mp4`
    """
    clave = clave_s3(marca, modelo, color, extension)
    if not clave:
        return ""
    carpeta, _, nombre = clave.partition("/")
    return f"{host_de_imagenes()}/{carpeta.replace(' ', '%20')}/{nombre}"


def url_de_validacion(marca, modelo, color, extension=EXTENSION_VIDEO):
    """La misma ruta en el host alterno, para comprobar que quedo subido."""
    clave = clave_s3(marca, modelo, color, extension)
    if not clave:
        return ""
    carpeta, _, nombre = clave.partition("/")
    return f"{host_de_validacion()}/{carpeta.replace(' ', '%20')}/{nombre}"


def formatear_tamano(bytes_totales):
    """Bytes a algo que se pueda leer de un vistazo."""
    try:
        cantidad = float(bytes_totales or 0)
    except (TypeError, ValueError):
        return "0 B"
    for unidad in ("B", "KB", "MB", "GB"):
        if cantidad < 1024 or unidad == "GB":
            if unidad == "B":
                return f"{int(cantidad)} B"
            return f"{cantidad:.1f} {unidad}"
        cantidad /= 1024
    return f"{cantidad:.1f} GB"


def validar_descarga(url, contenido, content_type="", extensiones=EXTENSIONES_ACEPTADAS):
    """(errores, avisos) de lo que el bucket devolvio. Nadie sube archivos.

    Se comprueba DESPUES de bajar el mp4 del bucket y ANTES de dárselo a
    Shopify. Un archivo de 1,4 GB tarda minutos en subir y recien despues
    Shopify lo marca FAILED: es el peor lugar para enterarse de un tope que se
    sabia desde el principio.

    El `content_type` es un aviso, no un error: S3 devuelve
    `application/octet-stream` para los mp4 a los que nadie les puso el tipo, y
    eso NO significa que el archivo este mal.
    """
    errores = []
    avisos = []
    direccion = texto(url)
    if not direccion:
        errores.append("No se pudo armar la dirección del video en el bucket.")
        return errores, avisos

    nombre = direccion.split("?", 1)[0].rsplit("/", 1)[-1]
    extension = nombre.rsplit(".", 1)[-1].lower() if "." in nombre else ""
    aceptadas = tuple(texto(item).lstrip(".").lower() for item in extensiones if texto(item))
    if extension not in aceptadas:
        errores.append(f"'{nombre}' no es {' ni '.join('.' + ext for ext in aceptadas)}.")

    tamano = len(contenido or b"")
    if tamano <= 0:
        errores.append("El bucket devolvió el archivo vacío.")
    elif tamano < VIDEO_MIN_BYTES:
        errores.append(f"El archivo pesa {formatear_tamano(tamano)}: no es un video.")
    elif tamano > VIDEO_MAX_BYTES:
        errores.append(
            f"El video pesa {formatear_tamano(tamano)} y Shopify acepta hasta "
            f"{formatear_tamano(VIDEO_MAX_BYTES)}."
        )
    elif tamano > VIDEO_AVISO_BYTES:
        avisos.append(
            f"El video pesa {formatear_tamano(tamano)}: la subida a Shopify y su "
            "procesamiento van a tardar."
        )

    tipo = texto(content_type).lower().split(";")[0]
    if tipo and not tipo.startswith("video/") and tipo != "application/octet-stream":
        avisos.append(f"El bucket lo entregó como '{tipo}' y no como video.")
    return errores, avisos


def validar_datos_del_producto(marca, modelo, color):
    """Errores de Marca/Modelo/Color antes de buscar nada."""
    errores = []
    if not texto(marca):
        errores.append("Falta la marca.")
    elif not carpeta_de_marca(marca):
        errores.append(f"La marca '{texto(marca)}' no tiene carpeta en el bucket.")
    if not normalizar_modelo(modelo):
        errores.append("Falta el modelo.")
    if not normalizar_color(color):
        errores.append("Falta el color.")
    return errores


# ---------------------------------------------------------------------------
# Lectura del media que devuelve Shopify
# ---------------------------------------------------------------------------

def _nodo_tipo(nodo):
    return texto((nodo or {}).get("mediaContentType")).upper()


def _nodo_id(nodo):
    return texto((nodo or {}).get("id"))


def nombre_de_archivo_de_media(nodo):
    """El nombre del archivo de un media, mire donde mire.

    Shopify no devuelve el nombre original en un campo: hay que sacarlo de la
    URL de la fuente del video, del preview o del alt. Se prueban los tres
    porque cada tipo de media rellena unos y deja otros vacios.
    """
    nodo = nodo or {}
    candidatos = []
    for fuente in (nodo.get("sources") or []):
        candidatos.append(texto((fuente or {}).get("url")))
    candidatos.append(texto(((nodo.get("preview") or {}).get("image") or {}).get("url")))
    candidatos.append(texto((nodo.get("image") or {}).get("url")))
    candidatos.append(texto(nodo.get("filename")))
    for candidato in candidatos:
        if not candidato:
            continue
        ruta = candidato.split("?", 1)[0].rstrip("/")
        nombre = ruta.rsplit("/", 1)[-1]
        if nombre:
            return nombre
    return texto(nodo.get("alt"))


def videos_del_producto(media):
    """Los media de tipo video del producto, en el orden en que vienen."""
    return [
        nodo for nodo in (media or [])
        if _nodo_tipo(nodo) in (MEDIA_VIDEO, MEDIA_VIDEO_EXTERNO)
    ]


def video_existente(media, nombre_esperado=""):
    """El video que ya tiene el producto, o None.

    Si se pasa `nombre_esperado` se prefiere el que coincide con ese nombre
    (Shopify le puede haber pegado un sufijo al subirlo), pero se devuelve
    cualquier video igual: el requerimiento es que el producto tenga UNO, no
    que tenga uno con ese nombre exacto. Nunca se crean duplicados en silencio.
    """
    encontrados = videos_del_producto(media)
    if not encontrados:
        return None
    raiz = texto(nombre_esperado).rsplit(".", 1)[0].lower()
    if raiz:
        for nodo in encontrados:
            actual = nombre_de_archivo_de_media(nodo).rsplit(".", 1)[0].lower()
            if actual == raiz or actual.startswith(raiz + "_"):
                return nodo
    return encontrados[0]


def posicion_de_media(media, media_id):
    """La posicion (1 = primera) de ese media, o 0 si no esta."""
    objetivo = texto(media_id)
    if not objetivo:
        return 0
    for indice, nodo in enumerate(media or [], start=1):
        if _nodo_id(nodo) == objetivo:
            return indice
    return 0


def plan_de_orden(media, media_id, posicion=POSICION_VIDEO):
    """Los movimientos que `productReorderMedia` necesita. Puede ser [].

    La mutacion trabaja con indices que EMPIEZAN EN 0 y los recibe como texto
    (`UnsignedInt64`): la posicion 2 que ve una persona es `newPosition: "1"`.
    Confundir las dos numeraciones deja el video tercero, que es exactamente el
    error que este modulo esta para evitar.

    Devuelve [] cuando el video ya esta donde tiene que estar: mandar un
    reordenamiento que no mueve nada gasta una llamada y un job de Shopify.
    """
    actual = posicion_de_media(media, media_id)
    if not actual:
        return []
    destino = max(1, int(posicion or POSICION_VIDEO))
    total = len(media or [])
    destino = min(destino, total)
    if actual == destino:
        return []
    return [{"id": texto(media_id), "newPosition": str(destino - 1)}]


def orden_resultante(media, movimientos):
    """El orden que quedaria tras aplicar esos movimientos.

    Sirve para mostrar el antes y el despues sin volver a preguntarle a
    Shopify, y para probar `plan_de_orden` sin tienda.
    """
    lista = list(media or [])
    for movimiento in movimientos or []:
        objetivo = texto((movimiento or {}).get("id"))
        try:
            destino = int(texto((movimiento or {}).get("newPosition")) or 0)
        except ValueError:
            continue
        indice = next(
            (i for i, nodo in enumerate(lista) if _nodo_id(nodo) == objetivo), None
        )
        if indice is None:
            continue
        nodo = lista.pop(indice)
        lista.insert(min(max(destino, 0), len(lista)), nodo)
    return lista


def resumen_de_media(media):
    """Cuantas fotos y cuantos videos tiene el producto ahora mismo."""
    lista = list(media or [])
    videos = videos_del_producto(lista)
    imagenes = [nodo for nodo in lista if _nodo_tipo(nodo) == MEDIA_IMAGEN]
    return {
        "total": len(lista),
        "imagenes": len(imagenes),
        "videos": len(videos),
        "otros": len(lista) - len(imagenes) - len(videos),
    }


def filas_de_media(media):
    """La galeria como tabla: Posicion / Tipo / Estado / Archivo."""
    filas = []
    for indice, nodo in enumerate(media or [], start=1):
        tipo = _nodo_tipo(nodo)
        filas.append(
            {
                "Posición": indice,
                "Tipo": "Video" if tipo in (MEDIA_VIDEO, MEDIA_VIDEO_EXTERNO) else "Foto",
                "Estado": texto((nodo or {}).get("status")) or "-",
                "Archivo": nombre_de_archivo_de_media(nodo),
                "Media ID": _nodo_id(nodo),
            }
        )
    return filas


def estado_de_media(nodo):
    """(estado, detalle). El detalle sale de `mediaErrors` cuando falla."""
    nodo = nodo or {}
    estado = texto(nodo.get("status")).upper() or "DESCONOCIDO"
    errores = nodo.get("mediaErrors") or []
    detalles = []
    for error in errores[:3]:
        detalle = (
            texto((error or {}).get("message"))
            or texto((error or {}).get("details"))
            or texto((error or {}).get("code"))
        )
        if detalle:
            detalles.append(detalle)
    return estado, "; ".join(detalles)


# ---------------------------------------------------------------------------
# Carga masiva
# ---------------------------------------------------------------------------
# El modo individual es la prioridad; esto deja el camino armado. Un Excel con
# Marca / Modelo / Color / Video se convierte en una lista de trabajos con las
# mismas reglas de nombre y ruta que usa el modo individual: no hay una segunda
# forma de armar el nombre.

COLUMNAS_MARCA = ("marca", "brand", "marca comercial")


def _clave_cabecera(nombre):
    limpio = texto(nombre).lower()
    for viejo, nuevo in (("á", "a"), ("é", "e"), ("í", "i"), ("ó", "o"), ("ú", "u")):
        limpio = limpio.replace(viejo, nuevo)
    return re.sub(r"[^a-z0-9]+", " ", limpio).strip()


def columna_para(cabeceras, candidatas):
    """La primera cabecera que encaja con alguno de esos nombres."""
    normalizadas = {_clave_cabecera(nombre): nombre for nombre in cabeceras or []}
    for candidata in candidatas:
        clave = _clave_cabecera(candidata)
        if clave in normalizadas:
            return normalizadas[clave]
    return None


def trabajos_desde_codigos(codigos, marcas=None, marca_por_defecto=""):
    """(trabajos, descartados) a partir de los codigos del Excel.

    Los codigos ya vienen limpios de `png_codigos_desde_excel`, que es la MISMA
    lectura que usa el mantenedor de fotos: quita vacios y repetidos y explica
    cada descarte. Aqui solo se valida que el codigo se parta en modelo y color
    (sin eso no hay direccion que armar) y se prepara el trabajo.

    La marca puede quedar VACIA a proposito: si el Excel no la trae, se resuelve
    despues con el metacampo `custom.marca` del producto, que es la fuente
    autoritativa. No se adivina aqui.
    """
    marcas = marcas or {}
    trabajos = []
    descartados = []
    for codigo in codigos or []:
        codigo = texto(codigo).upper()
        if not codigo:
            continue
        modelo = normalizar_modelo(codigo)
        color = normalizar_color(codigo) if "-" in codigo else ""
        if not modelo or not color:
            descartados.append({
                "Código Modelo Color": codigo,
                "Motivo": "No se puede separar en modelo y color; se espera MODELO-COLOR.",
            })
            continue
        marca = texto(marcas.get(codigo)) or texto(marca_por_defecto)
        trabajos.append(
            {
                "Código Modelo Color": codigo_modelo_color(modelo, color),
                "Modelo": modelo,
                "Color": color,
                "Marca": marca,
                "Nombre": nombre_de_video(modelo, color),
                "URL": url_de_video(marca, modelo, color) if marca else "",
            }
        )
    if not trabajos and not descartados:
        descartados.append({"Código Modelo Color": "", "Motivo": "El archivo no trae códigos."})
    return trabajos, descartados


def destino_del_video(marca, modelo, color):
    """Todo lo que hace falta para ir a buscar el video, en un diccionario.

    Un solo lugar arma nombre, clave y las dos direcciones. El host principal
    contesta 403 a las consultas anonimas, asi que siempre viaja tambien la
    alterna: tratar ese 403 como "no existe" fue lo que dejo 310 fotos en "Sin
    PNG" en su momento.
    """
    return {
        "Nombre": nombre_de_video(modelo, color),
        "Clave S3": clave_s3(marca, modelo, color),
        "Carpeta": carpeta_de_marca(marca),
        "URL": url_de_video(marca, modelo, color),
        "URL validación": url_de_validacion(marca, modelo, color),
    }


def resumen_del_analisis(filas):
    """Cuantos codigos hay en cada estado. Es lo que se confirma antes de cargar."""
    conteo = {}
    for fila in filas or []:
        estado = texto((fila or {}).get("Estado")) or "Sin estado"
        conteo[estado] = conteo.get(estado, 0) + 1
    return conteo


def publicables(filas):
    """Las filas que se van a intentar publicar, en el orden del Excel."""
    return [
        fila for fila in filas or []
        if texto((fila or {}).get("Estado")) in ESTADOS_PUBLICABLES
    ]
