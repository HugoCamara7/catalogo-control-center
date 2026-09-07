"""Presupuesto de memoria. Falla si un flujo se pasa de lo que cabe.

Por que existe
--------------
Streamlit Community Cloud da **1 GB por APP**, no por usuario: dos personas
cargando a la vez comparten el mismo contenedor. Cuando se pasa, el proceso
muere sin traza y la app dice "over its resource limits" sin decir de que.

En septiembre de 2026 la app se cayo por esto y no lo atrapo ninguna de las
~600 pruebas del repo, porque ninguna miraba la memoria:

- El lector del maestro VTEX hacia `list(filas)` antes de indexar. Medido con
  60.000 filas -una quinta parte de un maestro real- eran 242 MB solo la lista
  y 464 MB con el indice. Extrapolado a 300.000 filas, mas de 2 GB. Paso las 62
  pruebas del motor porque **se probo con la muestra de 500 filas** del ZIP.
- Una carga completa dejaba ~1,2 GB de DataFrames vivos a la vez en
  `st.session_state`.
- `CENTRY_COLUMNS` leia un Excel en tiempo de import: 5,5 s y ~35 MB en cada
  arranque, se usara Centry o no.

De ahi la regla del proyecto: **ningun archivo del usuario se materializa
entero, y un lector nuevo se prueba con un archivo del TAMANO REAL, nunca con
una muestra**. Esta prueba es lo que la hace cumplir.

Cada medicion corre en un SUBPROCESO: el pico de RSS es del proceso entero, asi
que medir varias cosas en el mismo interprete mezclaria unas con otras.

Ejecutar:  python scripts/test_memoria.py
"""
import csv
import json
import subprocess
import sys
import tempfile
import textwrap
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from engines import vtex_catalog as vtex  # noqa: E402

# --- Presupuestos --------------------------------------------------------
#
# Salen de repartir 1 GB con holgura para dos usuarios a la vez. No son
# aspiraciones: son el techo por encima del cual la app se muere.
PRESUPUESTO_IMPORT_MB = 220        # medido tras el arreglo: ~180
PRESUPUESTO_MAESTRO_VTEX_MB = 300  # medido con 300.000 filas: ~82
FILAS_MAESTRO_DE_PRUEBA = 300_000  # 30.000 productos x 10 tallas, un catalogo real


def medir(codigo):
    """(pico de RSS en MB, valor devuelto) de un fragmento en otro interprete.

    El fragmento tiene que imprimir una ultima linea con un JSON.
    """
    guion = "\n".join([
        "import json, resource, sys",
        f"sys.path.insert(0, {str(ROOT)!r})",
        "def pico(): return resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024",
        "salida = {}",
        textwrap.dedent(codigo).strip(),
        'salida["pico_mb"] = round(pico(), 1)',
        'print("__MEDIDA__" + json.dumps(salida))',
    ])
    proceso = subprocess.run([sys.executable, "-c", guion], capture_output=True, text=True, timeout=900)
    if proceso.returncode != 0:
        raise AssertionError(f"el fragmento fallo:\n{proceso.stderr[-2000:]}")
    for linea in reversed(proceso.stdout.splitlines()):
        if linea.startswith("__MEDIDA__"):
            datos = json.loads(linea[len("__MEDIDA__"):])
            return datos.pop("pico_mb"), datos
    raise AssertionError(f"el fragmento no imprimio la medida:\n{proceso.stdout[-2000:]}")


