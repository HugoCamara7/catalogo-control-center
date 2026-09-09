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
        # Media talla mas arriba que en la guia de Vans: la mujer de Columbia
        # calza 0,5 cm mas en el mismo numero US, y desde septiembre de 2026
        # Columbia tiene su propia tabla (`TABLA_COLUMBIA`).
        self.assertEqual(self._matrixify(), ["35", "36.5", "39"])

    def test_con_el_metacampo_manda_el_metacampo(self):
        """El DATO gana al texto: un titulo que diga "Mujer" no puede pisar un
        `custom.genero` que diga Masculino."""
        self.assertEqual(self._matrixify("Masculino"), ["36.5", "38", "40.5"])


class TestLaGuiaPorDefecto(unittest.TestCase):
    def test_sorel_se_convierte_aunque_no_tenga_guia_propia(self):
        # El ejemplo era Columbia hasta que Columbia tuvo la suya.
        self.assertIsNone(gt.guia_para("SOREL", gt.CALZADO))
        self.assertEqual(
            gt.convertir("8", "SOREL", gt.CALZADO, "Femenino"), ("38.5", gt.POR_DEFECTO))

    def test_y_la_carga_lo_deja_por_escrito(self):
        avisos = []
        g.display_size_for_site("8", SUPERMALL, gender="Femenino",
                                product_type="Zapatilla", marca="SOREL", avisos=avisos)
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
            [app.clean_value(v) for v in self.sial["Talla Web "]], ["35", "36.5", "39"])

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
            [app.clean_value(v) for v in centry["Talla Web "]], ["35", "36.5", "39"])


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

