"""Ningun clic puede quedarse esperando a la red (septiembre 2026).

Por que existe
--------------
Reportado asi: *"cuando hago click dentro de carga completa es muy lenta al
ponerse la pantalla y se queda pegado lo anterior, y pasa en todos los
botones"*.

No estaba roto y no era cache de mas: era **red en el camino de cada rerun**.
Mientras el script corre, Streamlit deja a la vista los elementos de la
ejecucion anterior, atenuados, y solo los poda cuando TERMINA -- eso es el
"se queda pegado lo anterior" (seccion 5 tertrigies). Asi que todo lo que
alargue el rerun se ve exactamente igual que una pantalla colgada.

Lo medido, con el usuario administrador y 250 ms de latencia por peticion, que
es lo que tarda api.github.com desde Streamlit Cloud:

| | antes | ahora |
|---|---:|---:|
| un clic en cualquier pantalla | 4 viajes · 1,03 s | 0 viajes · 0,03 s |
| el clic que cae tras los 25 s de la bandeja | 121 viajes · 4,06 s | 1 viaje · 0,30 s |

Los cuatro viajes fijos eran `check_storage()` -- token, repositorio, rama y
listado --, llamado desde la barra lateral para pintar UNA linea que dice
"Almacenamiento persistente". La barra lateral se dibuja al principio de
`main`, o sea en CADA rerun y en TODAS las pantallas.

Que fija esta prueba
--------------------
Que un rerun NO sale a la red. No lee el codigo: **entra a la app** con un
`urlopen` espia y cuenta los viajes de verdad -- es la leccion de
`start_suelto`, que tenia ocho pruebas leyendo su fuente y ninguna la
ejecutaba, asi que nadie vio que reventaba al llamarla.

La pantalla de Auditoria esta excluida a proposito: ahi el diagnostico de
almacenamiento SI se comprueba de verdad, porque la pregunta de esa pantalla es
"¿esto funciona AHORA?" y esa no se responde con una copia de hace diez
minutos.

Ejecutar:  python scripts/test_reruns_sin_red.py
"""
import io
import json
import sys
import threading
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import streamlit as st  # noqa: E402
from streamlit.testing.v1 import AppTest  # noqa: E402

import engines.audit as audit_mod  # noqa: E402
import engines.storage_check as storage_mod  # noqa: E402
import ticket_system as ticket_mod  # noqa: E402

APP = str(ROOT / "app_matrixify.py")
TIEMPO = 420
ADMIN = "hugo.camara@forus.pe"

TICKETING = {
    "backend": "github",
    "repository": "forus/datos",
    "token": "token-de-prueba",
    "branch": "catalog-tickets",
    "prefix": "catalog_tickets",
}

# Las pantallas del menu, con el valor que escribe cada boton. Auditoria queda
# fuera: ver el docstring.
AREAS = [
    "Inicio",
    "KPIs de catálogo",
    "Status de carga",
    "Carga Supermall",
    "Generador VTEX",
    "Diccionarios",
    "Colecciones",
    "Boost PLP",
    "Input comercial",
    "Solicitudes",
    "Carga de catálogo",
]


# Sin Secrets de Shopify cada pantalla toma su camino de "no configurado". Eso
# es un camino correcto, no un fallo; se distingue por el texto, igual que en
# `test_pantallas_reales`.
# Los hilos que la app lanza a proposito para que la pantalla no espere. Lo
# que hagan NO lo paga el clic.
HILOS_DE_FONDO = {"auditoria", "notificaciones"}

AVISOS_DE_CONFIGURACION = (
    "no esta configurado",
    "no tiene Shopify configurado",
    "no hay credenciales",
    "falta la sección",
    "no tiene Shopify API configurada",
    "BigQuery",
)


def _es_aviso_de_configuracion(texto):
    return any(marca.lower() in texto.lower() for marca in AVISOS_DE_CONFIGURACION)


