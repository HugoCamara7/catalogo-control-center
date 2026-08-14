"""Pruebas de engines/garment_types.py — diccionario maestro por sitio.

Generado desde "Tipo de Prendas Actualizado Diccionario - Corregido.xlsx",
la fuente de verdad que confirmo el usuario.
"""
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from engines import garment_types as g

SITIOS = ("columbia", "rockford", "hush_puppies", "vans")


class TestIntegridad(unittest.TestCase):
    def test_no_importa_streamlit_ni_pandas(self):
        fuente = (ROOT / "engines" / "garment_types.py").read_text(encoding="utf-8")
        self.assertNotIn("import streamlit", fuente)
        self.assertNotIn("import pandas", fuente)

    def test_son_60_tipos(self):
        self.assertEqual(len(g.TIPOS), 60)

    def test_toda_regla_tiene_tipo_y_clase(self):
        for t in g.TIPOS:
            self.assertTrue(t["tipo"], t)
            self.assertIn(t["categoria"], {"Vestuario", "Calzado", "Accesorios"}, t["tipo"])

    def test_ningun_nombre_apunta_a_dos_tipos(self):
        """Un alias ambiguo da resultados distintos segun el orden de la lista."""
        visto = {}
        for t in g.TIPOS:
            for n in [t["tipo"]] + list(t["sitios"].values()) + t["sinonimos"]:
                k = g.clave(n)
                if not k:
                    continue
                if k in visto and visto[k] != t["tipo"]:
                    self.fail(f"{n!r} apunta a {visto[k]} y a {t['tipo']}")
                visto[k] = t["tipo"]

    def test_los_sitios_son_los_cuatro_conocidos(self):
        for t in g.TIPOS:
            for s in t["sitios"]:
                self.assertIn(s, SITIOS, f"{t['tipo']}: {s}")


class TestResolucion(unittest.TestCase):
    def test_reconoce_venga_como_venga(self):
        for entrada in ("Chalecos", "CHALECOS", "chalecos", "  chalecos  "):
            self.assertEqual(g.tipo_canonico(entrada), "Chalecos", entrada)

    def test_los_sinonimos_del_excel(self):
        self.assertEqual(g.tipo_canonico("chompas"), "Chompas")
        self.assertEqual(g.tipo_canonico("remera"), "Polos")
        self.assertEqual(g.tipo_canonico("zapatilla"), "Zapatillas")

    def test_ignora_tildes_y_guiones(self):
        self.assertEqual(g.tipo_canonico("lentes de sol"), g.tipo_canonico("Lentes-De-Sol"))

    def test_la_clase_se_deriva(self):
        self.assertEqual(g.clase_de("Chalecos"), "Vestuario")
        self.assertEqual(g.clase_de("Zapatillas"), "Calzado")
        self.assertEqual(g.clase_de("Mochilas"), "Accesorios")

    def test_outdoor_no_es_un_tipo(self):
        """Es una clase. Reconocerlo seria repetir el fallo de Patagonia."""
        self.assertIsNone(g.resolver("Outdoor"))
        self.assertEqual(g.clase_de("Outdoor"), "")

    def test_lo_desconocido_devuelve_vacio(self):
        self.assertEqual(g.tipo_canonico("TipoQueNoExiste"), "")
        self.assertEqual(g.tipo_canonico(""), "")
        self.assertEqual(g.tipo_canonico(None), "")


class TestPorSitio(unittest.TestCase):
    def test_devuelve_el_nombre_del_sitio(self):
        for sitio in SITIOS:
            nombre = g.tipo_para_sitio("Casacas", sitio)
            if nombre:
                self.assertEqual(g.tipo_canonico(nombre), "Casacas", sitio)

    def test_un_tipo_que_el_sitio_no_vende_devuelve_vacio(self):
        """No se fuerza un nombre que esa tienda no usa."""
        for t in g.TIPOS:
            for sitio in SITIOS:
                if sitio not in t["sitios"]:
                    self.assertEqual(g.tipo_para_sitio(t["tipo"], sitio), "",
                                     f"{t['tipo']} / {sitio}")
                    self.assertFalse(g.aplica_a_sitio(t["tipo"], sitio))

    def test_sin_sitio_devuelve_el_canonico(self):
        self.assertEqual(g.tipo_para_sitio("chompas", ""), "Chompas")

    def test_un_sitio_desconocido_devuelve_el_canonico(self):
        self.assertEqual(g.tipo_para_sitio("chompas", "sitio_inventado"), "Chompas")

    def test_cada_sitio_tiene_tipos(self):
        for sitio in SITIOS:
            self.assertGreater(len(g.tipos_de_sitio(sitio)), 10, sitio)

    def test_los_tipos_de_un_sitio_se_resuelven_a_si_mismos(self):
        for sitio in SITIOS:
            for nombre in g.tipos_de_sitio(sitio):
                self.assertTrue(g.resolver(nombre), f"{sitio}: {nombre}")


class TestSinonimos(unittest.TestCase):
    def test_hay_muchos(self):
        self.assertGreater(sum(len(t["sinonimos"]) for t in g.TIPOS), 250)

    def test_sinonimos_de(self):
        self.assertTrue(g.sinonimos_de("Polos"))
        self.assertEqual(g.sinonimos_de("NoExiste"), [])


if __name__ == "__main__":
    unittest.main(verbosity=2)
