# -*- coding: utf-8 -*-
"""Tallas de calzado de Vans: de US a la escala peruana (PE).

Vans entrega el calzado en tallas US y la tienda las publica en PE. La
conversion NO es una formula: es la tabla oficial, con saltos propios (de US
Men 12 se pasa a 13, y PE salta de 46 a 47).

Dos trampas, y las dos estan cubiertas aqui:

1. **El mismo numero US es otra talla segun el genero.** Un 8 de hombre es PE
   40.5; un 8 de mujer es PE 38.5. Dos tallas y media de diferencia.

2. **Solo aplica a calzado.** En vestuario una talla "12" es una talla de nino,
   no un US 12. Convertirla la volveria un PE 46.

Ejecutar:  python scripts/test_tallas_calzado_pe.py
"""
import sys
import types
import unittest
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def _identity_decorator(*args, **kwargs):
    if args and callable(args[0]):
        return args[0]

    def _decorator(func):
        return func

    return _decorator


class _Secrets(dict):
    def get(self, key, default=None):
        return super().get(key, default if default is not None else {})


class _StreamlitStub(types.ModuleType):
    session_state = {}
    secrets = _Secrets()
    cache_data = staticmethod(_identity_decorator)
    cache_resource = staticmethod(_identity_decorator)

    def __getattr__(self, name):
        def _noop(*args, **kwargs):
            return None

        return _noop


if "streamlit" not in sys.modules:
    stub = _StreamlitStub("streamlit")
    comp = types.ModuleType("streamlit.components")
    comp_v1 = types.ModuleType("streamlit.components.v1")
    stub.__path__ = []
    comp.__path__ = []
    comp.v1 = comp_v1
    stub.components = comp
    sys.modules["streamlit"] = stub
    sys.modules["streamlit.components"] = comp
    sys.modules["streamlit.components.v1"] = comp_v1

import app_matrixify as app  # noqa: E402
import generate_columbia_matrixify as g  # noqa: E402
from engines import tallas_calzado as tc  # noqa: E402

VANS = g.get_brand_config("vans")
ROCKFORD = g.get_brand_config("rockford")


class TestLaTablaOficial(unittest.TestCase):
    """Cada fila de la guia, comprobada contra la conversion."""

    def test_todas_las_filas_convierten_a_su_pe(self):
        for us_men, us_women, us_boy, pe, _cm in tc.TABLA_VANS:
            if us_men:
                with self.subTest(escala="hombre", us=us_men):
                    self.assertEqual(tc.talla_pe(us_men, "Masculino")[0], tc.normalizar_talla(pe))
            if us_women:
                with self.subTest(escala="mujer", us=us_women):
                    self.assertEqual(tc.talla_pe(us_women, "Femenino")[0], tc.normalizar_talla(pe))
            if us_boy:
                with self.subTest(escala="nino", us=us_boy):
                    self.assertEqual(tc.talla_pe(us_boy, "Ninos")[0], tc.normalizar_talla(pe))

    def test_la_tabla_tiene_las_34_filas_de_la_guia(self):
        self.assertEqual(len(tc.TABLA_VANS), 34)

    def test_los_extremos(self):
        self.assertEqual(tc.talla_pe("10.5C")[0], "27")     # la mas chica
        self.assertEqual(tc.talla_pe("16", "Masculino")[0], "50")   # la mas grande

    def test_respeta_los_saltos_de_la_guia(self):
        """US Men no tiene 12.5, y PE salta de 46 a 47."""
        self.assertEqual(tc.talla_pe("12", "Masculino")[0], "46")
        self.assertEqual(tc.talla_pe("13", "Masculino")[0], "47")
        self.assertEqual(tc.talla_pe("12.5", "Masculino")[1], "desconocida")


