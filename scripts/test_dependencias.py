# -*- coding: utf-8 -*-
"""Toda libreria que usa la app tiene que estar en requirements.txt.

Origen: el 24/08/2026 la app reventó en produccion al generar el Excel con

    ModuleNotFoundError: No module named 'xlsxwriter'

El motor de Excel se cambio de openpyxl a xlsxwriter para bajar el pico de
memoria, pero **la dependencia nunca se declaro**. En local funcionaba porque
xlsxwriter venia instalado de arrastre; en el servidor no. Y el fallo salia al
FINAL del proceso, despues de calcular todo el catalogo.

Esta prueba recorre el codigo de produccion, saca sus imports de terceros y
comprueba que cada uno este declarado. Es barata y evita repetir la clase
entera de fallo, no solo el caso de xlsxwriter.

Ejecutar:  python scripts/test_dependencias.py
"""
import ast
import os
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# Modulos del propio proyecto: no son dependencias externas.
PROPIOS = {
    "app_matrixify", "generate_columbia_matrixify", "catalog_rules", "ticket_system",
    "centry_static_masters", "shopify_api", "catalog_engine", "job_store",
    "sync_worker", "api_main", "engines", "scripts",
}

# El paquete instalable no siempre se llama como el modulo.
PAQUETE_DE = {
    "google": ("google-cloud-bigquery", "google-auth"),
    "yaml": ("pyyaml",),
    "PIL": ("pillow",),
    "dateutil": ("python-dateutil",),
    "bs4": ("beautifulsoup4",),
    "dotenv": ("python-dotenv",),
}

# `api_main.py` es el servicio FastAPI, que no forma parte de la app Streamlit
# y tiene su propio requirements-api.txt.
SOLO_API = {"api_main.py"}


def _imports_de(ruta):
    try:
        arbol = ast.parse(ruta.read_text(encoding="utf-8-sig"))
    except SyntaxError:
        return set()
    modulos = set()
    for nodo in ast.walk(arbol):
        if isinstance(nodo, ast.Import):
            modulos.update(alias.name.split(".")[0] for alias in nodo.names)
        elif isinstance(nodo, ast.ImportFrom) and nodo.level == 0 and nodo.module:
            modulos.add(nodo.module.split(".")[0])
    return modulos


def _archivos_de_produccion():
    """El codigo que corre en el servidor: la app, los motores, no las pruebas."""
    archivos = []
    for ruta in ROOT.rglob("*.py"):
        partes = set(ruta.parts)
        if partes & {".git", "__pycache__", "outputs", "data", "job_inputs"}:
            continue
        if ruta.name.startswith("test_"):
            continue
        archivos.append(ruta)
    return archivos


def _declarados(nombre_archivo):
    ruta = ROOT / nombre_archivo
    if not ruta.exists():
        return ""
    return ruta.read_text(encoding="utf-8").lower()


class TestDependenciasDeclaradas(unittest.TestCase):
    def setUp(self):
        self.requirements = _declarados("requirements.txt")
        self.requirements_api = _declarados("requirements-api.txt")

    def _esta_declarado(self, modulo, texto):
        for paquete in PAQUETE_DE.get(modulo, (modulo,)):
            if paquete.lower() in texto:
                return True
        return False

    def test_todo_import_de_produccion_esta_en_requirements(self):
        """Regresion: xlsxwriter se usaba y no estaba declarado."""
        sin_declarar = {}
        for ruta in _archivos_de_produccion():
            texto = (self.requirements_api if ruta.name in SOLO_API else self.requirements)
            for modulo in _imports_de(ruta):
                if modulo in sys.stdlib_module_names or modulo in PROPIOS:
                    continue
                if modulo.startswith("_"):
                    continue
                if not self._esta_declarado(modulo, texto):
                    sin_declarar.setdefault(modulo, []).append(ruta.name)
        self.assertEqual(
            sin_declarar, {},
            "Estas librerias se usan pero no estan declaradas: "
            + "; ".join(f"{m} ({', '.join(sorted(set(f)))})" for m, f in sin_declarar.items()),
        )

    def test_xlsxwriter_esta_declarado(self):
        """El caso concreto que tumbo la app, con nombre y apellido."""
        self.assertIn("xlsxwriter", self.requirements)

    def test_requirements_no_esta_vacio(self):
        self.assertGreater(len(self.requirements.strip().splitlines()), 3)


class TestElExcelNoDependeDeUnaSolaLibreria(unittest.TestCase):
    """Aunque falte xlsxwriter, el Excel tiene que salir igual."""

    def test_el_motor_elegido_es_uno_de_los_dos(self):
        import app_matrixify as app

        self.assertIn(app.MOTOR_EXCEL, ("xlsxwriter", "openpyxl"))

    def test_prefiere_xlsxwriter_cuando_esta_instalado(self):
        import app_matrixify as app

        try:
            import xlsxwriter  # noqa: F401
        except ImportError:
            self.skipTest("xlsxwriter no esta instalado en este entorno")
        self.assertEqual(app.MOTOR_EXCEL, "xlsxwriter")

    def test_hay_respaldo_declarado_en_el_codigo(self):
        """Si un despliegue se queda sin xlsxwriter, cae a openpyxl en vez de
        reventar al final del proceso."""
        import inspect

        import app_matrixify as app

        fuente = inspect.getsource(app._motor_excel_disponible)
        self.assertIn("openpyxl", fuente)
        self.assertIn("ImportError", fuente)


if __name__ == "__main__":
    unittest.main(verbosity=2)
