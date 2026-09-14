"""La arquitectura de navegacion (septiembre 2026).

El menu tenia TRECE botones al mismo nivel, mezclando mirar KPIs, ejecutar una
carga, consultar un diccionario y revisar la auditoria. Ahora son seis grupos y
solo se despliega uno.

Lo que estas pruebas protegen no es el aspecto: es el **contrato de routing**.
`operation_area_choice` y `operation_mode_choice` los escribe codigo que vive
FUERA del menu -- `ir_a_carga_completa`, el atajo de "Aceptar carga", el boton
de Supermall --, asi que un valor que cambie deja a esos atajos apuntando a una
pantalla que no existe, **en silencio**.

Las pruebas EJECUTAN: entran a la app y pulsan. Es la leccion de `start_suelto`
-- leer el codigo no es ejecutarlo.

Ejecutar:  python scripts/test_navegacion.py
"""
import sys
import unittest
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
if str(RAIZ) not in sys.path:
    sys.path.insert(0, str(RAIZ))

from streamlit.testing.v1 import AppTest  # noqa: E402
import app_matrixify as app  # noqa: E402

APP = str(RAIZ / "app_matrixify.py")
TIEMPO = 420

AVISOS_DE_CONFIGURACION = (
    "no tiene Shopify configurado", "no tiene Shopify API configurada",
    "falta la sección", "no hay credenciales", "BigQuery", "no esta configurado",
)


def abrir(**estado):
    at = AppTest.from_file(APP, default_timeout=TIEMPO)
    at.session_state["authenticated"] = True
    at.session_state["auth_user"] = "hugo"
    for clave, valor in estado.items():
        at.session_state[clave] = valor
    at.run()
    return at


def problemas(at):
    """`at.error` ademas de `at.exception`: `run_app()` convierte toda excepcion
    en `st.error` (regla 4 de CLAUDE.md)."""
    fallos = [f"EXCEPCION {type(e.value).__name__}: {e.value}"[:400] for e in at.exception]
    fallos += [str(e.value)[:400] for e in at.error
               if not any(m.lower() in str(e.value).lower() for m in AVISOS_DE_CONFIGURACION)]
    return fallos


class TestElContratoDeRouting(unittest.TestCase):
    """Lo que NO puede cambiar aunque el menu se reorganice entero."""

    def test_las_areas_que_otras_pantallas_escriben_siguen_existiendo(self):
        """`ir_a_carga_completa` y los atajos escriben estos valores a mano. Si
        el menu deja de tenerlos, el atajo lleva a una pantalla que no existe y
        nadie se entera hasta que alguien lo pulsa."""
        areas = set(app.nav_areas(puede_auditar=True))
        for area in ("Carga de catálogo", "KPIs de catálogo", app.SUPERMALL_LABEL,
                     "Solicitudes", "Input comercial"):
            with self.subTest(area=area):
                self.assertIn(area, areas)

    def test_los_dos_modos_de_carga_conservan_su_valor(self):
        modos = {item["modo"] for grupo in app.nav_grupos(True)
                 for item in grupo["items"] if item["modo"]}
        self.assertEqual(modos, {"Carga completa", "Carga parcial"})

    def test_cada_area_del_menu_tiene_despacho_en_main(self):
        """Un destino sin despacho cae al final de `main` y dibuja la pantalla
        de carga: el boton parece funcionar y lleva a otro sitio."""
        fuente = (RAIZ / "app_matrixify.py").read_text(encoding="utf-8")
        cuerpo = fuente[fuente.index("\ndef main("):]
        for area in app.nav_areas(puede_auditar=True):
            if area == "Carga de catálogo":
                continue  # es el final de `main`, no lleva `if`
            with self.subTest(area=area):
                literal = f'operation_area == "{area}"'
                constante = area in (app.STATUS_CARGA_LABEL, app.SUPERMALL_LABEL,
                                     app.DICCIONARIOS_LABEL, app.COLECCIONES_LABEL,
                                     app.BOOST_LABEL, app.NAV_INICIO_LABEL)
                self.assertTrue(literal in cuerpo or constante,
                                f"{area!r} no tiene rama en main()")

    def test_auditoria_solo_para_quien_puede_verla(self):
        self.assertNotIn("Auditoria", app.nav_areas(puede_auditar=False))
        self.assertIn("Auditoria", app.nav_areas(puede_auditar=True))


class TestLosGrupos(unittest.TestCase):
    def test_ningun_item_queda_fuera_de_un_grupo(self):
        for grupo in app.nav_grupos(True):
            with self.subTest(grupo=grupo["clave"]):
                self.assertTrue(grupo["items"], f"{grupo['clave']} no tiene items")
                self.assertTrue(grupo["etiqueta"])

    def test_no_hay_dos_botones_con_la_misma_clave(self):
        """Dos botones con la misma key rompen Streamlit con
        `StreamlitDuplicateElementKey` y cortan la pantalla entera."""
        claves = [item["boton"] for grupo in app.nav_grupos(True) for item in grupo["items"]]
        self.assertEqual(len(claves), len(set(claves)), f"claves repetidas: {claves}")

    def test_se_ven_MENOS_botones_que_antes(self):
        """La razon de ser del cambio. Antes eran 13 al mismo nivel."""
        grupos = app.nav_grupos(True)
        # Cabeceras + los items del grupo mas grande: lo maximo en pantalla.
        mayor = max(len(g["items"]) for g in grupos)
        self.assertLessEqual(len(grupos) + mayor, 10)

    def test_carga_completa_y_parcial_van_a_la_MISMA_area(self):
        """Y por eso su resaltado no puede salir de comparar el area: con la
        regla simple, una de las dos salia activa siempre, incluso en KPIs."""
        cargas = [g for g in app.nav_grupos(True) if g["clave"] == "cargas"][0]
        completa = [i for i in cargas["items"] if i["modo"] == "Carga completa"][0]
        parcial = [i for i in cargas["items"] if i["modo"] == "Carga parcial"][0]
        self.assertEqual(completa["area"], parcial["area"])


