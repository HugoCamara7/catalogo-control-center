"""Diccionario maestro de tipos de prenda, por sitio.

Sin dependencias de Streamlit ni de pandas.

GENERADO desde "Tipo de Prendas Actualizado Diccionario - Corregido.xlsx"
(hoja "2 TIPOS"), agosto 2026. Es la fuente de verdad que confirmo el usuario.

Que resuelve
------------
1. **El tipo canonico** a partir de como lo escriba quien sea. 300+ sinonimos.
2. **La clase** (Vestuario / Calzado / Accesorios) derivada del tipo.
3. **El nombre que le toca a cada sitio**, que NO siempre es el canonico:
   una misma prenda puede llamarse distinto en Columbia y en Vans.

Un tipo que no aplica a un sitio no aparece en su diccionario "sitios". Eso es
informacion, no un hueco: significa que ese sitio no vende esa prenda.

Reglas al generar
-----------------
- Ningun nombre puede apuntar a dos tipos. El tipo canonico y sus nombres por
  sitio mandan sobre cualquier sinonimo.
- La busqueda ignora mayusculas, tildes, espacios y guiones.
"""

import re
import unicodedata

TIPOS = [
    {
        "tipo": "Accesorios De Limpieza",
        "categoria": "Accesorios",
        "sitios": {"rockford": "Accesorios De Limpieza", "hush_puppies": "Accesorios De Limpieza"},
        "sinonimos": ["Accesorio De Limpieza", "Betun", "Cremas Renovadoras", "Escobilla", "Escobilla Aplicadora", "Escobilla De Brillo", "Escobillas", "Escobillas Aplicadoras", "Escobillas De Brillo", "Impermeabilizante", "Protector Limpieza", "Protectores Limpieza", "Shampoo", "Shampoos"],
    },
    {
        "tipo": "Accesorios Para El Pelo",
        "categoria": "Accesorios",
        "sitios": {"hush_puppies": "Accesorios Para El Pelo"},
        "sinonimos": ["Accesorio Para El Pelo", "Colet", "Colets", "Vincha", "Vinchas"],
    },
    {
        "tipo": "Bastones",
        "categoria": "Accesorios",
        "sitios": {"columbia": "Bastones", "rockford": "Bastones"},
        "sinonimos": ["Baston", "Poles", "Trekking Pole"],
    },
    {
        "tipo": "Billeteras",
        "categoria": "Accesorios",
        "sitios": {"rockford": "Billeteras", "hush_puppies": "Billeteras", "vans": "Billeteras"},
        "sinonimos": ["Billetera", "Monedero", "Monederos", "Wallet", "Wallets"],
    },
    {
        "tipo": "Bolsos",
        "categoria": "Accesorios",
        "sitios": {"columbia": "Bolsos", "vans": "Bolsos"},
        "sinonimos": ["Bag", "Bags", "Bolsa", "Bolsas", "Bolso"],
    },
    {
        "tipo": "Botellas",
        "categoria": "Accesorios",
        "sitios": {"columbia": "Botellas", "rockford": "Botellas"},
        "sinonimos": ["Botella", "Bottle", "Bottles", "Termo", "Termos"],
    },
    {
        "tipo": "Bufandas",
        "categoria": "Accesorios",
        "sitios": {"rockford": "Bufandas"},
        "sinonimos": ["Bufanda", "Chalina", "Chalinas", "Scarf", "Scarves"],
    },
    {
        "tipo": "Canguros",
        "categoria": "Accesorios",
        "sitios": {"columbia": "Canguros", "rockford": "Canguros", "vans": "Canguros"},
        "sinonimos": ["Canguro", "Hip Pack", "Rinonera", "Rinoneras", "Waist Bag"],
    },
    {
        "tipo": "Carteras",
        "categoria": "Accesorios",
        "sitios": {"rockford": "Carteras", "hush_puppies": "Carteras", "vans": "Carteras"},
        "sinonimos": ["Bolso De Mano", "Cartera", "Handbag", "Purse"],
    },
    {
        "tipo": "Cartucheras",
        "categoria": "Accesorios",
        "sitios": {"hush_puppies": "Cartucheras"},
        "sinonimos": ["Cartuchera", "Estuche", "Estuches"],
    },
    {
        "tipo": "Chullos",
        "categoria": "Accesorios",
        "sitios": {"columbia": "Chullos", "rockford": "Beanies", "vans": "Beanie"},
        "sinonimos": ["Beanie", "Beanies", "Chullo", "Gorro De Lana"],
    },
    {
        "tipo": "Cinturones",
        "categoria": "Accesorios",
        "sitios": {"rockford": "Cinturones", "hush_puppies": "Cinturones", "vans": "Cinturones"},
        "sinonimos": ["Belt", "Belts", "Cinturon", "Correa", "Correas", "Faja", "Fajas"],
    },
    {
        "tipo": "Coolers",
        "categoria": "Accesorios",
        "sitios": {"columbia": "Coolers", "rockford": "Coolers"},
        "sinonimos": ["Conservadora", "Conservadoras", "Cooler"],
    },
    {
        "tipo": "Crema renovadora",
        "categoria": "Accesorios",
        "sitios": {"rockford": "Crema Renovadora"},
        "sinonimos": ["Cream Renov", "Cremas Renovadora"],
    },
    {
        "tipo": "Cuchillas",
        "categoria": "Accesorios",
        "sitios": {"columbia": "Cuchillas", "rockford": "Cuchillas"},
        "sinonimos": ["Cuchilla", "Cuchillo", "Cuchillos", "Knife"],
    },
    {
        "tipo": "Cuelleras",
        "categoria": "Accesorios",
        "sitios": {"columbia": "Cuelleras", "rockford": "Cuelleras"},
        "sinonimos": ["Buff", "Cuellera", "Cuello", "Cuellos", "Neck Gaiter"],
    },
    {
        "tipo": "Fundas Para Latas",
        "categoria": "Accesorios",
        "sitios": {"columbia": "Fundas Para Latas", "rockford": "Fundas Para Latas"},
        "sinonimos": ["Can Cooler", "Enfriador De Lata", "Funda Para Lata"],
    },
    {
        "tipo": "Gorros",
        "categoria": "Accesorios",
        "sitios": {"columbia": "Gorros", "rockford": "Gorros", "hush_puppies": "Gorros", "vans": "Gorros"},
        "sinonimos": ["Boina", "Boinas", "Bucket", "Buckets", "Cap", "Caps", "Gorra", "Gorras", "Gorro", "Jockey", "Jockeys"],
    },
    {
        "tipo": "Guantes",
        "categoria": "Accesorios",
        "sitios": {"columbia": "Guantes", "rockford": "Guantes"},
        "sinonimos": ["Glove", "Gloves", "Guante", "Manopla", "Manoplas"],
    },
    {
        "tipo": "Lentes De Sol",
        "categoria": "Accesorios",
        "sitios": {"rockford": "Lentes De Sol", "vans": "Lentes De Sol"},
        "sinonimos": ["Anteojos", "Gafas", "Gafas De Sol", "Lente", "Lente De Sol", "Lentes", "Sunglasses"],
    },
    {
        "tipo": "Maletines",
        "categoria": "Accesorios",
        "sitios": {"columbia": "Maletines", "rockford": "Maletines", "hush_puppies": "Maletines"},
        "sinonimos": ["Briefcase", "Maleta", "Maletas", "Maletin"],
    },
    {
        "tipo": "Medias",
        "categoria": "Accesorios",
        "sitios": {"columbia": "Medias", "rockford": "Medias", "hush_puppies": "Medias", "vans": "Medias"},
        "sinonimos": ["Calcetin", "Calcetines", "Media", "Sock", "Socks"],
    },
    {
        "tipo": "Mochilas",
        "categoria": "Accesorios",
        "sitios": {"columbia": "Mochilas", "rockford": "Mochilas", "hush_puppies": "Mochilas", "vans": "Mochilas"},
        "sinonimos": ["Backpack", "Backpacks", "Mochila"],
    },
    {
        "tipo": "Neceseres",
        "categoria": "Accesorios",
        "sitios": {"columbia": "Neceseres", "rockford": "Neceseres"},
        "sinonimos": ["Cosmetiquero", "Cosmetiqueros", "Neceser", "Toiletry"],
    },
    {
        "tipo": "Pasadores",
        "categoria": "Accesorios",
        "sitios": {"vans": "Pasadores"},
        "sinonimos": ["Cordon", "Cordones", "Pasador", "Shoelace", "Shoelaces"],
    },
    {
        "tipo": "Pasamontañas",
        "categoria": "Accesorios",
        "sitios": {"columbia": "Pasamontañas", "rockford": "Pasamontañas"},
        "sinonimos": ["Balaclava", "Pasamontana", "Pasamontanas"],
    },
    {
        "tipo": "Pañuelos",
        "categoria": "Accesorios",
        "sitios": {"rockford": "Pañuelos"},
        "sinonimos": ["Bandana", "Bandanas", "Panuelo", "Panuelos"],
    },
    {
        "tipo": "Sombreros",
        "categoria": "Accesorios",
        "sitios": {"columbia": "Sombreros", "rockford": "Sombreros", "vans": "Sombreros"},
        "sinonimos": ["Hat", "Hats", "Sombrero"],
    },
    {
        "tipo": "Tazas",
        "categoria": "Accesorios",
        "sitios": {"columbia": "Tazas"},
        "sinonimos": ["Mug", "Mugs", "Taza"],
    },
    {
        "tipo": "Alpargatas",
        "categoria": "Calzado",
        "sitios": {"rockford": "Alpargatas", "hush_puppies": "Alpargatas"},
        "sinonimos": ["Alpargata", "Espadrille", "Espadrilles"],
    },
    {
        "tipo": "Ballerinas",
        "categoria": "Calzado",
        "sitios": {"hush_puppies": "Ballerinas"},
        "sinonimos": ["Balerina", "Balerinas", "Ballerina", "Flat", "Flats", "Guillermina", "Guillerminas"],
    },
    {
        "tipo": "Botas",
        "categoria": "Calzado",
        "sitios": {"columbia": "Botas", "rockford": "Botas", "hush_puppies": "Botas"},
        "sinonimos": ["Boots", "Bota"],
    },
    {
        "tipo": "Botines",
        "categoria": "Calzado",
        "sitios": {"columbia": "Botines", "rockford": "Botines", "hush_puppies": "Botines"},
        "sinonimos": ["Ankle Boot", "Boot", "Botin"],
    },
    {
        "tipo": "Mocasines",
        "categoria": "Calzado",
        "sitios": {"rockford": "Mocasines", "hush_puppies": "Mocasines"},
        "sinonimos": ["Loafer", "Loafers", "Mocasin"],
    },
    {
        "tipo": "Pantuflas",
        "categoria": "Calzado",
        "sitios": {"columbia": "Pantuflas", "rockford": "Pantuflas", "hush_puppies": "Pantuflas"},
        "sinonimos": ["Babucha", "Babuchas", "Pantufla", "Slipper", "Slippers"],
    },
    {
        "tipo": "Sandalias",
        "categoria": "Calzado",
        "sitios": {"columbia": "Sandalias", "rockford": "Sandalias", "hush_puppies": "Sandalias"},
        "sinonimos": ["Chala", "Chalas", "Sandal", "Sandalia", "Sandals"],
    },
    {
        "tipo": "Slip Ons",
        "categoria": "Calzado",
        "sitios": {"rockford": "Slip Ons", "hush_puppies": "Slip Ons"},
        "sinonimos": ["Slip On"],
    },
    {
        "tipo": "Suecos",
        "categoria": "Calzado",
        "sitios": {"rockford": "Suecos", "hush_puppies": "Suecos"},
        "sinonimos": ["Clog", "Clogs", "Sueco", "Zueco", "Zuecos"],
    },
    {
        "tipo": "Zapatillas",
        "categoria": "Calzado",
        "sitios": {"columbia": "Zapatillas", "rockford": "Zapatillas", "hush_puppies": "Zapatillas", "vans": "Zapatillas"},
        "sinonimos": ["Sneaker", "Sneakers", "Tenis", "Zapatilla", "Zapatilla Deportiva"],
    },
    {
        "tipo": "Zapatos",
        "categoria": "Calzado",
        "sitios": {"rockford": "Zapatos", "hush_puppies": "Zapatos"},
        "sinonimos": ["Calzado Formal", "Shoe", "Shoes", "Zapato"],
    },
    {
        "tipo": "Blusas",
        "categoria": "Vestuario",
        "sitios": {"columbia": "Blusas", "rockford": "Blusas", "hush_puppies": "Blusas"},
        "sinonimos": ["Blouse", "Blusa"],
    },
    {
        "tipo": "Camisas",
        "categoria": "Vestuario",
        "sitios": {"columbia": "Camisas", "rockford": "Camisas", "hush_puppies": "Camisas", "vans": "Camisas"},
        "sinonimos": ["CAMISA M/L", "Camisa", "Camisa M/C", "Camisa Manga Corta", "Camisa Manga Larga", "Shirt", "Shirts"],
    },
    {
        "tipo": "Casacas",
        "categoria": "Vestuario",
        "sitios": {"columbia": "Casacas", "rockford": "Casacas", "hush_puppies": "Casacas", "vans": "Casacas"},
        "sinonimos": ["Campera", "Camperas", "Casaca", "Chamarra", "Chaqueta", "Chaquetas", "Jacket", "Jackets"],
    },
    {
        "tipo": "Chalecos",
        "categoria": "Vestuario",
        "sitios": {"columbia": "Chalecos", "rockford": "Chalecos", "hush_puppies": "Chalecos"},
        "sinonimos": ["Chaleco", "Chaleco Polar", "Chalecos Polares", "Vest", "Vests"],
    },
    {
        "tipo": "Chompas",
        "categoria": "Vestuario",
        "sitios": {"rockford": "Chompas", "hush_puppies": "Chompas"},
        "sinonimos": ["Chaleco Tejido", "Chompa", "Jersey", "Jerseys", "Pullover", "Pullovers", "SWEATER", "Sweaters"],
    },
    {
        "tipo": "Cortavientos",
        "categoria": "Vestuario",
        "sitios": {"columbia": "Cortavientos", "rockford": "Cortavientos"},
        "sinonimos": ["Cortaviento", "Rompeviento", "Windbreaker"],
    },
    {
        "tipo": "Enterizos",
        "categoria": "Vestuario",
        "sitios": {"columbia": "Enterizos", "hush_puppies": "Enterizos"},
        "sinonimos": ["Enterizo", "Jumpsuit", "Mameluco", "Mamelucos", "Overoles"],
    },
    {
        "tipo": "Faldas",
        "categoria": "Vestuario",
        "sitios": {"rockford": "Faldas", "hush_puppies": "Faldas", "vans": "Faldas"},
        "sinonimos": ["Falda", "Skirt", "Skirts"],
    },
    {
        "tipo": "Impermeables",
        "categoria": "Vestuario",
        "sitios": {"columbia": "Impermeables", "rockford": "Impermeables"},
        "sinonimos": ["Impermeable", "Raincoat", "Rompevientos"],
    },
    {
        "tipo": "Interiores Térmicos",
        "categoria": "Vestuario",
        "sitios": {"columbia": "Interiores Térmicos", "rockford": "Interiores Térmicos"},
        "sinonimos": ["Base Layer", "Interior Termico", "Interiores Termicos", "Primera Capa", "Termico", "Termicos"],
    },
    {
        "tipo": "Jeans",
        "categoria": "Vestuario",
        "sitios": {"rockford": "Jeans", "hush_puppies": "Jeans"},
        "sinonimos": ["Denim", "Jean", "Pantalon Jean"],
    },
    {
        "tipo": "Leggings",
        "categoria": "Vestuario",
        "sitios": {"columbia": "Leggings", "rockford": "Leggings"},
        "sinonimos": ["Calza", "Calzas", "Legging", "Licra", "Licras"],
    },
    {
        "tipo": "Overol",
        "categoria": "Vestuario",
        "sitios": {"hush_puppies": "Jardineras"},
        "sinonimos": ["Jardinera", "Jardineras", "Peto", "Petos"],
    },
    {
        "tipo": "Pantalones",
        "categoria": "Vestuario",
        "sitios": {"columbia": "Pantalones", "rockford": "Pantalones", "hush_puppies": "Pantalones", "vans": "Pantalones"},
        "sinonimos": ["Pant", "Pantalon", "Pantalones Largos", "Pants", "Trouser", "Trousers"],
    },
    {
        "tipo": "Polares",
        "categoria": "Vestuario",
        "sitios": {"columbia": "Polares", "rockford": "Polares", "hush_puppies": "Polares"},
        "sinonimos": ["Fleece", "Fleeces", "Polar"],
    },
    {
        "tipo": "Polerones",
        "categoria": "Vestuario",
        "sitios": {"columbia": "Polerones", "rockford": "Polerones", "hush_puppies": "Polerones", "vans": "Polerones"},
        "sinonimos": ["Buzo", "Buzos", "Hoodie", "Hoodies", "Poleron", "Sudadera", "Sudaderas"],
    },
    {
        "tipo": "Polos",
        "categoria": "Vestuario",
        "sitios": {"columbia": "Polos", "rockford": "Polos", "hush_puppies": "Polos", "vans": "Polos"},
        "sinonimos": ["Camiseta", "Camisetas", "Polera", "Poleras", "Polo", "Polo Manga Corta", "Polo Manga Larga", "Remera", "Remeras", "T-Shirt"],
    },
    {
        "tipo": "Ropas De Baños",
        "categoria": "Vestuario",
        "sitios": {"columbia": "Ropas De Baños", "rockford": "Ropas De Baños", "hush_puppies": "Ropas De Baños", "vans": "Ropas De Baños"},
        "sinonimos": ["Bikini", "Bikinis", "Malla", "Mallas", "Ropa de Bano", "Ropas De Banos", "Ropas de Bano", "Short De Bano", "Swimwear", "Traje De Bano", "Trajes De Bano"],
    },
    {
        "tipo": "Shorts",
        "categoria": "Vestuario",
        "sitios": {"columbia": "Shorts", "rockford": "Shorts", "hush_puppies": "Shorts", "vans": "Shorts"},
        "sinonimos": ["Bermuda", "Bermudas", "Pantaloneta", "Pantalonetas", "Short"],
    },
    {
        "tipo": "Vestidos",
        "categoria": "Vestuario",
        "sitios": {"rockford": "Vestidos", "hush_puppies": "Vestidos"},
        "sinonimos": ["Dress", "Dresses", "Vestido"],
    },
]


