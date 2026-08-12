"""Motor de consolidacion de stock por Codigo Modelo-Color.

Sin dependencias de Streamlit ni de pandas.

Por que existe
--------------
El stock llega a nivel de variante: una fila por talla (y a veces varias filas
por talla, porque una misma talla puede tener mas de un SKU en el maestro, o
porque dos formatos de talla se normalizan al mismo valor). Pero el producto
que se prende o se apaga en la web es el Modelo-Color completo.

Sumar las filas tal cual infla el total: la misma talla se cuenta dos veces.
Aqui la unidad de verdad es el par (Modelo-Color, talla): primero se consolida
cada talla, despues se suma el modelo. El resultado es estable aunque el
maestro traiga filas repetidas.

Que devuelve
------------
Por cada Modelo-Color: unidades, cuantas tallas hay, cuantas tienen stock,
cuantas no, la cobertura, y si el producto debe estar visible. Tambien deja
contadas las filas repetidas que se colapsaron, para poder ver si el maestro
esta trayendo duplicados.
"""

import re

# Politicas para decidir si el Modelo-Color debe estar visible en la web.
POLITICA_UNA_TALLA = "una_talla"        # basta con una talla con stock
POLITICA_TODAS = "todas_las_tallas"     # todas las tallas deben tener stock
POLITICA_MINIMO = "minimo_tallas"       # al menos N tallas con stock

POLITICAS = (POLITICA_UNA_TALLA, POLITICA_TODAS, POLITICA_MINIMO)

# Como resolver varias filas de la MISMA talla.
# "max" es el valor correcto por defecto: filas repetidas de una talla son la
# misma existencia vista dos veces, no dos existencias distintas.
COLAPSO_MAX = "max"
COLAPSO_SUMA = "suma"
COLAPSO_PRIMERO = "primero"


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
    """Forma canonica del Codigo Modelo-Color.

    Mayusculas y sin espacios sobrantes. No se tocan guiones ni puntos: son
    parte del codigo y distinguen modelos distintos.
    """
    return re.sub(r"\s+", " ", _texto(valor)).upper()


def clave_talla(valor):
    """Forma canonica de la talla, para agrupar las variantes de un modelo."""
    return re.sub(r"\s+", "", _texto(valor)).upper()


def clave_variante(mod_col, talla):
    """Identidad de una variante. Vacia si falta cualquiera de las dos partes."""
    modelo = clave_modelo_color(mod_col)
    talla = clave_talla(talla)
    return f"{modelo}-{talla}" if modelo and talla else ""


