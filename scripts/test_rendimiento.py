"""Pruebas de rendimiento: lo que se recalcula o se vuelve a bajar en cada rerun.

Por que existe
--------------
Streamlit vuelve a ejecutar el script entero en cada clic, y los logos van
embutidos como `data:` URI dentro del HTML. Los archivos estaban en resolucion
de origen --`assets/brands/logo_columbia.png` es 3840x696-- y el MISMO logo de
marca se embute cuatro veces por rerun: dentro del CSS, en la tarjeta de marca,
en la de Shopify y en la cabecera.

Medido en Columbia.pe: 668 KB de base64 en CADA clic. En un telefono con datos
moviles eso son segundos por interaccion, y no habia nada roto que mirar.

Lo que se prueba aqui es que la reduccion no se vaya de las manos en el otro
sentido: re-codificar algo que ya venia optimizado lo ENGORDA (shopify_logo.png
pasaba de 17 KB a 83 KB en PNG), y pasar a JPEG algo con transparencia le pone
fondo negro al logo.

Ejecutar:  python scripts/test_rendimiento_logos.py
"""
import ast
import base64
import io
import sys
import time
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import pandas as pd  # noqa: E402

import app_matrixify as app
import generate_columbia_matrixify as motor  # noqa: E402

FUENTE = io.open(ROOT / "app_matrixify.py", encoding="utf-8-sig").read()


def _kb(texto):
    return len(texto) / 1024.0


def _uri_sin_reducir(ruta):
    """Lo que devolvia la version anterior: el archivo crudo en base64."""
    crudo = Path(ruta).read_bytes()
    return "data:image/png;base64," + base64.b64encode(crudo).decode("ascii")


class TestReduccionDeLogos(unittest.TestCase):
    def test_los_logos_grandes_pesan_menos_que_antes(self):
        grandes = ["logo_columbia.png", "logo_mhw.png", "logo_patagonia.png", "logo_vans.jpg"]
        for nombre in grandes:
            ruta = ROOT / "assets" / "brands" / nombre
            if not ruta.exists():
                self.skipTest(f"falta {nombre}")
            antes = _kb(_uri_sin_reducir(ruta))
            ahora = _kb(app.image_data_uri(ruta))
            with self.subTest(nombre):
                self.assertLess(ahora, antes * 0.8,
                                f"{nombre}: {antes:.1f} KB -> {ahora:.1f} KB, se esperaba al menos 20% menos")

    def test_nunca_devuelve_algo_mas_grande_que_el_original(self):
        """La regla que evita el tiro por la culata.

        Sin ella, shopify_logo.png pasaba de 17 KB a 83 KB y logo_vans.jpg de
        12 a 28: reducir sin comparar habria hecho la app MAS lenta.
        """
        for ruta in sorted((ROOT / "assets").rglob("*")):
            if ruta.suffix.lower() not in (".png", ".jpg", ".jpeg", ".webp", ".gif"):
                continue
            uri = app.image_data_uri(ruta)
            if not uri:
                continue
            with self.subTest(ruta.name):
                self.assertLessEqual(_kb(uri), _kb(_uri_sin_reducir(ruta)) + 0.01,
                                     f"{ruta.name} salio mas grande que el original")

    def test_un_logo_ya_angosto_se_devuelve_tal_cual(self):
        ruta = ROOT / "assets" / "shopify_logo.png"
        if not ruta.exists():
            self.skipTest("falta shopify_logo.png")
        self.assertEqual(app.image_data_uri(ruta), _uri_sin_reducir(ruta))

    def test_el_ancho_maximo_se_respeta(self):
        try:
            from PIL import Image
        except ImportError:
            self.skipTest("sin Pillow")
        ruta = ROOT / "assets" / "brands" / "logo_columbia.png"
        if not ruta.exists():
            self.skipTest("falta logo_columbia.png")
        uri = app.image_data_uri(ruta, ancho_maximo=200)
        crudo = base64.b64decode(uri.split(",", 1)[1])
        with Image.open(io.BytesIO(crudo)) as imagen:
            self.assertLessEqual(imagen.width, 200)

    def test_ancho_maximo_cero_no_reduce(self):
        ruta = ROOT / "assets" / "brands" / "logo_columbia.png"
        if not ruta.exists():
            self.skipTest("falta logo_columbia.png")
        self.assertEqual(app.image_data_uri(ruta, ancho_maximo=0), _uri_sin_reducir(ruta))


