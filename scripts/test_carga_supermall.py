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
        self.assertIn("is_shopify_configured", cuerpo)
        self.assertIn("no tiene Shopify configurado", cuerpo)


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
        import app_matrixify as app
        fuente = inspect.getsource(app)
        self.assertIn("SUPERMALL_LABEL,\n        \"Input comercial\",", fuente)
        self.assertIn("if operation_area == SUPERMALL_LABEL:", fuente)

    def test_no_escribe_en_shopify_al_analizar(self):
        """Dos tiempos: primero se revisa TODO sin escribir nada."""
        import app_matrixify as app
        cuerpo = inspect.getsource(app.supermall_consolidar_origen)
        cuerpo += inspect.getsource(cs.consolidar)
        for prohibido in ("apply_full_product_updates", "metafieldsSet",
                          "update_product", "productCreateMedia"):
            self.assertNotIn(prohibido, cuerpo)


if __name__ == "__main__":
    unittest.main(verbosity=2)
