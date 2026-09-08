"""Pruebas de la optimizacion de septiembre de 2026: exportacion, memoria y fugas.

Lo que fija cada bloque, y por que:

- `dataframe_to_excel_bytes` armaba el libro con **openpyxl**, que lo materializa
  entero como objetos `Cell`. Medido con 40.000 filas x 107 columnas: **70,8 s y
  +1,79 GB de RSS**, en un contenedor que da **1 GB POR APP**. Y como
  `st.download_button` exige los bytes por adelantado, 17 botones lo rearmaban en
  CADA rerun aunque nadie pulsara nada.
- xlsxwriter, en cambio, INTERPRETA lo que escribe: un texto que empieza por "="
  sale como formula y uno que parece URL como hipervinculo. Las dos cosas
  corrompen el dato del usuario y hay que apagarlas.
- `apply(..., axis=1)` arma un Series por fila. En el catalogo y en el maestro
  ARTI eso son cientos de miles de objetos de pandas para leer dos o cuatro
  columnas.
- Las caches de disco (`.pkl` del catalogo, snapshots de los jobs) no se
  borraban nunca. El disco del contenedor es una cuota fija: cuando se llena, la
  escritura falla y la app cae con "Error running app" sin decir de que.

Ejecutar:  python scripts/test_optimizacion_memoria_excel.py
"""
import ast
import io
import os
import sys
import time
import unittest
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import app_matrixify as app  # noqa: E402


def _leer(buffer, hoja):
    buffer.seek(0)
    return pd.read_excel(buffer, sheet_name=hoja, dtype=object)