class TestNoRompeLaTransparencia(unittest.TestCase):
    """Pasar a JPEG algo con canal alfa le pone fondo negro al logo.

    Es un error que no revienta: la app sigue funcionando y el logo sale con un
    rectangulo negro detras. Por eso JPEG solo se usa en los modos que no
    pueden llevar transparencia.
    """

    def test_solo_rgb_y_l_se_guardan_como_jpeg(self):
        self.assertEqual(set(app._MODOS_SIN_ALFA), {"RGB", "L"})

    def test_un_logo_con_alfa_no_sale_en_jpeg(self):
        try:
            from PIL import Image
        except ImportError:
            self.skipTest("sin Pillow")
        for nombre in ("logo_columbia.png", "logo_hushpuppies.png"):
            ruta = ROOT / "assets" / "brands" / nombre
            if not ruta.exists():
                continue
            with Image.open(ruta) as imagen:
                if imagen.mode in app._MODOS_SIN_ALFA:
                    continue
            with self.subTest(nombre):
                self.assertTrue(app.image_data_uri(ruta).startswith("data:image/png;"),
                                f"{nombre} tiene alfa y no puede salir en JPEG")

    def test_los_modos_con_paleta_tambien_van_a_png(self):
        """`P` puede llevar transparencia en la paleta: ante la duda, PNG."""
        self.assertNotIn("P", app._MODOS_SIN_ALFA)
        self.assertNotIn("PA", app._MODOS_SIN_ALFA)
        self.assertNotIn("RGBA", app._MODOS_SIN_ALFA)
        self.assertNotIn("LA", app._MODOS_SIN_ALFA)


class TestArchivosQueNoSonImagenes(unittest.TestCase):
    """Un archivo roto no puede tumbar la pantalla.

    `assets/logo_columbia.png` son 2 bytes (`\\r\\n`) y no es una imagen. Antes
    de reducir nada eso daba un data URI invalido pero inofensivo; al abrirlo
    con Pillow hay que atrapar el fallo.
    """

    def test_un_archivo_que_no_existe_devuelve_cadena_vacia(self):
        self.assertEqual(app.image_data_uri("assets/no_existe_jamas.png"), "")
        self.assertEqual(app.image_data_uri(ROOT / "assets" / "tampoco.webp"), "")

    def test_un_archivo_corrupto_no_revienta(self):
        roto = ROOT / "assets" / "logo_columbia.png"
        if not roto.exists():
            self.skipTest("falta el archivo de 2 bytes")
        self.assertIsInstance(app.image_data_uri(roto), str)

    def test_un_directorio_no_revienta(self):
        self.assertIsInstance(app.image_data_uri(ROOT / "assets"), str)


class TestSinPillow(unittest.TestCase):
    """Pillow llega por Streamlit, pero si falta la app tiene que dibujar igual."""

    def test_sin_pillow_se_devuelve_el_original(self):
        real = sys.modules.pop("PIL", None)
        sys.modules["PIL"] = None  # fuerza el ImportError de `from PIL import Image`
        try:
            ruta = ROOT / "assets" / "brands" / "logo_columbia.png"
            if not ruta.exists():
                self.skipTest("falta logo_columbia.png")
            self.assertIsNone(app._reducir_imagen(ruta.read_bytes(), 480))
        finally:
            if real is not None:
                sys.modules["PIL"] = real
            else:
                sys.modules.pop("PIL", None)


