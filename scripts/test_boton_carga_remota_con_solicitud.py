"""El boton al runner no puede desaparecer sin decir nada.

Ejecutar:  python scripts/test_boton_carga_remota_con_solicitud.py

Reportado con una captura de Carga completa: *"el problema es que no puedo
ejecutar un git hub actions"*. El workflow funcionaba -- 17 ejecuciones, la
ultima el mismo dia -- y `[carga_remota]` estaba configurado (el aviso verde
"La carga sigue aunque cierres la sesion" lo prueba). Lo que faltaba era por
donde lanzarlo.

`render_boton_carga_remota` hacia un `return` **silencioso** en cuanto la carga
salia de una solicitud, con el argumento de que ese camino es "Ejecutar carga"
de la barra de acciones. El argumento vale mientras la solicitud OFREZCA esa
accion, y deja de valer en cuanto no:

    load_approved / ready_execute / dry_run  ->  ['ejecutar', ...]
    loading / validating_results             ->  ['finalizar', 'sial_ok']

O sea que una solicitud que ya paso a "En ejecucion" -- que es lo que hace el
propio "Ejecutar carga" -- se queda **sin ninguna forma de mandar la carga al
runner**: la pantalla solo ofrece el panel local, que se detiene al cerrar la
pestana. Pasa cuando el primer disparo fallo, y cuando se vuelve a analizar el
input y la carga nueva trae mas productos que la ya lanzada -- que es
exactamente el caso: 78 productos antes del arreglo de las medias, 178 despues.

Ahora: si la solicitud puede ejecutar, se DICE donde esta el boton; si no
puede, se dibuja el boton. Ante cualquier duda se dibuja -- un boton de mas se
ve y se ignora; el que falta se lee como "no funciona".

Las pruebas EJECUTAN la funcion con un Streamlit y un servicio de solicitudes
falsos: es la leccion de `start_suelto`, que tenia ocho pruebas leyendo su
fuente y ninguna la llamaba.
"""
import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import app_matrixify as app  # noqa: E402
import engines.ticket_flow as flujo  # noqa: E402

CONFIG = {"site_key": "rockford", "label": "Rockford"}


class PantallaFalsa:
    """Recoge lo que la funcion dibuja, sin Streamlit."""

    def __init__(self):
        self.infos, self.warnings, self.captions = [], [], []
        self.markdowns, self.botones = [], []

    def info(self, texto, **kw):
        self.infos.append(str(texto))

    def warning(self, texto, **kw):
        self.warnings.append(str(texto))

    def caption(self, texto, **kw):
        self.captions.append(str(texto))

    def markdown(self, texto, **kw):
        self.markdowns.append(str(texto))

    def button(self, etiqueta, **kw):
        self.botones.append(str(etiqueta))
        return False

    @property
    def texto(self):
        return " ".join(self.infos + self.warnings + self.captions + self.markdowns)


def dibujar(estado_solicitud, codigo="CAT-2026-000036", sobrevive=True,
            ticket_falla=False, sin_ticket=False):
    """Ejecuta `render_boton_carga_remota` y devuelve lo que dibujo."""
    pantalla = PantallaFalsa()
    sesion = {
        app.CLAVE_MATRIXIFY_SESION: {
            "codigo": codigo, "site_key": "rockford",
            "product_keys": ["A-1", "B-2", "C-3"],
            "excel_path": "/tmp/x.xlsx",
        },
    }

    ticket = None if sin_ticket else {
        "code": codigo, "status": estado_solicitud, "assignee": "hugo",
    }

    def ticket_para_pantalla(_servicio, _actor, _codigo):
        if ticket_falla:
            raise RuntimeError("GitHub no responde")
        return ticket

    with mock.patch.object(app, "st") as st_falso, \
            mock.patch.object(app, "estado_carga_remota",
                              return_value={"sobrevive": sobrevive, "faltan": []}), \
            mock.patch.object(app, "current_ticket_actor",
                              return_value={"role": "operator", "user": "hugo"}), \
            mock.patch.object(app, "get_ticket_service", return_value=(object(), None)), \
            mock.patch.object(app, "ticket_para_pantalla", side_effect=ticket_para_pantalla), \
            mock.patch.object(app, "render_aviso_carga_remota"):
        st_falso.session_state = sesion
        st_falso.info = pantalla.info
        st_falso.warning = pantalla.warning
        st_falso.caption = pantalla.caption
        st_falso.markdown = pantalla.markdown
        st_falso.button = pantalla.button
        app.render_boton_carga_remota(CONFIG)
    return pantalla


