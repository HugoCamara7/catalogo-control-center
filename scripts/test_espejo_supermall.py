"""Supermall.pe como sitio espejo: que le falta y como se le carga.

Por que existe
--------------
Supermall.pe dejo VTEX y paso a Shopify, y lleva el catalogo de TODOS los
sitios. Mantenerlo al dia "acordandose de cargar tambien alli" falla el dia que
alguien tiene prisa, y nadie se entera hasta que un producto lleva meses sin
salir. Estas pruebas fijan las dos mitades del arreglo:

1. El ESPEJO: la resta entre lo que hay en los demas sitios y lo que hay en
   Supermall, que es un dato y no una costumbre.
2. El SEGUNDO DESTINO: que la misma solicitud se pueda cargar en Supermall sin
   duplicar el ticket.

Ejecutar:  python scripts/test_espejo_supermall.py
"""
import ast
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from engines import espejo_supermall as espejo  # noqa: E402
from generate_columbia_matrixify import SITE_CONFIGS  # noqa: E402

FUENTE_APP = (ROOT / "app_matrixify.py").read_text(encoding="utf-8-sig")
ARBOL_APP = ast.parse(FUENTE_APP)


def producto(codigo, titulo="Producto", handle="", marca="Vans", estado="ACTIVE", publicado="SI"):
    return {
        "Mod-Col": codigo,
        "Title": titulo,
        "Handle": handle or (codigo.lower() or "sin-codigo"),
        "Marca": marca,
        "Status": estado,
        "Published Online Store": publicado,
    }


ETIQUETAS = {"vans": "Vans.pe", "columbia": "Columbia.pe", "supermall": "Supermall.pe"}