class TestElGeneroCambiaLaTalla(unittest.TestCase):
    def test_el_mismo_numero_es_otra_talla(self):
        self.assertEqual(tc.talla_pe("8", "Masculino")[0], "40.5")
        self.assertEqual(tc.talla_pe("8", "Femenino")[0], "38.5")

    def test_femenino_no_se_confunde_con_men(self):
        """Regresion: "femenino" contiene "men" y con una comparacion por
        subcadena caia en la escala de hombre. Un 8 de mujer salia PE 40.5 en
        vez de 38.5."""
        self.assertEqual(tc.escala_de_genero("Femenino"), tc.MUJER)
        self.assertEqual(tc.escala_de_genero("Masculino"), tc.HOMBRE)
        self.assertEqual(tc.escala_de_genero("Mujer"), tc.MUJER)
        self.assertEqual(tc.escala_de_genero("Niñas"), tc.MUJER)

    def test_unisex_no_tiene_escala_propia(self):
        self.assertEqual(tc.escala_de_genero("Unisex"), "")

    def test_sin_genero_avisa_de_la_ambiguedad(self):
        talla, nota = tc.talla_pe("8")
        self.assertEqual(nota, "ambigua")
        self.assertEqual(talla, "40.5")     # US Men, que es la escala por defecto

    def test_un_numero_de_una_sola_escala_no_es_ambiguo(self):
        """El 16 solo existe en hombre: no hay nada que decidir."""
        self.assertEqual(tc.talla_pe("16"), ("50", ""))

    def test_las_infantiles_nunca_son_ambiguas(self):
        for us, pe in [("10.5C", "27"), ("13C", "30.5"), ("1Y", "31.5"), ("3Y", "34")]:
            with self.subTest(us=us):
                self.assertEqual(tc.talla_pe(us), (pe, ""))


class TestFormatos(unittest.TestCase):
    def test_acepta_coma_y_ceros_de_mas(self):
        self.assertEqual(tc.normalizar_talla("8,5"), "8.5")
        self.assertEqual(tc.normalizar_talla("8.0"), "8")
        self.assertEqual(tc.normalizar_talla(" 10.5c "), "10.5C")
        self.assertEqual(tc.normalizar_talla("38.50"), "38.5")

    def test_una_talla_que_ya_esta_en_pe_no_se_toca(self):
        """Las escalas no se solapan -US llega a 16, PE empieza en 27- asi que
        convertir dos veces es inofensivo."""
        for pe in ("27", "38.5", "43", "50"):
            with self.subTest(pe=pe):
                self.assertTrue(tc.ya_es_pe(pe))
                self.assertEqual(tc.talla_pe(pe, "Masculino"), (pe, ""))

    def test_lo_que_no_esta_en_la_tabla_se_devuelve_igual(self):
        """No se inventa: si no la conoce, la deja como vino y lo dice."""
        self.assertEqual(tc.talla_pe("99", "Masculino"), ("99", "desconocida"))
        self.assertEqual(tc.talla_pe("M", "Masculino"), ("M", "desconocida"))

    def test_vacio_no_revienta(self):
        self.assertEqual(tc.talla_pe(""), ("", ""))
        self.assertEqual(tc.talla_pe(None), ("", ""))

    def test_conversion_desde_centimetros(self):
        self.assertEqual(tc.talla_pe_desde_cm("26"), "40.5")
        self.assertEqual(tc.talla_pe_desde_cm("34"), "50")
        self.assertEqual(tc.talla_pe_desde_cm("99"), "")


class TestElProductoRealDeLaTienda(unittest.TestCase):
    """VN000EJ8FST-532, el que estaba cargado con las tallas en US.

    Su selector mostraba: 5 5.5 6 6.5 7 7.5 8 8.5 9 9.5 10 10.5 11 11.5 12 040
    045. Dos cosas que la primera version no cubria: la escala de hombre por
    debajo de 6.5, y las tallas PE escritas con cero de relleno.
    """

    TALLAS = ["5", "5.5", "6", "6.5", "7", "7.5", "8", "8.5", "9", "9.5",
              "10", "10.5", "11", "11.5", "12", "040", "045"]
    ESPERADO = ["36.5", "37", "38", "38.5", "39", "40", "40.5", "41", "42",
                "42.5", "43", "44", "44.5", "45", "46", "40", "45"]

    def test_todas_las_tallas_del_producto_convierten(self):
        for us, pe in zip(self.TALLAS, self.ESPERADO):
            with self.subTest(us=us):
                self.assertEqual(tc.talla_pe(us, "Masculino")[0], pe)

    def test_ninguna_queda_sin_resolver(self):
        for us in self.TALLAS:
            with self.subTest(us=us):
                self.assertEqual(tc.talla_pe(us, "Masculino")[1], "")

    def test_el_ocho_de_hombre_es_40_y_medio(self):
        """Lo que pidio el usuario, tal cual."""
        self.assertEqual(tc.talla_pe("8", "Masculino")[0], "40.5")


