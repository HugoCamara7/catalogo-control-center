"""Los KPI de catalogo y de Status, y lo que costaba leerlos de BigQuery.

Ejecutar:  python scripts/test_kpis_y_bigquery.py

Las pruebas EJECUTAN el codigo: arman un maestro, un stock y un catalogo de
Shopify falsos y miran los numeros que salen. Leer el codigo no es ejecutarlo
-- es la leccion de `start_suelto`, que tenia ocho pruebas leyendo su fuente y
ninguna la llamaba.

Lo que fija
-----------

RENDIMIENTO DE BIGQUERY

1. **El EAN se completaba con decenas de consultas que el dashboard no usa.**
   `load_catalog_kpi_result` leia el maestro con
   `enrich_arti_barcodes_from_bigquery_table`, que consulta el Maestro de
   Productos en tandas de 5.000 SKU -- una consulta por tanda -- sobre el
   maestro ENTERO. Ningun KPI lee `CodBarras`: lo usa solo la hoja "Variantes a
   crear" del Excel de modelos no creados, que son unos cientos de codigos.
   Ahora se completa alli y en una sola consulta.

2. **La consulta de stock se bajaba entera y se filtraba en Python.** Las
   bodegas eComm de un sitio son un punado de las ~400 de la tabla central. El
   filtro va ahora en el WHERE, y es deliberadamente MAS LAXO que el de Python
   -- cualquier numero del campo vale, y una fila sin `codigo_tienda` pasa
   igual, porque ahi la bodega sale de `CONCAT_TIENDA` --, asi que quien decide
   que entra sigue siendo `normalize_warehouse_code`.

3. **Las tres lecturas eran secuenciales.** ARTI, stock y catalogo son espera
   de red: el dashboard tardaba la SUMA pudiendo tardar la mas lenta.

KPIs DE CATALOGO

4. **El universo es el maestro ARTI y no se decia.** Un producto que esta en
   Shopify y no en el maestro no aparecia en ningun numero, asi que "Modelos ya
   creados en Shopify" no cuadraba con el admin y nadie sabia por que.

5. **La causa principal mandaba al equipo equivocado.** "Sin stock Shopify" se
   evaluaba ANTES que "no activo" y "no publicado", asi que un producto en
   borrador -- que todavia no tiene stock sincronizado -- se reportaba como
   problema de stock.

6. **Cuatro claves para el mismo numero.** `modelos_listos_tienda`,
   `modelos_listos_venta` y `modelos_visibles_web` valian lo mismo y dos no las
   leia nadie.

KPIs DE STATUS DE CARGA

7. **"No visibles" metia los ARCHIVADOS**, que estan apagados a proposito, con
   los borradores y los activos sin publicar, que son trabajo pendiente.

8. **Tres bases de conteo distintas en la misma pantalla** y ninguna explicada:
   el titular contaba fichas (sitio x producto) y la pestana de abajo productos
   unicos.

9. **El panel no cruzaba nunca las solicitudes contra el catalogo real.**
   Comparaba solicitudes contra solicitudes: una marcada "Finalizada" cuyos
   productos no estaban en ninguna tienda se contaba como terminada.

10. **"Publicado en Online Store" se decidia con DOS reglas distintas.** Con el
    campo vacio, los KPI de catalogo miraban `Online Store URL` y el Status de
    carga daba por no publicado: el mismo producto salia visible en una
    pantalla y no visible en la otra.
"""
import ast
import inspect
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pandas as pd  # noqa: E402

import app_matrixify as app  # noqa: E402
from engines import load_status as ls  # noqa: E402


# --- datos de juguete, pero con la forma de los de verdad -----------------
def maestro(modelos=6, tallas=("S", "M", "L"), marca="COLUMBIA"):
    filas = []
    for i in range(modelos):
        mod = f"AB{i:04d}-N01"
        for t_i, talla in enumerate(tallas):
            filas.append({
                "CODINT_MA": f"{900000 + i * 10 + t_i}",
                "COD MOD COL": mod, "Mod-Col": mod, "TALNUM_MA": talla,
                "MARCA_MA": marca, "DESCRIPCION_MA": f"Producto {i}",
                "ColorNombre": "NEGRO", "Genero": "MASCULINO", "CodBarras": "",
                "TipoProducto": "Casacas", "Precio": "199.90",
            })
    return pd.DataFrame(filas)