class TestElMotorDeExcel(unittest.TestCase):
    """openpyxl era lo que tumbaba el contenedor."""

    def test_las_exportaciones_no_usan_openpyxl_a_mano(self):
        fuente = (ROOT / "app_matrixify.py").read_text(encoding="utf-8")
        arbol = ast.parse(fuente)
        culpables = []
        for nodo in ast.walk(arbol):
            if not isinstance(nodo, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            if nodo.name not in ("dataframe_to_excel_bytes", "to_excel_bytes",
                                 "update_to_excel_bytes", "columbia_to_excel_bytes"):
                continue
            cuerpo = ast.get_source_segment(fuente, nodo) or ""
            if 'engine="openpyxl"' in cuerpo:
                culpables.append(nodo.name)
        self.assertEqual(
            culpables, [],
            "openpyxl arma el libro entero en memoria: +1,79 GB medidos con el "
            "catalogo completo, y el contenedor da 1 GB para toda la app.",
        )

    def test_no_se_recorren_todas_las_celdas_para_el_ancho(self):
        """`sheet.columns` materializa una tupla con TODAS las celdas de la hoja."""
        fuente = (ROOT / "app_matrixify.py").read_text(encoding="utf-8")
        arbol = ast.parse(fuente)
        for nodo in ast.walk(arbol):
            if isinstance(nodo, ast.FunctionDef) and nodo.name == "dataframe_to_excel_bytes":
                cuerpo = ast.get_source_segment(fuente, nodo) or ""
                self.assertNotIn("column_dimensions", cuerpo)
                self.assertIn("_dar_formato_hojas", cuerpo)
                return
        self.fail("no se encontro dataframe_to_excel_bytes")


class TestNoSeCorrompeElDatoDelUsuario(unittest.TestCase):
    """xlsxwriter interpreta el texto si no se le dice que no."""

    def test_un_texto_que_empieza_por_igual_NO_se_vuelve_formula(self):
        df = pd.DataFrame({"Texto": ["=1+1", "=SUMA(A1:A2)", "normal"]})
        leido = _leer(app.dataframe_to_excel_bytes({"S": df}), "S")
        self.assertEqual(leido["Texto"].tolist(), ["=1+1", "=SUMA(A1:A2)", "normal"])

    def test_una_url_NO_se_vuelve_hipervinculo(self):
        """Excel admite 65.530 hipervinculos por hoja; el Matrixify lleva
        columnas enteras de URLs de imagen y pasado ese numero se DESCARTAN."""
        urls = [f"https://ecom-imagenes.forus.pe/COLUMBIA/foto_{i}.jpg" for i in range(50)]
        leido = _leer(app.dataframe_to_excel_bytes({"S": pd.DataFrame({"Image Src": urls})}), "S")
        self.assertEqual(leido["Image Src"].tolist(), urls)

    def test_las_opciones_del_motor_estan_apagadas(self):
        self.assertFalse(app.OPCIONES_XLSXWRITER["strings_to_formulas"])
        self.assertFalse(app.OPCIONES_XLSXWRITER["strings_to_urls"])

    def test_los_ceros_iniciales_y_las_tallas_sobreviven(self):
        df = pd.DataFrame({
            "SKU": ["0012", "000", "007", "0912-A"],
            "Talla": ["04-Jun", "400", "8.5", "O/S"],
        })
        leido = _leer(app.dataframe_to_excel_bytes({"S": df}), "S")
        self.assertEqual(leido["SKU"].tolist(), ["0012", "000", "007", "0912-A"])
        self.assertEqual(leido["Talla"].tolist(), ["04-Jun", "400", "8.5", "O/S"])

    def test_las_cabeceras_con_espacio_final_se_conservan(self):
        """SIAL las espera CON el espacio: asi se llaman en su plantilla."""
        df = pd.DataFrame({"Categoria ": ["Calzado"], "Tecnologias ": ["Omni-Heat"]})
        leido = _leer(app.dataframe_to_excel_bytes({"S": df}), "S")
        self.assertEqual(list(leido.columns), ["Categoria ", "Tecnologias "])


class TestElMemoDeExportaciones(unittest.TestCase):
    """17 botones rearmaban su Excel en cada rerun aunque nadie los pulsara."""

    def setUp(self):
        app._EXCEL_MEMO.clear()

    def test_el_mismo_contenido_da_los_mismos_bytes_sin_rearmar(self):
        df = pd.DataFrame({"a": list(range(2000)), "b": [f"t{i}" for i in range(2000)]})
        primero = app.dataframe_to_excel_bytes({"S": df}).getvalue()
        self.assertEqual(len(app._EXCEL_MEMO), 1)
        inicio = time.perf_counter()
        segundo = app.dataframe_to_excel_bytes({"S": df}).getvalue()
        reusado = time.perf_counter() - inicio
        self.assertEqual(primero, segundo)
        self.assertLess(reusado, 0.5, "la segunda llamada tiene que salir del memo")

    def test_un_contenido_distinto_NO_reusa(self):
        app.dataframe_to_excel_bytes({"S": pd.DataFrame({"a": [1]})})
        app.dataframe_to_excel_bytes({"S": pd.DataFrame({"a": [2]})})
        self.assertEqual(len(app._EXCEL_MEMO), 2)

    def test_un_frame_modificado_EN_EL_SITIO_se_vuelve_a_armar(self):
        """La clave es el CONTENIDO, no la identidad: si fuera `id(df)` una
        edicion en el sitio devolveria el Excel viejo."""
        df = pd.DataFrame({"a": ["uno", "dos"]})
        antes = app.dataframe_to_excel_bytes({"S": df}).getvalue()
        df.loc[0, "a"] = "CAMBIADO"
        despues = app.dataframe_to_excel_bytes({"S": df}).getvalue()
        self.assertNotEqual(antes, despues)
        self.assertEqual(_leer(io.BytesIO(despues), "S")["a"].tolist(), ["CAMBIADO", "dos"])

    def test_cada_llamada_devuelve_un_buffer_NUEVO(self):
        """Devolviendo el mismo objeto, un lector movia la posicion al siguiente."""
        df = pd.DataFrame({"a": [1]})
        uno = app.dataframe_to_excel_bytes({"S": df})
        uno.read()
        dos = app.dataframe_to_excel_bytes({"S": df})
        self.assertIsNot(uno, dos)
        self.assertEqual(dos.tell(), 0)
        self.assertTrue(dos.read())

    def test_el_memo_tiene_tope(self):
        self.assertLessEqual(app._EXCEL_MEMO_MAX_BYTES, 64 * 1024 * 1024)
        app._memo_excel_guardar("a", b"x" * (app._EXCEL_MEMO_MAX_BYTES // 2))
        app._memo_excel_guardar("b", b"y" * (app._EXCEL_MEMO_MAX_BYTES // 2))
        app._memo_excel_guardar("c", b"z" * (app._EXCEL_MEMO_MAX_BYTES // 2))
        total = sum(len(valor) for valor in app._EXCEL_MEMO.values())
        self.assertLessEqual(total, app._EXCEL_MEMO_MAX_BYTES)

    def test_una_hoja_que_no_se_puede_hashear_NO_rompe(self):
        """Devolver None es "no memoices esta", no un error."""
        df = pd.DataFrame({"a": [["lista", "dentro"], ["otra"]]})
        self.assertIsNone(app._huella_de_hojas({"S": df}))
        self.assertTrue(app.dataframe_to_excel_bytes({"S": df}).getvalue())


class TestHojasInesperadas(unittest.TestCase):
    """Un nombre raro o una hoja vacia no puede tumbar la descarga entera."""

    def test_diccionario_vacio(self):
        self.assertTrue(app.dataframe_to_excel_bytes({}).getvalue())

    def test_una_hoja_None_se_escribe_vacia(self):
        self.assertTrue(app.dataframe_to_excel_bytes({"S": None}).getvalue())

    def test_dos_nombres_que_chocan_al_cortar_en_31(self):
        hojas = {
            "Resumen de la carga completa por marca A": pd.DataFrame({"a": [1]}),
            "Resumen de la carga completa por marca B": pd.DataFrame({"b": [2]}),
        }
        libro = pd.ExcelFile(app.dataframe_to_excel_bytes(hojas))
        self.assertEqual(len(libro.sheet_names), 2)
        self.assertEqual(len(set(libro.sheet_names)), 2)

    def test_un_nombre_vacio_no_revienta(self):
        libro = pd.ExcelFile(app.dataframe_to_excel_bytes({"": pd.DataFrame({"a": [1]})}))
        self.assertEqual(libro.sheet_names, ["Hoja"])


class TestReparacionDeMojibake(unittest.TestCase):
    """Se mapeaba celda a celda TODA columna, tambien las numericas."""

    def _a_mano(self, df):
        """El recorrido viejo, celda a celda sobre todas las columnas."""
        salida = df.copy()
        salida.columns = [app._repair_column_name(c) for c in salida.columns]
        for posicion in range(salida.shape[1]):
            salida.isetitem(posicion, salida.iloc[:, posicion].map(
                lambda v: app.repair_mojibake_text(v)
                if isinstance(v, str) and any(m in v for m in app._MOJIBAKE_MARCADORES) else v))
        return salida

    def test_da_lo_mismo_que_el_recorrido_completo(self):
        df = pd.DataFrame({
            "texto": ["CategorÃ­a", "normal", "BaÃ±o"],
            "numeros": [1, 2, 3],
            "decimales": [1.5, 2.5, np.nan],
            "vacios": [None, "", "x"],
            "booleanos": [True, False, True],
        })
        pd.testing.assert_frame_equal(app.repair_mojibake_dataframe(df), self._a_mano(df))

    def test_repara_de_verdad_lo_que_hay_que_reparar(self):
        df = pd.DataFrame({"c": ["CategorÃ­a"]})
        self.assertEqual(app.repair_mojibake_dataframe(df)["c"].iloc[0], "Categoría")

    def test_no_toca_el_original(self):
        df = pd.DataFrame({"c": ["CategorÃ­a"]})
        app.repair_mojibake_dataframe(df)
        self.assertEqual(df["c"].iloc[0], "CategorÃ­a")

    def test_una_columna_numerica_se_descarta_sin_recorrerla(self):
        self.assertFalse(app._columna_puede_tener_mojibake(pd.Series([1, 2, 3])))
        self.assertFalse(app._columna_puede_tener_mojibake(pd.Series([1.5, 2.5])))
        self.assertTrue(app._columna_puede_tener_mojibake(pd.Series(["BaÃ±o"])))
        self.assertFalse(app._columna_puede_tener_mojibake(pd.Series(["limpio"])))

    def test_columnas_repetidas(self):
        df = pd.DataFrame([["CategorÃ­a", "BaÃ±o"]], columns=["c", "c"])
        salida = app.repair_mojibake_dataframe(df)
        self.assertEqual(salida.iloc[0].tolist(), ["Categoría", "Baño"])


class TestBuclesPorFila(unittest.TestCase):
    """`apply(axis=1)` arma un Series por fila para leer dos o cuatro columnas."""

    def test_las_claves_centry_dan_lo_mismo_que_apply(self):
        df = pd.DataFrame({
            "Metafield: custom.codigo_modelo_color [id]": ["ab-1", "", None],
            "Mod-Col": ["", "xy-2", None],
            "COD MOD COL": ["", "", "zz-3"],
            "Variant SKU": ["SK1-40", "SK2-41", "SK3-42"],
            "relleno": ["x", "y", "z"],
        })
        self.assertEqual(
            app.centry_keys_de_frame(df),
            df.apply(app.centry_mod_col_from_row, axis=1).tolist(),
        )

    def test_con_una_columna_ausente(self):
        df = pd.DataFrame({"Variant SKU": ["SK1-40", "SK2"]})
        self.assertEqual(
            app.centry_keys_de_frame(df),
            df.apply(app.centry_mod_col_from_row, axis=1).tolist(),
        )

    def test_con_columnas_repetidas_cae_a_apply(self):
        df = pd.DataFrame([["ab-1", "cd-2", "SK1-40"]],
                          columns=["Mod-Col", "Mod-Col", "Variant SKU"])
        self.assertEqual(
            app.centry_keys_de_frame(df),
            df.apply(app.centry_mod_col_from_row, axis=1).tolist(),
        )

    def test_la_busqueda_da_lo_mismo_que_apply(self):
        df = pd.DataFrame({
            "Mod-Col": ["AB-1", "CD-2", "EF-3"],
            "Nombre": ["Zapatilla Roja", "Casaca Azul", "Polera Roja"],
        }).astype(object)
        esperado = df.apply(
            lambda fila: "roja" in " ".join(app.clean_value(v).lower() for v in fila.values),
            axis=1,
        )
        pd.testing.assert_series_equal(
            app._mascara_de_busqueda(df, "roja"), esperado, check_dtype=False)

    def test_un_frame_de_tipos_mezclados_se_queda_con_apply(self):
        """Ahi el Series de la fila SI promueve el tipo y el texto cambiaria."""
        df = pd.DataFrame({"texto": ["uno", "dos"], "numero": [1, 2]})
        self.assertIsNone(app._filas_como_valores(df))
        esperado = df.apply(
            lambda fila: "uno" in " ".join(app.clean_value(v).lower() for v in fila.values),
            axis=1,
        )
        pd.testing.assert_series_equal(
            app._mascara_de_busqueda(df, "uno"), esperado, check_dtype=False)

    def test_el_maestro_arti_no_arma_un_series_por_fila(self):
        fuente = (ROOT / "app_matrixify.py").read_text(encoding="utf-8")
        self.assertNotIn(
            'arti.apply(lambda row: stock_key_from_parts(', fuente,
            "el maestro ARTI son cientos de miles de filas",
        )


class TestElSnapshotDelJobNoSeRecorreUnaVezPorProducto(unittest.TestCase):
    def test_las_claves_precalculadas_dan_el_mismo_subconjunto(self):
        df = pd.DataFrame({
            "Handle": ["a", "a", "b", "b", "c"],
            "Variant SKU": ["1", "2", "3", "4", "5"],
        })
        claves = app._sync_job_product_key_series(df, mode="full")
        for clave in ("a", "b", "c"):
            pd.testing.assert_frame_equal(
                app._sync_job_subset_df(df, clave, mode="full"),
                app._sync_job_subset_df(df, clave, mode="full", keys=claves),
            )

    def test_el_bloque_las_calcula_una_sola_vez(self):
        fuente = (ROOT / "app_matrixify.py").read_text(encoding="utf-8")
        arbol = ast.parse(fuente)
        for nodo in ast.walk(arbol):
            if isinstance(nodo, ast.FunctionDef) and nodo.name == "process_sync_job_next_block":
                cuerpo = ast.get_source_segment(fuente, nodo) or ""
                self.assertEqual(cuerpo.count("_sync_job_product_key_series("), 1)
                self.assertIn("keys=claves_del_snapshot", cuerpo)
                return
        self.fail("no se encontro process_sync_job_next_block")

    def test_el_snapshot_no_se_copia_para_picklearlo(self):
        fuente = (ROOT / "app_matrixify.py").read_text(encoding="utf-8")
        self.assertNotIn("pickle.dump(source_df.copy()", fuente)


class TestLasCachesDeDiscoSeLimpian(unittest.TestCase):
    """El disco del contenedor es una cuota fija."""

    def test_los_jobs_viejos_se_borran_con_su_pickle(self):
        app.SYNC_JOB_DIR.mkdir(parents=True, exist_ok=True)
        for viejo in app.SYNC_JOB_DIR.glob("prueba_*"):
            viejo.unlink()
        creados = []
        for i in range(app.JOBS_SINCRONIZACION_MAXIMOS + 4):
            nombre = f"prueba_{i:03d}"
            registro = app.SYNC_JOB_DIR / f"{nombre}.json"
            registro.write_text("{}")
            app._sync_job_data_path(nombre).write_bytes(b"x" * 100)
            marca = time.time() - i * 3600
            os.utime(registro, (marca, marca))
            creados.append(nombre)
        try:
            app._purgar_jobs_de_sincronizacion_viejos()
            vivos = [n for n in creados if (app.SYNC_JOB_DIR / f"{n}.json").exists()]
            self.assertLessEqual(len(vivos), app.JOBS_SINCRONIZACION_MAXIMOS)
            self.assertIn("prueba_000", vivos, "el mas reciente no se toca")
            for nombre in creados:
                if nombre not in vivos:
                    self.assertFalse(app._sync_job_data_path(nombre).exists(),
                                     "el pickle del snapshot tiene que irse con su registro")
        finally:
            for resto in app.SYNC_JOB_DIR.glob("prueba_*"):
                resto.unlink()

    def test_un_catalogo_caducado_se_BORRA_no_solo_se_ignora(self):
        sitio = "sitio_de_prueba_optimizacion"
        config = {"shop_domain": "prueba.myshopify.com", "token": "x"}
        ruta = app._ruta_catalogo_en_disco(sitio)
        ruta.parent.mkdir(parents=True, exist_ok=True)
        try:
            app.guardar_catalogo_en_disco(sitio, config, [{"id": "1"}])
            self.assertTrue(ruta.exists())
            productos, _ = app.catalogo_en_disco(sitio, config, minutos=0)
            self.assertIsNone(productos)
            self.assertFalse(ruta.exists(), "un catalogo caducado ocupa disco para nada")
        finally:
            if ruta.exists():
                ruta.unlink()

    def test_un_pickle_ilegible_tambien_se_borra(self):
        sitio = "sitio_roto_optimizacion"
        ruta = app._ruta_catalogo_en_disco(sitio)
        ruta.parent.mkdir(parents=True, exist_ok=True)
        ruta.write_bytes(b"esto no es un pickle")
        try:
            self.assertEqual(app.catalogo_en_disco(sitio, {"shop_domain": "x", "token": "y"}),
                             (None, None))
            self.assertFalse(ruta.exists())
        finally:
            if ruta.exists():
                ruta.unlink()


class TestLosExcelDelUsuarioNoSeACUMULAN(unittest.TestCase):
    """El prefijo lleva el SITIO: pasar por varios dejaba uno residente por sitio."""

    class _Archivo(io.BytesIO):
        def __init__(self, nombre, datos):
            super().__init__(datos)
            self.name = nombre
            self.size = len(datos)

    def _excel(self, valor):
        buffer = io.BytesIO()
        pd.DataFrame({"a": [valor]}).to_excel(buffer, index=False)
        return buffer.getvalue()

    def setUp(self):
        self._sesion = app.st.session_state
        app.st.session_state = {}

    def tearDown(self):
        app.st.session_state = self._sesion

    def test_solo_quedan_los_ultimos(self):
        for i in range(app.EXCEL_EN_SESION_MAXIMOS + 3):
            archivo = self._Archivo(f"input_{i}.xlsx", self._excel(f"v{i}"))
            app.read_uploaded_excel_cached(archivo, f"complete_input_sitio{i}")
        vivos = [c for c in app.st.session_state if c.endswith("_df")]
        self.assertLessEqual(len(vivos), app.EXCEL_EN_SESION_MAXIMOS)

    def test_el_que_sigue_en_uso_se_reusa_sin_releer(self):
        archivo = self._Archivo("input.xlsx", self._excel("uno"))
        primero = app.read_uploaded_excel_cached(archivo, "complete_input_vans")
        segundo = app.read_uploaded_excel_cached(archivo, "complete_input_vans")
        self.assertIs(primero, segundo)

    def test_el_registro_vive_en_la_sesion_y_no_en_un_global(self):
        """Streamlit Cloud corre UN proceso para todas las personas."""
        archivo = self._Archivo("input.xlsx", self._excel("uno"))
        app.read_uploaded_excel_cached(archivo, "complete_input_vans")
        self.assertIn(app.CLAVE_EXCEL_EN_SESION, app.st.session_state)


class TestNoQuedanLibrosDeExcelAbiertos(unittest.TestCase):
    def test_todo_pd_ExcelFile_va_dentro_de_un_with(self):
        """`pd.ExcelFile` deja abierto el zip del libro entero."""
        for archivo in ("app_matrixify.py", "generate_columbia_matrixify.py"):
            fuente = (ROOT / archivo).read_text(encoding="utf-8")
            arbol = ast.parse(fuente)
            dentro_de_with = set()
            for nodo in ast.walk(arbol):
                if isinstance(nodo, ast.With):
                    for item in nodo.items:
                        for hijo in ast.walk(item.context_expr):
                            dentro_de_with.add(id(hijo))
            for nodo in ast.walk(arbol):
                if not isinstance(nodo, ast.Call):
                    continue
                if getattr(nodo.func, "attr", "") != "ExcelFile":
                    continue
                self.assertIn(
                    id(nodo), dentro_de_with,
                    f"{archivo}:{nodo.lineno} abre un libro y no lo cierra",
                )


if __name__ == "__main__":
    unittest.main(verbosity=2)
