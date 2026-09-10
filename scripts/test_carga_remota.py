"""Pruebas de la carga que sobrevive al cierre de sesion.

Origen: la carga corria dentro del proceso de Streamlit. Al cerrar el
navegador o apagar la PC, Streamlit corta la sesion y la carga se detenia a
mitad del catalogo. El panel "recuperable por bloques" no lo resolvia: no
avanzaba solo y guardaba el avance en `outputs/`, que es efimero.

Ahora la ejecuta un runner de GitHub Actions y el avance vive en el
repositorio privado de datos.

Ejecutar:  python scripts/test_carga_remota.py
"""
import ast
import base64
import inspect
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from engines import carga_remota as cr  # noqa: E402
import ticket_system as ts  # noqa: E402


def ticket_listo(codigo="CAT-2026-000001", con_matrixify=True, claves=("A-1", "A-2", "A-3")):
    ticket = {
        "code": codigo,
        "site_key": "columbia",
        "brand": "COLUMBIA",
        "assigned_to": "hugo@forus.pe",
        "summary": {"products": len(claves)},
    }
    if con_matrixify:
        ticket["matrixify"] = {
            "path": f"catalog_tickets/artifacts/{codigo}/v001_matrixify_x.xlsx",
            "product_keys": list(claves),
            "site_key": "columbia",
        }
    return ticket


class AlmacenFalso:
    """Un almacen en memoria con la misma superficie que el de GitHub."""

    def __init__(self, fallar_al_guardar=False):
        self.jobs = {}
        self.archivos = {}
        self.guardados = 0
        self.fallar_al_guardar = fallar_al_guardar
        self.prefix = "catalog_tickets"

    def leer(self, job_id):
        job = self.jobs.get(job_id)
        return (json.loads(json.dumps(job)) if job else None), ("sha" if job else None)

    def guardar(self, job, sha=None, mensaje=""):
        if self.fallar_al_guardar:
            raise cr.ErrorCargaRemota("sin red")
        self.guardados += 1
        self.jobs[job["id"]] = json.loads(json.dumps(job))
        return f"sha{self.guardados}"

    def leer_archivo(self, ruta):
        return self.archivos.get(ruta, b"")

    def guardar_archivo(self, ruta, contenido, mensaje=""):
        self.archivos[ruta] = contenido
        return ruta


class DisparadorFalso:
    def __init__(self, error=None):
        self.error = error
        self.llamadas = []

    def __call__(self, **kwargs):
        self.llamadas.append(kwargs)
        if self.error:
            raise self.error
        return True


# --- lo que hace que la carga sobreviva -----------------------------------

class TestSobrevivirALaSesion(unittest.TestCase):
    def test_el_id_del_job_queda_en_el_ticket_no_en_la_sesion(self):
        """Es la pieza que hace que cerrar la sesion no pierda la carga.

        `start_load` guarda lo que devuelve el adaptador en `ticket["job"]`, y
        el ticket se persiste en GitHub. Si el id viviera en `st.session_state`
        se perderia al cerrar el navegador, que es justo el problema.
        """
        almacen = AlmacenFalso()
        disparador = DisparadorFalso()
        adaptador = cr.AdaptadorCargaActions(
            almacen, owner="o", repo="r", workflow="w.yml", token="t",
            disparador=disparador,
        )
        resultado = adaptador.start(ticket_listo())
        self.assertTrue(resultado["id"])
        self.assertEqual(resultado["mode"], "github_actions")
        self.assertEqual(resultado["status"], cr.JOB_ENCOLADO)
        # Y el registro con los pendientes quedo fuera del ticket, en el almacen.
        self.assertIn(resultado["id"], almacen.jobs)

    def test_el_ticket_solo_guarda_el_puntero_no_el_avance(self):
        """El detalle no puede vivir dentro del ticket.

        Con los pendientes y los resultados dentro, cada escritura de la
        solicitud arrastraria el catalogo entero y el JSON creceria sin techo.
        """
        almacen = AlmacenFalso()
        adaptador = cr.AdaptadorCargaActions(
            almacen, owner="o", repo="r", workflow="w.yml", token="t",
            disparador=DisparadorFalso(),
        )
        resultado = adaptador.start(ticket_listo(claves=tuple(f"K-{i}" for i in range(500))))
        for pesado in ("pending_keys", "completed_keys", "result_rows", "events", "product_keys"):
            self.assertNotIn(pesado, resultado)
        self.assertEqual(almacen.jobs[resultado["id"]]["total_products"], 500)

    def test_dispara_el_workflow_con_el_job_y_el_sitio(self):
        almacen = AlmacenFalso()
        disparador = DisparadorFalso()
        adaptador = cr.AdaptadorCargaActions(
            almacen, owner="HugoCamara7", repo="catalogo-control-center",
            workflow="carga-shopify.yml", ref="main", token="t", disparador=disparador,
        )
        resultado = adaptador.start(ticket_listo())
        self.assertEqual(len(disparador.llamadas), 1)
        llamada = disparador.llamadas[0]
        self.assertEqual(llamada["workflow"], "carga-shopify.yml")
        self.assertEqual(llamada["ref"], "main")
        self.assertEqual(llamada["inputs"]["job_id"], resultado["id"])
        self.assertEqual(llamada["inputs"]["site_key"], "columbia")


