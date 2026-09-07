"""Presupuesto de memoria. Falla si un flujo se pasa de lo que cabe.

Por que existe
--------------
Streamlit Community Cloud da **1 GB por APP**, no por usuario: dos personas
cargando a la vez comparten el mismo contenedor. Cuando se pasa, el proceso
muere sin traza y la app dice "over its resource limits" sin decir de que.

En septiembre de 2026 la app se cayo por esto y no lo atrapo ninguna de las
~600 pruebas del repo, porque ninguna miraba la memoria:

- Un lector de catalogo maestro hacia `list(filas)` antes de indexar. Medido
  con 60.000 filas eran 242 MB solo la lista y 464 MB con el indice;
  extrapolado a 300.000 filas, mas de 2 GB. Paso todas las pruebas del motor
  porque **se probo con una muestra de 500 filas**. Ese motor (la carga manual
  a VTEX) se retiro en septiembre de 2026, pero la leccion es la regla.
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

# --- Presupuestos --------------------------------------------------------
#
# Salen de repartir 1 GB con holgura para dos usuarios a la vez. No son
# aspiraciones: son el techo por encima del cual la app se muere.
PRESUPUESTO_IMPORT_MB = 220        # medido tras el arreglo: ~180


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


# Presupuesto del arranque. Sale de repartir 1 GB con holgura para dos usuarios
# a la vez; no es una aspiracion, es el techo por encima del cual la app muere.
PRESUPUESTO_IMPORT_MB = 220


def medir(codigo):
    """(pico de RSS en MB, valores) de un fragmento en OTRO interprete.

    En subproceso porque el pico de RSS es del proceso entero: medir varias
    cosas en el mismo interprete las mezclaria.
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
    proceso = subprocess.run([sys.executable, "-c", guion], capture_output=True, text=True, timeout=600)
    if proceso.returncode != 0:
        raise AssertionError(f"el fragmento fallo:\n{proceso.stderr[-2000:]}")
    for linea in reversed(proceso.stdout.splitlines()):
        if linea.startswith("__MEDIDA__"):
            datos = json.loads(linea[len("__MEDIDA__"):])
            return datos.pop("pico_mb"), datos
    raise AssertionError(f"el fragmento no imprimio la medida:\n{proceso.stdout[-2000:]}")


class TestArranque(unittest.TestCase):
    """Lo que cuesta la app antes de que entre nadie.

    Aqui vivia `CENTRY_COLUMNS = _centry_columns_desde_plantilla()`, que leia un
    Excel en tiempo de import para sacar nombres de columna: 5,5 s y ~35 MB en
    CADA arranque, se usara Centry o no.
    """

    def test_importar_la_app_cabe_en_el_presupuesto(self):
        pico, _ = medir("import app_matrixify  # noqa: F401")
        self.assertLess(pico, PRESUPUESTO_IMPORT_MB,
                        f"importar la app cuesta {pico:.0f} MB (techo {PRESUPUESTO_IMPORT_MB})")

    def test_importar_no_lee_ningun_excel(self):
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


PRESUPUESTO_INDICE_CATALOGO_MB = 40  # medido acotado: ~15; sin acotar eran 82


