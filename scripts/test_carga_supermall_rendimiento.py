"""Pruebas de por que "lo de Supermall no cargaba" (septiembre 2026).

`build_centry_matrixify_from_master` se llama **una vez por bloque**, y la carga
de Supermall va en bloques de 200 codigos: con 11.000 codigos son 55 llamadas.
En cada una se volvia a preparar TODO desde cero:

- copiar y normalizar el catalogo de ORIGEN entero y el del DESTINO entero,
- recorrerlos con `forward_fill_product_block` y calcular sus claves,
- construir los dos `lookup` producto a producto con `groupby` + `.iloc[0]`,
- y **copiar y normalizar el maestro ARTI COMPLETO** -- 653.000 filas en
  produccion -- para quedarse despues con las 200 filas del bloque.

Nada de eso depende de los codigos del bloque. Medido con 11.000 codigos y un
catalogo de 55.000 filas: **22,4 s por bloque, o sea 20,5 minutos** de reloj.
Eso era el "no carga".

Ejecutar:  python scripts/test_carga_supermall_rendimiento.py
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


def catalogo(n=40, desde=0):
    return pd.DataFrame([{
        "Handle": f"mc{j:04d}-xx",
        "ID": f"gid://{desde + j}",
        "Title": f"Producto {j}",
        "Body HTML": "<p>texto</p>",
        "Type": "Zapatilla",
        "Tags": "Columbia",
        "Vendor": "sitiope",
        "Metafield: custom.codigo_modelo_color [id]": f"MC{j:04d}-XX",
    } for j in range(n)])


def maestro(n=40):
    return pd.DataFrame([{
        "Mod-Col": f"MC{j:04d}-XX", "COD MOD COL": f"MC{j:04d}-XX",
        "CODINT_MA": f"SKU{j}-{k}", "TALNUM_MA": str(talla),
        "MARCA_MA": "COLUMBIA", "Precio": "199.90", "CodBarras": f"77{j}{k}",
    } for j in range(n) for k, talla in enumerate((400, 410, 420))])


class TestLaPreparacionSaleDelBucleDeBloques(unittest.TestCase):
    def test_supermall_prepara_el_contexto_UNA_vez(self):
        cuerpo = _cuerpo("supermall_generar")
        self.assertIn("preparar_contexto_de_codigos(", cuerpo)
        self.assertIn("contexto=contexto", cuerpo)
        # La preparacion tiene que quedar ANTES del bucle de bloques.
        self.assertLess(
            cuerpo.index("preparar_contexto_de_codigos("),
            cuerpo.index("for bloque in png_bloques("),
            "preparado dentro del bucle se vuelve a pagar en cada bloque",
        )

    def test_el_maestro_ya_no_se_normaliza_en_cada_bloque(self):
        cuerpo = _cuerpo("build_centry_matrixify_from_master")
        self.assertNotIn("normalize_arti_columns_for_app(arti_df)", cuerpo)
        self.assertIn('arti = contexto["arti"]', cuerpo)

    def test_los_catalogos_ya_no_se_copian_en_cada_bloque(self):
        cuerpo = _cuerpo("build_centry_matrixify_from_master")
        for caro in ("coalesce_duplicate_columns(shopify_matrixify_df)",
                     "forward_fill_product_block(",
                     "centry_keys_de_frame("):
            self.assertNotIn(caro, cuerpo, f"{caro} se rehacia una vez por bloque")

    def test_el_resolutor_del_maestro_sale_del_bucle_por_producto(self):
        """Solo depende de las COLUMNAS del maestro: se rearmaba una vez por
        modelo-color."""
        cuerpo = _cuerpo("build_centry_matrixify_from_master")
        self.assertLess(
            cuerpo.index("resolutor_maestro = centry_resolutor(arti)"),
            cuerpo.index('for key, variants in arti.groupby("__KEY"'),
        )

    def test_sin_contexto_sigue_funcionando_igual(self):
        """Centry y Carga Sial llaman una sola vez y no pasan contexto."""
        sin, _ = app.build_centry_matrixify_from_master(
            ["MC0000-XX"], catalogo(), maestro(), {"label": "Columbia"})
        contexto = app.preparar_contexto_de_codigos(
            catalogo(), maestro(), {"label": "Columbia"})
        con, _ = app.build_centry_matrixify_from_master(
            ["MC0000-XX"], catalogo(), maestro(), {"label": "Columbia"}, contexto=contexto)
        pd.testing.assert_frame_equal(sin, con)

    def test_el_contexto_da_lo_MISMO_bloque_a_bloque_que_de_una_vez(self):
        """Es la prueba de fondo: partir en bloques con un contexto compartido
        no puede cambiar ni una celda."""
        cat, mae, cfg = catalogo(30), maestro(30), {"label": "Columbia"}
        codigos = [f"MC{j:04d}-XX" for j in range(30)]
        entero, _ = app.build_centry_matrixify_from_master(codigos, cat, mae, cfg)
        contexto = app.preparar_contexto_de_codigos(cat, mae, cfg)
        partes = []
        for inicio in range(0, len(codigos), 7):
            parte, _ = app.build_centry_matrixify_from_master(
                codigos[inicio:inicio + 7], cat, mae, cfg, contexto=contexto)
            if not parte.empty:
                partes.append(parte)
        por_bloques = pd.concat(partes, ignore_index=True)
        self.assertEqual(len(entero), len(por_bloques))
        clave = "Metafield: custom.codigo_modelo_color [id]"
        pd.testing.assert_frame_equal(
            entero.sort_values([clave, "Variant SKU"]).reset_index(drop=True),
            por_bloques.sort_values([clave, "Variant SKU"]).reset_index(drop=True),
        )

    def test_el_contexto_NO_se_muta_al_usarlo(self):
        """Si un bloque tocara el maestro compartido, el siguiente veria otra
        cosa. El acotado va con `.copy()` antes de escribir nada."""
        cat, mae, cfg = catalogo(10), maestro(10), {"label": "Columbia"}
        contexto = app.preparar_contexto_de_codigos(cat, mae, cfg)
        antes_arti = contexto["arti"].copy()
        antes_shopify = contexto["shopify_df"].copy()
        app.build_centry_matrixify_from_master(
            ["MC0000-XX"], cat, mae, cfg, contexto=contexto)
        pd.testing.assert_frame_equal(contexto["arti"], antes_arti)
        pd.testing.assert_frame_equal(contexto["shopify_df"], antes_shopify)

    def test_los_diagnosticos_del_maestro_siguen_saliendo_en_cada_bloque(self):
        """Se calculan una vez, pero la hoja de Revision tiene que decir lo
        mismo que antes."""
        cat, mae, cfg = catalogo(10), maestro(10), {"label": "Columbia"}
        contexto = app.preparar_contexto_de_codigos(cat, mae, cfg)
        _, revision = app.build_centry_matrixify_from_master(
            ["MC0000-XX"], cat, mae, cfg, contexto=contexto)
        self.assertIn("Diagnostico EAN", set(revision["Mod-Col"]))


class TestElLookupPorClave(unittest.TestCase):
    """El `groupby` + `.iloc[0]` se llevaba 30 de los 58 segundos del perfil."""

    def test_da_lo_mismo_que_el_groupby(self):
        df = pd.DataFrame({
            "__CENTRY_KEY": ["ab-1", "ab-1", "CD-2", "cd-2", "", "ef-3"],
            "Handle": ["h1", "h2", "h3", "h4", "h5", "h6"],
            "ID": ["1", "2", "3", "4", "5", "6"],
        })
        esperado = {}
        for clave, grupo in df.groupby("__CENTRY_KEY", sort=False):
            clave = app.clean_value(clave).upper()
            if clave and clave not in esperado:
                esperado[clave] = grupo.iloc[0]
        obtenido = app._lookup_por_clave(df)
        self.assertEqual(set(obtenido), set(esperado))
        for clave in esperado:
            self.assertEqual(
                obtenido[clave].get("Handle"), esperado[clave].get("Handle"),
                f"gana la primera aparicion, no otra ({clave})",
            )

    def test_la_clave_vacia_no_entra(self):
        df = pd.DataFrame({"__CENTRY_KEY": ["", "  ", "ab-1"], "Handle": ["a", "b", "c"]})
        self.assertEqual(set(app._lookup_por_clave(df)), {"AB-1"})

    def test_frame_vacio_o_sin_la_columna(self):
        self.assertEqual(app._lookup_por_clave(pd.DataFrame()), {})
        self.assertEqual(app._lookup_por_clave(pd.DataFrame({"otra": [1]})), {})
        self.assertEqual(app._lookup_por_clave(None), {})

    def test_los_valores_sobreviven_al_astype(self):
        """Se pasa a `object` para no buscar el tipo comun en cada fila. El tipo
        comun que pandas calculaba ERA `object`, asi que el valor no cambia."""
        df = pd.DataFrame({
            "__CENTRY_KEY": ["ab-1"],
            "texto": pd.array(["valor"], dtype="string"),
            "objeto": pd.Series(["otro"], dtype=object),
            "numero": [7],
            "vacio": [None],
        })
        fila = app._lookup_por_clave(df)["AB-1"]
        self.assertEqual(fila.get("texto"), "valor")
        self.assertEqual(fila.get("objeto"), "otro")
        self.assertEqual(app.clean_value(fila.get("numero")), "7")
        self.assertEqual(app.clean_value(fila.get("vacio")), "")


class TestElContextoNoTocaShopify(unittest.TestCase):
    def test_preparar_no_escribe_en_la_tienda(self):
        cuerpo = _cuerpo("preparar_contexto_de_codigos")
        for mutacion in ("productCreateMedia", "metafieldsSet", "productUpdate",
                         "productCreate", "run_shopify_mutation", "apply_shopify_preview"):
            self.assertNotIn(mutacion, cuerpo)


if __name__ == "__main__":
    unittest.main(verbosity=2)
