"""Pruebas del motor engines/audit.py

Ejecutar:  python scripts/test_engines_audit.py
"""
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
    ACCIONES,
    LIMA,
    OCULTO,
    AuditService,
    LocalAuditStore,
    build_event,
    formato_lima,
    nombre_desde_correo,
    sanitize_value,
)


class TestArquitectura(unittest.TestCase):
    def test_no_importa_streamlit(self):
        fuente = (ROOT / "engines" / "audit.py").read_text(encoding="utf-8")
        self.assertNotIn("import streamlit", fuente)

    def test_cubre_las_acciones_pedidas(self):
        for clave in [
            "ticket_create", "file_upload", "file_validate", "ticket_submit",
            "ticket_take", "ticket_assign", "ticket_state", "ticket_observe",
            "ticket_finish", "ticket_reopen", "load_select", "load_start",
            "load_complete", "load_fail", "file_download", "config_change",
            "user_change", "logout",
        ]:
            self.assertIn(clave, ACCIONES, f"falta la accion {clave}")


class TestNoGuardaSecretos(unittest.TestCase):
    def test_oculta_por_nombre_de_clave(self):
        for clave in ["password", "clave", "token", "api_key", "private_key", "Authorization"]:
            self.assertEqual(sanitize_value("valor-real", clave), OCULTO, f"fallo con {clave}")

    def test_oculta_tokens_por_su_forma(self):
        for valor in [
            "ghp_" + "a" * 30,
            "github_pat_" + "b" * 30,
            "shpat_" + "c" * 30,
            "-----BEGIN PRIVATE KEY-----",
        ]:
            self.assertEqual(sanitize_value(valor), OCULTO, f"fallo con {valor[:20]}")

    def test_no_toca_valores_normales(self):
        self.assertEqual(sanitize_value("Columbia"), "Columbia")
        self.assertEqual(sanitize_value("CAT-000241"), "CAT-000241")

    def test_el_evento_sanea_el_detalle(self):
        evento = build_event("login", "a@forus.pe", detalle="ghp_" + "x" * 30)
        self.assertEqual(evento["detalle"], OCULTO)


class TestBuildEvent(unittest.TestCase):
    def test_campos_obligatorios(self):
        evento = build_event("ticket_take", "mario.biggio@forus.pe", rol="brand", solicitud="CAT-1")
        for campo in ["ts", "accion", "accion_label", "modulo", "usuario", "nombre",
                      "rol", "solicitud", "valor_anterior", "valor_nuevo",
                      "resultado", "detalle"]:
            self.assertIn(campo, evento)

    def test_deriva_nombre_y_modulo(self):
        evento = build_event("ticket_take", "mario.biggio@forus.pe")
        self.assertEqual(evento["nombre"], "Mario Biggio")
        self.assertEqual(evento["modulo"], "Solicitudes")
        self.assertEqual(evento["accion_label"], "Tomar solicitud")

    def test_hora_de_peru(self):
        evento = build_event("login", "a@forus.pe")
        self.assertIn("-05:00", evento["ts"])

    def test_resultado_invalido_cae_en_ok(self):
        self.assertEqual(build_event("login", "a@forus.pe", resultado="raro")["resultado"], "ok")
        self.assertEqual(build_event("login", "a@forus.pe", resultado="error")["resultado"], "error")

    def test_correo_se_normaliza(self):
        self.assertEqual(build_event("login", "  MARIO@Forus.PE ")["usuario"], "mario@forus.pe")


