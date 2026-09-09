"""El calzado no salia en tallas PE, y la hoja Sial decia otra talla que la
tienda (septiembre 2026).

Reportado con una captura de la hoja Carga Sial: *"las tallas no se estan
generando por las guias de tallas que te pase de Vans"*. Reproducido contra el
maestro real con la bota `1424692-2KQ` de Columbia antes de tocar nada. Eran
CUATRO cosas distintas y ninguna era la que parecia:

1. **La curva se interpretaba con el `0` y las internas `K` dentro.** El
   maestro trae, junto a las tallas, un `0` de cabecera y codigos tipo `K901`.
   Los dos se borran mas adelante, pero votaban sobre la escala:

       0, 50, 55, ..., 100, K901  ->  "no cabe en ninguna escala conocida"
       50, 55, ..., 100           ->  entre diez: la curva esta en US

   Con la curva sin interpretar, **el producto entero se quedaba sin convertir**.

2. **El conversor se quedaba sin genero.** Un US 8 de hombre es PE 40.5 y uno
   de mujer 38.5, asi que sin genero no se convierte. La hoja Sial resuelve el
   genero con una cascada (el dato y, si falta, el texto de la ficha) y el
   conversor solo miraba el dato: una "Bota Para Mujer Waterproof" sin el
   metacampo puesto se publicaba en US, con la palabra "Mujer" en el titulo.

3. **Sin guia propia no se convertia.** Decision del usuario en septiembre de
   2026: la guia de Vans -- la unica confirmada -- pasa a ser la guia POR
   DEFECTO del calzado. Se reporta marca por marca.

4. **`Talla Web ` salia del codigo del maestro, no de la talla publicada.** Con
   el calzado convertido, la hoja del almacen decia `5` y la tienda `34.5` para
   el MISMO SKU.

Ejecutar:  python scripts/test_tallas_de_calzado_en_supermall.py
"""
import sys
import unittest
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import app_matrixify as app  # noqa: E402
import generate_columbia_matrixify as g  # noqa: E402
from engines import guias_tallas as gt  # noqa: E402

SUPERMALL = app.SITE_CONFIGS["supermall"]
# La curva de la bota real que reporto el usuario, tal y como viene del maestro.
CURVA_BOTA = ["0", "50", "55", "60", "65", "70", "75", "80", "85", "90", "100", "K901"]


def catalogo(codigo, titulo, tipo, genero=""):
    return app.shopify_products_to_matrixify_df([{
        "Mod-Col": codigo, "Handle": codigo.lower(), "Product ID": "gid://1",
        "Title": titulo, "Body HTML": "<p>Ficha.</p>", "Type": tipo,
        "Tags": "Columbia", "Image Src": "https://img/a.jpg", "Vendor": "columbiape",
        "Marca": "Columbia", "Status": "ACTIVE", "Published Online Store": "SI",
        "Metafield: custom.genero [single_line_text_field]": genero,
        "Variants": [],
    }])


def maestro(codigo, tallas):
    return pd.DataFrame([{
        "Mod-Col": codigo, "COD MOD COL": codigo,
        "CODINT_MA": f"{codigo}-{i}", "TALNUM_MA": str(talla),
        "MARCA_MA": "COLUMBIA", "Precio": "199.90", "CodBarras": f"77{i}",
    } for i, talla in enumerate(tallas)])


class TestLaCurvaSoloLaVotanLasTallas(unittest.TestCase):
    def test_el_cero_y_las_internas_K_salen_de_la_curva(self):
        self.assertEqual(
            g.curva_de_tallas_reales(CURVA_BOTA),
            ["50", "55", "60", "65", "70", "75", "80", "85", "90", "100"],
        )

    def test_con_ellas_dentro_la_curva_NO_se_podia_leer(self):
        """Es el fallo: `interpretar_curva` contestaba que no cabia."""
        from engines.tallas_calzado import interpretar_curva
        _divisor, escala, _nota = interpretar_curva(CURVA_BOTA, "Femenino")
        self.assertEqual(escala, "", "el motor ya no deberia poder leer esta curva")

    def test_y_ahora_se_lee_como_US(self):
        divisor, escala, _nota = g._interpretar_curva_de_calzado(CURVA_BOTA, "Femenino")
        self.assertEqual((divisor, escala), (10, "US"))

    def test_una_curva_ya_en_PE_se_sigue_leyendo_como_PE(self):
        _d, escala, _n = g._interpretar_curva_de_calzado(["0", "390", "400", "410"], "")
        self.assertEqual(escala, "PE")


class TestElGeneroSaleDeLaFichaSiNoEstaElDato(unittest.TestCase):
    """Sin genero no hay conversion, y el genero estaba en el titulo."""

    def _matrixify(self, genero=""):
        codigo = "1424692-2KQ"
        mx, _rev = app.build_centry_matrixify_from_master(
            [codigo], catalogo(codigo, "Bota Para Mujer Waterproof", "Botas", genero),
            maestro(codigo, ["50", "60", "80"]), SUPERMALL,
            destino_matrixify_df=pd.DataFrame(),
        )
        return [app.clean_value(v) for v in mx["Option1 Value"]]

    def test_sin_el_metacampo_el_titulo_dice_el_genero(self):
        self.assertEqual(self._matrixify(), ["34.5", "36", "38.5"])

    def test_con_el_metacampo_manda_el_metacampo(self):
        """El DATO gana al texto: un titulo que diga "Mujer" no puede pisar un
        `custom.genero` que diga Masculino."""
        self.assertEqual(self._matrixify("Masculino"), ["36.5", "38", "40.5"])


