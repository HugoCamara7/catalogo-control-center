"""El catalogo se leia INCOMPLETO y no lo decia nadie.

Ejecutar:  python scripts/test_lectura_completa_del_catalogo.py

Lo que fija
-----------
Dos fallos de la lectura de Shopify que explican los dos sintomas reportados
-- "Patagonia.pe (Error), Supermall.pe (Error)" con los otros cuatro sitios
bien, y totales que no cuadran con la tienda:

1. **El tope de 5.000 productos, en silencio.** `fetch_products` tenia
   `max_products=5000` por defecto y `_bulk_reensamblar` hacia `break` sin
   decir nada al alcanzarlo. Rockford.pe pasa de 9.000 modelo-color. Y ese
   catalogo es el dato con el que se decide si un producto se **crea** o se
   **actualiza**: lo que se quedaba fuera del tope se volvia a crear y quedaba
   DUPLICADO en la tienda.

2. **El respaldo de la lectura masiva atrapaba solo `ShopifyApiError`.** Un
   corte de red bajando el JSONL, un gzip a medias o un timeout se propagaban
   y el sitio entero quedaba SIN LEER -- que es exactamente como se ven dos
   sitios en "(Error)" mientras los otros cuatro entran. La lectura paginada
   existe precisamente como respaldo.

Y lo tercero, que es lo que hace visibles a los dos: el parte de progreso del
motor -- lo unico que dice que se alcanzo el tope o que se cayo a la paginada
-- se tiraba. Ahora se recoge por sitio y se reporta en las dos pantallas que
leen los seis catalogos.
"""
import ast
import inspect
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import shopify_api as sa  # noqa: E402


def lineas_de_productos(cuantos):
    return [
        '{"id": "gid://shopify/Product/%d", "title": "P%d"}' % (i, i)
        for i in range(cuantos)
    ]


class TestElTopeDeProductos(unittest.TestCase):
    def test_ya_no_son_5000(self):
        """Rockford.pe pasa de 9.000 modelo-color: el tope se alcanzaba."""
        self.assertGreaterEqual(sa.PRODUCTOS_MAXIMOS, 20000)

    def test_se_puede_ajustar_desde_secrets(self):
        self.assertEqual(sa._limite_de_productos({"max_products": "8000"}), 8000)
        self.assertEqual(sa._limite_de_productos({}), sa.PRODUCTOS_MAXIMOS)

    def test_un_tope_invalido_no_revienta_la_lectura(self):
        """Un valor mal escrito en Secrets no puede dejar sin catalogo."""
        self.assertEqual(sa._limite_de_productos({"max_products": "muchos"}), sa.PRODUCTOS_MAXIMOS)
        self.assertEqual(sa._limite_de_productos({"max_products": ""}), sa.PRODUCTOS_MAXIMOS)

    def test_lo_que_pide_el_llamador_manda(self):
        self.assertEqual(sa._limite_de_productos({"max_products": "8000"}, 100), 100)

    def test_las_tres_lecturas_comparten_el_tope(self):
        """Si una leyera hasta 5.000 y otra hasta 50.000, el catalogo cambiaria
        segun por donde se leyo -- es lo que ya se paga con las dos
        `normalize_size`."""
        for funcion in (sa.fetch_products, sa.fetch_products_paginado, sa.fetch_products_bulk):
            firma = inspect.signature(funcion)
            self.assertIsNone(
                firma.parameters["max_products"].default,
                f"{funcion.__name__} trae su propio tope",
            )

    def test_al_alcanzar_el_tope_se_AVISA(self):
        """EL FALLO: el `break` era silencioso, y un catalogo cortado se lee
        como "esto es todo lo que hay"."""
        avisos = []
        registros = sa._bulk_reensamblar(
            lineas_de_productos(5), max_products=2, progreso=avisos.append,
        )
        self.assertEqual(len(registros), 2)
        self.assertTrue(any("tope" in a.lower() for a in avisos), avisos)

    def test_el_aviso_dice_cuantos_quedaron_sin_leer(self):
        avisos = []
        sa._bulk_reensamblar(lineas_de_productos(10), max_products=4, progreso=avisos.append)
        self.assertTrue(any("6" in a for a in avisos), avisos)

    def test_sin_alcanzar_el_tope_no_avisa_de_nada(self):
        """Un aviso que sale siempre no es un aviso."""
        avisos = []
        sa._bulk_reensamblar(lineas_de_productos(3), max_products=100, progreso=avisos.append)
        self.assertEqual(avisos, [])

    def test_sin_progreso_el_tope_no_revienta(self):
        """El aviso NUNCA puede tumbar la lectura."""
        registros = sa._bulk_reensamblar(lineas_de_productos(5), max_products=2)
        self.assertEqual(len(registros), 2)

    def test_la_paginada_tambien_avisa_del_tope(self):
        """La paginada es el respaldo y tiene que decir lo mismo: si no, el
        aviso depende de por donde se leyo."""
        fuente = inspect.getsource(sa.fetch_products_paginado)
        self.assertIn("tope", fuente)


