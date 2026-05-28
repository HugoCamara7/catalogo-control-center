import json
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


def graphql_request(shop_domain, access_token, query, variables=None, api_version=DEFAULT_API_VERSION, timeout=20):
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
    try:
        with urlopen(request, timeout=timeout) as response:
            body = response.read().decode("utf-8")
    except HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise ShopifyApiError(f"Shopify respondio HTTP {exc.code}: {detail}") from exc
    except URLError as exc:
        raise ShopifyApiError(f"No se pudo conectar a Shopify: {exc.reason}") from exc

    data = json.loads(body)
    if data.get("errors"):
        raise ShopifyApiError(json.dumps(data["errors"], ensure_ascii=False))
    return data.get("data", {})


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
    siblings = node.get("siblings") or {}
    siblings_color = node.get("siblingsColor") or {}
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
        variant_records.append(
            {
                "Variant ID": clean(variant.get("legacyResourceId")),
                "Variant GID": clean(variant.get("id")),
                "Variant SKU": clean(variant.get("sku")),
                "Variant Barcode": clean(variant.get("barcode")),
                "Variant Inventory Item ID": clean(inventory_item.get("legacyResourceId")),
                "Variant Inventory Item GID": clean(inventory_item.get("id")),
                "Variant Image": clean(variant_image.get("url")),
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
        "Type": clean(node.get("productType")),
        "Status": clean(node.get("status")),
        "Mod-Col": clean(metafield.get("value")).upper(),
        "Siblings": clean(siblings.get("value")),
        "Siblings Color": clean(siblings_color.get("value")),
        "Image Src": "; ".join(image_urls),
        "Media IDs": "; ".join(media_ids),
        "Variants": variant_records,
    }


def fetch_products(config, max_products=5000):
    shop_domain, api_version, token = _client(config)
    query = """
    query ProductsForMatrixify($first: Int!, $after: String) {
      products(first: $first, after: $after) {
        pageInfo {
          hasNextPage
          endCursor
        }
        nodes {
          id
          legacyResourceId
          handle
          title
          descriptionHtml
          tags
          vendor
          productType
          status
          codigoModeloColor: metafield(namespace: "custom", key: "codigo_modelo_color") {
            value
          }
          siblings: metafield(namespace: "theme", key: "siblings") {
            value
          }
          siblingsColor: metafield(namespace: "theme", key: "siblings_color") {
            value
          }
          media(first: 20) {
            nodes {
              id
              ... on MediaImage {
                image {
                  url
                }
              }
            }
          }
          variants(first: 100) {
            nodes {
              id
              legacyResourceId
              sku
              barcode
              image {
                url
              }
              inventoryItem {
                id
                legacyResourceId
              }
            }
          }
        }
      }
    }
    """
    records = []
    after = None
    while len(records) < max_products:
        data = graphql_request(
            shop_domain,
            token,
            query,
            variables={"first": min(250, max_products - len(records)), "after": after},
            api_version=api_version,
            timeout=45,
        )
        products = data.get("products") or {}
        records.extend(_product_node_to_record(node) for node in products.get("nodes") or [])
        page_info = products.get("pageInfo") or {}
        if not page_info.get("hasNextPage"):
            break
        after = page_info.get("endCursor")
        if not after:
            break
    return records


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