def stock_de(arti, bodega="320", unidades=5):
    filas = [{
        "fecha_corte": "2026-09-13", "id_producto": r["CODINT_MA"],
        "key_producto": f'{r["Mod-Col"]}-{r["TALNUM_MA"]}',
        "codigo_tienda": bodega, "stock_tiendas": unidades, "stock_bodega": 0,
        "stock_total": unidades,
    } for _, r in arti.iterrows()]
    return pd.DataFrame(filas)


def producto_shopify(mod_col, estado="ACTIVE", publicado="SI", url="", fotos=1,
                     tallas=("S", "M", "L"), stock=4, precio="199"):
    return {
        "Mod-Col": mod_col, "Handle": (mod_col or "sin-codigo").lower(), "Title": mod_col,
        "Vendor": "columbiape", "Type": "Casacas", "Status": estado,
        "Published Online Store": publicado, "Online Store URL": url,
        "Image Src": "; ".join(f"https://x/{n}.jpg" for n in range(fotos)),
        "Variants": [{
            "Variant SKU": f"sku{mod_col}{t}", "Variant Price": precio,
            "Variant Inventory Qty": stock, "Option1 Value": t,
        } for t in tallas],
    }


BRAND = app.get_brand_config("columbia")


def _rama_de_analizar():
    """El nodo `if analyze_clicked:` de `main()`, para mirarlo por dentro."""
    arbol = ast.parse(inspect.getsource(app.main))
    for nodo in ast.walk(arbol):
        if (isinstance(nodo, ast.If) and isinstance(nodo.test, ast.Name)
                and nodo.test.id == "analyze_clicked"):
            return nodo
    raise AssertionError("no encontre `if analyze_clicked:` en main()")


def kpis_de(arti, stock, productos, **extra):
    return app.build_catalog_kpis(arti, stock, productos, BRAND, **extra)


# --- 1. el EAN ------------------------------------------------------------
class TestElEanNoSeCompletaSobreElMaestroEntero(unittest.TestCase):
    """Decenas de consultas a BigQuery para una columna que ningun KPI lee."""

    def test_read_arti_for_app_con_ean_false_no_consulta_el_maestro(self):
        llamadas = []
        original_source = app.read_arti_source
        original_ean = app.enrich_arti_barcodes_from_bigquery_table
        app.read_arti_source = lambda **kw: (maestro(), "BigQuery: fake")

        def espia(df, config):
            llamadas.append(len(df))
            return df, "no deberia llamarse"

        app.enrich_arti_barcodes_from_bigquery_table = espia
        try:
            df, fuente = app.read_arti_for_app(BRAND, con_ean=False, bigquery_config={"x": 1})
        finally:
            app.read_arti_source = original_source
            app.enrich_arti_barcodes_from_bigquery_table = original_ean
        self.assertEqual(llamadas, [], "con con_ean=False no se consulta el maestro de productos")
        self.assertEqual(fuente, "BigQuery: fake")
        self.assertFalse(df.empty)

    def test_con_ean_true_sigue_completandolo(self):
        """La carga completa lo necesita y ahi va acotado por mod_cols."""
        llamadas = []
        original_source = app.read_arti_source
        original_ean = app.enrich_arti_barcodes_from_bigquery_table
        app.read_arti_source = lambda **kw: (maestro(), "BigQuery: fake")
        app.enrich_arti_barcodes_from_bigquery_table = lambda df, c: (llamadas.append(1) or (df, "EAN ok"))
        try:
            _df, fuente = app.read_arti_for_app(BRAND, con_ean=True, bigquery_config={"x": 1})
        finally:
            app.read_arti_source = original_source
            app.enrich_arti_barcodes_from_bigquery_table = original_ean
        self.assertEqual(len(llamadas), 1)
        self.assertIn("EAN ok", fuente)

    def test_el_ean_se_completa_solo_para_los_modelos_que_faltan(self):
        arti = maestro(modelos=6)
        stock = stock_de(arti)
        # Solo 2 de los 6 estan en Shopify: los otros 4 son los que faltan.
        productos = [producto_shopify("AB0000-N01"), producto_shopify("AB0001-N01")]
        recibidos = {}

        def enriquecer(filas):
            recibidos["filas"] = len(filas)
            recibidos["modelos"] = sorted(set(filas["Mod-Col KPI"]))
            copia = filas.copy()
            copia["CodBarras"] = "7790000000001"
            return copia

        resultado = kpis_de(arti, stock, productos, enriquecer_ean=enriquecer)
        self.assertEqual(len(recibidos["modelos"]), 4, "solo los modelos que faltan por crear")
        self.assertLess(recibidos["filas"], len(arti), "no se enriquece el maestro entero")
        variantes = resultado["missing_models_variants"]
        self.assertTrue((variantes["EAN / Barcode"] == "7790000000001").all())

    def test_si_el_enriquecido_falla_la_hoja_sale_igual(self):
        """Un fallo de BigQuery no puede tumbar el dashboard entero."""
        arti = maestro(modelos=3)
        productos = [producto_shopify("AB0000-N01")]

        def revienta(_filas):
            raise RuntimeError("permisos")

        resultado = kpis_de(arti, stock_de(arti), productos, enriquecer_ean=revienta)
        self.assertFalse(resultado["missing_models_input"].empty)
        self.assertTrue((resultado["missing_models_variants"]["EAN / Barcode"] == "").all())


