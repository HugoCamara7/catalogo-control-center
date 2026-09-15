"""Cada carga completa deja una coleccion de revision en la tienda.

Ejecutar:  python scripts/test_coleccion_de_carga.py

Pedido por el usuario: "necesito que cada vez que termine de cargar un catalogo
completo se cree con todo ello una coleccion dentro de la web para poder verlo
[...] el nombre de la coleccion deberia de tener la fecha que se cargo, la
marca y el numero del ticket".

Las pruebas EJECUTAN: llaman a `process_sync_job_next_block` de punta a punta
contra un Shopify falso y comprueban QUE se escribio en la tienda. Es la
leccion de `start_suelto`, que tenia ocho pruebas leyendo su fuente y ninguna
la llamaba.
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pandas as pd  # noqa: E402

import app_matrixify as app  # noqa: E402
import shopify_api  # noqa: E402
from engines import coleccion_de_carga as motor  # noqa: E402

CONFIG = {"shop_domain": "tienda-falsa.myshopify.com", "admin_access_token": "shpat_falso",
          "api_version": "2026-04"}
MARCA = "Metafield: custom.marca [single_line_text_field]"


class TiendaFalsa:
    """Responde como Shopify y guarda lo que se le manda."""

    def __init__(self, coleccion_existente=None, falla_al_crear=False, publica=True):
        self.colecciones = {}
        self.agregados = []
        self.creadas = []
        self.publicadas = []
        self.existente = coleccion_existente
        self.falla_al_crear = falla_al_crear
        self.publica = publica

    def __call__(self, shop_domain, token, query, variables=None, api_version=None,
                 timeout=20, max_retries=2):
        variables = variables or {}
        if "collectionByHandle" in query or "collection(handle:" in query:
            if self.existente and variables.get("handle") == self.existente.get("handle"):
                return {"collectionByHandle": dict(self.existente)}
            return {"collectionByHandle": None}
        if "collectionCreate" in query:
            if self.falla_al_crear:
                raise shopify_api.ShopifyApiError("la tienda dijo que no")
            entrada = variables["entrada"]
            identificador = "gid://shopify/Collection/%d" % (len(self.creadas) + 1)
            self.creadas.append(dict(entrada))
            self.colecciones[identificador] = dict(entrada)
            return {"collectionCreate": {
                "collection": {"id": identificador, "handle": entrada.get("handle"),
                               "title": entrada.get("title"),
                               "sortOrder": entrada.get("sortOrder")},
                "userErrors": []}}
        if "collectionAddProductsV2" in query:
            self.agregados.append(list(variables["productIds"]))
            return {"collectionAddProductsV2": {
                "job": {"id": "gid://shopify/Job/a%d" % len(self.agregados), "done": True},
                "userErrors": []}}
        if "job(id" in query:
            return {"job": {"id": variables["id"], "done": True}}
        if "publications(" in query:
            if not self.publica:
                return {"publications": {"nodes": []}}
            return {"publications": {"nodes": [
                {"id": "gid://shopify/Publication/1", "name": "Online Store"}]}}
        if "publishablePublish" in query:
            self.publicadas.append(variables["id"])
            return {"publishablePublish": {"publishable": {"id": variables["id"]},
                                           "userErrors": []}}
        return {}


class ConTiendaFalsa(unittest.TestCase):
    def setUp(self):
        self.tienda = TiendaFalsa()
        self._real = shopify_api.graphql_request
        shopify_api.graphql_request = self.tienda
        self._sleep = shopify_api.time.sleep
        shopify_api.time.sleep = lambda _s: None

    def tearDown(self):
        shopify_api.graphql_request = self._real
        shopify_api.time.sleep = self._sleep

    def usar(self, tienda):
        self.tienda = tienda
        shopify_api.graphql_request = tienda


def job_terminado(result_rows, mode="complete", ticket="CAT-0042", marca="Vans",
                  created_at="2026-09-15 10:30:00"):
    return {
        "id": "vans_complete_20260915", "site_key": "vans", "mode": mode,
        "status": "completed", "ticket": ticket, "marca": marca,
        "created_at": created_at, "result_rows": list(result_rows), "events": [],
    }


def fila(handle, identificador="1", resultado="OK"):
    return {"Handle": handle, "ID": identificador, "Resultado": resultado}


# =========================================================================
# 1. El nombre
# =========================================================================
class TestElNombre(unittest.TestCase):

    def test_lleva_fecha_marca_y_solicitud(self):
        self.assertEqual(
            motor.nombre_de_coleccion("2026-09-15", "Vans", "CAT-0042"),
            "Carga 2026-09-15 · Vans · CAT-0042")

    def test_la_fecha_va_en_ISO_para_que_ordene_cronologicamente(self):
        """El admin lista las colecciones por orden alfabetico."""
        nombres = sorted(motor.nombre_de_coleccion(f, "Vans", "CAT-1")
                         for f in ("2026-09-15", "2025-12-01", "2026-01-02"))
        self.assertEqual([n.split(" ")[1] for n in nombres],
                         ["2025-12-01", "2026-01-02", "2026-09-15"])

    def test_sin_solicitud_no_deja_un_hueco(self):
        """`Carga 2026-09-15 ·  · CAT-` se lee como un error de la app."""
        self.assertEqual(motor.nombre_de_coleccion("2026-09-15", "Vans", ""),
                         "Carga 2026-09-15 · Vans")
        self.assertEqual(motor.nombre_de_coleccion("2026-09-15", "", ""),
                         "Carga 2026-09-15")

    def test_el_handle_es_el_mismo_para_el_mismo_nombre(self):
        """Es lo que hace que dos tandas de la misma carga acaben en la MISMA
        coleccion: el runner se queda sin tiempo y encadena otra."""
        titulo = motor.nombre_de_coleccion("2026-09-15", "Vans", "CAT-0042")
        self.assertEqual(motor.handle_de_coleccion(titulo), "carga-2026-09-15-vans-cat-0042")
        self.assertEqual(motor.handle_de_coleccion(titulo),
                         motor.handle_de_coleccion(titulo))

    def test_el_handle_pliega_acentos_y_no_deja_simbolos(self):
        self.assertEqual(
            motor.handle_de_coleccion("Carga 2026-09-15 · Hush Puppies · CAT-1"),
            "carga-2026-09-15-hush-puppies-cat-1")

    def test_la_marca_solo_sale_si_la_carga_trae_UNA(self):
        """Rockford.pe vende cuatro marcas y Supermall diez: poner la primera
        seria mentir. Se pone la etiqueta del sitio, que es cierta."""
        self.assertEqual(motor.marca_de_la_carga(["Vans", "Vans"], "Vans.pe"), "Vans")
        self.assertEqual(motor.marca_de_la_carga(["Columbia", "Sorel"], "Rockford.pe"),
                         "Rockford.pe")
        self.assertEqual(motor.marca_de_la_carga([], "Vans.pe"), "Vans.pe")

    def test_el_titulo_no_pasa_del_tope_de_shopify(self):
        largo = motor.nombre_de_coleccion("2026-09-15", "M" * 400, "CAT-1")
        self.assertLessEqual(len(largo), motor.MAXIMO_TITULO)


# =========================================================================
# 2. Que productos entran
# =========================================================================
class TestQueEntra(unittest.TestCase):

    def test_solo_los_que_quedaron_en_la_tienda(self):
        """Un producto con ERROR no esta cargado: meterlo en la coleccion de
        revision seria decir que si."""
        gids, resumen = motor.productos_de_la_carga([
            fila("a", "1", "OK"), fila("b", "2", "PARCIAL"), fila("c", "3", "ERROR")])
        self.assertEqual(gids, ["gid://shopify/Product/1", "gid://shopify/Product/2"])
        self.assertEqual(resumen["con_error"], ["c"])

    def test_los_PARCIAL_entran_porque_estan_en_la_tienda(self):
        """Estan cargados, con avisos: es justo lo que hay que ir a mirar."""
        gids, _ = motor.productos_de_la_carga([fila("a", "1", "PARCIAL")])
        self.assertEqual(gids, ["gid://shopify/Product/1"])

    def test_un_producto_con_varias_filas_entra_si_ALGUNA_se_cargo(self):
        """El mismo producto puede tener una fila OK y otra de una foto que
        fallo; dejarlo fuera de la revision seria al reves de lo que hace falta."""
        gids, resumen = motor.productos_de_la_carga([
            fila("a", "1", "OK"), fila("a", "1", "ERROR")])
        self.assertEqual(gids, ["gid://shopify/Product/1"])
        self.assertEqual(resumen["con_error"], [])

    def test_sin_id_de_shopify_no_se_puede_agregar_y_se_dice(self):
        """Callarlo dejaria la coleccion incompleta sin que nadie supiera
        cuales faltaron."""
        gids, resumen = motor.productos_de_la_carga([fila("a", "", "OK")])
        self.assertEqual(gids, [])
        self.assertEqual(resumen["sin_id"], ["a"])

    def test_no_repite_un_producto(self):
        gids, _ = motor.productos_de_la_carga([fila("a", "1"), fila("a", "1")])
        self.assertEqual(gids, ["gid://shopify/Product/1"])

    def test_el_gid_sale_del_ID_que_devolvio_la_carga(self):
        """Asi no cuesta ni una lectura mas a Shopify."""
        gids, _ = motor.productos_de_la_carga([
            fila("a", "gid://shopify/Product/9"), fila("b", "7")])
        self.assertEqual(gids, ["gid://shopify/Product/9", "gid://shopify/Product/7"])


# =========================================================================
# 3. La escritura en la tienda
# =========================================================================
class TestSeEscribeEnLaTienda(ConTiendaFalsa):

    def test_crea_la_coleccion_la_llena_y_la_publica(self):
        job = app.crear_coleccion_de_carga(
            job_terminado([fila("a", "1"), fila("b", "2")]), CONFIG)
        registro = job["coleccion"]
        self.assertEqual(registro["estado"], "ok")
        self.assertEqual(registro["titulo"], "Carga 2026-09-15 · Vans · CAT-0042")
        self.assertEqual(registro["productos"], 2)
        self.assertEqual(self.tienda.creadas[0]["title"], registro["titulo"])
        self.assertEqual(self.tienda.agregados,
                         [["gid://shopify/Product/1", "gid://shopify/Product/2"]])
        self.assertEqual(self.tienda.publicadas, ["gid://shopify/Collection/1"])

    def test_nace_MANUAL(self):
        """Con cualquier otro orden Shopify reordena por su cuenta: el orden de
        la coleccion dejaria de ser el de la carga."""
        app.crear_coleccion_de_carga(job_terminado([fila("a", "1")]), CONFIG)
        self.assertEqual(self.tienda.creadas[0]["sortOrder"], "MANUAL")

    def test_no_hace_falta_ni_un_movimiento_de_reordenamiento(self):
        """`collectionAddProductsV2` agrega al FINAL, asi que en MANUAL el
        orden de la coleccion YA es el de la carga."""
        import ast
        import inspect
        import textwrap
        app.crear_coleccion_de_carga(
            job_terminado([fila("a", "1"), fila("b", "2"), fila("c", "3")]), CONFIG)
        llamadas = {
            nodo.func.id
            for nodo in ast.walk(ast.parse(textwrap.dedent(
                inspect.getsource(app.crear_coleccion_de_carga))))
            if isinstance(nodo, ast.Call) and isinstance(nodo.func, ast.Name)
        }
        self.assertNotIn("collection_reorder_products", llamadas)
        self.assertEqual(self.tienda.agregados[0],
                         ["gid://shopify/Product/1", "gid://shopify/Product/2",
                          "gid://shopify/Product/3"])

    def test_reusa_la_coleccion_si_ya_existe(self):
        """Dos tandas de la MISMA carga tienen que acabar en la misma
        coleccion, no en dos."""
        self.usar(TiendaFalsa(coleccion_existente={
            "id": "gid://shopify/Collection/77",
            "handle": "carga-2026-09-15-vans-cat-0042"}))
        job = app.crear_coleccion_de_carga(job_terminado([fila("a", "1")]), CONFIG)
        self.assertEqual(job["coleccion"]["id"], "gid://shopify/Collection/77")
        self.assertTrue(job["coleccion"]["reusada"])
        self.assertEqual(self.tienda.creadas, [])

    def test_no_la_crea_dos_veces_en_el_mismo_job(self):
        job = app.crear_coleccion_de_carga(job_terminado([fila("a", "1")]), CONFIG)
        app.crear_coleccion_de_carga(job, CONFIG)
        self.assertEqual(len(self.tienda.creadas), 1)

    def test_reintentar_errores_mete_los_que_faltaban_en_la_MISMA_coleccion(self):
        """"Reintentar errores" vuelve a cargar los que fallaron: esos tienen
        que acabar en la coleccion de revision, no fuera de ella."""
        job = app.crear_coleccion_de_carga(
            job_terminado([fila("a", "1"), fila("b", "2", "ERROR")]), CONFIG)
        self.assertEqual(job["coleccion"]["productos"], 1)
        # El reintento deja la fila de "b" ya en OK.
        job["result_rows"].append(fila("b", "2", "OK"))
        job = app.crear_coleccion_de_carga(job, CONFIG)
        self.assertEqual(job["coleccion"]["productos"], 2)
        self.assertEqual(len(self.tienda.creadas), 1, "no crea una segunda coleccion")
        self.assertEqual(self.tienda.agregados[-1],
                         ["gid://shopify/Product/1", "gid://shopify/Product/2"])

    def test_sin_productos_nuevos_no_gasta_ni_un_viaje(self):
        job = app.crear_coleccion_de_carga(job_terminado([fila("a", "1")]), CONFIG)
        agregados = len(self.tienda.agregados)
        app.crear_coleccion_de_carga(job, CONFIG)
        self.assertEqual(len(self.tienda.agregados), agregados)

    def test_una_carga_PARCIAL_no_crea_coleccion(self):
        """Toca un campo de productos que ya estaban cargados: no hay "lo que
        se cargo hoy" que revisar, y dejaria una por cada mantenimiento."""
        job = app.crear_coleccion_de_carga(
            job_terminado([fila("a", "1")], mode="partial_body"), CONFIG)
        self.assertNotIn("coleccion", job)
        self.assertEqual(self.tienda.creadas, [])

    def test_una_carga_sin_productos_cargados_no_crea_nada_y_lo_dice(self):
        job = app.crear_coleccion_de_carga(
            job_terminado([fila("a", "1", "ERROR")]), CONFIG)
        self.assertEqual(job["coleccion"]["estado"], "sin productos")
        self.assertEqual(self.tienda.creadas, [])

    def test_un_fallo_NO_tumba_la_carga(self):
        """Una carga que ya escribio miles de productos no se deshace porque
        falle una coleccion. Misma regla que los correos."""
        self.usar(TiendaFalsa(falla_al_crear=True))
        job = job_terminado([fila("a", "1")])
        job["status"] = "completed"
        devuelto = app.crear_coleccion_de_carga(job, CONFIG)
        self.assertEqual(devuelto["status"], "completed")
        self.assertEqual(devuelto["coleccion"]["estado"], "error")
        self.assertIn("la tienda dijo que no", devuelto["coleccion"]["detalle"])

    def test_si_no_se_puede_publicar_la_coleccion_SIGUE_creada(self):
        """Existe y se lleno; lo que falta es que la vea alguien, y eso se
        dice en vez de dejar que lo descubra quien abra la URL."""
        self.usar(TiendaFalsa(publica=False))
        job = app.crear_coleccion_de_carga(job_terminado([fila("a", "1")]), CONFIG)
        self.assertEqual(job["coleccion"]["estado"], "ok")
        self.assertFalse(job["coleccion"]["publicada"])
        self.assertIn("No se pudo publicar", job["coleccion"]["aviso"])

    def test_deja_la_url_para_poder_abrirla(self):
        job = app.crear_coleccion_de_carga(job_terminado([fila("a", "1")]), CONFIG)
        self.assertEqual(
            job["coleccion"]["url"],
            "https://tienda-falsa.myshopify.com/collections/carga-2026-09-15-vans-cat-0042")

    def test_los_productos_van_en_bloques_de_250(self):
        """El tope es de Shopify: los input objects de GraphQL estan limitados
        a 250 elementos."""
        filas = [fila(f"p{i}", str(i)) for i in range(1, 301)]
        app.crear_coleccion_de_carga(job_terminado(filas), CONFIG)
        self.assertEqual([len(b) for b in self.tienda.agregados], [250, 50])


