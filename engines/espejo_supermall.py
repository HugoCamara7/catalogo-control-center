"""Que le falta a Supermall de lo que ya esta cargado en los demas sitios.

Por que existe
--------------
Supermall.pe es el marketplace de Forus: lleva el catalogo de TODOS los sitios,
no el de una marca. La forma obvia de mantenerlo al dia es "acordarse de cargar
tambien en Supermall cada vez", y eso falla por definicion — falla el dia que
alguien tiene prisa, y nadie se entera hasta que un producto lleva meses sin
aparecer.

Este motor da la respuesta por la resta, que es un dato y no una costumbre:

    lo que hay en cualquier sitio  -  lo que hay en Supermall  =  lo que falta

Es la misma pregunta que responde `engines/load_status`, con otro corte: alli
se compara lo que las marcas pidieron contra lo que se cargo; aqui se comparan
los sitios entre si. Por eso **no se vuelve a escribir como se lee un producto
de Shopify**: la marca, el estado web y sobre todo la identidad salen de
`load_status`. Dos lectores del mismo producto se separan sin que nadie lo
note, que es lo que ya se paga en este repositorio con las dos `normalize_size`.

Sin Streamlit y sin pandas, como el resto de `engines/`.
"""
from engines.load_status import (
    PRENDIDO,
    SIN_MARCA,
    clave_de_producto,
    estado_web,
    marca_de_producto,
    modelo_color,
)

# El sitio espejo. Es una constante y no un literal suelto porque la pantalla,
# el motor y las pruebas tienen que estar hablando del mismo.
DESTINO = "supermall"

# Que hacer con cada producto, segun como este en el destino.
FALTA = "Falta en Supermall"
PUBLICAR = "Cargado pero no visible"
AL_DIA = "Al dia"

# Un producto sin codigo Modelo-Color no se puede espejar por codigo: la carga
# se pide con una lista de codigos y el suyo no existe. No es lo mismo que
# "falta", y mezclarlos haria que la lista de codigos saliera con huecos que
# nadie explica.
SIN_CODIGO = "Sin codigo Modelo-Color"


def _texto(valor):
    return "" if valor is None else str(valor).strip()


def comparar(catalogos_por_sitio, destino=DESTINO, etiquetas_de_sitio=None,
             marcas_conocidas=(), marcas_por_sitio=None, vendors_de_sitio=()):
    """Una fila por producto que exista en algun sitio distinto del destino.

    `catalogos_por_sitio` es {site_key: [productos de Shopify]}, tal cual lo
    devuelve `cargar_catalogos_de_todos_los_sitios`.

    El destino AUSENTE no es lo mismo que el destino VACIO: si Supermall no
    esta en el diccionario -sin Secrets, o su lectura fallo- todo saldria como
    "falta" y eso se leeria como "hay que cargar el catalogo entero". Se avisa
    aparte, en `resumen["destino_leido"]`.
    """
    catalogos_por_sitio = catalogos_por_sitio or {}
    etiquetas_de_sitio = etiquetas_de_sitio or {}
    marcas_por_sitio = dict(marcas_por_sitio or {})
    destino_leido = destino in catalogos_por_sitio

    # Lo que ya esta en el destino, por identidad.
    en_destino = {}
    for producto in catalogos_por_sitio.get(destino) or []:
        clave = clave_de_producto(producto)
        if clave:
            en_destino[clave] = producto

    # Lo que hay en los demas sitios. Un mismo producto puede estar en varios;
    # se cuenta UNA vez y se anota de donde sale, porque el dato util es "este
    # producto ya existe en Rockford y en Columbia", no tres filas iguales.
    origen = {}
    for site_key, productos in catalogos_por_sitio.items():
        if site_key == destino:
            continue
        etiqueta = _texto(etiquetas_de_sitio.get(site_key)) or site_key
        del_sitio = marcas_por_sitio.get(site_key) or ()
        for producto in productos or []:
            clave = clave_de_producto(producto)
            if not clave:
                continue
            entrada = origen.setdefault(clave, {"producto": producto, "sitios": [], "marca": ""})
            if etiqueta not in entrada["sitios"]:
                entrada["sitios"].append(etiqueta)
            # La marca se resuelve CON EL SITIO en la mano y se queda con la
            # primera respuesta de verdad. Resolverla despues, sobre el
            # producto guardado, perdia el ultimo respaldo -- el sitio de una
            # sola marca -- porque para entonces ya no se sabe de cual salio.
            if not entrada["marca"]:
                marca = marca_de_producto(
                    producto, marcas_conocidas, del_sitio, vendors_de_sitio)
                if marca != SIN_MARCA:
                    entrada["marca"] = marca

    filas = []
    for clave, entrada in origen.items():
        producto = entrada["producto"]
        codigo = modelo_color(producto)
        producto_destino = en_destino.get(clave)
        if not codigo:
            situacion = SIN_CODIGO
            estado = ""
        elif producto_destino is None:
            situacion = FALTA
            estado = ""
        else:
            estado = estado_web(producto_destino)
            situacion = AL_DIA if estado == PRENDIDO else PUBLICAR
        filas.append({
            "Clave": clave,
            "Mod-Col": codigo,
            "Marca": entrada["marca"] or SIN_MARCA,
            "Titulo": _texto(producto.get("Title")),
            "Handle": _texto(producto.get("Handle")),
            "Sitios de origen": ", ".join(entrada["sitios"]),
            "Estado en Supermall": estado,
            "Situacion": situacion,
        })

    # Orden estable: primero lo que hay que hacer, y dentro de eso por marca y
    # codigo. Una tabla que se reordena en cada refresco no se puede comparar
    # con la de hace un rato -- misma regla que la tabla de sitios del Status
    # de carga.
    prioridad = {FALTA: 0, PUBLICAR: 1, SIN_CODIGO: 2, AL_DIA: 3}
    filas.sort(key=lambda fila: (
        prioridad.get(fila["Situacion"], 9),
        fila["Marca"],
        fila["Mod-Col"] or fila["Clave"],
    ))
    return {"filas": filas, "resumen": resumen(filas, destino_leido=destino_leido)}