class TestLaGuiaPorDefecto(unittest.TestCase):
    def test_columbia_se_convierte_aunque_no_tenga_guia_propia(self):
        self.assertIsNone(gt.guia_para("COLUMBIA", gt.CALZADO))
        self.assertEqual(
            gt.convertir("8", "COLUMBIA", gt.CALZADO, "Femenino"), ("38.5", gt.POR_DEFECTO))

    def test_y_la_carga_lo_deja_por_escrito(self):
        avisos = []
        g.display_size_for_site("8", SUPERMALL, gender="Femenino",
                                product_type="Zapatilla", marca="COLUMBIA", avisos=avisos)
        filas = g.avisos_de_talla_a_issues(avisos)
        self.assertEqual(len(filas), 1)
        texto = filas[0]["Problema"]
        self.assertIn("se convirtieron a PE", texto)
        self.assertIn("guia de Vans", texto)
        self.assertNotIn("SIN convertir", texto)

    def test_la_nota_de_LECTURA_no_dice_que_no_se_convirtio(self):
        """Decia "se publican SIN convertir a PE porque numeros leidos entre
        10" sobre tallas que SI se convirtieron: manda a buscar un problema que
        no existe."""
        avisos = []
        g.display_size_for_site("50", SUPERMALL, gender="Femenino",
                                product_type="Zapatilla", marca="VANS",
                                avisos=avisos, curva=CURVA_BOTA, valor_crudo="50")
        textos = [f["Problema"] for f in g.avisos_de_talla_a_issues(avisos)]
        self.assertTrue(any("se leyeron asi" in t for t in textos), textos)
        self.assertFalse(any("SIN convertir" in t for t in textos), textos)

    def test_el_cero_y_las_internas_K_no_generan_aviso_de_conversion(self):
        for valor in ("0", "K901"):
            avisos = []
            salida = g.display_size_for_site(
                valor, SUPERMALL, gender="Femenino", product_type="Zapatilla",
                marca="COLUMBIA", avisos=avisos)
            self.assertEqual(avisos, [], valor)
            self.assertEqual(salida, g.normalize_size(valor), valor)


class TestLaHojaSialDiceLaMismaTallaQueLaTienda(unittest.TestCase):
    def setUp(self):
        codigo = "1424692-2KQ"
        self.mx, _rev = app.build_centry_matrixify_from_master(
            [codigo], catalogo(codigo, "Bota Para Mujer Waterproof", "Botas"),
            maestro(codigo, ["50", "60", "80"]), SUPERMALL,
            destino_matrixify_df=pd.DataFrame(),
        )
        self.sial = app.build_sial_de_sitio_from_matrixify(self.mx, SUPERMALL)

    def test_talla_web_es_la_talla_PUBLICADA(self):
        self.assertEqual(
            [app.clean_value(v) for v in self.sial["Talla Web "]], ["34.5", "36", "38.5"])

    def test_y_coincide_con_lo_que_se_escribe_en_shopify(self):
        """Dos lectores del mismo producto no pueden decir tallas distintas."""
        self.assertEqual(
            [app.clean_value(v) for v in self.sial["Talla Web "]],
            [app.clean_value(v) for v in self.mx["Option1 Value"]],
        )

    def test_la_columna_Talla_SIGUE_siendo_el_codigo_del_maestro(self):
        """Es lo que el almacen espera: no se toca."""
        self.assertEqual(
            [app.clean_value(v) for v in self.sial["Talla"]], ["50", "60", "80"])

    def test_la_hoja_de_Centry_tambien_publica_la_talla_convertida(self):
        centry = app.build_centry_sial_from_matrixify(self.mx, SUPERMALL)
        self.assertEqual(
            [app.clean_value(v) for v in centry["Talla Web "]], ["34.5", "36", "38.5"])


class TestLoQueNoCambia(unittest.TestCase):
    def test_el_vestuario_no_se_toca(self):
        codigo = "1275701-5HD"
        mx, _rev = app.build_centry_matrixify_from_master(
            [codigo], catalogo(codigo, "Blusa Manga Larga Mujer Firwood", "Blusas"),
            maestro(codigo, ["XS", "S", "M", "L", "XL"]), SUPERMALL,
            destino_matrixify_df=pd.DataFrame(),
        )
        sial = app.build_sial_de_sitio_from_matrixify(mx, SUPERMALL)
        self.assertEqual([app.clean_value(v) for v in sial["Talla"]],
                         ["XS", "S", "M", "L", "XL"])
        self.assertEqual([app.clean_value(v) for v in sial["Talla Web "]],
                         ["XS", "S", "M", "L", "XL"])

    def test_una_talla_que_ya_venia_en_PE_no_se_mueve(self):
        self.assertEqual(
            g.display_size_for_site("40", SUPERMALL, gender="Masculino",
                                    product_type="Zapatilla", marca="HUSH PUPPIES"),
            "40",
        )

    def test_un_sitio_que_publica_en_ORIGEN_sigue_sin_convertir(self):
        columbia = app.SITE_CONFIGS["columbia"]
        self.assertEqual(
            g.display_size_for_site("8", columbia, gender="Masculino",
                                    product_type="Zapatilla", marca="COLUMBIA"),
            "8",
        )


if __name__ == "__main__":
    unittest.main(verbosity=2)
