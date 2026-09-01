"""Pruebas del CSS responsive y del f-string que lo contiene.

Dos cosas distintas se protegen aqui.

1. **El f-string.** `inject_custom_css` es un f-string: toda llave del CSS va
   doblada. Con llaves simples, Python interpreta `{padding:10px}` como una
   interpolacion y la app revienta con `NameError: name 'padding' is not
   defined`. Esta prueba falla si aparece cualquier interpolacion que no sea
   una de las cinco legitimas.

2. **Los cortes de movil.** Las 13 media queries que ya existian paran en
   900-1100px, que es tablet. En un telefono las rejillas de 4 y 6 columnas
   dejaban tarjetas de 60px. Si alguien borra el bloque de movil, esto avisa.

Ejecutar:  python scripts/test_css_movil.py
"""
import ast
import io
import re
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

FUENTE = io.open(ROOT / "app_matrixify.py", encoding="utf-8-sig").read()

# Las unicas interpolaciones legitimas del CSS. Cualquier otra significa una
# llave de CSS sin doblar.
INTERPOLACIONES_PERMITIDAS = {
    "config['primary_color']",
    "config['accent_color']",
    "site_logo_css",
    "site_logo_src",
    "site_label_css",
}


def _fuente_de(nombre):
    for nodo in ast.walk(ast.parse(FUENTE)):
        if isinstance(nodo, ast.FunctionDef) and nodo.name == nombre:
            return ast.get_source_segment(FUENTE, nodo)
    raise AssertionError(f"No existe la funcion {nombre}")


CSS = _fuente_de("inject_custom_css")


class TestFStringDelCss(unittest.TestCase):
    def test_solo_las_cinco_interpolaciones_legitimas(self):
        campos = set()
        for nodo in ast.walk(ast.parse(CSS.replace("def inject_custom_css", "def _x", 1))):
            if isinstance(nodo, ast.JoinedStr):
                for parte in nodo.values:
                    if isinstance(parte, ast.FormattedValue):
                        campos.add(ast.unparse(parte.value))
        sobrantes = campos - INTERPOLACIONES_PERMITIDAS
        self.assertEqual(sobrantes, set(), f"Llaves de CSS sin doblar: {sorted(sobrantes)}")

    def test_la_funcion_se_puede_ejecutar(self):
        # La prueba de arriba mira el arbol; esta ejecuta de verdad el
        # f-string, que es donde saltaria el NameError.
        import app_matrixify as app

        app.inject_custom_css(app.get_site_config(app.get_brand_config()))


class TestCortesDeMovil(unittest.TestCase):
    def test_existen_los_dos_cortes(self):
        self.assertIn("max-width:640px", CSS, "Falta el corte de telefono/tablet vertical")
        self.assertIn("max-width:430px", CSS, "Falta el corte de telefono angosto")

    def test_las_rejillas_grandes_se_reducen_en_movil(self):
        """Cada rejilla se comprueba en la hoja que la gobierna, no en las dos.

        Las `.ticket-*` viven en `render_ticket_styles`; tenerlas tambien aqui
        era el error que dejaba los KPI de la bandeja en dos columnas.
        """
        movil = CSS[CSS.index("max-width:640px"):]
        for clase in ("kpi-card-grid", "partial-kpi-grid", "metric-grid",
                      "commercial-status-grid", "brand-request-kpis"):
            self.assertIn(clase, movil, f"{clase} no se reduce en movil")

        ticket = _fuente_de("render_ticket_styles")
        ticket_movil = ticket[ticket.index("max-width:640px"):]
        for clase in ("ticket-kpi-grid", "ticket-request-grid",
                      "ticket-summary", "ticket-workspace"):
            self.assertIn(clase, ticket_movil, f"{clase} no se reduce en movil")

    def test_las_columnas_de_streamlit_se_apilan(self):
        movil = CSS[CSS.index("max-width:640px"):]
        self.assertIn("stHorizontalBlock", movil)
        self.assertIn("flex-wrap:wrap", movil)

    def test_objetivo_tactil_de_44px(self):
        # 44px es el minimo de Apple y de Google. Debajo de eso el dedo falla.
        movil = CSS[CSS.index("max-width:640px"):]
        self.assertIn("min-height:44px", movil)

    def test_la_altura_fija_de_la_tarjeta_se_pisa(self):
        # `.kpi-card` trae `height:96px` FIJO. Pisar solo `min-height` no hace
        # nada: la tarjeta sigue midiendo 96px y ocho de esas son 800px de
        # scroll antes de llegar a algo que se pueda tocar.
        self.assertIn("height:96px", CSS, "Cambio la tarjeta; revisa el bloque de movil")
        movil = CSS[CSS.index("max-width:640px"):]
        self.assertIn("height:auto !important", movil)

    def test_las_pestanas_ruedan_en_vez_de_cortarse(self):
        movil = CSS[CSS.index("max-width:640px"):]
        self.assertIn("overflow-x:auto", movil)

    def test_el_campo_de_texto_no_hace_zoom_en_ios(self):
        # Safari hace zoom automatico si la fuente del input baja de 16px.
        movil = CSS[CSS.index("max-width:640px"):]
        self.assertIn("font-size:16px !important", movil)


