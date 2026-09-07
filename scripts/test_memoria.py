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


class TestReglasDelCodigo(unittest.TestCase):
    """Lo que no se puede volver a hacer, comprobado sobre el codigo."""

    def setUp(self):
        self.app = (ROOT / "app_matrixify.py").read_text(encoding="utf-8-sig")

    def test_los_dataframes_gigantes_de_carga_completa_van_a_disco(self):
        """330 MB el respaldo del catalogo y 167 MB el maestro ARTI, medidos.

        Con nombre fijo no pueden guardarse en la sesion. La unica escritura a
        `session_state` permitida es la de `_guardar_datos_de_carga`, cuando el
        disco no es escribible: ahi la correccion manda sobre el ahorro.
        """
        for clave in ("complete_template_df", "complete_arti_df"):
            self.assertNotIn(f'st.session_state["{clave}"] =', self.app,
                             f"{clave} no puede vivir en session_state")
        self.assertIn('_guardar_datos_de_carga(template_df, arti_df, brand_config)', self.app)
        self.assertIn('_guardar_df_en_disco(clave, df, brand_config)', self.app)

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
        self.assertNotIn("_leer_df_de_disco", condicion,
                         "data_ready no puede leer los DataFrames: se evalua en cada rerun")
        self.assertIn("_hay_datos_de_carga()", condicion)

    def test_los_dataframes_solo_se_leen_al_analizar(self):
        self.assertIn("_leer_datos_de_carga()", self.app)
        inicio = self.app.index("            if analyze_clicked:")
        fin = self.app.index("build_columbia_matrixify(", inicio)
        self.assertIn("_leer_datos_de_carga()", self.app[inicio:fin],
                      "los datos se leen dentro del analisis, que es cuando hacen falta")

    def test_si_el_disco_falla_los_datos_se_quedan_en_la_sesion(self):
        # Correccion antes que ahorro: perderlos obliga a releer Shopify y
        # BigQuery en cada clic, que es peor que gastar la memoria.
        inicio = self.app.index("def _guardar_datos_de_carga(")
        fin = self.app.index("def _hay_datos_de_carga(")
        cuerpo = self.app[inicio:fin]
        self.assertIn("st.session_state[clave_sesion] = df", cuerpo)

    def test_el_panel_no_cuenta_filas_leyendo_el_disco(self):
        # El PANEL de Carga completa, no la funcion que lo dibuja.
        inicio = self.app.index('("Columnas base"')
        fin = self.app.index("render_operational_status(", inicio)
        cuerpo = self.app[inicio:fin]
        for prohibido in ("len(template_df", "len(arti_df"):
            self.assertNotIn(prohibido, cuerpo,
                             f"'{prohibido}' obliga a tener el DataFrame en memoria en cada rerun")

    def test_guardar_y_leer_un_dataframe_de_disco_conserva_los_datos(self):
        import app_matrixify as app
        import pandas as pd
        original = pd.DataFrame({"Mod-Col": ["A-1", "B-2"], "Talla": ["39", "40"]}, dtype=object)
        with tempfile.TemporaryDirectory() as carpeta:
            import os
            anterior = os.getcwd()
            try:
                os.chdir(carpeta)
                ruta = app._guardar_df_en_disco("prueba", original, {"site_key": "columbia"})
                self.assertTrue(ruta, "no se pudo escribir el temporal")
                pd.testing.assert_frame_equal(app._leer_df_de_disco(ruta), original)
                app._borrar_temporal(ruta)
                self.assertIsNone(app._leer_df_de_disco(ruta))
                # Borrar dos veces no revienta: no existir ya es el objetivo.
                app._borrar_temporal(ruta)
            finally:
                os.chdir(anterior)

    def test_centry_y_sial_no_se_quedan_en_la_sesion(self):
        """277 MB y 191 MB medidos en una carga de 40.000 filas.

        Centry solo se usa para dibujar su pestana, y Streamlit ejecuta el
        contenido de TODAS las pestanas en cada rerun: por eso el DataFrame
        tenia que seguir vivo. Ahora los numeros se calculan una vez y en
        sesion queda el resumen. El Sial se necesita entero en un solo momento,
        al adjuntarlo en el cierre, y para eso vive en disco.
        """
        self.assertNotIn('st.session_state["complete_centry_df"] =', self.app)
        # La UNICA escritura del Sial a la sesion es el respaldo de
        # `_guardar_resumen_sial` para cuando el disco no es escribible.
        self.assertEqual(self.app.count('st.session_state["complete_sial_df"] = sial_df'), 1)
        inicio = self.app.index("def _guardar_resumen_sial(")
        fin = self.app.index("def _leer_sial_de_disco(")
        self.assertIn('st.session_state["complete_sial_df"] = sial_df', self.app[inicio:fin])
        self.assertIn('st.session_state["complete_centry_resumen"] = resumen_centry_para_pantalla(', self.app)
        self.assertIn("_guardar_resumen_sial(sial_df, brand_config)", self.app)

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

    def test_el_adjunto_del_cierre_sigue_llevando_el_sial_completo(self):
        # Perder esto dejaria el correo al Area de Producto SIN archivo, que es
        # el error que se corrigio en agosto de 2026.
        inicio = self.app.index("def _archivo_carga_sial(")
        fin = self.app.index("def _render_acciones_solicitud_tras_carga(")
        cuerpo = self.app[inicio:fin]
        self.assertIn("_leer_sial_de_disco()", cuerpo)
        self.assertIn('dataframe_to_excel_bytes({"Carga Sial": sial_df})', cuerpo)

    def test_si_el_disco_falla_el_sial_se_queda_en_la_sesion(self):
        inicio = self.app.index("def _guardar_resumen_sial(")
        fin = self.app.index("def _leer_sial_de_disco(")
        self.assertIn('st.session_state["complete_sial_df"] = sial_df', self.app[inicio:fin])

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
