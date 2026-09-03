"""Pruebas del peso de los logos, que es lo que hacia lenta cada interaccion.

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
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import app_matrixify as app  # noqa: E402

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


if __name__ == "__main__":
    unittest.main(verbosity=2)
