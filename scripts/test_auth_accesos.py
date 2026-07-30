"""Pruebas de accesos por usuario.

Verifica que los usuarios comerciales queden restringidos a "Input comercial"
y "Mis solicitudes", y que nunca caigan en el ROLE_ADMIN por defecto.

Ejecutar:  python scripts/test_auth_accesos.py
"""
import sys
import types
import unittest
from pathlib import Path

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

import app_matrixify as app
from ticket_system import ROLE_ADMIN, ROLE_BRAND

COMERCIALES = [
    "comercial@forus.pe",
    "alejandro.mosqueira@forus.pe",
    "clara.gallastegui@forus.pe",
    "natalia.ludowieg@forus.pe",
    "daniela.ballon@forus.pe",
    "mario.biggio@forus.pe",
    "nicolas.rodriguez@forus.pe",
    "alejandro.espinoza@forus.pe",
]


class TestUsuariosComerciales(unittest.TestCase):
    def test_los_ocho_estan_registrados(self):
        for correo in COMERCIALES:
            self.assertIn(correo, app.COMMERCIAL_INPUT_ONLY_USERS, f"falta {correo}")

    def test_todos_reciben_rol_brand(self):
        for correo in COMERCIALES:
            self.assertEqual(
                app.auth_access_scope(correo), ROLE_BRAND,
                f"{correo} deberia ser {ROLE_BRAND}",
            )

    def test_ninguno_es_admin(self):
        for correo in COMERCIALES:
            self.assertNotEqual(
                app.auth_access_scope(correo), ROLE_ADMIN,
                f"{correo} NO debe tener acceso de administrador",
            )

    def test_no_son_operadores_de_tickets(self):
        """Un comercial no debe poder tomar ni asignar solicitudes ajenas."""
        for correo in COMERCIALES:
            self.assertFalse(app.is_ticket_operator_user(correo), f"{correo} no es operador")

    def test_mayusculas_y_espacios_no_burlan_la_restriccion(self):
        for variante in ["  Mario.Biggio@Forus.pe  ", "MARIO.BIGGIO@FORUS.PE"]:
            self.assertEqual(app.auth_access_scope(variante), ROLE_BRAND, f"fallo con {variante!r}")


class TestOperadores(unittest.TestCase):
    def test_hugo_y_luis_siguen_siendo_admin(self):
        for correo in ["hugo.camara@forus.pe", "luis.nunez@forus.pe"]:
            self.assertEqual(app.auth_access_scope(correo), ROLE_ADMIN)
            self.assertTrue(app.is_ticket_operator_user(correo))


class TestEtiquetaDeSesion(unittest.TestCase):
    def test_nombre_desde_el_correo(self):
        self.assertEqual(app.auth_display_name("alejandro.mosqueira@forus.pe"), "Alejandro Mosqueira")
        self.assertEqual(app.auth_display_name("clara.gallastegui@forus.pe"), "Clara Gallastegui")
        self.assertEqual(app.auth_display_name("comercial@forus.pe"), "Comercial")

    def test_nombres_conocidos_tienen_prioridad(self):
        self.assertEqual(app.auth_display_name("hugo.camara@forus.pe"), "Hugo Camara")

    def test_usuario_vacio(self):
        self.assertEqual(app.auth_display_name(""), "Usuario")

    def test_etiquetas_de_rol(self):
        self.assertEqual(app.auth_role_label(ROLE_ADMIN), "Administrador")
        self.assertEqual(app.auth_role_label(ROLE_BRAND), "Comercial")
        self.assertEqual(app.auth_role_label("desconocido"), "Usuario")


class TestCssNoOcultaLaSesion(unittest.TestCase):
    def test_existe_el_estilo_de_la_tarjeta(self):
        css = (ROOT / "assets" / "app.css").read_text(encoding="utf-8")
        for clase in [".session-card", ".session-avatar", ".session-text"]:
            self.assertIn(clase, css, f"falta el estilo {clase}")

    def test_la_tarjeta_no_esta_oculta(self):
        css = (ROOT / "assets" / "app.css").read_text(encoding="utf-8")
        inicio = css.find(".session-card")
        bloque = css[inicio:inicio + 400]
        self.assertNotIn("display:none", bloque.replace(" ", ""))


if __name__ == "__main__":
    unittest.main(verbosity=2)