class TestEspejo(unittest.TestCase):
    def comparar(self, catalogos):
        return espejo.comparar(catalogos, etiquetas_de_sitio=ETIQUETAS)

    def test_lo_que_esta_en_un_sitio_y_no_en_supermall_sale_como_falta(self):
        resultado = self.comparar({
            "vans": [producto("VN1-001"), producto("VN2-002")],
            "supermall": [producto("VN1-001")],
        })
        faltan = [f for f in resultado["filas"] if f["Situacion"] == espejo.FALTA]
        self.assertEqual([f["Mod-Col"] for f in faltan], ["VN2-002"])
        self.assertEqual(resultado["resumen"]["Faltan en Supermall"], 1)
        self.assertEqual(espejo.codigos_a_cargar(resultado["filas"]), ["VN2-002"])

    def test_un_producto_en_varios_sitios_cuenta_una_vez(self):
        """Tres sitios con el mismo modelo no son tres cosas que cargar."""
        resultado = self.comparar({
            "vans": [producto("VN1-001")],
            "columbia": [producto("VN1-001")],
            "supermall": [],
        })
        self.assertEqual(len(resultado["filas"]), 1)
        self.assertEqual(resultado["filas"][0]["Sitios de origen"], "Vans.pe, Columbia.pe")

    def test_cargado_no_es_lo_mismo_que_visible(self):
        """Un producto en borrador esta cargado: recargarlo le reescribiria la
        ficha. Lo que hace falta es publicarlo, y son cosas distintas."""
        resultado = self.comparar({
            "vans": [producto("VN1-001")],
            "supermall": [producto("VN1-001", estado="DRAFT", publicado="NO")],
        })
        fila = resultado["filas"][0]
        self.assertEqual(fila["Situacion"], espejo.PUBLICAR)
        self.assertEqual(fila["Estado en Supermall"], "Borrador")
        self.assertEqual(resultado["resumen"]["Faltan en Supermall"], 0)
        self.assertEqual(espejo.codigos_a_cargar(resultado["filas"]), [],
                         "un producto ya cargado no se vuelve a cargar")

    def test_activo_sin_publicar_tampoco_cuenta_como_visible(self):
        resultado = self.comparar({
            "vans": [producto("VN1-001")],
            "supermall": [producto("VN1-001", publicado="")],
        })
        self.assertEqual(resultado["filas"][0]["Estado en Supermall"], "Activo sin publicar")
        self.assertEqual(resultado["resumen"]["Ya visibles en Supermall"], 0)

    def test_un_producto_sin_codigo_no_se_puede_espejar_y_se_dice(self):
        """Se cuenta -existe- pero queda fuera de la lista de codigos: la carga
        se pide por codigo y el suyo no existe. Mezclarlos dejaria la lista con
        huecos que nadie explica."""
        resultado = self.comparar({
            "vans": [producto("", handle="viejo")],
            "supermall": [],
        })
        self.assertEqual(resultado["filas"][0]["Situacion"], espejo.SIN_CODIGO)
        self.assertEqual(resultado["resumen"]["Sin codigo Modelo-Color"], 1)
        self.assertEqual(resultado["resumen"]["Faltan en Supermall"], 0)
        self.assertEqual(espejo.codigos_a_cargar(resultado["filas"]), [])

    def test_dos_productos_sin_codigo_no_se_colapsan_en_uno(self):
        """La trampa de la seccion 5 quater: con `set()` sobre el Mod-Col,
        todos los productos sin metacampo comparten la cadena vacia."""
        resultado = self.comparar({
            "vans": [producto("", handle="viejo-a"), producto("", handle="viejo-b")],
            "supermall": [],
        })
        self.assertEqual(len(resultado["filas"]), 2)
        self.assertEqual(resultado["resumen"]["Productos en los otros sitios"], 2)

    def test_sin_el_catalogo_del_destino_no_se_afirma_que_falte_todo(self):
        """Si Supermall no se pudo leer, todo saldria como "falta" y eso se
        leeria como "hay que cargar el catalogo entero"."""
        resultado = self.comparar({"vans": [producto("VN1-001")]})
        self.assertFalse(resultado["resumen"]["destino_leido"])

    def test_el_destino_vacio_si_es_un_dato(self):
        resultado = self.comparar({"vans": [producto("VN1-001")], "supermall": []})
        self.assertTrue(resultado["resumen"]["destino_leido"])
        self.assertEqual(resultado["resumen"]["Faltan en Supermall"], 1)

    def test_la_cobertura_es_sobre_lo_visible(self):
        resultado = self.comparar({
            "vans": [producto("VN1-001"), producto("VN2-002"), producto("VN3-003"), producto("VN4-004")],
            "supermall": [producto("VN1-001")],
        })
        self.assertEqual(resultado["resumen"]["Cobertura"], 25.0)

    def test_lo_que_hay_que_hacer_va_primero(self):
        """La primera fila visible sin bajar no puede ser algo ya resuelto."""
        resultado = self.comparar({
            "vans": [producto("VN1-001"), producto("VN2-002")],
            "supermall": [producto("VN1-001")],
        })
        self.assertEqual(resultado["filas"][0]["Situacion"], espejo.FALTA)

    def test_el_orden_es_estable_entre_corridas(self):
        catalogos = {
            "vans": [producto("VN3-003"), producto("VN1-001"), producto("VN2-002")],
            "supermall": [],
        }
        primera = [f["Mod-Col"] for f in self.comparar(catalogos)["filas"]]
        segunda = [f["Mod-Col"] for f in self.comparar(catalogos)["filas"]]
        self.assertEqual(primera, segunda)
        self.assertEqual(primera, ["VN1-001", "VN2-002", "VN3-003"])

    def test_por_marca_muestra_donde_esta_el_hueco(self):
        resultado = self.comparar({
            "vans": [producto("VN1-001", marca="Vans"), producto("VN2-002", marca="Vans")],
            "columbia": [producto("CO1-001", marca="Columbia")],
            "supermall": [producto("CO1-001", marca="Columbia")],
        })
        por_marca = espejo.por_marca(resultado["filas"])
        self.assertEqual(por_marca[0]["Marca"], "Vans")
        self.assertEqual(por_marca[0]["Faltan"], 2)

    def test_el_limite_de_codigos_se_respeta(self):
        resultado = self.comparar({
            "vans": [producto(f"VN{n}-00{n}") for n in range(1, 6)],
            "supermall": [],
        })
        self.assertEqual(len(espejo.codigos_a_cargar(resultado["filas"], limite=2)), 2)

    def test_sin_catalogos_no_revienta(self):
        self.assertEqual(espejo.comparar({})["filas"], [])
        self.assertEqual(espejo.comparar(None)["resumen"]["Productos en los otros sitios"], 0)