class TestElRespaldoDeLaLecturaMasiva(unittest.TestCase):
    def test_atrapa_cualquier_fallo_no_solo_ShopifyApiError(self):
        """Atrapando solo ese, un corte de red bajando el JSONL dejaba el sitio
        entero SIN LEER: es como se ven dos sitios en "(Error)" y cuatro bien."""
        arbol = ast.parse(inspect.getsource(sa.fetch_products).strip())
        manejadores = [n for n in ast.walk(arbol) if isinstance(n, ast.ExceptHandler)]
        self.assertTrue(manejadores, "la lectura masiva no tiene respaldo")
        self.assertIn("Exception", ast.unparse(manejadores[0].type))

    def test_un_fallo_de_red_cae_a_la_paginada(self):
        """Comprobado ejecutandolo, no solo leyendo el codigo."""
        llamadas = []
        original_bulk = sa.fetch_products_bulk
        original_pag = sa.fetch_products_paginado

        def bulk_que_se_cae(config, max_products=None, progreso=None):
            raise OSError("connection reset by peer")

        def paginada(config, max_products=None, progreso=None):
            llamadas.append(max_products)
            return [{"Mod-Col": "A-1"}]

        sa.fetch_products_bulk = bulk_que_se_cae
        sa.fetch_products_paginado = paginada
        try:
            avisos = []
            productos = sa.fetch_products({"shop_domain": "x"}, progreso=avisos.append)
        finally:
            sa.fetch_products_bulk = original_bulk
            sa.fetch_products_paginado = original_pag
        self.assertEqual(productos, [{"Mod-Col": "A-1"}])
        self.assertEqual(llamadas, [sa.PRODUCTOS_MAXIMOS])
        self.assertTrue(any("no disponible" in a.lower() for a in avisos), avisos)


class TestElParteDeLaLecturaSeREPORTA(unittest.TestCase):
    """El aviso del motor es lo unico que dice que el catalogo quedo corto. Si
    nadie lo recoge, no existe."""

    def test_la_lectura_de_los_sitios_recoge_el_progreso(self):
        import app_matrixify as app
        fuente = inspect.getsource(app.cargar_catalogos_de_todos_los_sitios)
        self.assertIn("progreso=", fuente)

    def test_el_error_de_un_sitio_lleva_el_TIPO_de_la_excepcion(self):
        """Un `URLError` a secas dice "urlopen error" y no distingue la red del
        token."""
        import app_matrixify as app
        fuente = inspect.getsource(app.cargar_catalogos_de_todos_los_sitios)
        self.assertIn("type(error).__name__", fuente)

    def test_un_sitio_leido_con_aviso_NO_cuenta_como_caido(self):
        """Las pantallas comparan contra el valor exacto "Leido". Un estado
        nuevo tipo "Leido con avisos" contaria un sitio bueno como caido, asi
        que el aviso viaja en `Detalle` y el estado no se toca."""
        import app_matrixify as app
        arbol = ast.parse(inspect.getsource(app.cargar_catalogos_de_todos_los_sitios).strip())
        estados = set()
        for nodo in ast.walk(arbol):
            if not isinstance(nodo, ast.Dict):
                continue
            for clave, valor in zip(nodo.keys, nodo.values):
                if getattr(clave, "value", "") == "Estado":
                    estados.add(ast.unparse(valor))
        self.assertEqual(estados, {"'Sin configurar'", "'Error'", "'Leido'"}, estados)

    def test_las_dos_pantallas_avisan_del_catalogo_incompleto(self):
        """Status de carga y Carga Supermall leen los mismos seis catalogos: si
        una avisara y la otra no, el mismo total se leeria bien en una pantalla
        y mal en la otra."""
        import app_matrixify as app
        for funcion in (app.render_status_de_carga, app.render_carga_supermall):
            fuente = inspect.getsource(funcion)
            self.assertIn("incompleto", fuente, funcion.__name__)

    def test_el_aviso_de_incompleto_solo_mira_los_sitios_LEIDOS(self):
        """Un sitio caido ya tiene su propio aviso; sacarlo tambien aqui seria
        contar el mismo problema dos veces."""
        import app_matrixify as app
        fuente = inspect.getsource(app.render_carga_supermall)
        self.assertIn('e.get("Estado") == "Leido" and clean_value(e.get("Detalle"))', fuente)


