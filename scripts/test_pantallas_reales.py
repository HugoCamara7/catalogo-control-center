"""Cada pantalla se DIBUJA de verdad, no solo su motor (septiembre 2026).

Por que existe
--------------
Las ~1.800 pruebas del repo cubren los motores. Los fallos que llegan a
produccion viven en el **pegamento** con la pantalla, y ninguna los veia:

- `render_status_de_carga` pedia `kpis["Marcas con catálogo"]` con tilde y era
  un `KeyError` que tumbaba la pantalla entera (seccion 5 quater).
- Tres fallos dejaron el Mantenedor de Tallas sin efecto y **ninguna de sus 34
  pruebas los atrapo**, porque todas prueban el motor (seccion 5 sexdecies).

Esta prueba entra a la app -- `authenticated` en `session_state`, sin
credenciales -- y **recorre cada pantalla del menu** comprobando `at.error`
ademas de `at.exception`, que es la regla 4 de CLAUDE.md: `run_app()` convierte
toda excepcion en `st.error`, asi que mirar solo `at.exception` dice "sin
excepciones" con la app rota.

No sale a la red: sin Secrets de Shopify cada pantalla toma su camino de
"sitio no configurado", que es tambien un camino que hay que probar.

Ejecutar:  python scripts/test_pantallas_reales.py
"""
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from streamlit.testing.v1 import AppTest  # noqa: E402

APP = str(ROOT / "app_matrixify.py")
TIEMPO = 420

# Las pantallas del menu principal, con el valor que escribe cada boton.
AREAS = [
    "KPIs de catálogo",
    "Status de carga",
    "Carga Supermall",
    "Diccionarios",
    "Input comercial",
    "Solicitudes",
    "Auditoria",
    "Carga de catálogo",
]
MODOS = ["Carga completa", "Carga parcial"]


def abrir(**estado):
    """La app ya dentro, con el estado que pida la prueba."""
    at = AppTest.from_file(APP, default_timeout=TIEMPO)
    at.session_state["authenticated"] = True
    at.session_state["auth_user"] = "hugo"
    for clave, valor in estado.items():
        at.session_state[clave] = valor
    at.run()
    return at


# Sin Secrets, cada pantalla toma su camino de "no configurado" y lo DICE con
# un `st.error`. Eso es el comportamiento correcto, no un fallo: la app no
# puede inventarse un catalogo. Lo que no puede haber es ninguna otra cosa.
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


def problemas(at):
    """Lo que NO deberia estar en pantalla.

    Se miran `at.error` ademas de `at.exception` porque `run_app()` convierte
    toda excepcion en `st.error`: mirando solo `at.exception` la prueba diria
    "sin excepciones" con la app rota. Es la regla 4 de CLAUDE.md.
    """
    fallos = [f"EXCEPCION {type(e.value).__name__}: {e.value}"[:400] for e in at.exception]
    fallos += [str(e.value)[:400] for e in at.error
               if not _es_aviso_de_configuracion(str(e.value))]
    return fallos


class TestTodasLasPantallasSeDibujan(unittest.TestCase):
    def test_el_login_no_revienta(self):
        at = AppTest.from_file(APP, default_timeout=TIEMPO)
        at.run()
        self.assertEqual(problemas(at), [])

    def test_la_app_entra(self):
        at = abrir()
        self.assertEqual(problemas(at), [])

    def test_cada_area_del_menu(self):
        for area in AREAS:
            with self.subTest(area=area):
                at = abrir(operation_area_choice=area)
                self.assertEqual(problemas(at), [], f"la pantalla {area!r} no se dibuja")

    def test_los_dos_modos_de_carga(self):
        for modo in MODOS:
            with self.subTest(modo=modo):
                at = abrir(operation_area_choice="Carga de catálogo",
                           operation_mode_choice=modo)
                self.assertEqual(problemas(at), [], f"el modo {modo!r} no se dibuja")

    def test_cada_opcion_de_carga_parcial(self):
        """Las opciones de Carga parcial son pantallas enteras: Centry, Carga
        Sial, Mantenedor de Fotos, de Videos y de Tallas."""
        at = abrir(operation_area_choice="Carga de catálogo",
                   operation_mode_choice="Carga parcial")
        radios = [r for r in at.radio]
        opciones = []
        for radio in radios:
            opciones = list(getattr(radio, "options", []) or [])
            if len(opciones) > 2:
                break
        self.assertTrue(opciones, "no se encontro el selector de Carga parcial")
        for opcion in opciones:
            with self.subTest(opcion=opcion):
                at = abrir(operation_area_choice="Carga de catálogo",
                           operation_mode_choice="Carga parcial")
                for radio in at.radio:
                    if opcion in list(getattr(radio, "options", []) or []):
                        radio.set_value(opcion).run()
                        break
                self.assertEqual(problemas(at), [], f"la opcion {opcion!r} no se dibuja")

    def test_cada_sitio_activo(self):
        """Un sitio sin Shopify en Secrets tiene que tomar su camino de
        "no configurado", no reventar."""
        import app_matrixify as app
        for site_key, config in app.SITE_CONFIGS.items():
            with self.subTest(sitio=site_key):
                at = abrir(operation_area_choice="KPIs de catálogo",
                           site_picker=config.get("site_label"))
                self.assertEqual(problemas(at), [], f"el sitio {site_key!r} no se dibuja")


