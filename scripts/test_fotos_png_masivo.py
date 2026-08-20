# -*- coding: utf-8 -*-
"""Pruebas del mantenedor de fotos PNG con Excel de varios codigos.

El mantenedor sigue siendo independiente de la carga parcial y sigue buscando
SOLO .png: lo unico que se agrega es de donde salen los codigos. El motor
normal de imagenes no se toca y continua con JPG/JPEG.

Lo que se comprueba aqui:
  - se leen todos los codigos del Excel, sin vacios ni repetidos;
  - se validan ANTES de tocar la red, para no gastar 10 peticiones en un
    codigo mal escrito;
  - se respeta el tope de 10 vistas por modelo-color;
  - el resumen por modelo cuadra: encontradas, cargadas, existentes, errores.

Ejecutar:  python scripts/test_fotos_png_masivo.py
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


class TestLeerCodigosDelExcel(unittest.TestCase):
    def test_lee_la_columna_codigo_modelo_color(self):
        df = pd.DataFrame({"Código Modelo Color": ["HP1234567-001", "HP1234567-002"]})
        codigos, descartes = app.png_codigos_desde_excel(df)
        self.assertEqual(codigos, ["HP1234567-001", "HP1234567-002"])
        self.assertEqual(descartes, [])

    def test_quita_vacios_sin_reportarlos(self):
        """Una fila vacia al final del Excel es normal, no un problema."""
        df = pd.DataFrame({"Código Modelo Color": ["HP1234567-001", "", None, "   "]})
        codigos, descartes = app.png_codigos_desde_excel(df)
        self.assertEqual(codigos, ["HP1234567-001"])
        self.assertEqual(descartes, [])

    def test_quita_repetidos_y_dice_cuales(self):
        df = pd.DataFrame({"Código Modelo Color": [
            "HP1234567-001", "hp1234567-001", "HP1234567-002", "HP1234567-001",
        ]})
        codigos, descartes = app.png_codigos_desde_excel(df)
        self.assertEqual(codigos, ["HP1234567-001", "HP1234567-002"])
        self.assertEqual(len(descartes), 2)
        self.assertTrue(all("Duplicado" in item["Motivo"] for item in descartes))

    def test_conserva_el_orden_del_archivo(self):
        df = pd.DataFrame({"Código Modelo Color": ["HP3-C", "HP1-A", "HP2-B"]})
        codigos, _ = app.png_codigos_desde_excel(df)
        self.assertEqual(codigos, ["HP3-C", "HP1-A", "HP2-B"])

    def test_acepta_los_alias_habituales_de_la_columna(self):
        for cabecera in ["Mod-Col", "COD MOD COL", "Codigo Modelo Color", "codigo_modelo_color"]:
            df = pd.DataFrame({cabecera: ["HP1234567-001"]})
            codigos, _ = app.png_codigos_desde_excel(df)
            self.assertEqual(codigos, ["HP1234567-001"], cabecera)

    def test_acepta_una_columna_sin_cabecera_reconocible(self):
        df = pd.DataFrame({"Sin nombre": ["HP1234567-001", "HP1234567-002"]})
        codigos, _ = app.png_codigos_desde_excel(df)
        self.assertEqual(codigos, ["HP1234567-001", "HP1234567-002"])

    def test_avisa_cuando_no_hay_columna_de_codigos(self):
        df = pd.DataFrame({"Comentario": ["texto libre", "otra cosa"]})
        codigos, descartes = app.png_codigos_desde_excel(df)
        self.assertEqual(codigos, [])
        self.assertTrue(descartes)

    def test_un_excel_vacio_no_revienta(self):
        codigos, descartes = app.png_codigos_desde_excel(pd.DataFrame())
        self.assertEqual(codigos, [])
        self.assertTrue(descartes)
        self.assertEqual(app.png_codigos_desde_excel(None)[0], [])


class TestValidarCodigos(unittest.TestCase):
    def test_pasa_los_que_se_pueden_separar_en_modelo_y_color(self):
        validos, invalidos = app.png_validar_codigos(["HP1234567-001", "RK21101121-085"])
        self.assertEqual(validos, ["HP1234567-001", "RK21101121-085"])
        self.assertEqual(invalidos, [])

    def test_descarta_lo_que_no_tiene_forma_de_modelo_color(self):
        """Se descarta ANTES de la red: 10 peticiones por codigo malo."""
        validos, invalidos = app.png_validar_codigos(["HP1234567-001", "SINCOLOR", ""])
        self.assertEqual(validos, ["HP1234567-001"])
        self.assertEqual({item["Código Modelo Color"] for item in invalidos}, {"SINCOLOR", ""})


class TestTopeDeVistas(unittest.TestCase):
    def test_diez_vistas_por_modelo_color(self):
        urls = app.png_image_candidates("HP1234567-001", {"image_base_url": "https://cdn/fotos"})
        self.assertEqual(len(urls), app.PNG_MAX_VISTAS)
        self.assertEqual(app.PNG_MAX_VISTAS, 10)

    def test_solo_png(self):
        urls = app.png_image_candidates("HP1234567-001", {"image_base_url": "https://cdn/fotos"})
        self.assertTrue(all(url.endswith(".png") for url in urls), urls)

    def test_van_en_orden_de_vista(self):
        urls = app.png_image_candidates("HP1234567-001", {"image_base_url": "https://cdn/fotos"})
        self.assertTrue(urls[0].endswith("_1.png"))
        self.assertTrue(urls[-1].endswith("_10.png"))


class TestResumenPorModelo(unittest.TestCase):
    def _filas(self):
        return [
            {"Vista": 1, "URL": "u1", "Estado": "Encontrada", "Detalle": ""},
            {"Vista": 2, "URL": "u2", "Estado": "Ya existente", "Detalle": ""},
            {"Vista": 3, "URL": "u3", "Estado": "No existe", "Detalle": ""},
            {"Vista": 4, "URL": "u4", "Estado": "Error", "Detalle": "timeout"},
            {"Vista": 5, "URL": "u5", "Estado": "Duplicada", "Detalle": ""},
        ]

    def test_cuenta_cada_estado(self):
        resumen = app.png_resumen_modelo("HP1-001", self._filas(), producto={"Product ID": "1"})
        self.assertEqual(resumen["Código Modelo Color"], "HP1-001")
        self.assertEqual(resumen["En Shopify"], "SI")
        self.assertEqual(resumen["Vistas encontradas"], 1)
        self.assertEqual(resumen["Cargadas"], 0)
        self.assertEqual(resumen["Ya existentes"], 1)
        self.assertEqual(resumen["Sin PNG"], 1)
        self.assertEqual(resumen["Duplicadas"], 1)
        self.assertEqual(resumen["Errores"], 1)

    def test_marca_el_modelo_que_no_esta_en_shopify(self):
        resumen = app.png_resumen_modelo("HP1-001", self._filas(), producto=None)
        self.assertEqual(resumen["En Shopify"], "NO")

    def test_tras_cargar_las_encontradas_pasan_a_cargadas(self):
        filas = app.png_marcar_resultado_carga(self._filas(), app.PNG_ESTADO_CARGADA, "1 foto")
        resumen = app.png_resumen_modelo("HP1-001", filas, producto={"Product ID": "1"})
        self.assertEqual(resumen["Cargadas"], 1)
        # Se sigue sabiendo cuantas se habian encontrado.
        self.assertEqual(resumen["Vistas encontradas"], 1)

    def test_un_error_de_carga_no_se_confunde_con_uno_de_busqueda(self):
        filas = app.png_marcar_resultado_carga(self._filas(), app.PNG_ESTADO_ERROR_CARGA, "403")
        resumen = app.png_resumen_modelo("HP1-001", filas, producto={"Product ID": "1"})
        self.assertEqual(resumen["Cargadas"], 0)
        self.assertEqual(resumen["Errores"], 2)  # el de busqueda y el de carga
        self.assertEqual(resumen["Vistas encontradas"], 1)

    def test_marcar_resultado_no_toca_las_demas_vistas(self):
        filas = app.png_marcar_resultado_carga(self._filas(), app.PNG_ESTADO_CARGADA, "ok")
        estados = [fila["Estado"] for fila in filas]
        self.assertEqual(estados, [app.PNG_ESTADO_CARGADA, "Ya existente", "No existe", "Error", "Duplicada"])


class TestDetalleDelLote(unittest.TestCase):
    def test_junta_todas_las_vistas_con_su_codigo(self):
        resultados = [
            {"mod_col": "HP1-001", "filas": [{"Vista": 1, "Estado": "Encontrada"}]},
            {"mod_col": "HP1-002", "filas": [{"Vista": 1, "Estado": "No existe"},
                                             {"Vista": 2, "Estado": "Encontrada"}]},
        ]
        detalle = app.png_detalle_por_modelo(resultados)
        self.assertEqual(len(detalle), 3)
        self.assertEqual(detalle[0]["Código Modelo Color"], "HP1-001")
        self.assertEqual(detalle[2]["Código Modelo Color"], "HP1-002")


class TestNoContaminaElMotorNormal(unittest.TestCase):
    """El motor de imagenes de siempre sigue siendo solo JPG."""

    def test_el_motor_normal_no_busca_png(self):
        from generate_columbia_matrixify import image_candidates

        urls = image_candidates("HP1234567-001", {"image_base_url": "https://cdn/fotos"})
        self.assertTrue(urls, "el motor normal deberia seguir generando URLs")
        self.assertFalse([url for url in urls if url.lower().endswith(".png")], urls[:3])


if __name__ == "__main__":
    unittest.main(verbosity=2)
