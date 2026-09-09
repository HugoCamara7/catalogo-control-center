"""La curva decide como leer la talla, y la carga remota sin solicitud.

Ejecutar:  python scripts/test_curva_y_carga_suelta.py

Dos cosas, las dos reportadas por el usuario.

1. **Un valor suelto no se puede interpretar.** `040` puede ser el PE 40 o el
   US 4, y son dos tallas y media. Lo que SI se puede decidir es la curva
   entera: un producto de calzado tiene sus tallas en UNA escala.

2. **La carga remota exigia una solicitud.** El job colgaba del ticket, asi que
   subir un Excel a mano condenaba la carga a ejecutarse dentro de la sesion de
   Streamlit -- y cerrar la pestana la detenia, que es justo lo que el runner
   existe para evitar.
"""
import inspect
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pandas as pd  # noqa: E402

import app_matrixify as app  # noqa: E402
import generate_columbia_matrixify as g  # noqa: E402
from engines import carga_remota as cr  # noqa: E402
from engines.tallas_calzado import MINIMO_PE_MUJER, interpretar_curva  # noqa: E402
from engines import tallas_calzado  # noqa: E402


def matrixify_de(tallas, site_key, genero="HOMBRE", tipo="Zapatilla", marca=None):
    """El Matrixify de un producto de prueba.

    `marca` se pasa explicita porque la MARCA es la que decide la tabla de
    conversion. Tomar `allowed_arti_brands[0]` haria que en Supermall -- cuyas
    marcas son la union de todas -- el producto saliera de otra marca y la
    comparacion entre sitios midiera otra cosa.
    """
    config = g.get_brand_config(site_key)
    marca = marca or config["allowed_arti_brands"][0]
    arti = pd.DataFrame([{
        "Mod-Col": "X-1", "COD MOD COL": "X-1", "CODINT_MA": f"S{i}", "TALNUM_MA": t,
        "MARCA_MA": marca, "Precio": "100", "CodBarras": "",
        "NombreModelo": "P", "TipoProducto": tipo, "Genero": genero,
    } for i, t in enumerate(tallas, 1)])
    mx, _ = app.build_centry_matrixify_from_master(["X-1"], pd.DataFrame(), arti, config)
    return list(mx["Option1 Value"])