class TestLoginEnMovil(unittest.TestCase):
    """El login tiene su PROPIO bloque de CSS.

    `require_login()` llama a `render_login_styles()` y nunca a
    `inject_custom_css`, asi que las reglas de movil de alla no le llegan. Por
    eso el boton Ingresar se quedaba en 74x40. Entrar es lo primero que alguien
    hace desde el telefono: si eso falla, no importa el resto de la app.
    """

    def setUp(self):
        self.login = _fuente_de("render_login_styles")

    def test_el_login_no_pasa_por_inject_custom_css(self):
        # Si algun dia pasara, este archivo sobra. Mientras tanto, es la razon
        # de que el bloque de movil este duplicado.
        requiere = _fuente_de("require_login")
        self.assertIn("render_login_styles()", requiere)
        self.assertNotIn("inject_custom_css", requiere)

    def test_tiene_sus_propios_cortes_de_movil(self):
        self.assertIn("max-width: 560px", self.login)
        self.assertIn("max-width: 430px", self.login)

    def test_el_boton_de_ingresar_toma_el_ancho(self):
        movil = self.login[self.login.index("max-width: 560px"):]
        # No basta con el boton: quien limita el ancho es el contenedor de
        # elemento de Streamlit, que mide lo que el texto.
        self.assertIn("stElementContainer", movil)
        self.assertIn("stBaseButton-primaryFormSubmit", movil)
        self.assertIn("width:100% !important", movil)

    def test_objetivo_tactil_en_el_login(self):
        movil = self.login[self.login.index("max-width: 560px"):]
        self.assertIn("min-height:46px !important", movil)

    def test_el_campo_del_login_no_hace_zoom_en_ios(self):
        movil = self.login[self.login.index("max-width: 560px"):]
        self.assertIn("font-size:16px !important", movil)


class TestBandejaDeSolicitudesEnMovil(unittest.TestCase):
    """La pantalla mas pesada de la app, medida en un telefono de 390px.

    Antes de esto la primera solicitud empezaba en y=1138px: 1,3 pantallas de
    scroll antes de ver nada util. Nada estaba roto, simplemente no se podia
    trabajar. Quedo en y=724px, dentro de la primera pantalla.
    """

    def setUp(self):
        self.ticket = _fuente_de("render_ticket_styles")

    def test_la_hoja_de_solicitudes_tiene_su_propio_bloque_movil(self):
        self.assertIn("max-width:640px", self.ticket)
        self.assertIn("max-width:430px", self.ticket)

    def test_las_clases_ticket_las_gobierna_una_sola_hoja(self):
        # Estaban en las DOS hojas. La de `inject_custom_css` ganaba por
        # `!important` y dejaba los KPI de la bandeja en dos columnas cuando la
        # hoja de Solicitudes pedia tres. Dos hojas peleando por la misma clase
        # no se ve hasta que alguien mide el DOM.
        movil = CSS[CSS.index("================= MOVIL"):]
        for clase in (".ticket-kpi-grid", ".ticket-result-grid", ".ticket-summary",
                      ".ticket-request-grid", ".ticket-stepper", ".ticket-workspace"):
            self.assertNotIn(clase, movil,
                             f"{clase} volvio a inject_custom_css; la gobierna render_ticket_styles")

    def test_los_kpi_de_la_bandeja_van_de_a_tres(self):
        movil = self.ticket[self.ticket.index("max-width:640px"):]
        self.assertIn(".ticket-kpi-grid{grid-template-columns:repeat(3", movil)

    def test_la_cabecera_no_deja_hueco_muerto(self):
        # Streamlit le pone su propio padding a los h1 de markdown (~36px
        # arriba y abajo). Sin anularlo, el hueco era mas alto que el titulo.
        movil = self.ticket[self.ticket.index("max-width:640px"):]
        self.assertIn(".ticket-hero h1", movil)
        self.assertIn("padding:0", movil)

    def test_las_columnas_anidadas_toman_la_fila_entera(self):
        # La fila exterior partia la pantalla en dos y los cinco filtros de
        # adentro quedaban en 181px: uno por fila, con la mitad vacia al lado.
        movil = CSS[CSS.index("max-width:640px"):]
        self.assertIn('[data-testid="stColumn"]:has([data-testid="stHorizontalBlock"])', movil)
        self.assertIn("flex-basis:100% !important", movil)

    def test_las_columnas_angostas_comparten_fila(self):
        movil = CSS[CSS.index("max-width:640px"):]
        self.assertIn("calc(50% - 4px)", movil)
        self.assertIn("min-width:150px", movil)


class TestNoSeRompioEscritorio(unittest.TestCase):
    def test_los_cortes_de_movil_van_dentro_de_media_queries(self):
        # Todo lo nuevo tiene que estar dentro de un @media: una regla suelta
        # con !important se llevaria por delante el escritorio.
        bloque = CSS[CSS.index("================= MOVIL"):]
        fuera = re.sub(r"@media[^{]*\{\{.*?\}\}\s*\}\}", "", bloque, flags=re.S)
        self.assertNotIn("!important", fuera,
                         "Hay reglas de movil fuera de un @media: pisarian el escritorio")


if __name__ == "__main__":
    unittest.main(verbosity=2)
