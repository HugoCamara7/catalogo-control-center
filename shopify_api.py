import json
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
                    time.sleep(1.5 * attempt)
                    continue
                raise ShopifyApiError(error_message)
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
        "Type": clean(node.get("productType")),
        "Status": clean(node.get("status")),
        "Online Store URL": clean(node.get("onlineStoreUrl")),
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
          onlineStoreUrl
          codigoModeloColor: metafield(namespace: "custom", key: "codigo_modelo_color") {
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
        if name in ("online store", "tienda online", "canal online"):
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
