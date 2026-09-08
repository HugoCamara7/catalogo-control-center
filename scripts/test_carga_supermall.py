"""La carga de Supermall: consolidar lo que ya esta en las demas webs.

Ejecutar:  python scripts/test_carga_supermall.py

Lo que fija
-----------
El agujero que este modulo cierra: el espejo decia QUE FALTA y mandaba a
"Carga parcial -> Carga Sial", pero esa pantalla solo produce la hoja SIAL y
lee el catalogo de UN sitio -- el activo. Estando en Supermall ese es el
DESTINO, donde los productos que faltan por definicion no estan, asi que el
producto salia casi vacio.
"""
import ast
import inspect
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from engines import carga_supermall as cs  # noqa: E402
import generate_columbia_matrixify as g  # noqa: E402

ETIQUETAS = {
    "columbia": "Columbia.pe", "rockford": "Rockford.pe", "vans": "Vans.pe",
    "hush_puppies": "HushPuppies.pe", "supermall": "Supermall.pe",
}
ORDEN = ["columbia", "rockford", "vans", "hush_puppies", "supermall"]


def producto(codigo="X-1", **extra):
    base = {
        "Mod-Col": codigo, "Handle": codigo.lower(), "Product ID": "gid://1",
        "Title": "", "Body HTML": "", "Type": "", "Tags": "", "Image Src": "",
        "Vendor": "sitiope", "Marca": "", "Status": "ACTIVE",
        "Published Online Store": "SI", "Variants": [],
    }
    base.update(extra)
    return base


def consolidar(catalogos, codigos=()):
    return cs.consolidar(catalogos, codigos=codigos, etiquetas_de_sitio=ETIQUETAS,
                         marcas_conocidas=("Vans", "Columbia", "Hush Puppies"),
                         orden_de_sitios=ORDEN)


class TestLaConsolidacionCampoACampo(unittest.TestCase):
    def test_cada_campo_sale_de_la_web_que_lo_tenga(self):
        """Tomar "el sitio ganador" entero desperdicia el campo que solo tiene
        el otro. Se resuelve campo a campo."""
        r = consolidar({
            "vans": [producto(Title="Old Skool", Marca="Vans")],
            "rockford": [producto(Type="Zapatilla", **{"Image Src": "a.jpg"})],
            "supermall": [],
        })
        ficha = r["fichas"][0]
        self.assertEqual(ficha["Title"], "Old Skool")
        self.assertEqual(ficha["Type"], "Zapatilla")
        self.assertEqual(ficha["Image Src"], "a.jpg")

    def test_se_dice_de_donde_salio_cada_dato(self):
        """Cuando un producto salga raro la pregunta va a ser "de donde sacó
        esa descripcion". Tiene que poder responderse sin abrir seis pestanas."""
        r = consolidar({
            "vans": [producto(Title="Old Skool")],
            "rockford": [producto(Type="Zapatilla")],
            "supermall": [],
        })
        origen = r["fichas"][0]["Origen por campo"]
        self.assertIn("Title=Vans.pe", origen)
        self.assertIn("Type=Rockford.pe", origen)

    def test_manda_el_sitio_donde_esta_PRENDIDO(self):
        """A igualdad de dato manda la web donde el producto se ve de verdad:
        es la que alguien reviso."""
        r = consolidar({
            "columbia": [producto(Title="Borrador viejo", Status="DRAFT",
                                  **{"Published Online Store": "NO"})],
            "vans": [producto(Title="Nombre bueno")],
            "supermall": [],
        })
        self.assertEqual(r["fichas"][0]["Title"], "Nombre bueno")

    def test_ningun_sitio_manda_sobre_otro(self):
        """Supermall no tiene marca propia: lleva todas. A igualdad de estado,
        el desempate es el orden declarado y no el de llegada, para que dos
        ejecuciones se puedan comparar."""
        catalogos = {
            "columbia": [producto(Title="Desde Columbia")],
            "vans": [producto(Title="Desde Vans")],
            "supermall": [],
        }
        primera = consolidar(catalogos)["fichas"][0]["Title"]
        segunda = consolidar(dict(reversed(list(catalogos.items()))))["fichas"][0]["Title"]
        self.assertEqual(primera, segunda)

    def test_un_producto_en_tres_webs_cuenta_una_vez(self):
        r = consolidar({
            "columbia": [producto(Title="A")], "vans": [producto(Title="A")],
            "rockford": [producto(Title="A")], "supermall": [],
        })
        self.assertEqual(len(r["fichas"]), 1)
        self.assertEqual(r["fichas"][0]["Sitios de origen"],
                         "Columbia.pe, Rockford.pe, Vans.pe")


