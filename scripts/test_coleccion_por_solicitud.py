"""Los codigos se encuentran, y cada solicitud deja su coleccion en sus sitios.

Ejecutar:  python scripts/test_coleccion_por_solicitud.py

Dos pedidos del usuario, en la misma conversacion:

1. "en mi carga de colecciones me ayudes a poner los codigos igual, me sale que
   no puede mapearlos y es raro" -- con una captura del admin de Shopify
   buscando `29206-GID` y ENCONTRANDO el producto, mientras la app lo reportaba
   como "No esta en el catalogo de esta tienda".
2. "Necesito que cada ticket pueda crear su coleccion porfavor en los sitios
   donde corresponde".

Las pruebas EJECUTAN -- emparejan contra catalogos de verdad, escriben contra un
Shopify falso y entran a la app con `AppTest` -- en vez de leer el codigo. Es la
leccion de `start_suelto`: leer el codigo no es ejecutarlo.
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import app_matrixify as app  # noqa: E402
import shopify_api  # noqa: E402
from engines import coleccion_de_carga as coleccion  # noqa: E402
from engines import colecciones_admin as motor  # noqa: E402

CONFIG = {"shop_domain": "tienda-falsa.myshopify.com", "admin_access_token": "shpat_falso",
          "api_version": "2026-04"}


def producto(identificador, handle, titulo="", mod_col="", tags="", skus=()):
    """Un producto como lo devuelve `shopify_api.fetch_products`."""
    return {
        "Product ID": "gid://shopify/Product/%s" % identificador,
        "Handle": handle,
        "Title": titulo,
        "Mod-Col": mod_col,
        "Tags": tags,
        "Variants": [{"Variant SKU": sku} for sku in skus],
    }


def items(*codigos):
    return [{"fila": numero, "codigo": codigo, "orden": numero}
            for numero, codigo in enumerate(codigos, start=2)]


# =========================================================================
# 1. EL FALLO REPORTADO: el codigo esta en la tienda y la app decia que no
# =========================================================================
class TestElCodigoSeEncuentra(unittest.TestCase):
    """El metacampo `custom.codigo_modelo_color` solo lo tienen los productos
    que creo esta app. En los de antes el codigo esta en los TAGS o dentro del
    handle, y buscando solo por metacampo y handle exacto se reportaban como
    inexistentes: 40 de 252 en la carga real de Patagonia.pe."""

    # El producto de la captura: el usuario lo encontro en el admin buscando
    # 29206-GID y la app decia que no estaba.
    CHULLO = producto(
        "1", "chullo-patagonia-brodeo-beanie", "Chullo Patagonia Brodeo Beanie",
        tags="Unisex, Accesorios, Chullos, Patagonia, 29206-Gid, Negro")
    # Sin metacampo, pero con el codigo dentro del handle.
    POLAR = producto(
        "2", "polar-mujer-patagonia-daily-snap-t-pullover-20265-ike-negro",
        "Polar Mujer Patagonia Daily Snap-T Pullover")
    # Con metacampo: este se encontraba ya antes.
    RETRO = producto("3", "polar-classic-retrox-23057-ilo",
                     "Polar Hombre Patagonia Classic Retro-X", mod_col="23057-ILO")

    def informe(self, catalogo, *codigos, **kwargs):
        return motor.validar_asignacion(items(*codigos),
                                        motor.indice_de_catalogo(catalogo), **kwargs)

    def test_el_codigo_en_un_TAG_lo_encuentra(self):
        informe = self.informe([self.CHULLO], "29206-GID")
        self.assertEqual(informe["no_encontrados"], [])
        self.assertEqual(informe["listos"][0]["fuente"], "tag")

    def test_el_codigo_DENTRO_del_handle_lo_encuentra(self):
        """El handle se arma `nombre-genero-modcol-color`, asi que el codigo
        esta partido en dos piezas: `...-20265-ike-negro`."""
        informe = self.informe([self.POLAR], "20265-IKE")
        self.assertEqual(informe["no_encontrados"], [])
        self.assertEqual(informe["listos"][0]["fuente"], "texto")

    def test_el_codigo_en_el_SKU_lo_encuentra(self):
        uno = producto("9", "algo", "Algo", skus=("AB123-XY",))
        informe = self.informe([uno], "AB123-XY")
        self.assertEqual(informe["listos"][0]["fuente"], "sku")

    def test_los_tres_juntos_no_dejan_ninguno_fuera(self):
        informe = self.informe([self.CHULLO, self.POLAR, self.RETRO],
                               "29206-GID", "20265-IKE", "23057-ILO")
        self.assertEqual([f["codigo"] for f in informe["listos"]],
                         ["29206-GID", "20265-IKE", "23057-ILO"])
        self.assertEqual(informe["no_encontrados"], [])

    def test_el_METACAMPO_manda_sobre_las_demas_fuentes(self):
        """Si un producto lo tiene en el metacampo y otros tres lo mencionan en
        un tag, NO es ambiguo: gana el metacampo. Resolver todo en el mismo saco
        convertiria un acierto en una ambiguedad y bloquearia la carga."""
        ruido = [producto(str(10 + n), "otro-%d" % n, "Otro", tags="23057-ILO")
                 for n in range(3)]
        informe = self.informe([self.RETRO] + ruido, "23057-ILO")
        self.assertEqual(informe["ambiguos"], [])
        self.assertEqual(informe["listos"][0]["fuente"], "codigo")
        self.assertEqual(informe["listos"][0]["handle"], self.RETRO["Handle"])

    def test_el_orden_del_archivo_se_conserva(self):
        """Un informe que se reordena solo no se puede comparar con el anterior."""
        informe = self.informe([self.RETRO, self.POLAR, self.CHULLO],
                               "29206-GID", "23057-ILO", "20265-IKE")
        self.assertEqual([f["codigo"] for f in informe["listos"]],
                         ["29206-GID", "23057-ILO", "20265-IKE"])

    def test_un_codigo_que_de_verdad_no_esta_sigue_saliendo_como_tal(self):
        informe = self.informe([self.RETRO], "99999-ZZZ")
        self.assertEqual(len(informe["no_encontrados"]), 1)
        self.assertTrue(informe["bloqueado"])

    def test_dos_productos_con_el_mismo_codigo_siguen_siendo_AMBIGUOS(self):
        """Elegir uno a dedo escribiria en el producto equivocado."""
        gemelo = producto("4", "otro-handle", "Otro", mod_col="23057-ILO")
        informe = self.informe([self.RETRO, gemelo], "23057-ILO")
        self.assertEqual(len(informe["ambiguos"]), 1)
        self.assertEqual(informe["listos"], [])

    def test_una_coincidencia_en_el_texto_ambigua_no_escribe_nada(self):
        otro = producto("5", "otra-cosa-20265-ike-azul", "Otra cosa")
        informe = self.informe([self.POLAR, otro], "20265-IKE")
        self.assertEqual(len(informe["ambiguos"]), 1)

    def test_con_guion_y_sin_guion_son_el_mismo_codigo(self):
        pegado = producto("6", "pegado", "Pegado", mod_col="29206GID")
        self.assertEqual(len(self.informe([pegado], "29206-GID")["listos"]), 1)
        self.assertEqual(len(self.informe([self.RETRO], "23057ILO")["listos"]), 1)

    def test_un_codigo_numerico_que_Excel_leyo_como_float(self):
        """Basta un hueco en la columna para que pandas la traiga en float, y
        `str(29206.0)` es "29206.0": ese `.0` no emparejaba con nada."""
        self.assertEqual(motor._codigo(29206.0), "29206")
        numerico = producto("7", "numerico", "Numerico", mod_col="29206")
        filas = [{"fila": 2, "codigo": motor._codigo(29206.0), "orden": None}]
        informe = motor.validar_asignacion(filas, motor.indice_de_catalogo([numerico]))
        self.assertEqual(len(informe["listos"]), 1)

    def test_un_codigo_CORTO_no_se_busca_dentro_del_texto(self):
        """`ABC` apareceria dentro de media tienda. Las cuatro fuentes exactas
        no tienen ese problema y siguen valiendo."""
        suelto = producto("8", "abc-chaqueta-hombre", "ABC Chaqueta")
        self.assertEqual(motor.validar_asignacion(
            items("ABC"), motor.indice_de_catalogo([suelto]))["listos"], [])

    def test_el_catalogo_se_recorre_UNA_vez_para_todos_los_sueltos(self):
        """Con 40 codigos sin resolver y 10.000 productos, una pasada por codigo
        serian 400.000 recorridos del mismo handle."""
        vistas = []

        class Espia(dict):
            def get(self, clave, por_defecto=None):
                if clave in ("Handle", "Title"):
                    vistas.append(clave)
                return dict.get(self, clave, por_defecto)

        catalogo = [Espia(producto(str(n), "handle-%d" % n, "Titulo %d" % n))
                    for n in range(5)]
        indice = motor.indice_de_catalogo(catalogo)
        del vistas[:]  # lo que se mide es la BUSQUEDA, no armar el indice
        motor.validar_asignacion(items("AAAAA-1", "BBBBB-2", "CCCCC-3"), indice)
        self.assertEqual(len(vistas), 10, "una pasada: 2 campos x 5 productos")

    def test_cada_fila_dice_POR_DONDE_se_emparejo(self):
        """Por el metacampo es seguro; por el texto del handle es una deduccion,
        y quien revisa tiene que poder distinguirlas."""
        informe = self.informe([self.CHULLO, self.RETRO], "29206-GID", "23057-ILO")
        self.assertEqual(informe["por_fuente"], {"tag": 1, "codigo": 1})
        self.assertEqual(informe["listos"][0]["emparejado_por"],
                         motor.ETIQUETA_DE_FUENTE["tag"])

    def test_lo_que_ya_esta_dentro_sigue_sin_volver_a_agregarse(self):
        informe = self.informe([self.RETRO], "23057-ILO", ya_en_coleccion=["23057-ILO"])
        self.assertEqual(informe["listos"], [])
        self.assertEqual(len(informe["ya_estaban"]), 1)


# =========================================================================
# 2. LA COLECCION ES LA MISMA, aunque cambie la fecha
# =========================================================================
class TestLaColeccionDeLaSolicitud(unittest.TestCase):

    def test_la_encuentra_aunque_se_cargara_otro_dia(self):
        """Quien revisa entra al dia siguiente. Emparejando por el handle
        completo se crearia una segunda con la mitad de los productos."""
        self.assertTrue(coleccion.es_de_la_solicitud(
            "carga-2026-09-20-patagonia-cat-0042", "CAT-0042"))

    def test_no_se_lleva_por_delante_una_coleccion_de_otro(self):
        """"Novedades CAT-0042" es de alguien, no nuestra: llenarla seria
        escribir donde nadie lo pidio."""
        self.assertFalse(coleccion.es_de_la_solicitud("novedades-cat-0042", "CAT-0042"))

    def test_una_solicitud_parecida_no_cuenta(self):
        self.assertFalse(coleccion.es_de_la_solicitud(
            "carga-2026-09-15-patagonia-cat-42", "CAT-0042"))
        self.assertFalse(coleccion.es_de_la_solicitud(
            "carga-2026-09-15-patagonia-cat-00420", "CAT-0042"))

    def test_sin_solicitud_no_empareja_con_nada(self):
        self.assertFalse(coleccion.es_de_la_solicitud("carga-2026-09-15-vans", ""))

    def test_elige_la_de_la_solicitud_entre_todas_las_de_la_tienda(self):
        encontrada = coleccion.coleccion_de_la_solicitud([
            {"handle": "novedades", "id": "1"},
            {"handle": "carga-2026-09-10-vans-cat-0041", "id": "2"},
            {"handle": "carga-2026-09-15-patagonia-cat-0042", "id": "3"},
        ], "CAT-0042")
        self.assertEqual(encontrada["id"], "3")


class TestLosSitiosDeLaSolicitud(unittest.TestCase):

    ETIQUETAS = {"columbia": "Columbia.pe", "rockford": "Rockford.pe", "vans": "Vans.pe"}

    def test_traduce_las_etiquetas_a_claves_de_sitio(self):
        claves, sin_resolver = coleccion.sitios_de_la_solicitud(
            {"sites": ["Columbia.pe", "Rockford.pe"]}, self.ETIQUETAS)
        self.assertEqual(claves, ["columbia", "rockford"])
        self.assertEqual(sin_resolver, [])

    def test_una_etiqueta_desconocida_se_DEVUELVE_no_se_ignora(self):
        """Una solicitud que pedia tres sitios y deja colecciones en dos se lee
        igual de bien que una que dejo las tres si nadie dice cual falto."""
        claves, sin_resolver = coleccion.sitios_de_la_solicitud(
            {"sites": ["Columbia.pe", "Tienda.pe"]}, self.ETIQUETAS)
        self.assertEqual(claves, ["columbia"])
        self.assertEqual(sin_resolver, ["Tienda.pe"])

    def test_no_se_repite_un_sitio(self):
        claves, _ = coleccion.sitios_de_la_solicitud(
            {"sites": ["Columbia.pe", "columbia", "COLUMBIA.PE"]}, self.ETIQUETAS)
        self.assertEqual(claves, ["columbia"])

    def test_los_sitios_de_la_solicitud_salen_de_SITE_CONFIGS(self):
        """Con una lista escrita a mano, un sitio nuevo no recibiria coleccion
        hasta que alguien se acordara de venir a este archivo."""
        etiquetas = {clave: app.clean_value(config.get("label"))
                     for clave, config in app.SITE_CONFIGS.items()}
        claves, sin_resolver = coleccion.sitios_de_la_solicitud(
            {"sites": [etiquetas["columbia"]]}, etiquetas)
        self.assertEqual(claves, ["columbia"])
        self.assertEqual(sin_resolver, [])


# =========================================================================
# 3. DE PUNTA A PUNTA: se crea de verdad en cada sitio
# =========================================================================
class TiendaFalsa:
    """Responde como Shopify y guarda lo que se le manda.

    El estado va **por dominio**: cada sitio es una tienda distinta, y con uno
    solo la coleccion creada en el primero aparecia en el segundo -- la prueba
    de "la crea en cada sitio" fallaba por el doble falso, no por la app.
    """

    def __init__(self, colecciones=(), dentro=(), falla=False):
        self.iniciales = [dict(c) for c in colecciones]
        self.dentro = list(dentro)
        self.falla = falla
        self.por_dominio = {}

    def tienda(self, dominio):
        return self.por_dominio.setdefault(dominio, {
            "colecciones": [dict(c) for c in self.iniciales],
            "creadas": [], "agregados": [], "publicadas": [],
        })

    # Atajos para el caso de un solo sitio, que es el normal en las pruebas.
    def _unica(self, campo):
        return [valor for tienda in self.por_dominio.values() for valor in tienda[campo]]

    creadas = property(lambda self: self._unica("creadas"))
    agregados = property(lambda self: self._unica("agregados"))
    publicadas = property(lambda self: self._unica("publicadas"))

    def __call__(self, shop_domain, token, query, variables=None, api_version=None,
                 timeout=20, max_retries=2):
        variables = variables or {}
        if self.falla:
            raise shopify_api.ShopifyApiError("la tienda dijo que no")
        tienda = self.tienda(shop_domain)
        if "CollectionsForCatalog" in query:
            return {"collections": {"pageInfo": {"hasNextPage": False},
                                    "nodes": [dict(c) for c in tienda["colecciones"]]}}
        if "CollectionProducts" in query:
            return {"collection": {"id": variables.get("id"), "handle": "x",
                                   "products": {"pageInfo": {"hasNextPage": False},
                                                "nodes": list(self.dentro)}}}
        if "collectionByHandle" in query or "collection(handle:" in query:
            for candidata in tienda["colecciones"]:
                if candidata.get("handle") == variables.get("handle"):
                    return {"collectionByHandle": dict(candidata)}
            return {"collectionByHandle": None}
        if "collectionCreate" in query:
            entrada = variables["entrada"]
            identificador = "gid://shopify/Collection/%s-%d" % (
                shop_domain.split(".")[0], len(tienda["creadas"]) + 1)
            tienda["creadas"].append(dict(entrada))
            tienda["colecciones"].append({"id": identificador, "handle": entrada.get("handle"),
                                          "title": entrada.get("title")})
            return {"collectionCreate": {
                "collection": {"id": identificador, "handle": entrada.get("handle"),
                               "title": entrada.get("title")},
                "userErrors": []}}
        if "collectionAddProductsV2" in query:
            tienda["agregados"].append(list(variables["productIds"]))
            return {"collectionAddProductsV2": {
                "job": {"id": "gid://shopify/Job/a", "done": True}, "userErrors": []}}
        if "job(id" in query:
            return {"job": {"id": variables["id"], "done": True}}
        if "publications(" in query:
            return {"publications": {"nodes": [
                {"id": "gid://shopify/Publication/1", "name": "Online Store"}]}}
        if "publishablePublish" in query:
            tienda["publicadas"].append(variables["id"])
            return {"publishablePublish": {"publishable": {"id": variables["id"]},
                                           "userErrors": []}}
        return {}


TICKET = {
    "code": "CAT-0042", "brand": "Patagonia", "created_at": "2026-09-15T10:00:00",
    "model_colors": ["29206-GID", "20265-IKE", "23057-ILO"],
    "sites": ["Columbia.pe"],
}

CATALOGO = {
    "columbia": [TestElCodigoSeEncuentra.CHULLO, TestElCodigoSeEncuentra.POLAR,
                 TestElCodigoSeEncuentra.RETRO],
    "rockford": [TestElCodigoSeEncuentra.RETRO],
    "vans": [],
}


class DePuntaAPunta(unittest.TestCase):

    def setUp(self):
        self._graphql = shopify_api.graphql_request
        self._sleep = shopify_api.time.sleep
        self._config = app.get_shopify_config
        self._catalogo = app.leer_catalogo_del_sitio
        shopify_api.time.sleep = lambda _s: None
        # Cada sitio es una TIENDA distinta, con su dominio: con un solo
        # dominio la coleccion creada en el primero aparecia en el segundo.
        app.get_shopify_config = lambda site_key: dict(
            CONFIG, site_key=site_key, shop_domain="%s.myshopify.com" % site_key)
        app.leer_catalogo_del_sitio = (
            lambda site_key, config, force_refresh=False, aviso=None: CATALOGO.get(site_key, []))

    def tearDown(self):
        shopify_api.graphql_request = self._graphql
        shopify_api.time.sleep = self._sleep
        app.get_shopify_config = self._config
        app.leer_catalogo_del_sitio = self._catalogo

    def usar(self, tienda):
        self.tienda = tienda
        shopify_api.graphql_request = tienda
        return tienda

    def test_crea_la_coleccion_con_los_productos_de_la_solicitud(self):
        tienda = self.usar(TiendaFalsa())
        partes = app.crear_coleccion_de_solicitud(TICKET, ["columbia"])
        self.assertEqual(partes[0]["estado"], "ok")
        self.assertEqual(tienda.creadas[0]["title"], "Carga 2026-09-15 · Patagonia · CAT-0042")
        self.assertEqual(tienda.creadas[0]["sortOrder"], motor.ORDEN_MANUAL)
        self.assertEqual(len(tienda.agregados[0]), 3)
        self.assertEqual(partes[0]["agregados"], 3)
        self.assertTrue(tienda.publicadas, "sin publicar no la ve nadie")

    def test_entran_los_tres_aunque_dos_no_tengan_el_metacampo(self):
        """Es el fallo reportado, visto desde la coleccion de la solicitud."""
        tienda = self.usar(TiendaFalsa())
        app.crear_coleccion_de_solicitud(TICKET, ["columbia"])
        self.assertEqual(sorted(tienda.agregados[0]), sorted(
            p["Product ID"] for p in CATALOGO["columbia"]))

    def test_la_crea_en_CADA_sitio_que_se_le_pide(self):
        tienda = self.usar(TiendaFalsa())
        partes = app.crear_coleccion_de_solicitud(TICKET, ["columbia", "rockford"])
        self.assertEqual([p["sitio"] for p in partes], ["columbia", "rockford"])
        self.assertEqual([p["estado"] for p in partes], ["ok", "ok"])
        self.assertEqual(len(tienda.creadas), 2)

    def test_un_codigo_que_no_esta_en_ese_sitio_NO_bloquea_pero_se_dice(self):
        """La solicitud pidio tres sitios y puede haberse cargado en dos: se
        agrega lo que hay y se nombra lo que falta."""
        self.usar(TiendaFalsa())
        parte = app.crear_coleccion_de_solicitud(TICKET, ["rockford"])[0]
        self.assertEqual(parte["estado"], "ok")
        self.assertEqual(parte["agregados"], 1)
        self.assertEqual(parte["no_encontrados"], 2)
        self.assertEqual(sorted(parte["faltan"]), ["20265-IKE", "29206-GID"])

    def test_NO_crea_una_coleccion_vacia(self):
        """Deja basura en la tienda que despues hay que borrar a mano."""
        tienda = self.usar(TiendaFalsa())
        parte = app.crear_coleccion_de_solicitud(TICKET, ["vans"])[0]
        self.assertEqual(parte["estado"], "sin productos")
        self.assertEqual(tienda.creadas, [])

    def test_REUSA_la_coleccion_de_la_solicitud_aunque_sea_de_otra_fecha(self):
        """Dos colecciones de la misma solicitud, con la mitad de los productos
        cada una, es peor que ninguna."""
        tienda = self.usar(TiendaFalsa(colecciones=[
            {"id": "gid://shopify/Collection/99", "handle": "carga-2026-09-10-patagonia-cat-0042",
             "title": "Carga 2026-09-10 · Patagonia · CAT-0042"}]))
        parte = app.crear_coleccion_de_solicitud(TICKET, ["columbia"])[0]
        self.assertEqual(tienda.creadas, [], "no se crea una segunda")
        self.assertTrue(parte["reusada"])
        self.assertEqual(parte["id"], "gid://shopify/Collection/99")

    def test_lo_que_ya_estaba_dentro_no_se_vuelve_a_agregar(self):
        tienda = self.usar(TiendaFalsa(
            colecciones=[{"id": "gid://shopify/Collection/99",
                          "handle": "carga-2026-09-15-patagonia-cat-0042",
                          "title": "Carga 2026-09-15 · Patagonia · CAT-0042"}],
            dentro=[{"id": TestElCodigoSeEncuentra.RETRO["Product ID"],
                     "handle": TestElCodigoSeEncuentra.RETRO["Handle"],
                     "title": "x", "codigoModeloColor": {"value": "23057-ILO"}}]))
        parte = app.crear_coleccion_de_solicitud(TICKET, ["columbia"])[0]
        self.assertEqual(parte["ya_estaban"], 1)
        self.assertEqual(parte["agregados"], 2)
        self.assertNotIn(TestElCodigoSeEncuentra.RETRO["Product ID"], tienda.agregados[0])

    def test_un_sitio_que_falla_no_detiene_a_los_demas(self):
        """Cortar en seco deja sin saber que alcanzo a hacerse."""
        tienda = self.usar(TiendaFalsa())
        llamadas = {"n": 0}
        real = tienda.__call__

        def alternar(shop_domain, token, query, variables=None, **kwargs):
            if "CollectionsForCatalog" in query:
                llamadas["n"] += 1
                if llamadas["n"] == 1:
                    raise shopify_api.ShopifyApiError("token vencido")
            return real(shop_domain, token, query, variables, **kwargs)

        shopify_api.graphql_request = alternar
        partes = app.crear_coleccion_de_solicitud(TICKET, ["columbia", "rockford"])
        self.assertEqual(partes[0]["estado"], "error")
        self.assertIn("token vencido", partes[0]["detalle"])
        self.assertEqual(partes[1]["estado"], "ok")

    def test_nunca_levanta(self):
        """Un fallo aqui no puede tumbar la pantalla de la solicitud."""
        self.usar(TiendaFalsa(falla=True))
        partes = app.crear_coleccion_de_solicitud(TICKET, ["columbia"])
        self.assertEqual(partes[0]["estado"], "error")

    def test_un_sitio_sin_Shopify_en_Secrets_lo_dice(self):
        self.usar(TiendaFalsa())
        app.get_shopify_config = lambda site_key: {}
        parte = app.crear_coleccion_de_solicitud(TICKET, ["columbia"])[0]
        self.assertEqual(parte["estado"], "sin configurar")

    def test_la_carga_reusa_la_coleccion_que_creo_la_pantalla(self):
        """Los dos caminos acaban en LA MISMA coleccion. Si no, la solicitud
        tendria dos: la de la carga y la de la pantalla."""
        tienda = self.usar(TiendaFalsa(colecciones=[
            {"id": "gid://shopify/Collection/77", "handle": "carga-2026-09-10-patagonia-cat-0042",
             "title": "Carga 2026-09-10 · Patagonia · CAT-0042"}]))
        guardado = {}
        real_guardar = app._save_sync_job
        app._save_sync_job = lambda job: guardado.update(job)
        try:
            job = app.crear_coleccion_de_carga({
                "id": "j1", "site_key": "columbia", "mode": "complete",
                "ticket": "CAT-0042", "marca": "Patagonia",
                "created_at": "2026-09-15 10:30:00", "events": [],
                "result_rows": [{"Handle": "h", "ID": "gid://shopify/Product/3",
                                 "Resultado": "OK"}],
            }, CONFIG)
        finally:
            app._save_sync_job = real_guardar
        self.assertEqual(job["coleccion"]["estado"], "ok")
        self.assertTrue(job["coleccion"]["reusada"])
        self.assertEqual(tienda.creadas, [], "no se crea una segunda coleccion")
        self.assertEqual(job["coleccion"]["id"], "gid://shopify/Collection/77")


# =========================================================================
# 4. LA PANTALLA. Un motor perfecto al que no se le puede pedir nada no sirve
#    (seccion 5 octotrigies: el subidor que nadie escribio).
# =========================================================================
from streamlit.testing.v1 import AppTest  # noqa: E402

GUION = """
import sys
sys.path.insert(0, %r)
import streamlit as st
import app_matrixify as app