class TestNadieSeSaltaLaCacheDelCatalogo(unittest.TestCase):
    """El Dashboard leia la tienda entera aunque ya estuviera en cache.

    Reportado como *"hay mucho cache por eso se pone lenta"*. Era al reves: el
    problema es que el Dashboard **no usaba** la cache. `load_catalog_kpi_result`
    llamaba a `fetch_products` directo, saltandose la de sesion y la de disco
    (2 horas) que usan todas las demas pantallas: se entraba a KPIs justo
    despues de que Status de carga o Carga Supermall hubieran leido ese mismo
    sitio, y volvia a leerlo entero. En Vans.pe son minutos.
    """

    def _fuente(self, nombre):
        import app_matrixify as app
        return inspect.getsource(getattr(app, nombre))

    def test_el_dashboard_lee_por_la_puerta_con_cache(self):
        cuerpo = self._fuente("load_catalog_kpi_result")
        self.assertIn("leer_catalogo_del_sitio(", cuerpo)
        self.assertNotIn("fetch_products(", cuerpo)

    def test_solo_DOS_sitios_llaman_a_fetch_products(self):
        """`session_shopify_products` (que cachea) y el lector en paralelo, que
        consulta la cache antes en el hilo de la pantalla. Cualquier tercero se
        estaria saltando la cache."""
        import pathlib
        import app_matrixify as app
        arbol = ast.parse(pathlib.Path(app.__file__).read_text(encoding="utf-8"))
        duenos = set()
        for fn in [n for n in ast.walk(arbol) if isinstance(n, ast.FunctionDef)]:
            for nodo in ast.walk(fn):
                if (isinstance(nodo, ast.Call) and isinstance(nodo.func, ast.Name)
                        and nodo.func.id == "fetch_products"):
                    duenos.add(fn.name)
        # `_leer` es el cuerpo del hilo dentro de `cargar_catalogos_de_todos_los_sitios`:
        # ahi la cache ya se consulto ANTES, en el hilo de la pantalla, porque
        # `st.session_state` no se puede tocar desde un hilo.
        permitidos = {"session_shopify_products", "cargar_catalogos_de_todos_los_sitios", "_leer"}
        self.assertEqual(
            duenos, permitidos,
            f"alguien mas llama a fetch_products y se salta la cache: {sorted(duenos - permitidos)}",
        )

    def test_Actualizar_SI_fuerza_la_relectura(self):
        """La cache no puede convertirse en una trampa: el boton existe para
        pasar por encima de ella."""
        cuerpo = self._fuente("render_catalog_kpi_dashboard")
        self.assertIn("force_refresh=True", cuerpo)

    def test_el_hueco_del_avance_NO_se_crea_dentro_de_una_rama(self):
        """Creado dentro del `if`, solo existe en los reruns que leen, y eso
        cambia la forma del arbol de elementos entre un rerun y el siguiente.

        El nombre lleva sufijo (`_kpis`) a proposito: `test_lectura_catalogo`
        localiza el hueco de Carga completa por su nombre con `.index()`, y dos
        variables iguales en archivos distintos le dan la posicion equivocada.
        """
        cuerpo = self._fuente("render_catalog_kpi_dashboard")
        lineas = [l for l in cuerpo.splitlines() if "aviso_lectura_kpis = st.empty()" in l]
        self.assertEqual(len(lineas), 1)
        sangria = len(lineas[0]) - len(lineas[0].lstrip())
        self.assertEqual(sangria, 4, "el hueco quedo dentro de una rama")