class TestCrearOActualizar(unittest.TestCase):
    def test_lo_que_no_esta_en_supermall_se_crea(self):
        r = consolidar({"vans": [producto(Title="A", Type="Zapatilla")], "supermall": []})
        self.assertEqual(r["fichas"][0]["Accion"], "Crear")

    def test_lo_que_ya_esta_se_actualiza(self):
        r = consolidar({
            "vans": [producto(Title="A", Type="Zapatilla")],
            "supermall": [producto(Title="A")],
        })
        self.assertEqual(r["fichas"][0]["Accion"], "Actualizar")
        self.assertEqual(r["fichas"][0]["Estado en Supermall"], "Prendido y visible")

    def test_el_handle_y_el_id_de_origen_no_viajan(self):
        """Son de la tienda de ORIGEN. Un producto que se crea en Supermall con
        el handle de Vans.pe quedaria enlazado con una ficha que no existe."""
        r = consolidar({"vans": [producto(Title="A", Type="Zapatilla")], "supermall": []})
        productos = cs.productos_para_matrixify(r["fichas"])
        self.assertNotIn("Handle", productos[0])
        self.assertNotIn("Product ID", productos[0])


class TestQueBloqueaYQueSoloAvisa(unittest.TestCase):
    """La separacion importa: un aviso que bloquea detiene una carga de miles
    por un dato que no lo merece."""

    def test_sin_nombre_no_se_puede_cargar(self):
        r = consolidar({"vans": [producto(Type="Zapatilla")], "supermall": []})
        self.assertFalse(r["fichas"][0]["Se puede cargar"])
        self.assertIn(cs.SIN_TITULO, r["fichas"][0]["Bloqueos"])

    def test_sin_tipo_no_se_puede_cargar(self):
        r = consolidar({"vans": [producto(Title="A")], "supermall": []})
        self.assertIn(cs.SIN_TIPO, r["fichas"][0]["Bloqueos"])

    def test_sin_codigo_no_se_puede_cargar(self):
        """La carga se pide por lista de codigos y el suyo no existe."""
        r = consolidar({"vans": [producto("", Title="A", Type="Zapatilla", Handle="h")],
                        "supermall": []})
        self.assertIn(cs.SIN_CODIGO, r["fichas"][0]["Bloqueos"])

    def test_sin_genero_SI_se_carga(self):
        """Solo avisa. Su calzado se queda en la talla de origen, y eso se
        reporta -- pero no detiene una carga de miles."""
        r = consolidar({"vans": [producto(Title="A", Type="Zapatilla")], "supermall": []})
        ficha = r["fichas"][0]
        self.assertTrue(ficha["Se puede cargar"])
        self.assertIn(cs.SIN_GENERO, ficha["Avisos"])

    def test_sin_fotos_SI_se_carga(self):
        r = consolidar({"vans": [producto(Title="A", Type="Zapatilla")], "supermall": []})
        self.assertIn(cs.SIN_FOTOS, r["fichas"][0]["Avisos"])
        self.assertTrue(r["fichas"][0]["Se puede cargar"])

    def test_los_bloqueados_quedan_fuera_del_archivo(self):
        r = consolidar({
            "vans": [producto("A-1", Title="A", Type="Zapatilla"), producto("B-1")],
            "supermall": [],
        })
        self.assertEqual(cs.codigos_cargables(r["fichas"]), ["A-1"])
        self.assertEqual(len(cs.productos_para_matrixify(r["fichas"])), 1)