# =========================================================================
# 4. El enganche: las DOS formas de cargar lo heredan
# =========================================================================
class TestElEnganche(ConTiendaFalsa):
    """Esta en `process_sync_job_next_block`, no en la pantalla: por ahi salen
    el panel de bloques de la sesion Y el runner de GitHub Actions."""

    def setUp(self):
        super().setUp()
        self._run = app._sync_job_run_one_product
        app._sync_job_run_one_product = self._carga_falsa

    def tearDown(self):
        app._sync_job_run_one_product = self._run
        super().tearDown()

    @staticmethod
    def _carga_falsa(shopify_config, source_df, product_key, mode,
                     activate_inventory_locations, progress_callback=None, keys=None):
        numero = str(abs(hash(product_key)) % 1000)
        return pd.DataFrame([{"Handle": product_key, "ID": numero, "Resultado": "OK"}])

    def _matrixify(self, handles):
        return pd.DataFrame([{
            "Handle": h, "Title": h.title(), "Variant SKU": f"SKU{i}",
            "Metafield: custom.codigo_modelo_color [id]": f"AB{i}-010",
            MARCA: "Vans",
        } for i, h in enumerate(handles, 1)])

    def test_al_terminar_el_job_la_coleccion_esta_creada(self):
        job = app._create_sync_job("vans", "complete", self._matrixify(["a", "b"]),
                                   batch_size=10, ticket="CAT-0042", marca="Vans")
        terminado = app.process_sync_job_next_block(job["id"], CONFIG)
        self.assertEqual(terminado["status"], "completed")
        self.assertEqual(terminado["coleccion"]["estado"], "ok")
        self.assertEqual(terminado["coleccion"]["productos"], 2)
        self.assertEqual(len(self.tienda.creadas), 1)

    def test_no_se_crea_hasta_que_NO_QUEDA_NADA_pendiente(self):
        """Creada en el primer bloque, la coleccion de una carga de 8.000
        productos tendria 20."""
        job = app._create_sync_job("vans", "complete", self._matrixify(["a", "b", "c", "d"]),
                                   batch_size=2, ticket="CAT-1", marca="Vans")
        primero = app.process_sync_job_next_block(job["id"], CONFIG)
        self.assertEqual(primero["status"], "pending")
        self.assertNotIn("coleccion", primero)
        self.assertEqual(self.tienda.creadas, [])
        segundo = app.process_sync_job_next_block(job["id"], CONFIG)
        self.assertEqual(segundo["coleccion"]["productos"], 4)

    def test_el_job_guarda_la_solicitud_y_la_marca(self):
        """De ahi sale el nombre, y por eso viajan en el REGISTRO y no en la
        pantalla: el runner no tiene pantalla a la que preguntarle."""
        job = app._create_sync_job("vans", "complete", self._matrixify(["a"]),
                                   ticket="CAT-0042", marca="Vans")
        self.assertEqual(job["ticket"], "CAT-0042")
        self.assertEqual(job["marca"], "Vans")

    def test_las_marcas_salen_del_metacampo_no_del_vendor(self):
        """El `Vendor` es el de la TIENDA (`rockfordpe`), el mismo para todas
        sus marcas."""
        frame = self._matrixify(["a", "b"])
        frame["Vendor"] = "vanspe"
        self.assertEqual(app.marcas_del_matrixify(frame), ["Vans"])
        frame.loc[1, MARCA] = "Columbia"
        self.assertEqual(app.marcas_del_matrixify(frame), ["Vans", "Columbia"])

    def test_una_carga_parcial_que_termina_no_deja_coleccion(self):
        job = app._create_sync_job("vans", "partial_body", self._matrixify(["a"]),
                                   ticket="CAT-1", marca="Vans")
        terminado = app.process_sync_job_next_block(job["id"], CONFIG)
        self.assertEqual(terminado["status"], "completed")
        self.assertNotIn("coleccion", terminado)