class TestEstaCacheado(unittest.TestCase):
    """Sin cache son cuatro lecturas de disco y cuatro base64 por rerun.

    Se lee del arbol en vez de medir tiempos: una prueba de rendimiento por
    reloj falla sola en una maquina cargada.
    """

    def _decoradores(self, nombre):
        for nodo in ast.walk(ast.parse(FUENTE)):
            if isinstance(nodo, ast.FunctionDef) and nodo.name == nombre:
                return [ast.unparse(d) for d in nodo.decorator_list]
        raise AssertionError(f"no existe la funcion {nombre}")

    def test_el_data_uri_esta_cacheado(self):
        self.assertTrue(any("cache_data" in d for d in self._decoradores("_image_data_uri_cacheado")))

    def test_resolver_la_ruta_del_logo_esta_cacheado(self):
        """Su ultimo respaldo hace `iterdir()`: un listado de directorio."""
        self.assertTrue(any("cache_data" in d for d in self._decoradores("resolve_logo_path")))

    def test_la_cache_se_invalida_si_el_archivo_cambia(self):
        """La firma lleva mtime y tamano, o habria que reiniciar la app."""
        arbol = ast.parse(FUENTE)
        for nodo in ast.walk(arbol):
            if isinstance(nodo, ast.FunctionDef) and nodo.name == "image_data_uri":
                cuerpo = ast.unparse(nodo)
                self.assertIn("st_mtime_ns", cuerpo)
                self.assertIn("st_size", cuerpo)
                return
        raise AssertionError("no existe image_data_uri")

    def test_el_stat_va_fuera_de_la_cache(self):
        """Si el `stat` fuera dentro, la cache jamas se invalidaria."""
        for nodo in ast.walk(ast.parse(FUENTE)):
            if isinstance(nodo, ast.FunctionDef) and nodo.name == "_image_data_uri_cacheado":
                self.assertNotIn(".stat()", ast.unparse(nodo))
                return
        raise AssertionError("no existe _image_data_uri_cacheado")


class TestPillowEsDependenciaDeclarada(unittest.TestCase):
    def test_pillow_esta_en_requirements(self):
        """Se usa directamente, asi que no puede depender de Streamlit."""
        with io.open(ROOT / "requirements.txt", encoding="utf-8") as fuente:
            requisitos = fuente.read().lower()
        self.assertIn("pillow", requisitos)


class TestAdjuntosCacheados(unittest.TestCase):
    """`st.download_button` exige los bytes POR ADELANTADO.

    Eso hacia que cada rerun bajara de GitHub el Excel del input Y el de
    validacion aunque nadie pulsara el boton. Con la bandeja y Carga completa
    abiertas eran entre dos y cinco descargas por CLIC, y la pantalla se
    quedaba en gris esperando la red. Medido con 250 ms de latencia por
    descarga: 5 clics pasaban de 5,01 s a 0,50 s.

    Cachear por ruta es correcto porque los adjuntos son INMUTABLES: la ruta
    lleva la solicitud, el numero de version y el tipo, y una version nueva
    escribe una ruta nueva.
    """

    class _StoreQueCuenta:
        def __init__(self):
            self.descargas = []

        def get_artifact(self, path):
            self.descargas.append(path)
            return b"contenido " + str(path).encode("utf-8")

    def test_la_misma_ruta_se_baja_una_sola_vez(self):
        store = self._StoreQueCuenta()
        ruta = "catalog_tickets/CAT-cache-1/v1/input/Input.xlsx"
        primero = app.artefacto_de_solicitud(store, ruta)
        for _ in range(9):
            self.assertEqual(app.artefacto_de_solicitud(store, ruta), primero)
        self.assertEqual(len(store.descargas), 1,
                         f"se bajo {len(store.descargas)} veces en vez de 1")

    def test_rutas_distintas_no_se_confunden(self):
        store = self._StoreQueCuenta()
        entrada = app.artefacto_de_solicitud(store, "CAT-cache-2/v1/input/a.xlsx")
        reporte = app.artefacto_de_solicitud(store, "CAT-cache-2/v1/report/b.xlsx")
        self.assertNotEqual(entrada, reporte)
        self.assertEqual(len(store.descargas), 2)

    def test_el_store_no_entra_en_la_clave_de_cache(self):
        """Dos stores distintos y la misma ruta: no se vuelve a bajar.

        El parametro se llama `_store` justamente para que Streamlit no lo
        hashee. Si entrara en la clave, cada rerun crearia un store nuevo y la
        cache no serviria de nada.
        """
        ruta = "catalog_tickets/CAT-cache-3/v1/input/Input.xlsx"
        primero = self._StoreQueCuenta()
        app.artefacto_de_solicitud(primero, ruta)
        segundo = self._StoreQueCuenta()
        app.artefacto_de_solicitud(segundo, ruta)
        self.assertEqual(segundo.descargas, [],
                         "el segundo store volvio a bajar el adjunto")



