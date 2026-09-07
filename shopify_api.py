import gzip
import json
import os
import tempfile
import uuid
import time
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen


DEFAULT_API_VERSION = "2026-04"


class ShopifyApiError(Exception):
    pass


def clean(value):
    if value is None:
        return ""
    return str(value).strip()


def normalize_shop_domain(value):
    domain = clean(value).replace("https://", "").replace("http://", "")
    domain = domain.split("/")[0].strip().lower()
    if domain and "." not in domain:
        domain = f"{domain}.myshopify.com"
    return domain


def client_credentials_token(shop_domain, client_id, client_secret, timeout=20):
    shop_domain = normalize_shop_domain(shop_domain)
    client_id = clean(client_id)
    client_secret = clean(client_secret)
    if not shop_domain:
        raise ShopifyApiError("Falta shop_domain.")
    if not client_id or not client_secret:
        raise ShopifyApiError("Falta client_id o client_secret.")

    payload = urlencode(
        {
            "grant_type": "client_credentials",
            "client_id": client_id,
            "client_secret": client_secret,
        }
    ).encode("utf-8")
    request = Request(
        f"https://{shop_domain}/admin/oauth/access_token",
        data=payload,
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        method="POST",
    )
    try:
        with urlopen(request, timeout=timeout) as response:
            data = json.loads(response.read().decode("utf-8"))
    except HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise ShopifyApiError(f"No se pudo obtener token. HTTP {exc.code}: {detail}") from exc
    except URLError as exc:
        raise ShopifyApiError(f"No se pudo conectar para obtener token: {exc.reason}") from exc

    token = clean(data.get("access_token"))
    if not token:
        raise ShopifyApiError(f"Shopify no devolvio access_token: {data}")
    return token, data


def resolve_access_token(config):
    token = clean(config.get("admin_access_token") or config.get("access_token") or config.get("token"))
    if token:
        return token, "secret"
    token, _ = client_credentials_token(
        config.get("shop_domain") or config.get("domain"),
        config.get("client_id"),
        config.get("client_secret"),
    )
    return token, "client_credentials"


# Ultimo informe de costo que devolvio Shopify. Sirve para saber si la lentitud
# viene de throttling y no de la red.
ULTIMO_COSTO_GRAPHQL = {}


def _remember_query_cost(data):
    cost = ((data or {}).get("extensions") or {}).get("cost") or {}
    if cost:
        ULTIMO_COSTO_GRAPHQL.clear()
        ULTIMO_COSTO_GRAPHQL.update(cost)


def _throttle_wait_seconds(data, attempt, default_wait=1.5):
    """Cuanto esperar cuando Shopify responde THROTTLED.

    Shopify informa cuantos puntos quedan y a que velocidad se recargan. Antes
    se dormia 1.5 segundos a ciegas: a veces de mas, y a veces de menos y se
    gastaba un reintento. Con el dato real se espera lo justo.
    """
    estado = (((data or {}).get("extensions") or {}).get("cost") or {}).get("throttleStatus") or {}
    solicitado = (((data or {}).get("extensions") or {}).get("cost") or {}).get("requestedQueryCost")
    try:
        disponible = float(estado.get("currentlyAvailable"))
        recarga = float(estado.get("restoreRate")) or 50.0
        necesario = float(solicitado) if solicitado is not None else float(estado.get("maximumAvailable") or 1000)
    except (TypeError, ValueError):
        return default_wait * attempt
    faltante = max(0.0, necesario - disponible)
    if not faltante:
        return default_wait
    return max(0.2, min(faltante / recarga + 0.2, 10.0))


def graphql_request(shop_domain, access_token, query, variables=None, api_version=DEFAULT_API_VERSION, timeout=20, max_retries=2):
    shop_domain = normalize_shop_domain(shop_domain)
    access_token = clean(access_token)
    api_version = clean(api_version) or DEFAULT_API_VERSION
    if not shop_domain:
        raise ShopifyApiError("Falta shop_domain.")
    if not access_token:
        raise ShopifyApiError("Falta Admin API access token.")

    payload = json.dumps({"query": query, "variables": variables or {}}).encode("utf-8")
    request = Request(
        f"https://{shop_domain}/admin/api/{api_version}/graphql.json",
        data=payload,
        headers={
            "Content-Type": "application/json",
            "X-Shopify-Access-Token": access_token,
        },
        method="POST",
    )
    attempts = max(1, int(max_retries or 0) + 1)
    last_error = None
    for attempt in range(1, attempts + 1):
        try:
            with urlopen(request, timeout=timeout) as response:
                body = response.read().decode("utf-8")
            data = json.loads(body)
            if data.get("errors"):
                error_message = json.dumps(data["errors"], ensure_ascii=False)
                retryable = "THROTTLED" in error_message or "throttled" in error_message.lower()
                if retryable and attempt < attempts:
                    time.sleep(_throttle_wait_seconds(data, attempt))
                    continue
                raise ShopifyApiError(error_message)
            _remember_query_cost(data)
            return data.get("data", {})
        except HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            last_error = ShopifyApiError(f"Shopify respondio HTTP {exc.code}: {detail}")
            retry_after = clean(exc.headers.get("Retry-After") if exc.headers else "")
            retryable = exc.code == 429 or 500 <= int(exc.code) <= 599
            if retryable and attempt < attempts:
                delay = float(retry_after) if retry_after.replace(".", "", 1).isdigit() else 1.5 * attempt
                time.sleep(min(delay, 10))
                continue
            raise last_error from exc
        except URLError as exc:
            last_error = ShopifyApiError(f"No se pudo conectar a Shopify: {exc.reason}")
            if attempt < attempts:
                time.sleep(1.5 * attempt)
                continue
            raise last_error from exc
    if last_error:
        raise last_error
    raise ShopifyApiError("Shopify no devolvio respuesta.")


def test_connection(config):
    shop_domain = normalize_shop_domain(config.get("shop_domain") or config.get("domain"))
    api_version = clean(config.get("api_version")) or DEFAULT_API_VERSION
    token, token_source = resolve_access_token(config)
    query = """
    query ShopifyConnectionTest {
      shop {
        name
        myshopifyDomain
        primaryDomain {
          host
          url
        }
      }
    }
    """
    data = graphql_request(shop_domain, token, query, api_version=api_version)
    shop = data.get("shop", {})
    shop["token_source"] = token_source
    return shop


def _client(config):
    shop_domain = normalize_shop_domain(config.get("shop_domain") or config.get("domain"))
    api_version = clean(config.get("api_version")) or DEFAULT_API_VERSION
    token, _ = resolve_access_token(config)
    return shop_domain, api_version, token


def _product_node_to_record(node):
    metafield = node.get("codigoModeloColor") or {}
    # `vendor` es del SITIO (rockfordpe), el mismo para todas las marcas de esa
    # tienda. La marca comercial solo esta en este metacampo.
    marca = node.get("marca") or {}
    materialidad = node.get("materialidad") or {}
    tecnologia = node.get("tecnologia") or {}
    logo = node.get("logo") or {}
    siblings = node.get("siblings") or {}
    siblings_color = node.get("siblingsColor") or {}
    custom_siblings = node.get("customSiblings") or {}
    custom_siblings_color = node.get("customSiblingsColor") or {}
    media_nodes = ((node.get("media") or {}).get("nodes")) or []
    image_urls = []
    media_ids = []
    for media in media_nodes:
        media_ids.append(clean(media.get("id")))
        image = media.get("image") or {}
        if image.get("url"):
            image_urls.append(clean(image.get("url")))
    variant_records = []
    for variant in ((node.get("variants") or {}).get("nodes")) or []:
        inventory_item = variant.get("inventoryItem") or {}
        variant_image = variant.get("image") or {}
        selected_options = variant.get("selectedOptions") or []
        option_values = {clean(option.get("name")): clean(option.get("value")) for option in selected_options}
        variant_records.append(
            {
                "Variant ID": clean(variant.get("legacyResourceId")),
                "Variant GID": clean(variant.get("id")),
                "Variant SKU": clean(variant.get("sku")),
                "Variant Barcode": clean(variant.get("barcode")),
                "Variant Inventory Item ID": clean(inventory_item.get("legacyResourceId")),
                "Variant Inventory Item GID": clean(inventory_item.get("id")),
                "Variant Image": clean(variant_image.get("url")),
                "Variant Price": clean(variant.get("price")),
                "Variant Compare At Price": clean(variant.get("compareAtPrice")),
                "Variant Inventory Qty": clean(variant.get("inventoryQuantity")),
                "Option1 Name": clean(selected_options[0].get("name")) if len(selected_options) >= 1 else "",
                "Option1 Value": clean(selected_options[0].get("value")) if len(selected_options) >= 1 else "",
                "Option2 Name": clean(selected_options[1].get("name")) if len(selected_options) >= 2 else "",
                "Option2 Value": clean(selected_options[1].get("value")) if len(selected_options) >= 2 else "",
            }
        )
    return {
        "Product ID": clean(node.get("id")),
        "Legacy ID": clean(node.get("legacyResourceId")),
        "Handle": clean(node.get("handle")),
        "Title": clean(node.get("title")),
        "Body HTML": clean(node.get("descriptionHtml")),
        "Tags": ", ".join(node.get("tags") or []),
        "Vendor": clean(node.get("vendor")),
        "Marca": clean(marca.get("value")),
        "Type": clean(node.get("productType")),
        "Status": clean(node.get("status")),
        "Online Store URL": clean(node.get("onlineStoreUrl")),
        "Published Online Store": (
            "SI"
            if node.get("publishedOnOnlineStore") is True
            else "NO"
            if node.get("publishedOnOnlineStore") is False
            else ""
        ),
        "Mod-Col": clean(metafield.get("value")).upper(),
        "Metafield: custom.materialidad [single_line_text_field]": clean(materialidad.get("value")),
        "Metafield: custom.tecnologia [list.single_line_text_field]": clean(tecnologia.get("value")),
        "Metafield: custom.logo [list.metaobject_reference]": clean(logo.get("value")),
        "Siblings": clean(siblings.get("value")),
        "Siblings Color": clean(siblings_color.get("value")),
        "Custom Siblings": clean(custom_siblings.get("value")),
        "Custom Siblings Color": clean(custom_siblings_color.get("value")),
        "Image Src": "; ".join(image_urls),
        "Media IDs": "; ".join(media_ids),
        "Variants": variant_records,
    }