class TestUnaTiendaVaciaSeLEE(unittest.TestCase):
    """Reportado como *"en supermall no habia ningun producto"*.

    Un catalogo VACIO leido sin error no es un catalogo AUSENTE. Si la app
    confundiera los dos, `render_carga_supermall` cortaria y **la primera
    carga en una tienda vacia seria imposible** -- justo el caso de uso con
    el que empieza Supermall.

    Estas pruebas EJECUTAN la cadena entera. Las de arriba leen el codigo, y
    leer el codigo no es ejecutarlo: un `if productos:` en vez de
    `if productos is not None:` no se ve en un AST que busca otra cosa.
    """

    def _cargar(self, productos_por_sitio):
        import app_matrixify as app
        sitios = {k: {"site_label": k.title()} for k in productos_por_sitio}
        previos = {
            n: getattr(app, n) for n in (
                "SITE_CONFIGS", "get_shopify_config", "is_shopify_configured",
                "shopify_products_en_cache", "guardar_shopify_products",
                "fetch_products",
            )
        }
        app.SITE_CONFIGS = sitios
        app.get_shopify_config = lambda site_key: {"site_key": site_key}
        app.is_shopify_configured = lambda config: True
        app.shopify_products_en_cache = lambda site_key, config: None
        app.guardar_shopify_products = lambda site_key, config, productos: None
        app.fetch_products = lambda config, **kw: productos_por_sitio[config["site_key"]]
        try:
            return app.cargar_catalogos_de_todos_los_sitios()
        finally:
            for nombre, valor in previos.items():
                setattr(app, nombre, valor)

    def test_el_sitio_vacio_ENTRA_en_los_catalogos(self):
        catalogos, estados = self._cargar({"vans": [{"Handle": "a"}], "supermall": []})
        self.assertIn("supermall", catalogos, "una tienda vacia se perdio por el camino")
        self.assertEqual(catalogos["supermall"], [])

    def test_el_sitio_vacio_queda_en_Leido_con_0_productos(self):
        _, estados = self._cargar({"vans": [{"Handle": "a"}], "supermall": []})
        fila = next(e for e in estados if e["Sitio"] == "Supermall")
        self.assertEqual(fila["Estado"], "Leido")
        self.assertEqual(fila["Productos"], 0)

    def test_el_sitio_CAIDO_no_entra_y_queda_en_Error(self):
        """El contraste: eso SI tiene que cortar la pantalla."""
        import app_matrixify as app
        class _Roto(list):
            def __iter__(self):
                raise RuntimeError("401")
        def _cargar_con_error():
            productos = {"vans": [{"Handle": "a"}]}
            previos = {n: getattr(app, n) for n in (
                "SITE_CONFIGS", "get_shopify_config", "is_shopify_configured",
                "shopify_products_en_cache", "guardar_shopify_products", "fetch_products")}
            app.SITE_CONFIGS = {"vans": {"site_label": "Vans"}, "supermall": {"site_label": "Supermall"}}
            app.get_shopify_config = lambda site_key: {"site_key": site_key}
            app.is_shopify_configured = lambda config: True
            app.shopify_products_en_cache = lambda site_key, config: None
            app.guardar_shopify_products = lambda site_key, config, prods: None
            def _fetch(config, **kw):
                if config["site_key"] == "supermall":
                    raise RuntimeError("HTTP 401")
                return productos["vans"]
            app.fetch_products = _fetch
            try:
                return app.cargar_catalogos_de_todos_los_sitios()
            finally:
                for nombre, valor in previos.items():
                    setattr(app, nombre, valor)
        catalogos, estados = _cargar_con_error()
        self.assertNotIn("supermall", catalogos)
        fila = next(e for e in estados if e["Sitio"] == "Supermall")
        self.assertEqual(fila["Estado"], "Error")
        self.assertIn("401", fila["Detalle"])

    def test_la_cadena_entera_deja_generar_la_primera_carga(self):
        """De la lectura al resumen: con Supermall vacio, `destino_leido` es
        True y todo sale como "falta cargar", que es lo correcto."""
        from engines import carga_supermall
        catalogos, _ = self._cargar({
            "vans": [{"Mod-Col": "AB-1", "Handle": "ab-1", "Title": "Old Skool",
                      "Type": "Zapatilla", "Status": "ACTIVE", "Variants": []}],
            "supermall": [],
        })
        consolidado = carga_supermall.consolidar(catalogos, orden_de_sitios=["vans"])
        self.assertTrue(consolidado["resumen"]["destino_leido"])
        self.assertEqual(len(consolidado["fichas"]), 1)
        self.assertEqual(consolidado["fichas"][0]["Situacion"], "Falta cargar")
        self.assertEqual(consolidado["resumen"]["Falta cargar"], 1)
        self.assertEqual(consolidado["resumen"]["Se crean"], 1)

    def test_la_cache_tampoco_pierde_una_tienda_vacia(self):
        """La rama de cache es OTRO camino: `guardados or []` con una lista
        vacia da `[]`, pero solo entra si `guardados is not None`."""
        import app_matrixify as app
        previos = {n: getattr(app, n) for n in (
            "SITE_CONFIGS", "get_shopify_config", "is_shopify_configured",
            "shopify_products_en_cache")}
        app.SITE_CONFIGS = {"supermall": {"site_label": "Supermall"}}
        app.get_shopify_config = lambda site_key: {"site_key": site_key}
        app.is_shopify_configured = lambda config: True
        app.shopify_products_en_cache = lambda site_key, config: []
        try:
            catalogos, estados = app.cargar_catalogos_de_todos_los_sitios()
        finally:
            for nombre, valor in previos.items():
                setattr(app, nombre, valor)
        self.assertIn("supermall", catalogos)
        self.assertEqual(estados[0]["Estado"], "Leido")


if __name__ == "__main__":
    unittest.main(verbosity=2)