class TestSupermallComoSitio(unittest.TestCase):
    def test_esta_en_site_configs(self):
        self.assertIn("supermall", SITE_CONFIGS)
        self.assertEqual(SITE_CONFIGS["supermall"]["site_label"], "Supermall.pe")

    def test_lleva_las_marcas_de_todos_los_demas_sitios(self):
        """Escritas a mano, una marca nueva en cualquier sitio se cargaria ahi
        y Supermall la rechazaria hasta que alguien se acordara de venir al
        archivo. Supermall existe justo para no depender de eso."""
        esperadas = {
            marca
            for clave, config in SITE_CONFIGS.items()
            if clave != "supermall"
            for marca in config["allowed_arti_brands"]
        }
        self.assertEqual(set(SITE_CONFIGS["supermall"]["allowed_arti_brands"]), esperadas)
        self.assertIn("VANS", esperadas)
        self.assertIn("COLUMBIA", esperadas)
        self.assertIn("HUSH PUPPIES", esperadas)

    def test_su_cola_sial_trae_su_propia_columna_de_product_id(self):
        """Sin ella el ID de Supermall no vuelve al sitio correcto -- es el
        mismo detalle que se arreglo para Patagonia."""
        cola = SITE_CONFIGS["supermall"]["sial_tail_columns"]
        self.assertIn("Porduct Id - Supermall.pe", cola)
        self.assertIn("Nuevo o Actualizar (Supermall.pe)", cola)

    def test_la_columna_de_bodega_activa_esta_en_la_cola(self):
        config = SITE_CONFIGS["supermall"]
        for columna in config["sial_active_columns"]:
            self.assertIn(columna, config["sial_tail_columns"],
                          "una bodega activa que no esta en la cola sale como columna vacia")

    def test_el_sial_le_pone_su_product_id_y_no_el_de_otro_sitio(self):
        from generate_columbia_matrixify import sial_tail_row
        fila = sial_tail_row(SITE_CONFIGS["supermall"], existing_id="9988", sku="SKU-1")
        self.assertEqual(fila["Porduct Id - Supermall.pe"], "9988")
        self.assertEqual(fila["Porduct Id - Columbia.pe"], "")

    def test_la_carpeta_de_fotos_la_manda_la_marca_no_el_sitio(self):
        """Supermall vende varias marcas: tomar la carpeta del sitio dejaria
        las fotos de todas en la misma. Es el caso de Rockford.pe."""
        from generate_columbia_matrixify import brand_image_config
        config = brand_image_config("COLUMBIA", SITE_CONFIGS["supermall"])
        self.assertEqual(config["image_folder"], "COLUMBIA")

    def test_no_pide_input_comercial_propio(self):
        """Supermall no recibe input comercial: recibe lo que ya se cargo en
        otro sitio. Si entrara, la plantilla le pondria a cada marca una
        columna PUBLICAR_SUPERMALL_PE que no decide nada, y una casilla que no
        hace nada es peor que no tenerla."""
        import app_matrixify as app
        for marca in ("Vans", "Columbia", "Patagonia"):
            sitios = {s["site_label"] for s in app.sites_for_commercial_brand(marca)}
            self.assertNotIn("Supermall.pe", sitios, marca)
            self.assertTrue(sitios, f"{marca} se quedo sin ningun sitio")

    def test_su_carga_remota_tiene_las_variables_en_el_workflow(self):
        """Un sitio en la app sin sus variables en el workflow falla con
        "faltan credenciales" y nada mas. Es la trampa de Hush Puppies."""
        from catalog_engine import _env_name
        workflow = (ROOT / ".github" / "workflows" / "carga-shopify.yml").read_text(encoding="utf-8")
        for sufijo in ("SHOP_DOMAIN", "ADMIN_API_ACCESS_TOKEN"):
            self.assertIn(f"{_env_name('supermall', sufijo)}:", workflow)

    def test_tiene_su_entrada_en_la_interfaz(self):
        """Sin ella el selector de sitio no sabe que logo ni que colores usar."""
        import app_matrixify as app
        self.assertIn("Supermall.pe", app.SITE_UI_CONFIG)


class TestSegundoDestino(unittest.TestCase):
    """La misma solicitud se carga tambien en el espejo, sin duplicar ticket."""

    def cuerpo(self, nombre):
        return ast.get_source_segment(FUENTE_APP, next(
            n for n in ast.walk(ARBOL_APP)
            if isinstance(n, ast.FunctionDef) and n.name == nombre))

    def test_el_espejo_acepta_las_solicitudes_de_cualquier_sitio(self):
        import app_matrixify as app
        ticket = {"sites": ["Vans.pe"], "brand": "Vans"}
        self.assertTrue(app._ticket_matches_active_site(ticket, SITE_CONFIGS["supermall"]))
        self.assertFalse(app._ticket_matches_active_site(ticket, SITE_CONFIGS["columbia"]))

    def test_el_cambio_de_sitio_no_escribe_el_widget_ya_dibujado(self):
        """Escribir `site_picker` despues de instanciar el selectbox levanta
        StreamlitAPIException, y el boton vive en el area principal, que se
        dibuja despues de la barra lateral."""
        cuerpo = self.cuerpo("ir_a_carga_en_espejo")
        self.assertIn("site_picker_pendiente", cuerpo)
        self.assertNotIn('st.session_state["site_picker"]', cuerpo)
        # Y la barra lateral tiene que consumirlo ANTES de dibujar el selector.
        pendiente = FUENTE_APP.index("site_picker_pendiente", FUENTE_APP.index("site_options = {"))
        selector = FUENTE_APP.index('key="site_picker"')
        self.assertLess(pendiente, selector)

    def test_el_boton_solo_sale_si_el_espejo_esta_configurado(self):
        """Un boton que no puede funcionar es peor que no tener boton."""
        cuerpo = self.cuerpo("sitio_espejo")
        self.assertIn("is_shopify_configured", cuerpo)

    def test_el_espejo_no_se_ofrece_a_si_mismo(self):
        cuerpo = self.cuerpo("render_carga_tambien_en_espejo")
        self.assertIn("== espejo_key", cuerpo)

    def test_lleva_la_misma_solicitud(self):
        cuerpo = self.cuerpo("render_carga_tambien_en_espejo")
        self.assertIn("carga_desde_solicitud", cuerpo)

    def test_el_intento_queda_en_la_auditoria(self):
        cuerpo = self.cuerpo("render_carga_tambien_en_espejo")
        self.assertIn("log_user_activity", cuerpo)

    def test_no_se_arman_dos_matrixify_a_la_vez(self):
        """Cada pasada arma el suyo: son ~450 MB de los 1.024 que Streamlit
        Cloud da POR APP. La segunda pasada es un rerun, no una rama mas."""
        cuerpo = self.cuerpo("render_carga_tambien_en_espejo")
        self.assertNotIn("build_columbia_matrixify", cuerpo)
        self.assertIn("st.rerun()", cuerpo)