# Los campos del producto, escritos UNA vez. Los usan las dos lecturas -la
# masiva y la paginada- para que no puedan separarse: si una trajera un campo
# que la otra no, el catalogo cambiaria segun por donde se leyo. Es el mismo
# criterio que las dos `normalize_size` que ya se pagan en este repositorio.
#
# `__PUBLICATION_FIELD__` se rellena solo si la tienda expone el canal Online
# Store; sin el, `Published Online Store` llega vacio y quien lee lo reporta
# como "Activo sin publicar", nunca como publicado.
CAMPOS_PRODUCTO = """
          id
          legacyResourceId
          handle
          title
          descriptionHtml
          tags
          vendor
          productType
          status
          onlineStoreUrl
          __PUBLICATION_FIELD__
          codigoModeloColor: metafield(namespace: "custom", key: "codigo_modelo_color") {
            value
          }
          marca: metafield(namespace: "custom", key: "marca") {
            value
          }
          materialidad: metafield(namespace: "custom", key: "materialidad") {
            value
          }
          tecnologia: metafield(namespace: "custom", key: "tecnologia") {
            value
          }
          logo: metafield(namespace: "custom", key: "logo") {
            value
          }
          siblings: metafield(namespace: "theme", key: "siblings") {
            value
          }
          siblingsColor: metafield(namespace: "theme", key: "siblings_color") {
            value
          }
          customSiblings: metafield(namespace: "custom", key: "siblings") {
            value
          }
          customSiblingsColor: metafield(namespace: "custom", key: "siblings_color") {
            value
          }
"""

CAMPOS_MEDIA = """
              id
              ... on MediaImage {
                image {
                  url
                }
              }
"""

CAMPOS_VARIANTE = """
              id
              legacyResourceId
              sku
              barcode
              price
              compareAtPrice
              inventoryQuantity
              selectedOptions {
                name
                value
              }
              image {
                url
              }
              inventoryItem {
                id
                legacyResourceId
              }
"""


def _publication_field(config):
    """El fragmento del canal Online Store, o vacio si la tienda no lo expone.

    Va aparte porque las dos lecturas lo necesitan y porque preguntarlo cuesta
    un viaje: si falla, se sigue sin el en vez de tumbar la lectura entera.
    """
    try:
        publication_id = online_store_publication_id(config)
    except Exception:
        publication_id = ""
    if not publication_id:
        return "", ""
    return publication_id, "publishedOnOnlineStore: publishedOnPublication(publicationId: $publicationId)"


def _avisar(progreso, mensaje):
    """Avisa por donde va la lectura. Nunca puede tumbarla."""
    if not progreso:
        return
    try:
        progreso(mensaje)
    except Exception:
        pass


def fetch_products(config, max_products=5000, progreso=None):
    """El catalogo del sitio.

    Por defecto va por **bulk operation**, que es lo que cambia el orden de
    magnitud. La lectura paginada pide 250 productos con sus 100 variantes y
    sus 10 fotos en una sola consulta, y eso a Shopify le cuesta ~430 puntos
    POR PRODUCTO: una pagina entera pasa de 100.000 y el maximo de una consulta
    son 1.000. Con eso, la unica forma de que la consulta entre es bajar
    `products_page_size` a dos o tres productos, y entonces un catalogo de
    3.000 productos son 1.000 viajes que ademas pagan espera de balde en cada
    uno -el balde se recarga a 50 puntos por segundo-. Eso es lo que se sentia
    como "no termina de leer".

    Una bulk operation no tiene limite de costo: se le entrega la consulta a
    Shopify, la corre en su lado y devuelve un JSONL con el catalogo entero.

    Si la operacion masiva no se puede usar -ya hay una corriendo para esta
    app y esta tienda, la tienda la rechaza, o el token no la permite- se cae
    a la lectura paginada de siempre, que es exactamente la de antes.
    """
    if _bulk_habilitado(config):
        try:
            return fetch_products_bulk(config, max_products=max_products, progreso=progreso)
        except ShopifyApiError as exc:
            _avisar(progreso, f"Lectura masiva no disponible ({exc}). Se sigue pagina por pagina.")
    return fetch_products_paginado(config, max_products=max_products, progreso=progreso)


def _bulk_habilitado(config):
    valor = clean((config or {}).get("bulk_products"))
    if not valor:
        return True
    return valor.lower() not in ("0", "false", "no", "off")


def fetch_products_paginado(config, max_products=5000, progreso=None):
    """La lectura pagina por pagina. Es el respaldo, no el camino normal.

    `products_page_size` existe porque el costo por pagina depende de cuantas
    variantes tenga el catalogo del sitio: si Shopify rechaza la consulta por
    costo, se baja desde Secrets.
    """
    shop_domain, api_version, token = _client(config)
    try:
        page_size = int(clean(config.get("products_page_size")) or 250)
    except (TypeError, ValueError):
        page_size = 250
    page_size = max(1, min(page_size, 250))
    try:
        variantes_por_producto = int(clean(config.get("variants_page_size")) or 100)
    except (TypeError, ValueError):
        variantes_por_producto = 100
    variantes_por_producto = max(1, min(variantes_por_producto, 250))
    publication_id, publication_field = _publication_field(config)
    publication_variable = ", $publicationId: ID!" if publication_id else ""
    query = """
    query ProductsForMatrixify($first: Int!, $after: String__PUBLICATION_VARIABLE__) {
      products(first: $first, after: $after) {
        pageInfo {
          hasNextPage
          endCursor
        }
        nodes {
__CAMPOS_PRODUCTO__
          media(first: 10) {
            nodes {
__CAMPOS_MEDIA__
            }
          }
          variants(first: __VARIANTES__) {
            nodes {
__CAMPOS_VARIANTE__
            }
          }
        }
      }
    }
    """
    query = (
        query.replace("__CAMPOS_PRODUCTO__", CAMPOS_PRODUCTO.strip("\n"))
        .replace("__CAMPOS_MEDIA__", CAMPOS_MEDIA.strip("\n"))
        .replace("__CAMPOS_VARIANTE__", CAMPOS_VARIANTE.strip("\n"))
        .replace("__VARIANTES__", str(variantes_por_producto))
        .replace("__PUBLICATION_VARIABLE__", publication_variable)
        .replace("__PUBLICATION_FIELD__", publication_field)
    )
    records = []
    after = None
    while len(records) < max_products:
        variables = {"first": min(page_size, max_products - len(records)), "after": after}
        if publication_id:
            variables["publicationId"] = publication_id
        data = graphql_request(shop_domain, token, query, variables=variables, api_version=api_version, timeout=45)
        products = data.get("products") or {}
        records.extend(_product_node_to_record(node) for node in products.get("nodes") or [])
        _avisar(progreso, f"{len(records):,} productos leídos...")
        page_info = products.get("pageInfo") or {}
        if not page_info.get("hasNextPage"):
            break
        after = page_info.get("endCursor")
        if not after:
            break
    return records


# --- Lectura masiva (bulk operation) -------------------------------------
#
# Una bulk operation NO paga costo por consulta: se le entrega la consulta a
# Shopify, la ejecuta de su lado y deja el resultado en un JSONL. Es la unica
# forma razonable de bajarse un catalogo entero; la paginada, con 100 variantes
# por producto, cuesta ~430 puntos por producto y el maximo de una consulta son
# 1.000, asi que obliga a paginas de dos o tres productos.
#
# El JSONL trae una linea por objeto. Las variantes y las fotos vienen como
# lineas aparte con `__parentId` apuntando al producto: hay que volver a
# armarlas. Se reensambla con la MISMA forma que devuelve la consulta paginada
# para poder reusar `_product_node_to_record` y que no existan dos lecturas que
# se separen.
BULK_ESPERA_INICIAL = 2.0
BULK_ESPERA_MAXIMA = 15.0
BULK_MINUTOS_MAXIMOS = 20