class TestLasMigasDePan(unittest.TestCase):
    def test_dicen_el_grupo_y_la_pantalla(self):
        self.assertEqual(app.nav_ruta(app.BOOST_LABEL, ""),
                         ["Merchandising", app.BOOST_LABEL])
        self.assertEqual(app.nav_ruta("Carga de catálogo", "Carga parcial"),
                         ["Cargas", "Carga parcial"])
        self.assertEqual(app.nav_ruta("Carga de catálogo", "Carga completa"),
                         ["Cargas", "Carga completa"])

    def test_inicio_no_lleva_migas(self):
        """Una miga de un solo nivel no dice nada que el titulo no diga."""
        self.assertEqual(len(app.nav_ruta(app.NAV_INICIO_LABEL, "")), 1)

    def test_un_area_desconocida_no_revienta(self):
        self.assertEqual(app.nav_ruta("Pantalla inventada", ""), [])
        self.assertEqual(app.nav_ruta("", ""), [])


class TestLaAppSeDIBUJA(unittest.TestCase):
    """Entrar de verdad, que es donde este repositorio se llevo sus fallos."""

    def test_inicio_es_el_destino_por_defecto(self):
        """Antes abria en KPIs, que LEE el catalogo entero de Shopify: entrar a
        mirar una solicitud costaba minutos de espera."""
        at = abrir()
        self.assertEqual(at.session_state["operation_area_choice"], app.NAV_INICIO_LABEL)
        self.assertEqual(problemas(at), [])

    def test_inicio_no_lee_el_catalogo(self):
        """La razon de que exista. Si llamara a `fetch_products`, abrir la app
        volveria a costar lo mismo que antes."""
        llamadas = []
        original = app.leer_catalogo_del_sitio
        app.leer_catalogo_del_sitio = lambda *a, **k: llamadas.append(1) or []
        try:
            abrir(operation_area_choice=app.NAV_INICIO_LABEL)
        finally:
            app.leer_catalogo_del_sitio = original
        self.assertEqual(llamadas, [], "Inicio salio a leer el catalogo")

    def test_cada_grupo_se_puede_abrir_sin_cambiar_de_pantalla(self):
        """Explorar el menu no puede perder lo que estabas haciendo."""
        for grupo in app.nav_grupos(True):
            if grupo["clave"] == "inicio":
                continue
            with self.subTest(grupo=grupo["clave"]):
                at = abrir(operation_area_choice=app.NAV_INICIO_LABEL,
                           nav_grupo_abierto=grupo["clave"])
                self.assertEqual(at.session_state["operation_area_choice"],
                                 app.NAV_INICIO_LABEL)
                self.assertEqual(problemas(at), [])

    def test_el_grupo_abierto_SIGUE_a_la_pantalla(self):
        """Llegar por un atajo tiene que dejar el menu marcado donde estas, no
        donde lo dejaste."""
        at = abrir(operation_area_choice=app.BOOST_LABEL)
        # `at.session_state` no tiene `.get()`: se accede por clave.
        self.assertEqual(at.session_state["nav_grupo_abierto"], "merchandising")

    def test_todas_las_areas_se_dibujan(self):
        for area in app.nav_areas(puede_auditar=True):
            with self.subTest(area=area):
                at = abrir(operation_area_choice=area)
                self.assertEqual(problemas(at), [], f"{area!r} no se dibuja")


class TestCargaParcialAgrupada(unittest.TestCase):
    def test_las_catorce_opciones_siguen_estando(self):
        """Agrupar no puede PERDER una opcion: son catorce operaciones que
        alguien usa."""
        at = abrir(operation_area_choice="Carga de catálogo",
                   operation_mode_choice="Carga parcial")
        menu = [s for s in at.selectbox if s.label == "Que quieres actualizar"][0]
        self.assertEqual(len(list(menu.options)), 14)

    def test_las_que_NO_escriben_en_shopify_estan_separadas(self):
        """Centry y Carga Sial producen un Excel. Es la diferencia mas
        importante de esta pantalla y era la unica que no se veia."""
        at = abrir(operation_area_choice="Carga de catálogo",
                   operation_mode_choice="Carga parcial")
        menu = [s for s in at.selectbox if s.label == "Que quieres actualizar"][0]
        etiquetas = [str(o) for o in menu.options]
        excel = [e for e in etiquetas if "no escribe en Shopify" in e]
        self.assertEqual(len(excel), 2, f"esperaba Centry y Carga Sial, salio {excel}")


if __name__ == "__main__":
    unittest.main(verbosity=2)