class TestPantalla(unittest.TestCase):
    """Las claves que pide la pantalla tienen que existir en el motor.

    Es la leccion de `render_status_de_carga`: una clave mal escrita con
    `kpis["..."]` es un KeyError que tumba la pantalla, y con `.get()` es peor,
    porque devuelve None y el numero simplemente no aparece nunca.
    """

    def test_las_claves_del_resumen_existen(self):
        cuerpo = ast.get_source_segment(FUENTE_APP, next(
            n for n in ast.walk(ARBOL_APP)
            if isinstance(n, ast.FunctionDef) and n.name == "render_espejo_supermall"))
        disponibles = set(espejo.resumen([]))
        pedidas = set()
        for nodo in ast.walk(ast.parse(cuerpo.strip())):
            # resumen["..."]
            if isinstance(nodo, ast.Subscript) and isinstance(nodo.slice, ast.Constant) \
                    and isinstance(nodo.slice.value, str) \
                    and isinstance(nodo.value, ast.Name) and nodo.value.id == "resumen":
                pedidas.add(nodo.slice.value)
            # resumen.get("...")
            if isinstance(nodo, ast.Call) and isinstance(nodo.func, ast.Attribute) \
                    and nodo.func.attr == "get" and isinstance(nodo.func.value, ast.Name) \
                    and nodo.func.value.id == "resumen" and nodo.args \
                    and isinstance(nodo.args[0], ast.Constant):
                pedidas.add(nodo.args[0].value)
        self.assertTrue(pedidas, "la prueba no encontro ninguna clave: revisa que siga midiendo algo")
        self.assertEqual(pedidas - disponibles, set(),
                         f"la pantalla pide claves que el motor no devuelve: {pedidas - disponibles}")

    def test_la_pantalla_tiene_llamador(self):
        self.assertIn("render_espejo_supermall(tablas.get(\"espejo\"))", FUENTE_APP)
        self.assertIn("render_carga_tambien_en_espejo(brand_config)", FUENTE_APP)

    def test_el_espejo_sale_de_los_catalogos_ya_leidos(self):
        """Darle pantalla propia costaria leer los seis sitios otra vez."""
        cuerpo = ast.get_source_segment(FUENTE_APP, next(
            n for n in ast.walk(ARBOL_APP)
            if isinstance(n, ast.FunctionDef) and n.name == "construir_status_de_carga"))
        self.assertIn("espejo_de_supermall(catalogos", cuerpo)

    def test_el_motor_no_importa_streamlit(self):
        fuente = (ROOT / "engines" / "espejo_supermall.py").read_text(encoding="utf-8")
        self.assertNotIn("import streamlit", fuente)
        self.assertNotIn("import pandas", fuente)

    def test_no_se_vuelve_a_escribir_como_se_lee_un_producto(self):
        """La marca, el estado web y la identidad salen de `load_status`. Dos
        lectores del mismo producto se separan sin que nadie lo note."""
        fuente = (ROOT / "engines" / "espejo_supermall.py").read_text(encoding="utf-8")
        self.assertIn("from engines.load_status import", fuente)
        for prohibido in ('get("Status")', 'get("Published Online Store")', 'get("Tags")'):
            self.assertNotIn(prohibido, fuente,
                             f"'{prohibido}' es releer el producto por su cuenta")


if __name__ == "__main__":
    unittest.main(verbosity=2)