st.session_state["authenticated"] = True
st.session_state["auth_user"] = "hugo"
app._render_coleccion_de_solicitud(st.session_state["ticket"],
                                   {"role": st.session_state["rol"]})
"""


class TestLaPantalla(unittest.TestCase):

    def dibujar(self, ticket, rol=app.ROLE_ADMIN):
        raiz = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        guion = os.path.join(raiz, "outputs", "_panel_coleccion_solicitud.py")
        os.makedirs(os.path.dirname(guion), exist_ok=True)
        with open(guion, "w", encoding="utf-8") as archivo:
            archivo.write(GUION % raiz)
        at = AppTest.from_file(guion, default_timeout=120)
        at.session_state["ticket"] = ticket
        at.session_state["rol"] = rol
        at.run()
        return at

    def test_ofrece_los_sitios_y_el_boton(self):
        at = self.dibujar(TICKET)
        self.assertEqual([str(e.value)[:200] for e in at.exception], [])
        self.assertTrue(at.multiselect, "sin selector de sitios no hay donde crearla")
        self.assertTrue(at.button, "sin boton no se puede crear")

    def test_los_sitios_de_la_solicitud_vienen_MARCADOS(self):
        """Tener que volver a elegir lo que la solicitud ya dice es rebuscar un
        dato que la app tiene delante."""
        at = self.dibujar(TICKET)
        self.assertEqual(at.multiselect[0].value, ["columbia"])

    def test_una_solicitud_sin_lista_de_codigos_lo_DICE(self):
        """Las viejas guardaron solo el conteo. Un boton que no puede funcionar
        es peor que no tener boton."""
        at = self.dibujar(dict(TICKET, model_colors=[]))
        self.assertEqual(at.button, [])
        self.assertTrue(any("lista de códigos" in str(i.value) for i in at.info))

    def test_una_marca_no_puede_escribir_en_la_tienda(self):
        at = self.dibujar(TICKET, rol=app.ROLE_BRAND)
        self.assertEqual(at.button, [])

    def test_el_panel_se_dibuja_dentro_del_detalle_de_la_solicitud(self):
        """Una pantalla a la que no se llega no existe."""
        import ast
        import inspect
        arbol = ast.parse(inspect.getsource(app.render_ticket_detail))
        llamadas = {n.func.id for n in ast.walk(arbol)
                    if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)}
        self.assertIn("_render_coleccion_de_solicitud", llamadas)


if __name__ == "__main__":
    unittest.main(verbosity=2)
