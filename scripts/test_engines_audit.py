"""Pruebas del motor engines/audit.py y engines/storage_check.py

Ejecutar:  python scripts/test_engines_audit.py
"""
import json
import shutil
import sys
import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from engines.audit import (
    CAMPOS,
    CAMPOS_LEGADO,
    LIMA,
    OCULTO,
    AuditService,
    LocalAuditStore,
    build_event,
    formato_lima,
    nombre_desde_correo,
    normalizar,
    sanitize_value,
)
from engines.storage_check import check_github_store, check_local_store, resumen


class TestArquitectura(unittest.TestCase):
    def test_los_motores_no_importan_streamlit(self):
        for modulo in ["audit.py", "storage_check.py"]:
            fuente = (ROOT / "engines" / modulo).read_text(encoding="utf-8")
            self.assertNotIn("import streamlit", fuente, modulo)


class TestCompatibilidadConElLogViejo(unittest.TestCase):
    """Los registros escritos por log_user_activity deben seguir leyendose."""

    def test_conserva_los_8_campos_originales(self):
        for campo in ["fecha", "usuario", "nombre", "rol", "accion", "modulo", "sitio", "detalle"]:
            self.assertIn(campo, CAMPOS_LEGADO)
            self.assertIn(campo, CAMPOS)

    def test_formato_de_fecha_identico_al_viejo(self):
        evento = build_event("Inicio de sesion", "a@forus.pe",
                             momento=datetime(2026, 7, 30, 14, 32, 5, tzinfo=LIMA))
        self.assertEqual(evento["fecha"], "2026-07-30 14:32:05")

    def test_lee_un_registro_antiguo_sin_los_campos_nuevos(self):
        antiguo = {
            "fecha": "2026-07-27 10:00:00", "usuario": "hugo.camara@forus.pe",
            "nombre": "Hugo Camara", "rol": "Administrador",
            "accion": "Inicio de sesion", "modulo": "", "sitio": "columbia", "detalle": "",
        }
        fila = normalizar(antiguo)
        self.assertEqual(fila["usuario"], "hugo.camara@forus.pe")
        self.assertEqual(fila["marca"], "")
        self.assertEqual(fila["solicitud"], "")
        self.assertEqual(fila["resultado"], "ok")

    def test_registros_viejos_y_nuevos_conviven(self):
        carpeta = Path(tempfile.mkdtemp())
        try:
            (carpeta / "2026-07.jsonl").write_text(
                json.dumps({"fecha": "2026-07-27 10:00:00", "usuario": "a@forus.pe",
                            "accion": "Inicio de sesion"}) + "\n", encoding="utf-8")
            svc = AuditService(LocalAuditStore(carpeta))
            svc.record("Tomar solicitud", "b@forus.pe", solicitud="CAT-1",
                       momento=datetime(2026, 7, 28, 9, 0, tzinfo=LIMA))
            eventos = svc.all_events()
            self.assertEqual(len(eventos), 2)
            self.assertEqual(eventos[0]["accion"], "Tomar solicitud")
        finally:
            shutil.rmtree(carpeta, ignore_errors=True)


class TestNoGuardaSecretos(unittest.TestCase):
    def test_oculta_por_nombre_de_clave(self):
        for clave in ["password", "clave", "token", "api_key", "private_key", "Authorization"]:
            self.assertEqual(sanitize_value("valor-real", clave), OCULTO, clave)

    def test_oculta_tokens_por_su_forma(self):
        for valor in ["ghp_" + "a" * 30, "github_pat_" + "b" * 30,
                      "shpat_" + "c" * 30, "-----BEGIN PRIVATE KEY-----"]:
            self.assertEqual(sanitize_value(valor), OCULTO, valor[:16])

    def test_no_toca_valores_normales(self):
        self.assertEqual(sanitize_value("Columbia"), "Columbia")
        self.assertEqual(sanitize_value("CAT-2026-000008"), "CAT-2026-000008")

    def test_el_evento_sanea_detalle_y_extra(self):
        evento = build_event("x", "a@forus.pe", detalle="ghp_" + "x" * 30,
                             extra={"token": "abc", "marca": "Columbia"})
        self.assertEqual(evento["detalle"], OCULTO)
        self.assertEqual(evento["extra"]["token"], OCULTO)
        self.assertEqual(evento["extra"]["marca"], "Columbia")


