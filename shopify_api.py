import json
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
