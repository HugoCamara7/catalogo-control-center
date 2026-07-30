"""Pruebas de la ejecucion de carga usando el archivo guardado en la solicitud.

Lo critico: el archivo que viene de la solicitud debe comportarse EXACTAMENTE
igual que uno subido con st.file_uploader, para que el motor de carga no
necesite ningun cambio.

Ejecutar:  python scripts/test_carga_desde_solicitud.py
"""
import io
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

import pandas as pd  # noqa: E402

import app_matrixify as app  # noqa: E402


def excel_de_prueba():
    buffer = io.BytesIO()
    df = pd.DataFrame({"Mod-Col": ["AB-1", "CD-2"], "Marca": ["Columbia", "Columbia"]})
    with pd.ExcelWriter(buffer, engine="openpyxl") as writer:
        df.to_excel(writer, index=False, sheet_name="PARA_COMPLETAR")
    return buffer.getvalue()


class TestArchivoDeSolicitud(unittest.TestCase):
    """Debe ser indistinguible de un archivo subido."""

    def setUp(self):
        self.contenido = excel_de_prueba()
        self.archivo = app.ArchivoDeSolicitud(self.contenido, "input prueba hp.xlsx", "CAT-2026-000009")

    def test_tiene_la_interfaz_de_un_archivo_subido(self):
        for atributo in ["name", "size", "seek", "read"]:
            self.assertTrue(hasattr(self.archivo, atributo), atributo)

    def test_name_y_size_correctos(self):
        self.assertEqual(self.archivo.name, "input prueba hp.xlsx")
        self.assertEqual(self.archivo.size, len(self.contenido))

    def test_nombre_por_defecto_si_falta(self):
        self.assertEqual(app.ArchivoDeSolicitud(b"x", "").name, "input_solicitud.xlsx")

    def test_pandas_lo_lee(self):
        df = pd.read_excel(self.archivo, dtype=object)
        self.assertEqual(list(df.columns), ["Mod-Col", "Marca"])
        self.assertEqual(len(df), 2)

    def test_se_puede_releer_tras_seek(self):
        pd.read_excel(self.archivo, dtype=object)
        self.archivo.seek(0)
        df = pd.read_excel(self.archivo, dtype=object)
        self.assertEqual(len(df), 2)

    def test_produce_el_mismo_dataframe_que_un_archivo_subido(self):
        """La prueba que importa: mismo contenido, mismo resultado."""
        class Subido(io.BytesIO):
            def __init__(self, datos, nombre):
                super().__init__(datos)
                self.name = nombre
                self.size = len(datos)

        manual = Subido(self.contenido, "input prueba hp.xlsx")
        df_manual = pd.read_excel(manual, dtype=object).dropna(how="all")
        self.archivo.seek(0)
        df_solicitud = pd.read_excel(self.archivo, dtype=object).dropna(how="all")
        pd.testing.assert_frame_equal(df_manual, df_solicitud)

    def test_la_huella_es_estable(self):
        """Si cambiara entre reruns, el estado de carga se limpiaria solo."""
        h1 = app.uploaded_file_fingerprint(self.archivo)
        h2 = app.uploaded_file_fingerprint(self.archivo)
        self.assertEqual(h1, h2)
        self.assertIn("input prueba hp.xlsx", h1)

    def test_dos_solicitudes_distintas_dan_huellas_distintas(self):
        otro = app.ArchivoDeSolicitud(self.contenido + b"  ", "otro.xlsx", "CAT-2")
        self.assertNotEqual(
            app.uploaded_file_fingerprint(self.archivo),
            app.uploaded_file_fingerprint(otro),
        )

    def test_conserva_el_codigo_de_solicitud(self):
        self.assertEqual(self.archivo.ticket_code, "CAT-2026-000009")


class _ServicioFalso:
    def __init__(self, tickets, artefactos=None):
        self._tickets = tickets
        self.store = types.SimpleNamespace(get_artifact=self._get)
        self._artefactos = artefactos or {}

    def list_tickets(self, actor):
        return self._tickets

    def _get(self, ruta):
        if ruta not in self._artefactos:
            raise RuntimeError("no encontrado")
        return self._artefactos[ruta]