class TestCerosDeRelleno(unittest.TestCase):
    """El catalogo trae tallas PE escritas "040" y "045"."""

    def test_quita_el_cero_de_la_izquierda(self):
        self.assertEqual(tc.normalizar_talla("040"), "40")
        self.assertEqual(tc.normalizar_talla("045"), "45")
        self.assertEqual(tc.normalizar_talla("08.5"), "8.5")

    def test_las_reconoce_como_pe_y_no_las_toca(self):
        self.assertEqual(tc.talla_pe("040", "Masculino"), ("40", ""))
        self.assertEqual(tc.talla_pe("045", "Masculino"), ("45", ""))

    def test_no_convierte_el_cero_en_vacio(self):
        """La talla 0 tiene su propio tratamiento en el motor."""
        self.assertEqual(tc.normalizar_talla("0"), "0")


class TestEscalaDeHombreCompleta(unittest.TestCase):
    """US Men por debajo de 6.5 no venia en la guia pero el catalogo la usa.

    Se deriva del desfase de la propia tabla: en las OCHO filas donde Men y
    Women coinciden, Men es siempre Women menos 1.5.
    """

    def test_el_desfase_es_constante_en_toda_la_tabla(self):
        pares = [(m, w) for m, w, _b, _pe, _cm in tc.TABLA_VANS if m and w]
        self.assertTrue(pares)
        for men, women in pares:
            with self.subTest(men=men):
                self.assertAlmostEqual(float(women) - float(men), 1.5, places=2)

    def test_las_tallas_derivadas(self):
        for men, pe in [("3.5", "34.5"), ("4", "35"), ("4.5", "36"),
                        ("5", "36.5"), ("5.5", "37"), ("6", "38")]:
            with self.subTest(men=men):
                self.assertEqual(tc.talla_pe(men, "Masculino")[0], pe)

    def test_un_cinco_de_hombre_no_es_un_cinco_de_mujer(self):
        """Regresion: el 5 de hombre caia en la columna de mujer y salia PE
        34.5 en vez de 36.5, dos tallas de menos."""
        self.assertEqual(tc.talla_pe("5", "Masculino")[0], "36.5")
        self.assertEqual(tc.talla_pe("5", "Femenino")[0], "34.5")


class TestSoloCalzadoYSoloVans(unittest.TestCase):
    def test_el_calzado_de_vans_sale_en_pe(self):
        self.assertEqual(
            g.display_size_for_site("8", VANS, gender="Masculino", product_type="Zapatillas"),
            "40.5",
        )

    def test_el_vestuario_de_vans_no_se_toca(self):
        """Una talla 12 de nino no es un US 12: convertirla la volveria PE 46."""
        self.assertEqual(
            g.display_size_for_site("12", VANS, gender="Niños", product_type="Poleras"),
            "12",
        )
        self.assertEqual(
            g.display_size_for_site("M", VANS, gender="Masculino", product_type="Poleras"),
            "M",
        )

    def test_sin_tipo_de_prenda_no_se_arriesga(self):
        self.assertEqual(g.display_size_for_site("8", VANS, gender="Masculino"), "8")

    def test_las_demas_marcas_siguen_igual(self):
        self.assertEqual(
            g.display_size_for_site("8", ROCKFORD, gender="Masculino", product_type="Zapatos"),
            "8",
        )

    def test_la_bandera_esta_solo_en_vans(self):
        self.assertTrue(VANS.get("tallas_calzado_pe"))
        for clave in ("columbia", "rockford", "hush_puppies", "patagonia"):
            with self.subTest(sitio=clave):
                self.assertFalse(g.get_brand_config(clave).get("tallas_calzado_pe"))

    def test_rockford_conserva_su_talla_unica(self):
        self.assertEqual(g.display_size_for_site("O/S", ROCKFORD), "Talla Única")

    def test_es_calzado_reconoce_la_clase(self):
        self.assertTrue(g.es_calzado("Zapatillas"))
        self.assertTrue(g.es_calzado("Zapatos"))
        self.assertFalse(g.es_calzado("Poleras"))
        self.assertFalse(g.es_calzado(""))


