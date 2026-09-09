"""El pico de memoria de "Generar la carga de Supermall" (septiembre 2026).

Reportado literal: *"le di click a generar excel y cargo todo, termino y se
quedo asi; ya paso 20 min y no sale nada"*.

No estaba colgado y no habia excepcion: **el contenedor mata el proceso**.
Streamlit Community Cloud da 1.024 MB **para toda la app**, y cuando se pasa
no hay traza ni `st.error` -- `run_app()` no llega a atrapar nada porque muere
el proceso entero -- asi que la pantalla se queda exactamente como estaba.

Medido a la escala del usuario (8.928 codigos, 38.423 filas de Matrixify y el
maestro ARTI de verdad, 653.431 filas), con catalogos de PRUEBA -- o sea sin
los seis catalogos reales que en produccion viven en `session_state`:

    supermall_generar   183,6 s   pico 1.007 MB
    el Excel             36,1 s

Con 1.007 MB de 1.024 y los catalogos de verdad encima, no cabe.

De donde salia el pico:

- `contexto["arti"]` es una copia ENTERA del maestro normalizado, y seguia
  viva durante el `concat`, la hoja Sial y el Excel, encima del maestro crudo
  que ya esta en `session_state`: dos maestros a la vez.
- el maestro del contexto llevaba las 653.431 filas aunque la carga toque
  unas 40.000, y cada uno de los 45 bloques volvia a barrerlas enteras.
- `dataframe_to_excel_bytes` copiaba el archivo entero con `getvalue()`
  aunque no fuera a memoizarlo.
- la pantalla se quedaba con los tres frames grandes vivos durante todo el
  resto del dibujado.

Ejecutar:  python scripts/test_supermall_pico_de_memoria.py
"""
import ast
import sys
import unittest
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import app_matrixify as app  # noqa: E402

FUENTE = (ROOT / "app_matrixify.py").read_text(encoding="utf-8")


def _cuerpo(nombre):
    arbol = ast.parse(FUENTE)
    for nodo in ast.walk(arbol):
        if isinstance(nodo, (ast.FunctionDef, ast.AsyncFunctionDef)) and nodo.name == nombre:
            return ast.get_source_segment(FUENTE, nodo) or ""
    raise AssertionError(f"no se encontro {nombre}")


def catalogo(codigos):
    return pd.DataFrame([{
        "Handle": codigo.lower(),
        "ID": f"gid://{i}",
        "Title": f"Producto {codigo}",
        "Body HTML": "<p>texto</p>",
        "Type": "Zapatilla",
        "Tags": "Columbia",
        "Vendor": "sitiope",
        "Metafield: custom.codigo_modelo_color [id]": codigo,
    } for i, codigo in enumerate(codigos)])


def maestro(codigos, con_ean=()):
    return pd.DataFrame([{
        "Mod-Col": codigo, "COD MOD COL": codigo,
        "CODINT_MA": f"{codigo}-{talla}", "TALNUM_MA": str(talla),
        "MARCA_MA": "COLUMBIA", "Precio": "199.90",
        "CodBarras": f"77{i}{talla}" if codigo in con_ean else "",
        "NombreModelo": f"Producto {codigo}", "TipoProducto": "Zapatilla",
        "Genero": "Hombre",
    } for i, codigo in enumerate(codigos) for talla in (400, 410, 420)])


MARCA = {"site_key": "supermall", "label": "Supermall",
         "allowed_arti_brands": ["COLUMBIA"], "sial_active_columns": ["13"],
         "sial_tail_columns": ["Nuevo o Actualizar (Supermall.pe)",
                               "Porduct Id - Supermall.pe", "13"]}

TODOS = [f"MC{j:04d}-XX" for j in range(30)]
PEDIDOS = TODOS[:6]