# --- 2. el stock acotado a las bodegas del sitio --------------------------
class TestLaConsultaDeStockSeAcotaEnElWhere(unittest.TestCase):
    def test_sin_bodegas_no_se_acota(self):
        self.assertEqual(app._stock_query_acotada_a_bodegas("SELECT 1", []), "")
        self.assertEqual(app._stock_query_acotada_a_bodegas("SELECT 1", ["", "0"]), "")

    def test_con_bodegas_envuelve_la_consulta_y_nombra_los_codigos(self):
        sql = app._stock_query_acotada_a_bodegas("SELECT 1", ["13", "4", "6"])
        self.assertIn("SELECT 1", sql, "la consulta original viaja entera dentro")
        self.assertIn("IN (4, 6, 13)", sql, "ordenados y sin repetidos")
        self.assertIn("codigo_tienda IS NULL", sql, "una fila sin bodega sigue pasando")

    def test_el_filtro_sql_es_mas_laxo_que_el_de_python_nunca_mas_estricto(self):
        """Quien decide que entra sigue siendo `normalize_warehouse_code`."""
        sql = app._stock_query_acotada_a_bodegas("SELECT 1", ["13"])
        # Se emula el WHERE con las mismas piezas: cualquier numero del campo.
        import re

        def pasa_el_sql(valor):
            texto = "" if valor is None else str(valor)
            if not texto.strip():
                return True
            return any(n.isdigit() and int(n) == 13 for n in re.findall(r"[0-9]+", texto))

        self.assertIn("REGEXP_EXTRACT_ALL", sql)
        for valor in ("13", "13.0", "0013", "TDA-13", "999-13", " ", "", None, "4"):
            acepta_python = app.normalize_warehouse_code(valor) == "13"
            if acepta_python:
                self.assertTrue(pasa_el_sql(valor), f"{valor!r} lo acepta Python y el SQL lo tiraba")

    def test_una_consulta_acotada_vacia_se_repite_sin_acotar(self):
        """Vacia no puede significar 'la tabla no respondio'."""
        ejecutadas = []

        class ClienteFalso:
            def query(self, texto, **kw):
                ejecutadas.append(texto)
                return texto

        def a_dataframe(texto):
            if "REGEXP_EXTRACT_ALL" in texto:
                return pd.DataFrame(columns=["fecha_corte", "key_producto", "codigo_tienda",
                                             "stock_tiendas", "stock_bodega", "stock_total"])
            return pd.DataFrame([{
                "fecha_corte": "2026-09-13", "id_producto": "1", "key_producto": "AB-1",
                "codigo_tienda": "320", "stock_tiendas": 2, "stock_bodega": 0, "stock_total": 2,
            }])

        original = app.bigquery_a_dataframe
        app.bigquery_a_dataframe = a_dataframe
        try:
            import google.cloud.bigquery as bq  # noqa: F401
        except Exception:
            app.bigquery_a_dataframe = original
            self.skipTest("sin google-cloud-bigquery instalado")
        try:
            sys.modules["google.cloud.bigquery"].Client = lambda **kw: ClienteFalso()
            df = app.read_current_stock_from_bigquery({}, bodegas=["320"])
        finally:
            app.bigquery_a_dataframe = original
        self.assertEqual(len(ejecutadas), 2, "se reintenta sin acotar")
        self.assertFalse(df.empty)


