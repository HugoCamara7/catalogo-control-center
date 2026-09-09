"""El Handle, el tipo por sitio y la clave Modelo+Color (septiembre 2026).

Tres fallos de la carga POR CODIGOS -- la que sirve a Centry, a la Carga Sial
parcial y a **Carga Supermall** --, todos reproducidos contra el maestro real
antes de tocar nada:

1. **El Handle salia a medias.** Un producto que no esta en la tienda destino
   recibia `key.lower()`, o sea el codigo pelado (`10001330-n11`), mientras la
   carga completa del MISMO producto armaba
   `cooler-pfg-welded-harbody-10001330-n11-negro`. Medido: **2.448 de 2.448
   filas**. Y el handle es la URL del producto en la tienda.

2. **El Type se copiaba del sitio de ORIGEN sin traducir.** Una carga de
   Supermall se llevaba los nombres de Columbia.pe, y Rockford -- que es
   multimarca -- heredaba la clasificacion de la marca de la que viniera el
   producto en vez de la suya.

3. **Los codigos no se deduplicaban.** Dentro de una llamada el `groupby` los
   colapsa, pero la carga va POR BLOQUES: el mismo codigo en dos bloques deja
   el producto dos veces en el Matrixify concatenado, y Modelo+Color es LA
   clave del producto.

Ejecutar:  python scripts/test_handle_tipo_y_duplicados.py
"""
import sys
import unittest
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import app_matrixify as app  # noqa: E402
import generate_columbia_matrixify as gen  # noqa: E402
import engines.garment_types as gt  # noqa: E402

CLAVE = "Metafield: custom.codigo_modelo_color [id]"


def catalogo(codigos, titulo="Casaca Hombre Columbia", tipo="Cortavientos"):
    filas = []
    for j, codigo in enumerate(codigos):
        filas.append({
            "Handle": f"viejo-{codigo.lower()}", "ID": f"gid://{j}",
            "Title": f"{titulo} {j}", "Body HTML": "<p>t</p>", "Type": tipo,
            "Tags": "Columbia", "Vendor": "columbiape", CLAVE: codigo,
            "Metafield: custom.color [single_line_text_field]": "NEGRO",
        })
    return pd.DataFrame(filas)


def maestro(codigos):
    return pd.DataFrame([{
        "Mod-Col": c, "COD MOD COL": c, "CODINT_MA": f"SKU{c}-{k}",
        "TALNUM_MA": str(t), "MARCA_MA": "COLUMBIA", "Precio": "199.90",
        "CodBarras": f"77{j}{k}",
    } for j, c in enumerate(codigos) for k, t in enumerate(("S", "M", "L"))])


def generar(codigos, cfg=None, destino=None, **kw):
    cfg = cfg or {"label": "Columbia", "site_key": "rockford",
                  "allowed_arti_brands": ["COLUMBIA"]}
    return app.build_centry_matrixify_from_master(
        codigos, catalogo(codigos, **kw), maestro(codigos), cfg,
        destino_matrixify_df=destino)


class TestElHandle(unittest.TestCase):
    """La URL del producto en la tienda."""

    def test_un_producto_NUEVO_lleva_nombre_codigo_y_color(self):
        vacio = pd.DataFrame(columns=list(app.MATRIXIFY_COLUMNS))
        salida, _ = generar(["BM4077-P12"], destino=vacio)
        handle = salida["Handle"].iloc[0]
        self.assertNotEqual(handle, "bm4077-p12", "el codigo pelado no es un handle")
        self.assertIn("casaca", handle)
        self.assertIn("bm4077-p12", handle)

    def test_es_EXACTAMENTE_el_de_la_carga_completa(self):
        """Dos handles distintos para el mismo producto segun por donde pase es
        la trampa de las dos `normalize_size`."""
        vacio = pd.DataFrame(columns=list(app.MATRIXIFY_COLUMNS))
        salida, _ = generar(["BM4077-P12"], destino=vacio)
        esperado = gen.build_product_handle(
            salida["Title"].iloc[0], "BM4077-P12",
            salida["Metafield: custom.color [single_line_text_field]"].iloc[0])
        self.assertEqual(salida["Handle"].iloc[0], esperado)

    def test_uno_que_YA_esta_en_el_destino_conserva_el_suyo(self):
        """Cambiarselo romperia su URL y Shopify lo trataria como otro."""
        salida, _ = generar(["BM4077-P12"])  # destino == origen
        self.assertEqual(salida["Handle"].iloc[0], "viejo-bm4077-p12")

    def test_los_siblings_usan_el_MISMO_handle(self):
        """Con otro, el producto se listaria a si mismo con un nombre que no
        existe en la tienda."""
        vacio = pd.DataFrame(columns=list(app.MATRIXIFY_COLUMNS))
        salida, _ = generar(["BM4077-P12"], destino=vacio)
        hermanos = salida["Metafield: custom.siblings [single_line_text_field]"].iloc[0]
        self.assertIn(salida["Handle"].iloc[0], str(hermanos))

    def test_sin_titulo_el_handle_sigue_siendo_util(self):
        vacio = pd.DataFrame(columns=list(app.MATRIXIFY_COLUMNS))
        salida, _ = generar(["BM4077-P12"], destino=vacio, titulo="")
        self.assertTrue(str(salida["Handle"].iloc[0]).strip())