class TestElMaestroSeAcotaALaCarga(unittest.TestCase):
    """Con el maestro entero, una carga de 200 codigos barria 653.431 filas."""

    def test_solo_quedan_las_filas_de_los_codigos_pedidos(self):
        contexto = app.preparar_contexto_de_codigos(
            catalogo(TODOS), maestro(TODOS), MARCA, codigos=PEDIDOS,
        )
        claves = set(contexto["arti"]["__KEY"])
        self.assertEqual(claves, set(PEDIDOS))
        self.assertEqual(len(contexto["arti"]), len(PEDIDOS) * 3)

    def test_un_codigo_de_SOLO_MODELO_arrastra_todos_sus_colores(self):
        """El bloque filtra por `__MODEL` cuando el codigo no lleva guion, asi
        que el acotado tiene que dejar pasar lo mismo o el color se pierde."""
        contexto = app.preparar_contexto_de_codigos(
            catalogo(TODOS), maestro(["AB-N1", "AB-N2", "CD-N1"]), MARCA,
            codigos=["AB"],
        )
        self.assertEqual(set(contexto["arti"]["__KEY"]), {"AB-N1", "AB-N2"})

    def test_sin_codigos_el_maestro_va_ENTERO(self):
        """Es el comportamiento de siempre: Centry y la Carga Sial parcial no
        pueden cambiar porque Supermall acote el suyo."""
        contexto = app.preparar_contexto_de_codigos(
            catalogo(TODOS), maestro(TODOS), MARCA,
        )
        self.assertEqual(len(contexto["arti"]), len(TODOS) * 3)

    def test_los_diagnosticos_se_calculan_sobre_el_maestro_ENTERO(self):
        """Son sobre el ESTADO del maestro, no sobre esta carga.

        Aqui los codigos pedidos no tienen EAN y otros si. Acotando ANTES de
        los diagnosticos, el maestro pareceria no tener ni un EAN y la hoja de
        Revision ganaria un aviso que no le corresponde.
        """
        contexto = app.preparar_contexto_de_codigos(
            catalogo(TODOS), maestro(TODOS, con_ean=set(TODOS[10:])), MARCA,
            codigos=PEDIDOS,
        )
        problemas = [d["Mod-Col"] for d in contexto["diagnosticos"]]
        self.assertEqual(problemas, ["Diagnostico EAN"])
        self.assertNotIn("Diagnostico BigQuery", problemas)


class TestLaSalidaNoCambia(unittest.TestCase):
    def test_acotar_el_maestro_da_EXACTAMENTE_lo_mismo(self):
        origen, arti = catalogo(TODOS), maestro(TODOS)
        resultados = []
        for codigos in (None, PEDIDOS):
            contexto = app.preparar_contexto_de_codigos(
                origen, arti, MARCA, codigos=codigos,
            )
            matrixify, _revision = app.build_centry_matrixify_from_master(
                PEDIDOS, origen, arti, MARCA, contexto=contexto,
            )
            resultados.append(matrixify.reset_index(drop=True).astype(str))
        self.assertFalse(resultados[0].empty, "el caso base no genero nada")
        pd.testing.assert_frame_equal(resultados[0], resultados[1])

    def test_por_bloques_da_lo_mismo_que_de_una_vez(self):
        origen, arti = catalogo(TODOS), maestro(TODOS)
        contexto = app.preparar_contexto_de_codigos(
            origen, arti, MARCA, codigos=TODOS,
        )
        entero, _ = app.build_centry_matrixify_from_master(
            TODOS, origen, arti, MARCA, contexto=contexto)
        partes = [
            app.build_centry_matrixify_from_master(
                bloque, origen, arti, MARCA, contexto=contexto)[0]
            for bloque in app.png_bloques(TODOS, 7)
        ]
        por_bloques = pd.concat(partes, ignore_index=True)
        pd.testing.assert_frame_equal(
            entero.reset_index(drop=True).astype(str),
            por_bloques.reset_index(drop=True).astype(str),
        )