class TestElGeneroLlegaAlConversorDeTallas(unittest.TestCase):
    def test_el_genero_viaja_con_su_nombre_corto(self):
        """Es lo que lee el conversor: sin el, una zapatilla de Vans no se
        puede pasar a PE y se queda en US."""
        r = consolidar({
            "vans": [producto(Title="A", Type="Zapatilla", **{
                "Metafield: custom.genero [single_line_text_field]": "Femenino"})],
            "supermall": [],
        })
        self.assertEqual(r["fichas"][0]["Genero"], "Femenino")
        self.assertEqual(cs.productos_para_matrixify(r["fichas"])[0]["Genero"], "Femenino")


class TestElDestinoAusente(unittest.TestCase):
    def test_sin_catalogo_de_supermall_todo_sale_como_crear(self):
        """Es exactamente por esto que la PANTALLA corta cuando Supermall no
        se pudo leer: sin destino todo saldria como "falta"."""
        r = consolidar({"vans": [producto(Title="A", Type="Zapatilla")]})
        self.assertEqual(r["fichas"][0]["Accion"], "Crear")

    def test_la_pantalla_corta_si_supermall_no_tiene_shopify(self):
        import app_matrixify as app
        cuerpo = inspect.getsource(app.render_carga_supermall)
        self.assertIn("sitio_espejo()", cuerpo)
        self.assertIn("no tiene Shopify configurado", cuerpo)

    def test_no_hay_una_segunda_comprobacion_del_token(self):
        """`sitio_espejo()` ya comprueba Shopify: un segundo `if` por el token
        seria una rama que no se puede alcanzar nunca."""
        import app_matrixify as app
        cuerpo = inspect.getsource(app.render_carga_supermall)
        self.assertNotIn("if not is_shopify_configured(shopify_config):", cuerpo)


class TestLasReglasDeSupermall(unittest.TestCase):
    def test_entra_activo_y_publicado(self):
        self.assertEqual(g.estado_al_cargar(g.get_brand_config("supermall")), ("Active", "TRUE"))

    def test_los_demas_sitios_conservan_su_estado(self):
        self.assertEqual(
            g.estado_al_cargar(g.get_brand_config("vans"), {"Status": "Draft", "Published": "FALSE"}),
            ("Draft", "FALSE"),
        )

    def test_el_precio_lo_sincroniza_el_erp(self):
        self.assertTrue(g.get_brand_config("supermall").get("precio_desde_erp"))
        for clave in ("vans", "columbia", "rockford"):
            self.assertFalse(g.get_brand_config(clave).get("precio_desde_erp"), clave)

    def test_la_bodega_sial_es_la_13(self):
        self.assertEqual(g.get_brand_config("supermall").get("sial_active_columns"), ["13"])

    def test_las_marcas_son_la_union_de_los_demas_sitios(self):
        supermall = set(g.get_brand_config("supermall")["allowed_arti_brands"])
        for clave, config in g.SITE_CONFIGS.items():
            if clave == "supermall":
                continue
            self.assertTrue(set(config.get("allowed_arti_brands", [])) <= supermall, clave)