class TestAnalisisNoEsCuadratico(unittest.TestCase):
    """El analisis no puede recorrer el catalogo una vez POR PRODUCTO.

    Origen: `matrixify_rows_for_handle` hacia `iterrows()` sobre el catalogo
    entero y se la llama una vez por producto dentro del bucle del analisis.
    Medido con un catalogo de 20.000 filas: 1,7 s POR PRODUCTO, o sea 27,8
    MINUTOS para los 1.009 productos de una carga real de Vans. En pantalla se
    veia como "Analizando input..." para siempre.

    Con el indice armado una sola vez: 0,6 s en total. 2.940 veces mas rapido y
    el mismo resultado.
    """

    @staticmethod
    def _catalogo(productos=2500, variantes=8):
        # En una exportacion Matrixify solo la PRIMERA fila de cada producto
        # trae el Handle; las variantes siguientes lo dejan vacio.
        filas = []
        for numero in range(productos):
            for variante in range(variantes):
                filas.append({
                    "Handle": f"producto-{numero}" if variante == 0 else "",
                    "Variant SKU": f"SKU{numero}-{variante}",
                    "Title": f"Producto {numero}",
                })
        return pd.DataFrame(filas)

    def test_el_indice_arrastra_el_handle_a_las_variantes(self):
        catalogo = self._catalogo(productos=3, variantes=4)
        indice = motor.indice_de_handles(catalogo)
        self.assertEqual(sorted(indice), ["producto-0", "producto-1", "producto-2"])
        # Las cuatro filas del producto, no solo la que trae el Handle.
        self.assertEqual(len(indice["producto-1"]), 4)

    def test_con_indice_y_sin_indice_devuelven_lo_mismo(self):
        catalogo = self._catalogo(productos=20, variantes=5)
        indice = motor.indice_de_handles(catalogo)
        for handle in ("producto-0", "producto-7", "producto-19", "no-existe"):
            pd.testing.assert_frame_equal(
                motor.matrixify_rows_for_handle(catalogo, handle),
                motor.matrixify_rows_for_handle(catalogo, handle, indice=indice),
            )

    def test_mil_productos_se_resuelven_en_segundos_no_en_minutos(self):
        catalogo = self._catalogo()
        comienzo = time.time()
        indice = motor.indice_de_handles(catalogo)
        for numero in range(1009):
            motor.matrixify_rows_for_handle(
                catalogo, f"producto-{numero % 2500}", indice=indice)
        segundos = time.time() - comienzo
        # Techo generoso: medido en 0,6 s. Antes eran ~1.670 s.
        self.assertLess(segundos, 30,
                        f"resolver 1.009 productos tarda {segundos:.0f}s: volvio a ser cuadratico")

    def test_el_analisis_pasa_el_indice_en_vez_de_rearmarlo(self):
        """Sin esto el arreglo se deshace solo: la funcion sigue aceptando que
        no le pasen indice, y ahi lo arma y lo tira en cada llamada."""
        fuente = (ROOT / "generate_columbia_matrixify.py").read_text(encoding="utf-8")
        inicio = fuente.index("def build_columbia_matrixify(")
        fin = fuente.index("\ndef ", inicio + 10)
        cuerpo = fuente[inicio:fin]
        self.assertIn("handles_del_catalogo = indice_de_handles(matrixify_df)", cuerpo)
        self.assertIn("indice=handles_del_catalogo", cuerpo)
        self.assertNotIn("matrixify_rows_for_handle(matrixify_df, existing_handle)", cuerpo)

    def test_las_pasadas_grandes_del_catalogo_no_usan_iterrows(self):
        """`build_existing_lookup` y `siblings_ya_publicados` recorren el
        catalogo ENTERO, una vez por analisis.

        Medido sobre 20.000 filas: 9,4 s y 4,2 s. `iterrows()` construye una
        Series con las 107 columnas del export solo para leer un punado de
        valores; acotando las columnas y pasando a dicts bajan a menos de un
        segundo. Es el 45% del analisis.

        OJO: esto vale para las pasadas GRANDES. En los trozos de una decena de
        filas -- los de por producto -- `to_dict("records")` sale mas caro que
        `iterrows()` (medido: 14,3 s -> 17,5 s), y ahi se deja como esta.
        """
        fuente = (ROOT / "generate_columbia_matrixify.py").read_text(encoding="utf-8-sig")
        arbol = ast.parse(fuente)
        for nodo in ast.walk(arbol):
            if isinstance(nodo, ast.FunctionDef) and nodo.name in (
                    "build_existing_lookup", "siblings_ya_publicados"):
                llamadas = set()
                for hijo in ast.walk(nodo):
                    if isinstance(hijo, ast.Call):
                        # `df.iterrows()` es un Attribute; `filas_como_registros()`
                        # es un Name. Hay que mirar los dos.
                        llamadas.add(getattr(hijo.func, "attr", "")
                                     or getattr(hijo.func, "id", ""))
                self.assertNotIn("iterrows", llamadas,
                                 f"{nodo.name} recorre el catalogo entero: sin iterrows")
                self.assertIn("filas_como_registros", llamadas, nodo.name)

    def test_filas_como_registros_solo_trae_lo_pedido(self):
        catalogo = pd.DataFrame([{"Handle": "a", "Title": "T", "Otra": "x"}])
        registros = motor.filas_como_registros(catalogo, ["Handle", "Title", "No existe"])
        self.assertEqual(registros, [{"Handle": "a", "Title": "T"}])
        self.assertEqual(motor.filas_como_registros(pd.DataFrame(), ["Handle"]), [])

    def test_el_trozo_por_producto_no_se_copia(self):
        """`.loc[lista]` ya devuelve una copia: el `.copy()` extra duplicaba las
        107 columnas del trozo una vez por producto."""
        # Por AST: el comentario EXPLICA el `.copy()` que se quito y lo nombra.
        fuente = (ROOT / "generate_columbia_matrixify.py").read_text(encoding="utf-8-sig")
        for nodo in ast.walk(ast.parse(fuente)):
            if isinstance(nodo, ast.FunctionDef) and nodo.name == "matrixify_rows_for_handle":
                llamadas = {getattr(hijo.func, "attr", "")
                            for hijo in ast.walk(nodo) if isinstance(hijo, ast.Call)}
                self.assertNotIn("copy", llamadas)

    def test_el_indice_no_usa_iterrows(self):
        """Por AST, no por texto: el docstring EXPLICA el problema y lo nombra."""
        # utf-8-sig: el archivo empieza con BOM y ast.parse no lo tolera.
        fuente = (ROOT / "generate_columbia_matrixify.py").read_text(encoding="utf-8-sig")
        arbol = ast.parse(fuente)
        for nodo in ast.walk(arbol):
            if isinstance(nodo, ast.FunctionDef) and nodo.name in (
                    "indice_de_handles", "matrixify_rows_for_handle"):
                llamadas = {
                    getattr(hijo.func, "attr", "")
                    for hijo in ast.walk(nodo) if isinstance(hijo, ast.Call)
                }
                self.assertNotIn("iterrows", llamadas,
                                 f"{nodo.name}: iterrows sobre la fila entera es "
                                 "justo lo que hacia esto lento")