class TestNoTumbaLaSolicitud(unittest.TestCase):
    """Un fallo al disparar no puede deshacer la transicion del ticket.

    Misma regla que los correos: ningun fallo de un sistema externo puede
    tumbar ni revertir un cambio de estado.
    """

    def test_sin_matrixify_avisa_y_no_dispara(self):
        almacen = AlmacenFalso()
        disparador = DisparadorFalso()
        adaptador = cr.AdaptadorCargaActions(
            almacen, owner="o", repo="r", workflow="w.yml", token="t", disparador=disparador,
        )
        resultado = adaptador.start(ticket_listo(con_matrixify=False))
        self.assertEqual(resultado["status"], cr.JOB_SIN_DISPARAR)
        self.assertIn("Matrixify", resultado["message"])
        # No se gastan minutos de runner en un job que moriria leyendo un
        # archivo que no existe.
        self.assertEqual(disparador.llamadas, [])
        self.assertEqual(almacen.jobs, {})

    def test_si_el_disparo_falla_devuelve_el_motivo_sin_levantar(self):
        almacen = AlmacenFalso()
        adaptador = cr.AdaptadorCargaActions(
            almacen, owner="o", repo="r", workflow="w.yml", token="t",
            disparador=DisparadorFalso(error=cr.ErrorCargaRemota("permisos")),
        )
        resultado = adaptador.start(ticket_listo())
        self.assertEqual(resultado["status"], cr.JOB_SIN_DISPARAR)
        self.assertIn("permisos", resultado["message"])

    def test_si_no_puede_guardar_el_registro_tampoco_levanta(self):
        adaptador = cr.AdaptadorCargaActions(
            AlmacenFalso(fallar_al_guardar=True), owner="o", repo="r",
            workflow="w.yml", token="t", disparador=DisparadorFalso(),
        )
        resultado = adaptador.start(ticket_listo())
        self.assertEqual(resultado["status"], cr.JOB_SIN_DISPARAR)

    def test_el_dry_run_sigue_siendo_local(self):
        """Mandar la simulacion a un runner solo agregaria cola a un paso
        que hoy es inmediato, y no llama a Shopify."""
        disparador = DisparadorFalso()
        adaptador = cr.AdaptadorCargaActions(
            AlmacenFalso(), owner="o", repo="r", workflow="w.yml", token="t",
            disparador=disparador,
        )
        dry = adaptador.dry_run(ticket_listo())
        self.assertEqual(dry["status"], "completed")
        self.assertEqual(disparador.llamadas, [])


# --- reanudacion -----------------------------------------------------------

class TestReanudacion(unittest.TestCase):
    def test_un_producto_ya_cargado_no_vuelve_a_la_cola(self):
        """Si el runner muere a la mitad, el siguiente no puede recargar lo
        que ya escribio en Shopify."""
        job = cr.nuevo_registro_job(
            codigo_solicitud="CAT-1", site_key="columbia", matrixify_path="x",
            claves_producto=["A", "B", "C", "D"],
        )
        cr.registrar_avance_bloque(job, ok=2, completados=["A", "B"])
        self.assertEqual(job["pending_keys"], ["C", "D"])
        self.assertEqual(job["processed_products"], 2)
        # Un bloque repetido con los mismos productos no los duplica ni los
        # devuelve a pendientes.
        cr.registrar_avance_bloque(job, ok=0, completados=["A", "B"])
        self.assertEqual(job["pending_keys"], ["C", "D"])
        self.assertEqual(job["processed_products"], 2)

    def test_quedar_con_pendientes_no_es_terminar(self):
        """El runner que se queda sin tiempo vuelve a la cola, no a completado.

        Marcarlo completado con productos sin cargar es exactamente el error
        que se corrigio en agosto de 2026 con la cadena de cierre.
        """
        job = cr.nuevo_registro_job(
            codigo_solicitud="CAT-1", site_key="columbia", matrixify_path="x",
            claves_producto=["A", "B", "C"],
        )
        cr.registrar_avance_bloque(job, ok=1, completados=["A"])
        cr.cerrar_job(job)
        self.assertEqual(job["status"], cr.JOB_ENCOLADO)
        self.assertNotIn(job["status"], cr.ESTADOS_JOB_TERMINADO)
        self.assertIn("pendientes", job["message"])

    def test_sin_pendientes_y_sin_errores_queda_completado(self):
        job = cr.nuevo_registro_job(
            codigo_solicitud="CAT-1", site_key="columbia", matrixify_path="x",
            claves_producto=["A", "B"],
        )
        cr.registrar_avance_bloque(job, ok=2, completados=["A", "B"])
        cr.cerrar_job(job)
        self.assertEqual(job["status"], cr.JOB_COMPLETADO)
        self.assertTrue(job["finished_at"])

    def test_con_errores_se_distingue_de_completado_limpio(self):
        job = cr.nuevo_registro_job(
            codigo_solicitud="CAT-1", site_key="columbia", matrixify_path="x",
            claves_producto=["A", "B"],
        )
        cr.registrar_avance_bloque(job, ok=1, errores=1, completados=["A", "B"], con_error=["B"])
        cr.cerrar_job(job)
        self.assertEqual(job["status"], cr.JOB_COMPLETADO_CON_ERRORES)

    def test_un_error_del_worker_deja_el_job_fallido_con_motivo(self):
        job = cr.nuevo_registro_job(
            codigo_solicitud="CAT-1", site_key="columbia", matrixify_path="x",
            claves_producto=["A"],
        )
        cr.cerrar_job(job, error="Shopify devolvio 500")
        self.assertEqual(job["status"], cr.JOB_FALLIDO)
        self.assertIn("500", job["message"])

    def test_los_eventos_no_crecen_sin_techo(self):
        """El registro se serializa entero en cada publicacion: un evento por
        producto convertiria cada commit en un archivo de megabytes."""
        job = cr.nuevo_registro_job(
            codigo_solicitud="CAT-1", site_key="columbia", matrixify_path="x",
            claves_producto=["A"],
        )
        for indice in range(400):
            cr.agregar_evento(job, "Bloque", f"detalle {indice}")
        self.assertEqual(len(job["events"]), 250)
        self.assertIn("399", job["events"][-1]["Detalle"])


# --- los logos de Actions son publicos ------------------------------------