class TestLosSiblingsSiempreSeCargan(unittest.TestCase):
    def test_la_carga_por_codigos_escribe_siblings(self):
        """Hasta ahora solo los escribia la carga completa: la rama de carga
        por codigos -- Centry, Carga Sial y Supermall -- los dejaba vacios."""
        import app_matrixify as app
        cuerpo = inspect.getsource(app.build_centry_matrixify_from_master)
        for columna in (
            "Metafield: theme.siblings [single_line_text_field]",
            "Metafield: custom.siblings [single_line_text_field]",
            "Metafield: theme.siblings_color [single_line_text_field]",
            "Metafield: custom.siblings_color [single_line_text_field]",
        ):
            self.assertIn(columna, cuerpo)

    def test_usa_la_misma_regla_que_la_carga_completa(self):
        """Escrita dos veces, el arreglo siguiente entraria en una y se
        olvidaria en la otra."""
        import app_matrixify as app
        self.assertIn("unir_siblings(", inspect.getsource(app.build_centry_matrixify_from_master))
        self.assertIn("unir_siblings(", inspect.getsource(g.build_columbia_matrixify))

    def test_lo_ya_publicado_no_se_pisa(self):
        """Un modelo con tres colores en la tienda que hoy recibe uno nuevo
        tiene que acabar con cuatro hermanos, no con uno."""
        unidos = g.unir_siblings({"M1": ["nuevo"]}, {"M1": ["viejo-a", "viejo-b"]})
        self.assertEqual(unidos["M1"], "nuevo, viejo-a, viejo-b")


class TestLaPantalla(unittest.TestCase):
    def test_el_tramo_comun_sigue_siendo_uno(self):
        """`supermall_generar` pasa por `matrixify_desde_codigos_modelo_color`,
        no por una segunda copia del cruce con el maestro."""
        import app_matrixify as app
        arbol = ast.parse(inspect.getsource(app))
        llamadas = sum(
            1 for nodo in ast.walk(arbol)
            if isinstance(nodo, ast.Call) and isinstance(nodo.func, ast.Name)
            and nodo.func.id == "build_centry_matrixify_from_master"
        )
        self.assertEqual(llamadas, 1)

    def test_se_procesa_por_bloques_y_se_avisa_del_avance(self):
        import app_matrixify as app
        cuerpo = inspect.getsource(app.supermall_generar)
        self.assertIn("png_bloques(", cuerpo)
        self.assertIn("avanzar(", cuerpo)

    def test_el_menu_registra_el_boton_en_las_cinco_listas(self):
        """Un boton nuevo del menu lateral hay que registrarlo en CINCO listas
        de selectores y darle su icono. Nada en el codigo lo obliga."""
        import app_matrixify as app
        fuente = inspect.getsource(app)
        for selector in (
            "div.st-key-operation_nav_supermall button,",
            'div.st-key-operation_nav_supermall button [data-testid="stMarkdownContainer"],',
            "div.st-key-operation_nav_supermall button p,",
            "div.st-key-operation_nav_supermall button::before,",
            "div.st-key-operation_nav_supermall button:hover,",
        ):
            self.assertIn(selector, fuente, selector)
        self.assertIn("div.st-key-operation_nav_supermall button::before {{", fuente)

    def test_esta_en_el_menu_principal(self):
        """Supermall es una funcionalidad central, no una opcion escondida
        dentro de Carga parcial."""
        import ast

        import app_matrixify as app
        fuente = inspect.getsource(app)
        # Se mira que SUPERMALL_LABEL este en la lista `nav_options` del menu,
        # no que sea vecino de "Input comercial": esa era la comprobacion
        # anterior y se rompio sola al meter "Diccionarios" en medio, sin que
        # Supermall se hubiera movido del menu.
        opciones = []
        for nodo in ast.walk(ast.parse(fuente)):
            if not isinstance(nodo, ast.Assign):
                continue
            destinos = [d.id for d in nodo.targets if isinstance(d, ast.Name)]
            if "nav_options" in destinos and isinstance(nodo.value, ast.List):
                opciones = [
                    e.id if isinstance(e, ast.Name) else getattr(e, "value", None)
                    for e in nodo.value.elts
                ]
        self.assertIn("SUPERMALL_LABEL", opciones)
        self.assertIn("if operation_area == SUPERMALL_LABEL:", fuente)

    def test_no_escribe_en_shopify_al_analizar(self):
        """Dos tiempos: primero se revisa TODO sin escribir nada."""
        import app_matrixify as app
        cuerpo = inspect.getsource(app.supermall_consolidar_origen)
        cuerpo += inspect.getsource(cs.consolidar)
        for prohibido in ("apply_full_product_updates", "metafieldsSet",
                          "update_product", "productCreateMedia"):
            self.assertNotIn(prohibido, cuerpo)