class TestVansDePuntaAPunta(unittest.TestCase):
    """El Centry de un Vans de calzado sale con las tallas en PE."""

    COD = "VN0A5JMH-BLK"

    def _centry(self, genero, tipo, tallas_us):
        def fila(**valores):
            base = {columna: "" for columna in app.MATRIXIFY_COLUMNS}
            base.update(valores)
            return base

        mx, arti = [], []
        for indice, talla in enumerate(tallas_us):
            sku = str(6000 + indice)
            mx.append(fila(**{
                "Handle": "vans", "Title": f"{tipo} Vans" if indice == 0 else "",
                "Vendor": "Vans" if indice == 0 else "",
                "Type": tipo if indice == 0 else "",
                "Image Src": "https://cdn/f.jpg" if indice == 0 else "",
                "Variant SKU": sku, "Option1 Value": talla, "Variant Price": "299",
                "Metafield: custom.codigo_modelo_color [id]": self.COD if indice == 0 else "",
                "Metafield: custom.genero [single_line_text_field]": genero if indice == 0 else "",
            }))
            arti.append({
                "CODINT_MA": sku, "COD MOD COL": self.COD, "TALNUM_MA": talla,
                "MARCA_MA": "VANS", "CodBarras": f"77987{sku}", "ColorNombre": "Negro",
                "Precio": "299", "Genero": genero, "TipoProducto": tipo,
            })
        return app.build_centry_from_matrixify(
            pd.DataFrame(mx), VANS, arti_df=pd.DataFrame(arti)
        )

    def test_calzado_de_hombre(self):
        centry, _ = self._centry("Masculino", "Zapatillas", ["8", "9", "10"])
        self.assertEqual(list(centry["Talla"]), ["40.5", "42", "43"])

    def test_calzado_de_mujer(self):
        centry, _ = self._centry("Femenino", "Zapatillas", ["8", "9", "10"])
        self.assertEqual(list(centry["Talla"]), ["38.5", "40", "41"])

    def test_calzado_infantil(self):
        centry, _ = self._centry("Niños", "Zapatillas", ["11C", "1Y", "3Y"])
        self.assertEqual(list(centry["Talla"]), ["27.5", "31.5", "34"])

    def test_el_vestuario_de_vans_conserva_su_talla(self):
        centry, _ = self._centry("Masculino", "Poleras", ["S", "M", "L"])
        self.assertEqual(list(centry["Talla"]), ["S", "M", "L"])

    def test_el_producto_de_la_tienda_con_tallas_mezcladas(self):
        """US y PE en el mismo producto: las dos acaban en PE."""
        centry, _ = self._centry("Masculino", "Zapatillas", ["7.5", "8", "040"])
        self.assertEqual(list(centry["Talla"]), ["40", "40.5", "40"])

    def test_avisa_de_las_tallas_repetidas_tras_convertir(self):
        """"7.5" en US y "040" en PE son la misma talla: al converter chocan."""
        _, issues = self._centry("Masculino", "Zapatillas", ["7.5", "040"])
        texto = " ".join(str(v) for v in issues["Problema"])
        self.assertIn("Tallas repetidas tras convertir", texto)

    def test_una_talla_que_ya_venia_en_pe_no_cambia(self):
        centry, _ = self._centry("Masculino", "Zapatillas", ["40.5", "42"])
        self.assertEqual(list(centry["Talla"]), ["40.5", "42"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
