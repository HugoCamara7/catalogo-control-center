"""Pruebas de build_body_html — Descripcion, Caracteristicas, Materiales, Cuidados.

El fallo que fijan: la Descripcion nunca se emitia como seccion propia. Se leia
solo como sustituto de Caracteristicas, asi que con las dos columnas llenas
(el caso de Rockford) la Descripcion se perdia entera, y con solo Descripcion
salia publicada bajo el titulo "Caracteristicas".
"""
import re
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import pandas as pd
from generate_columbia_matrixify import build_body_html


def secciones(html):
    return [s for s in re.findall(r'data-titulo="([^"]+)"', html)
            if s != "Información del producto"]


def cuerpo(fila):
    return build_body_html(pd.Series(fila))


class TestDescripcion(unittest.TestCase):
    ROCKFORD = {
        "Descripcion": "Zapatilla urbana de uso diario.",
        "Caracteristicas": "Suela antideslizante|Plantilla acolchada",
        "Materiales": "Cuero legitimo|Suela de goma",
        "Cuidados": "Limpiar con pano humedo",
    }

    def test_la_descripcion_no_se_pierde_con_caracteristicas(self):
        html = cuerpo(self.ROCKFORD)
        self.assertIn("Zapatilla urbana de uso diario.", html)

    def test_salen_las_cuatro_secciones(self):
        self.assertEqual(secciones(cuerpo(self.ROCKFORD)),
                         ["Descripción", "Características", "Materiales", "Cuidados"])

    def test_la_descripcion_va_primero(self):
        self.assertEqual(secciones(cuerpo(self.ROCKFORD))[0], "Descripción")

    def test_sola_no_se_disfraza_de_caracteristicas(self):
        self.assertEqual(secciones(cuerpo({"Descripcion": "Zapatilla urbana."})), ["Descripción"])

    def test_prosa_va_en_parrafo_no_en_lista(self):
        html = cuerpo({"Descripcion": "Zapatilla urbana de uso diario."})
        self.assertIn("<p>Zapatilla urbana de uso diario.</p>", html)

    def test_con_pipe_la_descripcion_si_es_lista(self):
        html = cuerpo({"Descripcion": "Uso diario|Urbana"})
        self.assertEqual(re.findall(r"<li>(.*?)</li>", html), ["Uso diario", "Urbana"])

    def test_alias_con_y_sin_tilde(self):
        for alias in ("Descripcion", "Descripción", "Description", "Product Description"):
            self.assertIn("Texto", cuerpo({alias: "Texto de prueba"}), alias)


class TestSeccionesRestantes(unittest.TestCase):
    def test_caracteristicas_en_bullets(self):
        html = cuerpo({"Caracteristicas": "Suela antideslizante|Plantilla acolchada"})
        self.assertEqual(re.findall(r"<li>(.*?)</li>", html),
                         ["Suela antideslizante", "Plantilla acolchada"])

    def test_materiales_en_bullets(self):
        html = cuerpo({"Materiales": "Cuero|Goma"})
        self.assertEqual(re.findall(r"<li>(.*?)</li>", html), ["Cuero", "Goma"])

    def test_cuidados(self):
        self.assertEqual(secciones(cuerpo({"Cuidados": "Lavar a mano"})), ["Cuidados"])

    def test_el_pipe_decimal_no_corta(self):
        """5|3-oz son 5.3 oz, no dos materiales."""
        html = cuerpo({"Materiales": "Nylon 5|3-oz|Poliester"})
        self.assertEqual(re.findall(r"<li>(.*?)</li>", html), ["Nylon 5|3-oz", "Poliester"])


class TestBordes(unittest.TestCase):
    def test_sin_contenido_no_hay_body(self):
        self.assertEqual(cuerpo({}), "")
        self.assertEqual(cuerpo({"Descripcion": "", "Caracteristicas": ""}), "")

    def test_texto_basura_se_descarta(self):
        self.assertEqual(cuerpo({"Descripcion": "---"}), "")

    def test_solo_las_secciones_con_datos(self):
        self.assertEqual(secciones(cuerpo({"Descripcion": "Algo util", "Cuidados": "Lavar a mano"})),
                         ["Descripción", "Cuidados"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