class TestSupermallEsUnaWEBnoUnaMARCA(unittest.TestCase):
    """Todo el calzado de Supermall.pe tiene que verse en la misma escala.

    Pedido del usuario en septiembre de 2026: *"la guia de tallas de vans
    cambiala en todo supermall porque supermall es una web no una marca
    entonces tiene que verse igual la talla de todos los calzados"*.

    La guia por defecto ya cubria las marcas sin guia propia, pero quedaba un
    hueco: el calzado **UNISEX**. `escala_de_genero("Unisex")` devuelve "" --
    igual que un producto sin genero -- y el conversor lo trataba como "no se
    sabe", asi que unas zapatillas unisex se publicaban en `8, 9, 10` justo al
    lado de otras en `40.5, 42, 43`.
    """

    def _publicadas(self, marca, genero, curva):
        return [
            g.display_size_for_site(
                valor, SUPERMALL, gender=genero, product_type="Zapatillas",
                marca=marca, curva=curva, valor_crudo=valor,
            )
            for valor in curva
        ]

    def test_el_calzado_unisex_TAMBIEN_sale_en_PE(self):
        self.assertEqual(
            self._publicadas("COLUMBIA", "Unisex", ["70", "80", "90"]),
            ["39", "40.5", "42"],
        )

    def test_todas_las_marcas_de_supermall_publican_en_la_misma_escala(self):
        """La misma curva US, en cualquier marca, da la misma talla PE.

        Es la pregunta del usuario: Supermall es una web, no una marca. Con una
        marca sin convertir, el filtro de talla de la tienda no sirve.
        """
        esperado = ["39", "40.5", "42"]
        for marca in ("VANS", "COLUMBIA", "HUSH PUPPIES", "SOREL", "KEDS", "ROCKFORD"):
            for genero in ("Masculino", "Unisex"):
                with self.subTest(marca=marca, genero=genero):
                    self.assertEqual(
                        self._publicadas(marca, genero, ["70", "80", "90"]), esperado)

    def test_una_curva_que_ya_viene_en_PE_no_se_toca(self):
        self.assertEqual(
            self._publicadas("HUSH PUPPIES", "Unisex", ["390", "400", "410"]),
            ["39", "40", "41"],
        )

    def test_la_conversion_unisex_QUEDA_por_escrito(self):
        """Convertida no es lo mismo que convertida sin salvedades: la escala
        unisex es una decision de la guia y tiene que poder leerse."""
        _convertida, nota = gt.convertir("8", "SOREL", gt.CALZADO, "Unisex")
        self.assertEqual(nota, gt.POR_DEFECTO_UNISEX)
        problema = g.avisos_de_talla_a_issues(
            [{"Talla": "8", "Marca": "SOREL", "Motivo": nota}])[0]["Problema"]
        self.assertIn("unisex", problema)
        self.assertIn("convirtieron a PE", problema)

    def test_las_dos_salvedades_se_leen_las_dos(self):
        """Marca sin guia propia Y producto unisex. Pisar una con la otra deja
        la mitad del informe sin escribir."""
        _c, nota = gt.convertir("8", "SOREL", gt.CALZADO, "Unisex")
        problema = g.avisos_de_talla_a_issues(
            [{"Talla": "8", "Marca": "SOREL", "Motivo": nota}])[0]["Problema"]
        self.assertIn("unisex", problema)
        self.assertIn("guia de Vans", problema)

    def test_una_marca_CON_guia_propia_avisa_solo_del_unisex(self):
        _c, nota = gt.convertir("8", "VANS", gt.CALZADO, "Unisex")
        self.assertEqual(nota, gt.UNISEX)

    def test_sin_genero_NINGUNO_se_sigue_sin_convertir(self):
        """Unisex es un DATO; no saber el genero es otra cosa.

        Un US 8 de hombre es PE 40.5 y uno de mujer 38.5: adivinar publica una
        talla inventada como si fuera cierta. Se deja en origen y se reporta.
        """
        convertida, nota = gt.convertir("8", "COLUMBIA", gt.CALZADO, "")
        self.assertEqual((convertida, nota), ("8", gt.SIN_GENERO))

    def test_el_calzado_de_NINO_tambien_sale_en_PE(self):
        """`1Y` y `1` son la misma talla, y el maestro escribe la segunda.

        Medido en el catalogo real de Columbia.pe: TODAS las botas y
        zapatillas de nino traen la curva `10, 20, 30, 40, 45` -- o sea `1, 2,
        3, 4, 4.5` --, y esos numeros no estaban en ninguna columna de la guia,
        asi que el producto entero se quedaba sin convertir y salia en `1, 2,
        3, 4` al lado de las de adulto en `39, 40, 41`.
        """
        self.assertEqual(
            self._publicadas("COLUMBIA", "Niños", ["10", "20", "30", "40", "45"]),
            ["31.5", "32.5", "34", "35", "36"],
        )

    def test_pero_un_10_punto_5_de_ADULTO_no_es_una_talla_de_bebe(self):
        """Las de bebe (`10.5C`...`13.5C`) NO se alian: esos numeros existen en
        la columna de adulto. Un `10.5` de hombre es PE 44, no el PE 27 de un
        `10.5C`."""
        from engines import tallas_calzado as tc
        self.assertIsNone(tc.POR_ESCALA[tc.NINO].get("10.5"))
        self.assertEqual(gt.convertir("10.5", "VANS", gt.CALZADO, "Masculino")[0], "44")
        self.assertEqual(gt.convertir("10.5C", "VANS", gt.CALZADO, "")[0], "27")

    def test_el_aviso_de_AMBIGUA_no_dice_que_no_se_convirtio(self):
        """Se convierten -- con la otra escala de la guia -- y el aviso decia
        "se publican SIN convertir a PE". Medido: 7 tallas de una carga real de
        Columbia. Es el mismo fallo que ya se corrigio con la nota de lectura.
        """
        convertida, nota = gt.convertir("8", "VANS", gt.CALZADO, "Ninos")
        self.assertEqual(nota, "ambigua")
        self.assertNotEqual(convertida, "8", "la talla SI se convirtio")
        problema = g.avisos_de_talla_a_issues(
            [{"Talla": "8", "Marca": "VANS", "Motivo": nota}])[0]["Problema"]
        self.assertIn("convirtieron a PE", problema)
        self.assertNotIn("SIN convertir", problema)

    def test_un_sitio_que_publica_en_ORIGEN_no_convierte_el_unisex(self):
        columbia = app.SITE_CONFIGS["columbia"]
        self.assertEqual(
            g.display_size_for_site("80", columbia, gender="Unisex",
                                    product_type="Zapatillas", marca="COLUMBIA",
                                    curva=["70", "80"], valor_crudo="80"),
            "8",
        )