class TestElCatalogoSeCortaUnaVez(unittest.TestCase):
    """El analisis cortaba el catalogo una vez POR PRODUCTO.

    `indice_de_handles` ya habia quitado el bucle cuadratico, pero cada
    producto seguia haciendo `matrixify_df.loc[lista]`: pandas reindexa las 107
    columnas del catalogo y las materializa. Con 1.000 productos y 33.000 filas
    de catalogo, esos cortes y los `iterrows()` que venian detras eran ~40 de
    los 79 segundos del analisis. Medido con cProfile:

        antes   79,1 s   (1,58 M accesos a `Series.__getitem__`)
        ahora   38,2 s

    Y la salida es IDENTICA: comparadas las 6 hojas en tres sitios.
    """

    @classmethod
    def setUpClass(cls):
        cls.catalogo = pd.DataFrame([
            {"Handle": "zapato-a", "Variant SKU": "A1", "Option1 Value": "40", "Variant Price": "10"},
            {"Handle": "", "Variant SKU": "A2", "Option1 Value": "41", "Variant Price": "20"},
            {"Handle": "zapato-b", "Variant SKU": "B1", "Option1 Value": "38", "Variant Price": "30"},
        ])

    def test_devuelve_las_mismas_filas_que_el_corte_de_antes(self):
        agrupadas = motor.filas_por_handle(self.catalogo)
        for handle in ("zapato-a", "zapato-b"):
            trozo = motor.matrixify_rows_for_handle(self.catalogo, handle)
            self.assertEqual(
                [fila.get("Variant SKU") for fila in agrupadas[handle]],
                list(trozo["Variant SKU"]),
                handle,
            )

    def test_arrastra_el_handle_a_las_variantes(self):
        """En un export Matrixify solo la primera fila trae el Handle."""
        agrupadas = motor.filas_por_handle(self.catalogo)
        self.assertEqual(len(agrupadas["zapato-a"]), 2)

    def test_un_catalogo_vacio_no_revienta(self):
        self.assertEqual(motor.filas_por_handle(None), {})
        self.assertEqual(motor.filas_por_handle(pd.DataFrame()), {})

    def test_los_consumidores_dan_lo_mismo_con_dataframe_y_con_dicts(self):
        """Se aceptan las dos formas para no romper a quien llame desde fuera."""
        trozo = motor.matrixify_rows_for_handle(self.catalogo, "zapato-a")
        dicts = motor.filas_por_handle(self.catalogo)["zapato-a"]
        self.assertEqual(
            motor.build_product_variant_lookup(trozo),
            motor.build_product_variant_lookup(dicts),
        )
        self.assertEqual(
            motor.first_valid_product_price(trozo),
            motor.first_valid_product_price(dicts),
        )
        generadas = [{"Variant SKU": "A1"}, {"Variant SKU": "A2"}]
        self.assertEqual(
            motor.product_is_unchanged(generadas, trozo, list(self.catalogo.columns)),
            motor.product_is_unchanged(generadas, dicts, list(self.catalogo.columns)),
        )

    def test_solo_guarda_los_handles_pedidos(self):
        """El catalogo ENTERO como dicts costaba 82 MB medidos para 33 MB de
        DataFrame, y eso crece con la tienda. Una carga toca sus handles."""
        agrupadas = motor.filas_por_handle(self.catalogo, handles=["zapato-b"])
        self.assertEqual(list(agrupadas), ["zapato-b"])

    def test_solo_guarda_las_columnas_que_se_leen(self):
        columnas = motor.columnas_leidas_del_catalogo(list(self.catalogo.columns))
        agrupadas = motor.filas_por_handle(self.catalogo, columnas=columnas)
        guardadas = set(agrupadas["zapato-a"][0])
        self.assertIn("Variant SKU", guardadas)
        self.assertIn("Handle", guardadas)
        self.assertNotIn("Option1 Name", guardadas,
                         "esa columna no se lee del catalogo y ocupa memoria")

    def test_las_columnas_leidas_traen_las_que_compara_el_sin_cambios(self):
        """Si faltara una, `product_is_unchanged` dejaria de compararla y un
        producto que SI cambio se reportaria como omitido."""
        columnas = list(self.catalogo.columns) + ["Title", "Body HTML"]
        leidas = set(motor.columnas_leidas_del_catalogo(columnas))
        for columna in motor.comparable_columns(columnas):
            self.assertIn(columna, leidas, columna)
        for columna in motor.COLUMNAS_VARIANTE_EXISTENTE:
            self.assertIn(columna, leidas, columna)

    def test_el_analisis_acota_el_indice(self):
        fuente = (ROOT / "generate_columbia_matrixify.py").read_text(encoding="utf-8")
        inicio = fuente.index("def build_columbia_matrixify(")
        cuerpo = fuente[inicio:]
        self.assertIn("handles=handles_de_la_carga", cuerpo)
        self.assertIn("columnas=columnas_leidas_del_catalogo(", cuerpo)

    def test_el_analisis_ya_no_corta_el_catalogo_dentro_del_bucle(self):
        fuente = (ROOT / "generate_columbia_matrixify.py").read_text(encoding="utf-8")
        inicio = fuente.index("def build_columbia_matrixify(")
        cuerpo = fuente[inicio:]
        self.assertNotIn("matrixify_rows_for_handle(", cuerpo,
                         "cortar el catalogo por producto es lo que costaba los segundos")
        self.assertIn("filas_del_catalogo.get(", cuerpo)

    def test_el_maestro_arti_no_se_barre_una_vez_por_producto(self):
        """`arti[arti["__KEY"] == key]` dentro del bucle son 1.000 barridos
        del maestro entero."""
        fuente = (ROOT / "generate_columbia_matrixify.py").read_text(encoding="utf-8")
        inicio = fuente.index("def build_columbia_matrixify(")
        cuerpo = fuente[inicio:]
        # Se mira la ASIGNACION, no el texto suelto: el comentario que explica
        # el arreglo tambien contiene la expresion vieja.
        self.assertNotIn('variants = arti[arti["__KEY"] == key]', cuerpo)
        self.assertIn("variantes_por_clave", cuerpo)

    def test_el_bucle_recorre_dicts_y_no_series(self):
        """Con `iterrows()` cada `.get()` pasa por el indice de pandas: eran
        1,47 millones de accesos y 20 segundos."""
        fuente = (ROOT / "generate_columbia_matrixify.py").read_text(encoding="utf-8")
        inicio = fuente.index("def build_columbia_matrixify(")
        cuerpo = fuente[inicio:]
        self.assertNotIn("in input_df.iterrows()", cuerpo)
        self.assertNotIn("variants.iterrows()", cuerpo)
        self.assertIn('input_df.to_dict("records")', cuerpo)


