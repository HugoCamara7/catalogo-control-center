#!/usr/bin/env python3
"""Lee las colecciones REALES de cada tienda y escribe el diccionario.

    python scripts/generar_diccionario_colecciones.py
    python scripts/generar_diccionario_colecciones.py --sitios columbia,vans

El diccionario de colecciones no se escribe a mano. Cada tienda tiene sus
propias colecciones y sus propias reglas, y una lista inventada se leeria como
cierta -- que es peor que no tenerla. Este script las lee, cruza cada coleccion
con el catalogo para saber a que MARCAS alcanza, y guarda el resultado en
`data/colecciones_por_marca.json`.

Que NO pisa al regenerar
------------------------
La clasificacion del vocabulario propio de cada tienda (que tags son actividad,
cuales tecnologia, cuales linea) es un dato CURADO a mano: Shopify no sabe que
"Hiking" es una actividad y "Omni-Tech(tm)" una tecnologia. Se conserva tal cual
estaba y los tags nuevos entran como `sin_clasificar`. Regenerar tiene que
poder correrse cuantas veces haga falta sin perder trabajo.

Credenciales
------------
Salen de `.streamlit/secrets.toml` (`[shopify_sites.<sitio>]`) o de las
variables de entorno del workflow (`COLUMBIA_SHOP_DOMAIN`,
`COLUMBIA_ADMIN_API_ACCESS_TOKEN`). No se importa `catalog_engine`, que ya las
sabe leer, porque ese modulo arrastra `app_matrixify` y con el Streamlit
entero: es la deuda de la seccion 2 del contexto, y no hace falta pagarla para
correr un script.

Un sitio sin credenciales o que devuelve error NO se reporta como tienda sin
colecciones -- eso se leeria como "no han creado ninguna". Se anota su fallo y
se deja lo que ya hubiera del anterior.
"""

import argparse
import json
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAIZ))

import shopify_api  # noqa: E402
from engines import colecciones as motor  # noqa: E402
from engines import load_status  # noqa: E402
from engines.garment_types import clase_de  # noqa: E402
from generate_columbia_matrixify import SITE_CONFIGS  # noqa: E402

DESTINO = RAIZ / "data" / "colecciones_por_marca.json"
SECRETS = RAIZ / ".streamlit" / "secrets.toml"


def _variable(site_key, sufijo):
    sitio = re.sub(r"[^A-Za-z0-9]+", "_", str(site_key or "")).strip("_").upper()
    return f"{sitio}_{sufijo}" if sitio else sufijo


def _secrets():
    if not SECRETS.exists():
        return {}
    try:
        import tomllib
    except ImportError:  # pragma: no cover - Python < 3.11
        return {}
    try:
        with open(SECRETS, "rb") as archivo:
            return tomllib.load(archivo)
    except Exception:
        return {}


def config_de_sitio(site_key, secretos):
    config = dict((secretos.get("shopify_sites") or {}).get(site_key) or {})
    for campo, sufijo in (
        ("shop_domain", "SHOP_DOMAIN"),
        ("admin_access_token", "ADMIN_API_ACCESS_TOKEN"),
        ("api_version", "API_VERSION"),
    ):
        if not config.get(campo):
            valor = os.getenv(_variable(site_key, sufijo)) or os.getenv(sufijo)
            if valor:
                config[campo] = valor
    return config


def _marcas_conocidas():
    return sorted({
        marca
        for config in SITE_CONFIGS.values()
        for marca in config.get("allowed_arti_brands", [])
    })


def leer_sitio(site_key, config, max_productos):
    """(colecciones, productos, error). Nunca levanta: un sitio caido no puede
    dejar sin diccionario a los otros cinco."""
    try:
        crudas = shopify_api.fetch_collections(config)
    except Exception as error:  # noqa: BLE001 - se reporta, no se propaga
        return [], [], f"colecciones: {error}"
    try:
        productos = shopify_api.fetch_products(config, max_products=max_productos)
    except Exception as error:  # noqa: BLE001
        return [shopify_api.coleccion_a_registro(c) for c in crudas], [], f"catalogo: {error}"
    return [shopify_api.coleccion_a_registro(c) for c in crudas], productos, ""


def producto_para_motor(producto):
    """La forma que evalua `engines/colecciones`, leida con el MISMO lector que
    el Status de carga: la marca y la identidad no se vuelven a escribir."""
    return {
        "clave": load_status.clave_de_producto(producto),
        "tags": [t.strip() for t in str(producto.get("Tags") or "").split(",") if t.strip()],
        "tipo": producto.get("Type") or "",
        "vendor": producto.get("Vendor") or "",
        "titulo": producto.get("Title") or "",
    }


