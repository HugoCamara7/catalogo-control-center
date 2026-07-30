"""Pruebas del motor engines/normalize.py

Son pruebas de CARACTERIZACION: fijan el comportamiento actual tal como esta hoy
en produccion, para que cualquier cambio futuro que lo altere falle de inmediato.

Incluye el caso de las DOS normalizaciones de talla que conviven en el repo
(engines.normalize.normalize_size y generate_columbia_matrixify.normalize_size).
Ese test documenta la divergencia a proposito: NO se debe "arreglar" haciendo
que ambas coincidan sin antes decidir cual es la correcta para cada flujo.

Ejecutar:  python scripts/test_engines_normalize.py
"""
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import pandas as pd

from engines.normalize import (
    SIZE_ORDER,
    clean_value,
    coalesce_duplicate_columns,
    expected_catalog_vendors,
    first_existing_column,
    first_row_value,
    format_datetime_lima,
    looks_like_mod_col,
    normalize_header,
    normalize_size,
    parse_iso_datetime,
    parse_publication_date,
    product_lookup_candidates,
    product_lookup_key,
    repair_mojibake_text,
    safe_float_value,
    safe_int_value,
    size_sort_key,
    slugify,
    variant_mod_col_candidates,
)


class TestMotorNoImportaStreamlit(unittest.TestCase):
    """La regla de arquitectura: los motores no dependen de Streamlit."""

    def test_normalize_no_importa_streamlit(self):
        fuente = (ROOT / "engines" / "normalize.py").read_text(encoding="utf-8")
        self.assertNotIn("import streamlit", fuente)
        self.assertNotIn("st.", fuente)

    def test_se_puede_importar_sin_streamlit_instalado(self):
        # el modulo ya esta importado arriba; si dependiera de st habria fallado
        import engines.normalize as motor

        self.assertFalse(hasattr(motor, "st"))


class TestCleanValue(unittest.TestCase):
    def test_recorta_espacios(self):
        self.assertEqual(clean_value("  hola  "), "hola")

    def test_none_y_vacios(self):
        self.assertEqual(clean_value(None), "")
        self.assertEqual(clean_value(""), "")
        self.assertEqual(clean_value(float("nan")), "")

    def test_numeros(self):
        self.assertEqual(clean_value(5), "5")
        self.assertEqual(clean_value(5.0), "5")

    def test_no_altera_texto_normal(self):
        self.assertEqual(clean_value("Columbia"), "Columbia")


class TestNormalizeHeader(unittest.TestCase):
    def test_minusculas_y_quita_separadores(self):
        # comportamiento actual: baja a minusculas y elimina guiones/espacios
        self.assertEqual(normalize_header("  Mod-Col  "), "modcol")
        self.assertEqual(normalize_header("TALLA"), "talla")
        self.assertEqual(normalize_header("COD MOD COL"), normalize_header("codmodcol"))

    def test_none(self):
        self.assertEqual(normalize_header(None), "")


class TestFirstExistingColumn(unittest.TestCase):
    def test_encuentra_la_primera(self):
        df = pd.DataFrame(columns=["A", "Mod-Col", "C"])
        self.assertEqual(first_existing_column(df, ["Mod-Col", "A"]), "Mod-Col")

    def test_sin_coincidencia(self):
        df = pd.DataFrame(columns=["X"])
        self.assertIsNone(first_existing_column(df, ["Y", "Z"]))


class TestSafeNumeros(unittest.TestCase):
    def test_float(self):
        self.assertEqual(safe_float_value("12.5"), 12.5)
        self.assertEqual(safe_float_value("abc"), 0.0)
        self.assertEqual(safe_float_value("abc", 9.9), 9.9)

    def test_int(self):
        self.assertEqual(safe_int_value("12"), 12)
        self.assertEqual(safe_int_value("abc"), 0)


class TestModCol(unittest.TestCase):
    def test_looks_like_mod_col(self):
        self.assertTrue(looks_like_mod_col("1234567-890"))
        self.assertFalse(looks_like_mod_col(""))

    def test_lookup_key_normaliza(self):
        self.assertEqual(product_lookup_key("  ab-12 "), product_lookup_key("AB-12"))

    def test_candidates_devuelve_lista(self):
        self.assertIsInstance(product_lookup_candidates("AB-12"), list)

    def test_variant_candidates_devuelve_lista(self):
        self.assertIsInstance(variant_mod_col_candidates({"Mod-Col": "AB-12"}), list)


class TestNormalizeSize(unittest.TestCase):
    """Comportamiento EXACTO de la normalizacion de tallas del motor."""

    def test_alfabeticas(self):
        self.assertEqual(normalize_size("M"), "M")
        self.assertEqual(normalize_size("  L  "), "L")
        self.assertEqual(normalize_size("SMALL"), "S")
        self.assertEqual(normalize_size("EXTRA LARGE"), "XL")
        self.assertEqual(normalize_size("3 EXTRA LARGE"), "XXXL")

    def test_talla_unica(self):
        self.assertEqual(normalize_size("UNICA"), "O/S")
        self.assertEqual(normalize_size("OS"), "O/S")
        self.assertEqual(normalize_size("O/S"), "O/S")

    def test_quita_prefijo_talla(self):
        self.assertEqual(normalize_size("TALLA M"), "M")

    def test_nulos(self):
        for v in ["N/A", "NAN", "SIN TALLA", "#N/D", ""]:
            self.assertEqual(normalize_size(v), "", f"fallo con {v!r}")

    def test_numericas_NO_se_dividen_entre_10(self):
        """El motor NO convierte 85 -> 8.5. Esta es la semantica actual."""
        self.assertEqual(normalize_size("85"), "85")
        self.assertEqual(normalize_size("400"), "400")
        self.assertEqual(normalize_size("245"), "245")
        self.assertEqual(normalize_size("38.0"), "38.0")