class TestCamposPedidos(unittest.TestCase):
    """Los 11 campos del requerimiento."""

    def test_estan_todos(self):
        e = build_event("Cambiar estado", "hugo.camara@forus.pe", rol="Administrador",
                        marca="Columbia", modulo="Solicitudes", solicitud="CAT-2026-000008",
                        estado_anterior="pendiente", estado_nuevo="en_proceso",
                        resultado="ok", detalle="Tomada por el operador")
        self.assertEqual(e["usuario"], "hugo.camara@forus.pe")
        self.assertEqual(e["nombre"], "Hugo Camara")
        self.assertEqual(e["rol"], "Administrador")
        self.assertEqual(e["marca"], "Columbia")
        self.assertEqual(e["modulo"], "Solicitudes")
        self.assertEqual(e["solicitud"], "CAT-2026-000008")
        self.assertEqual(e["estado_anterior"], "pendiente")
        self.assertEqual(e["estado_nuevo"], "en_proceso")
        self.assertEqual(e["resultado"], "ok")
        self.assertTrue(e["fecha"])

    def test_hora_de_peru(self):
        e = build_event("x", "a@forus.pe", momento=datetime(2026, 7, 30, 23, 0, tzinfo=LIMA))
        self.assertEqual(e["fecha"], "2026-07-30 23:00:00")

    def test_resultado_invalido_cae_en_ok(self):
        self.assertEqual(build_event("x", "a@forus.pe", resultado="raro")["resultado"], "ok")
        self.assertEqual(build_event("x", "a@forus.pe", resultado="error")["resultado"], "error")


class TestServicio(unittest.TestCase):
    def setUp(self):
        self.dir = Path(tempfile.mkdtemp())
        self.svc = AuditService(LocalAuditStore(self.dir))
        base = datetime(2026, 7, 15, 9, 0, tzinfo=LIMA)
        datos = [
            ("Inicio de sesion", "hugo.camara@forus.pe", "Administrador", "", "", "ok"),
            ("Crear solicitud", "mario.biggio@forus.pe", "Comercial", "CAT-001", "Columbia", "ok"),
            ("Subir archivo", "mario.biggio@forus.pe", "Comercial", "CAT-001", "Columbia", "ok"),
            ("Tomar solicitud", "hugo.camara@forus.pe", "Administrador", "CAT-001", "Columbia", "ok"),
            ("Iniciar carga", "hugo.camara@forus.pe", "Administrador", "CAT-001", "Columbia", "ok"),
            ("Carga fallida", "hugo.camara@forus.pe", "Administrador", "CAT-001", "Columbia", "error"),
            ("Finalizar solicitud", "hugo.camara@forus.pe", "Administrador", "CAT-001", "Columbia", "ok"),
        ]
        for i, (accion, usuario, rol, sol, marca, res) in enumerate(datos):
            self.svc.record(accion, usuario, rol=rol, solicitud=sol, marca=marca,
                            resultado=res, momento=base + timedelta(minutes=i))

    def tearDown(self):
        shutil.rmtree(self.dir, ignore_errors=True)

    def test_todo_quedo_registrado(self):
        self.assertEqual(len(self.svc.all_events()), 7)

    def test_orden_mas_reciente_primero(self):
        self.assertEqual(self.svc.all_events()[0]["accion"], "Finalizar solicitud")

    def test_append_only(self):
        self.svc.record("Cierre de sesion", "hugo.camara@forus.pe")
        self.assertEqual(len(self.svc.all_events()), 8)

    def test_filtros(self):
        self.assertEqual(len(self.svc.query(usuario="mario.biggio@forus.pe")), 2)
        self.assertEqual(len(self.svc.query(resultado="error")), 1)
        self.assertEqual(len(self.svc.query(marca="Columbia")), 6)
        self.assertEqual(len(self.svc.query(solicitud="CAT-001")), 6)

    def test_filtro_por_fechas(self):
        self.assertEqual(len(self.svc.query(desde="2026-07-15", hasta="2026-07-15")), 7)
        self.assertEqual(len(self.svc.query(desde="2026-07-16")), 0)

    def test_buscador(self):
        self.assertEqual(len(self.svc.query(buscar="cat-001")), 6)
        self.assertEqual(len(self.svc.query(buscar="COLUMBIA")), 6)

    def test_filtros_combinados(self):
        self.assertEqual(len(self.svc.query(usuario="hugo.camara@forus.pe", resultado="error")), 1)

    def test_kpis(self):
        k = self.svc.kpis(self.svc.all_events())
        self.assertEqual((k["total"], k["usuarios"], k["solicitudes"], k["errores"]), (7, 2, 1, 1))

    def test_resumen_por_usuario(self):
        filas = self.svc.por_usuario(self.svc.all_events())
        self.assertEqual(len(filas), 2)
        self.assertEqual(filas[0]["Correo"], "hugo.camara@forus.pe")
        self.assertEqual(filas[0]["Acciones"], 5)
        self.assertEqual(filas[0]["Errores"], 1)

    def test_el_registro_nunca_lanza(self):
        class Roto:
            persistente = False

            def append(self, evento):
                raise RuntimeError("disco lleno")

            def periods(self):
                return []

        self.assertIsNone(AuditService(Roto()).record("x", "a@forus.pe"))

    def test_all_events_tolera_store_roto(self):
        class Roto:
            persistente = False

            def periods(self):
                raise RuntimeError("sin red")

        self.assertEqual(AuditService(Roto()).all_events(), [])


