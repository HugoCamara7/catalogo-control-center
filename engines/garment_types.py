"""Diccionario maestro de tipos de prenda, por sitio.

Sin dependencias de Streamlit ni de pandas.

GENERADO desde "Tipo de Prendas Actualizado Diccionario - Corregido.xlsx"
(hoja "2 TIPOS"), agosto 2026. Es la fuente de verdad que confirmo el usuario.

Es el UNICO diccionario de tipos. `catalog_rules.PRODUCT_TYPE_RULES` se arma a
partir de esta lista (septiembre 2026): antes eran dos tablas escritas a mano
que se habian separado en 186 nombres y se contradecian en diez prendas -- para
`catalog_rules` un "buzo" era un pantalon y aqui es un poleron; una "falda" era
un short y aqui es una falda. Dos diccionarios del mismo dato se separan sin que
nadie lo note, como las dos `normalize_size`.

Que resuelve
------------
1. **El tipo canonico** a partir de como lo escriba quien sea. 460+ sinonimos.
2. **La clase** (Vestuario / Calzado / Accesorios) derivada del tipo.
3. **El nombre que le toca a cada sitio**, que NO siempre es el canonico:
   una misma prenda puede llamarse distinto en Columbia y en Vans.
4. **El grupo de guia de tallas** (TOPS / BOTTOMS) y si la prenda **admite
   talla unica**. Los dos vivian solo en `catalog_rules`, y por eso Sweater,
   Jean, Enterizo y Chaleco Polar se quedaron sin grupo en el lote de agosto:
   sin grupo, las guias de TOPS y BOTTOMS empatan en prioridad 95 y la elegida
   depende del orden de la lista, no del producto.

Un tipo que no aplica a un sitio no aparece en su diccionario "sitios". Eso es
informacion, no un hueco: significa que ese sitio no vende esa prenda.
Patagonia.pe y Supermall.pe no declaran ninguno todavia, asi que reciben el
nombre canonico -- que es lo correcto mientras nadie confirme sus nombres.

Reglas al generar
-----------------
- Ningun nombre puede apuntar a dos tipos. Lo comprueba `conflictos()`, y hay
  una prueba que falla si devuelve algo: el indice es "gana el primero", asi
  que un choque no revienta, simplemente manda uno de los dos y nadie se
  entera.
- El tipo canonico va en PLURAL y `singular` es la forma corta. Donde el tipo
  ya existia en `catalog_rules` el singular es exactamente el que esa tabla
  emitia, para no cambiar una etiqueta que ya esta en uso.
- `grupo_talla` solo lo lleva Vestuario; `talla_unica` solo lo admiten los
  Accesorios. Las dos invariantes se comprueban en las pruebas.
- La busqueda ignora mayusculas, tildes, espacios y guiones.

Lo que NO esta y es a proposito: "calzado" y "footwear" NO resuelven a
Zapatilla. Son la CLASE, no el tipo, y mapearlos convertia una sandalia
declarada como "calzado" en una zapatilla. Sin mapeo, la validacion lo avisa.
"""

import re
import unicodedata