class TestLogsPublicos(unittest.TestCase):
    def test_enmascara_los_tokens_conocidos(self):
        for secreto in (
            "shpat_1234567890abcdef",
            "github_pat_11ABCDE_xyz123",
            "ghp_0123456789abcdefghij",
            "https://user:clave@github.com/x",
        ):
            with self.subTest(secreto):
                self.assertNotIn(secreto, cr.texto_publico(f"fallo con {secreto} al final"))

    def test_recorta_para_no_volcar_una_respuesta_entera(self):
        self.assertLessEqual(len(cr.texto_publico("x" * 5000)), cr.LARGO_MAXIMO_LOG)

    def test_el_worker_no_imprime_por_fuera_del_saneado(self):
        """Cada print suelto es una fuga permanente en un repositorio publico."""
        fuente = (ROOT / "scripts" / "worker_carga_shopify.py").read_text(encoding="utf-8")
        arbol = ast.parse(fuente)
        impresiones = [
            nodo for nodo in ast.walk(arbol)
            if isinstance(nodo, ast.Call) and isinstance(nodo.func, ast.Name)
            and nodo.func.id == "print"
        ]
        # El unico print permitido es el que vive dentro de _decir().
        self.assertEqual(len(impresiones), 1, "Hay un print fuera de _decir().")

    def test_un_error_de_github_se_sanea_antes_de_viajar(self):
        """El detalle de un HTTPError puede traer la URL con el token dentro,
        y esa excepcion tambien termina en pantalla y en la auditoria."""
        fuente = (ROOT / "engines" / "carga_remota.py").read_text(encoding="utf-8")
        self.assertIn("texto_publico(detalle", fuente)


# --- contrato con ticket_system -------------------------------------------

class TestEngancheConSolicitudes(unittest.TestCase):
    def test_start_load_sigue_llamando_al_adaptador(self):
        """El enganche es `self.jobs.start(ticket)` dentro de `start_load`.

        Si alguien lo quita, la carga deja de salir a Actions y no falla nada:
        el ticket pasa a "en ejecucion" y no carga nadie. Por eso se fija aqui.
        """
        # utf-8-sig: ticket_system.py y app_matrixify.py llevan BOM.
        fuente = (ROOT / "ticket_system.py").read_text(encoding="utf-8-sig")
        arbol = ast.parse(fuente)
        metodos = [n for n in ast.walk(arbol)
                   if isinstance(n, ast.FunctionDef) and n.name == "start_load"]
        self.assertEqual(len(metodos), 1)
        cuerpo = ast.dump(metodos[0])
        self.assertIn("'start'", cuerpo.replace('"', "'"))

    def test_upgrade_ticket_conserva_el_matrixify_de_un_ticket_viejo(self):
        viejo = {"code": "CAT-1", "status": "loading"}
        self.assertEqual(ts.upgrade_ticket(viejo)["matrixify"], {})
        con_dato = {"code": "CAT-1", "status": "loading", "matrixify": {"path": "p"}}
        self.assertEqual(ts.upgrade_ticket(con_dato)["matrixify"], {"path": "p"})

    def test_attach_matrixify_no_reescribe_si_el_contenido_no_cambio(self):
        """Cada escritura es un commit: pulsar dos veces con el mismo analisis
        no tiene por que dejar dos."""
        with tempfile.TemporaryDirectory() as carpeta:
            store = ts.LocalTicketStore(carpeta)
            servicio = ts.TicketService(store)
            actor_marca = servicio.actor("marca@forus.pe", ts.ROLE_BRAND, ["COLUMBIA"])
            ticket = servicio.create_ticket(
                actor_marca, brand="COLUMBIA", sites=["Columbia.pe"], load_type="complete",
                filename="input.xlsx", input_bytes=b"x", report_bytes=b"",
                summary={"products": 2, "blocked": 0, "new_products": 2, "updated_products": 0},
            )
            admin = servicio.actor("hugo@forus.pe", ts.ROLE_ADMIN)
            escrituras = []
            original = store.put_artifact

            def espia(*args, **kwargs):
                escrituras.append(args[2] if len(args) > 2 else kwargs.get("kind"))
                return original(*args, **kwargs)

            store.put_artifact = espia
            for _ in range(3):
                servicio.attach_matrixify(
                    admin, ticket["code"], filename="m.xlsx", payload=b"contenido",
                    product_keys=["A", "B"], site_key="columbia",
                )
            self.assertEqual(escrituras.count("matrixify"), 1)
            guardado = servicio.get_ticket(admin, ticket["code"])["matrixify"]
            self.assertEqual(guardado["product_keys"], ["A", "B"])
            self.assertTrue(guardado["path"])


def _worker():
    """Carga el worker por ruta.

    Con `from scripts import ...` haria falta un `__init__.py` en scripts/, y
    eso cambia como se resuelven los otros 19 scripts de prueba.
    """
    import importlib.util

    if "worker_carga_shopify" in sys.modules:
        return sys.modules["worker_carga_shopify"]
    ruta = ROOT / "scripts" / "worker_carga_shopify.py"
    spec = importlib.util.spec_from_file_location("worker_carga_shopify", ruta)
    modulo = importlib.util.module_from_spec(spec)
    sys.modules["worker_carga_shopify"] = modulo
    spec.loader.exec_module(modulo)
    return modulo


