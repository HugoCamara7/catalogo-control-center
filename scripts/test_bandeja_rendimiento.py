"""Pruebas de rendimiento de la bandeja: descargas en paralelo y cache.

Origen: la bandeja tardaba varios segundos con cada clic, incluso al marcar una
casilla. La API de contenidos de GitHub no devuelve el contenido al listar un
directorio, asi que `list_tickets` pedia el indice y despues UN ARCHIVO POR
SOLICITUD, encadenados. Con 31 solicitudes eran 32 viajes en serie, y la
pantalla llama a `list_tickets` dos veces por rerun mas un `get_ticket` para el
detalle: unas 65 peticiones seguidas por cada clic.

Aqui se comprueba que:
  - los archivos se bajan en paralelo, no uno detras de otro;
  - la lista se guarda unos segundos y no se vuelve a pedir;
  - cualquier escritura tira esa copia;
  - `get_ticket` NUNCA sale de la cache, porque de ahi viene el `_revision`
    con el que se guarda;
  - el control de duplicados fuerza una lectura fresca.

Ejecutar:  python scripts/test_bandeja_rendimiento.py
"""
import json
import shutil
import sys
import threading
import time
import unittest
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from ticket_system import (  # noqa: E402
    GitHubTicketStore,
    LocalTicketStore,
    MockJobAdapter,
    MockNotificationAdapter,
    ROLE_BRAND,
    TicketService,
    limpiar_cache_bandeja,
)


class StoreEspia(GitHubTicketStore):
    """Store de GitHub con la capa HTTP sustituida por archivos en memoria."""

    def __init__(self, cantidad=16, retardo=0.05, **kwargs):
        super().__init__(owner="forus", repo="datos", token="x",
                         branch="catalog-tickets", prefix="catalog_tickets", **kwargs)
        self.retardo = retardo
        self.archivos = {}
        for indice in range(1, cantidad + 1):
            ruta = "catalog_tickets/tickets/CAT-2026-%06d.json" % indice
            self.archivos[ruta] = {
                "code": "CAT-2026-%06d" % indice,
                "brand": "Columbia",
                "status": "pending_assignment",
                "created_at": "2026-08-%02dT10:00:00Z" % ((indice % 28) + 1),
            }
        self.peticiones = 0
        self.concurrencia_maxima = 0
        self._vivos = 0
        self._candado = threading.Lock()

    def _request(self, method, path, payload=None, ref=True):
        with self._candado:
            self.peticiones += 1
        if path == self.prefix + "/tickets":
            return [
                {"type": "file", "name": Path(ruta).name, "path": ruta,
                 "sha": self._sha(ruta)}
                for ruta in self.archivos
            ]
        return None

    def _sha(self, ruta):
        """El sha del blob: el hash del CONTENIDO, como el de GitHub."""
        datos = self.archivos.get(ruta)
        if datos is None:
            return ""
        return "sha-" + str(hash(json.dumps(datos, sort_keys=True)))

    def _get_file(self, path):
        with self._candado:
            self.peticiones += 1
            self._vivos += 1
            self.concurrencia_maxima = max(self.concurrencia_maxima, self._vivos)
        try:
            time.sleep(self.retardo)
            datos = self.archivos.get(path)
            if datos is None:
                return None, None
            return json.dumps(datos).encode("utf-8"), self._sha(path)
        finally:
            with self._candado:
                self._vivos -= 1


class TestDescargaParalela(unittest.TestCase):
    def setUp(self):
        limpiar_cache_bandeja()

    def tearDown(self):
        limpiar_cache_bandeja()

    def test_baja_los_archivos_a_la_vez_y_no_uno_detras_de_otro(self):
        store = StoreEspia(cantidad=16, retardo=0.05, max_workers=8)
        inicio = time.monotonic()
        tickets = store.list_tickets()
        transcurrido = time.monotonic() - inicio
        self.assertEqual(len(tickets), 16)
        self.assertGreater(store.concurrencia_maxima, 1,
                           "los archivos se siguen bajando uno detras de otro")
        # En serie serian 16 x 50 ms = 800 ms. Con 8 en paralelo, dos tandas.
        self.assertLess(transcurrido, 0.55, "tardo %.2fs, parece serie" % transcurrido)

    def test_respeta_el_tope_de_descargas(self):
        store = StoreEspia(cantidad=16, retardo=0.05, max_workers=4)
        store.list_tickets()
        self.assertLessEqual(store.concurrencia_maxima, 4)

    def test_devuelve_las_solicitudes_de_la_mas_nueva_a_la_mas_vieja(self):
        store = StoreEspia(cantidad=5, retardo=0)
        fechas = [t.get("created_at") for t in store.list_tickets()]
        self.assertEqual(fechas, sorted(fechas, reverse=True))

    def test_conserva_la_revision_de_cada_archivo(self):
        store = StoreEspia(cantidad=3, retardo=0)
        for ticket in store.list_tickets():
            ruta = "catalog_tickets/tickets/%s.json" % ticket["code"]
            self.assertEqual(ticket["_revision"], store._sha(ruta))