def resumen(filas, destino_leido=True):
    """Los numeros de arriba de la pantalla.

    Las CLAVES no llevan tilde, igual que en `engines/load_status`: una clave
    con tilde que la pantalla pide sin ella es un KeyError que tumba la
    pantalla entera, y con `.get()` es peor -- devuelve None y el numero
    simplemente no aparece nunca.
    """
    filas = filas or []
    cuenta = {}
    for fila in filas:
        cuenta[fila["Situacion"]] = cuenta.get(fila["Situacion"], 0) + 1
    total = len(filas)
    al_dia = cuenta.get(AL_DIA, 0)
    return {
        "Productos en los otros sitios": total,
        "Ya visibles en Supermall": al_dia,
        "Faltan en Supermall": cuenta.get(FALTA, 0),
        "Cargados sin publicar": cuenta.get(PUBLICAR, 0),
        "Sin codigo Modelo-Color": cuenta.get(SIN_CODIGO, 0),
        "Cobertura": round(100.0 * al_dia / total, 1) if total else 0.0,
        "destino_leido": bool(destino_leido),
    }


def codigos_a_cargar(filas, limite=0):
    """Los Modelo-Color que hay que cargar en Supermall, sin repetir.

    Solo los que FALTAN. Un producto que ya esta cargado y solo hace falta
    publicar no se vuelve a cargar: eso lo arregla el propio Shopify y
    recargarlo le reescribiria la ficha sin que nadie lo haya pedido.

    Los que no tienen codigo quedan fuera a proposito y se cuentan aparte: la
    carga se pide por lista de codigos y el suyo no existe.
    """
    codigos = []
    for fila in filas or []:
        if fila.get("Situacion") != FALTA:
            continue
        codigo = _texto(fila.get("Mod-Col")).upper()
        if codigo and codigo not in codigos:
            codigos.append(codigo)
        if limite and len(codigos) >= limite:
            break
    return codigos


def por_marca(filas):
    """El mismo corte, agrupado por marca: donde esta el hueco mas grande."""
    marcas = {}
    for fila in filas or []:
        marca = fila.get("Marca") or SIN_MARCA
        fila_marca = marcas.setdefault(marca, {
            "Marca": marca,
            "En los otros sitios": 0,
            "Ya visibles": 0,
            "Faltan": 0,
            "Sin publicar": 0,
            "Sin codigo": 0,
        })
        fila_marca["En los otros sitios"] += 1
        situacion = fila.get("Situacion")
        if situacion == AL_DIA:
            fila_marca["Ya visibles"] += 1
        elif situacion == FALTA:
            fila_marca["Faltan"] += 1
        elif situacion == PUBLICAR:
            fila_marca["Sin publicar"] += 1
        elif situacion == SIN_CODIGO:
            fila_marca["Sin codigo"] += 1
    return sorted(marcas.values(), key=lambda fila: (-fila["Faltan"], fila["Marca"]))