class TestIndiceDelCatalogo(unittest.TestCase):
    """El analisis pasa el catalogo a dicts para no cortarlo por producto.

    Eso es lo que lo hizo 2,4 veces mas rapido, pero guardar el catalogo ENTERO
    como dicts costaba **82 MB medidos** para un DataFrame de 33 MB -- y crece
    con la tienda, mientras el contenedor sigue dando 1 GB POR APP. Acotado a
    los handles que la carga toca y a las columnas que se leen, son ~15 MB.

    Sin esta prueba, quitar el acotado no rompe nada visible: solo vuelve a
    llenar la memoria, que es como se cayo la app en septiembre de 2026.
    """

    def test_el_indice_acotado_cabe_en_el_presupuesto(self):
        pico, datos = medir(f"""
            import pandas as pd
            import generate_columbia_matrixify as g

            # Las columnas REALES del export de Matrixify, no inventadas: de
            # cuantas se descartan depende el ahorro, y un juego inventado de
            # metacampos daria un numero que no se parece al de produccion.
            import app_matrixify as app
            COLUMNAS = list(pd.read_excel(app.DEFAULT_MATRIXIFY_PATH, sheet_name=0, nrows=0).columns)
            cuerpo = "<p>Zapatilla de cuero con suela de goma.</p>" * 4
            filas = []
            for i in range(3000):
                h = f"zapatilla-modelo-{{i}}"
                cab = {{c: "" for c in COLUMNAS}}
                cab.update({{"Handle": h, "Top Row": "TRUE", "Title": f"Zapatilla {{i}}",
                            "Body HTML": cuerpo, "Tags": "hombre, calzado, negro"}})
                filas.append(cab)
                for j in range(10):
                    v = {{c: "" for c in COLUMNAS}}
                    v.update({{"Handle": h, "Variant SKU": f"SKU{{i}}{{j}}",
                               "Option1 Value": str(380 + j * 10), "Variant Price": "199.90"}})
                    filas.append(v)
            base = pd.DataFrame(filas, columns=COLUMNAS)
            salida["catalogo_mb"] = round(base.memory_usage(deep=True).sum() / 1e6)

            # Las filas con las que se armo el DataFrame se sueltan antes de
            # medir: si no, lo que se mide es el andamio y no el indice.
            del filas
            import gc
            gc.collect()

            def rss():
                with open("/proc/self/statm") as f:
                    return int(f.read().split()[1]) * 4096 / 1e6
            antes = rss()
            handles = {{f"zapatilla-modelo-{{i}}" for i in range(1000)}}
            columnas = g.columnas_leidas_del_catalogo(list(base.columns))
            agrupadas = g.filas_por_handle(base, handles=handles, columnas=columnas)
            salida["indice_mb"] = round(rss() - antes)
            salida["handles"] = len(agrupadas)
            # Lo que importa es cuantas se GUARDAN, no cuantas se piden:
            # `filas_por_handle` descarta las que el catalogo no tiene.
            primera = agrupadas[next(iter(agrupadas))][0]
            salida["columnas_guardadas"] = len(primera)
            salida["columnas_catalogo"] = len(base.columns)
        """)
        self.assertEqual(datos["handles"], 1000, "tiene que quedarse solo con los pedidos")
        self.assertLess(datos["columnas_guardadas"], datos["columnas_catalogo"],
                        "tiene que descartar las columnas que no se leen")
        print(f"      [indice del catalogo: {datos['indice_mb']} MB para un catalogo de "
              f"{datos['catalogo_mb']} MB, {datos['columnas_guardadas']} de "
              f"{datos['columnas_catalogo']} columnas]")
        self.assertLess(
            datos["indice_mb"], PRESUPUESTO_INDICE_CATALOGO_MB,
            f"el indice del catalogo cuesta {datos['indice_mb']} MB "
            f"(techo {PRESUPUESTO_INDICE_CATALOGO_MB}); el catalogo son {datos['catalogo_mb']} MB",
        )