TIPOS = [
    {
        "tipo": "Accesorios De Limpieza",
        "singular": "Accesorio De Limpieza",
        "categoria": "Accesorios",
        "grupo_talla": "",
        "talla_unica": True,
        "sitios": {"rockford": "Accesorios De Limpieza", "hush_puppies": "Accesorios De Limpieza"},
        "sinonimos": ["Accesorio De Limpieza", "Betun", "Cleaner", "Escobilla", "Escobilla Aplicadora", "Escobilla De Brillo", "Escobillas", "Escobillas Aplicadoras", "Escobillas De Brillo", "Impermeabilizante", "Kit De Limpieza", "Limpiador", "Limpiadores", "Protector Limpieza", "Protectores Limpieza", "Shampoo", "Shampoos"],
    },
    {
        "tipo": "Accesorios Para El Pelo",
        "singular": "Accesorio Para El Pelo",
        "categoria": "Accesorios",
        "grupo_talla": "",
        "talla_unica": True,
        "sitios": {"hush_puppies": "Accesorios Para El Pelo"},
        "sinonimos": ["Accesorio Para El Pelo", "Colet", "Colets", "Hair Accessories", "Ligas Para El Pelo", "Scrunchie", "Scrunchies", "Vincha", "Vinchas"],
    },
    {
        "tipo": "Bastones",
        "singular": "Baston",
        "categoria": "Accesorios",
        "grupo_talla": "",
        "talla_unica": True,
        "sitios": {"columbia": "Bastones", "rockford": "Bastones"},
        "sinonimos": ["Baston", "Baston De Trekking", "Bastones De Trekking", "Hiking Poles", "Poles", "Trekking Pole", "Trekking Poles"],
    },
    {
        "tipo": "Billeteras",
        "singular": "Billetera",
        "categoria": "Accesorios",
        "grupo_talla": "",
        "talla_unica": True,
        "sitios": {"rockford": "Billeteras", "hush_puppies": "Billeteras", "vans": "Billeteras"},
        "sinonimos": ["Billetera", "Card Holder", "Monedero", "Monederos", "Portadocumentos", "Tarjetero", "Tarjeteros", "Wallet", "Wallets"],
    },
    {
        "tipo": "Bolsos",
        "singular": "Bolso",
        "categoria": "Accesorios",
        "grupo_talla": "",
        "talla_unica": True,
        "sitios": {"columbia": "Bolsos", "vans": "Bolsos"},
        "sinonimos": ["Bag", "Bags", "Bandolera", "Bandoleras", "Bolsa", "Bolsas", "Bolso", "Bolso De Viaje", "Bolso Deportivo", "Crossbody", "Duffel", "Duffel Bag", "Duffle", "Tote", "Tote Bag"],
    },
    {
        "tipo": "Botellas",
        "singular": "Botella",
        "categoria": "Accesorios",
        "grupo_talla": "",
        "talla_unica": True,
        "sitios": {"columbia": "Botellas", "rockford": "Botellas"},
        "sinonimos": ["Botella", "Botella Termica", "Bottle", "Bottles", "Cantimplora", "Cantimploras", "Termo", "Termos", "Tomatodo", "Tomatodos"],
    },
    {
        "tipo": "Bufandas",
        "singular": "Bufanda",
        "categoria": "Accesorios",
        "grupo_talla": "",
        "talla_unica": True,
        "sitios": {"rockford": "Bufandas"},
        "sinonimos": ["Bufanda", "Chalina", "Chalinas", "Pashmina", "Pashminas", "Scarf", "Scarves"],
    },
    {
        "tipo": "Canguros",
        "singular": "Canguro",
        "categoria": "Accesorios",
        "grupo_talla": "",
        "talla_unica": True,
        "sitios": {"columbia": "Canguros", "rockford": "Canguros", "vans": "Canguros"},
        "sinonimos": ["Banano", "Bananos", "Canguro", "Fanny Pack", "Hip Pack", "Pochete", "Rinonera", "Rinoneras", "Waist Bag", "Waist Pack"],
    },
    {
        "tipo": "Carteras",
        "singular": "Cartera",
        "categoria": "Accesorios",
        "grupo_talla": "",
        "talla_unica": True,
        "sitios": {"rockford": "Carteras", "hush_puppies": "Carteras", "vans": "Carteras"},
        "sinonimos": ["Bolso Cartera", "Bolso De Mano", "Cartera", "Cartera De Mano", "Clutch", "Clutches", "Handbag", "Purse"],
    },
    {
        "tipo": "Cartucheras",
        "singular": "Cartuchera",
        "categoria": "Accesorios",
        "grupo_talla": "",
        "talla_unica": True,
        "sitios": {"hush_puppies": "Cartucheras"},
        "sinonimos": ["Cartuchera", "Estuche", "Estuche Escolar", "Estuches", "Pencil Case", "Portalapices"],
    },
    {
        "tipo": "Chullos",
        "singular": "Chullo",
        "categoria": "Accesorios",
        "grupo_talla": "",
        "talla_unica": True,
        "sitios": {"columbia": "Chullos", "rockford": "Beanies", "vans": "Beanie"},
        "sinonimos": ["Beanie", "Beanies", "Chullo", "Gorro Andino", "Gorro De Lana", "Gorro Peruano", "Gorros Andinos", "Knit Beanie", "Knit Hat"],
    },
    {
        "tipo": "Cinturones",
        "singular": "Cinturon",
        "categoria": "Accesorios",
        "grupo_talla": "",
        "talla_unica": True,
        "sitios": {"rockford": "Cinturones", "hush_puppies": "Cinturones", "vans": "Cinturones"},
        "sinonimos": ["Belt", "Belts", "Cinturon", "Correa", "Correas", "Faja", "Fajas", "Pretina", "Pretinas"],
    },
    {
        "tipo": "Coolers",
        "singular": "Cooler",
        "categoria": "Accesorios",
        "grupo_talla": "",
        "talla_unica": True,
        "sitios": {"columbia": "Coolers", "rockford": "Coolers"},
        "sinonimos": ["Caja Termica", "Conservadora", "Conservadoras", "Cooler", "Ice Chest", "Nevera Portatil"],
    },
    {
        "tipo": "Crema renovadora",
        "singular": "Crema renovadora",
        "categoria": "Accesorios",
        "grupo_talla": "",
        "talla_unica": True,
        "sitios": {"rockford": "Crema Renovadora"},
        "sinonimos": ["Cream Renov", "Cremas Renovadora", "Cremas Renovadoras", "Renovador", "Renovador De Cuero", "Renovadores"],
    },
    {
        "tipo": "Cuchillas",
        "singular": "Cuchilla",
        "categoria": "Accesorios",
        "grupo_talla": "",
        "talla_unica": True,
        "sitios": {"columbia": "Cuchillas", "rockford": "Cuchillas"},
        "sinonimos": ["Cuchilla", "Cuchillo", "Cuchillos", "Knife", "Multiherramienta", "Multitool", "Navaja", "Navajas"],
    },
    {
        "tipo": "Cuelleras",
        "singular": "Cuellera",
        "categoria": "Accesorios",
        "grupo_talla": "",
        "talla_unica": True,
        "sitios": {"columbia": "Cuelleras", "rockford": "Cuelleras"},
        "sinonimos": ["Buff", "Cuellera", "Cuello", "Cuellos", "Neck Gaiter", "Neckwarmer", "Tubular"],
    },
    {
        "tipo": "Fundas Para Latas",
        "singular": "Funda Para Lata",
        "categoria": "Accesorios",
        "grupo_talla": "",
        "talla_unica": True,
        "sitios": {"columbia": "Fundas Para Latas", "rockford": "Fundas Para Latas"},
        "sinonimos": ["Can Cooler", "Enfriador De Lata", "Funda Para Lata", "Fundas para Lata", "Koozie", "Portalata", "Portalatas"],
    },
    {
        "tipo": "Gorros",
        "singular": "Gorro",
        "categoria": "Accesorios",
        "grupo_talla": "",
        "talla_unica": True,
        "sitios": {"columbia": "Gorros", "rockford": "Gorros", "hush_puppies": "Gorros", "vans": "Gorros"},
        "sinonimos": ["Boina", "Boinas", "Bucket", "Bucket Hat", "Buckets", "Cap", "Caps", "Gorra", "Gorras", "Gorro", "Jockey", "Jockeys", "Snapback", "Trucker", "Visera", "Viseras"],
    },
    {
        "tipo": "Guantes",
        "singular": "Guante",
        "categoria": "Accesorios",
        "grupo_talla": "",
        "talla_unica": True,
        "sitios": {"columbia": "Guantes", "rockford": "Guantes"},
        "sinonimos": ["Glove", "Gloves", "Guante", "Manopla", "Manoplas", "Miton", "Mitones", "Mitten", "Mittens"],
    },
    {
        "tipo": "Lentes De Sol",
        "singular": "Lente De Sol",
        "categoria": "Accesorios",
        "grupo_talla": "",
        "talla_unica": True,
        "sitios": {"rockford": "Lentes De Sol", "vans": "Lentes De Sol"},
        "sinonimos": ["Anteojos", "Eyewear", "Gafa", "Gafas", "Gafas De Sol", "Lente", "Lente De Sol", "Lentes", "Sunglasses"],
    },
    {
        "tipo": "Maletines",
        "singular": "Maletin",
        "categoria": "Accesorios",
        "grupo_talla": "",
        "talla_unica": True,
        "sitios": {"columbia": "Maletines", "rockford": "Maletines", "hush_puppies": "Maletines"},
        "sinonimos": ["Briefcase", "Maleta", "Maletas", "Maletin", "Portafolio", "Portafolios"],
    },
    {
        "tipo": "Medias",
        "singular": "Media",
        "categoria": "Accesorios",
        "grupo_talla": "",
        "talla_unica": True,
        "sitios": {"columbia": "Medias", "rockford": "Medias", "hush_puppies": "Medias", "vans": "Medias"},
        "sinonimos": ["Calceta", "Calcetas", "Calcetin", "Calcetines", "Media", "Sock", "Socks"],
    },
    {
        "tipo": "Mochilas",
        "singular": "Mochila",
        "categoria": "Accesorios",
        "grupo_talla": "",
        "talla_unica": True,
        "sitios": {"columbia": "Mochilas", "rockford": "Mochilas", "hush_puppies": "Mochilas", "vans": "Mochilas"},
        "sinonimos": ["Backpack", "Backpacks", "Daypack", "Mochila", "Mochila De Trekking", "Morral", "Morrales"],
    },
    {
        "tipo": "Neceseres",
        "singular": "Neceser",
        "categoria": "Accesorios",
        "grupo_talla": "",
        "talla_unica": True,
        "sitios": {"columbia": "Neceseres", "rockford": "Neceseres"},
        "sinonimos": ["Bolso De Aseo", "Cosmetiquero", "Cosmetiqueros", "Neceser", "Toiletry", "Toiletry Bag"],
    },
    {
        "tipo": "Pasadores",
        "singular": "Pasador",
        "categoria": "Accesorios",
        "grupo_talla": "",
        "talla_unica": True,
        "sitios": {"vans": "Pasadores"},
        "sinonimos": ["Agujeta", "Agujetas", "Cordon", "Cordones", "Laces", "Pasador", "Shoelace", "Shoelaces"],
    },
    {
        "tipo": "Pasamontañas",
        "singular": "Pasamontaña",
        "categoria": "Accesorios",
        "grupo_talla": "",
        "talla_unica": True,
        "sitios": {"columbia": "Pasamontañas", "rockford": "Pasamontañas"},
        "sinonimos": ["Balaclava", "Balaclavas", "Pasamontana", "Pasamontanas"],
    },
    {
        "tipo": "Pañuelos",
        "singular": "Pañuelo",
        "categoria": "Accesorios",
        "grupo_talla": "",
        "talla_unica": True,
        "sitios": {"rockford": "Pañuelos"},
        "sinonimos": ["Bandana", "Bandanas", "Neckerchief", "Panuelo", "Panuelos"],
    },
    {
        "tipo": "Sombreros",
        "singular": "Sombrero",
        "categoria": "Accesorios",
        "grupo_talla": "",
        "talla_unica": True,
        "sitios": {"columbia": "Sombreros", "rockford": "Sombreros", "vans": "Sombreros"},
        "sinonimos": ["Hat", "Hats", "Panama", "Sombrero", "Sombrero De Ala", "Sun Hat"],
    },
    {
        "tipo": "Tazas",
        "singular": "Taza",
        "categoria": "Accesorios",
        "grupo_talla": "",
        "talla_unica": True,
        "sitios": {"columbia": "Tazas"},
        "sinonimos": ["Mug", "Mugs", "Taza", "Tumbler", "Vaso", "Vasos"],
    },
    {
        "tipo": "Alpargatas",
        "singular": "Alpargata",
        "categoria": "Calzado",
        "grupo_talla": "",
        "talla_unica": False,
        "sitios": {"rockford": "Alpargatas", "hush_puppies": "Alpargatas"},
        "sinonimos": ["Alpargata", "Alpargata De Yute", "Espadrille", "Espadrilles"],
    },
    {
        "tipo": "Ballerinas",
        "singular": "Ballerina",
        "categoria": "Calzado",
        "grupo_talla": "",
        "talla_unica": False,
        "sitios": {"hush_puppies": "Ballerinas"},
        "sinonimos": ["Balerina", "Balerinas", "Ballerina", "Flat", "Flats", "Guilleminas", "Guillermina", "Guillerminas"],
    },
    {
        "tipo": "Botas",
        "singular": "Bota",
        "categoria": "Calzado",
        "grupo_talla": "",
        "talla_unica": False,
        "sitios": {"columbia": "Botas", "rockford": "Botas", "hush_puppies": "Botas"},
        "sinonimos": ["Boots", "Bota", "Botas Altas", "Botas De Lluvia", "Rain Boot", "Snow Boot"],
    },
    {
        "tipo": "Botines",
        "singular": "Botin",
        "categoria": "Calzado",
        "grupo_talla": "",
        "talla_unica": False,
        "sitios": {"columbia": "Botines", "rockford": "Botines", "hush_puppies": "Botines"},
        "sinonimos": ["Ankle Boot", "Boot", "Bootie", "Booties", "Botin"],
    },
    {
        "tipo": "Mocasines",
        "singular": "Mocasin",
        "categoria": "Calzado",
        "grupo_talla": "",
        "talla_unica": False,
        "sitios": {"rockford": "Mocasines", "hush_puppies": "Mocasines"},
        "sinonimos": ["Loafer", "Loafers", "Mocasin", "Mocasin De Cuero"],
    },
    {
        "tipo": "Pantuflas",
        "singular": "Pantufla",
        "categoria": "Calzado",
        "grupo_talla": "",
        "talla_unica": False,
        "sitios": {"columbia": "Pantuflas", "rockford": "Pantuflas", "hush_puppies": "Pantuflas"},
        "sinonimos": ["Babucha", "Babuchas", "Pantufla", "Slipper", "Slippers"],
    },
    {
        "tipo": "Sandalias",
        "singular": "Sandalia",
        "categoria": "Calzado",
        "grupo_talla": "",
        "talla_unica": False,
        "sitios": {"columbia": "Sandalias", "rockford": "Sandalias", "hush_puppies": "Sandalias"},
        "sinonimos": ["Chala", "Chalas", "Chancla", "Chanclas", "Flip Flop", "Flip Flops", "Ojota", "Ojotas", "Sandal", "Sandalia", "Sandals"],
    },
    {
        "tipo": "Slip Ons",
        "singular": "Slip On",
        "categoria": "Calzado",
        "grupo_talla": "",
        "talla_unica": False,
        "sitios": {"rockford": "Slip Ons", "hush_puppies": "Slip Ons"},
        "sinonimos": ["Slip On"],
    },
    {
        "tipo": "Suecos",
        "singular": "Sueco",
        "categoria": "Calzado",
        "grupo_talla": "",
        "talla_unica": False,
        "sitios": {"rockford": "Suecos", "hush_puppies": "Suecos"},
        "sinonimos": ["Clog", "Clogs", "Sueco", "Zueco", "Zuecos"],
    },
    {
        "tipo": "Zapatillas",
        "singular": "Zapatilla",
        "categoria": "Calzado",
        "grupo_talla": "",
        "talla_unica": False,
        "sitios": {"columbia": "Zapatillas", "rockford": "Zapatillas", "hush_puppies": "Zapatillas", "vans": "Zapatillas"},
        "sinonimos": ["Running", "Sneaker", "Sneakers", "Tenis", "Trainer", "Trainers", "Zapatilla", "Zapatilla Deportiva", "Zapatilla Urbana"],
    },
    {
        "tipo": "Zapatos",
        "singular": "Zapato",
        "categoria": "Calzado",
        "grupo_talla": "",
        "talla_unica": False,
        "sitios": {"rockford": "Zapatos", "hush_puppies": "Zapatos"},
        "sinonimos": ["Calzado Formal", "Derby", "Oxford", "Shoe", "Shoes", "Zapato", "Zapato De Vestir"],
    },
    {
        "tipo": "Blusas",
        "singular": "Blusa",
        "categoria": "Vestuario",
        "grupo_talla": "TOPS",
        "talla_unica": False,
        "sitios": {"columbia": "Blusas", "rockford": "Blusas", "hush_puppies": "Blusas"},
        "sinonimos": ["Blouse", "Blusa", "Camisola", "Camisolas"],
    },
    {
        "tipo": "Camisas",
        "singular": "Camisa",
        "categoria": "Vestuario",
        "grupo_talla": "TOPS",
        "talla_unica": False,
        "sitios": {"columbia": "Camisas", "rockford": "Camisas", "hush_puppies": "Camisas", "vans": "Camisas"},
        "sinonimos": ["Camisa", "Camisa De Vestir", "Camisa M/C", "CAMISA M/L", "Camisa Manga Corta", "Camisa Manga Larga", "Shirt", "Shirts"],
    },
    {
        "tipo": "Casacas",
        "singular": "Casaca",
        "categoria": "Vestuario",
        "grupo_talla": "TOPS",
        "talla_unica": False,
        "sitios": {"columbia": "Casacas", "rockford": "Casacas", "hush_puppies": "Casacas", "vans": "Casacas"},
        "sinonimos": ["Anorak", "Anoraks", "Campera", "Camperas", "Casaca", "Chamarra", "Chaqueta", "Chaquetas", "Jacket", "Jackets", "Parka", "Parkas", "Plumon", "Plumones", "Puffer"],
    },
    {
        "tipo": "Chalecos",
        "singular": "Chaleco",
        "categoria": "Vestuario",
        "grupo_talla": "TOPS",
        "talla_unica": False,
        "sitios": {"columbia": "Chalecos", "rockford": "Chalecos", "hush_puppies": "Chalecos"},
        "sinonimos": ["Chaleco", "Chaleco Polar", "Chalecos Polares", "Gilet", "Vest", "Vests"],
    },
    {
        "tipo": "Chompas",
        "singular": "Chompa",
        "categoria": "Vestuario",
        "grupo_talla": "TOPS",
        "talla_unica": False,
        "sitios": {"rockford": "Chompas", "hush_puppies": "Chompas"},
        "sinonimos": ["Cardigan", "Cardigans", "Chaleco Tejido", "Chompa", "Chompa De Lana", "Jersey", "Jerseys", "Knit", "Pullover", "Pullovers", "SWEATER", "Sweaters"],
    },
    {
        "tipo": "Cortavientos",
        "singular": "Cortaviento",
        "categoria": "Vestuario",
        "grupo_talla": "TOPS",
        "talla_unica": False,
        "sitios": {"columbia": "Cortavientos", "rockford": "Cortavientos"},
        "sinonimos": ["Cortaviento", "Rompeviento", "Windbreaker", "Windbreakers"],
    },
    {
        "tipo": "Enterizos",
        "singular": "Enterizo",
        "categoria": "Vestuario",
        "grupo_talla": "TOPS",
        "talla_unica": False,
        "sitios": {"columbia": "Enterizos", "hush_puppies": "Enterizos"},
        "sinonimos": ["Enterito", "Enteritos", "Enterizo", "Jumpsuit", "Jumpsuits", "Mameluco", "Mamelucos", "Romper", "Rompers"],
    },
    {
        "tipo": "Faldas",
        "singular": "Falda",
        "categoria": "Vestuario",
        "grupo_talla": "BOTTOMS",
        "talla_unica": False,
        "sitios": {"rockford": "Faldas", "hush_puppies": "Faldas", "vans": "Faldas"},
        "sinonimos": ["Falda", "Pollera", "Polleras", "Skirt", "Skirts"],
    },
    {
        "tipo": "Impermeables",
        "singular": "Impermeable",
        "categoria": "Vestuario",
        "grupo_talla": "TOPS",
        "talla_unica": False,
        "sitios": {"columbia": "Impermeables", "rockford": "Impermeables"},
        "sinonimos": ["Cortalluvia", "Impermeable", "Rain Jacket", "Raincoat", "Raincoats", "Rompevientos"],
    },
    {
        "tipo": "Interiores Térmicos",
        "singular": "Interior Termico",
        "categoria": "Vestuario",
        "grupo_talla": "TOPS",
        "talla_unica": False,
        "sitios": {"columbia": "Interiores Térmicos", "rockford": "Interiores Térmicos"},
        "sinonimos": ["Base Layer", "Base Layers", "Interior Termico", "Interiores Termicos", "Primera Capa", "Segunda Piel", "Termico", "Termicos"],
    },
    {
        "tipo": "Jeans",
        "singular": "Jean",
        "categoria": "Vestuario",
        "grupo_talla": "BOTTOMS",
        "talla_unica": False,
        "sitios": {"rockford": "Jeans", "hush_puppies": "Jeans"},
        "sinonimos": ["Denim", "Jean", "Pantalon Jean", "Pitillo"],
    },
    {
        "tipo": "Leggings",
        "singular": "Legging",
        "categoria": "Vestuario",
        "grupo_talla": "BOTTOMS",
        "talla_unica": False,
        "sitios": {"columbia": "Leggings", "rockford": "Leggings"},
        "sinonimos": ["Calza", "Calza Larga", "Calzas", "Legging", "Legins", "Licra", "Licras", "Tights"],
    },
    {
        "tipo": "Overol",
        "singular": "Overol",
        "categoria": "Vestuario",
        "grupo_talla": "TOPS",
        "talla_unica": False,
        "sitios": {"hush_puppies": "Jardineras"},
        "sinonimos": ["Jardinera", "Jardineras", "Overall", "Overalls", "Overoles", "Peto", "Petos"],
    },
    {
        "tipo": "Pantalones",
        "singular": "Pantalon",
        "categoria": "Vestuario",
        "grupo_talla": "BOTTOMS",
        "talla_unica": False,
        "sitios": {"columbia": "Pantalones", "rockford": "Pantalones", "hush_puppies": "Pantalones", "vans": "Pantalones"},
        "sinonimos": ["Cargo", "Chino", "Chinos", "Jogger", "Joggers", "Pant", "Pantalon", "Pantalon Cargo", "Pantalones Largos", "Pants", "Trouser", "Trousers"],
    },
    {
        "tipo": "Polares",
        "singular": "Polar",
        "categoria": "Vestuario",
        "grupo_talla": "TOPS",
        "talla_unica": False,
        "sitios": {"columbia": "Polares", "rockford": "Polares", "hush_puppies": "Polares"},
        "sinonimos": ["Fleece", "Fleeces", "Microfleece", "Micropolar", "Micropolares", "Polar", "Polar Jacket"],
    },
    {
        "tipo": "Polerones",
        "singular": "Poleron",
        "categoria": "Vestuario",
        "grupo_talla": "TOPS",
        "talla_unica": False,
        "sitios": {"columbia": "Polerones", "rockford": "Polerones", "hush_puppies": "Polerones", "vans": "Polerones"},
        "sinonimos": ["Buzo", "Buzos", "Hoodie", "Hoodies", "Hoody", "Hoodys", "Poleron", "Sudadera", "Sudaderas", "Sweatshirt", "Sweatshirts"],
    },
    {
        "tipo": "Polos",
        "singular": "Polo",
        "categoria": "Vestuario",
        "grupo_talla": "TOPS",
        "talla_unica": False,
        "sitios": {"columbia": "Polos", "rockford": "Polos", "hush_puppies": "Polos", "vans": "Polos"},
        "sinonimos": ["Camiseta", "Camiseta Manga Corta", "Camisetas", "Polera", "Poleras", "Polo", "Polo Box", "Polo Manga Corta", "Polo Manga Larga", "Remera", "Remeras", "T-Shirt", "Tee", "Tees"],
    },
    {
        "tipo": "Ropas De Baños",
        "singular": "Ropa De Baño",
        "categoria": "Vestuario",
        "grupo_talla": "BOTTOMS",
        "talla_unica": False,
        "sitios": {"columbia": "Ropas De Baños", "rockford": "Ropas De Baños", "hush_puppies": "Ropas De Baños", "vans": "Ropas De Baños"},
        "sinonimos": ["Banador", "Bikini", "Bikinis", "Boardshort", "Boardshorts", "Malla", "Mallas", "Ropa de Bano", "Ropas de Bano", "Ropas De Banos", "Short De Bano", "Swimwear", "Traje De Bano", "Trajes De Bano"],
    },
    {
        "tipo": "Shorts",
        "singular": "Short",
        "categoria": "Vestuario",
        "grupo_talla": "BOTTOMS",
        "talla_unica": False,
        "sitios": {"columbia": "Shorts", "rockford": "Shorts", "hush_puppies": "Shorts", "vans": "Shorts"},
        "sinonimos": ["Bermuda", "Bermudas", "Pantaloneta", "Pantalonetas", "Short", "Short Deportivo"],
    },
    {
        "tipo": "Vestidos",
        "singular": "Vestido",
        "categoria": "Vestuario",
        "grupo_talla": "TOPS",
        "talla_unica": False,
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


def nombres_de(regla):
    """Todas las formas de escribir ese tipo: canonico, singular, por sitio y
    sinonimos. Es lo que se indexa, y lo que mira `conflictos()`."""
    return [regla["tipo"], regla["singular"], *regla["sitios"].values(), *regla["sinonimos"]]


def conflictos():
    """Nombres que apuntan a dos tipos distintos. Vacio es la unica respuesta
    valida: el indice es "gana el primero", asi que un choque no falla, manda
    uno de los dos en silencio."""
    duenio, choques = {}, []
    for regla in TIPOS:
        for nombre in nombres_de(regla):
            k = clave(nombre)
            if not k:
                continue
            if k in duenio and duenio[k] != regla["tipo"]:
                choques.append((nombre, duenio[k], regla["tipo"]))
            duenio[k] = regla["tipo"]
    return choques


_INDICE = {}
for _t in TIPOS:
    for _n in nombres_de(_t):
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


def singular_de(valor):
    """La forma corta del tipo. Es la que `catalog_rules` emite como
    `normalized`."""
    regla = resolver(valor)
    return regla["singular"] if regla else ""


def clase_de(valor):
    """Vestuario / Calzado / Accesorios. La clase se DERIVA del tipo."""
    regla = resolver(valor)
    return regla["categoria"] if regla else ""


def grupo_talla_de(valor):
    """TOPS / BOTTOMS para vestuario; "" para calzado y accesorios, que no
    usan grupo."""
    regla = resolver(valor)
    return regla["grupo_talla"] if regla else ""


def admite_talla_unica(valor):
    regla = resolver(valor)
    return bool(regla and regla["talla_unica"])


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


def tipos_de_clase(categoria):
    """Los tipos de una clase, en orden alfabetico."""
    k = clave(categoria)
    return sorted(t["tipo"] for t in TIPOS if clave(t["categoria"]) == k)