class TestLaCurvaDecide(unittest.TestCase):
    def test_el_maestro_de_hoy_no_se_toca(self):
        """Lo que hoy funciona tiene que seguir igual: el maestro trae el
        calzado multiplicado por diez (`400` es el PE 40)."""
        self.assertEqual(interpretar_curva(["40", "41", "42"])[:2], (1, "PE"))
        self.assertEqual(matrixify_de(["390", "400", "410"], "vans", "Masculino"),
                         ["39", "40", "41"])

    def test_relleno_de_ceros_x10(self):
        """`040, 050, 060` leido directo daria PE 40 a 60, que no existe."""
        self.assertEqual(interpretar_curva(["4", "5", "6", "7"])[:2], (1, "US"))
        # `070, 080` leido directo daria PE 70 y 80, que no existen; entre diez
        # da US 7 y 8, que si. La curva lo decide, el valor suelto no podria.
        self.assertEqual(interpretar_curva(["070", "080"])[:2], (10, "US"))
        self.assertEqual(matrixify_de(["070", "080"], "vans", "Masculino"), ["39", "40.5"])

    def test_085_es_ocho_y_medio(self):
        self.assertEqual(matrixify_de(["070", "085"], "vans", "Masculino"), ["39", "41"])

    def test_x100_tambien(self):
        """`850` es 8.5 multiplicado por cien."""
        self.assertEqual(interpretar_curva(["800", "850", "900"])[:2], (100, "US"))
        self.assertEqual(matrixify_de(["800", "850"], "vans", "Masculino"), ["40.5", "41"])

    def test_040_de_mujer_es_un_US_4(self):
        """La regla del usuario: ninguna curva de mujer empieza en la 40."""
        divisor, escala, nota = interpretar_curva(["40"], "Femenino")
        self.assertEqual((divisor, escala), (10, "US"))
        self.assertIn("mujer", nota)
        self.assertEqual(matrixify_de(["040"], "vans", "Femenino"), ["35"])

    def test_040_de_hombre_sigue_siendo_PE_40(self):
        self.assertEqual(interpretar_curva(["40"], "Masculino")[:2], (1, "PE"))
        self.assertEqual(matrixify_de(["040"], "vans", "Masculino"), ["40"])

    def test_una_curva_PE_de_mujer_normal_no_se_toca(self):
        """El umbral es el MINIMO de la curva, no el valor: una curva de mujer
        que llega a la 40 pero empieza en la 36 es PE."""
        self.assertEqual(interpretar_curva(["36", "38", "40"], "Femenino")[:2], (1, "PE"))
        self.assertEqual(matrixify_de(["036", "038"], "vans", "Femenino"), ["36", "38"])

    def test_el_umbral_de_mujer_es_el_declarado(self):
        self.assertEqual(MINIMO_PE_MUJER, 40.0)

    def test_no_hay_una_segunda_funcion_de_curva_sin_usar(self):
        """`aplicar_curva` se escribio y no la llamaba nadie. Una funcion sin
        llamador es la regla 6 de CLAUDE.md, y ademas seria un segundo criterio
        de lectura de curva esperando a separarse del primero."""
        self.assertFalse(hasattr(tallas_calzado, "aplicar_curva"))

    def test_lo_que_no_es_calzado_no_se_interpreta(self):
        self.assertEqual(interpretar_curva(["M", "L", "XL"]), (1, "", ""))

    def test_una_curva_imposible_se_reporta_y_no_se_toca(self):
        divisor, escala, nota = interpretar_curva(["9000"])
        self.assertEqual((divisor, escala), (1, ""))
        self.assertIn("no cabe", nota)

    def test_sin_curva_se_comporta_como_antes(self):
        """`curva` es opcional: sin ella nada cambia."""
        config = g.get_brand_config("vans")
        self.assertEqual(
            g.display_size_for_site("8", config, gender="Masculino", product_type="Zapatilla"),
            g.display_size_for_site("8", config, gender="Masculino", product_type="Zapatilla",
                                    curva=None),
        )

    def test_el_ajuste_se_reporta(self):
        avisos = []
        g.display_size_for_site("850", g.get_brand_config("vans"), gender="Masculino",
                                product_type="Zapatilla", marca="VANS",
                                curva=["800", "850"], valor_crudo="850", avisos=avisos)
        self.assertTrue(any("entre 100" in a["Motivo"] for a in avisos), avisos)


class TestRockfordTallaUnica(unittest.TestCase):
    def test_un_accesorio_de_una_sola_talla(self):
        self.assertEqual(matrixify_de(["400"], "rockford", tipo="Mochila"), ["Talla Única"])

    def test_un_accesorio_con_curva_no(self):
        self.assertNotIn("Talla Única", matrixify_de(["400", "410"], "rockford", tipo="Mochila"))

    def test_el_calzado_de_una_sola_talla_NO_se_renombra(self):
        """"Talla Única" esta bloqueada en calzado y vestuario a proposito:
        `final_variant_filter` BORRA esas filas. Renombrarla haria desaparecer
        el producto entero, que es peor que publicar la talla."""
        self.assertEqual(matrixify_de(["400"], "rockford", tipo="Zapatilla"), ["40"])

    def test_la_guarda_coincide_con_la_del_filtro_final(self):
        for tipo in ("Zapatilla", "Casaca", "Polera"):
            self.assertTrue(g._talla_unica_bloqueada(tipo), tipo)
        for tipo in ("Mochila", "Gorra"):
            self.assertFalse(g._talla_unica_bloqueada(tipo), tipo)

    def test_solo_rockford(self):
        for site_key in ("vans", "columbia", "supermall"):
            self.assertNotIn("Talla Única", matrixify_de(["400"], site_key, tipo="Mochila"),
                             site_key)


class TestSupermallYVansUsanLaMismaGuia(unittest.TestCase):
    def test_la_misma_talla_sale_igual_en_los_dos_sitios(self):
        for tallas, genero in ((["070", "080"], "Masculino"), (["070", "080"], "Femenino"),
                               (["390", "400"], "Masculino")):
            self.assertEqual(
                matrixify_de(tallas, "vans", genero, marca="VANS"),
                matrixify_de(tallas, "supermall", genero, marca="VANS"),
                (tallas, genero),
            )

    def test_los_dos_publican_en_PE(self):
        for site_key in ("vans", "supermall"):
            self.assertEqual(g.escala_de_calzado(g.get_brand_config(site_key)), "PE")