class TestElTipoPorSitio(unittest.TestCase):
    def test_se_traduce_al_vocabulario_del_sitio_destino(self):
        salida, _ = generar(["BM4077-P12"], tipo="Chaquetas")
        self.assertEqual(salida["Type"].iloc[0], gt.tipo_para_sitio("Chaquetas", "rockford"))
        self.assertEqual(salida["Type"].iloc[0], "Casacas")

    def test_un_tipo_que_el_sitio_NO_vende_cae_al_canonico_y_no_se_vacia(self):
        """`tipo_para_sitio` devuelve "" cuando el sitio no vende esa prenda --
        Rockford no vende ocho de los sesenta tipos-- y un Type vacio seria
        perder el dato en vez de traducirlo."""
        sin_rockford = [t["tipo"] for t in gt.TIPOS if "rockford" not in t["sitios"]]
        self.assertTrue(sin_rockford, "si Rockford ya los vende todos, esta prueba sobra")
        tipo = sin_rockford[0]
        self.assertEqual(gt.tipo_para_sitio(tipo, "rockford"), "")
        self.assertEqual(
            app.tipo_de_prenda_para_sitio(tipo, {"site_key": "rockford"}), tipo)

    def test_un_tipo_desconocido_se_deja_tal_cual(self):
        self.assertEqual(
            app.tipo_de_prenda_para_sitio("ChismeQueNadieConoce", {"site_key": "rockford"}),
            "ChismeQueNadieConoce")

    def test_los_dos_caminos_usan_LA_MISMA_regla(self):
        """La carga completa y la carga por codigos no pueden clasificar el
        mismo producto distinto."""
        cfg = {"site_key": "rockford"}
        por_carga_completa, _ = gen.resolve_product_type({"Tipo de prenda": "Chaquetas"}, cfg)
        self.assertEqual(por_carga_completa,
                         app.tipo_de_prenda_para_sitio("Chaquetas", cfg))

    def test_cada_sitio_puede_llamarlo_distinto(self):
        """Rockford es multimarca: manda SU estructura, no la de la marca de
        la que venga el producto."""
        for sitio in ("rockford", "columbia", "hush_puppies", "vans"):
            valor = app.tipo_de_prenda_para_sitio("Chaquetas", {"site_key": sitio})
            self.assertTrue(valor, f"{sitio} dejo el Type vacio")