class TestWorkerReanuda(unittest.TestCase):
    """La prueba de que la carga sobrevive: el worker retoma donde iba.

    Se simula el motor de bloques de app_matrixify --que ya tiene sus propias
    pruebas-- para poder matar al runner a mitad de camino sin llamar a
    Shopify. Lo que se verifica aqui es lo que agrega el worker: de donde saca
    el estado y a donde publica el avance.
    """

    def setUp(self):
        self.modulos_previos = {
            nombre: sys.modules.get(nombre)
            for nombre in ("app_matrixify", "catalog_engine", "pandas")
        }
        self.cargados = []
        sys.modules["app_matrixify"] = self._app_falsa()
        sys.modules["catalog_engine"] = self._catalog_engine_falso()
        # El worker deja el Matrixify bajado en `job_inputs/`. En el runner eso
        # esta bien; aqui dejaria archivos sueltos en el repositorio en cada
        # corrida, asi que la prueba trabaja en una carpeta temporal.
        self.carpeta = tempfile.TemporaryDirectory()
        self.cwd_previo = os.getcwd()
        os.chdir(self.carpeta.name)

    def tearDown(self):
        os.chdir(self.cwd_previo)
        self.carpeta.cleanup()
        for nombre, modulo in self.modulos_previos.items():
            if modulo is None:
                sys.modules.pop(nombre, None)
            else:
                sys.modules[nombre] = modulo

    def _catalog_engine_falso(self):
        import types

        modulo = types.ModuleType("catalog_engine")

        # El doble acepta `sheet_name` porque el real lo acepta, y ademas lo
        # COMPRUEBA: una carga completa tiene que pedir la hoja `Products`. Si
        # el worker le pidiera la hoja de la vista previa, el Matrixify de una
        # solicitud llegaria vacio y el job se cerraria sin cargar nada.
        def _leer(ruta, sheet_name="Products"):
            self.hojas_pedidas.append(sheet_name)
            return _TablaFalsa(["A", "B", "C", "D", "E"])

        self.hojas_pedidas = []
        modulo.read_matrixify_excel = _leer
        modulo.shopify_config_from_env = lambda site_key: {
            "shop_domain": "x.myshopify.com", "admin_access_token": "t",
        }
        # El doble tiene que traer lo mismo que el modulo real: el worker le
        # pide `_env_name` para nombrar la credencial que falta.
        modulo._env_name = lambda site_key, sufijo: f"{site_key.upper()}_{sufijo}"
        return modulo

    def _app_falsa(self):
        import types

        prueba = self
        modulo = types.ModuleType("app_matrixify")
        estado = {}

        def _sync_job_product_keys(df, mode="full"):
            return list(df.claves)

        def _create_sync_job(site_key, mode, source_df, batch_size=20,
                             activate_inventory_locations=True):
            job = {
                "id": "local-1", "batch_size": batch_size,
                "product_keys": list(source_df.claves),
                "pending_keys": list(source_df.claves), "completed_keys": [],
                "error_keys": [], "ok_products": 0, "partial_products": 0,
                "error_products": 0, "result_rows": [], "events": [],
            }
            estado[job["id"]] = job
            return job

        def _save_sync_job(job):
            estado[job["id"]] = json.loads(json.dumps(job))

        def _load_sync_job(job_id):
            job = estado.get(job_id)
            return json.loads(json.dumps(job)) if job else None

        def process_sync_job_next_block(job_id, configuracion, **kwargs):
            job = estado[job_id]
            bloque = job["pending_keys"][: job["batch_size"]]
            for clave in bloque:
                prueba.cargados.append(clave)
                job["completed_keys"].append(clave)
                job["ok_products"] += 1
                job["result_rows"].append({"Handle": clave, "Resultado": "OK"})
            job["pending_keys"] = job["pending_keys"][len(bloque):]
            estado[job_id] = job
            return json.loads(json.dumps(job))

        modulo._sync_job_product_keys = _sync_job_product_keys
        modulo._create_sync_job = _create_sync_job
        modulo._save_sync_job = _save_sync_job
        modulo._load_sync_job = _load_sync_job
        modulo.process_sync_job_next_block = process_sync_job_next_block
        modulo.dataframe_to_excel_bytes = lambda hojas: b"xlsx"
        return modulo

    def _job_y_almacen(self, batch_size=2, completados=()):
        almacen = AlmacenFalso()
        job = cr.nuevo_registro_job(
            codigo_solicitud="CAT-2026-000001", site_key="columbia",
            matrixify_path="catalog_tickets/artifacts/CAT/m.xlsx",
            claves_producto=["A", "B", "C", "D", "E"], batch_size=batch_size,
        )
        job["completed_keys"] = list(completados)
        almacen.archivos[job["matrixify_path"]] = b"excel"
        almacen.guardar(job)
        return job, almacen

    def test_una_carga_completa_pide_la_hoja_Products(self):
        """La hoja la decide el modo. Desde que el worker sabe hacer cargas
        parciales -- que viajan en la hoja `Vista previa` --, pedir la hoja
        equivocada dejaria el Matrixify de una solicitud sin una sola fila y el
        job se cerraria "completado" sin haber cargado nada."""
        worker = _worker()
        job, almacen = self._job_y_almacen(batch_size=5)
        worker._ejecutar(job, "sha", almacen, "columbia", 60)
        self.assertEqual(self.hojas_pedidas, [cr.HOJA_MATRIXIFY])

    def test_carga_todo_y_publica_el_avance_en_cada_bloque(self):
        worker = _worker()

        job, almacen = self._job_y_almacen(batch_size=2)
        guardados_antes = almacen.guardados
        worker._ejecutar(job, "sha", almacen, "columbia", 60)

        self.assertEqual(self.cargados, ["A", "B", "C", "D", "E"])
        self.assertEqual(job["status"], cr.JOB_COMPLETADO)
        self.assertEqual(job["processed_products"], 5)
        # Tres bloques de dos: el avance se publico DENTRO del bucle, no solo
        # al final. Sin esto, un runner que muere no deja constancia de nada.
        self.assertGreaterEqual(almacen.guardados - guardados_antes, 3)

    def test_no_recarga_lo_que_un_intento_anterior_ya_cargo(self):
        """Es la razon de ser de todo esto: el runner murio, vuelve a arrancar
        y no puede volver a escribir en Shopify lo que ya estaba bien."""
        worker = _worker()

        job, almacen = self._job_y_almacen(batch_size=2, completados=("A", "B"))
        worker._ejecutar(job, "sha", almacen, "columbia", 60)

        self.assertEqual(self.cargados, ["C", "D", "E"])
        self.assertNotIn("A", self.cargados)
        self.assertEqual(job["status"], cr.JOB_COMPLETADO)
        self.assertEqual(job["processed_products"], 5)

    def test_si_se_acaba_el_tiempo_deja_pendientes_y_vuelve_a_la_cola(self):
        """El runner tiene 6 h de tope. Al llegar al limite no puede darse por
        terminado: tiene que dejar los pendientes anotados para que el
        siguiente disparo los retome, en vez de que GitHub lo mate sin rastro.
        """
        worker = _worker()

        job, almacen = self._job_y_almacen(batch_size=2)
        # El reloj salta despues del primer bloque: un bloque cargado y el
        # resto pendiente, que es el caso que importa.
        reloj = iter([0, 1, 10 ** 9] + [10 ** 9] * 50)
        original = worker.time.monotonic
        worker.time.monotonic = lambda: next(reloj)
        try:
            worker._ejecutar(job, "sha", almacen, "columbia", 60)
        finally:
            worker.time.monotonic = original

        self.assertEqual(self.cargados, ["A", "B"])
        self.assertEqual(job["status"], cr.JOB_ENCOLADO)
        self.assertEqual(job["pending_keys"], ["C", "D", "E"])
        self.assertNotIn(job["status"], cr.ESTADOS_JOB_TERMINADO)
        self.assertIn("pendientes", job["message"])

    def test_el_excel_de_resultado_va_al_repositorio_privado(self):
        worker = _worker()

        job, almacen = self._job_y_almacen(batch_size=5)
        worker._ejecutar(job, "sha", almacen, "columbia", 60)

        self.assertTrue(job["result_path"])
        self.assertIn(job["result_path"], almacen.archivos)
        self.assertTrue(job["result_path"].startswith("catalog_tickets/"))


