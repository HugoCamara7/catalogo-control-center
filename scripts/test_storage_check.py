"""Pruebas del diagnostico de almacenamiento frente a fallos de GitHub.

Origen: la app mostro "Almacenamiento sin persistir" con el detalle
"Respuesta 503: No server is currently available to service your request" y el
consejo "Revisa el token en Secrets". El token estaba bien: GitHub no atendio
esa peticion. Un solo hipo dejaba el banner en rojo y mandaba a buscar el
problema donde no estaba.

Ejecutar:  python scripts/test_storage_check.py
"""
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from engines import storage_check as sc  # noqa: E402

MENSAJE_503 = "No server is currently available to service your request."


class _GitHubFalso:
    """Devuelve respuestas por URL, en orden, y cuenta las llamadas."""

    def __init__(self, respuestas):
        self.respuestas = respuestas
        self.llamadas = []

    def __call__(self, metodo, url, token, payload=None, timeout=15):
        self.llamadas.append(url)
        for fragmento, secuencia in self.respuestas.items():
            if fragmento in url:
                return secuencia.pop(0) if len(secuencia) > 1 else secuencia[0]
        return 200, {}


class TestReintentoTransitorio(unittest.TestCase):
    def setUp(self):
        self._peticion = sc._peticion_una_vez
        self._sleep = sc.time.sleep
        sc.time.sleep = lambda _s: None

    def tearDown(self):
        sc._peticion_una_vez = self._peticion
        sc.time.sleep = self._sleep

    def test_reintenta_el_503_y_sigue_si_luego_responde(self):
        tienda = _GitHubFalso({
            "/user": [(503, {"message": MENSAJE_503}), (200, {"login": "HugoCamara7"})],
        })
        sc._peticion_una_vez = tienda
        resultado = sc.check_github_store("HugoCamara7", "catalogo-control-center-data", "tok")
        paso_token = next(p for p in resultado["pasos"] if p["paso"] == "Token")
        self.assertEqual(paso_token["estado"], sc.OK)
        self.assertIn("HugoCamara7", paso_token["detalle"])

    def test_un_503_persistente_no_culpa_al_token(self):
        tienda = _GitHubFalso({"/user": [(503, {"message": MENSAJE_503})]})
        sc._peticion_una_vez = tienda
        resultado = sc.check_github_store("HugoCamara7", "catalogo-control-center-data", "tok")
        paso_token = next(p for p in resultado["pasos"] if p["paso"] == "Token")
        # Aviso, no falla: no se sabe si persiste, pero el token no es el culpable.
        self.assertEqual(paso_token["estado"], sc.AVISO)
        self.assertIn("no es el token", paso_token["arreglo"].lower())
        self.assertFalse(resultado["persistente"])

    def test_el_banner_dice_por_confirmar_y_no_sin_persistir(self):
        tienda = _GitHubFalso({"/user": [(503, {"message": MENSAJE_503})]})
        sc._peticion_una_vez = tienda
        resultado = sc.check_github_store("HugoCamara7", "catalogo-control-center-data", "tok")
        estado, texto = sc.resumen(resultado)
        self.assertEqual(estado, sc.AVISO)
        self.assertEqual(texto, "Almacenamiento por confirmar")

    def test_reintenta_las_veces_configuradas(self):
        tienda = _GitHubFalso({"/user": [(503, {"message": MENSAJE_503})]})
        sc._peticion_una_vez = tienda
        sc.check_github_store("HugoCamara7", "catalogo-control-center-data", "tok")
        self.assertEqual(len([u for u in tienda.llamadas if u.endswith("/user")]), sc.REINTENTOS)

    def test_el_401_no_se_reintenta_y_sigue_siendo_falla(self):
        tienda = _GitHubFalso({"/user": [(401, {"message": "Bad credentials"})]})
        sc._peticion_una_vez = tienda
        resultado = sc.check_github_store("HugoCamara7", "catalogo-control-center-data", "tok")
        paso_token = next(p for p in resultado["pasos"] if p["paso"] == "Token")
        self.assertEqual(paso_token["estado"], sc.FALLA)
        self.assertEqual(len([u for u in tienda.llamadas if u.endswith("/user")]), 1)
        self.assertEqual(sc.resumen(resultado)[1], "Almacenamiento sin persistir")

    def test_sin_conexion_tambien_se_reintenta(self):
        tienda = _GitHubFalso({"/user": [(0, {"message": "sin conexion: timeout"})]})
        sc._peticion_una_vez = tienda
        resultado = sc.check_github_store("HugoCamara7", "catalogo-control-center-data", "tok")
        self.assertEqual(len([u for u in tienda.llamadas if u.endswith("/user")]), sc.REINTENTOS)
        self.assertFalse(resultado["persistente"])

    def test_falta_configuracion_sigue_avisando_claro(self):
        resultado = sc.check_github_store("", "", "", "")
        self.assertFalse(resultado["persistente"])
        self.assertEqual(resultado["pasos"][0]["estado"], sc.FALLA)
        self.assertIn("owner", resultado["pasos"][0]["detalle"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