class TestPaginacion(unittest.TestCase):
    def setUp(self):
        self.eventos = [build_event("x", f"u{i}@forus.pe") for i in range(95)]

    def test_treinta_por_pagina(self):
        p = AuditService.paginate(self.eventos, 1)
        self.assertEqual((len(p["filas"]), p["paginas"], p["total"]), (30, 4, 95))
        self.assertEqual((p["desde"], p["hasta"]), (1, 30))

    def test_ultima_pagina_parcial(self):
        p = AuditService.paginate(self.eventos, 4)
        self.assertEqual((len(p["filas"]), p["desde"], p["hasta"]), (5, 91, 95))

    def test_pagina_fuera_de_rango(self):
        self.assertEqual(AuditService.paginate(self.eventos, 99)["pagina"], 4)
        self.assertEqual(AuditService.paginate(self.eventos, 0)["pagina"], 1)

    def test_sin_eventos(self):
        p = AuditService.paginate([], 1)
        self.assertEqual((p["total"], p["paginas"], p["desde"]), (0, 1, 0))

    def test_ninguna_fila_se_pierde_ni_se_repite(self):
        vistas = []
        for n in range(1, 5):
            vistas.extend(AuditService.paginate(self.eventos, n)["filas"])
        self.assertEqual(len(vistas), 95)


class TestExportacion(unittest.TestCase):
    def test_encabezados(self):
        filas = AuditService.to_export_rows([build_event("x", "a@forus.pe")])
        self.assertEqual(list(filas[0].keys())[:5],
                         ["Fecha y hora (Peru)", "Usuario", "Correo", "Rol", "Marca"])

    def test_exporta_todo_lo_filtrado(self):
        eventos = [build_event("x", f"u{i}@forus.pe") for i in range(95)]
        self.assertEqual(len(AuditService.to_export_rows(eventos)), 95)

    def test_fecha_legible(self):
        e = build_event("x", "a@forus.pe", momento=datetime(2026, 7, 30, 14, 32, 5, tzinfo=LIMA))
        self.assertEqual(AuditService.to_export_rows([e])[0]["Fecha y hora (Peru)"],
                         "30/07/2026 14:32:05")


class TestDiagnosticoAlmacenamiento(unittest.TestCase):
    def test_sin_configuracion_avisa_que_falta(self):
        r = check_github_store("", "", "", "")
        self.assertFalse(r["persistente"])
        self.assertEqual(r["pasos"][0]["estado"], "error")
        self.assertIn("owner", r["pasos"][0]["detalle"])

    def test_local_nunca_es_persistente(self):
        carpeta = Path(tempfile.mkdtemp())
        try:
            r = check_local_store(carpeta)
            self.assertFalse(r["persistente"])
            self.assertEqual(resumen(r)[0], "error")
        finally:
            shutil.rmtree(carpeta, ignore_errors=True)

    def test_el_diagnostico_no_devuelve_el_token(self):
        secreto = "ghp_" + "z" * 30
        r = check_github_store("o", "r", secreto, "b")
        self.assertNotIn(secreto, json.dumps(r))


class TestUtilidades(unittest.TestCase):
    def test_nombre_desde_correo(self):
        self.assertEqual(nombre_desde_correo("clara.gallastegui@forus.pe"), "Clara Gallastegui")
        self.assertEqual(nombre_desde_correo(""), "Usuario")

    def test_formato_lima_acepta_el_formato_viejo(self):
        self.assertEqual(formato_lima("2026-07-30 14:32:05"), "30/07/2026 14:32:05")