def ticket(codigo, estado, sitio="Columbia.pe", ruta="ruta/input.xlsx", tipo="complete",
           marca="Columbia"):
    return {
        "code": codigo, "status": estado, "load_type": tipo,
        "sites": [sitio], "brand": marca,
        "summary": {"products": 3}, "requested_by": "comercial@forus.pe",
        "created_at": "2026-07-30T10:00:00",
        "versions": ([{"input_path": ruta, "filename": "input.xlsx"}] if ruta else []),
    }


class TestSolicitudesElegibles(unittest.TestCase):
    def setUp(self):
        self.brand = app.get_brand_config("columbia")

    def test_solo_las_que_tienen_archivo(self):
        svc = _ServicioFalso([
            ticket("CAT-1", app.STATE_APPROVED),
            ticket("CAT-2", app.STATE_APPROVED, ruta=""),
        ])
        codigos = [t["code"] for t in app.solicitudes_ejecutables(svc, {}, self.brand)]
        self.assertEqual(codigos, ["CAT-1"])

    def test_solo_carga_completa(self):
        svc = _ServicioFalso([
            ticket("CAT-1", app.STATE_APPROVED),
            ticket("CAT-2", app.STATE_APPROVED, tipo="partial"),
        ])
        codigos = [t["code"] for t in app.solicitudes_ejecutables(svc, {}, self.brand)]
        self.assertEqual(codigos, ["CAT-1"])

    def test_solo_del_sitio_activo(self):
        # _ticket_matches_active_site compara sitios Y marca: para que un
        # ticket sea de otro sitio, ambos tienen que serlo.
        svc = _ServicioFalso([
            ticket("CAT-1", app.STATE_APPROVED, sitio="Columbia.pe", marca="Columbia"),
            ticket("CAT-2", app.STATE_APPROVED, sitio="Vans.pe", marca="Vans"),
        ])
        codigos = [t["code"] for t in app.solicitudes_ejecutables(svc, {}, self.brand)]
        self.assertEqual(codigos, ["CAT-1"])

    def test_la_marca_tambien_cuenta_como_sitio(self):
        """Un ticket de marca Columbia sigue siendo elegible en Columbia.pe."""
        svc = _ServicioFalso([ticket("CAT-1", app.STATE_APPROVED, sitio="otro.pe", marca="Columbia")])
        self.assertEqual([t["code"] for t in app.solicitudes_ejecutables(svc, {}, self.brand)], ["CAT-1"])

    def test_un_servicio_caido_no_revienta(self):
        class Roto:
            def list_tickets(self, actor):
                raise RuntimeError("sin red")

        self.assertEqual(app.solicitudes_ejecutables(Roto(), {}, self.brand), [])


class TestRecuperarArchivo(unittest.TestCase):
    def test_devuelve_el_adjunto(self):
        contenido = excel_de_prueba()
        svc = _ServicioFalso([], {"ruta/input.xlsx": contenido})
        archivo = app.archivo_de_solicitud(svc, ticket("CAT-9", app.STATE_APPROVED))
        self.assertIsNotNone(archivo)
        self.assertEqual(archivo.size, len(contenido))
        self.assertEqual(archivo.ticket_code, "CAT-9")

    def test_sin_versiones_devuelve_none(self):
        svc = _ServicioFalso([], {})
        self.assertIsNone(app.archivo_de_solicitud(svc, ticket("CAT-9", app.STATE_APPROVED, ruta="")))

    def test_si_el_artefacto_no_existe_devuelve_none(self):
        """Solicitudes viejas cuyo archivo se perdio: se cae a la carga manual."""
        svc = _ServicioFalso([], {})
        self.assertIsNone(app.archivo_de_solicitud(svc, ticket("CAT-9", app.STATE_APPROVED)))

    def test_artefacto_vacio_devuelve_none(self):
        svc = _ServicioFalso([], {"ruta/input.xlsx": b""})
        self.assertIsNone(app.archivo_de_solicitud(svc, ticket("CAT-9", app.STATE_APPROVED)))


class TestNoSeDuplicoElMotor(unittest.TestCase):
    def test_sigue_habiendo_un_solo_lector_de_input(self):
        fuente = (ROOT / "app_matrixify.py").read_text(encoding="utf-8-sig")
        self.assertEqual(fuente.count("def read_uploaded_excel_cached"), 1)

    def test_sigue_habiendo_un_solo_generador_matrixify(self):
        fuente = (ROOT / "app_matrixify.py").read_text(encoding="utf-8-sig")
        self.assertEqual(fuente.count("build_columbia_matrixify("), 1)


if __name__ == "__main__":
    unittest.main(verbosity=2)