def _bulk_query(config):
    """La consulta que corre Shopify de su lado.

    Las bulk operation NO admiten variables ni argumentos de paginacion, asi
    que el id de la publicacion va escrito dentro de la consulta y las
    conexiones van sin `first`.
    """
    publication_id, publication_field = _publication_field(config)
    if publication_id:
        publication_field = (
            'publishedOnOnlineStore: publishedOnPublication(publicationId: "%s")' % publication_id
        )
    consulta = """
    {
      products {
        edges {
          node {
__CAMPOS_PRODUCTO__
            media {
              edges {
                node {
__CAMPOS_MEDIA__
                }
              }
            }
            variants {
              edges {
                node {
__CAMPOS_VARIANTE__
                }
              }
            }
          }
        }
      }
    }
    """
    return (
        consulta.replace("__CAMPOS_PRODUCTO__", CAMPOS_PRODUCTO.strip("\n"))
        .replace("__CAMPOS_MEDIA__", CAMPOS_MEDIA.strip("\n"))
        .replace("__CAMPOS_VARIANTE__", CAMPOS_VARIANTE.strip("\n"))
        .replace("__PUBLICATION_FIELD__", publication_field)
    )


def _bulk_lanzar(shop_domain, token, api_version, consulta):
    mutation = """
    mutation IniciarLecturaMasiva($query: String!) {
      bulkOperationRunQuery(query: $query) {
        bulkOperation {
          id
          status
        }
        userErrors {
          field
          message
        }
      }
    }
    """
    data = graphql_request(
        shop_domain, token, mutation, variables={"query": consulta},
        api_version=api_version, timeout=45,
    )
    resultado = (data or {}).get("bulkOperationRunQuery") or {}
    errores = resultado.get("userErrors") or []
    if errores:
        raise ShopifyApiError(
            "Shopify no aceptó la lectura masiva: "
            + "; ".join(clean(error.get("message")) for error in errores)
        )
    operacion = resultado.get("bulkOperation") or {}
    identificador = clean(operacion.get("id"))
    if not identificador:
        raise ShopifyApiError("Shopify no devolvió el identificador de la lectura masiva.")
    return identificador


def _bulk_estado(shop_domain, token, api_version, identificador):
    query = """
    query EstadoLecturaMasiva($id: ID!) {
      node(id: $id) {
        ... on BulkOperation {
          id
          status
          errorCode
          objectCount
          url
        }
      }
    }
    """
    data = graphql_request(
        shop_domain, token, query, variables={"id": identificador},
        api_version=api_version, timeout=45,
    )
    return (data or {}).get("node") or {}


def _bulk_esperar(shop_domain, token, api_version, identificador, progreso=None,
                  minutos_maximos=BULK_MINUTOS_MAXIMOS, dormir=time.sleep):
    """Espera a que Shopify termine y devuelve la URL del JSONL.

    La espera crece: preguntar cada dos segundos por un catalogo que tarda
    cinco minutos son 150 viajes que no aportan nada.
    """
    limite = time.time() + minutos_maximos * 60
    espera = BULK_ESPERA_INICIAL
    while True:
        estado = _bulk_estado(shop_domain, token, api_version, identificador)
        situacion = clean(estado.get("status")).upper()
        if situacion == "COMPLETED":
            url = clean(estado.get("url"))
            if not url:
                # Catalogo vacio: Shopify termina sin dejar archivo.
                return ""
            return url
        if situacion in ("FAILED", "CANCELED", "CANCELING", "EXPIRED"):
            raise ShopifyApiError(
                f"La lectura masiva terminó en {situacion or 'estado desconocido'}"
                + (f" ({clean(estado.get('errorCode'))})" if estado.get("errorCode") else "")
            )
        leidos = estado.get("objectCount")
        _avisar(progreso, f"Shopify está preparando el catálogo... {clean(leidos) or 0} objetos")
        if time.time() > limite:
            raise ShopifyApiError(
                f"La lectura masiva pasó de {minutos_maximos} minutos y se abandonó."
            )
        dormir(espera)
        espera = min(espera * 1.5, BULK_ESPERA_MAXIMA)


def _bulk_descargar(url, destino, timeout=120):
    """Baja el JSONL a disco, por trozos.

    A disco y no a memoria a proposito: el resultado de un catalogo grande son
    decenas de MB y la regla del proyecto es que ningun archivo se materialice
    entero. Lo que se guarda en memoria es solo el catalogo ya reensamblado,
    que es lo mismo que devolvia la lectura paginada.
    """
    peticion = Request(url, headers={"Accept-Encoding": "gzip"})
    try:
        with urlopen(peticion, timeout=timeout) as respuesta:
            comprimido = clean(respuesta.headers.get("Content-Encoding")).lower() == "gzip"
            with open(destino, "wb") as archivo:
                while True:
                    trozo = respuesta.read(1024 * 256)
                    if not trozo:
                        break
                    archivo.write(trozo)
    except HTTPError as exc:
        raise ShopifyApiError(f"No se pudo bajar el resultado de la lectura masiva: HTTP {exc.code}") from exc
    except URLError as exc:
        raise ShopifyApiError(f"No se pudo bajar el resultado de la lectura masiva: {exc.reason}") from exc
    return comprimido


def _bulk_abrir(ruta, comprimido):
    if comprimido:
        return gzip.open(ruta, "rt", encoding="utf-8")
    with open(ruta, "rb") as archivo:
        firma = archivo.read(2)
    if firma == b"\x1f\x8b":
        return gzip.open(ruta, "rt", encoding="utf-8")
    return open(ruta, "r", encoding="utf-8")


def _bulk_reensamblar(lineas, max_products=5000):
    """Del JSONL a la misma lista de registros que devuelve la paginada.

    Las lineas hijas traen `__parentId`. No se asume que vengan despues de su
    padre: se guardan aparte y se cuelgan al final. Los registros se van
    armando a medida que se sacan los nodos del diccionario para no tener el
    catalogo dos veces en memoria.
    """
    productos = {}
    hijos = {}
    for linea in lineas:
        linea = linea.strip()
        if not linea:
            continue
        try:
            objeto = json.loads(linea)
        except ValueError:
            continue
        padre = clean(objeto.get("__parentId"))
        identificador = clean(objeto.get("id"))
        if not padre:
            if identificador.startswith("gid://shopify/Product/"):
                objeto.setdefault("media", {"nodes": []})
                objeto.setdefault("variants", {"nodes": []})
                productos[identificador] = objeto
            continue
        objeto.pop("__parentId", None)
        clave = "variants" if identificador.startswith("gid://shopify/ProductVariant/") else "media"
        hijos.setdefault(padre, {"variants": [], "media": []})[clave].append(objeto)
    for padre, contenido in hijos.items():
        nodo = productos.get(padre)
        if nodo is None:
            continue
        nodo["variants"]["nodes"].extend(contenido["variants"])
        nodo["media"]["nodes"].extend(contenido["media"])
    hijos.clear()
    registros = []
    for identificador in list(productos.keys()):
        if len(registros) >= max_products:
            break
        registros.append(_product_node_to_record(productos.pop(identificador)))
    productos.clear()
    return registros


def fetch_products_bulk(config, max_products=5000, progreso=None):
    """El catalogo entero por bulk operation. Levanta ShopifyApiError si no se puede."""
    shop_domain, api_version, token = _client(config)
    _avisar(progreso, "Pidiendo el catálogo completo a Shopify (lectura masiva)...")
    identificador = _bulk_lanzar(shop_domain, token, api_version, _bulk_query(config))
    url = _bulk_esperar(shop_domain, token, api_version, identificador, progreso=progreso)
    if not url:
        return []
    _avisar(progreso, "Bajando el catálogo...")
    carpeta = tempfile.mkdtemp(prefix="shopify_bulk_")
    ruta = os.path.join(carpeta, "catalogo.jsonl")
    try:
        comprimido = _bulk_descargar(url, ruta)
        with _bulk_abrir(ruta, comprimido) as archivo:
            registros = _bulk_reensamblar(archivo, max_products=max_products)
    finally:
        try:
            os.remove(ruta)
        except OSError:
            pass
        try:
            os.rmdir(carpeta)
        except OSError:
            pass
    _avisar(progreso, f"{len(registros):,} productos leídos.")
    return registros


def fetch_metaobjects(config, metaobject_type, max_items=1000):
    shop_domain, api_version, token = _client(config)
    query = """
    query MetaobjectsForMatrixify($type: String!, $first: Int!, $after: String) {
      metaobjects(type: $type, first: $first, after: $after) {
        pageInfo {
          hasNextPage
          endCursor
        }
        nodes {
          id
          handle
          type
          displayName
          fields {
            key
            value
            reference {
              ... on MediaImage {
                image {
                  url
                }
              }
              ... on GenericFile {
                url
              }
            }
          }
        }
      }
    }
    """
    records = []
    after = None
    while len(records) < max_items:
        data = graphql_request(
            shop_domain,
            token,
            query,
            variables={"type": metaobject_type, "first": min(250, max_items - len(records)), "after": after},
            api_version=api_version,
            timeout=45,
        )
        metaobjects = data.get("metaobjects") or {}
        records.extend(metaobjects.get("nodes") or [])
        page_info = metaobjects.get("pageInfo") or {}
        if not page_info.get("hasNextPage"):
            break
        after = page_info.get("endCursor")
        if not after:
            break
    return records