# --- 3. las tres lecturas van en paralelo --------------------------------
class TestLasLecturasVanEnParalelo(unittest.TestCase):
    def test_arti_y_stock_no_esperan_al_catalogo(self):
        import threading
        import time

        orden = []
        arranques = []
        lock = threading.Lock()

        def lenta(nombre, salida):
            def _fn(*a, **kw):
                with lock:
                    arranques.append((nombre, time.perf_counter()))
                time.sleep(0.4)
                with lock:
                    orden.append(nombre)
                return salida
            return _fn

        arti = maestro(modelos=2)
        originales = (app.read_arti_for_app, app.read_current_stock_from_bigquery,
                      app.leer_catalogo_del_sitio, app.get_bigquery_config,
                      app.ecomm_stock_rule_codes_for_site)
        app.read_arti_for_app = lenta("arti", (arti, "BigQuery"))
        app.read_current_stock_from_bigquery = lenta("stock", stock_de(arti))
        app.leer_catalogo_del_sitio = lenta("shopify", [producto_shopify("AB0000-N01")])
        app.get_bigquery_config = lambda: {"project_id": "x"}
        app.ecomm_stock_rule_codes_for_site = lambda _b: ["320"]
        inicio = time.perf_counter()
        try:
            app.load_catalog_kpi_result(BRAND, {"shop_domain": "x"})
        finally:
            (app.read_arti_for_app, app.read_current_stock_from_bigquery,
             app.leer_catalogo_del_sitio, app.get_bigquery_config,
             app.ecomm_stock_rule_codes_for_site) = originales
        total = time.perf_counter() - inicio
        self.assertEqual(sorted(orden), ["arti", "shopify", "stock"])
        self.assertLess(total, 1.0, f"secuencial serian 1,2 s; tardo {total:.2f} s")

    def test_lo_que_pasa_por_streamlit_se_resuelve_fuera_del_hilo(self):
        """`st.session_state` y `st.cache_data` no se pueden tocar desde un hilo."""
        import threading

        principal = threading.get_ident()
        hilos = {}
        arti = maestro(modelos=2)
        originales = (app.read_arti_for_app, app.read_current_stock_from_bigquery,
                      app.leer_catalogo_del_sitio, app.get_bigquery_config,
                      app.ecomm_stock_rule_codes_for_site)

        def anota(nombre, salida):
            def _fn(*a, **kw):
                hilos[nombre] = threading.get_ident()
                return salida
            return _fn

        app.read_arti_for_app = anota("arti", (arti, "BigQuery"))
        app.read_current_stock_from_bigquery = anota("stock", stock_de(arti))
        app.leer_catalogo_del_sitio = anota("shopify", [producto_shopify("AB0000-N01")])
        app.get_bigquery_config = lambda: hilos.setdefault("config", threading.get_ident()) and {} or {}
        app.ecomm_stock_rule_codes_for_site = lambda _b: (
            hilos.setdefault("bodegas", threading.get_ident()) and ["320"] or ["320"])
        try:
            app.load_catalog_kpi_result(BRAND, {"shop_domain": "x"})
        finally:
            (app.read_arti_for_app, app.read_current_stock_from_bigquery,
             app.leer_catalogo_del_sitio, app.get_bigquery_config,
             app.ecomm_stock_rule_codes_for_site) = originales
        self.assertEqual(hilos["config"], principal, "get_bigquery_config lee st.secrets")
        self.assertEqual(hilos["bodegas"], principal, "ecomm_stock_rule_codes_for_site pasa por st.cache_data")
        self.assertEqual(hilos["shopify"], principal, "leer_catalogo_del_sitio toca st.session_state")