class _TablaFalsa:
    """Lo minimo que el worker le pide a un DataFrame de Matrixify."""

    def __init__(self, claves):
        self.claves = list(claves)
        self.empty = not claves


class TestMemoriaDeLaSesion(unittest.TestCase):
    """El Matrixify no puede quedarse fijo en la sesion.

    `build_columbia_matrixify` no esta cacheada: el DataFrame se reconstruye en
    cada rerun y se libera solo. Guardar una referencia en `st.session_state`
    lo fija hasta cerrar la sesion, y el contenedor de Streamlit Cloud da 1 GB
    por app compartido entre todos los que esten trabajando. Es el mismo error
    que se corrigio bajando los DataFrames gigantes a disco.
    """

    @staticmethod
    def _funcion(nombre):
        fuente = (ROOT / "app_matrixify.py").read_text(encoding="utf-8-sig")
        arbol = ast.parse(fuente)
        for nodo in ast.walk(arbol):
            if isinstance(nodo, ast.FunctionDef) and nodo.name == nombre:
                return nodo, fuente
        raise AssertionError(f"No encontre {nombre} en app_matrixify.py")

    def test_no_deja_el_dataframe_en_session_state(self):
        nodo, _ = self._funcion("recordar_matrixify_de_carga")
        parametros = {arg.arg for arg in nodo.args.args}
        self.assertIn("matrixify_df", parametros)
        guardados = []
        for sub in ast.walk(nodo):
            if isinstance(sub, ast.Dict):
                guardados.extend(
                    valor.id for valor in sub.values if isinstance(valor, ast.Name)
                )
        self.assertNotIn(
            "matrixify_df", guardados,
            "recordar_matrixify_de_carga guarda el DataFrame en la sesion: lo fija "
            "hasta cerrar sesion y el contenedor solo tiene 1 GB.",
        )

    def test_guarda_la_ruta_del_excel_que_ya_esta_en_disco(self):
        """No se arma un Excel nuevo: la pantalla ya escribio uno para el boton
        de descarga, y su primera hoja es la que lee el worker."""
        nodo, fuente = self._funcion("recordar_matrixify_de_carga")
        self.assertIn("excel_path", {arg.arg for arg in nodo.args.args})
        # Y el sitio de llamada tiene que pasarla, o llegaria siempre vacia.
        self.assertIn('excel_path=st.session_state.get("complete_excel_path")', fuente)

    def test_el_adjunto_sale_del_disco_no_de_un_excel_nuevo(self):
        nodo, _ = self._funcion("_adjuntar_matrixify_antes_de_cargar")
        llamadas = {
            sub.func.id for sub in ast.walk(nodo)
            if isinstance(sub, ast.Call) and isinstance(sub.func, ast.Name)
        }
        self.assertIn("_leer_excel_de_disco", llamadas)
        self.assertNotIn(
            "dataframe_to_excel_bytes", llamadas,
            "Armar el Excel al pulsar duplica en memoria justo en el peor momento.",
        )

    def test_si_el_archivo_se_perdio_pero_ya_hay_adjunto_no_corta(self):
        """El contenedor se reinicia y el Excel de disco desaparece. Si la
        solicitud ya tiene un Matrixify de un intento anterior, reintentar la
        carga tiene que seguir siendo posible."""
        nodo, _ = self._funcion("_adjuntar_matrixify_antes_de_cargar")
        cuerpo = ast.dump(nodo)
        self.assertIn("get_ticket", cuerpo)
        self.assertIn("matrixify", cuerpo)


class TestSinStreamlit(unittest.TestCase):
    def test_el_motor_no_importa_streamlit(self):
        fuente = (ROOT / "engines" / "carga_remota.py").read_text(encoding="utf-8")
        self.assertNotIn("import streamlit", fuente)


class TestRegistroGrande(unittest.TestCase):
    """Un registro de mas de 1 MB dejaba el job IMPOSIBLE de reanudar.

    Caso real (septiembre de 2026): la carga de Supermall llego a 1.280 de
    8.112 productos, corto por tiempo, y el `Re-run` murio a los 21 segundos
    con `Expecting value: line 1 column 1 (char 0)`. La Contents API de GitHub
    **deja de mandar `content` en los archivos de mas de 1 MB** -- responde con
    la cadena vacia -- y el registro habia crecido por encima de eso.

    Lo cruel es cuando falla: la reanudacion deja de funcionar justo en las
    cargas largas, que son las unicas que la necesitan.
    """

    def _almacen(self, respuestas, crudo=b""):
        almacen = cr.AlmacenJobsGitHub(
            owner="o", repo="r", token="t", branch="catalog-tickets")
        almacen._pedir = lambda *a, **k: respuestas
        almacen._pedir_crudo = lambda ruta: crudo
        return almacen

    def test_lee_por_la_via_cruda_cuando_content_llega_vacio(self):
        registro = {"id": "job-1", "site_key": "supermall", "completed_keys": ["A", "B"]}
        almacen = self._almacen(
            # Asi responde GitHub por encima de 1 MB: content vacio y
            # encoding "none". El sha SI viene, y es el que hace falta.
            {"content": "", "encoding": "none", "sha": "sha-grande"},
            crudo=json.dumps(registro).encode("utf-8"),
        )
        job, sha = almacen.leer("job-1")
        self.assertEqual(job["completed_keys"], ["A", "B"])
        self.assertEqual(sha, "sha-grande")

    def test_el_camino_normal_no_cambia(self):
        registro = {"id": "job-1", "completed_keys": ["A"]}
        contenido = base64.b64encode(json.dumps(registro).encode("utf-8")).decode()
        almacen = self._almacen({"content": contenido, "sha": "sha-chico"})
        # Si tocara la via cruda, esta prueba fallaria: devuelve b"".
        job, sha = almacen.leer("job-1")
        self.assertEqual(job["completed_keys"], ["A"])
        self.assertEqual(sha, "sha-chico")

    def test_un_archivo_que_no_existe_sigue_dando_None(self):
        almacen = self._almacen({"content": "", "encoding": "none", "sha": "x"}, crudo=b"")
        self.assertEqual(almacen.leer("job-1"), (None, None))