class TestLaMarcaSeLee(unittest.TestCase):
    """La marca es el eje del panel del hueco: si sale "Sin marca", el panel
    que reparte el trabajo por marca no dice nada."""

    def test_el_centinela_sin_marca_ya_no_gana(self):
        """`marca_de_producto` nunca devuelve vacio: cuando no la sabe devuelve
        la cadena "Sin marca". Tomando el primer valor NO VACIO del grupo, ese
        centinela ganaba y tapaba la marca de la web siguiente."""
        r = consolidar({
            "columbia": [producto(Title="A", Type="Casaca")],          # sin marca
            "vans": [producto(Title="A", Type="Casaca", Marca="Vans")],
            "supermall": [],
        })
        self.assertEqual(r["fichas"][0]["Marca"], "Vans")

    def test_un_sitio_de_una_sola_marca_la_resuelve(self):
        """Columbia.pe solo vende COLUMBIA: un producto suyo sin metacampo y
        sin tag no es "Sin marca", es Columbia."""
        r = cs.consolidar(
            {"columbia": [producto(Title="A", Type="Casaca")], "supermall": []},
            etiquetas_de_sitio=ETIQUETAS, orden_de_sitios=ORDEN,
            marcas_por_sitio={"columbia": ["Columbia"]},
        )
        self.assertEqual(r["fichas"][0]["Marca"], "Columbia")

    def test_un_sitio_de_varias_marcas_no_la_adivina(self):
        """Rockford.pe vende cuatro. Ahi no hay respuesta, y decir cualquiera
        seria peor que decir "Sin marca"."""
        r = cs.consolidar(
            {"rockford": [producto(Title="A", Type="Casaca")], "supermall": []},
            etiquetas_de_sitio=ETIQUETAS, orden_de_sitios=ORDEN,
            marcas_por_sitio={"rockford": ["Columbia", "Rockford", "Sorel"]},
        )
        self.assertEqual(r["fichas"][0]["Marca"], cs.SIN_MARCA)

    def test_las_marcas_del_sitio_salen_de_SITE_CONFIGS(self):
        """Escritas a mano en la pantalla, una marca nueva en un sitio no
        llegaria aqui hasta que alguien se acordara."""
        import app_matrixify as app
        por_sitio = app.marcas_por_sitio_configuradas()
        self.assertEqual(por_sitio["columbia"], ["Columbia"])
        self.assertIn("Columbia", por_sitio["rockford"])
        self.assertGreater(len(por_sitio["rockford"]), 1)