def consolidar_por_modelo_color(filas, politica=POLITICA_UNA_TALLA, minimo_tallas=1,
                                colapso=COLAPSO_MAX, umbral_unidades=0):
    """Agrupa filas de variante en un resumen por Modelo-Color.

    filas: iterable de dicts con 'mod_col', 'talla' y 'unidades'. Se aceptan
    ademas 'marca' y 'sku', que se conservan para el informe.

    umbral_unidades: unidades por encima de las cuales la talla cuenta como
    disponible. Con 0, cualquier unidad positiva cuenta.

    Devuelve una lista de dicts ordenada por Modelo-Color.
    """
    if politica not in POLITICAS:
        politica = POLITICA_UNA_TALLA
    minimo_tallas = max(1, int(minimo_tallas or 1))
    umbral = float(umbral_unidades or 0)

    modelos = {}
    for fila in filas or []:
        if not isinstance(fila, dict):
            continue
        modelo = clave_modelo_color(fila.get("mod_col"))
        talla = clave_talla(fila.get("talla"))
        if not modelo or not talla:
            continue
        unidades = max(0.0, _numero(fila.get("unidades")))
        datos = modelos.setdefault(modelo, {
            "mod_col": modelo,
            "marca": _texto(fila.get("marca")),
            "tallas": {},
            "skus": set(),
            "filas_leidas": 0,
            "filas_colapsadas": 0,
        })
        if not datos["marca"]:
            datos["marca"] = _texto(fila.get("marca"))
        if _texto(fila.get("sku")):
            datos["skus"].add(_texto(fila.get("sku")))
        datos["filas_leidas"] += 1
        if talla in datos["tallas"]:
            datos["filas_colapsadas"] += 1
            previo = datos["tallas"][talla]
            if colapso == COLAPSO_SUMA:
                datos["tallas"][talla] = previo + unidades
            elif colapso == COLAPSO_PRIMERO:
                datos["tallas"][talla] = previo
            else:
                datos["tallas"][talla] = max(previo, unidades)
        else:
            datos["tallas"][talla] = unidades

    salida = []
    for modelo in sorted(modelos):
        datos = modelos[modelo]
        tallas = datos["tallas"]
        con_stock = sorted(t for t, u in tallas.items() if u > umbral)
        sin_stock = sorted(t for t, u in tallas.items() if u <= umbral)
        total = len(tallas)
        unidades = sum(tallas.values())
        if politica == POLITICA_TODAS:
            visible = total > 0 and not sin_stock
        elif politica == POLITICA_MINIMO:
            visible = len(con_stock) >= minimo_tallas
        else:
            visible = bool(con_stock)
        salida.append({
            "mod_col": modelo,
            "marca": datos["marca"],
            "unidades": int(unidades) if float(unidades).is_integer() else round(unidades, 2),
            "tallas_total": total,
            "tallas_con_stock": len(con_stock),
            "tallas_sin_stock": len(sin_stock),
            "cobertura": round(len(con_stock) * 100.0 / total, 1) if total else 0.0,
            "detalle_tallas_con_stock": con_stock,
            "detalle_tallas_sin_stock": sin_stock,
            "skus": sorted(datos["skus"]),
            "filas_leidas": datos["filas_leidas"],
            "filas_colapsadas": datos["filas_colapsadas"],
            "con_stock": bool(con_stock),
            "debe_estar_visible": bool(visible),
        })
    return salida


def resumen_consolidado(consolidado):
    """Totales de una consolidacion, para KPIs y para el cuerpo del correo."""
    consolidado = list(consolidado or [])
    return {
        "modelos_color": len(consolidado),
        "modelos_con_stock": sum(1 for m in consolidado if m["con_stock"]),
        "modelos_sin_stock": sum(1 for m in consolidado if not m["con_stock"]),
        "modelos_visibles": sum(1 for m in consolidado if m["debe_estar_visible"]),
        "unidades": sum(m["unidades"] for m in consolidado),
        "tallas": sum(m["tallas_total"] for m in consolidado),
        "tallas_con_stock": sum(m["tallas_con_stock"] for m in consolidado),
        "tallas_sin_stock": sum(m["tallas_sin_stock"] for m in consolidado),
        "filas_leidas": sum(m["filas_leidas"] for m in consolidado),
        "filas_colapsadas": sum(m["filas_colapsadas"] for m in consolidado),
    }


def indice_por_modelo_color(consolidado):
    """Diccionario Modelo-Color -> resumen, para cruzar sin recorrer la lista."""
    return {m["mod_col"]: m for m in (consolidado or [])}


def filas_desde_dataframe(df, columna_mod_col, columna_talla, columna_unidades,
                          columna_marca="", columna_sku=""):
    """Convierte un DataFrame en las filas que espera consolidar_por_modelo_color.

    Se acepta un DataFrame para no obligar a las pantallas a rearmar los datos,
    pero el motor sigue sin depender de pandas: solo se usa el acceso por
    columna, que cualquier objeto tabular ofrece.
    """
    if df is None or getattr(df, "empty", True):
        return []
    columnas = list(getattr(df, "columns", []))
    for requerida in (columna_mod_col, columna_talla, columna_unidades):
        if requerida not in columnas:
            return []
    filas = []
    marca = columna_marca if columna_marca in columnas else ""
    sku = columna_sku if columna_sku in columnas else ""
    campos = [columna_mod_col, columna_talla, columna_unidades]
    if marca:
        campos.append(marca)
    if sku:
        campos.append(sku)
    for registro in df[campos].to_dict("records"):
        filas.append({
            "mod_col": registro.get(columna_mod_col),
            "talla": registro.get(columna_talla),
            "unidades": registro.get(columna_unidades),
            "marca": registro.get(marca) if marca else "",
            "sku": registro.get(sku) if sku else "",
        })
    return filas