class TestFilasDeResultadoAcotadas(unittest.TestCase):
    """El registro se reescribe entero en cada bloque: no puede crecer sin techo."""

    def _filas(self, cuantas, resultado="OK"):
        return [{"Handle": f"h{i}", "Resultado": resultado} for i in range(cuantas)]

    def test_por_debajo_del_tope_no_toca_nada(self):
        job = {"result_rows": []}
        cr.registrar_avance_bloque(job, ok=3, filas=self._filas(3))
        self.assertEqual(len(job["result_rows"]), 3)
        self.assertNotIn("result_rows_omitidas", job)

    def test_conserva_TODOS_los_fallos_y_recorta_los_OK(self):
        """De 8.000 productos, lo que alguien va a mirar son los que fallaron.

        Recortar por antiguedad a secas se llevaria justo esos.
        """
        job = {"result_rows": []}
        problemas = self._filas(5, resultado="ERROR") + self._filas(5, resultado="PARCIAL")
        cr.registrar_avance_bloque(job, filas=problemas)
        cr.registrar_avance_bloque(job, filas=self._filas(50), ok=50)
        cr.acotar_filas_de_resultado(job, maximo=20)

        conservadas = job["result_rows"]
        self.assertEqual(len(conservadas), 20)
        no_ok = [f for f in conservadas if f["Resultado"] != "OK"]
        self.assertEqual(len(no_ok), 10, "no se conservaron todos los fallos")
        self.assertEqual(job["result_rows_omitidas"], 40)

    def test_lo_descartado_se_CUENTA(self):
        """Un informe al que le faltan filas y no lo dice es peor que uno corto."""
        job = {"result_rows": self._filas(30)}
        cr.acotar_filas_de_resultado(job, maximo=10)
        self.assertEqual(job["result_rows_omitidas"], 20)
        cr.acotar_filas_de_resultado(job, maximo=10)
        self.assertEqual(job["result_rows_omitidas"], 20, "no debe contar dos veces")

    def test_con_mas_fallos_que_el_tope_se_queda_con_los_ultimos(self):
        job = {"result_rows": self._filas(30, resultado="ERROR")}
        cr.acotar_filas_de_resultado(job, maximo=10)
        self.assertEqual(len(job["result_rows"]), 10)
        self.assertEqual(job["result_rows"][-1]["Handle"], "h29")


class TestEncadenarLaSiguienteTanda(unittest.TestCase):
    """Con 8.000 productos son seis tandas de 5,5 h. A mano no se termina nunca."""

    def setUp(self):
        self.worker = _worker()
        self.previos = {
            nombre: os.environ.get(nombre)
            for nombre in ("CARGA_REMOTA_TOKEN", "GITHUB_REPOSITORY", "GITHUB_REF_NAME")
        }
        os.environ["GITHUB_REPOSITORY"] = "HugoCamara7/catalogo-control-center"
        os.environ["GITHUB_REF_NAME"] = "main"
        self.llamadas = []
        self.original = cr.disparar_workflow
        self.worker.disparar_workflow = lambda **kw: self.llamadas.append(kw) or True

    def tearDown(self):
        self.worker.disparar_workflow = self.original
        for nombre, valor in self.previos.items():
            if valor is None:
                os.environ.pop(nombre, None)
            else:
                os.environ[nombre] = valor

    def test_dispara_el_MISMO_job_para_que_retome(self):
        os.environ["CARGA_REMOTA_TOKEN"] = "tok"
        job = {"id": "job-1", "site_key": "supermall", "ticket": "CAT-1"}
        self.assertTrue(self.worker._encadenar_siguiente_tanda(job))
        self.assertEqual(len(self.llamadas), 1)
        # El mismo job_id es lo que hace que la tanda nueva salte lo ya hecho.
        self.assertEqual(self.llamadas[0]["inputs"]["job_id"], "job-1")
        self.assertEqual(self.llamadas[0]["inputs"]["site_key"], "supermall")

    def test_el_aviso_de_token_no_se_lo_come_el_saneador(self):
        """`texto_publico` enmascara un "TOKEN" seguido de espacio o dos puntos.

        Lo destapo esta misma prueba: el aviso salia como
        "No hay CARGA_REMOTA_[oculto] siguiente tanda..." -- o sea que el
        mensaje que dice QUE secreto falta se comia justamente el nombre del
        secreto. Por eso detras va un punto.
        """
        import io, contextlib
        os.environ.pop("CARGA_REMOTA_TOKEN", None)
        salida = io.StringIO()
        with contextlib.redirect_stdout(salida):
            self.worker._encadenar_siguiente_tanda({"id": "job-1"})
        self.assertIn("CARGA_REMOTA_TOKEN", salida.getvalue())
        self.assertNotIn("[oculto]", salida.getvalue())

    def test_sin_token_no_dispara_y_no_levanta(self):
        os.environ.pop("CARGA_REMOTA_TOKEN", None)
        self.assertFalse(self.worker._encadenar_siguiente_tanda({"id": "job-1"}))
        self.assertEqual(self.llamadas, [])

    def test_un_fallo_al_disparar_no_tumba_la_tanda(self):
        os.environ["CARGA_REMOTA_TOKEN"] = "tok"
        def explota(**kw):
            raise cr.ErrorCargaRemota("permisos")
        self.worker.disparar_workflow = explota
        job = {"id": "job-1"}
        self.assertFalse(self.worker._encadenar_siguiente_tanda(job))
        self.assertTrue(any("encadenar" in str(e).lower() for e in job.get("events") or []))

    def test_sin_avance_NO_se_encadena(self):
        """Un job que no carga nada se relanzaria para siempre.

        Se lee del codigo del bucle: solo encadena si el contador de
        procesados subio respecto de lo que ya habia al arrancar la tanda.
        """
        fuente = inspect.getsource(self.worker._ejecutar)
        self.assertIn("hechos_al_arrancar", fuente)
        pos_guarda = fuente.index("> hechos_al_arrancar")
        pos_llamada = fuente.index("_encadenar_siguiente_tanda")
        self.assertLess(pos_guarda, pos_llamada, "la guarda va ANTES de encadenar")