class TestElVendorTambienDiceLaMarca(unittest.TestCase):
    """En los productos que crea esta app el vendor es el de la TIENDA
    (`rockfordpe`), el mismo para todas sus marcas. En los cargados por fuera
    trae la marca de verdad -- de ahi salen los "Massimo Cerutti" del catalogo.
    """

    def _consolidar(self, vendor):
        return cs.consolidar(
            {"rockford": [producto(Title="A", Type="Casaca", Vendor=vendor)],
             "supermall": []},
            etiquetas_de_sitio=ETIQUETAS, orden_de_sitios=ORDEN,
            marcas_conocidas=("Vans", "Columbia", "Hush Puppies"),
            marcas_por_sitio={"rockford": ["Columbia", "Rockford", "Sorel"]},
            vendors_de_sitio=("rockfordpe", "columbiape", "Vans"),
        )

    def test_un_vendor_que_no_es_de_la_tienda_es_la_marca(self):
        self.assertEqual(self._consolidar("Massimo Cerutti")["fichas"][0]["Marca"],
                         "Massimo Cerutti")

    def test_el_vendor_de_la_tienda_no_es_una_marca(self):
        """Contando por vendor, todo el catalogo de Rockford.pe saldria bajo
        una marca inventada, que es peor que "Sin marca"."""
        self.assertEqual(self._consolidar("rockfordpe")["fichas"][0]["Marca"],
                         cs.SIN_MARCA)

    def test_sin_la_lista_de_vendors_el_paso_no_se_hace(self):
        """Sin saber cuales son los vendors de las tiendas no se puede
        distinguir uno del otro, y ante la duda no se inventa una marca."""
        r = cs.consolidar(
            {"rockford": [producto(Title="A", Type="Casaca", Vendor="rockfordpe")],
             "supermall": []},
            etiquetas_de_sitio=ETIQUETAS, orden_de_sitios=ORDEN,
            marcas_por_sitio={"rockford": ["Columbia", "Rockford"]},
        )
        self.assertEqual(r["fichas"][0]["Marca"], cs.SIN_MARCA)

    def test_un_vendor_que_ES_una_marca_conocida_vale_igual(self):
        """`Vans` es las dos cosas: la marca, y el vendor antiguo de Vans.pe.
        Descartarlo dejaba sin marca a los productos de Vans en Supermall."""
        self.assertEqual(self._consolidar("Vans")["fichas"][0]["Marca"], "Vans")

    def test_la_lista_de_vendors_sale_de_SITE_CONFIGS(self):
        import app_matrixify as app
        vendors = app.vendors_de_los_sitios()
        self.assertIn("rockfordpe", vendors)
        self.assertIn("columbiape", vendors)


class TestLaMismaMarcaEscritaDistinto(unittest.TestCase):
    """En el catalogo real salian "Hush Puppies" con 2.399 productos y "Hush
    puppies" con 2: la misma marca partida en dos filas de la tabla por una
    mayuscula."""

    def test_se_devuelve_el_nombre_canonico(self):
        r = cs.consolidar(
            {"hush_puppies": [producto("A-1", Title="A", Type="Casaca",
                                       Marca="Hush Puppies"),
                              producto("B-1", Title="B", Type="Casaca",
                                       Marca="Hush puppies")],
             "supermall": []},
            etiquetas_de_sitio=ETIQUETAS, orden_de_sitios=ORDEN,
            marcas_conocidas=("Hush Puppies",),
        )
        self.assertEqual({f["Marca"] for f in r["fichas"]}, {"Hush Puppies"})

    def test_una_sola_fila_en_el_hueco_por_marca(self):
        r = cs.consolidar(
            {"hush_puppies": [producto("A-1", Title="A", Type="Casaca",
                                       Marca="HUSH PUPPIES"),
                              producto("B-1", Title="B", Type="Casaca",
                                       Marca="Hush puppies")],
             "supermall": []},
            etiquetas_de_sitio=ETIQUETAS, orden_de_sitios=ORDEN,
            marcas_conocidas=("Hush Puppies",),
        )
        filas = cs.hueco_por_marca(r["fichas"])
        self.assertEqual(len(filas), 1)
        self.assertEqual(filas[0]["Total"], 2)