def fetch_metaobject_definitions(config, max_items=250):
    shop_domain, api_version, token = _client(config)
    query = """
    query MetaobjectDefinitionsForMatrixify($first: Int!, $after: String) {
      metaobjectDefinitions(first: $first, after: $after) {
        pageInfo {
          hasNextPage
          endCursor
        }
        nodes {
          type
          name
        }
      }
    }
    """
    records = []
    after = None
    while len(records) < max_items:
        data = graphql_request(
            shop_domain,
            token,
            query,
            variables={"first": min(250, max_items - len(records)), "after": after},
            api_version=api_version,
            timeout=45,
        )
        definitions = data.get("metaobjectDefinitions") or {}
        records.extend(definitions.get("nodes") or [])
        page_info = definitions.get("pageInfo") or {}
        if not page_info.get("hasNextPage"):
            break
        after = page_info.get("endCursor")
        if not after:
            break
    return records


def fetch_metafield_definition(config, owner_type, namespace, key):
    shop_domain, api_version, token = _client(config)
    query = """
    query MetafieldDefinitionForMatrixify($ownerType: MetafieldOwnerType!, $namespace: String!, $key: String!) {
      metafieldDefinition(identifier: { ownerType: $ownerType, namespace: $namespace, key: $key }) {
        id
        name
        namespace
        key
        type {
          name
        }
        validations {
          name
          value
        }
      }
    }
    """
    data = graphql_request(
        shop_domain,
        token,
        query,
        {"ownerType": owner_type, "namespace": namespace, "key": key},
        api_version=api_version,
        timeout=45,
    )
    return data.get("metafieldDefinition") or {}


def fetch_metaobjects_for_definition(config, definition_id, max_items=1000):
    shop_domain, api_version, token = _client(config)
    query = """
    query MetaobjectsByDefinitionForMatrixify($id: ID!, $first: Int!, $after: String) {
      metaobjectDefinition(id: $id) {
        id
        type
        metaobjects(first: $first, after: $after) {
          pageInfo {
            hasNextPage
            endCursor
          }
          nodes {
            id
            handle
            type
            displayName
            fields {
              key
              value
              reference {
                ... on MediaImage {
                  image {
                    url
                  }
                }
                ... on GenericFile {
                  url
                }
              }
            }
          }
        }
      }
    }
    """
    records = []
    after = None
    while len(records) < max_items:
        data = graphql_request(
            shop_domain,
            token,
            query,
            {"id": definition_id, "first": min(250, max_items - len(records)), "after": after},
            api_version=api_version,
            timeout=45,
        )
        definition = data.get("metaobjectDefinition") or {}
        metaobjects = definition.get("metaobjects") or {}
        records.extend(metaobjects.get("nodes") or [])
        page_info = metaobjects.get("pageInfo") or {}
        if not page_info.get("hasNextPage"):
            break
        after = page_info.get("endCursor")
        if not after:
            break
    return records


def product_update(config, product_id, title=None, body_html=None, tags=None, vendor=None, product_type=None, status=None):
    shop_domain, api_version, token = _client(config)
    input_data = {"id": product_id}
    if title is not None:
        input_data["title"] = title
    if body_html is not None:
        input_data["descriptionHtml"] = body_html
    if tags is not None:
        input_data["tags"] = tags
    if vendor is not None:
        input_data["vendor"] = vendor
    if product_type is not None:
        input_data["productType"] = product_type
    if status is not None:
        input_data["status"] = status

    def run_product_update(input_type):
        mutation = """
    mutation ProductUpdate($input: __INPUT_TYPE__!) {
      productUpdate(input: $input) {
        product {
          id
          handle
        }
        userErrors {
          field
          message
        }
      }
    }
        """.replace("__INPUT_TYPE__", input_type)
        data = graphql_request(shop_domain, token, mutation, {"input": input_data}, api_version=api_version)
        payload = data.get("productUpdate") or {}
        errors = payload.get("userErrors") or []
        if errors:
            raise ShopifyApiError(json.dumps(errors, ensure_ascii=False))
        return payload.get("product") or {}

    try:
        return run_product_update("ProductUpdateInput")
    except ShopifyApiError as exc:
        error_text = str(exc)
        if "ProductInput" not in error_text and "variableMismatch" not in error_text:
            raise
        return run_product_update("ProductInput")


def product_create(
    config,
    title,
    handle=None,
    body_html=None,
    tags=None,
    vendor=None,
    product_type=None,
    status=None,
    option_name="Talla",
    option_values=None,
):
    shop_domain, api_version, token = _client(config)
    product = {"title": clean(title) or "Producto sin titulo"}
    if handle:
        product["handle"] = clean(handle)
    if body_html:
        product["descriptionHtml"] = clean(body_html)
    if tags is not None:
        product["tags"] = tags
    if vendor:
        product["vendor"] = clean(vendor)
    if product_type:
        product["productType"] = clean(product_type)
    if status:
        product["status"] = clean(status).upper()

    values = [clean(value) for value in option_values or [] if clean(value)]
    if values:
        product["productOptions"] = [
            {
                "name": clean(option_name) or "Talla",
                "values": [{"name": value} for value in dict.fromkeys(values)],
            }
        ]

    mutation = """
    mutation ProductCreate($product: ProductCreateInput!) {
      productCreate(product: $product) {
        product {
          id
          legacyResourceId
          handle
        }
        userErrors {
          field
          message
        }
      }
    }
    """
    data = graphql_request(shop_domain, token, mutation, {"product": product}, api_version=api_version, timeout=45)
    payload = data.get("productCreate") or {}
    errors = payload.get("userErrors") or []
    if errors:
        raise ShopifyApiError(json.dumps(errors, ensure_ascii=False))
    return payload.get("product") or {}


def metafields_set(config, metafields):
    shop_domain, api_version, token = _client(config)
    mutation = """
    mutation MetafieldsSet($metafields: [MetafieldsSetInput!]!) {
      metafieldsSet(metafields: $metafields) {
        metafields {
          id
          key
        }
        userErrors {
          field
          message
        }
      }
    }
    """
    data = graphql_request(shop_domain, token, mutation, {"metafields": metafields}, api_version=api_version)
    payload = data.get("metafieldsSet") or {}
    errors = payload.get("userErrors") or []
    if errors:
        raise ShopifyApiError(json.dumps(errors, ensure_ascii=False))
    return payload.get("metafields") or []


def fetch_publications(config, max_items=50):
    shop_domain, api_version, token = _client(config)
    query = """
    query Publications($first: Int!) {
      publications(first: $first) {
        nodes {
          id
          name
        }
      }
    }
    """
    data = graphql_request(
        shop_domain,
        token,
        query,
        {"first": max_items},
        api_version=api_version,
    )
    return ((data.get("publications") or {}).get("nodes")) or []


def online_store_publication_id(config):
    configured = clean(config.get("publication_id") or config.get("online_store_publication_id"))
    if configured:
        return configured
    publications = fetch_publications(config)
    for publication in publications:
        name = clean(publication.get("name")).lower()
        normalized = name.replace("-", " ").replace("_", " ")
        if name in ("online store", "tienda online", "canal online"):
            return clean(publication.get("id"))
        if ("online" in normalized and ("store" in normalized or "tienda" in normalized or "web" in normalized)):
            return clean(publication.get("id"))
        if ("web" in normalized and ("store" in normalized or "tienda" in normalized or "canal" in normalized)):
            return clean(publication.get("id"))
    return clean((publications[0] if publications else {}).get("id"))


def publishable_publish(config, product_id, publication_id=None, publish_date=None):
    publication_id = clean(publication_id) or online_store_publication_id(config)
    if not publication_id:
        raise ShopifyApiError("No encontre publication_id para publicar el producto.")
    shop_domain, api_version, token = _client(config)
    publication_input = {"publicationId": publication_id}
    if clean(publish_date):
        publication_input["publishDate"] = clean(publish_date)
    mutation = """
    mutation PublishProduct($id: ID!, $input: [PublicationInput!]!) {
      publishablePublish(id: $id, input: $input) {
        publishable {
          ... on Product {
            id
            handle
          }
        }
        userErrors {
          field
          message
        }
      }
    }
    """
    data = graphql_request(
        shop_domain,
        token,
        mutation,
        {"id": product_id, "input": [publication_input]},
        api_version=api_version,
        timeout=45,
    )
    payload = data.get("publishablePublish") or {}
    errors = payload.get("userErrors") or []
    if errors:
        raise ShopifyApiError(json.dumps(errors, ensure_ascii=False))
    return payload.get("publishable") or {}