class TestCredencialesQueFaltan(unittest.TestCase):
    """El log tiene que decir QUE secreto falta, no "revisa los secretos".

    Caso real: se disparo una carga de Supermall.pe y el runner murio con
    "Faltan credenciales de Shopify para el sitio supermall. Revisa los
    secretos del repositorio". El sitio estaba dado de alta en SITE_CONFIGS y
    mapeado en el workflow --lo que la prueba de mas abajo comprueba-- pero sus
    secretos de Actions nunca se crearon. El mensaje no lo decia, y desde la
    pantalla lo unico que se ve es que la carga fallo.
    """

    def setUp(self):
        self.worker = _worker()

    def test_nombra_las_dos_variables_del_sitio(self):
        faltantes = self.worker._credenciales_que_faltan(
            "supermall", {"shop_domain": "", "admin_access_token": ""})
        self.assertEqual(
            faltantes, ["SUPERMALL_SHOP_DOMAIN", "SUPERMALL_ADMIN_API_ACCESS_TOKEN"])

    def test_nombra_solo_la_que_falta(self):
        faltantes = self.worker._credenciales_que_faltan(
            "vans", {"shop_domain": "vans.myshopify.com", "admin_access_token": "   "})
        self.assertEqual(faltantes, ["VANS_ADMIN_API_ACCESS_TOKEN"])

    def test_hush_puppies_lleva_el_nombre_de_la_VARIABLE(self):
        """No el del secreto guardado, que va sin guion (HUSHPUPPIES_*).

        Quien lea el log tiene que poder buscar ese nombre en el bloque `env:`
        del workflow y ver de que secreto sale.
        """
        faltantes = self.worker._credenciales_que_faltan(
            "hush_puppies", {"shop_domain": "", "admin_access_token": ""})
        self.assertEqual(faltantes[0], "HUSH_PUPPIES_SHOP_DOMAIN")

    def test_el_nombre_acabado_en_TOKEN_sobrevive_al_saneado(self):
        """`texto_publico` enmascara un "TOKEN" seguido de un espacio.

        Comprobado: "SUPERMALL_ADMIN_API_ACCESS_TOKEN llegaron vacias" sale
        como "SUPERMALL_ADMIN_API_[oculto] vacias". El mensaje pone un punto
        detras del ultimo nombre justamente por eso, y esta prueba es lo que
        impide que una reescritura del texto se lleve el dato por delante.
        """
        faltantes = ["SUPERMALL_SHOP_DOMAIN", "SUPERMALL_ADMIN_API_ACCESS_TOKEN"]
        mensaje = self.worker._error_de_credenciales("supermall", faltantes)
        # Doble saneado: el del registro del job (500) y el de _decir (300).
        en_el_log = cr.texto_publico("ERROR: " + cr.texto_publico(mensaje, 500), 300)
        for nombre in faltantes:
            self.assertIn(nombre, en_el_log)
        # Y entra entero en el log: recortado, la parte que dice donde
        # agregarlos seria lo primero en irse.
        self.assertNotIn("…", en_el_log)

    def test_el_mensaje_no_lleva_ningun_VALOR(self):
        """Solo nombres de variable. El log de Actions es publico."""
        configuracion = {"shop_domain": "supermall.myshopify.com",
                         "admin_access_token": ""}
        faltantes = self.worker._credenciales_que_faltan("supermall", configuracion)
        mensaje = self.worker._error_de_credenciales("supermall", faltantes)
        self.assertNotIn("supermall.myshopify.com", mensaje)

    def test_se_EJECUTA_y_levanta_con_el_nombre_dentro(self):
        """Se corre `_ejecutar` de verdad, no se lee su codigo.

        Es la leccion de `start_suelto`: ocho pruebas leian su fuente con
        `inspect.getsource` y ninguna lo llamaba, asi que nadie vio el
        `AttributeError` que lo tumbaba en el primer clic. Leer el codigo no es
        ejecutarlo.
        """
        import types

        previos = {nombre: sys.modules.get(nombre)
                   for nombre in ("catalog_engine", "app_matrixify")}
        falso = types.ModuleType("catalog_engine")
        falso.read_matrixify_excel = lambda ruta: None
        falso.shopify_config_from_env = lambda site_key: {
            "shop_domain": "", "admin_access_token": "",
        }
        falso._env_name = lambda site_key, sufijo: f"{site_key.upper()}_{sufijo}"
        sys.modules["catalog_engine"] = falso
        sys.modules["app_matrixify"] = types.ModuleType("app_matrixify")
        try:
            with self.assertRaises(RuntimeError) as caja:
                self.worker._ejecutar({}, "sha", None, "supermall", 60)
        finally:
            for nombre, modulo in previos.items():
                if modulo is None:
                    sys.modules.pop(nombre, None)
                else:
                    sys.modules[nombre] = modulo
        self.assertIn("SUPERMALL_SHOP_DOMAIN", str(caja.exception))
        self.assertIn("SUPERMALL_ADMIN_API_ACCESS_TOKEN", str(caja.exception))