class TestReglasDelCodigo(unittest.TestCase):
    """Lo que no se puede volver a hacer, comprobado sobre el codigo."""

    def setUp(self):
        self.app = (ROOT / "app_matrixify.py").read_text(encoding="utf-8-sig")

    def test_los_datos_de_carga_no_pasan_por_disco(self):
        """El disco fue un mal negocio y hay que impedir que vuelva.

        Estuvieron en `outputs/sesion/*.pkl` un dia: ahorraban ~500 MB de RAM a
        cambio de 9 SEGUNDOS de I/O en cada analisis -medidos: 5,6 s de
        escritura y 3,3 s de lectura del catalogo del sitio, el ARTI y el Sial-,
        y en Streamlit Cloud el disco es mas lento que en local. Una carga de
        Vans de 1.009 productos que antes entraba dejo de terminar de leerse.
        """
        for prohibido in ("_guardar_df_en_disco", "_leer_df_de_disco"):
            self.assertNotIn(prohibido, self.app,
                             f"{prohibido} mete disco en el camino de cada analisis")
        inicio = self.app.index("def _guardar_datos_de_carga(")
        fin = self.app.index("def _hay_datos_de_carga(")
        self.assertIn("st.session_state[clave_sesion] = df", self.app[inicio:fin])

    def test_el_catalogo_del_sitio_no_se_copia_en_cada_analisis(self):
        """331 MB duplicados por analisis, medidos sobre un catalogo real.

        `prepare_matrixify_context` hacia `.copy()` del catalogo actual, y ahi
        solo se LEE: `build_existing_lookup`, `siblings_ya_publicados` y
        `matrixify_rows_for_handle`, que hace su propia copia del trozo que
        devuelve. Ese era el ahorro de verdad, y no cuesta un segundo.
        """
        motor = (ROOT / "generate_columbia_matrixify.py").read_text(encoding="utf-8")
        inicio = motor.index("def prepare_matrixify_context(")
        fin = motor.index("\ndef ", inicio + 10)
        self.assertNotIn("matrixify_source.copy()", motor[inicio:fin])

    def test_el_adjunto_del_cierre_sigue_llevando_el_sial_completo(self):
        # Perder esto dejaria el correo al Area de Producto SIN archivo, que es
        # el error que se corrigio en agosto de 2026.
        inicio = self.app.index("def _archivo_carga_sial(")
        fin = self.app.index("def _render_acciones_solicitud_tras_carga(")
        cuerpo = self.app[inicio:fin]
        self.assertIn("_sial_completo()", cuerpo)
        self.assertIn('dataframe_to_excel_bytes({"Carga Sial": sial_df})', cuerpo)

    def test_el_centry_no_se_queda_entero_en_la_sesion(self):
        # 277 MB medidos. Este ahorro SI se conserva: es gratis.
        self.assertNotIn('st.session_state["complete_centry_df"] =', self.app)
        self.assertIn('st.session_state["complete_centry_resumen"] = resumen_centry_para_pantalla(', self.app)

    def test_data_ready_no_lee_los_dataframes_en_cada_rerun(self):
        """La regresion que hubo que arreglar el mismo dia.

        `data_ready` se evalua en CADA rerun, o sea en cada clic. Leer ahi los
        temporales -330 MB del catalogo y 167 MB del ARTI- era medio segundo de
        disco por clic; y si la escritura habia fallado, `data_ready` daba False
        y la pantalla volvia a leer Shopify y BigQuery en cada interaccion. Se
        sentia como "no carga y esta lentisimo".
        """
        inicio = self.app.index("            data_ready = (")
        fin = self.app.index("            if data_ready:", inicio)
        condicion = self.app[inicio:fin]
        self.assertIn("_hay_datos_de_carga()", condicion)
        inicio = self.app.index("def _hay_datos_de_carga(")
        fin = self.app.index("def _leer_datos_de_carga(")
        cuerpo = self.app[inicio:fin]
        for prohibido in ("read_pickle", "Path(", ".exists()"):
            self.assertNotIn(prohibido, cuerpo,
                             "se evalua en cada rerun: no puede tocar el disco")

    def test_el_panel_no_cuenta_filas_leyendo_el_disco(self):
        # El PANEL de Carga completa, no la funcion que lo dibuja.
        inicio = self.app.index('("Columnas base"')
        fin = self.app.index("render_operational_status(", inicio)
        cuerpo = self.app[inicio:fin]
        for prohibido in ("len(template_df", "len(arti_df"):
            self.assertNotIn(prohibido, cuerpo,
                             f"'{prohibido}' obliga a tener el DataFrame en memoria en cada rerun")

    def test_el_resumen_de_centry_no_arrastra_el_dataframe(self):
        import app_matrixify as app
        import pandas as pd
        filas = 500
        centry = pd.DataFrame({
            "SKU del producto": [f"A-{i//5}" for i in range(filas)],
            "Código de barra variante (EAN/UPC/ISBN)": ["779" + str(i) for i in range(filas)],
            "URL imagen principal": ["" if i % 10 == 0 else "http://x/1.jpg" for i in range(filas)],
        }, dtype=object)
        resumen = app.resumen_centry_para_pantalla(centry, filas_vista_previa=120)
        self.assertEqual(resumen["total_rows"], filas)
        self.assertEqual(resumen["total_products"], 100)
        self.assertEqual(resumen["no_image"], 50)
        self.assertEqual(resumen["no_barcode"], 0)
        # Lo que queda en sesion son 120 filas, no las 500.
        self.assertEqual(len(resumen["muestra"]), 120)
        peso_resumen = app.peso_de_objeto_mb(resumen["muestra"])
        peso_completo = app.peso_de_objeto_mb(centry)
        self.assertLess(peso_resumen, peso_completo,
                        "la muestra tiene que pesar menos que el Centry entero")

    def test_el_panel_de_cierre_no_cuenta_filas_del_sial_en_memoria(self):
        inicio = self.app.index("def _conteo_carga_sial(")
        fin = self.app.index("def _archivo_carga_sial(")
        cuerpo = self.app[inicio:fin]
        self.assertNotIn("len(sial_df)", cuerpo,
                         "se dibuja en cada rerun: los conteos van guardados")
        self.assertIn("complete_sial_filas", cuerpo)

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