class CuandoLaSolicitudPuedeEjecutar(unittest.TestCase):
    """El boton sobra, pero hay que decir donde esta el que sirve."""

    ESTADOS = ("load_approved", "ready_execute", "dry_run")

    def test_no_se_dibuja_el_boton(self):
        for estado in self.ESTADOS:
            with self.subTest(estado=estado):
                self.assertEqual(dibujar(estado).botones, [])

    def test_pero_se_dice_donde_esta(self):
        """El `return` mudo dejaba la pantalla con solo el panel local."""
        for estado in self.ESTADOS:
            with self.subTest(estado=estado):
                pantalla = dibujar(estado)
                self.assertTrue(pantalla.infos, f"{estado}: no dice nada")
                self.assertIn("Ejecutar carga", pantalla.texto)
                self.assertIn("CAT-2026-000036", pantalla.texto)


class CuandoLaSolicitudYaNoPuede(unittest.TestCase):
    """Aqui el boton es la UNICA salida: sin el no hay forma de lanzar nada."""

    ESTADOS = ("loading", "validating_results", "sial_loaded")

    def test_el_boton_se_dibuja(self):
        for estado in self.ESTADOS:
            with self.subTest(estado=estado):
                pantalla = dibujar(estado)
                self.assertEqual(pantalla.botones, ["Ejecutar carga en GitHub Actions"],
                                 f"{estado}: sin boton no hay forma de lanzar el runner")

    def test_dice_por_que_aparece_y_que_no_mueve_el_estado(self):
        pantalla = dibujar("loading")
        self.assertIn("CAT-2026-000036", pantalla.texto)
        self.assertIn("no cambia de estado", pantalla.texto)

    def test_dice_cuantos_productos_van(self):
        self.assertIn("3 productos", dibujar("loading").texto)

    def test_esos_estados_de_verdad_no_ofrecen_ejecutar(self):
        """Si el flujo cambiara, esta prueba estaria midiendo otra cosa."""
        for estado in self.ESTADOS:
            claves = {a["clave"] for a in flujo.acciones_disponibles(estado, "operator", "hugo", "hugo")}
            self.assertNotIn("ejecutar", claves, estado)


class AnteLaDudaSeDibuja(unittest.TestCase):
    """Un boton de mas se ve y se ignora; el que falta se lee como "no funciona"."""

    def test_si_no_se_puede_leer_la_solicitud(self):
        self.assertEqual(dibujar("loading", ticket_falla=True).botones,
                         ["Ejecutar carga en GitHub Actions"])

    def test_si_la_solicitud_no_esta_en_la_bandeja(self):
        self.assertEqual(dibujar("loading", sin_ticket=True).botones,
                         ["Ejecutar carga en GitHub Actions"])

    def test_un_estado_desconocido_tampoco_deja_sin_salida(self):
        self.assertEqual(dibujar("un_estado_que_no_existe").botones,
                         ["Ejecutar carga en GitHub Actions"])


class SinSolicitudNadaCambia(unittest.TestCase):
    """El camino que ya existia sigue igual."""

    def test_el_boton_se_dibuja_como_siempre(self):
        pantalla = dibujar("", codigo="")
        self.assertEqual(pantalla.botones, ["Ejecutar carga en GitHub Actions"])
        self.assertEqual(pantalla.infos, [])

    def test_sin_carga_remota_configurada_dice_que_falta(self):
        pantalla = dibujar("", codigo="", sobrevive=False)
        self.assertEqual(pantalla.botones, [])
        self.assertIn("no está configurada", pantalla.texto)

    def test_sin_matrixify_analizado_no_dibuja_nada(self):
        pantalla = PantallaFalsa()
        with mock.patch.object(app, "st") as st_falso:
            st_falso.session_state = {}
            st_falso.info, st_falso.caption = pantalla.info, pantalla.caption
            st_falso.markdown, st_falso.button = pantalla.markdown, pantalla.button
            app.render_boton_carga_remota(CONFIG)
        self.assertEqual(pantalla.botones, [])
        self.assertEqual(pantalla.texto, "")


class LaPreguntaSeHaceIgualQueLaBarra(unittest.TestCase):
    """Con otras claves contestaria que si cuando la barra no dibuja el boton."""

    def test_usa_assignee_y_user_como_render_barra_acciones(self):
        vistos = {}

        def espia(estado, rol, asignada, usuario):
            vistos.update(estado=estado, rol=rol, asignada=asignada, usuario=usuario)
            return []

        with mock.patch.object(app, "flujo_acciones", side_effect=espia), \
                mock.patch.object(app, "current_ticket_actor",
                                  return_value={"role": "OPERATOR", "user": "hugo"}), \
                mock.patch.object(app, "get_ticket_service", return_value=(object(), None)), \
                mock.patch.object(app, "ticket_para_pantalla",
                                  return_value={"status": "loading", "assignee": "hugo"}):
            app._solicitud_puede_ejecutar_carga("CAT-1")
        self.assertEqual(vistos["estado"], "loading")
        self.assertEqual(vistos["rol"], "operator")
        self.assertEqual(vistos["asignada"], "hugo")
        self.assertEqual(vistos["usuario"], "hugo")


if __name__ == "__main__":
    unittest.main(verbosity=1)