def product_delete_media(config, product_id, media_ids):
    media_ids = [clean(media_id) for media_id in media_ids if clean(media_id)]
    if not media_ids:
        return []
    shop_domain, api_version, token = _client(config)
    mutation = """
    mutation ProductDeleteMedia($productId: ID!, $mediaIds: [ID!]!) {
      productDeleteMedia(productId: $productId, mediaIds: $mediaIds) {
        deletedMediaIds
        userErrors {
          field
          message
        }
      }
    }
    """
    data = graphql_request(
        shop_domain,
        token,
        mutation,
        {"productId": product_id, "mediaIds": media_ids},
        api_version=api_version,
    )
    payload = data.get("productDeleteMedia") or {}
    errors = payload.get("userErrors") or []
    if errors:
        raise ShopifyApiError(json.dumps(errors, ensure_ascii=False))
    return payload.get("deletedMediaIds") or []


def product_create_media(config, product_id, image_urls):
    urls = [clean(url) for url in image_urls if clean(url)]
    if not urls:
        return []
    shop_domain, api_version, token = _client(config)
    mutation = """
    mutation ProductCreateMedia($productId: ID!, $media: [CreateMediaInput!]!) {
      productCreateMedia(productId: $productId, media: $media) {
        media {
          id
          mediaContentType
          status
        }
        mediaUserErrors {
          field
          message
        }
      }
    }
    """
    media = [{"mediaContentType": "IMAGE", "originalSource": url} for url in urls]
    data = graphql_request(
        shop_domain,
        token,
        mutation,
        {"productId": product_id, "media": media},
        api_version=api_version,
        timeout=45,
    )
    payload = data.get("productCreateMedia") or {}
    errors = payload.get("mediaUserErrors") or []
    if errors:
        raise ShopifyApiError(json.dumps(errors, ensure_ascii=False))
    return payload.get("media") or []


def staged_upload_image(config, filename, mime_type, image_bytes):
    shop_domain, api_version, token = _client(config)
    mutation = """
    mutation StagedUploadsCreate($input: [StagedUploadInput!]!) {
      stagedUploadsCreate(input: $input) {
        stagedTargets {
          url
          resourceUrl
          parameters {
            name
            value
          }
        }
        userErrors {
          field
          message
        }
      }
    }
    """
    data = graphql_request(
        shop_domain,
        token,
        mutation,
        {
            "input": [
                {
                    "filename": clean(filename) or "product_image.jpg",
                    "httpMethod": "PUT",
                    "mimeType": clean(mime_type) or "image/jpeg",
                    "resource": "IMAGE",
                }
            ]
        },
        api_version=api_version,
        timeout=45,
    )
    payload = data.get("stagedUploadsCreate") or {}
    errors = payload.get("userErrors") or []
    if errors:
        raise ShopifyApiError(json.dumps(errors, ensure_ascii=False))
    targets = payload.get("stagedTargets") or []
    if not targets:
        raise ShopifyApiError("Shopify no devolvio staged upload target.")
    target = targets[0]
    headers = {item.get("name"): item.get("value") for item in target.get("parameters") or [] if item.get("name")}
    headers["Content-Type"] = headers.get("content_type") or clean(mime_type) or "image/jpeg"
    headers["Content-Length"] = str(len(image_bytes))
    request = Request(target.get("url"), data=image_bytes, headers=headers, method="PUT")
    try:
        with urlopen(request, timeout=60) as response:
            if response.status >= 400:
                raise ShopifyApiError(f"Staged upload respondio HTTP {response.status}.")
    except HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise ShopifyApiError(f"Staged upload respondio HTTP {exc.code}: {detail}") from exc
    except URLError as exc:
        raise ShopifyApiError(f"No se pudo subir imagen a Shopify staged upload: {exc.reason}") from exc
    return clean(target.get("resourceUrl"))


def file_create(config, original_source, alt="", content_type="IMAGE"):
    shop_domain, api_version, token = _client(config)
    mutation = """
    mutation FileCreateForMatrixify($files: [FileCreateInput!]!) {
      fileCreate(files: $files) {
        files {
          id
          fileStatus
          alt
          ... on MediaImage {
            image {
              url
            }
          }
        }
        userErrors {
          field
          message
        }
      }
    }
    """
    data = graphql_request(
        shop_domain,
        token,
        mutation,
        {"files": [{"originalSource": clean(original_source), "alt": clean(alt), "contentType": clean(content_type) or "IMAGE"}]},
        api_version=api_version,
        timeout=45,
    )
    payload = data.get("fileCreate") or {}
    errors = payload.get("userErrors") or []
    if errors:
        raise ShopifyApiError(json.dumps(errors, ensure_ascii=False))
    return payload.get("files") or []


def fetch_file_statuses(config, file_ids):
    file_ids = [clean(file_id) for file_id in file_ids if clean(file_id)]
    if not file_ids:
        return []
    shop_domain, api_version, token = _client(config)
    query = """
    query FileStatusesForMatrixify($ids: [ID!]!) {
      nodes(ids: $ids) {
        id
        ... on File {
          fileStatus
          preview {
            image {
              url
            }
          }
        }
      }
    }
    """
    data = graphql_request(shop_domain, token, query, {"ids": file_ids}, api_version=api_version, timeout=45)
    return [node for node in data.get("nodes") or [] if node]


def wait_file_statuses(config, file_ids, attempts=8, delay_seconds=3):
    statuses = []
    pending = set(file_ids)
    for attempt in range(max(1, attempts)):
        statuses = fetch_file_statuses(config, list(pending))
        pending = {
            clean(file_node.get("id"))
            for file_node in statuses
            if clean(file_node.get("id")) and clean(file_node.get("fileStatus")).upper() in ("UPLOADED", "PROCESSING")
        }
        if not pending:
            break
        if attempt < attempts - 1:
            time.sleep(delay_seconds)
    return statuses


def product_set_files(config, product_id, files):
    files = [file_input for file_input in files if file_input]
    if not files:
        return {}
    shop_domain, api_version, token = _client(config)
    mutation = """
    mutation ProductSetFilesForMatrixify($input: ProductSetInput!) {
      productSet(input: $input, synchronous: true) {
        product {
          id
        }
        userErrors {
          field
          message
        }
      }
    }
    """
    data = graphql_request(
        shop_domain,
        token,
        mutation,
        {"input": {"id": product_id, "files": files}},
        api_version=api_version,
        timeout=60,
    )
    payload = data.get("productSet") or {}
    errors = payload.get("userErrors") or []
    if errors:
        raise ShopifyApiError(json.dumps(errors, ensure_ascii=False))
    return payload.get("product") or {}


def product_variants_bulk_create(config, product_id, variants, strategy=None):
    variants = [variant for variant in variants if variant]
    if not variants:
        return []
    shop_domain, api_version, token = _client(config)
    mutation = """
    mutation ProductVariantsBulkCreate($productId: ID!, $variants: [ProductVariantsBulkInput!]!, $strategy: ProductVariantsBulkCreateStrategy) {
      productVariantsBulkCreate(productId: $productId, variants: $variants, strategy: $strategy) {
        productVariants {
          id
          legacyResourceId
          sku
          price
          compareAtPrice
          barcode
          selectedOptions {
            name
            value
          }
        }
        userErrors {
          field
          message
        }
      }
    }
    """
    data = graphql_request(
        shop_domain,
        token,
        mutation,
        {"productId": product_id, "variants": variants, "strategy": strategy},
        api_version=api_version,
        timeout=45,
    )
    payload = data.get("productVariantsBulkCreate") or {}
    errors = payload.get("userErrors") or []
    if errors:
        raise ShopifyApiError(json.dumps(errors, ensure_ascii=False))
    return payload.get("productVariants") or []


def product_variants_bulk_update(config, product_id, variants):
    variants = [variant for variant in variants if variant]
    if not variants:
        return []
    shop_domain, api_version, token = _client(config)
    mutation = """
    mutation ProductVariantsBulkUpdate($productId: ID!, $variants: [ProductVariantsBulkInput!]!) {
      productVariantsBulkUpdate(productId: $productId, variants: $variants) {
        productVariants {
          id
          legacyResourceId
          sku
          price
          compareAtPrice
          barcode
          selectedOptions {
            name
            value
          }
        }
        userErrors {
          field
          message
        }
      }
    }
    """
    data = graphql_request(
        shop_domain,
        token,
        mutation,
        {"productId": product_id, "variants": variants},
        api_version=api_version,
        timeout=45,
    )
    payload = data.get("productVariantsBulkUpdate") or {}
    errors = payload.get("userErrors") or []
    if errors:
        raise ShopifyApiError(json.dumps(errors, ensure_ascii=False))
    return payload.get("productVariants") or []