class TestLoQueSeSueltaYCuando(unittest.TestCase):
    def test_el_contexto_se_suelta_ANTES_de_la_hoja_Sial(self):
        cuerpo = _cuerpo("supermall_generar")
        self.assertIn("del contexto", cuerpo)
        self.assertLess(
            cuerpo.index("del contexto"),
            cuerpo.index("build_sial_de_sitio_from_matrixify("),
            "el maestro del contexto sigue vivo durante la parte que mas "
            "memoria pide",
        )

    def test_las_listas_de_partes_se_vacian_tras_el_concat(self):
        cuerpo = _cuerpo("supermall_generar")
        for linea in ("partes.clear()", "revisiones.clear()"):
            self.assertIn(linea, cuerpo)
        self.assertLess(cuerpo.index("pd.concat(partes"), cuerpo.index("partes.clear()"))

    def test_los_dos_llamadores_le_pasan_los_codigos(self):
        """Si uno no los pasa, ahi el maestro sigue yendo entero y nadie lo ve."""
        for nombre in ("build_centry_matrixify_from_master", "supermall_generar"):
            cuerpo = _cuerpo(nombre)
            self.assertIn("preparar_contexto_de_codigos(", cuerpo, nombre)
            trozo = cuerpo[cuerpo.index("preparar_contexto_de_codigos("):]
            self.assertIn("codigos=", trozo[:400], nombre)

    def test_la_pantalla_suelta_los_frames_al_terminar_el_excel(self):
        cuerpo = _cuerpo("render_carga_supermall")
        self.assertIn("del matrixify_df, sial_df, revision_df", cuerpo)
        self.assertLess(
            cuerpo.index("dataframe_to_excel_bytes("),
            cuerpo.index("del matrixify_df, sial_df, revision_df"),
        )

    def test_la_hoja_Sial_suelta_su_lista_de_filas(self):
        """38.000 diccionarios de 50 claves son otra copia entera de la hoja.

        Se sueltan ANTES del `fillna`, que copia el frame: guardandolos hasta
        el final conviven la lista, el frame y su copia.
        """
        for nombre in ("build_sial_de_sitio_from_matrixify",
                       "build_centry_sial_from_matrixify"):
            cuerpo = _cuerpo(nombre)
            self.assertIn("rows.clear()", cuerpo, nombre)
            self.assertLess(cuerpo.index("pd.DataFrame(rows"),
                            cuerpo.index("rows.clear()"), nombre)
            self.assertLess(cuerpo.index("rows.clear()"),
                            cuerpo.index(".fillna("), nombre)

    def test_los_conteos_se_sacan_ANTES_de_armar_el_excel(self):
        """Si se sacaran despues, los frames tendrian que seguir vivos."""
        cuerpo = _cuerpo("render_carga_supermall")
        self.assertLess(
            cuerpo.index("modelos_generados ="),
            cuerpo.index("dataframe_to_excel_bytes("),
        )


class TestElMaestroNoSeQuedaEnSesion(unittest.TestCase):
    """336,9 MB medidos: el objeto mas grande de toda la app."""

    def test_olvidar_arti_borra_las_tres_claves(self):
        import streamlit as st
        for sufijo in ("", "_source", "_meta"):
            st.session_state[f"arti_cache_supermall{sufijo}"] = "algo"
        st.session_state["arti_cache_vans"] = "no se toca"
        app.olvidar_arti_de_la_sesion({"site_key": "supermall"})
        for sufijo in ("", "_source", "_meta"):
            self.assertNotIn(f"arti_cache_supermall{sufijo}", st.session_state)
        self.assertIn("arti_cache_vans", st.session_state)

    def test_olvidar_arti_no_revienta_si_no_hay_nada(self):
        app.olvidar_arti_de_la_sesion({"site_key": "sitio_que_no_existe"})

    def test_supermall_lo_suelta_TRAS_preparar_el_contexto(self):
        """Antes del contexto seria soltarlo sin haberlo usado; despues del
        bucle, ya se pago la memoria durante toda la generacion."""
        cuerpo = _cuerpo("supermall_generar")
        self.assertIn("olvidar_arti_de_la_sesion(brand_config)", cuerpo)
        self.assertLess(
            cuerpo.index("preparar_contexto_de_codigos("),
            cuerpo.index("olvidar_arti_de_la_sesion(brand_config)"),
        )
        self.assertLess(
            cuerpo.index("olvidar_arti_de_la_sesion(brand_config)"),
            cuerpo.index("for bloque in png_bloques("),
        )

    def test_la_referencia_local_al_maestro_tambien_se_suelta(self):
        """Borrarlo de la sesion no sirve de nada si la variable local lo
        sigue apuntando: el bucle lee `contexto["arti"]`, no este frame."""
        cuerpo = _cuerpo("supermall_generar")
        self.assertIn("arti_df = None", cuerpo)
        self.assertLess(cuerpo.index("arti_df = None"),
                        cuerpo.index("for bloque in png_bloques("))


