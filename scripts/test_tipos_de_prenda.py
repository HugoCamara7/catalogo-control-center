"""Pruebas del diccionario de tipos de prenda.

Origen: 14 de los 20 tipos que Forus usa siempre no estaban en
PRODUCT_TYPE_RULES, asi que cada carga salia con la advertencia
"Tipo no reconocido en diccionario".

Ejecutar:  python scripts/test_tipos_de_prenda.py
"""
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import catalog_rules as reglas  # noqa: E402

# Los tipos que Forus maneja siempre.
TIPOS_HABITUALES = [
    "Polares", "Pantalones", "Cuelleras", "Guantes", "Polos",
    "Casacas", "Shorts", "Chalecos", "Chullos", "Sombreros",
    "Gorros", "Polerones", "Camisas", "Interiores Térmicos", "Mochilas",
    "Maletines", "Neceseres", "Canguros", "Ropas de Baño", "Correas",
]


def _validar(tipo, categoria="Vestuario"):
    return reglas.validate_catalog_row({
        "Mod-Col": "1234567-NRY", "Marca": "Columbia", "Genero": "Mujer",
        "Categoria": categoria, "Tipo de prenda": tipo,
        "Guia de tallas": "", "Talla": "M", "SKU": "VALIDACION",
    })


class TestLosVeinteTiposHabituales(unittest.TestCase):
    def test_todos_estan_en_el_diccionario(self):
        faltan = [t for t in TIPOS_HABITUALES if reglas.normalize_product_type(t) is None]
        self.assertEqual(faltan, [], f"tipos sin regla: {faltan}")

    def test_ninguno_genera_advertencia(self):
        con_aviso = []
        for tipo in TIPOS_HABITUALES:
            issues = [i for i in _validar(tipo).get("issues", [])
                      if i.get("field") == "Tipo de prenda"]
            if issues:
                con_aviso.append((tipo, issues[0]["message"]))
        self.assertEqual(con_aviso, [], f"tipos con advertencia: {con_aviso}")

    def test_cada_tipo_trae_categoria_y_subcategoria(self):
        for tipo in TIPOS_HABITUALES:
            regla = reglas.normalize_product_type(tipo)
            self.assertTrue(regla.get("category"), tipo)
            self.assertTrue(regla.get("subcategory"), tipo)
            self.assertTrue(regla.get("plural"), tipo)


class TestClasificacion(unittest.TestCase):
    """La categoria decide como se publica en Shopify."""

    def test_los_de_vestuario(self):
        for tipo in ["Polares", "Chalecos", "Camisas", "Interiores Térmicos",
                     "Casacas", "Polos", "Polerones", "Pantalones", "Shorts"]:
            self.assertEqual(reglas.normalize_product_type(tipo)["category"], "Vestuario", tipo)

    def test_los_accesorios(self):
        for tipo in ["Cuelleras", "Guantes", "Chullos", "Sombreros", "Gorros",
                     "Mochilas", "Maletines", "Neceseres", "Canguros", "Correas"]:
            self.assertEqual(reglas.normalize_product_type(tipo)["category"], "Accesorios", tipo)

    def test_los_accesorios_admiten_talla_unica(self):
        for tipo in ["Cuelleras", "Guantes", "Chullos", "Sombreros",
                     "Mochilas", "Maletines", "Neceseres", "Canguros", "Correas"]:
            self.assertTrue(reglas.normalize_product_type(tipo)["can_one_size"], tipo)

    def test_el_vestuario_no_admite_talla_unica(self):
        for tipo in ["Polares", "Chalecos", "Camisas", "Interiores Térmicos"]:
            self.assertFalse(reglas.normalize_product_type(tipo)["can_one_size"], tipo)

    def test_grupo_de_guia_de_tallas(self):
        for tipo in ["Polares", "Chalecos", "Camisas", "Interiores Térmicos"]:
            self.assertEqual(reglas.normalize_product_type(tipo)["size_guide_group"], "TOPS", tipo)
        self.assertEqual(reglas.normalize_product_type("Ropas de Baño")["size_guide_group"], "BOTTOMS")


class TestVariantesDeEscritura(unittest.TestCase):
    """Singular, plural, mayusculas y acentos deben resolver al mismo tipo."""

    CASOS = [
        ("polar", "Polar"), ("POLARES", "Polar"), ("Polares", "Polar"),
        ("chaleco", "Chaleco"), ("Chalecos", "Chaleco"),
        ("camisa", "Camisa"), ("Camisas", "Camisa"),
        ("Interiores Termicos", "Interior Termico"),
        ("Interiores Térmicos", "Interior Termico"),
        ("Ropa de Baño", "Ropa de Bano"), ("ropa de bano", "Ropa de Bano"),
        ("maletín", "Maletin"), ("Maletines", "Maletin"),
        ("riñonera", "Canguro"), ("Canguros", "Canguro"),
        ("cinturon", "Correa"), ("Correas", "Correa"),
        ("guantes", "Guante"), ("mitones", "Guante"),
        ("bucket hat", "Sombrero"), ("mochilas", "Mochila"),
    ]

    def test_todas_resuelven(self):
        for entrada, esperado in self.CASOS:
            regla = reglas.normalize_product_type(entrada)
            self.assertIsNotNone(regla, f"{entrada!r} no se reconoce")
            self.assertEqual(regla["normalized"], esperado, entrada)


class TestNoSeRompioLoAnterior(unittest.TestCase):
    """Los 10 tipos que ya existian deben seguir igual."""

    ORIGINALES = {
        "Zapatilla": "Calzado", "Casaca": "Vestuario", "Polo": "Vestuario",
        "Poleron": "Vestuario", "Pantalon": "Vestuario", "Short": "Vestuario",
        "Gorro": "Accesorios", "Bolso": "Accesorios", "Slip On": "Calzado",
    }

    def test_siguen_reconociendose(self):
        for tipo, categoria in self.ORIGINALES.items():
            regla = reglas.normalize_product_type(tipo)
            self.assertIsNotNone(regla, tipo)
            self.assertEqual(regla["category"], categoria, tipo)

    def test_no_hay_normalizados_duplicados(self):
        vistos = [r["normalized"] for r in reglas.PRODUCT_TYPE_RULES]
        self.assertEqual(len(vistos), len(set(vistos)), f"duplicados: {vistos}")

    def test_ningun_alias_apunta_a_dos_tipos(self):
        """Un mismo texto no puede resolver a dos reglas distintas."""
        import re

        alias = {}
        for regla in reglas.PRODUCT_TYPE_RULES:
            for campo in ("received", "singular", "plural", "normalized"):
                for parte in re.split(r"[,;/|]", regla.get(campo, "")):
                    clave = reglas.normalize_key(parte)
                    if not clave:
                        continue
                    if clave in alias and alias[clave] != regla["normalized"]:
                        self.fail(f"'{parte.strip()}' apunta a {alias[clave]} y a {regla['normalized']}")
                    alias[clave] = regla["normalized"]

    def test_un_tipo_inventado_sigue_avisando(self):
        issues = [i for i in _validar("TipoQueNoExiste").get("issues", [])
                  if i.get("field") == "Tipo de prenda"]
        self.assertTrue(issues, "un tipo desconocido debe seguir avisando")


if __name__ == "__main__":
    unittest.main(verbosity=2)