def inventory_item_update(config, inventory_item_id, input_data):
    inventory_item_id = clean(inventory_item_id)
    input_data = dict(input_data or {})
    if not inventory_item_id or not input_data:
        return {}
    shop_domain, api_version, token = _client(config)
    mutation = """
    mutation InventoryItemUpdate($id: ID!, $input: InventoryItemInput!) {
      inventoryItemUpdate(id: $id, input: $input) {
        inventoryItem {
          id
          legacyResourceId
          sku
          tracked
        }
        userErrors {
          field
          message
        }
      }
    }
    """
    data = graphql_request(
        shop_domain,
        token,
        mutation,
        {"id": inventory_item_id, "input": input_data},
        api_version=api_version,
        timeout=45,
    )
    payload = data.get("inventoryItemUpdate") or {}
    errors = payload.get("userErrors") or []
    if errors:
        raise ShopifyApiError(json.dumps(errors, ensure_ascii=False))
    return payload.get("inventoryItem") or {}


def fetch_locations(config):
    shop_domain, api_version, token = _client(config)
    query = """
    query LocationsForInventoryActivation($first: Int!, $after: String) {
      locations(first: $first, after: $after) {
        pageInfo {
          hasNextPage
          endCursor
        }
        nodes {
          id
          legacyResourceId
          name
          isActive
        }
      }
    }
    """
    locations = []
    after = None
    while True:
        data = graphql_request(
            shop_domain,
            token,
            query,
            {"first": 250, "after": after},
            api_version=api_version,
            timeout=45,
        )
        connection = data.get("locations") or {}
        for node in connection.get("nodes") or []:
            if node.get("isActive") is False:
                continue
            locations.append(
                {
                    "id": clean(node.get("id")),
                    "legacyResourceId": clean(node.get("legacyResourceId")),
                    "name": clean(node.get("name")),
                    "isActive": bool(node.get("isActive", True)),
                }
            )
        page_info = connection.get("pageInfo") or {}
        if not page_info.get("hasNextPage"):
            break
        after = page_info.get("endCursor")
    return locations


def inventory_item_active_locations(config, inventory_item_id):
    inventory_item_id = clean(inventory_item_id)
    if not inventory_item_id:
        return []
    shop_domain, api_version, token = _client(config)
    query = """
    query InventoryItemActiveLocations($id: ID!, $first: Int!, $after: String) {
      inventoryItem(id: $id) {
        id
        sku
        inventoryLevels(first: $first, after: $after) {
          pageInfo {
            hasNextPage
            endCursor
          }
          nodes {
            id
            location {
              id
              legacyResourceId
              name
            }
          }
        }
      }
    }
    """
    locations = []
    after = None
    while True:
        data = graphql_request(
            shop_domain,
            token,
            query,
            {"id": inventory_item_id, "first": 250, "after": after},
            api_version=api_version,
            timeout=45,
            max_retries=3,
        )
        item = data.get("inventoryItem") or {}
        connection = item.get("inventoryLevels") or {}
        for node in connection.get("nodes") or []:
            location = node.get("location") or {}
            if clean(location.get("id")):
                locations.append(
                    {
                        "id": clean(location.get("id")),
                        "legacyResourceId": clean(location.get("legacyResourceId")),
                        "name": clean(location.get("name")),
                    }
                )
        page_info = connection.get("pageInfo") or {}
        if not page_info.get("hasNextPage"):
            break
        after = page_info.get("endCursor")
    return locations


def inventory_bulk_activate(config, inventory_item_id, location_ids):
    """Activa un inventory item en varias sucursales con una sola llamada.

    Antes se hacia una mutacion por cada par (variante, sucursal). Con 10 tallas
    y 8 sucursales eso eran 80 llamadas por producto; asi son 10. Shopify expone
    inventoryBulkToggleActivation justamente para esto.

    Devuelve la lista de mensajes de error que no sean "ya estaba activo".
    """
    inventory_item_id = clean(inventory_item_id)
    location_ids = [clean(value) for value in (location_ids or []) if clean(value)]
    if not inventory_item_id or not location_ids:
        return []
    shop_domain, api_version, token = _client(config)
    mutation = """
    mutation InventoryBulkActivateForMatrixify($inventoryItemId: ID!, $updates: [InventoryBulkToggleActivationInput!]!) {
      inventoryBulkToggleActivation(inventoryItemId: $inventoryItemId, inventoryItemUpdates: $updates) {
        inventoryItem {
          id
        }
        userErrors {
          field
          message
        }
      }
    }
    """
    variables = {
        "inventoryItemId": inventory_item_id,
        "updates": [{"locationId": location_id, "activate": True} for location_id in location_ids],
    }
    try:
        data = graphql_request(shop_domain, token, mutation, variables, api_version=api_version, timeout=45)
    except ShopifyApiError as exc:
        message = str(exc)
        if "ACCESS_DENIED" in message or "Access denied" in message:
            raise ShopifyApiError(
                "Shopify nego activar inventario. El token necesita permiso de escritura de inventario "
                "(write_inventory / Inventory management). Actualiza los permisos del token o crea un token nuevo con ese scope."
            ) from exc
        raise
    payload = data.get("inventoryBulkToggleActivation") or {}
    errores = []
    for error in payload.get("userErrors") or []:
        texto = clean(error.get("message"))
        if texto and "already" not in texto.lower() and "ya " not in texto.lower():
            errores.append(texto)
    return errores


def inventory_activate(config, inventory_item_id, location_id, available=None):
    inventory_item_id = clean(inventory_item_id)
    location_id = clean(location_id)
    if not inventory_item_id or not location_id:
        return {}
    variables = {"inventoryItemId": inventory_item_id, "locationId": location_id}
    variables["idempotencyKey"] = str(
        uuid.uuid5(uuid.NAMESPACE_URL, f"matrixify-inventory-activate:{inventory_item_id}:{location_id}:{available}")
    )
    available_line = ""
    if available is not None:
        variables["available"] = int(available)
        available_line = ", available: $available"
    shop_domain, api_version, token = _client(config)
    mutation = f"""
    mutation InventoryActivateForMatrixify($inventoryItemId: ID!, $locationId: ID!, $idempotencyKey: String!{', $available: Int' if available is not None else ''}) {{
      inventoryActivate(inventoryItemId: $inventoryItemId, locationId: $locationId{available_line}) @idempotent(key: $idempotencyKey) {{
        inventoryLevel {{
          id
          location {{
            id
            name
          }}
          item {{
            id
            sku
          }}
        }}
        userErrors {{
          field
          message
        }}
      }}
    }}
    """
    try:
        data = graphql_request(
            shop_domain,
            token,
            mutation,
            variables,
            api_version=api_version,
            timeout=45,
        )
    except ShopifyApiError as exc:
        message = str(exc)
        if "ACCESS_DENIED" in message or "Access denied" in message:
            raise ShopifyApiError(
                "Shopify nego activar inventario. El token necesita permiso de escritura de inventario "
                "(write_inventory / Inventory management). Actualiza los permisos del token o crea un token nuevo con ese scope."
            ) from exc
        raise
    payload = data.get("inventoryActivate") or {}
    errors = payload.get("userErrors") or []
    if errors:
        message = json.dumps(errors, ensure_ascii=False)
        if "already" not in message.lower() and "ya" not in message.lower():
            raise ShopifyApiError(message)
    return payload.get("inventoryLevel") or {}


def fetch_product_id_by_handle(config, handle):
    """ID del producto a partir de su handle. Devuelve "" si no existe.

    Se usa para enlazar productos relacionados (siblings): el metacampo pide
    `gid://shopify/Product/...` y el generador solo conoce el handle. Va por
    `products(query:)` y no por `productByHandle`, que esta deprecado.
    """
    shop_domain, api_version, token = _client(config)
    handle = clean(handle)
    if not handle:
        return ""
    query = """
    query ProductIdByHandleForMatrixify($query: String!) {
      products(first: 1, query: $query) {
        nodes {
          id
          handle
        }
      }
    }
    """
    data = graphql_request(
        shop_domain,
        token,
        query,
        {"query": f"handle:{handle}"},
        api_version=api_version,
    )
    for node in (data.get("products") or {}).get("nodes") or []:
        if clean(node.get("handle")).lower() == handle.lower():
            return clean(node.get("id"))
    return ""


def fetch_product_options_and_variants(config, product_id):
    shop_domain, api_version, token = _client(config)
    query = """
    query ProductOptionsAndVariantsForMatrixify($id: ID!) {
      product(id: $id) {
        id
        options {
          id
          name
          position
          values
          optionValues {
            id
            name
            hasVariants
          }
        }
        variants(first: 250) {
          nodes {
            id
            legacyResourceId
            sku
            barcode
            price
            compareAtPrice
            inventoryItem {
              id
              legacyResourceId
              sku
              tracked
              inventoryLevels(first: 50) {
                nodes {
                  location {
                    id
                    legacyResourceId
                    name
                  }
                }
              }
            }
            selectedOptions {
              name
              value
            }
          }
        }
      }
    }
    """
    data = graphql_request(
        shop_domain,
        token,
        query,
        {"id": product_id},
        api_version=api_version,
        timeout=45,
    )
    return data.get("product") or {}