class TestNuncaSeDuplicaModeloColor(unittest.TestCase):
    def test_un_codigo_repetido_no_duplica_el_producto(self):
        salida, _ = generar(["BM4077-P12", "BM4077-P12"])
        claves = salida[CLAVE].map(lambda v: app.clean_value(v).upper())
        self.assertEqual(claves.nunique(), 1)
        self.assertEqual(len(salida), 3, "tres tallas, no seis")

    def test_la_lista_se_deduplica_ANTES_de_partir_en_bloques(self):
        """Dentro de un bloque el `groupby` colapsa el repetido; entre bloques
        no hay quien lo haga, y la carga de Supermall va de 200 en 200."""
        import ast
        fuente = (ROOT / "app_matrixify.py").read_text(encoding="utf-8")
        for nodo in ast.walk(ast.parse(fuente)):
            if isinstance(nodo, ast.FunctionDef) and nodo.name == "supermall_generar":
                cuerpo = ast.get_source_segment(fuente, nodo) or ""
                self.assertIn("dict.fromkeys(", cuerpo)
                self.assertLess(
                    cuerpo.index("dict.fromkeys("),
                    cuerpo.index("for bloque in png_bloques("),
                    "deduplicar despues de partir en bloques no sirve de nada",
                )
                return
        self.fail("no se encontro supermall_generar")

    def test_el_orden_de_los_codigos_se_conserva(self):
        codigos = ["BM4079-A", "BM4077-P12", "BM4078-P13", "BM4077-P12"]
        salida, _ = generar(codigos)
        vistos = list(dict.fromkeys(
            salida[CLAVE].map(lambda v: app.clean_value(v).upper())))
        self.assertEqual(vistos[0], "BM4079-A", "se reordeno la lista de entrada")


class TestElColorNoSeTiraPorElCamino(unittest.TestCase):
    """`custom.color` se leia de la tienda, se asignaba y se perdia."""

    def test_es_una_columna_del_frame(self):
        """El frame se construye con `columns=default_columns`: la clave que no
        este en esa lista se tira aunque el `row.update` le ponga valor."""
        df = app.shopify_products_to_matrixify_df([{
            "Mod-Col": "BM1-A", "Handle": "h", "Variants": [{}],
            "Metafield: custom.color [single_line_text_field]": "AZUL MARINO",
        }])
        self.assertIn("Metafield: custom.color [single_line_text_field]", df.columns)
        self.assertEqual(
            app.clean_value(df["Metafield: custom.color [single_line_text_field]"].iloc[0]),
            "AZUL MARINO")

    def test_lo_leen_los_tres_extremos(self):
        """Lo lee `shopify_api`, esta en la plantilla de escritura y
        `CENTRY_COLUMNAS_COLOR` lo busca: los tres apuntaban a una columna que
        no existia."""
        self.assertIn("Metafield: custom.color [single_line_text_field]",
                      app.CENTRY_COLUMNAS_COLOR)
        self.assertIn("Metafield: custom.color [single_line_text_field]",
                      list(app.MATRIXIFY_COLUMNS))

    def test_llega_hasta_la_variante_y_el_handle(self):
        origen = app.shopify_products_to_matrixify_df([{
            "Mod-Col": "BM1-A", "Handle": "h", "Title": "Casaca Hombre",
            "Body HTML": "<p>x</p>", "Type": "Casacas", "Vendor": "columbiape",
            "Metafield: custom.color [single_line_text_field]": "AZUL MARINO",
            "Variants": [{"Variant SKU": "S1", "Talla": "M"}],
        }])
        vacio = pd.DataFrame(columns=list(app.MATRIXIFY_COLUMNS))
        salida, _ = app.build_centry_matrixify_from_master(
            ["BM1-A"],
            origen,
            pd.DataFrame([{"Mod-Col": "BM1-A", "COD MOD COL": "BM1-A",
                           "CODINT_MA": "S1", "TALNUM_MA": "M",
                           "MARCA_MA": "COLUMBIA", "Precio": "1", "CodBarras": "7"}]),
            {"label": "Columbia", "site_key": "rockford",
             "allowed_arti_brands": ["COLUMBIA"]},
            destino_matrixify_df=vacio)
        self.assertEqual(app.clean_value(salida["Option2 Value"].iloc[0]), "AZUL MARINO")
        self.assertIn("azul-marino", salida["Handle"].iloc[0])


class TestNoSePierdeInformacion(unittest.TestCase):
    def test_los_SKU_y_las_tallas_salen_intactos(self):
        salida, _ = generar(["BM4077-P12"])
        self.assertEqual(sorted(salida["Variant SKU"]),
                         sorted(["SKUBM4077-P12-0", "SKUBM4077-P12-1", "SKUBM4077-P12-2"]))
        self.assertEqual(sorted(salida["Option1 Value"]), ["L", "M", "S"])

    def test_el_codigo_modelo_color_sale_intacto(self):
        salida, _ = generar(["BM4077-P12"])
        self.assertEqual(set(salida[CLAVE]), {"BM4077-P12"})


if __name__ == "__main__":
    unittest.main(verbosity=2)