class TestClavesDeFila(unittest.TestCase):
    """El respaldo por nombre normalizado tiene que seguir funcionando.

    Varias funciones leian las columnas de la fila con `getattr(row, "index")`.
    Con un dict eso devuelve `[]` **sin fallar**: el respaldo dejaba de
    encontrar la columna y el campo salia vacio. Es el peor tipo de error, el
    que no revienta.
    """

    def test_funciona_con_series_y_con_dict(self):
        fila = {"Nombre de Producto": "Zapato", "Descripcion": "x"}
        self.assertEqual(set(motor.claves_de_fila(fila)), set(fila))
        self.assertEqual(set(motor.claves_de_fila(pd.Series(fila))), set(fila))
        self.assertEqual(motor.claves_de_fila(None), ())

    def test_el_respaldo_por_nombre_encuentra_la_columna_en_un_dict(self):
        """"Descripción" con tilde tiene que encontrarse pidiendo "Descripcion"."""
        for fila in ({"Descripción ": "texto"}, pd.Series({"Descripción ": "texto"})):
            self.assertEqual(motor.row_alias_value(fila, ["Descripcion"]), "texto",
                             type(fila).__name__)
            self.assertEqual(motor.row_first_existing(fila, ["Descripcion"]), "texto",
                             type(fila).__name__)