class TestDivergenciaDeTallas(unittest.TestCase):
    """DOCUMENTA a proposito la divergencia entre las dos normalizaciones.

    NO unificar sin decidir antes cual aplica a cada flujo:
      - engines.normalize.normalize_size          -> deja la talla cruda (85)
      - generate_columbia_matrixify.normalize_size -> convierte a calzado (8.5)

    El dato real de ARTI (TALNUM_MA) viene en formato x10: '85', '400', '245'.
    """

    CASOS = {
        "85": ("85", "8.5"),
        "90": ("90", "9"),
        "400": ("400", "40"),
        "245": ("245", "24.5"),
        "38.0": ("38.0", "38"),
    }

    def test_divergencia_sigue_presente(self):
        from generate_columbia_matrixify import normalize_size as maestro

        for entrada, (esperado_motor, esperado_maestro) in self.CASOS.items():
            self.assertEqual(
                normalize_size(entrada), esperado_motor,
                f"cambio la semantica del MOTOR para {entrada!r}",
            )
            self.assertEqual(
                maestro(entrada), esperado_maestro,
                f"cambio la semantica del MAESTRO para {entrada!r}",
            )
            self.assertNotEqual(
                normalize_size(entrada), maestro(entrada),
                f"las dos normalizaciones se unificaron para {entrada!r}: "
                "revisa que sea intencional y que ambos flujos sigan correctos",
            )

    def test_coinciden_en_tallas_alfabeticas(self):
        from generate_columbia_matrixify import normalize_size as maestro

        for v in ["M", "L", "XL", "XS", "UNICA", "OS"]:
            self.assertEqual(normalize_size(v), maestro(v), f"divergen en {v!r}")


class TestSizeSortKey(unittest.TestCase):
    def test_orden_alfabetico(self):
        self.assertEqual(
            sorted(["XL", "S", "M", "XXL", "XS", "L"], key=size_sort_key),
            ["XS", "S", "M", "L", "XL", "XXL"],
        )

    def test_orden_numerico(self):
        self.assertEqual(
            sorted(["100", "85", "95", "110", "90"], key=size_sort_key),
            ["85", "90", "95", "100", "110"],
        )

    def test_size_order_tiene_las_basicas(self):
        for t in ["XS", "S", "M", "L", "XL"]:
            self.assertIn(t, SIZE_ORDER)


class TestSlugify(unittest.TestCase):
    def test_basico(self):
        self.assertEqual(slugify("Camisa Azul"), "camisa-azul")

    def test_acentos(self):
        self.assertNotIn("ñ", slugify("Niño"))
        self.assertNotIn("á", slugify("Pantalón"))

    def test_vacio_usa_fallback(self):
        # comportamiento actual: cadena vacia -> "producto"
        self.assertEqual(slugify(""), "producto")


class TestMojibake(unittest.TestCase):
    def test_repara_texto_doble_codificado(self):
        self.assertEqual(repair_mojibake_text("AlgodÃ³n"), "Algodón")

    def test_no_rompe_texto_correcto(self):
        self.assertEqual(repair_mojibake_text("Algodón"), "Algodón")
        self.assertEqual(repair_mojibake_text("Columbia"), "Columbia")


class TestFechas(unittest.TestCase):
    def test_parse_iso(self):
        self.assertIsNotNone(parse_iso_datetime("2026-07-30T10:00:00"))
        self.assertIsNone(parse_iso_datetime("no es fecha"))

    def test_format_lima_no_revienta(self):
        self.assertIsInstance(format_datetime_lima("2026-07-30T10:00:00"), str)
        self.assertIsInstance(format_datetime_lima(""), str)

    def test_parse_publication_date_acepta_vacio(self):
        parse_publication_date("")


class TestCoalesceDuplicateColumns(unittest.TestCase):
    def test_sin_duplicados_no_cambia_columnas(self):
        df = pd.DataFrame({"A": [1, 2], "B": [3, 4]})
        self.assertEqual(list(coalesce_duplicate_columns(df).columns), ["A", "B"])

    def test_fusiona_duplicadas(self):
        df = pd.DataFrame([[1, None], [None, 4]], columns=["A", "A"])
        salida = coalesce_duplicate_columns(df)
        self.assertEqual(list(salida.columns).count("A"), 1)


class TestVarios(unittest.TestCase):
    def test_expected_catalog_vendors_devuelve_iterable(self):
        self.assertIsNotNone(expected_catalog_vendors({"vendor": "Columbia"}))

    def test_first_row_value(self):
        fila = pd.Series({"A": "", "B": "valor"})
        self.assertEqual(first_row_value(fila, ["A", "B"]), "valor")


if __name__ == "__main__":
    unittest.main(verbosity=2)