class TestUnaSolaPreguntaPorElGENERO(unittest.TestCase):
    """La carga completa y la carga por codigos preguntaban distinto.

    La completa usaba `product_gender` -- solo el dato declarado -- y la de
    codigos `centry_gender`, que ademas lee el titulo. La misma bota se
    convertia a PE por un camino y se quedaba en US por el otro: es la trampa
    de las dos `normalize_size`.
    """

    def test_la_cascada_esta_escrita_UNA_vez(self):
        """`centry_gender` DELEGA; no vuelve a escribir la cascada."""
        import inspect
        cuerpo = inspect.getsource(app.centry_gender)
        self.assertIn("genero_de_producto(row)", cuerpo)
        for palabra in ("unisex", "femenino", "masculino"):
            self.assertNotIn(palabra, cuerpo.split('"""')[-1].lower(),
                             "la cascada esta escrita otra vez en centry_gender")

    def test_la_carga_completa_pregunta_por_la_cascada_COMPLETA(self):
        import inspect
        cuerpo = inspect.getsource(g.build_columbia_matrixify)
        self.assertIn("gender=genero_de_producto(product)", cuerpo)
        self.assertNotIn("gender=product_gender(product)", cuerpo)

    def test_el_titulo_resuelve_el_genero_en_las_DOS(self):
        ficha = {"Title": "Bota Para Mujer Waterproof", "Type": "Botas"}
        self.assertEqual(g.genero_de_producto(ficha), "Femenino")
        self.assertEqual(app.centry_gender(ficha), "Femenino")

    def test_pero_la_hoja_Sial_conserva_el_valor_DECLARADO(self):
        """`product_gender` no se toca: el almacen espera el valor del maestro,
        no el normalizado. Un titulo no puede inventarle un genero a la hoja."""
        self.assertEqual(g.product_gender({"Genero": "MUJER"}), "MUJER")
        self.assertEqual(g.product_gender({"Title": "Bota Para Mujer"}), "")

    def test_el_DATO_sigue_mandando_sobre_el_texto(self):
        self.assertEqual(
            g.genero_de_producto({"Genero": "Masculino", "Title": "Bota Para Mujer"}),
            "Masculino",
        )

    def test_un_NoDisponible_del_maestro_no_es_un_genero(self):
        self.assertEqual(g.genero_de_producto({"Genero": "#N/D", "Title": "Zapatilla"}), "")


class TestNoExisteUnaTalla2Punto1(unittest.TestCase):
    """Reportado por el usuario: *"vi que habian tallas que decian 2.1 eso no
    tiene sentido"*.

    `interpretar_curva` elegia el divisor solo por el RANGO numerico, asi que
    una curva `42, 44, 46, 48, 50, 52` -- que no es de calzado: son tallas de
    vestuario -- entraba en el rango del US al dividirla entre diez y se
    publicaba `4.2, 4.4, 4.6, 4.8, 5, 5.2`.

    Medido sobre el maestro real (653.431 filas): **18 modelo-color** lo
    hacian, 16 de Rockford y 2 de Columbia.
    """

    def _leer(self, curva, genero=""):
        from engines.tallas_calzado import interpretar_curva
        divisor, escala, _nota = interpretar_curva(curva, genero)
        return divisor, escala, [g._dividir_talla(v, divisor) for v in curva]

    def test_la_curva_real_de_Rockford_ya_no_se_divide(self):
        divisor, escala, salida = self._leer(["42", "44", "46", "48", "50", "52"])
        self.assertEqual((divisor, escala), (1, ""))
        self.assertEqual(salida, ["42", "44", "46", "48", "50", "52"])

    def test_la_curva_real_de_Columbia_tampoco(self):
        _d, _e, salida = self._leer(["12", "36", "38", "40", "42"])
        self.assertEqual(salida, ["12", "36", "38", "40", "42"])

    def test_ninguna_division_puede_dejar_un_decimal_que_no_sea_medio(self):
        """Las escalas de calzado van de media en media. Un `2.1` no es una
        talla: es la prueba de que el divisor no era el bueno."""
        for curva in (["21", "22", "23"], ["210", "220", "230"], ["25", "26", "27"],
                      ["11", "13", "17"], ["42", "44", "46"]):
            with self.subTest(curva=curva):
                _d, _e, salida = self._leer(curva)
                for talla in salida:
                    if "." in talla:
                        self.assertTrue(talla.endswith(".5"), f"{curva} -> {salida}")

    def test_y_las_curvas_de_verdad_se_siguen_leyendo_IGUAL(self):
        """La guarda no puede costar ninguna lectura buena: son las mismas
        curvas que el maestro trae hoy."""
        esperado = {
            ("50", "55", "60", "65", "70"): ["5", "5.5", "6", "6.5", "7"],
            ("390", "400", "410"): ["39", "40", "41"],
            ("800", "850"): ["8", "8.5"],
            ("085", "090"): ["8.5", "9"],
            ("040", "050", "060", "070"): ["4", "5", "6", "7"],
            ("10", "20", "30", "40", "45"): ["1", "2", "3", "4", "4.5"],
            ("70", "75", "80", "85", "90", "100"): ["7", "7.5", "8", "8.5", "9", "10"],
        }
        for curva, salida in esperado.items():
            with self.subTest(curva=curva):
                self.assertEqual(self._leer(list(curva))[2], salida)

    def test_la_lectura_DIRECTA_no_se_toca(self):
        """La directa no transforma nada -- lo que trae el maestro sale tal
        cual --, asi que ahi no hay nada que comprobar. Solo dividir inventa un
        numero."""
        from engines.tallas_calzado import interpretar_curva
        self.assertEqual(interpretar_curva(["38.5", "39", "40"], "")[:2], (1, "PE"))


if __name__ == "__main__":
    unittest.main(verbosity=2)