def vocabulario_fusionado(anterior, tags_vivos):
    """El vocabulario curado, mas los tags nuevos en `sin_clasificar`.

    Los tags que ya no estan en la tienda se CONSERVAN: una coleccion vacia
    hoy puede volver a llenarse manana, y borrar su clasificacion obligaria a
    curarla otra vez.
    """
    salida = {familia: list(anterior.get(familia) or []) for familia in motor.FAMILIAS}
    ya = {motor.clave(t) for tags in salida.values() for t in tags}
    for tag in tags_vivos:
        k = motor.clave(tag)
        if k and k not in ya and motor.familia_de_tag(tag) == "sin_clasificar":
            ya.add(k)
            salida["sin_clasificar"].append(tag)
    return {f: sorted(v, key=str.casefold) for f, v in salida.items() if v}


def construir(sitios, max_productos, anterior):
    marcas_conocidas = _marcas_conocidas()
    secretos = _secrets()
    salida = {"version": 1, "generado": datetime.now(timezone.utc).isoformat(timespec="seconds"),
              "marcas": {}, "sitios_con_error": {}}
    marcas_previas = (anterior or {}).get("marcas", {})

    for site_key in sitios:
        config = config_de_sitio(site_key, secretos)
        if not config.get("shop_domain") or not config.get("admin_access_token"):
            salida["sitios_con_error"][site_key] = "sin credenciales en Secrets ni en el entorno"
            print(f"  {site_key}: sin credenciales, se salta")
            continue
        cols, productos, error = leer_sitio(site_key, config, max_productos)
        if error:
            salida["sitios_con_error"][site_key] = error
            print(f"  {site_key}: {error}")
            if not cols:
                continue
        etiqueta = SITE_CONFIGS.get(site_key, {}).get("site_label", site_key)
        print(f"  {site_key}: {len(cols)} colecciones, {len(productos)} productos")

        por_marca = {}
        for producto in productos:
            marca = load_status.marca_de_producto(producto, marcas_conocidas)
            por_marca.setdefault(marca, []).append(producto_para_motor(producto))

        for marca, lista in sorted(por_marca.items()):
            resultado = motor.evaluar_catalogo(lista, cols)
            previo = ((marcas_previas.get(marca) or {}).get("sitios") or {}).get(site_key) or {}
            del_sitio = []
            for coleccion in cols:
                cuenta = resultado["por_coleccion"].get(coleccion["handle"], 0)
                if not cuenta and coleccion["automatica"]:
                    # Una coleccion automatica sin un solo producto de ESTA
                    # marca no es suya. Listarla en las seis marcas haria creer
                    # que todas comparten las mismas colecciones.
                    continue
                del_sitio.append({
                    **coleccion,
                    "tags": motor.tags_de_coleccion(coleccion),
                    "evaluable": motor.coleccion_evaluable(coleccion),
                    "productos_de_la_marca": cuenta,
                })
            tags_vivos = [f["tag"] for f in motor.vocabulario_de_catalogo(lista)]
            salida["marcas"].setdefault(marca, {"sitios": {}})["sitios"][site_key] = {
                "etiqueta": etiqueta,
                "colecciones": del_sitio,
                "vocabulario": vocabulario_fusionado(previo.get("vocabulario") or {}, tags_vivos),
                "productos": len(lista),
                "huerfanos": len(resultado["huerfanos"]),
                "indeterminados": len(resultado["indeterminados"]),
            }
    return salida


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sitios", default="", help="lista separada por comas; por defecto todos")
    parser.add_argument("--max-productos", type=int, default=20000)
    parser.add_argument("--destino", default=str(DESTINO))
    args = parser.parse_args()

    sitios = [s.strip() for s in args.sitios.split(",") if s.strip()] or list(SITE_CONFIGS)
    desconocidos = [s for s in sitios if s not in SITE_CONFIGS]
    if desconocidos:
        parser.error(f"sitios que no estan en SITE_CONFIGS: {', '.join(desconocidos)}")

    destino = Path(args.destino)
    anterior = motor.cargar_diccionario(destino)
    print(f"Leyendo {len(sitios)} sitios...")
    datos = construir(sitios, args.max_productos, anterior)

    # Lo leido REEMPLAZA por sitio, no por archivo: si esta vez solo se leyo
    # Vans, las colecciones de los otros cinco tienen que seguir ahi.
    fusion = json.loads(json.dumps(anterior))
    fusion["version"] = datos["version"]
    fusion["generado"] = datos["generado"]
    fusion.setdefault("marcas", {})
    fusion["sitios_con_error"] = datos["sitios_con_error"]
    for marca, entrada in datos["marcas"].items():
        destino_marca = fusion["marcas"].setdefault(marca, {"sitios": {}})
        destino_marca.setdefault("sitios", {}).update(entrada["sitios"])

    motor.guardar_diccionario(destino, fusion)
    marcas = sorted(fusion["marcas"])
    print(f"\nEscrito {destino}")
    print(f"  marcas: {len(marcas)} -> {', '.join(marcas) or '(ninguna)'}")
    if datos["sitios_con_error"]:
        print("  sitios con error:")
        for sitio, error in sorted(datos["sitios_con_error"].items()):
            print(f"    {sitio}: {error}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