class TestRefrescoPorSha(unittest.TestCase):
    """Al refrescar, solo se baja lo que CAMBIO.

    Por que: la lista se guarda 25 segundos, asi que cada 25 segundos el
    siguiente clic la volvia a bajar ENTERA -- un archivo por solicitud. Medido
    con 120 solicitudes y 250 ms de latencia (lo que tarda api.github.com desde
    Streamlit Cloud): **121 viajes y 4,06 s** en un clic cualquiera. Eso es lo
    que se veia como "hago clic y se queda pegada la pantalla anterior", porque
    mientras el script espera a la red Streamlit deja a la vista, en gris, la
    pantalla del rerun anterior.

    El listado del directorio ya trae el `sha` de cada archivo, y ese sha es el
    del blob: el hash del contenido. Si no cambio, el archivo no cambio.
    """

    def setUp(self):
        limpiar_cache_bandeja()

    def tearDown(self):
        limpiar_cache_bandeja()

    def _refrescar(self, store):
        """Un refresco como el que hace el clic que cae tras los 25 segundos."""
        return store.list_tickets(force_refresh=True)

    def test_refrescar_sin_cambios_es_UN_solo_viaje(self):
        store = StoreEspia(cantidad=30, retardo=0)
        store.list_tickets()
        self.assertEqual(store.peticiones, 31, "la primera vez se bajan todas")
        store.peticiones = 0
        tickets = self._refrescar(store)
        self.assertEqual(len(tickets), 30)
        self.assertEqual(store.peticiones, 1,
                         "volvio a bajar archivos que no habian cambiado")

    def test_la_solicitud_que_cambia_SI_se_vuelve_a_bajar(self):
        store = StoreEspia(cantidad=10, retardo=0)
        store.list_tickets()
        ruta = "catalog_tickets/tickets/CAT-2026-000004.json"
        store.archivos[ruta]["status"] = "completed"
        store.peticiones = 0
        tickets = self._refrescar(store)
        self.assertEqual(store.peticiones, 2, "el listado y la que cambio")
        cambiada = [t for t in tickets if t["code"] == "CAT-2026-000004"][0]
        self.assertEqual(cambiada["status"], "completed",
                         "sirvio una copia vieja de una solicitud que cambio")

    def test_una_solicitud_nueva_se_baja_y_las_demas_no(self):
        store = StoreEspia(cantidad=5, retardo=0)
        store.list_tickets()
        ruta = "catalog_tickets/tickets/CAT-2026-000099.json"
        store.archivos[ruta] = {"code": "CAT-2026-000099", "brand": "Vans",
                                "status": "draft", "created_at": "2026-09-01T10:00:00Z"}
        store.peticiones = 0
        tickets = self._refrescar(store)
        self.assertEqual(store.peticiones, 2)
        self.assertEqual(len(tickets), 6)

    def test_el_resultado_es_EL_MISMO_que_bajandolo_todo(self):
        """Reusar por sha no puede cambiar ni un dato."""
        store = StoreEspia(cantidad=12, retardo=0)
        completo = store.list_tickets()
        limpiar_cache_bandeja()
        store2 = StoreEspia(cantidad=12, retardo=0)
        de_cero = store2.list_tickets()
        limpiar_cache_bandeja()
        store3 = StoreEspia(cantidad=12, retardo=0)
        store3.list_tickets()
        reusado = store3.list_tickets(force_refresh=True)
        self.assertEqual(completo, de_cero)
        self.assertEqual(completo, reusado)

    def test_sin_sha_en_el_listado_se_baja_todo(self):
        """Un GitHub que no diera el sha no puede dejar la bandeja vacia."""
        class SinSha(StoreEspia):
            def _sha(self, ruta):
                return ""
        store = SinSha(cantidad=6, retardo=0)
        store.list_tickets()
        store.peticiones = 0
        tickets = store.list_tickets(force_refresh=True)
        self.assertEqual(len(tickets), 6)
        self.assertEqual(store.peticiones, 7, "sin sha hay que bajarlas todas")

    def test_quien_recibe_la_lista_no_ensucia_la_cache(self):
        """La copia por sha se entrega en deepcopy, como la de la lista."""
        store = StoreEspia(cantidad=3, retardo=0)
        store.list_tickets()
        primera = store.list_tickets(force_refresh=True)
        primera[0]["brand"] = "TOCADO"
        segunda = store.list_tickets(force_refresh=True)
        self.assertNotIn("TOCADO", [t.get("brand") for t in segunda])