class TestHushKedsSorelUsanLaGuiaPorDefecto(unittest.TestCase):
    """Septiembre de 2026: el usuario pidio que TODO el calzado saliera con la
    guia. Ninguna de estas marcas tiene la suya, asi que caen en la de Vans --
    la unica confirmada -- y cada conversion se REPORTA."""

    def test_siguen_sin_guia_PROPIA_registrada(self):
        from engines import guias_tallas as gt
        # Columbia salio de esta lista en septiembre de 2026: su guia se busco
        # en la web a peticion del usuario (`TABLA_COLUMBIA`).
        for marca in ("HUSH PUPPIES", "KEDS", "SOREL"):
            self.assertIsNone(gt.guia_para(marca, gt.CALZADO), marca)
        self.assertIsNotNone(gt.guia_para("COLUMBIA", gt.CALZADO))

    def test_su_talla_se_convierte_con_la_por_defecto_y_queda_avisada(self):
        from engines import guias_tallas as gt
        for marca in ("HUSH PUPPIES", "KEDS", "SOREL"):
            talla, nota = gt.convertir("8", marca, gt.CALZADO, "Masculino")
            self.assertEqual(talla, "40.5", marca)
            self.assertEqual(nota, gt.POR_DEFECTO, marca)


class TestCargaRemotaSinSolicitud(unittest.TestCase):
    def test_el_adaptador_sabe_lanzar_sin_ticket(self):
        self.assertTrue(hasattr(cr.AdaptadorCargaActions, "start_suelto"))

    def test_el_matrixify_se_sube_ANTES_de_guardar_el_registro(self):
        """Con el registro guardado y el archivo no, el runner arrancaria para
        morir leyendo una ruta que no existe."""
        cuerpo = inspect.getsource(cr.AdaptadorCargaActions.start_suelto)
        self.assertLess(cuerpo.index("guardar_archivo"), cuerpo.index("self.almacen.guardar(job"))

    def test_el_archivo_va_al_lado_del_registro_del_job(self):
        almacen = cr.AlmacenJobsGitHub.__new__(cr.AlmacenJobsGitHub)
        almacen.prefix = "catalog_tickets"
        ruta = almacen.ruta_de_matrixify("job-123", "matrixify_vans.xlsx")
        self.assertEqual(ruta, "catalog_tickets/catalog_jobs/job-123/matrixify_vans.xlsx")

    def test_la_ruta_sanea_el_nombre_y_asegura_extension(self):
        almacen = cr.AlmacenJobsGitHub.__new__(cr.AlmacenJobsGitHub)
        almacen.prefix = "catalog_tickets"
        ruta = almacen.ruta_de_matrixify("j", "raro/../nombre")
        self.assertTrue(ruta.endswith(".xlsx"))
        # Lo que importa es que el nombre no pueda salirse de su carpeta: la
        # barra y los puntos se sanean a guion, asi que no hay travesia.
        self.assertEqual(ruta.count("/"), 3)
        self.assertTrue(ruta.startswith("catalog_tickets/catalog_jobs/j/"))

    def test_el_codigo_se_ve_como_lo_que_es(self):
        """Inventar un CAT-#### haria creer que existe una solicitud."""
        self.assertEqual(cr.CODIGO_CARGA_SUELTA, "CARGA")
        cuerpo = inspect.getsource(cr.AdaptadorCargaActions.start_suelto)
        self.assertIn("CODIGO_CARGA_SUELTA", cuerpo)

    def test_nunca_levanta_y_devuelve_el_motivo(self):
        cuerpo = inspect.getsource(cr.AdaptadorCargaActions.start_suelto)
        self.assertIn("_job_sin_disparar", cuerpo)

    def test_reusa_el_mismo_worker_y_el_mismo_workflow(self):
        """No hay un segundo motor de carga: mismo registro, mismo workflow,
        mismo avance por bloques."""
        cuerpo = inspect.getsource(cr.AdaptadorCargaActions.start_suelto)
        self.assertIn("nuevo_registro_job", cuerpo)
        self.assertIn("self._disparar", cuerpo)
        self.assertIn("self.workflow", cuerpo)

    def test_recordar_matrixify_ya_no_exige_codigo(self):
        """Era la puerta cerrada: sin solicitud no se apuntaba nada, asi que no
        habia con que lanzar la carga remota."""
        cuerpo = inspect.getsource(app.recordar_matrixify_de_carga)
        self.assertNotIn("if not codigo or matrixify_df is None", cuerpo)
        self.assertIn("if matrixify_df is None or matrixify_df.empty", cuerpo)

    def test_el_boton_no_se_dibuja_si_hay_solicitud(self):
        """Ahi manda la barra de acciones de la solicitud, que ademas mueve su
        estado. Dos botones para lo mismo es peor que uno."""
        cuerpo = inspect.getsource(app.render_boton_carga_remota)
        self.assertIn('clean_value(guardado.get("codigo"))', cuerpo)
        self.assertIn("return", cuerpo)

    def test_el_boton_avisa_cuando_falta_configuracion(self):
        cuerpo = inspect.getsource(app.render_boton_carga_remota)
        self.assertIn("estado_carga_remota()", cuerpo)
        self.assertIn("no está configurada", cuerpo)

    def test_el_boton_se_dibuja_fuera_de_la_casilla_de_sincronizacion(self):
        """Anidado dentro no aparecia con "Respaldo Excel" ni sin marcarla, que
        es el mismo fallo que ya se corrigio con el cierre de la solicitud."""
        fuente = inspect.getsource(app).splitlines()
        for i, linea in enumerate(fuente):
            if "render_boton_carga_remota(brand_config)" in linea and "def " not in linea:
                sangria_boton = len(linea) - len(linea.lstrip())
                for j in range(i, 0, -1):
                    if "recordar_matrixify_de_carga(" in fuente[j]:
                        sangria_ref = len(fuente[j]) - len(fuente[j].lstrip())
                        break
                self.assertEqual(sangria_boton, sangria_ref)
                return
        self.fail("no encontre la llamada a render_boton_carga_remota")