class TestColumbiaEnDosWebs(unittest.TestCase):
    """Columbia se vende en Columbia.pe y tambien en Rockford.pe. El mismo
    producto esta en las dos y de la consolidacion tiene que salir UNA ficha,
    con la informacion de la tienda de la marca."""

    def _catalogos(self):
        return {
            "columbia": [producto("C-1", Title="Desde Columbia", Type="Casaca",
                                  Marca="Columbia")],
            "rockford": [producto("C-1", Title="Desde Rockford", Type="Casaca",
                                  Marca="Columbia")],
            "supermall": [],
        }

    def _consolidar(self):
        return cs.consolidar(
            self._catalogos(), etiquetas_de_sitio=ETIQUETAS, orden_de_sitios=ORDEN,
            marcas_por_sitio={"columbia": ["Columbia"]},
            sitio_de_marca={"Columbia": "columbia"},
        )

    def test_no_se_duplica(self):
        r = self._consolidar()
        self.assertEqual(len(r["fichas"]), 1)
        self.assertEqual(cs.codigos_cargables(r["fichas"]), ["C-1"])

    def test_manda_la_tienda_de_la_marca(self):
        ficha = self._consolidar()["fichas"][0]
        self.assertEqual(ficha["Web principal"], "Columbia.pe")
        self.assertEqual(ficha["Title"], "Desde Columbia")
        self.assertEqual(ficha["En cuantas webs"], 2)

    def test_sin_sitio_propio_manda_el_orden_declarado(self):
        """El desempate final nunca es el de llegada: una consolidacion que
        cambia de resultado en cada ejecucion no se puede comparar."""
        r = cs.consolidar(self._catalogos(), etiquetas_de_sitio=ETIQUETAS,
                          orden_de_sitios=["rockford", "columbia", "supermall"])
        self.assertEqual(r["fichas"][0]["Web principal"], "Rockford.pe")

    def test_el_sitio_propio_de_cada_marca_sale_de_SITE_CONFIGS(self):
        import app_matrixify as app
        propios = app.sitio_propio_de_cada_marca()
        self.assertEqual(propios["Columbia"], "columbia")
        self.assertEqual(propios["Vans"], "vans")
        self.assertNotIn("Supermall", propios)  # el espejo no es tienda de nadie


class TestElRepartoEntreLosCuatroEstados(unittest.TestCase):
    """Antes la pantalla filtraba los codigos ANTES de consolidar, con la lista
    del espejo: de las cuatro situaciones solo podia salir "Falta cargar", asi
    que consolidados, se pueden cargar y se crean daban el MISMO numero y la
    cobertura siempre 0 %."""

    def _catalogos(self):
        return {
            "vans": [
                producto("A-1", Title="A", Type="Zapatilla"),
                producto("B-1", Title="B", Type="Zapatilla"),
                producto("C-1", Title="C", Type="Zapatilla"),
                producto("D-1", Type="Zapatilla"),          # sin titulo: bloqueado
            ],
            "supermall": [
                producto("A-1"),
                producto("B-1", Status="DRAFT"),
            ],
        }

    def test_el_resumen_reparte_el_total(self):
        r = consolidar(self._catalogos())
        resumen = r["resumen"]
        reparto = sum(resumen[clave] for clave in cs.SEGMENTOS)
        self.assertEqual(reparto, resumen["Productos consolidados"])
        self.assertEqual(resumen[cs.YA_VISIBLE], 1)
        self.assertEqual(resumen[cs.SIN_PUBLICAR], 1)
        self.assertEqual(resumen[cs.FALTA_CARGAR], 1)
        self.assertEqual(resumen[cs.NO_CARGABLE], 1)

    def test_solo_se_genera_lo_que_falta(self):
        """Lo cargado sin publicar se PUBLICA, no se recarga: recargarlo le
        reescribiria la ficha sin que nadie lo haya pedido."""
        r = consolidar(self._catalogos())
        self.assertEqual(
            cs.codigos_cargables(r["fichas"], (cs.FALTA_CARGAR,)), ["C-1"])
        self.assertEqual(
            len(cs.productos_para_matrixify(r["fichas"], (cs.FALTA_CARGAR,))), 1)

    def test_la_pantalla_genera_solo_lo_que_falta(self):
        import app_matrixify as app
        cuerpo = inspect.getsource(app.supermall_generar)
        self.assertIn("carga_supermall.FALTA_CARGAR", cuerpo)

    def test_la_pantalla_ya_no_prefiltra_con_el_espejo(self):
        """Prefiltrando, el panel de las cuatro situaciones no puede decir nada."""
        import app_matrixify as app
        cuerpo = inspect.getsource(app.render_carga_supermall)
        self.assertNotIn("espejo_de_supermall(catalogos", cuerpo)


