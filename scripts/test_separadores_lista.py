"""Pruebas del separador | en los campos de lista del input comercial.

Origen: un input de Patagonia cargado en Rockford con 8 bullets bien separados
por | fue rechazado porque las frases contenian comas. Las comas son puntuacion
normal dentro de un bullet, no separadores.

Ejecutar:  python scripts/test_separadores_lista.py
"""
import sys
import types
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def _identity(*a, **k):
    if a and callable(a[0]):
        return a[0]
    return lambda f: f


class _Stub(types.ModuleType):
    session_state = {}
    secrets = {}
    cache_data = staticmethod(_identity)
    cache_resource = staticmethod(_identity)

    def __getattr__(self, name):
        return lambda *a, **k: None


if "streamlit" not in sys.modules:
    s = _Stub("streamlit")
    c = types.ModuleType("streamlit.components")
    v = types.ModuleType("streamlit.components.v1")
    s.__path__ = []
    c.__path__ = []
    c.v1 = v
    s.components = c
    sys.modules["streamlit"] = s
    sys.modules["streamlit.components"] = c
    sys.modules["streamlit.components.v1"] = v

from app_matrixify import (  # noqa: E402
    COMMERCIAL_INPUT_TEXT_LIST_COLUMNS,
    revisar_separadores_lista,
)

# El valor exacto que fue rechazado en produccion.
CASO_REAL = (
    "El tejido principal está hecho de 100 % algodón Regenerative Organic "
    "Certified™, el estándar más alto del algodón orgánico"
    "|Polar Snap-T de corte recto, con un largo a la altura de la cadera y un "
    "diseño tipo blusón"
    "|La tapeta con tres botones a presión facilita la ventilación, y el cuello "
    "alzado es suave y cálido al contacto con la piel"
    "|Puños y bajo elásticos que mantienen el calor corporal y evitan que el "
    "tejido estorbe"
    "|Cuenta con un bolsillo en el pecho con cierre de botón a presión y dos "
    "bolsillos calientamanos laterales que protegen tus pertenencias y las "
    "mantienen siempre a mano"
    "|Producto confeccionado en una fábrica que cuenta con Certificación Fair "
    "Trade™, lo que significa que las personas que hicieron este producto "
    "recibieron una remuneración justa por su trabajo"
    "|Peso: 493 G (17.4 oz)"
    "|País de origen: Hecho en Perú"
)


class TestCasoReportado(unittest.TestCase):
    def test_el_caso_de_patagonia_ya_no_se_rechaza(self):
        self.assertEqual(revisar_separadores_lista(CASO_REAL), "")

    def test_ese_valor_tiene_8_bullets_y_4_comas(self):
        """Deja constancia de por que fallaba: comas dentro de las frases."""
        self.assertEqual(len(CASO_REAL.split("|")), 8)
        self.assertGreater(CASO_REAL.count(","), 0)


class TestValoresCorrectos(unittest.TestCase):
    """Con | presente, el formato es correcto pase lo que pase dentro."""

    def test_lista_simple(self):
        self.assertEqual(revisar_separadores_lista("Impermeable|Transpirable"), "")

    def test_con_comas_dentro_de_los_bullets(self):
        self.assertEqual(
            revisar_separadores_lista("Cuello alzado, suave|Puños elásticos, cálidos"), "")

    def test_con_punto_y_coma_dentro_de_un_bullet(self):
        self.assertEqual(revisar_separadores_lista("Lavar en frío; no usar lejía|Secar a la sombra"), "")

    def test_con_dos_puntos_y_parentesis(self):
        self.assertEqual(revisar_separadores_lista("Peso: 493 G (17.4 oz)|País de origen: Perú"), "")

    def test_un_solo_valor_sin_separador(self):
        self.assertEqual(revisar_separadores_lista("100% poliéster"), "")

    def test_un_solo_valor_con_comas(self):
        """Un bullet unico puede llevar comas: no es un separador equivocado."""
        self.assertEqual(revisar_separadores_lista("Cuello alzado, suave y cálido al tacto"), "")

    def test_vacio_y_nulo(self):
        for valor in ["", "   ", None]:
            self.assertEqual(revisar_separadores_lista(valor), "", repr(valor))


class TestSeparadoresEquivocados(unittest.TestCase):
    """Sin |, un salto de linea o un ; si delatan otro separador."""

    def test_saltos_de_linea(self):
        aviso = revisar_separadores_lista("Impermeable\nTranspirable\nLiviano")
        self.assertIn("saltos de linea", aviso)

    def test_retorno_de_carro(self):
        self.assertIn("saltos de linea", revisar_separadores_lista("Impermeable\r\nTranspirable"))

    def test_punto_y_coma(self):
        aviso = revisar_separadores_lista("Impermeable; Transpirable; Liviano")
        self.assertIn(";", aviso)

    def test_separadores_vacios(self):
        aviso = revisar_separadores_lista("Impermeable||Transpirable")
        self.assertIn("||", aviso)

    def test_los_avisos_dicen_que_hacer(self):
        for valor in ["A\nB", "A; B", "A||B"]:
            aviso = revisar_separadores_lista(valor)
            self.assertTrue(aviso)
            self.assertIn("|", aviso, f"el aviso de {valor!r} no explica usar |")


