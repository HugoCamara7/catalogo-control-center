import io
import sys
import shutil
import unittest
import uuid
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from ticket_system import (  # noqa: E402
    LocalTicketStore,
    MockJobAdapter,
    MockNotificationAdapter,
    ROLE_ADMIN,
    ROLE_BRAND,
    ROLE_OPERATOR,
    STATE_APPROVED,
    STATE_ASSIGNED,
    STATE_COMPLETED,
    STATE_CORRECTED,
    STATE_FAILED,
    STATE_LOADING,
    STATE_OBSERVED,
    STATE_PENDING,
    STATE_REVIEW,
    TicketConflictError,
    TicketPermissionError,
    TicketService,
    TicketValidationError,
)


class CatalogTicketTests(unittest.TestCase):
    def setUp(self):
        self.temp_path = ROOT / ".test_ticket_data" / uuid.uuid4().hex
        self.temp_path.mkdir(parents=True, exist_ok=True)
        self.store = LocalTicketStore(self.temp_path)
        self.service = TicketService(
            self.store,
            notifier=MockNotificationAdapter(),
            jobs=MockJobAdapter(),
            sla_hours={"normal": 48},
        )
        self.brand = self.service.actor("brand@forus.pe", ROLE_BRAND, ["Columbia"])
        self.other_brand = self.service.actor("otro@forus.pe", ROLE_BRAND, ["Rockford"])
        self.operator = self.service.actor("operador@forus.pe", ROLE_OPERATOR, ["Columbia"])
        self.operator_two = self.service.actor("operador2@forus.pe", ROLE_OPERATOR, ["Columbia"])
        self.admin = self.service.actor("admin@forus.pe", ROLE_ADMIN, [])

    def tearDown(self):
        shutil.rmtree(self.temp_path, ignore_errors=True)

    def create_ticket(self, suffix="a", actor=None, brand="Columbia", priority="normal"):
        return self.service.create_ticket(
            actor or self.brand,
            brand=brand,
            sites=["Columbia.pe"],
            filename=f"input_{suffix}.xlsx",
            input_bytes=f"excel-{suffix}".encode(),
            report_bytes=f"report-{suffix}".encode(),
            template_version="2026.07",
            load_type="complete",
            summary={
                "products": 3,
                "model_colors": 2,
                "variants": 7,
                "new_products": 2,
                "updated_products": 1,
                "blocked": 0,
            },
            warnings=["Advertencia de prueba"],
            comment="Campana de prueba",
            model_colors=["ABC-001", "ABC-002"],
            priority=priority,
        )

    def prepare_approved(self, suffix="approved"):
        ticket = self.create_ticket(suffix)
        self.service.assign(self.operator, ticket["code"], self.operator["user"])
        self.service.start_review(self.operator, ticket["code"])
        return self.service.approve(self.operator, ticket["code"], "Conforme")

    def test_01_invalid_summary_without_products(self):
        with self.assertRaises(TicketValidationError):
            self.service.create_ticket(
                self.brand,
                brand="Columbia",
                sites=["Columbia.pe"],
                filename="bad.xlsx",
                input_bytes=b"bad",
                summary={"products": 0, "blocked": 0},
            )

    def test_02_blocked_file_cannot_create_ticket(self):
        with self.assertRaises(TicketValidationError):
            self.service.create_ticket(
                self.brand,
                brand="Columbia",
                sites=["Columbia.pe"],
                filename="blocked.xlsx",
                input_bytes=b"blocked",
                summary={"products": 2, "blocked": 1},
            )

    def test_03_ticket_creation_and_code(self):
        ticket = self.create_ticket()
        self.assertRegex(ticket["code"], r"^CAT-\d{4}-\d{6}$")
        self.assertEqual(ticket["status"], STATE_PENDING)
        self.assertEqual(ticket["summary"]["variants"], 7)
        self.assertEqual(len(ticket["versions"]), 1)

    def test_03b_ticket_accepts_streamlit_bytesio_attachments(self):
        ticket = self.service.create_ticket(
            self.brand,
            brand="Columbia",
            sites=["Columbia.pe"],
            filename="input_streamlit.xlsx",
            input_bytes=io.BytesIO(b"input-streamlit"),
            report_bytes=io.BytesIO(b"report-streamlit"),
            summary={"products": 1, "blocked": 0},
        )
        version = ticket["versions"][0]
        self.assertEqual(self.store.get_artifact(version["input_path"]), b"input-streamlit")
        self.assertEqual(self.store.get_artifact(version["report_path"]), b"report-streamlit")

    def test_04_duplicate_ticket_is_prevented(self):
        self.create_ticket("duplicate")
        with self.assertRaises(TicketConflictError):
            self.create_ticket("duplicate")

    def test_05_brand_cannot_see_another_request(self):
        ticket = self.create_ticket()
        with self.assertRaises(TicketPermissionError):
            self.service.get_ticket(self.other_brand, ticket["code"])

    def test_06_brand_cannot_start_load(self):
        ticket = self.create_ticket()
        with self.assertRaises(TicketPermissionError):
            self.service.start_load(self.brand, ticket["code"])

    def test_07_operator_sees_authorized_new_task(self):
        ticket = self.create_ticket()
        visible = self.service.list_tickets(self.operator)
        self.assertEqual([item["code"] for item in visible], [ticket["code"]])

    def test_08_assignment_and_admin_reassignment(self):
        ticket = self.create_ticket()
        assigned = self.service.assign(self.operator, ticket["code"], self.operator["user"])
        self.assertEqual(assigned["status"], STATE_ASSIGNED)
        reassigned = self.service.assign(self.admin, ticket["code"], self.operator_two["user"])
        self.assertEqual(reassigned["assignee"], self.operator_two["user"])

    def test_09_second_operator_can_reassign_ticket(self):
        ticket = self.create_ticket()
        self.service.assign(self.operator, ticket["code"], self.operator["user"])
        reassigned = self.service.assign(self.operator_two, ticket["code"], self.operator_two["user"])
        self.assertEqual(reassigned["assignee"], self.operator_two["user"])

    def test_10_request_correction_records_structured_observation(self):
        ticket = self.create_ticket()
        self.service.assign(self.operator, ticket["code"], self.operator["user"])
        self.service.start_review(self.operator, ticket["code"])
        observed = self.service.request_correction(
            self.operator,
            ticket["code"],
            "Corregir material",
            [{"Producto": "ABC-001", "Campo": "Material", "Valor encontrado": "", "Correccion recomendada": "Completar"}],
        )
        self.assertEqual(observed["status"], STATE_OBSERVED)
        self.assertEqual(observed["observations"][0]["status"], "open")

    def test_11_correction_creates_new_version_and_preserves_previous(self):
        ticket = self.create_ticket()
        self.service.assign(self.operator, ticket["code"], self.operator["user"])
        self.service.start_review(self.operator, ticket["code"])
        self.service.request_correction(self.operator, ticket["code"], "Corregir")
        corrected = self.service.add_correction_version(
            self.brand,
            ticket["code"],
            "input_corregido.xlsx",
            b"excel-corregido",
            b"reporte-corregido",
            {"products": 3, "model_colors": 2, "blocked": 0},
            "Listo",
        )
        self.assertEqual(corrected["status"], STATE_CORRECTED)
        self.assertEqual(len(corrected["versions"]), 2)
        self.assertNotEqual(corrected["versions"][0]["hash"], corrected["versions"][1]["hash"])

    def test_12_same_correction_version_is_rejected(self):
        ticket = self.create_ticket()
        self.service.assign(self.operator, ticket["code"], self.operator["user"])
        self.service.start_review(self.operator, ticket["code"])
        self.service.request_correction(self.operator, ticket["code"], "Corregir")
        with self.assertRaises(TicketConflictError):
            self.service.add_correction_version(
                self.brand,
                ticket["code"],
                ticket["filename"],
                b"excel-a",
                b"report",
                {"products": 3, "blocked": 0},
            )

    def test_13_approval(self):
        ticket = self.prepare_approved()
        self.assertEqual(ticket["status"], STATE_APPROVED)

    def test_14_requester_cannot_approve_own_ticket(self):
        ticket = self.create_ticket()
        requester_as_admin = self.service.actor(self.brand["user"], ROLE_ADMIN, [])
        self.service.assign(self.admin, ticket["code"], self.admin["user"])
        self.service.start_review(self.admin, ticket["code"])
        with self.assertRaises(TicketPermissionError):
            self.service.approve(requester_as_admin, ticket["code"])

    def test_15_dry_run(self):
        ticket = self.prepare_approved()
        simulated = self.service.run_dry_run(self.operator, ticket["code"])
        self.assertEqual(simulated["dry_run"]["status"], "completed")
        self.assertEqual(simulated["status"], STATE_APPROVED)

    def test_16_load_requires_dry_run(self):
        ticket = self.prepare_approved()
        with self.assertRaises(TicketValidationError):
            self.service.start_load(self.operator, ticket["code"])

    def test_17_mock_worker_starts_after_dry_run(self):
        ticket = self.prepare_approved()
        self.service.run_dry_run(self.operator, ticket["code"])
        loading = self.service.start_load(self.operator, ticket["code"])
        self.assertEqual(loading["status"], STATE_LOADING)
        self.assertTrue(loading["job"]["id"].startswith("MOCK-"))

    def test_18_completed_job(self):
        ticket = self.prepare_approved()
        self.service.run_dry_run(self.operator, ticket["code"])
        self.service.start_load(self.operator, ticket["code"])
        completed = self.service.record_job_result(self.admin, ticket["code"], success=True, result={"processed": 3})
        self.assertEqual(completed["status"], STATE_COMPLETED)
        self.assertEqual(completed["result"]["processed"], 3)

    def test_19_failed_job_can_retry(self):
        ticket = self.prepare_approved()
        self.service.run_dry_run(self.operator, ticket["code"])
        self.service.start_load(self.operator, ticket["code"])
        failed = self.service.record_job_result(self.admin, ticket["code"], success=False, error="Timeout")
        self.assertEqual(failed["status"], STATE_FAILED)
        retried = self.service.start_load(self.operator, ticket["code"])
        self.assertEqual(retried["status"], STATE_LOADING)

    def test_20_notifications_are_registered(self):
        ticket = self.create_ticket()
        self.assertEqual(ticket["notifications"][0]["event"], "new_ticket")
        self.assertEqual(ticket["notifications"][0]["email_status"], "prepared_mock")

    def test_21_audit_history_contains_transitions(self):
        ticket = self.create_ticket()
        self.service.assign(self.operator, ticket["code"], self.operator["user"])
        reviewed = self.service.start_review(self.operator, ticket["code"])
        actions = [event["action"] for event in reviewed["events"]]
        self.assertIn("ticket_created", actions)
        self.assertIn("assigned", actions)
        self.assertIn("status_changed", actions)

    def test_22_optimistic_concurrency_rejects_stale_write(self):
        ticket = self.create_ticket()
        stale = dict(ticket)
        self.service.add_comment(self.brand, ticket["code"], "Primer cambio")
        stale["brand_comment"] = "Cambio obsoleto"
        with self.assertRaises(TicketConflictError):
            self.store.update_ticket(stale, ticket["_revision"])

    def test_23_persistence_survives_new_service_instance(self):
        ticket = self.create_ticket()
        new_service = TicketService(LocalTicketStore(self.temp_path))
        loaded = new_service.get_ticket(self.brand, ticket["code"])
        self.assertEqual(loaded["file_hash"], ticket["file_hash"])
        self.assertEqual(new_service.store.get_artifact(loaded["versions"][0]["input_path"]), b"excel-a")

    def test_24_filters_and_search(self):
        first = self.create_ticket("filter-one")
        self.create_ticket("filter-two", priority="urgent")
        by_priority = self.service.list_tickets(self.admin, filters={"priority": "urgent"})
        self.assertEqual(len(by_priority), 1)
        by_search = self.service.list_tickets(self.admin, search="ABC-001")
        self.assertEqual(len(by_search), 2)
        by_code = self.service.list_tickets(self.admin, search=first["code"])
        self.assertEqual(len(by_code), 1)

    def test_25_brand_cannot_create_for_unassigned_brand(self):
        with self.assertRaises(TicketPermissionError):
            self.create_ticket("wrong-brand", brand="Rockford")

    def test_26_artifact_path_traversal_is_blocked(self):
        with self.assertRaises(TicketPermissionError):
            self.store.get_artifact("../fuera.txt")


if __name__ == "__main__":
    unittest.main(verbosity=2)