class TestCacheDeLaBandeja(unittest.TestCase):
    def setUp(self):
        limpiar_cache_bandeja()

    def tearDown(self):
        limpiar_cache_bandeja()

    def test_la_segunda_lectura_no_pide_nada(self):
        store = StoreEspia(cantidad=10, retardo=0)
        store.list_tickets()
        pedidas = store.peticiones
        self.assertEqual(len(store.list_tickets()), 10)
        self.assertEqual(store.peticiones, pedidas, "volvio a bajar la bandeja entera")

    def test_la_cache_es_del_proceso_y_no_de_la_instancia(self):
        """El servicio se construye de nuevo en cada rerun de Streamlit.

        Si la cache viviera en la instancia no serviria para nada: cada clic
        crea un `GitHubTicketStore` nuevo apuntando al mismo repositorio.
        """
        primera = StoreEspia(cantidad=10, retardo=0)
        primera.list_tickets()
        segunda = StoreEspia(cantidad=10, retardo=0)
        segunda.list_tickets()
        self.assertEqual(segunda.peticiones, 0)

    def test_force_refresh_vuelve_a_leer(self):
        store = StoreEspia(cantidad=10, retardo=0)
        store.list_tickets()
        pedidas = store.peticiones
        store.list_tickets(force_refresh=True)
        self.assertGreater(store.peticiones, pedidas)

    def test_invalidar_obliga_a_releer(self):
        store = StoreEspia(cantidad=10, retardo=0)
        store.list_tickets()
        pedidas = store.peticiones
        store.invalidate_cache()
        store.list_tickets()
        self.assertGreater(store.peticiones, pedidas)

    def test_la_cache_caduca(self):
        store = StoreEspia(cantidad=4, retardo=0, cache_seconds=1)
        store.list_tickets()
        pedidas = store.peticiones
        time.sleep(1.1)
        store.list_tickets()
        self.assertGreater(store.peticiones, pedidas)

    def test_quien_recibe_la_lista_no_ensucia_la_cache(self):
        store = StoreEspia(cantidad=4, retardo=0)
        primera = store.list_tickets()
        primera[0]["brand"] = "TOCADO"
        self.assertNotEqual(store.list_tickets()[0]["brand"], "TOCADO")

    def test_get_ticket_no_pasa_por_la_cache(self):
        """De `get_ticket` sale el `_revision` con el que se guarda. Servirlo
        de una copia vieja haria fallar cada guardado con "cambio en otra
        sesion", que es justo el bloqueo que se arreglo antes."""
        store = StoreEspia(cantidad=4, retardo=0)
        store.list_tickets()
        pedidas = store.peticiones
        store.get_ticket("CAT-2026-000001")
        self.assertGreater(store.peticiones, pedidas)


class EspiaLocal:
    """Envuelve el store local anotando si se pidio lectura fresca."""

    def __init__(self, store):
        self._store = store
        self.forzadas = []

    def __getattr__(self, nombre):
        return getattr(self._store, nombre)

    def list_tickets(self, force_refresh=False):
        self.forzadas.append(bool(force_refresh))
        return self._store.list_tickets(force_refresh=force_refresh)


class TestLecturasQueNoPuedenSerViejas(unittest.TestCase):
    """El control de duplicados no puede mirar una lista guardada."""

    def setUp(self):
        limpiar_cache_bandeja()
        self.temp_path = ROOT / ".test_ticket_data" / uuid.uuid4().hex
        self.temp_path.mkdir(parents=True, exist_ok=True)
        self.store = EspiaLocal(LocalTicketStore(self.temp_path))
        self.service = TicketService(
            self.store, notifier=MockNotificationAdapter(), jobs=MockJobAdapter()
        )
        self.brand = self.service.actor("brand@forus.pe", ROLE_BRAND, ["Columbia"])

    def tearDown(self):
        shutil.rmtree(self.temp_path, ignore_errors=True)
        limpiar_cache_bandeja()

    def _crear(self, sufijo):
        return self.service.create_ticket(
            self.brand,
            brand="Columbia",
            sites=["Columbia.pe"],
            filename="input_%s.xlsx" % sufijo,
            input_bytes=("excel-%s" % sufijo).encode(),
            report_bytes=("report-%s" % sufijo).encode(),
            template_version="2026.07",
            load_type="complete",
            summary={"products": 3, "model_colors": 2, "variants": 7,
                     "new_products": 2, "updated_products": 1, "blocked": 0},
            model_colors=["ABC-001-%s" % sufijo, "ABC-002-%s" % sufijo],
            priority="normal",
        )

    def test_el_control_de_duplicados_lee_fresco(self):
        """Dos envios seguidos dentro del TTL: el segundo tiene que ver al
        primero o vuelve el duplicado que se corrigio en agosto."""
        self._crear("a")
        self.assertTrue(any(self.store.forzadas),
                        "el control de duplicados acepto una lista guardada")

    def test_la_bandeja_normal_no_fuerza_lectura(self):
        self._crear("a")
        self.store.forzadas.clear()
        self.service.list_tickets(self.brand)
        self.assertEqual(self.store.forzadas, [False])


if __name__ == "__main__":
    unittest.main(verbosity=2)
