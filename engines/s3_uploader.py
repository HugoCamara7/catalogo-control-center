# -*- coding: utf-8 -*-
"""Subida de archivos al bucket de imagenes. Sin Streamlit.

Que habia antes
---------------
NADA. La app LEE del bucket desde el primer dia (`image_candidates` arma las
URLs y Shopify se las descarga), pero **nunca escribio en el**: no hay boto3 en
`requirements.txt` ni credenciales de AWS en Secrets. Las fotos las sube otra
persona por fuera.

El Mantenedor de Videos es la primera pantalla que necesita escribir, asi que
la seccion `[s3]` de Secrets es nueva. Sin ella este modulo no inventa nada:
dice con todas las letras que falta la configuracion, y la pantalla decide. El
video se puede publicar igual, porque quien sirve el archivo en la web es el
CDN de Shopify, no el bucket; el bucket es el respaldo con el nombre canonico.

Configuracion (Secrets)
-----------------------
    [s3]
    bucket = "ecom-imagenes.forus-digital.xyz.peru"
    region = "us-east-1"
    aws_access_key_id = "..."
    aws_secret_access_key = "..."
    # opcional
    # aws_session_token = "..."
    # endpoint_url = "..."
    # acl = "public-read"

Si el contenedor ya trae credenciales por rol (variables de entorno, perfil de
instancia), basta con `bucket`: boto3 las resuelve solo.
"""

# El bucket que ya usa la app para leer. Se deja como valor por defecto para
# que la seccion [s3] pueda traer solo las credenciales.
BUCKET_POR_DEFECTO = "ecom-imagenes.forus-digital.xyz.peru"
REGION_POR_DEFECTO = "us-east-1"


class S3NoConfigurado(Exception):
    """Falta la seccion [s3] en Secrets, o falta boto3."""


class S3Error(Exception):
    """El bucket rechazo la escritura."""


def _texto(valor):
    return "" if valor is None else str(valor).strip()


def configuracion_s3(secrets_s3=None):
    """Normaliza la seccion [s3] de Secrets. Nunca lanza."""
    datos = dict(secrets_s3 or {})
    return {
        "bucket": _texto(datos.get("bucket")) or BUCKET_POR_DEFECTO,
        "region": _texto(datos.get("region") or datos.get("region_name")) or REGION_POR_DEFECTO,
        "aws_access_key_id": _texto(datos.get("aws_access_key_id") or datos.get("access_key_id")),
        "aws_secret_access_key": _texto(
            datos.get("aws_secret_access_key") or datos.get("secret_access_key")
        ),
        "aws_session_token": _texto(datos.get("aws_session_token") or datos.get("session_token")),
        "endpoint_url": _texto(datos.get("endpoint_url")),
        "acl": _texto(datos.get("acl")),
    }


def s3_esta_configurado(config):
    """True si hay con que escribir.

    Basta el bucket cuando el entorno ya resuelve las credenciales por rol; con
    llaves explicitas hacen falta las dos.
    """
    config = config or {}
    if not _texto(config.get("bucket")):
        return False
    llave = _texto(config.get("aws_access_key_id"))
    secreto = _texto(config.get("aws_secret_access_key"))
    if llave or secreto:
        return bool(llave and secreto)
    return _credenciales_del_entorno()


def _credenciales_del_entorno():
    """True si boto3 encuentra credenciales por su cuenta (rol, perfil, env)."""
    try:
        import boto3
    except ImportError:
        return False
    try:
        return boto3.Session().get_credentials() is not None
    except Exception:
        return False


def _cliente(config):
    try:
        import boto3
    except ImportError as exc:  # pragma: no cover - depende del entorno
        raise S3NoConfigurado(
            "Falta la librería boto3. Agrégala a requirements.txt y vuelve a desplegar."
        ) from exc

    argumentos = {"region_name": _texto(config.get("region")) or REGION_POR_DEFECTO}
    if _texto(config.get("aws_access_key_id")) and _texto(config.get("aws_secret_access_key")):
        argumentos["aws_access_key_id"] = _texto(config["aws_access_key_id"])
        argumentos["aws_secret_access_key"] = _texto(config["aws_secret_access_key"])
        if _texto(config.get("aws_session_token")):
            argumentos["aws_session_token"] = _texto(config["aws_session_token"])
    if _texto(config.get("endpoint_url")):
        argumentos["endpoint_url"] = _texto(config["endpoint_url"])
    try:
        return boto3.client("s3", **argumentos)
    except Exception as exc:
        raise S3NoConfigurado(f"No se pudo crear el cliente de S3: {exc}") from exc


def subir_bytes(config, clave, contenido, content_type="application/octet-stream", cliente=None):
    """Escribe `contenido` en `bucket/clave`. Devuelve la clave escrita.

    `cliente` existe para las pruebas: se les pasa un doble y se comprueba con
    que argumentos se llamo a `put_object`, sin tocar AWS.
    """
    config = config or {}
    bucket = _texto(config.get("bucket"))
    clave = _texto(clave).lstrip("/")
    if not bucket:
        raise S3NoConfigurado("No hay bucket configurado en la sección [s3] de Secrets.")
    if not clave:
        raise S3Error("No se pudo armar la ruta del archivo en el bucket.")
    if not contenido:
        raise S3Error("El archivo llegó vacío; no se subió nada.")

    cliente = cliente or _cliente(config)
    argumentos = {
        "Bucket": bucket,
        "Key": clave,
        "Body": contenido,
        "ContentType": _texto(content_type) or "application/octet-stream",
    }
    # El ACL solo se manda si Secrets lo pide: muchos buckets tienen
    # "Object Ownership: bucket owner enforced" y ahi cualquier ACL es un 400.
    if _texto(config.get("acl")):
        argumentos["ACL"] = _texto(config["acl"])
    try:
        cliente.put_object(**argumentos)
    except Exception as exc:
        raise S3Error(f"S3 rechazó la escritura de {clave}: {exc}") from exc
    return clave


def existe_objeto(config, clave, cliente=None):
    """True/False/None: None cuando no se pudo saber (sin permiso de lectura)."""
    config = config or {}
    bucket = _texto(config.get("bucket"))
    clave = _texto(clave).lstrip("/")
    if not bucket or not clave:
        return None
    try:
        cliente = cliente or _cliente(config)
        cliente.head_object(Bucket=bucket, Key=clave)
        return True
    except Exception as exc:
        detalle = str(exc)
        if "404" in detalle or "NoSuchKey" in detalle or "Not Found" in detalle:
            return False
        return None