class TestNoRompeOtrasColumnas(unittest.TestCase):
    def test_aplica_a_las_cinco_columnas_de_lista(self):
        for columna in ["Caracteristicas", "Materiales", "Cuidados", "Tecnologia", "Tags adicionales"]:
            self.assertIn(columna, COMMERCIAL_INPUT_TEXT_LIST_COLUMNS, columna)

    def test_no_avisa_para_materiales_tipicos(self):
        for valor in ["100% poliéster", "80% algodón, 20% poliéster",
                      "Exterior: 100% nylon|Forro: 100% poliéster"]:
            self.assertEqual(revisar_separadores_lista(valor), "", valor)

    def test_no_avisa_para_cuidados_tipicos(self):
        self.assertEqual(
            revisar_separadores_lista("Lavar a máquina con agua fría|No usar blanqueador|Secar a la sombra"), "")


class TestElPipeMandaEnTodosLosCampos(unittest.TestCase):
    """Si el valor trae |, ese es el separador. Ningun otro parte el texto."""

    def setUp(self):
        from generate_columbia_matrixify import split_technology_items
        from app_matrixify import _split_tags, manual_sizes_from_text
        self.tec = split_technology_items
        self.tags = _split_tags
        self.tallas = manual_sizes_from_text

    def test_tecnologia_no_parte_por_la_coma_si_hay_pipe(self):
        """Antes daba 3 valores: 'Gore-Tex', '2 capas', 'Omni-Heat'."""
        self.assertEqual(self.tec("Gore-Tex, 2 capas|Omni-Heat"),
                         ["Gore-Tex, 2 capas", "Omni-Heat"])

    def test_tecnologia_no_parte_por_punto_y_coma_si_hay_pipe(self):
        self.assertEqual(self.tec("Lavar; secar|Omni-Heat"), ["Lavar; secar", "Omni-Heat"])

    def test_tags_no_parten_por_la_coma_si_hay_pipe(self):
        self.assertEqual(self.tags("Outdoor, casual|Nueva temporada"),
                         ["Outdoor, casual", "Nueva temporada"])

    def test_tallas_con_pipe(self):
        self.assertEqual(self.tallas("S|M|L"), ["S", "M", "L"])

    def test_body_html_coincide_con_tecnologia(self):
        """El mismo valor debe dar los mismos trozos en ambos caminos."""
        import re

        from app_matrixify import build_body_html_from_commercial_row

        valor = "Gore-Tex, 2 capas|Omni-Heat|Cuello alzado, suave"
        html = build_body_html_from_commercial_row({"Caracteristicas": valor})
        bullets = re.findall(r"<li>(.*?)</li>", html)
        self.assertEqual(len(bullets), len(self.tec(valor)))
        self.assertEqual(len(bullets), 3)


class TestNoSeRompeLoQueVieneDeShopify(unittest.TestCase):
    """Sin |, se conserva la tolerancia: esos datos vienen de Shopify."""

    def setUp(self):
        from generate_columbia_matrixify import split_technology_items
        from app_matrixify import _split_tags
        self.tec = split_technology_items
        self.tags = _split_tags

    def test_tecnologia_separada_por_comas(self):
        self.assertEqual(self.tec("Omni-Tech, Omni-Heat"), ["Omni-Tech", "Omni-Heat"])

    def test_tecnologia_separada_por_punto_y_coma(self):
        self.assertEqual(self.tec("Omni-Tech; Omni-Heat"), ["Omni-Tech", "Omni-Heat"])

    def test_tecnologia_en_json(self):
        self.assertEqual(self.tec('["Omni-Tech", "Omni-Heat"]'), ["Omni-Tech", "Omni-Heat"])

    def test_tags_separados_por_comas(self):
        self.assertEqual(self.tags("Outdoor, Casual, Verano"), ["Outdoor", "Casual", "Verano"])

    def test_valores_vacios_no_revientan(self):
        for valor in ["", None, "   "]:
            self.assertEqual(self.tec(valor), [], repr(valor))
            self.assertEqual(self.tags(valor), [], repr(valor))

    def test_no_se_duplican_valores(self):
        self.assertEqual(self.tec("Omni-Heat|Omni-Heat"), ["Omni-Heat"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