# --- 4. el universo de los KPI de catalogo -------------------------------
class TestElUniversoEsElMaestroYSeDice(unittest.TestCase):
    def test_los_productos_de_shopify_fuera_del_maestro_se_cuentan_aparte(self):
        arti = maestro(modelos=2)
        productos = [
            producto_shopify("AB0000-N01"),
            producto_shopify("AB0001-N01"),
            producto_shopify("ZZ9999-X99"),   # no esta en el maestro
            producto_shopify(""),             # sin metacampo de codigo
        ]
        k = kpis_de(arti, stock_de(arti), productos)["kpis"]
        self.assertEqual(k["productos_en_shopify"], 4)
        self.assertEqual(k["productos_shopify_fuera_del_maestro"], 1)
        self.assertEqual(k["productos_shopify_sin_codigo"], 1)
        self.assertEqual(k["modelos_creados_shopify"], 2, "los KPI solo ven el maestro")

    def test_la_auditoria_nombra_el_universo(self):
        arti = maestro(modelos=2)
        auditoria = kpis_de(arti, stock_de(arti), [producto_shopify("AB0000-N01")])["kpi_audit"]
        indicadores = set(auditoria["Indicador"])
        self.assertIn("Productos en el catalogo Shopify", indicadores)
        self.assertIn("Productos Shopify fuera del maestro", indicadores)


class TestLaCausaPrincipalNoMandaAlEquipoEquivocado(unittest.TestCase):
    def test_un_borrador_sin_stock_se_reporta_como_no_activo(self):
        arti = maestro(modelos=1)
        productos = [producto_shopify("AB0000-N01", estado="DRAFT", stock=0, fotos=0)]
        k = kpis_de(arti, stock_de(arti), productos)["kpis"]
        self.assertEqual(k["no_visible_no_activo"], 1)
        self.assertEqual(k["no_visible_sin_stock_shopify"], 0)
        self.assertEqual(k["no_visible_sin_foto"], 0)

    def test_un_activo_publicado_sin_foto_sigue_siendo_sin_foto(self):
        arti = maestro(modelos=1)
        productos = [producto_shopify("AB0000-N01", fotos=0)]
        k = kpis_de(arti, stock_de(arti), productos)["kpis"]
        self.assertEqual(k["no_visible_sin_foto"], 1)
        self.assertEqual(k["no_visible_no_activo"], 0)

    def test_la_columna_de_bloqueos_sigue_listandolos_todos(self):
        arti = maestro(modelos=1)
        productos = [producto_shopify("AB0000-N01", estado="DRAFT", stock=0, fotos=0)]
        bloqueos = kpis_de(arti, stock_de(arti), productos)["non_visible_web"]["Bloqueos"].iloc[0]
        for esperado in ("Sin stock Shopify", "Sin foto", "No activo Shopify"):
            self.assertIn(esperado, bloqueos)


class TestUnSoloNombrePorNumero(unittest.TestCase):
    def test_las_claves_duplicadas_ya_no_estan(self):
        arti = maestro(modelos=2)
        k = kpis_de(arti, stock_de(arti), [producto_shopify("AB0000-N01")])["kpis"]
        for muerta in ("modelos_listos_tienda", "modelos_listos_venta", "productos_visibles"):
            self.assertNotIn(muerta, k)
        self.assertIn("modelos_visibles_web", k)

    def test_las_tarjetas_cuadran_entre_si(self):
        arti = maestro(modelos=5)
        productos = [producto_shopify(f"AB{i:04d}-N01") for i in range(3)]
        k = kpis_de(arti, stock_de(arti), productos)["kpis"]
        self.assertEqual(
            k["modelos_con_stock"],
            k["modelos_creados_con_stock"] + k["modelos_pendientes"],
            "con stock = creados + pendientes por crear",
        )
        self.assertEqual(
            k["modelos_creados_con_stock"],
            k["modelos_visibles_web"] + k["modelos_no_visibles_web"],
            "creados = visibles + no visibles",
        )