class _Respuesta(io.BytesIO):
    status = 200

    def __init__(self, data):
        super().__init__(data)
        self.headers = {}

    def getcode(self):
        return 200

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


class GitHubEspia:
    """Sustituye `urlopen` y cuenta cada viaje, con solicitudes plausibles.

    Cuentan los viajes que el clic ESPERA. Quedan fuera los dos hilos que la
    app lanza a proposito para no bloquear la pantalla -- `auditoria` y
    `notificaciones` --: un viaje de esos en el hilo de la pantalla dejaria el
    boton colgado justo al aprobar o finalizar.

    Los del pool de descargas de la bandeja SI cuentan, aunque sean otros
    hilos: el script se queda esperando a que terminen.
    """

    def __init__(self, solicitudes=25):
        self.viajes = []
        self._candado = threading.Lock()
        self.archivos = {}
        for indice in range(solicitudes):
            codigo = "CAT-2026-%06d" % indice
            self.archivos["catalog_tickets/tickets/%s.json" % codigo] = {
                "code": codigo,
                "brand": "Columbia",
                "site_key": "columbia",
                "status": "completed",
                "created_at": "2026-09-01T10:00:00+00:00",
                "requester": "comercial@forus.pe",
                "history": [],
                "products": [],
            }

    def reset(self):
        with self._candado:
            self.viajes = []

    def __call__(self, req, *a, **k):
        import base64
        import hashlib

        url = req.get_full_url() if hasattr(req, "get_full_url") else str(req)
        if threading.current_thread().name not in HILOS_DE_FONDO:
            with self._candado:
                self.viajes.append(url)
        ruta = url.split("/contents/")[-1].split("?")[0] if "/contents/" in url else ""
        if "api.github.com/user" in url:
            cuerpo = {"login": "HugoCamara7"}
        elif "/branches/" in url:
            cuerpo = {"name": "catalog-tickets"}
        elif ruta in self.archivos:
            crudo = json.dumps(self.archivos[ruta]).encode("utf-8")
            cuerpo = {"type": "file", "encoding": "base64",
                      "content": base64.b64encode(crudo).decode("ascii"),
                      "sha": hashlib.sha1(crudo).hexdigest()}
        elif ruta == "catalog_tickets/tickets":
            cuerpo = []
            for camino, doc in self.archivos.items():
                crudo = json.dumps(doc).encode("utf-8")
                cuerpo.append({"type": "file", "name": Path(camino).name, "path": camino,
                               "sha": hashlib.sha1(crudo).hexdigest(), "size": len(crudo)})
        elif "api.github.com/repos/" in url and "/contents/" not in url:
            cuerpo = {"private": True, "permissions": {"push": True, "pull": True}}
        else:
            cuerpo = {}
        return _Respuesta(json.dumps(cuerpo).encode("utf-8"))


class BaseConEspia(unittest.TestCase):
    def setUp(self):
        self.espia = GitHubEspia()
        self._reales = {}
        for modulo in (storage_mod, ticket_mod, audit_mod):
            self._reales[modulo] = getattr(modulo, "urlopen", None)
            modulo.urlopen = self.espia
        ticket_mod.limpiar_cache_bandeja()
        st.cache_data.clear()

    def tearDown(self):
        for modulo, real in self._reales.items():
            if real is not None:
                modulo.urlopen = real
        ticket_mod.limpiar_cache_bandeja()
        st.cache_data.clear()

    def abrir(self, **estado):
        at = AppTest.from_file(APP, default_timeout=TIEMPO)
        at.secrets["ticketing"] = dict(TICKETING)
        at.session_state["authenticated"] = True
        at.session_state["auth_user"] = ADMIN
        for clave, valor in estado.items():
            at.session_state[clave] = valor
        return at

    def sin_fallos(self, at, donde):
        """Lo que NO deberia estar en pantalla.

        Se miran `at.error` ademas de `at.exception` porque `run_app()`
        convierte toda excepcion en `st.error` (regla 4 de CLAUDE.md). Los
        avisos de "no esta configurado" no son fallos: sin Secrets de Shopify
        cada pantalla toma su camino de no configurado, que es el correcto.
        """
        fallos = ["EXCEPCION %s: %s" % (type(e.value).__name__, e.value) for e in at.exception]
        fallos += [str(e.value)[:300] for e in at.error
                   if not _es_aviso_de_configuracion(str(e.value))]
        self.assertEqual(fallos, [], donde)


