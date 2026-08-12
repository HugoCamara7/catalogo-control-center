"""Validacion de precio y stock por Codigo Modelo-Color.

Sin dependencias de Streamlit ni de pandas.

Que responde
------------
Una sola pregunta: despues de que Producto cargo los precios, ¿llegaron
correctamente a Shopify? Mientras la respuesta no sea que si, la solicitud no
puede cerrarse.

La comparacion es por Modelo-Color porque es la unidad con la que se trabaja en
toda la app. Un modelo con una sola talla mal cargada es un modelo con
problema, no "una variante con problema".

Severidad
---------
- bloqueo: impide cerrar (sin precio, precio en cero, no llego a Shopify).
- aviso:   no impide cerrar pero hay que mirarlo (diferencia de centimos,
           stock distinto del esperado).

Es deliberado que un aviso no bloquee: si cualquier diferencia frenara el
cierre, nadie cerraria nunca y se volveria a cerrar a mano por fuera del flujo.
"""

import re

SEVERIDAD_BLOQUEO = "bloqueo"
SEVERIDAD_AVISO = "aviso"

# Diferencia de precio que se tolera sin avisar. Cubre el redondeo de Shopify.
TOLERANCIA_PRECIO = 0.01

MOTIVO_SIN_SHOPIFY = "No llegó a Shopify"
MOTIVO_SIN_PRECIO = "Sin precio en Shopify"
MOTIVO_PRECIO_CERO = "Precio en cero"
MOTIVO_PRECIO_DISTINTO = "Precio distinto del esperado"
MOTIVO_SIN_STOCK = "Sin stock en Shopify"
MOTIVO_STOCK_DISTINTO = "Stock distinto del esperado"


def _texto(valor):
    if valor is None:
        return ""
    if isinstance(valor, float) and valor != valor:
        return ""
    return str(valor).strip()


def _numero(valor, defecto=None):
    texto = _texto(valor)
    if not texto:
        return defecto
    texto = re.sub(r"[^\d,.\-]", "", texto).replace(",", ".")
    if texto.count(".") > 1:  # separador de miles
        entero, _, decimal = texto.rpartition(".")
        texto = entero.replace(".", "") + "." + decimal
    try:
        return float(texto)
    except ValueError:
        return defecto


def clave_modelo_color(valor):
    return re.sub(r"\s+", " ", _texto(valor)).upper()


def validar(esperados, en_shopify, *, tolerancia=TOLERANCIA_PRECIO,
            exigir_stock=False):
    """Compara lo que se esperaba contra lo que hay en Shopify.

    esperados: dicts con 'mod_col' y, opcionalmente, 'precio' y 'stock'.
               Sin 'precio' solo se comprueba que exista precio en Shopify.
    en_shopify: dicts con 'mod_col', 'precio' y 'stock'.

    exigir_stock: con True, un modelo sin stock en Shopify bloquea. Por defecto
    solo avisa, porque un producto puede cargarse legitimamente sin stock.

    Devuelve el resumen y el detalle de cada problema.
    """
    reales = {}
    for fila in en_shopify or []:
        if not isinstance(fila, dict):
            continue
        modelo = clave_modelo_color(fila.get("mod_col"))
        if not modelo:
            continue
        precio = _numero(fila.get("precio"))
        stock = _numero(fila.get("stock"), 0.0)
        previo = reales.get(modelo)
        if previo is None:
            reales[modelo] = {"precio": precio, "stock": stock or 0.0}
        else:
            # Varias variantes del mismo modelo: precio el primero no vacio,
            # stock la suma.
            if previo["precio"] is None:
                previo["precio"] = precio
            previo["stock"] = (previo["stock"] or 0.0) + (stock or 0.0)

    problemas = []
    revisados = 0
    vistos = set()
    for fila in esperados or []:
        if not isinstance(fila, dict):
            continue
        modelo = clave_modelo_color(fila.get("mod_col"))
        if not modelo or modelo in vistos:
            continue
        vistos.add(modelo)
        revisados += 1
        real = reales.get(modelo)
        marca = _texto(fila.get("marca"))

        if real is None:
            problemas.append(_problema(modelo, marca, SEVERIDAD_BLOQUEO, MOTIVO_SIN_SHOPIFY,
                                       fila.get("precio"), None))
            continue

        precio_real = real["precio"]
        if precio_real is None:
            problemas.append(_problema(modelo, marca, SEVERIDAD_BLOQUEO, MOTIVO_SIN_PRECIO,
                                       fila.get("precio"), None))
        elif precio_real <= 0:
            problemas.append(_problema(modelo, marca, SEVERIDAD_BLOQUEO, MOTIVO_PRECIO_CERO,
                                       fila.get("precio"), precio_real))
        else:
            esperado = _numero(fila.get("precio"))
            if esperado is not None and abs(esperado - precio_real) > float(tolerancia):
                problemas.append(_problema(modelo, marca, SEVERIDAD_AVISO, MOTIVO_PRECIO_DISTINTO,
                                           esperado, precio_real))

        stock_real = real["stock"] or 0.0
        stock_esperado = _numero(fila.get("stock"))
        if stock_real <= 0:
            severidad = SEVERIDAD_BLOQUEO if exigir_stock else SEVERIDAD_AVISO
            problemas.append(_problema(modelo, marca, severidad, MOTIVO_SIN_STOCK,
                                       stock_esperado, stock_real, campo="stock"))
        elif stock_esperado is not None and abs(stock_esperado - stock_real) > 0:
            problemas.append(_problema(modelo, marca, SEVERIDAD_AVISO, MOTIVO_STOCK_DISTINTO,
                                       stock_esperado, stock_real, campo="stock"))

    bloqueos = [p for p in problemas if p["severidad"] == SEVERIDAD_BLOQUEO]
    avisos = [p for p in problemas if p["severidad"] == SEVERIDAD_AVISO]
    con_problema = {p["mod_col"] for p in bloqueos}
    return {
        "revisados": revisados,
        "conformes": revisados - len(con_problema),
        "bloqueos": len(bloqueos),
        "avisos": len(avisos),
        "modelos_bloqueados": sorted(con_problema),
        "problemas": problemas,
        "aprobado": revisados > 0 and not bloqueos,
        "detalle": _detalle(revisados, bloqueos, avisos),
    }


def _problema(modelo, marca, severidad, motivo, esperado, real, campo="precio"):
    return {
        "mod_col": modelo,
        "marca": marca,
        "severidad": severidad,
        "campo": campo,
        "motivo": motivo,
        "esperado": esperado,
        "encontrado": real,
    }


def _detalle(revisados, bloqueos, avisos):
    if not revisados:
        return "No había modelo-color que revisar."
    if bloqueos:
        return (f"{len(bloqueos)} modelo-color con problema bloqueante de "
                f"{revisados} revisados. No se puede cerrar la solicitud.")
    if avisos:
        return f"{revisados} modelo-color validados, con {len(avisos)} aviso(s) para revisar."
    return f"{revisados} modelo-color con precio y stock correctos en Shopify."


def filas_para_informe(resultado):
    """Los problemas en forma de tabla, para mostrarlos o exportarlos."""
    return [{
        "Mod-Col": p["mod_col"],
        "Marca": p["marca"],
        "Severidad": "Bloqueo" if p["severidad"] == SEVERIDAD_BLOQUEO else "Aviso",
        "Campo": p["campo"].capitalize(),
        "Problema": p["motivo"],
        "Esperado": "" if p["esperado"] is None else p["esperado"],
        "En Shopify": "" if p["encontrado"] is None else p["encontrado"],
    } for p in (resultado or {}).get("problemas", [])]