class TestWorkflow(unittest.TestCase):
    RUTA = ROOT / ".github" / "workflows" / "carga-shopify.yml"

    def test_el_workflow_existe_y_acepta_el_job(self):
        texto = self.RUTA.read_text(encoding="utf-8")
        self.assertIn("workflow_dispatch", texto)
        self.assertIn("job_id", texto)
        self.assertIn("worker_carga_shopify.py", texto)

    def test_todos_los_sitios_tienen_el_nombre_de_variable_que_espera_el_codigo(self):
        """`catalog_engine._env_name` arma la variable desde el site_key, y
        tiene que coincidir con la del workflow. Ojo con Hush Puppies: su
        site_key es `hush_puppies`, asi que la variable es HUSH_PUPPIES_*
        mientras el secreto guardado se llama HUSHPUPPIES_*. Sin el mapeo,
        falla con "faltan credenciales" y nada mas.

        La lista sale de SITE_CONFIGS y NO esta escrita a mano: con la lista
        fija, un sitio nuevo -- Supermall.pe fue el caso -- entraba en la app y
        su carga remota fallaba sin que ninguna prueba lo dijera.
        """
        from catalog_engine import _env_name
        from generate_columbia_matrixify import SITE_CONFIGS

        texto = self.RUTA.read_text(encoding="utf-8")
        for site_key in SITE_CONFIGS:
            for sufijo in ("SHOP_DOMAIN", "ADMIN_API_ACCESS_TOKEN"):
                with self.subTest(site_key=site_key, sufijo=sufijo):
                    self.assertIn(f"{_env_name(site_key, sufijo)}:", texto)

    def test_no_corre_dos_cargas_del_mismo_sitio_a_la_vez(self):
        texto = self.RUTA.read_text(encoding="utf-8")
        self.assertIn("concurrency:", texto)
        self.assertIn("cancel-in-progress: false", texto)

    def test_respeta_el_secreto_de_version_de_la_api(self):
        """Con la version escrita a mano, cambiarla en el secreto del
        repositorio no tenia efecto y la carga remota se quedaba en la
        anterior sin que nada lo dijera."""
        texto = self.RUTA.read_text(encoding="utf-8")
        self.assertIn("secrets.API_VERSION", texto)
        self.assertNotIn('API_VERSION: "2026-04"', texto)

    def test_no_sube_el_resultado_como_artifact_publico(self):
        """El repositorio es publico: un artifact con el detalle de la carga
        seria publicar el catalogo. El resultado va al repositorio privado."""
        self.assertNotIn("upload-artifact", self.RUTA.read_text(encoding="utf-8"))



class TestDiagnostico(unittest.TestCase):
    """Si la carga sobrevive al cierre de sesion, y que falta si no.

    Origen: `get_job_adapter` cae al adaptador local EN SILENCIO cuando falta
    configuracion. Es lo correcto -- sin `[carga_remota]` la app sigue
    funcionando igual que antes -- pero deja a quien lanza una carga de 1.000
    productos sin forma de saber si puede cerrar la pestana. Y esa es LA
    pregunta cuando la carga dura horas.
    """

    def test_con_todo_configurado_sobrevive(self):
        estado = cr.diagnostico_carga_remota(
            {"token": "ghp_x", "repository": "HugoCamara7/catalogo-control-center"},
            almacen_disponible=True)
        self.assertTrue(estado["sobrevive"])
        self.assertTrue(all(paso["estado"] == "ok" for paso in estado["pasos"]))

    def test_sin_token_no_sobrevive_y_dice_cual(self):
        estado = cr.diagnostico_carga_remota({}, almacen_disponible=True)
        self.assertFalse(estado["sobrevive"])
        fallo = [paso for paso in estado["pasos"] if paso["estado"] != "ok"]
        self.assertEqual([paso["clave"] for paso in fallo], ["token"])
        # Y el arreglo tiene que decir QUE token, que es donde se confunde todo
        # el mundo: no es el de [ticketing].
        self.assertIn("ticketing", fallo[0]["arreglo"])

    def test_sin_repositorio_de_datos_no_sobrevive(self):
        estado = cr.diagnostico_carga_remota({"token": "ghp_x"}, almacen_disponible=False)
        self.assertFalse(estado["sobrevive"])
        self.assertIn("almacen", [paso["clave"] for paso in estado["pasos"]
                                  if paso["estado"] != "ok"])

    def test_apagado_a_proposito_tambien_se_ve(self):
        estado = cr.diagnostico_carga_remota(
            {"token": "ghp_x", "enabled": "false"}, almacen_disponible=True)
        self.assertFalse(estado["sobrevive"])
        self.assertIn("habilitado", [paso["clave"] for paso in estado["pasos"]
                                     if paso["estado"] != "ok"])

    def test_todos_los_requisitos_traen_su_arreglo(self):
        estado = cr.diagnostico_carga_remota({}, almacen_disponible=False)
        for paso in estado["pasos"]:
            if paso["estado"] != "ok":
                self.assertTrue(paso["arreglo"], f"{paso['clave']} sin instrucciones")

    def test_el_aviso_se_dibuja_donde_se_lanza_la_carga(self):
        fuente = (ROOT / "app_matrixify.py").read_text(encoding="utf-8-sig")
        self.assertIn("def render_aviso_carga_remota(", fuente)
        # Antes de la casilla que dispara la sincronizacion, no despues.
        aviso = fuente.index("render_aviso_carga_remota()\n                    confirm_complete")
        self.assertGreater(aviso, 0)
        # Dos llamadas: la de Carga completa y la de Auditoria. La definicion
        # no cuenta, lleva `compacto=False` dentro del parentesis.
        self.assertGreaterEqual(fuente.count("render_aviso_carga_remota()"), 2)


if __name__ == "__main__":
    unittest.main(verbosity=2)