class TestLasCopiasQueNoHacianFalta(unittest.TestCase):
    """Cada copia de una hoja de 38.000 filas son ~90 MB de los 1.024."""

    def test_las_dos_hojas_Sial_no_pagan_la_copia_defensiva(self):
        for nombre in ("build_sial_de_sitio_from_matrixify",
                       "build_centry_sial_from_matrixify"):
            self.assertIn("copiar=False", _cuerpo(nombre), nombre)

    def test_por_defecto_SIGUE_sin_tocar_el_frame_de_quien_llama(self):
        """`copiar=False` es para quien acaba de construir el frame; el resto
        no puede notar la diferencia."""
        df = pd.DataFrame({"Mod-Col": ["A-1", "A-1"], "Talla": ["O/S", "40"]})
        antes = df.copy()
        app.filter_centry_size_rows(df, [], "Talla", key_column="Mod-Col")
        pd.testing.assert_frame_equal(df, antes)

    def test_con_copiar_False_el_resultado_es_el_MISMO(self):
        base = pd.DataFrame({"Mod-Col": ["A-1", "A-1", "B-2"],
                             "Talla": ["0", "40", "O/S"]})
        con, _ = app.filter_centry_size_rows(
            base.copy(), [], "Talla", key_column="Mod-Col")
        sin, _ = app.filter_centry_size_rows(
            base.copy(), [], "Talla", key_column="Mod-Col", copiar=False)
        pd.testing.assert_frame_equal(con, sin)

    def test_una_hoja_limpia_no_se_copia_para_repararla(self):
        limpia = pd.DataFrame({"a": ["hola", "adios"], "n": [1, 2]})
        self.assertFalse(app.hoja_necesita_reparacion(limpia))

    def test_una_hoja_con_mojibake_SI_se_repara(self):
        self.assertTrue(app.hoja_necesita_reparacion(pd.DataFrame({"a": ["BaÃ±o"]})))

    def test_una_CABECERA_con_mojibake_tambien_cuenta(self):
        """El nombre de una columna es una LLAVE: si sale mal, no coincide."""
        self.assertTrue(app.hoja_necesita_reparacion(pd.DataFrame({"CategorÃ­a": ["x"]})))

    def test_la_exportacion_pregunta_antes_de_copiar(self):
        cuerpo = _cuerpo("dataframe_to_excel_bytes")
        self.assertIn("if hoja_necesita_reparacion(df):", cuerpo)

    def test_el_excel_sigue_saliendo_reparado(self):
        hojas = {"H": pd.DataFrame({"CategorÃ­a": ["BaÃ±o"]})}
        leido = pd.read_excel(app.dataframe_to_excel_bytes(hojas), sheet_name="H")
        self.assertEqual(list(leido.columns), ["Categoría"])
        self.assertEqual(leido.iloc[0, 0], "Baño")


class TestElExcelNoSeCopiaDeBalde(unittest.TestCase):
    def test_el_tamano_se_mide_SIN_copiar(self):
        cuerpo = _cuerpo("dataframe_to_excel_bytes")
        self.assertIn("buffer.getbuffer().nbytes", cuerpo)
        self.assertLess(
            cuerpo.index("buffer.getbuffer().nbytes"),
            cuerpo.index("buffer.getvalue()"),
            "se copia el archivo entero antes de saber si cabe en el memo",
        )

    def test_el_memo_sigue_funcionando(self):
        hojas = {"Products": pd.DataFrame({"A": ["1", "2"], "B": ["x", "y"]})}
        primero = app.dataframe_to_excel_bytes(hojas).getvalue()
        segundo = app.dataframe_to_excel_bytes(hojas).getvalue()
        self.assertEqual(primero, segundo)

    def test_dos_buffers_distintos(self):
        """Devolver el mismo objeto dejaria que un lector moviera la posicion."""
        hojas = {"Products": pd.DataFrame({"A": ["1"]})}
        uno = app.dataframe_to_excel_bytes(hojas)
        dos = app.dataframe_to_excel_bytes(hojas)
        self.assertIsNot(uno, dos)
        uno.read()
        self.assertEqual(dos.tell(), 0)


if __name__ == "__main__":
    unittest.main(verbosity=2)