# =========================================================================
# 5. La pantalla
# =========================================================================
class TestLaPantalla(unittest.TestCase):

    def test_hay_UN_solo_dibujante_y_lo_llaman_los_dos_paneles(self):
        """Escrito dos veces, uno de los dos acabaria diciendo otra cosa."""
        import inspect
        self.assertIn("render_coleccion_de_carga(job)",
                      inspect.getsource(app.render_estado_carga_remota))
        self.assertIn("render_coleccion_de_carga(job)",
                      inspect.getsource(app.render_persistent_sync_job_panel))

    def test_el_motor_no_importa_streamlit(self):
        """`engines/` nunca importa Streamlit: esto lo usa tambien el runner."""
        ruta = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                            "engines", "coleccion_de_carga.py")
        with open(ruta, encoding="utf-8") as archivo:
            self.assertNotIn("streamlit", archivo.read())

    def test_el_escritor_tampoco_toca_streamlit(self):
        """Desde un hilo de runner no hay Streamlit al que hablarle.

        Se mira el ARBOL, no el texto: un docstring que nombra `st.` no es una
        llamada a Streamlit. Es la misma correccion que ya se hizo con la
        prueba de `st.rerun()` en el menu."""
        import ast
        import inspect
        import textwrap
        arbol = ast.parse(textwrap.dedent(inspect.getsource(app.crear_coleccion_de_carga)))
        for nodo in ast.walk(arbol):
            if isinstance(nodo, ast.Attribute) and isinstance(nodo.value, ast.Name):
                self.assertNotEqual(nodo.value.id, "st",
                                    f"llama a st.{nodo.attr}")


if __name__ == "__main__":
    unittest.main(verbosity=1)