def _texto(valor):
    if valor is None:
        return ""
    if isinstance(valor, float) and valor != valor:
        return ""
    return str(valor).strip()


def clave(valor):
    """Forma de busqueda: sin mayusculas, tildes, espacios ni guiones."""
    texto = unicodedata.normalize("NFKD", _texto(valor))
    texto = "".join(c for c in texto if not unicodedata.combining(c))
    return re.sub(r"[^a-z0-9]+", "", texto.casefold())


_INDICE = {}
for _t in TIPOS:
    for _n in [_t["tipo"]] + list(_t["sitios"].values()) + _t["sinonimos"]:
        _k = clave(_n)
        if _k and _k not in _INDICE:
            _INDICE[_k] = _t


def resolver(valor):
    """El tipo canonico completo, o None si no se reconoce.

    Devolver None es una respuesta valida: significa que hay que avisarlo en la
    validacion, no inventar un tipo.
    """
    return _INDICE.get(clave(valor))


def tipo_canonico(valor):
    regla = resolver(valor)
    return regla["tipo"] if regla else ""


def clase_de(valor):
    """Vestuario / Calzado / Accesorios. La clase se DERIVA del tipo."""
    regla = resolver(valor)
    return regla["categoria"] if regla else ""


def tipo_para_sitio(valor, sitio):
    """Como se escribe ese tipo en ese sitio.

    Si el sitio no vende esa prenda devuelve "": no se fuerza un nombre que
    esa tienda no usa. Sin sitio, o con un sitio desconocido, devuelve el
    canonico.
    """
    regla = resolver(valor)
    if not regla:
        return ""
    sitio = _texto(sitio).casefold().replace(" ", "_")
    if not sitio:
        return regla["tipo"]
    if sitio not in {s for t in TIPOS for s in t["sitios"]}:
        return regla["tipo"]
    return regla["sitios"].get(sitio, "")


def aplica_a_sitio(valor, sitio):
    regla = resolver(valor)
    if not regla:
        return False
    return _texto(sitio).casefold().replace(" ", "_") in regla["sitios"]


def tipos_de_sitio(sitio):
    """Todos los tipos que vende ese sitio, con el nombre que usa."""
    sitio = _texto(sitio).casefold().replace(" ", "_")
    return sorted(t["sitios"][sitio] for t in TIPOS if sitio in t["sitios"])


def sinonimos_de(valor):
    regla = resolver(valor)
    return list(regla["sinonimos"]) if regla else []