class TestUnClicNoEsperaALaRed(BaseConEspia):
    def test_ninguna_pantalla_sale_a_la_red_al_redibujarse(self):
        for area in AREAS:
            with self.subTest(area=area):
                self.espia.reset()
                at = self.abrir(operation_area_choice=area,
                                operation_mode_choice="Carga completa")
                at.run()
                self.sin_fallos(at, area)
                self.espia.reset()
                at.run()
                self.sin_fallos(at, area)
                self.assertEqual(
                    self.espia.viajes, [],
                    "%s hace %d viajes de red por rerun: %s"
                    % (area, len(self.espia.viajes), self.espia.viajes[:4]),
                )

    def test_la_barra_lateral_no_comprueba_el_almacenamiento_en_cada_clic(self):
        """Cuatro peticiones para pintar una linea, en todas las pantallas."""
        at = self.abrir(operation_area_choice="Inicio")
        at.run()
        self.espia.reset()
        at.run()
        comprobaciones = [u for u in self.espia.viajes if u.endswith("api.github.com/user")]
        self.assertEqual(comprobaciones, [],
                         "check_storage vuelve a salir a la red en cada rerun")

    def test_las_dos_cargas_son_las_pantallas_del_reporte(self):
        """Carga completa y Carga parcial, que es donde se reporto."""
        for modo in ("Carga completa", "Carga parcial"):
            with self.subTest(modo=modo):
                at = self.abrir(operation_area_choice="Carga de catálogo",
                                operation_mode_choice=modo)
                at.run()
                self.espia.reset()
                at.run()
                self.sin_fallos(at, modo)
                self.assertEqual(self.espia.viajes, [])


class TestLaBandejaSoloBajaLoQueCambio(BaseConEspia):
    def test_refrescar_la_bandeja_es_un_viaje_y_no_uno_por_solicitud(self):
        at = self.abrir(operation_area_choice="Solicitudes")
        at.run()
        self.sin_fallos(at, "Solicitudes")
        # La primera vez se bajan todas: 25 solicitudes + el listado.
        self.assertGreaterEqual(len(self.espia.viajes), 26)
        # Caduca el TTL de la lista, pero el contenido por sha sigue valiendo.
        with ticket_mod._BANDEJA_CACHE_LOCK:
            ticket_mod._BANDEJA_CACHE.clear()
        self.espia.reset()
        at.run()
        self.sin_fallos(at, "Solicitudes")
        self.assertEqual(
            len(self.espia.viajes), 1,
            "al refrescar volvio a bajar solicitudes que no habian cambiado: %d viajes"
            % len(self.espia.viajes),
        )
        self.assertIn("/contents/catalog_tickets/tickets?", self.espia.viajes[0],
                      "el unico viaje tiene que ser el listado del directorio")


class TestAuditoriaSiComprueba(BaseConEspia):
    def test_auditoria_comprueba_el_almacenamiento_de_verdad(self):
        """La unica pantalla donde la pregunta es '¿funciona AHORA?'."""
        at = self.abrir(operation_area_choice="Auditoria")
        at.run()
        self.sin_fallos(at, "Auditoria")
        self.assertTrue(
            [u for u in self.espia.viajes if u.endswith("api.github.com/user")],
            "Auditoria ya no comprueba el almacenamiento de verdad",
        )


if __name__ == "__main__":
    unittest.main(verbosity=2)