# --- 5. una sola regla para "publicado en Online Store" ------------------
class TestPublicadoSeDecideEnUnSoloSitio(unittest.TestCase):
    def test_con_el_campo_vacio_la_url_manda_en_las_dos_pantallas(self):
        producto = producto_shopify("AB0000-N01", publicado="", url="https://tienda/x")
        self.assertEqual(ls.estado_web(producto), ls.PRENDIDO)
        productos_df, _ = app.flatten_shopify_for_kpis([producto])
        self.assertTrue(bool(productos_df["Visible"].iloc[0]))

    def test_sin_campo_y_sin_url_ninguna_lo_da_por_publicado(self):
        producto = producto_shopify("AB0000-N01", publicado="", url="")
        self.assertEqual(ls.estado_web(producto), ls.ACTIVO_SIN_PUBLICAR)
        productos_df, _ = app.flatten_shopify_for_kpis([producto])
        self.assertFalse(bool(productos_df["Visible"].iloc[0]))

    def test_el_campo_declarado_manda_sobre_la_url(self):
        producto = producto_shopify("AB0000-N01", publicado="NO", url="https://tienda/x")
        self.assertEqual(ls.estado_web(producto), ls.ACTIVO_SIN_PUBLICAR)
        productos_df, _ = app.flatten_shopify_for_kpis([producto])
        self.assertFalse(bool(productos_df["Visible"].iloc[0]))

    def test_las_dos_pantallas_coinciden_en_todos_los_casos(self):
        for estado in ("ACTIVE", "DRAFT", "ARCHIVED"):
            for publicado, url in (("SI", ""), ("NO", ""), ("", "https://x/y"), ("", "")):
                producto = producto_shopify("AB0000-N01", estado=estado, publicado=publicado, url=url)
                productos_df, _ = app.flatten_shopify_for_kpis([producto])
                self.assertEqual(
                    ls.estado_web(producto) == ls.PRENDIDO,
                    bool(productos_df["Visible"].iloc[0]),
                    f"discrepan con estado={estado} publicado={publicado!r} url={url!r}",
                )

    def test_la_fuente_del_dato_se_reporta(self):
        _pub, fuente = ls.publicado_en_la_web({"Published Online Store": "SI"})
        self.assertEqual(fuente, "publishedOnPublication")
        _pub, fuente = ls.publicado_en_la_web({"Online Store URL": "https://x/y"})
        self.assertEqual(fuente, "onlineStoreUrl")


# --- 6. los KPI del Status de carga --------------------------------------
def fila_status(mod_col, sitio="Columbia.pe", estado="ACTIVE", publicado="SI", marca="Columbia"):
    return {
        "Mod-Col": mod_col, "Handle": mod_col.lower(), "Marca": marca, "Vendor": "columbiape",
        "Type": "Casacas", "Status": estado, "Published Online Store": publicado,
        "Tags": "", "Image Src": "", "Online Store URL": "",
    }


def inventario_de(por_sitio):
    return ls.inventario(por_sitio, etiquetas_de_sitio={k: k for k in por_sitio})