def escribir_maestro_csv(ruta, filas=FILAS_MAESTRO_DE_PRUEBA):
    """Un maestro de VTEX del tamano real. CSV porque generarlo en xlsx tarda
    dos minutos y lo que se mide -la memoria- es igual en los dos."""
    columnas = list(vtex.COLUMNAS_PRODUCTOS_Y_SKUS)
    indice = {columna: numero for numero, columna in enumerate(columnas)}
    descripcion = ("Slip on confeccionado con aparado y forro de cuero, con una pieza "
                   "antideslizante en el taco y sistema de amortiguacion. ") * 3
    with open(ruta, "w", encoding="utf-8-sig", newline="") as archivo:
        escritor = csv.writer(archivo)
        escritor.writerow([""] * len(columnas))
        escritor.writerow(columnas)
        sku = 300000
        for producto in range(1, filas // 10 + 1):
            referencia = f"HP{1020000 + producto}-{producto % 999:03d}"
            for talla in range(10):
                sku += 1
                fila = [""] * len(columnas)
                fila[indice["Product ID"]] = str(producto)
                fila[indice["Product Name"]] = f"ZAPATO MODELO {producto} PARA HOMBRE"
                fila[indice["Description"]] = descripcion
                fila[indice["Additional description"]] = descripcion
                fila[indice["Brand ID"]] = "2000008"
                fila[indice["Brand"]] = "Hush Puppies"
                fila[indice["Department ID"]] = "25"
                fila[indice["Department"]] = "Hombre"
                fila[indice["Category ID"]] = "41"
                fila[indice["Category"]] = "Zapatos"
                fila[indice["Sales channels"]] = "1, 4"
                fila[indice["Commercial condition"]] = "Padrão"
                fila[indice["Product reference code"]] = referencia
                fila[indice["SKU ID"]] = str(sku)
                fila[indice["SKU name"]] = f"TALLA {36 + talla}"
                fila[indice["SKU reference code"]] = str(sku)
                fila[indice["Package weight"]] = "800"
                escritor.writerow(fila)
    return ruta


class TestArranque(unittest.TestCase):
    def test_importar_la_app_cabe_en_el_presupuesto(self):
        """Lo que cuesta la app antes de que entre nadie.

        Aqui vivia `CENTRY_COLUMNS = _centry_columns_desde_plantilla()`, que
        leia un Excel en tiempo de import para sacar 26 nombres de columna.
        """
        pico, _ = medir("import app_matrixify  # noqa: F401")
        self.assertLess(pico, PRESUPUESTO_IMPORT_MB,
                        f"importar la app cuesta {pico:.0f} MB (techo {PRESUPUESTO_IMPORT_MB})")

    def test_importar_no_lee_ningun_excel(self):
        """Ni el de Centry ni ningun otro. Un import tiene que ser barato."""
        pico, datos = medir("""
            import time
            comienzo = time.time()
            import app_matrixify  # noqa: F401
            salida["segundos"] = round(time.time() - comienzo, 2)
        """)
        self.assertLess(datos["segundos"], 3.0,
                        f"importar tarda {datos['segundos']}s: algo esta leyendo un archivo")

    def test_las_columnas_de_centry_se_calculan_al_usarlas(self):
        import app_matrixify as app
        self.assertIsNone(app._CENTRY_COLUMNS, "no debe calcularse al importar")
        columnas = app.centry_columns()
        self.assertGreater(len(columnas), 20)
        self.assertIs(app.centry_columns(), columnas, "tiene que quedar cacheado")
        self.assertEqual(app.CENTRY_COLUMNS, columnas, "el nombre de siempre sigue sirviendo")


class TestMaestroVTEX(unittest.TestCase):
    """El maestro real pasa de las 300.000 filas. Se prueba con ese tamano."""

    @classmethod
    def setUpClass(cls):
        cls.carpeta = tempfile.TemporaryDirectory()
        cls.ruta = Path(cls.carpeta.name) / "maestro.csv"
        escribir_maestro_csv(cls.ruta)

    @classmethod
    def tearDownClass(cls):
        cls.carpeta.cleanup()

    def test_leer_un_maestro_real_cabe_en_el_presupuesto(self):
        pico, datos = medir(f"""
            import csv, time
            from engines import vtex_catalog as vtex
            def filas():
                with open({str(self.ruta)!r}, encoding="utf-8-sig", newline="") as archivo:
                    for fila in csv.reader(archivo):
                        yield fila
            codigos = [f"HP{{1020000 + p}}-{{p % 999:03d}}" for p in range(1, 501)]
            comienzo = time.time()
            maestro = vtex.CatalogoMaestroVTEX.desde_filas(filas(), referencias=codigos)
            salida["segundos"] = round(time.time() - comienzo, 1)
            salida["productos_tienda"] = maestro.total_productos
            salida["skus_tienda"] = maestro.total_skus
            salida["productos_guardados"] = len(maestro.productos_por_id)
            salida["skus_guardados"] = len(maestro.skus_por_id)
            salida["condicion"] = maestro.valor_por_defecto("Commercial condition", "?")
        """)
        self.assertLess(pico, PRESUPUESTO_MAESTRO_VTEX_MB,
                        f"leer el maestro cuesta {pico:.0f} MB (techo {PRESUPUESTO_MAESTRO_VTEX_MB})")
        # Y el trabajo tiene que estar BIEN hecho, no solo ser barato.
        self.assertEqual(datos["productos_tienda"], 30000)
        self.assertEqual(datos["skus_tienda"], 300000)
        self.assertEqual(datos["productos_guardados"], 500)
        self.assertEqual(datos["skus_guardados"], 5000)
        self.assertEqual(datos["condicion"], "Padrão")

    def test_guardar_todo_el_maestro_seria_lo_que_reventaba(self):
        """Sin acotar por codigos, el mismo archivo se sale del presupuesto.

        No es un fallo: es la prueba de que el ahorro viene de acotar, y de por
        que la pantalla SIEMPRE tiene que pasar las referencias.
        """
        pico, _ = medir(f"""
            import csv
            from engines import vtex_catalog as vtex
            def filas():
                with open({str(self.ruta)!r}, encoding="utf-8-sig", newline="") as archivo:
                    for numero, fila in enumerate(csv.reader(archivo)):
                        if numero > 60000:
                            break
                        yield fila
            maestro = vtex.CatalogoMaestroVTEX.desde_filas(filas())
            salida["productos"] = len(maestro.productos_por_id)
        """)
        # Con solo 60.000 de las 300.000 filas ya se acerca al techo.
        self.assertGreater(pico, PRESUPUESTO_MAESTRO_VTEX_MB * 0.5,
                           "si esto deja de ser caro, revisa que la prueba siga midiendo algo")


class TestReglasDelCodigo(unittest.TestCase):
    """Lo que no se puede volver a hacer, comprobado sobre el codigo."""

    def setUp(self):
        self.motor = (ROOT / "engines" / "vtex_catalog.py").read_text(encoding="utf-8")
        self.app = (ROOT / "app_matrixify.py").read_text(encoding="utf-8-sig")

    def test_el_lector_del_maestro_no_materializa_el_archivo(self):
        inicio = self.app.index("def vtex_filas_de_archivo(")
        fin = self.app.index("def vtex_tamano_de_archivo_mb(")
        cuerpo = self.app[inicio:fin]
        self.assertIn("yield", cuerpo, "tiene que ser un generador")
        for prohibido in ("filas.append(", "list(hoja.iter_rows", ".getvalue()"):
            self.assertNotIn(prohibido, cuerpo,
                             f"'{prohibido}' vuelve a cargar el archivo entero en memoria")

    def test_los_dataframes_gigantes_de_carga_completa_van_a_disco(self):
        # 330 MB el respaldo del catalogo y 167 MB el maestro ARTI, medidos.
        for clave in ("complete_template_df", "complete_arti_df"):
            self.assertNotIn(f'st.session_state["{clave}"] =', self.app,
                             f"{clave} no puede vivir en session_state")
        self.assertIn('_guardar_df_en_disco(\n                    "template"', self.app)
        self.assertIn('_guardar_df_en_disco(\n                    "arti"', self.app)

    def test_la_vista_previa_de_centry_no_copia_el_dataframe(self):
        inicio = self.app.index("def render_centry_preview(")
        fin = self.app.index("def model_codes_from_text(")
        self.assertNotIn("centry_df.copy()", self.app[inicio:fin],
                         "copiar el Centry entero son 277 MB en cada rerun")

    def test_los_temporales_de_disco_se_borran_al_limpiar(self):
        inicio = self.app.index("def clear_complete_load_state(")
        fin = self.app.index("def reset_load_workspace(")
        self.assertIn("_borrar_temporal", self.app[inicio:fin],
                      "cada carga dejaria otro .pkl de cientos de MB en el contenedor")

    def test_el_medidor_de_memoria_tiene_llamador(self):
        # Ya paso dos veces en este repo: se define un panel y nunca se invoca.
        self.assertIn("def render_panel_memoria(", self.app)
        # La definicion tambien contiene el texto, asi que dos es una llamada.
        self.assertGreaterEqual(self.app.count("render_panel_memoria()"), 2,
                                "el panel de memoria no se dibuja en ninguna pantalla")


if __name__ == "__main__":
    unittest.main(verbosity=2)