class TestElTrabajoNoSeRepiteEnCadaRerun(unittest.TestCase):
    """Streamlit reejecuta el script entero en cada clic, y esta pantalla tiene
    cuatro controles. Con el catalogo completo, rehacer `filas_para_tabla` y su
    DataFrame costaba 0,24 s medidos POR CLIC, y el resultado no cambia."""

    def test_la_tabla_y_el_hueco_se_calculan_al_analizar(self):
        import app_matrixify as app
        cuerpo = inspect.getsource(app.render_carga_supermall)
        antes = cuerpo.split('st.session_state["supermall_consolidado"] = consolidado', 1)[0]
        # Los cuatro se calculan DENTRO del bloque que analiza, o sea antes de
        # guardarse en la sesion. Comprobarlo sobre el cuerpo entero no diria
        # nada: la linea existiria igual estando en el camino de dibujo.
        for guardado in ('consolidado["tabla"]', 'consolidado["hueco"]',
                         'consolidado["totales_hueco"]', 'consolidado["por_cargar"]'):
            self.assertIn(guardado, antes, f"{guardado} no se calcula al analizar")

    def test_no_se_rehace_al_dibujar(self):
        import app_matrixify as app
        cuerpo = inspect.getsource(app.render_carga_supermall)
        # despues del bloque de analisis no puede volver a llamarse
        despues = cuerpo.split('st.session_state["supermall_consolidado"] = consolidado', 1)[1]
        for prohibido in ("carga_supermall.filas_para_tabla(",
                          "carga_supermall.hueco_por_marca(",
                          "carga_supermall.totales_del_hueco("):
            self.assertNotIn(prohibido, despues,
                             f"{prohibido} se rehace en cada rerun")

    def test_las_tablas_grandes_del_status_se_arman_una_vez(self):
        """Streamlit ejecuta el cuerpo de las SEIS pestanas en cada rerun."""
        import app_matrixify as app
        self.assertIn("isinstance(datos, pd.DataFrame)",
                      inspect.getsource(app._tabla_status))
        self.assertIn('"tabla": _tabla_status(', inspect.getsource(app.espejo_de_supermall))


class TestElDestinoSinLeerCorta(unittest.TestCase):
    """Destino AUSENTE no es destino VACIO. Sin el catalogo de Supermall todo
    sale como "falta cargar", y generar esa carga crearia por duplicado miles
    de productos que ya existen."""

    def test_el_resumen_lo_dice(self):
        r = consolidar({"vans": [producto(Title="A", Type="Zapatilla")]})
        self.assertFalse(r["resumen"]["destino_leido"])

    def test_con_supermall_vacio_si_esta_leido(self):
        r = consolidar({"vans": [producto(Title="A", Type="Zapatilla")], "supermall": []})
        self.assertTrue(r["resumen"]["destino_leido"])

    def test_la_pantalla_corta(self):
        import app_matrixify as app
        cuerpo = inspect.getsource(app.render_carga_supermall)
        self.assertIn('destino_leido', cuerpo)
        self.assertIn("no se pudo leer el catálogo de Supermall.pe".lower(),
                      cuerpo.lower())

    def test_la_pantalla_ensena_el_motivo_del_fallo(self):
        """El aviso decia solo "Supermall.pe (Error)". En produccion el motivo
        era un HTTP 401 por token vencido y no se veia en ninguna parte."""
        import app_matrixify as app
        cuerpo = inspect.getsource(app.render_carga_supermall)
        self.assertIn("Detalle", cuerpo)


if __name__ == "__main__":
    unittest.main(verbosity=2)