def product_options_reorder(config, product_id, options):
    options = [option for option in options if option]
    if not options:
        return {}
    shop_domain, api_version, token = _client(config)
    mutation = """
    mutation ProductOptionsReorder($productId: ID!, $options: [OptionReorderInput!]!) {
      productOptionsReorder(productId: $productId, options: $options) {
        product {
          id
        }
        userErrors {
          field
          message
          code
        }
      }
    }
    """
    data = graphql_request(
        shop_domain,
        token,
        mutation,
        {"productId": product_id, "options": options},
        api_version=api_version,
        timeout=45,
    )
    payload = data.get("productOptionsReorder") or {}
    errors = payload.get("userErrors") or []
    if errors:
        raise ShopifyApiError(json.dumps(errors, ensure_ascii=False))
    return payload.get("product") or {}


def product_variants_bulk_reorder(config, product_id, positions):
    positions = [position for position in positions if position]
    if not positions:
        return {}
    shop_domain, api_version, token = _client(config)
    mutation = """
    mutation ProductVariantsBulkReorder($productId: ID!, $positions: [ProductVariantPositionInput!]!) {
      productVariantsBulkReorder(productId: $productId, positions: $positions) {
        product {
          id
        }
        userErrors {
          field
          message
        }
      }
    }
    """
    data = graphql_request(
        shop_domain,
        token,
        mutation,
        {"productId": product_id, "positions": positions},
        api_version=api_version,
        timeout=45,
    )
    payload = data.get("productVariantsBulkReorder") or {}
    errors = payload.get("userErrors") or []
    if errors:
        raise ShopifyApiError(json.dumps(errors, ensure_ascii=False))
    return payload.get("product") or {}


def product_option_update(config, product_id, option_id, values_to_update):
    """Renombra valores de una opcion de producto (por ejemplo Talla).

    Se renombra el VALOR de la opcion, no la opcion de cada variante: un solo
    cambio alcanza a todas las variantes que lo usan. Renombrar variante por
    variante con `productVariantsBulkUpdate` dejaria dos variantes con el mismo
    valor a medio camino, y Shopify rechaza el duplicado.

    `variantStrategy` se queda en el valor por defecto (LEAVE_AS_IS): esto
    cambia la etiqueta, no crea ni borra variantes. El SKU, el precio y el
    inventario no se tocan.
    """
    values_to_update = [
        {"id": clean(value.get("id")), "name": clean(value.get("name"))}
        for value in values_to_update or []
        if clean(value.get("id")) and clean(value.get("name"))
    ]
    if not values_to_update:
        return {}
    shop_domain, api_version, token = _client(config)
    mutation = """
    mutation ProductOptionUpdateForSizes($productId: ID!, $option: OptionUpdateInput!, $optionValuesToUpdate: [OptionValueUpdateInput!]) {
      productOptionUpdate(productId: $productId, option: $option, optionValuesToUpdate: $optionValuesToUpdate) {
        product {
          id
        }
        userErrors {
          field
          message
          code
        }
      }
    }
    """
    data = graphql_request(
        shop_domain,
        token,
        mutation,
        {
            "productId": product_id,
            "option": {"id": clean(option_id)},
            "optionValuesToUpdate": values_to_update,
        },
        api_version=api_version,
        timeout=45,
    )
    payload = data.get("productOptionUpdate") or {}
    errors = payload.get("userErrors") or []
    if errors:
        raise ShopifyApiError(json.dumps(errors, ensure_ascii=False))
    return payload.get("product") or {}


def fetch_media_statuses(config, media_ids):
    media_ids = [clean(media_id) for media_id in media_ids if clean(media_id)]
    if not media_ids:
        return []
    shop_domain, api_version, token = _client(config)
    query = """
    query MediaStatusesForMatrixify($ids: [ID!]!) {
      nodes(ids: $ids) {
        id
        ... on MediaImage {
          status
          mediaErrors {
            code
            details
            message
          }
        }
      }
    }
    """
    data = graphql_request(
        shop_domain,
        token,
        query,
        {"ids": media_ids},
        api_version=api_version,
        timeout=45,
    )
    return [node for node in data.get("nodes") or [] if node]


def wait_media_statuses(config, media_ids, attempts=6, delay_seconds=3):
    statuses = []
    pending = set(media_ids)
    for attempt in range(max(1, attempts)):
        statuses = fetch_media_statuses(config, list(pending))
        pending = {
            clean(media.get("id"))
            for media in statuses
            if clean(media.get("id")) and clean(media.get("status")).upper() in ("UPLOADED", "PROCESSING")
        }
        if not pending:
            break
        if attempt < attempts - 1:
            time.sleep(delay_seconds)
    return statuses


# ===========================================================================
# Media de VIDEO en el producto
# ===========================================================================
# Un video de producto NO se resuelve como una foto. Con las fotos alcanza con
# pasarle a Shopify la URL publica del bucket y el la descarga sola. Con los
# videos eso NO funciona: `originalSource` de un media VIDEO solo acepta el
# `resourceUrl` de un staged upload. Por eso hay tres viajes obligatorios:
#
#   1. stagedUploadsCreate(resource: VIDEO)  -> destino temporal
#   2. POST multipart del archivo a ese destino
#   3. productCreateMedia(mediaContentType: VIDEO, originalSource: resourceUrl)
#
# Y despues, como el media SIEMPRE se agrega al final, un cuarto viaje con
# productReorderMedia para dejarlo en la posicion que toca.

VIDEO_MIME_POR_DEFECTO = "video/mp4"


def _multipart_body(campos, nombre_archivo, contenido, content_type):
    """Arma un cuerpo multipart/form-data a mano.

    Sin `requests` en el proyecto, y `urllib` no trae codificador multipart. El
    orden importa: el destino de staged upload (Google Cloud Storage) exige que
    el campo `file` vaya el ULTIMO, despues de todos los parametros firmados.
    """
    frontera = f"----shopifyvideo{uuid.uuid4().hex}"
    separador = f"--{frontera}".encode("utf-8")
    partes = []
    for nombre, valor in campos:
        partes.append(separador)
        partes.append(f'Content-Disposition: form-data; name="{nombre}"'.encode("utf-8"))
        partes.append(b"")
        partes.append(clean(valor).encode("utf-8"))
    partes.append(separador)
    partes.append(
        f'Content-Disposition: form-data; name="file"; filename="{nombre_archivo}"'.encode("utf-8")
    )
    partes.append(f"Content-Type: {content_type}".encode("utf-8"))
    partes.append(b"")
    cuerpo = b"\r\n".join(partes) + b"\r\n" + contenido + b"\r\n" + f"--{frontera}--\r\n".encode("utf-8")
    return cuerpo, f"multipart/form-data; boundary={frontera}"


def staged_upload_video(config, filename, mime_type, video_bytes, timeout=600):
    """Sube el archivo a un destino temporal de Shopify y devuelve su resourceUrl.

    Diferencias con `staged_upload_image`, que son las que hacen que no se pueda
    reutilizar aquella:

    - `resource: VIDEO` en vez de IMAGE.
    - `fileSize` es OBLIGATORIO para VIDEO; sin el, la mutacion falla.
    - `httpMethod: POST` y multipart, no PUT: el destino que devuelve Shopify
      para video es una politica firmada de Google Cloud Storage.
    """
    shop_domain, api_version, token = _client(config)
    contenido = video_bytes or b""
    if not contenido:
        raise ShopifyApiError("El archivo de video llego vacio.")
    filename = clean(filename) or "product_video.mp4"
    mime_type = clean(mime_type) or VIDEO_MIME_POR_DEFECTO
    mutation = """
    mutation StagedUploadsCreateVideo($input: [StagedUploadInput!]!) {
      stagedUploadsCreate(input: $input) {
        stagedTargets {
          url
          resourceUrl
          parameters {
            name
            value
          }
        }
        userErrors {
          field
          message
        }
      }
    }
    """
    data = graphql_request(
        shop_domain,
        token,
        mutation,
        {
            "input": [
                {
                    "filename": filename,
                    "mimeType": mime_type,
                    "resource": "VIDEO",
                    "fileSize": str(len(contenido)),
                    "httpMethod": "POST",
                }
            ]
        },
        api_version=api_version,
        timeout=60,
    )
    payload = data.get("stagedUploadsCreate") or {}
    errors = payload.get("userErrors") or []
    if errors:
        raise ShopifyApiError(json.dumps(errors, ensure_ascii=False))
    targets = payload.get("stagedTargets") or []
    if not targets:
        raise ShopifyApiError("Shopify no devolvio destino de subida para el video.")
    target = targets[0]
    destino = clean(target.get("url"))
    if not destino:
        raise ShopifyApiError("El destino de subida de video llego sin URL.")

    campos = [
        (clean(item.get("name")), item.get("value"))
        for item in target.get("parameters") or []
        if clean(item.get("name"))
    ]
    cuerpo, content_type = _multipart_body(campos, filename, contenido, mime_type)
    request = Request(
        destino,
        data=cuerpo,
        headers={"Content-Type": content_type, "Content-Length": str(len(cuerpo))},
        method="POST",
    )
    try:
        with urlopen(request, timeout=timeout) as response:
            if response.status >= 400:
                raise ShopifyApiError(f"La subida del video respondio HTTP {response.status}.")
    except HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")[:400]
        raise ShopifyApiError(f"La subida del video respondio HTTP {exc.code}: {detail}") from exc
    except URLError as exc:
        raise ShopifyApiError(f"No se pudo subir el video a Shopify: {exc.reason}") from exc
    return clean(target.get("resourceUrl"))