class TestAdjuntarElMatrixifyALaSolicitud(unittest.TestCase):
    """El puente entre la sesion y el runner, que fallaba EN SILENCIO.

    `_adjuntar_matrixify_antes_de_cargar` tenia dos salidas que devolvian ""
    -o sea "todo bien"- sin haber adjuntado nada: cuando no habia Matrixify
    apuntado y cuando el codigo apuntado no era el de la solicitud. En las dos
    la carga seguia adelante y moria en el adaptador con "La solicitud no tiene
    un Matrixify adjunto. Genéralo en Carga completa (Analizar input)", que
    culpa a la solicitud y manda a hacer algo que ya se hizo.

    Y el segundo caso se hizo MAS probable al permitir la carga remota sin
    solicitud: desde entonces el codigo apuntado puede venir vacio.
    """

    CODIGO = "CAT-2026-000041"

    def setUp(self):
        import pathlib
        import tempfile
        self.excel = pathlib.Path(tempfile.mkdtemp()) / "m.xlsx"
        self.excel.write_bytes(b"PK contenido")
        self.sesion_previa = app.st.session_state
        self.apuntado = {
            "codigo": "", "excel_path": str(self.excel), "product_keys": ["a", "b"],
            "site_key": "rockford", "filename": "m.xlsx",
        }

    def tearDown(self):
        app.st.session_state = self.sesion_previa

    def _servicio(self, ticket):
        adjuntos = []

        class Servicio:
            def get_ticket(self, actor, code):
                return ticket

            def attach_matrixify(self, actor, code, **kw):
                adjuntos.append({"codigo": code, "site_key": kw.get("site_key"),
                                 "bytes": len(kw["payload"])})

        return Servicio(), adjuntos

    def _ejecutar(self, apuntado, ticket, remota=True):
        app.st.session_state = {} if apuntado is None else {
            app.CLAVE_MATRIXIFY_SESION: dict(apuntado)}
        servicio, adjuntos = self._servicio(ticket)
        previo = app.estado_carga_remota
        app.estado_carga_remota = lambda *a, **k: {"sobrevive": remota, "pasos": []}
        try:
            aviso = app._adjuntar_matrixify_antes_de_cargar(
                servicio, {"role": "admin"}, self.CODIGO)
        finally:
            app.estado_carga_remota = previo
        return aviso, adjuntos

    def test_sin_carga_remota_activa_no_bloquea(self):
        """Sin `[carga_remota]` la carga se hace dentro de la sesion, por
        bloques: no hay runner que necesite el archivo en el repositorio, asi
        que no hay nada que adjuntar y bloquear cortaria un camino valido."""
        aviso, adjuntos = self._ejecutar(None, {"site_key": "rockford", "matrixify": {}},
                                         remota=False)
        self.assertEqual(aviso, "")
        self.assertEqual(adjuntos, [])

    def test_analizado_SIN_ticket_se_adjunta_igual(self):
        """El caso que reporto el usuario. En la sesion solo cabe el ultimo
        Matrixify analizado; si se ejecuta la carga de una solicitud del mismo
        sitio, ese es el archivo."""
        aviso, adjuntos = self._ejecutar(self.apuntado, {"site_key": "rockford", "matrixify": {}})
        self.assertEqual(aviso, "")
        self.assertEqual(len(adjuntos), 1)
        self.assertEqual(adjuntos[0]["codigo"], self.CODIGO)

    def test_analizado_con_otro_codigo_del_mismo_sitio_tambien(self):
        aviso, adjuntos = self._ejecutar(dict(self.apuntado, codigo="CAT-2026-000099"),
                                         {"site_key": "rockford", "matrixify": {}})
        self.assertEqual(aviso, "")
        self.assertEqual(len(adjuntos), 1)

    def test_otro_SITIO_no_se_adjunta_y_lo_dice(self):
        """Lo que de verdad no puede cruzarse: un Matrixify de Vans.pe en una
        solicitud de Rockford.pe cargaria el catalogo equivocado."""
        aviso, adjuntos = self._ejecutar(dict(self.apuntado, site_key="vans"),
                                         {"site_key": "rockford", "matrixify": {}})
        self.assertEqual(adjuntos, [])
        self.assertIn("vans", aviso)
        self.assertIn("rockford", aviso)

    def test_sin_nada_apuntado_lo_dice_en_vez_de_seguir(self):
        aviso, adjuntos = self._ejecutar(None, {"site_key": "rockford", "matrixify": {}})
        self.assertEqual(adjuntos, [])
        self.assertIn("Analizar input", aviso)
        self.assertNotEqual(aviso, "")

    def test_si_la_solicitud_ya_tiene_adjunto_se_sigue(self):
        """Un reintento legitimo no puede convertirse en callejon sin salida."""
        aviso, adjuntos = self._ejecutar(
            None, {"site_key": "rockford", "matrixify": {"path": "catalog_tickets/x.xlsx"}})
        self.assertEqual(aviso, "")
        self.assertEqual(adjuntos, [])

    def test_sin_el_excel_en_disco_lo_dice(self):
        aviso, adjuntos = self._ejecutar(dict(self.apuntado, excel_path="/no/existe.xlsx"),
                                         {"site_key": "rockford", "matrixify": {}})
        self.assertEqual(adjuntos, [])
        self.assertIn("no está en disco", aviso)

    def test_no_queda_ninguna_salida_silenciosa(self):
        """Cada `return ""` de la funcion tiene que ir despues de un adjunto o
        despues de comprobar que la solicitud ya tenia uno."""
        cuerpo = inspect.getsource(app._adjuntar_matrixify_antes_de_cargar)
        self.assertNotIn('    if not isinstance(guardado, dict):\n        return ""', cuerpo)
        self.assertNotIn('!= clean_value(codigo):\n        return ""', cuerpo)

    def test_tras_adjuntar_queda_apuntado_a_esa_solicitud(self):
        """Para que un segundo clic no vuelva a subir el mismo archivo."""
        self._ejecutar(self.apuntado, {"site_key": "rockford", "matrixify": {}})
        self.assertEqual(
            app.st.session_state[app.CLAVE_MATRIXIFY_SESION]["codigo"], self.CODIGO)


if __name__ == "__main__":
    unittest.main(verbosity=2)