class TestElStatusSeparaLoPendienteDeLoApagado(unittest.TestCase):
    def test_archivados_no_cuentan_como_trabajo_pendiente(self):
        filas = inventario_de({"Columbia.pe": [
            fila_status("A-1"),                              # visible
            fila_status("A-2", estado="DRAFT"),              # pendiente
            fila_status("A-3", publicado="NO"),              # pendiente
            fila_status("A-4", estado="ARCHIVED"),           # apagado a proposito
        ]})
        k = ls.kpis(filas, [])
        self.assertEqual(k["Prendidos y visibles"], 1)
        self.assertEqual(k["Pendientes de publicar"], 2)
        self.assertEqual(k["Archivados"], 1)
        self.assertEqual(k["No visibles"], 3, "sigue siendo la suma, para no romper nada")
        self.assertEqual(k["Pendientes de publicar"] + k["Archivados"], k["No visibles"])

    def test_productos_unicos_es_la_base_de_las_pestanas_de_abajo(self):
        """El titular cuenta fichas por sitio; SKUs por clase cuenta productos."""
        filas = inventario_de({
            "Columbia.pe": [fila_status("A-1"), fila_status("A-2")],
            "Rockford.pe": [fila_status("A-1", sitio="Rockford.pe")],
        })
        k = ls.kpis(filas, [])
        self.assertEqual(k["Productos cargados"], 3, "tres fichas")
        self.assertEqual(k["Productos unicos"], 2, "dos productos")
        total_clases = [f for f in ls.resumen_por_clase(filas) if f["Marca"] == "Total"][0]
        self.assertEqual(total_clases["Total"], k["Productos unicos"],
                         "el titular y la pestana tienen que hablar de lo mismo")


class TestElCruceContraElCatalogoReal(unittest.TestCase):
    def solicitud(self, code, modelos, status="completed"):
        return {"code": code, "brand": "Columbia", "status": status, "model_colors": list(modelos)}

    def test_una_solicitud_finalizada_sin_productos_en_la_web_se_ve(self):
        filas = inventario_de({"Columbia.pe": [fila_status("A-1")]})
        cruce = ls.cruce_de_solicitudes(filas, [self.solicitud("CAT-1", ["A-1", "A-2"])])
        self.assertEqual(cruce["Codigos pedidos"], 2)
        self.assertEqual(cruce["Codigos pedidos cargados"], 1)
        self.assertEqual(cruce["Codigos pedidos sin cargar"], 1)
        self.assertEqual(cruce["% pedidos cargados"], 50.0)

    def test_cargado_no_es_lo_mismo_que_visible(self):
        filas = inventario_de({"Columbia.pe": [
            fila_status("A-1"), fila_status("A-2", estado="DRAFT"),
        ]})
        cruce = ls.cruce_de_solicitudes(filas, [self.solicitud("CAT-1", ["A-1", "A-2"])])
        self.assertEqual(cruce["Codigos pedidos cargados"], 2)
        self.assertEqual(cruce["Codigos pedidos visibles"], 1)

    def test_el_mismo_codigo_en_dos_solicitudes_cuenta_una_vez(self):
        filas = inventario_de({"Columbia.pe": [fila_status("A-1")]})
        cruce = ls.cruce_de_solicitudes(
            filas, [self.solicitud("CAT-1", ["A-1"]), self.solicitud("CAT-2", ["A-1"])])
        self.assertEqual(cruce["Codigos pedidos"], 1)

    def test_las_solicitudes_sin_lista_de_codigos_se_reportan_y_no_se_inventan(self):
        filas = inventario_de({"Columbia.pe": [fila_status("A-1")]})
        cruce = ls.cruce_de_solicitudes(filas, [
            self.solicitud("CAT-1", ["A-1"]),
            {"code": "CAT-VIEJA", "brand": "Columbia", "status": "completed",
             "summary": {"products": 40}},
        ])
        self.assertEqual(cruce["Codigos pedidos"], 1, "el conteo suelto no se cruza")
        self.assertEqual(cruce["Solicitudes sin detalle"], 1)

    def test_un_codigo_en_minusculas_empareja_igual(self):
        filas = inventario_de({"Columbia.pe": [fila_status("A-1")]})
        cruce = ls.cruce_de_solicitudes(filas, [self.solicitud("CAT-1", ["a-1"])])
        self.assertEqual(cruce["Codigos pedidos cargados"], 1)

    def test_sin_solicitudes_no_revienta(self):
        cruce = ls.cruce_de_solicitudes([], [])
        self.assertEqual(cruce["Codigos pedidos"], 0)
        self.assertEqual(cruce["% pedidos cargados"], 0.0)