class TestElTicketNoSeBajaEnCadaClic(unittest.TestCase):
    """Las pantallas que solo DIBUJAN el ticket iban a GitHub en cada rerun.

    `get_ticket` no esta cacheada a proposito: de ahi sale el `_revision` con
    el que se guarda, y servirlo viejo haria fallar cada guardado. Pero eso no
    justifica pagar el viaje para pintar un titulo: en Carga completa eran
    tres pantallas pidiendolo, o sea tres viajes a GitHub POR CLIC.

    Medido con 250 ms de latencia -lo que tarda la API de GitHub desde
    Streamlit Cloud-: **0,75 s por clic** que ya no se pagan.
    """

    class _Servicio:
        def __init__(self, tickets):
            self.tickets = tickets
            self.viajes_get = 0
        def get_ticket(self, actor, codigo):
            self.viajes_get += 1
            return next((t for t in self.tickets if t["code"] == codigo), None)
        def list_tickets(self, actor, **kwargs):
            return self.tickets

    def test_dibujar_no_cuesta_un_viaje_a_github(self):
        servicio = self._Servicio([{"code": "CAT-1", "status": "loading"}])
        for _ in range(3):
            ticket = app.ticket_para_pantalla(servicio, {}, "CAT-1")
            self.assertEqual(ticket["code"], "CAT-1")
        self.assertEqual(servicio.viajes_get, 0, "sigue bajando el ticket en cada rerun")

    def test_si_no_esta_en_la_bandeja_se_pide(self):
        """La bandeja va filtrada por rol y una solicitud recien creada puede
        no estar: ahi si hay que ir a buscarla, o la pantalla se queda vacia."""
        servicio = self._Servicio([{"code": "CAT-1", "status": "loading"}])
        servicio.tickets.append({"code": "CAT-2", "status": "draft"})
        del servicio.tickets[1]
        self.assertIsNone(app.ticket_para_pantalla(servicio, {}, "CAT-2"))
        self.assertEqual(servicio.viajes_get, 1)

    def test_un_fallo_de_la_bandeja_no_tumba_la_pantalla(self):
        class Rota(self._Servicio):
            def list_tickets(self, actor, **kwargs):
                raise RuntimeError("GitHub caido")
        servicio = Rota([{"code": "CAT-1", "status": "loading"}])
        self.assertEqual(app.ticket_para_pantalla(servicio, {}, "CAT-1")["code"], "CAT-1")
        self.assertEqual(servicio.viajes_get, 1, "tiene que caer al camino de siempre")

    def test_sin_codigo_no_pregunta_nada(self):
        servicio = self._Servicio([])
        self.assertIsNone(app.ticket_para_pantalla(servicio, {}, ""))
        self.assertEqual(servicio.viajes_get, 0)

    def test_las_pantallas_que_dibujan_ya_no_llaman_a_get_ticket(self):
        fuente = (ROOT / "app_matrixify.py").read_text(encoding="utf-8-sig")
        arbol = ast.parse(fuente)
        for nombre in ("_render_acciones_solicitud_tras_carga",
                       "render_full_load_ticket_queue", "render_ticket_detail"):
            cuerpo = ast.get_source_segment(fuente, next(
                n for n in ast.walk(arbol)
                if isinstance(n, ast.FunctionDef) and n.name == nombre))
            self.assertNotIn(".get_ticket(", cuerpo,
                             f"{nombre} vuelve a bajar el ticket en cada rerun")
            self.assertIn("ticket_para_pantalla(", cuerpo, nombre)

    def test_escribir_sigue_pidiendo_el_ticket_fresco(self):
        """El `_revision` con el que se guarda TIENE que venir de GitHub."""
        fuente = (ROOT / "app_matrixify.py").read_text(encoding="utf-8-sig")
        arbol = ast.parse(fuente)
        cuerpo = ast.get_source_segment(fuente, next(
            n for n in ast.walk(arbol)
            if isinstance(n, ast.FunctionDef) and n.name == "_adjuntar_matrixify_antes_de_cargar"))
        self.assertIn("service.get_ticket(", cuerpo)


if __name__ == "__main__":
    unittest.main(verbosity=2)