class TestEnvoltorioDeSolicitudes(unittest.TestCase):
    """AuditedTicketService debe registrar sin cambiar el comportamiento."""

    def setUp(self):
        from engines.audit import ACCIONES_TICKET, AuditedTicketService
        self.ACCIONES = ACCIONES_TICKET
        self.registros = []

        class ServicioFalso:
            def __init__(self):
                self.estado = "pending_assignment"
                self.store = "STORE"
                self.llamadas = []

            def get_ticket(self, actor, code):
                return {"code": code, "status": self.estado, "brand": "Columbia"}

            def approve(self, actor, code, comment=""):
                self.llamadas.append(("approve", code, comment))
                self.estado = "load_approved"
                return {"code": code, "status": self.estado, "brand": "Columbia"}

            def start_load(self, actor, code):
                self.estado = "loading"
                return {"code": code, "status": self.estado, "brand": "Columbia"}

            def reject(self, actor, code, comment=""):
                raise RuntimeError("sin permiso")

            def mark_notification_read(self, actor, code, notification_id):
                return {"code": code}

            def list_tickets(self, actor, filters=None, search=""):
                return [{"code": "CAT-1"}]

        self.falso = ServicioFalso()
        self.svc = AuditedTicketService(self.falso, lambda accion, **kw: self.registros.append((accion, kw)))
        self.actor = {"user": "hugo.camara@forus.pe", "role": "operator"}

    def test_devuelve_lo_mismo_que_el_servicio_real(self):
        r = self.svc.approve(self.actor, "CAT-1", "ok")
        self.assertEqual(r["code"], "CAT-1")
        self.assertEqual(r["status"], "load_approved")

    def test_no_altera_la_llamada_original(self):
        self.svc.approve(self.actor, "CAT-1", "revisado")
        self.assertEqual(self.falso.llamadas, [("approve", "CAT-1", "revisado")])

    def test_registra_estado_anterior_y_nuevo(self):
        self.svc.approve(self.actor, "CAT-1", "ok")
        accion, kw = self.registros[-1]
        self.assertEqual(accion, "Aprobar solicitud")
        self.assertEqual(kw["estado_anterior"], "pending_assignment")
        self.assertEqual(kw["estado_nuevo"], "load_approved")
        self.assertEqual(kw["solicitud"], "CAT-1")
        self.assertEqual(kw["marca"], "Columbia")
        self.assertEqual(kw["usuario"], "hugo.camara@forus.pe")
        self.assertEqual(kw["resultado"], "ok")

    def test_encadena_estados(self):
        self.svc.approve(self.actor, "CAT-1")
        self.svc.start_load(self.actor, "CAT-1")
        _, kw = self.registros[-1]
        self.assertEqual((kw["estado_anterior"], kw["estado_nuevo"]), ("load_approved", "loading"))

    def test_registra_el_error_y_lo_vuelve_a_lanzar(self):
        with self.assertRaises(RuntimeError):
            self.svc.reject(self.actor, "CAT-1", "no")
        accion, kw = self.registros[-1]
        self.assertEqual(accion, "Rechazar solicitud")
        self.assertEqual(kw["resultado"], "error")
        self.assertIn("sin permiso", kw["detalle"])

    def test_no_registra_ruido(self):
        self.svc.mark_notification_read(self.actor, "CAT-1", "n1")
        self.svc.list_tickets(self.actor)
        self.assertEqual(self.registros, [])

    def test_deja_pasar_atributos_normales(self):
        self.assertEqual(self.svc.store, "STORE")
        self.assertEqual(self.svc.list_tickets(self.actor), [{"code": "CAT-1"}])

    def test_un_fallo_del_registro_no_rompe_la_accion(self):
        from engines.audit import AuditedTicketService

        def registrar_roto(accion, **kw):
            raise RuntimeError("auditoria caida")

        svc = AuditedTicketService(self.falso, registrar_roto)
        self.assertEqual(svc.approve(self.actor, "CAT-1")["status"], "load_approved")

    def test_cubre_las_acciones_del_requerimiento(self):
        for metodo in ["create_ticket", "assign", "approve", "reject", "request_correction",
                       "start_load", "record_job_result", "cancel_ticket", "change_state",
                       "set_priority", "add_comment", "add_correction_version"]:
            self.assertIn(metodo, self.ACCIONES, metodo)
            self.assertTrue(self.ACCIONES[metodo], f"{metodo} no tiene etiqueta")

if __name__ == "__main__":
    unittest.main(verbosity=2)