class TestLosBotonesSeDibujanYSonPulsables(unittest.TestCase):
    """Un boton que se dibuja y no se puede pulsar es peor que no tenerlo."""

    def test_sin_input_dice_EXACTAMENTE_que_falta(self):
        """Sin input el boton de Analizar no se dibuja -- correcto --, pero
        entonces la pantalla tiene que decir por que. El aviso era el mismo en
        los dos casos, asi que quien ya habia cargado el input leia que le
        faltaba lo que si tenia."""
        at = abrir(operation_area_choice="Carga de catálogo",
                   operation_mode_choice="Carga completa")
        etiquetas = [b.label for b in at.button]
        self.assertFalse(any("Analizar input" in e for e in etiquetas),
                         "sin input no deberia haber boton de analizar")
        avisos = " ".join(str(i.value) for i in at.info)
        self.assertIn("falta", avisos.lower(),
                      f"la pantalla no explica por que no se puede analizar: {avisos[:300]}")
        self.assertIn("input comercial", avisos.lower())

    NAVEGACION = {
        "Cerrar sesion", "KPIs de catálogo", "Status de carga", "Carga Supermall",
        "Diccionarios", "Input comercial", "Solicitudes", "Carga completa",
        "Carga parcial", "Auditoria",
    }

    def test_TODOS_los_botones_de_accion_se_pulsan_sin_reventar(self):
        """Pulsarlos sin datos cargados es el caso mas comun -- y el que se
        reporta como "no ejecuta". Tienen que avisar, no levantar."""
        pulsados = 0
        for area in AREAS:
            at = abrir(operation_area_choice=area)
            etiquetas = [b.label for b in at.button if b.label not in self.NAVEGACION]
            for etiqueta in etiquetas:
                with self.subTest(area=area, boton=etiqueta):
                    at = abrir(operation_area_choice=area)
                    for boton in at.button:
                        if boton.label == etiqueta:
                            boton.click().run()
                            break
                    self.assertEqual(
                        [f"{type(e.value).__name__}: {e.value}"[:300]
                         for e in at.exception], [],
                        f"{etiqueta!r} en {area!r} levanta una excepcion",
                    )
                    pulsados += 1
        self.assertTrue(pulsados, "no se pulso ningun boton")

    def test_ningun_boton_queda_sin_etiqueta(self):
        """Un boton sin texto se dibuja y nadie sabe que hace."""
        for area in AREAS:
            with self.subTest(area=area):
                at = abrir(operation_area_choice=area)
                vacios = [b.key for b in at.button if not str(b.label).strip()]
                self.assertEqual(vacios, [], f"botones sin etiqueta en {area!r}")

    def test_ningun_boton_se_repite_en_la_misma_pantalla(self):
        """Dos botones con la misma clave cortan la pantalla con
        `StreamlitDuplicateElementKey`."""
        for area in AREAS:
            with self.subTest(area=area):
                at = abrir(operation_area_choice=area)
                claves = [b.key for b in at.button if b.key]
                self.assertEqual(len(claves), len(set(claves)),
                                 f"claves repetidas en {area!r}")


if __name__ == "__main__":
    unittest.main(verbosity=2)
