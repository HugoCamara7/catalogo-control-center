"""Metricas por Codigo Modelo-Color.

Sin dependencias de Streamlit ni de pandas.

La unidad de medida es el PRODUCTO (Modelo-Color), no la variante ni el
archivo. Un producto con 8 tallas y sin una sola imagen cuenta 1, no 8.

Por que existe
--------------
"Productos sin foto" se venia contando de varias formas a la vez: imagenes
faltantes, variantes sin foto, filas del maestro. Todas dan numeros distintos y
ninguna responde la pregunta que se hace de verdad, que es cuantos productos no
se pueden publicar porque no tienen NINGUNA imagen.

Aqui hay una sola definicion, y devuelve tambien el total para poder decir
"12 / 185" en vez de un numero suelto.
"""

import re


def _texto(valor):
    if valor is None:
        return ""
    if isinstance(valor, float) and valor != valor:
        return ""
    return str(valor).strip()


def _numero(valor, defecto=0.0):
    texto = _texto(valor)
    if not texto:
        return defecto
    try:
        return float(texto.replace(",", "."))
    except ValueError:
        return defecto


def clave_modelo_color(valor):
    return re.sub(r"\s+", " ", _texto(valor)).upper()


def contar_fotos(valor):
    """Cuantas imagenes tiene un producto.

    Acepta un numero ya contado, o el texto de Shopify con las URL separadas
    por ';' o coma. Un texto vacio o sin URL reales cuenta 0.
    """
    if isinstance(valor, bool):
        return 1 if valor else 0
    if isinstance(valor, float) and valor != valor:
        # NaN. Una columna de pandas sin valor llega asi, y int(nan) revienta.
        return 0
    if isinstance(valor, (int, float)):
        return max(0, int(valor))
    if isinstance(valor, (list, tuple, set)):
        return len([item for item in valor if _texto(item)])
    texto = _texto(valor)
    if not texto:
        return 0
    if re.fullmatch(r"\d+(\.0+)?", texto):
        return max(0, int(float(texto)))
    return len([parte for parte in re.split(r"[;,]", texto) if _texto(parte)])


def productos_sin_foto(filas):
    """Modelo-Color sin NINGUNA imagen.

    filas: iterable de dicts con 'mod_col' y 'fotos'. Se aceptan ademas
    'marca' y 'con_stock', que se conservan para el informe.

    Un mismo Modelo-Color puede venir en varias filas: se queda con el maximo
    de fotos visto. Si una fila dice 0 y otra dice 3, el producto TIENE fotos.

    Devuelve el conteo, el total y la lista de los que estan sin foto, para
    poder decir "Sin foto: 12 / 185 productos" y ademas saber cuales son.
    """
    fotos_por_modelo = {}
    marca_por_modelo = {}
    stock_por_modelo = {}
    for fila in filas or []:
        if not isinstance(fila, dict):
            continue
        modelo = clave_modelo_color(fila.get("mod_col"))
        if not modelo:
            continue
        fotos = contar_fotos(fila.get("fotos"))
        fotos_por_modelo[modelo] = max(fotos_por_modelo.get(modelo, 0), fotos)
        if _texto(fila.get("marca")) and not marca_por_modelo.get(modelo):
            marca_por_modelo[modelo] = _texto(fila.get("marca"))
        if fila.get("con_stock"):
            stock_por_modelo[modelo] = True

    sin_foto = sorted(modelo for modelo, fotos in fotos_por_modelo.items() if fotos <= 0)
    total = len(fotos_por_modelo)
    sin_foto_con_stock = [modelo for modelo in sin_foto if stock_por_modelo.get(modelo)]
    return {
        "sin_foto": len(sin_foto),
        "total": total,
        "con_foto": total - len(sin_foto),
        "porcentaje": round(len(sin_foto) * 100.0 / total, 1) if total else 0.0,
        "ratio": f"{len(sin_foto)} / {total} productos",
        "detalle": [
            {"mod_col": modelo,
             "marca": marca_por_modelo.get(modelo, ""),
             "con_stock": bool(stock_por_modelo.get(modelo))}
            for modelo in sin_foto
        ],
        "sin_foto_con_stock": len(sin_foto_con_stock),
    }


def resumen_modelo_color(filas):
    """Panorama por Modelo-Color: cuantos hay, con foto, con stock y vendibles.

    filas: dicts con 'mod_col' y, opcionalmente, 'fotos', 'con_stock',
    'con_precio' y 'creado'.

    "Vendible" es el producto que tiene las cuatro cosas a la vez. Es el unico
    numero que responde "cuantos puedo vender hoy".
    """
    modelos = {}
    for fila in filas or []:
        if not isinstance(fila, dict):
            continue
        modelo = clave_modelo_color(fila.get("mod_col"))
        if not modelo:
            continue
        datos = modelos.setdefault(modelo, {
            "fotos": 0, "con_stock": False, "con_precio": False, "creado": False,
        })
        datos["fotos"] = max(datos["fotos"], contar_fotos(fila.get("fotos")))
        datos["con_stock"] = datos["con_stock"] or bool(fila.get("con_stock"))
        datos["con_precio"] = datos["con_precio"] or bool(fila.get("con_precio"))
        datos["creado"] = datos["creado"] or bool(fila.get("creado"))

    total = len(modelos)
    con_foto = sum(1 for d in modelos.values() if d["fotos"] > 0)
    con_stock = sum(1 for d in modelos.values() if d["con_stock"])
    con_precio = sum(1 for d in modelos.values() if d["con_precio"])
    creados = sum(1 for d in modelos.values() if d["creado"])
    vendibles = sum(1 for d in modelos.values()
                    if d["fotos"] > 0 and d["con_stock"] and d["con_precio"] and d["creado"])
    return {
        "total": total,
        "con_foto": con_foto,
        "sin_foto": total - con_foto,
        "con_stock": con_stock,
        "sin_stock": total - con_stock,
        "con_precio": con_precio,
        "sin_precio": total - con_precio,
        "creados": creados,
        "no_creados": total - creados,
        "vendibles": vendibles,
    }


def ratio(parte, total, sustantivo="productos"):
    """Texto '12 / 185 productos'. Un numero suelto no dice si es mucho o poco."""
    parte = int(_numero(parte))
    total = int(_numero(total))
    return f"{parte:,} / {total:,} {sustantivo}".replace(",", ".")


def filas_desde_dataframe(df, columna_mod_col, columna_fotos="", columna_marca="",
                          columna_stock="", columna_precio="", columna_creado=""):
    """Convierte un DataFrame en las filas que esperan las funciones de arriba.

    Se admite un DataFrame para no obligar a las pantallas a rearmar los datos,
    pero el motor sigue sin importar pandas: solo se usa el acceso por columna.
    """
    if df is None or getattr(df, "empty", True):
        return []
    columnas = list(getattr(df, "columns", []))
    if columna_mod_col not in columnas:
        return []
    mapa = {
        "fotos": columna_fotos,
        "marca": columna_marca,
        "con_stock": columna_stock,
        "con_precio": columna_precio,
        "creado": columna_creado,
    }
    presentes = {destino: origen for destino, origen in mapa.items()
                 if origen and origen in columnas}
    campos = [columna_mod_col] + list(presentes.values())
    filas = []
    for registro in df[campos].to_dict("records"):
        fila = {"mod_col": registro.get(columna_mod_col)}
        for destino, origen in presentes.items():
            fila[destino] = registro.get(origen)
        filas.append(fila)
    return filas