def product_create_video_media(config, product_id, resource_url, alt="", filename=""):
    """Asocia el video al PRODUCTO, no a los archivos de la tienda.

    `fileCreate` deja el mp4 en Contenido > Archivos y ahi se queda: no aparece
    en la galeria del producto. Lo que lo publica en la ficha es este
    `productCreateMedia` con `mediaContentType: VIDEO`.

    Devuelve los nodos de media creados. El procesamiento es ASINCRONO: salen
    en UPLOADED o PROCESSING y hay que esperarlos con `wait_video_media_ready`.
    """
    resource_url = clean(resource_url)
    if not resource_url:
        raise ShopifyApiError("Falta el origen del video (resourceUrl del staged upload).")
    shop_domain, api_version, token = _client(config)
    mutation = """
    mutation ProductCreateVideoMedia($productId: ID!, $media: [CreateMediaInput!]!) {
      productCreateMedia(productId: $productId, media: $media) {
        media {
          id
          mediaContentType
          status
          alt
          ... on Video {
            filename
            originalSource {
              url
            }
            sources {
              url
              format
              mimeType
            }
          }
          preview {
            image {
              url
            }
          }
          mediaErrors {
            code
            details
            message
          }
        }
        mediaUserErrors {
          field
          message
        }
      }
    }
    """
    media_input = [
        {
            "mediaContentType": "VIDEO",
            "originalSource": resource_url,
            "alt": clean(alt) or clean(filename),
        }
    ]
    data = graphql_request(
        shop_domain,
        token,
        mutation,
        {"productId": clean(product_id), "media": media_input},
        api_version=api_version,
        timeout=60,
    )
    payload = data.get("productCreateMedia") or {}
    errors = payload.get("mediaUserErrors") or []
    if errors:
        raise ShopifyApiError(json.dumps(errors, ensure_ascii=False))
    return payload.get("media") or []


def fetch_product_media(config, product_id, first=50):
    """La galeria completa del producto, EN ORDEN.

    El orden que devuelve Shopify es el orden real de la ficha, y es lo unico
    con lo que se puede saber en que posicion quedo el video. Trae fotos y
    videos juntos porque la posicion se cuenta sobre la galeria entera: mirar
    solo los videos daria siempre "posicion 1".
    """
    shop_domain, api_version, token = _client(config)
    query = """
    query ProductMediaForVideos($id: ID!, $first: Int!) {
      product(id: $id) {
        id
        title
        handle
        status
        onlineStoreUrl
        codigoModeloColor: metafield(namespace: "custom", key: "codigo_modelo_color") {
          value
        }
        marca: metafield(namespace: "custom", key: "marca") {
          value
        }
        media(first: $first) {
          nodes {
            id
            mediaContentType
            status
            alt
            preview {
              image {
                url
              }
            }
            mediaErrors {
              code
              details
              message
            }
            ... on MediaImage {
              image {
                url
              }
            }
            ... on Video {
              filename
              duration
              originalSource {
                url
              }
              sources {
                url
                format
                mimeType
              }
            }
          }
        }
      }
    }
    """
    data = graphql_request(
        shop_domain,
        token,
        query,
        {"id": clean(product_id), "first": max(1, min(int(first or 50), 250))},
        api_version=api_version,
        timeout=45,
    )
    product = data.get("product") or {}
    if not product:
        raise ShopifyApiError(f"Shopify no devolvio el producto {clean(product_id)}.")
    media = ((product.get("media") or {}).get("nodes")) or []
    return {
        "id": clean(product.get("id")),
        "title": clean(product.get("title")),
        "handle": clean(product.get("handle")),
        "status": clean(product.get("status")),
        "onlineStoreUrl": clean(product.get("onlineStoreUrl")),
        "modCol": clean((product.get("codigoModeloColor") or {}).get("value")).upper(),
        "marca": clean((product.get("marca") or {}).get("value")),
        "media": [node for node in media if node],
    }


def product_reorder_media(config, product_id, moves):
    """Mueve media dentro de la galeria. `newPosition` empieza en 0.

    Es el paso que hace que el video quede SEGUNDO: `productCreateMedia`
    siempre lo agrega al final y no acepta posicion. La mutacion devuelve un
    `job` porque el reordenamiento tambien es asincrono.
    """
    moves = [
        {"id": clean(move.get("id")), "newPosition": clean(move.get("newPosition"))}
        for move in moves or []
        if clean((move or {}).get("id"))
    ]
    if not moves:
        return {}
    shop_domain, api_version, token = _client(config)
    mutation = """
    mutation ProductReorderMediaForVideos($id: ID!, $moves: [MoveInput!]!) {
      productReorderMedia(id: $id, moves: $moves) {
        job {
          id
          done
        }
        mediaUserErrors {
          field
          message
        }
      }
    }
    """
    data = graphql_request(
        shop_domain,
        token,
        mutation,
        {"id": clean(product_id), "moves": moves},
        api_version=api_version,
        timeout=45,
    )
    payload = data.get("productReorderMedia") or {}
    errors = payload.get("mediaUserErrors") or []
    if errors:
        raise ShopifyApiError(json.dumps(errors, ensure_ascii=False))
    return payload.get("job") or {}


def fetch_video_media_statuses(config, media_ids):
    """Estado de esos media, sirvan para foto o para video.

    `fetch_media_statuses` solo abre el fragmento `... on MediaImage`: con un
    video devuelve el nodo sin `status` y la espera termina creyendo que ya
    esta listo. Este pide los dos fragmentos.
    """
    media_ids = [clean(media_id) for media_id in media_ids if clean(media_id)]
    if not media_ids:
        return []
    shop_domain, api_version, token = _client(config)
    query = """
    query VideoMediaStatuses($ids: [ID!]!) {
      nodes(ids: $ids) {
        id
        ... on Media {
          mediaContentType
          status
          alt
          preview {
            image {
              url
            }
          }
          mediaErrors {
            code
            details
            message
          }
        }
        ... on Video {
          filename
          duration
          sources {
            url
            format
            mimeType
          }
        }
      }
    }
    """
    data = graphql_request(shop_domain, token, query, {"ids": media_ids}, api_version=api_version, timeout=45)
    return [node for node in data.get("nodes") or [] if node]


def wait_video_media_ready(config, media_ids, attempts=20, delay_seconds=6):
    """Espera a que Shopify termine de procesar el video.

    Un mp4 de producto tarda decenas de segundos, a veces minutos: los 6x3s de
    `wait_media_statuses` (pensados para fotos) devuelven PROCESSING casi
    siempre y la pantalla diria "no se pudo" con un video que estaba bien.
    """
    statuses = []
    pending = [clean(media_id) for media_id in media_ids if clean(media_id)]
    for attempt in range(max(1, attempts)):
        statuses = fetch_video_media_statuses(config, pending)
        pending = [
            clean(node.get("id"))
            for node in statuses
            if clean(node.get("id")) and clean(node.get("status")).upper() in ("UPLOADED", "PROCESSING")
        ]
        if not pending:
            break
        if attempt < attempts - 1:
            time.sleep(delay_seconds)
    return statuses


def search_products(config, search_query, first=20):
    """Busqueda dirigida de productos, sin traer el catalogo entero.

    Encontrar un producto para subirle un video no puede costar las 40 paginas
    de `fetch_products`: el usuario espera minutos por un dato que Shopify
    resuelve en un viaje. Devuelve lo minimo para identificarlo y decidir.
    """
    search_query = clean(search_query)
    if not search_query:
        return []
    shop_domain, api_version, token = _client(config)
    query = """
    query SearchProductsForVideos($first: Int!, $query: String!) {
      products(first: $first, query: $query) {
        nodes {
          id
          legacyResourceId
          handle
          title
          status
          vendor
          onlineStoreUrl
          codigoModeloColor: metafield(namespace: "custom", key: "codigo_modelo_color") {
            value
          }
          marca: metafield(namespace: "custom", key: "marca") {
            value
          }
          media(first: 1) {
            nodes {
              id
            }
          }
        }
      }
    }
    """
    data = graphql_request(
        shop_domain,
        token,
        query,
        {"first": max(1, min(int(first or 20), 100)), "query": search_query},
        api_version=api_version,
        timeout=45,
    )
    nodes = ((data.get("products") or {}).get("nodes")) or []
    return [
        {
            "Product ID": clean(node.get("id")),
            "Legacy ID": clean(node.get("legacyResourceId")),
            "Handle": clean(node.get("handle")),
            "Title": clean(node.get("title")),
            "Status": clean(node.get("status")),
            "Vendor": clean(node.get("vendor")),
            "Online Store URL": clean(node.get("onlineStoreUrl")),
            "Mod-Col": clean((node.get("codigoModeloColor") or {}).get("value")).upper(),
            "Marca": clean((node.get("marca") or {}).get("value")),
        }
        for node in nodes
        if node
    ]