class TestServicio(unittest.TestCase):
    def setUp(self):
        self.dir = Path(tempfile.mkdtemp())
        self.svc = AuditService(LocalAuditStore(self.dir))

    def tearDown(self):
        shutil.rmtree(self.dir, ignore_errors=True)

    def _sembrar(self):
        base = datetime(2026, 7, 15, 9, 0, tzinfo=LIMA)
        datos = [
            ("login", "hugo.camara@forus.pe", "admin", "", "ok"),
            ("ticket_create", "mario.biggio@forus.pe", "brand", "CAT-001", "ok"),
            ("file_upload", "mario.biggio@forus.pe", "brand", "CAT-001", "ok"),
            ("ticket_take", "hugo.camara@forus.pe", "admin", "CAT-001", "ok"),
            ("load_start", "hugo.camara@forus.pe", "admin", "CAT-001", "ok"),
            ("load_fail", "hugo.camara@forus.pe", "admin", "CAT-001", "error"),
            ("ticket_observe", "hugo.camara@forus.pe", "admin", "CAT-001", "ok"),
        ]
        for i, (accion, usuario, rol, sol, res) in enumerate(datos):
            self.svc.record(accion, usuario, rol=rol, solicitud=sol, resultado=res,
                            momento=base + timedelta(minutes=i))

    def test_append_y_lectura(self):
        self._sembrar()
        self.assertEqual(len(self.svc.all_events()), 7)

    def test_orden_mas_reciente_primero(self):
        self._sembrar()
        eventos = self.svc.all_events()
        self.assertEqual(eventos[0]["accion"], "ticket_observe")
        self.assertEqual(eventos[-1]["accion"], "login")

    def test_append_only_no_pisa_lo_anterior(self):
        self._sembrar()
        self.svc.record("logout", "hugo.camara@forus.pe", rol="admin")
        self.assertEqual(len(self.svc.all_events()), 8)

    def test_filtro_por_usuario(self):
        self._sembrar()
        self.assertEqual(len(self.svc.query(usuario="mario.biggio@forus.pe")), 2)

    def test_filtro_por_modulo_y_resultado(self):
        self._sembrar()
        # ticket_create + ticket_take + ticket_observe. file_upload cae en
        # "Input comercial" y load_* en "Carga de catalogo".
        self.assertEqual(len(self.svc.query(modulo="Solicitudes")), 3)
        self.assertEqual(len(self.svc.query(modulo="Input comercial")), 1)
        self.assertEqual(len(self.svc.query(modulo="Carga de catalogo")), 2)
        self.assertEqual(len(self.svc.query(modulo="Sesion")), 1)
        self.assertEqual(len(self.svc.query(resultado="error")), 1)

    def test_filtro_por_solicitud_via_busqueda(self):
        self._sembrar()
        self.assertEqual(len(self.svc.query(buscar="CAT-001")), 6)

    def test_busqueda_no_distingue_mayusculas(self):
        self._sembrar()
        self.assertEqual(len(self.svc.query(buscar="cat-001")), 6)

    def test_filtro_por_rango_de_fechas(self):
        self._sembrar()
        self.assertEqual(len(self.svc.query(desde="2026-07-15", hasta="2026-07-15")), 7)
        self.assertEqual(len(self.svc.query(desde="2026-07-16")), 0)

    def test_filtros_combinados(self):
        self._sembrar()
        self.assertEqual(len(self.svc.query(usuario="hugo.camara@forus.pe", resultado="error")), 1)

    def test_kpis(self):
        self._sembrar()
        k = self.svc.kpis(self.svc.all_events())
        self.assertEqual(k["total"], 7)
        self.assertEqual(k["usuarios"], 2)
        self.assertEqual(k["solicitudes"], 1)
        self.assertEqual(k["errores"], 1)

    def test_el_registro_nunca_lanza(self):
        class StoreRoto:
            persistente = False

            def append(self, evento):
                raise RuntimeError("disco lleno")

            def periods(self):
                return []

        self.assertIsNone(AuditService(StoreRoto()).record("login", "a@forus.pe"))

    def test_marca_si_es_persistente(self):
        self.assertFalse(self.svc.persistente)


class TestPaginacion(unittest.TestCase):
    def setUp(self):
        self.eventos = [build_event("login", f"u{i}@forus.pe") for i in range(95)]

    def test_treinta_por_pagina(self):
        p = AuditService.paginate(self.eventos, 1)
        self.assertEqual(len(p["filas"]), 30)
        self.assertEqual(p["paginas"], 4)
        self.assertEqual(p["total"], 95)
        self.assertEqual((p["desde"], p["hasta"]), (1, 30))

    def test_ultima_pagina_parcial(self):
        p = AuditService.paginate(self.eventos, 4)
        self.assertEqual(len(p["filas"]), 5)
        self.assertEqual((p["desde"], p["hasta"]), (91, 95))

    def test_pagina_fuera_de_rango_se_ajusta(self):
        self.assertEqual(AuditService.paginate(self.eventos, 99)["pagina"], 4)
        self.assertEqual(AuditService.paginate(self.eventos, 0)["pagina"], 1)

    def test_sin_eventos(self):
        p = AuditService.paginate([], 1)
        self.assertEqual((p["total"], p["paginas"], p["desde"]), (0, 1, 0))

    def test_las_paginas_no_se_solapan_ni_pierden_filas(self):
        vistas = []
        for n in range(1, 5):
            vistas.extend(AuditService.paginate(self.eventos, n)["filas"])
        self.assertEqual(len(vistas), 95)


class TestExportacion(unittest.TestCase):
    def test_encabezados_en_espanol(self):
        filas = AuditService.to_export_rows([build_event("ticket_take", "a@forus.pe", rol="admin", solicitud="CAT-9")])
        self.assertEqual(list(filas[0].keys())[:4], ["Fecha y hora (Peru)", "Usuario", "Correo", "Rol"])

    def test_exporta_todo_lo_filtrado_no_solo_la_pagina(self):
        eventos = [build_event("login", f"u{i}@forus.pe") for i in range(95)]
        self.assertEqual(len(AuditService.to_export_rows(eventos)), 95)

    def test_fecha_legible(self):
        evento = build_event("login", "a@forus.pe", momento=datetime(2026, 7, 30, 14, 32, 5, tzinfo=LIMA))
        self.assertEqual(AuditService.to_export_rows([evento])[0]["Fecha y hora (Peru)"], "30/07/2026 14:32:05")


class TestUtilidades(unittest.TestCase):
    def test_nombre_desde_correo(self):
        self.assertEqual(nombre_desde_correo("clara.gallastegui@forus.pe"), "Clara Gallastegui")
        self.assertEqual(nombre_desde_correo(""), "Usuario")

    def test_formato_lima_convierte_utc(self):
        self.assertIn("/", formato_lima("2026-07-30T19:32:05+00:00"))


if __name__ == "__main__":
    unittest.main(verbosity=2)