class TestLaPantallaPideClavesQueElMotorDevuelve(unittest.TestCase):
    """Un `KeyError` aqui tumba la pantalla entera; un `.get()` mal escrito la
    deja muda para siempre. Ver la seccion 5 quater de CLAUDE.md."""

    def test_las_claves_de_las_tarjetas_existen(self):
        filas = inventario_de({"Columbia.pe": [fila_status("A-1")]})
        k = ls.kpis(filas, [])
        for clave in ("Productos cargados", "Prendidos y visibles", "Pendientes de publicar",
                      "Archivados", "% visible", "Productos unicos", "Solicitudes en curso"):
            self.assertIn(clave, k)
        cruce = ls.cruce_de_solicitudes(filas, [])
        for clave in ("Codigos pedidos", "Codigos pedidos cargados",
                      "Codigos pedidos sin cargar", "Solicitudes sin detalle"):
            self.assertIn(clave, cruce)


# --- 7. "Analizar input": el avance se ve ---------------------------------
class TestElAnalisisDicePorDondeVa(unittest.TestCase):
    """Reportado literal: *"le di analizar input pero no se si ya cargo, si
    sigue cargando o no se, pero no bota nada"*. El analisis corria detras de
    UN solo spinner mudo mientras hacia cinco cosas pesadas, y mientras tanto
    Streamlit deja a la vista la pantalla anterior en gris."""

    class Hueco:
        def __init__(self):
            self.textos = []
            self.vaciados = 0

        def info(self, texto):
            self.textos.append(texto)

        def empty(self):
            self.vaciados += 1

    def test_numera_los_pasos_y_los_cuenta(self):
        hueco = self.Hueco()
        app._paso_del_analisis(hueco, 1, "cruzando el maestro")
        self.assertEqual(hueco.textos, [f"Paso 1 de {app.PASOS_DEL_ANALISIS} · cruzando el maestro"])

    def test_el_paso_cero_limpia_el_aviso(self):
        hueco = self.Hueco()
        app._paso_del_analisis(hueco, 0, "")
        self.assertEqual(hueco.vaciados, 1)
        self.assertEqual(hueco.textos, [])

    def test_sin_hueco_no_hace_nada(self):
        app._paso_del_analisis(None, 3, "x")   # no levanta

    def test_un_aviso_roto_no_puede_tumbar_el_analisis(self):
        class Roto:
            def info(self, _texto):
                raise RuntimeError("streamlit se quejo")

        app._paso_del_analisis(Roto(), 2, "x")   # no levanta

    def test_el_hueco_se_crea_SIEMPRE_y_no_dentro_del_if(self):
        """Creado en la rama que analiza cambia la forma del arbol de elementos
        entre reruns, y entonces el bloque de abajo se AGREGA debajo del viejo
        en vez de reemplazarlo. Es el fallo de la seccion 5 terdecies."""
        rama = _rama_de_analizar()
        dentro = [
            n for n in ast.walk(rama)
            if isinstance(n, ast.Assign)
            and any(getattr(t, "id", "") == "aviso_analisis" for t in n.targets)
        ]
        self.assertEqual(dentro, [], "el hueco del avance quedo DENTRO de `if analyze_clicked:`")
        fuente = inspect.getsource(app.main)
        self.assertIn("aviso_analisis = st.empty()", fuente, "el hueco del avance desaparecio")

    def test_los_cinco_pasos_se_anuncian_dentro_de_la_rama(self):
        rama = _rama_de_analizar()
        numeros = {
            nodo.args[1].value
            for nodo in ast.walk(rama)
            if isinstance(nodo, ast.Call)
            and getattr(nodo.func, "id", "") == "_paso_del_analisis"
            and len(nodo.args) >= 2
            and isinstance(nodo.args[1], ast.Constant)
        }
        self.assertEqual(numeros, {0, 1, 2, 3, 4, 5}, "faltan pasos o sobran")


if __name__ == "__main__":
    unittest.main(verbosity=2)
