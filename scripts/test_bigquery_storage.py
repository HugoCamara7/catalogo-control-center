"""BigQuery: la via rapida, y que el respaldo REST siga estando (septiembre 2026).

Por que existe
--------------
El log de Streamlit Cloud se llenaba de este aviso, una vez por consulta:

    UserWarning: BigQuery Storage module not found, fetch data with the REST
    endpoint instead.

No es un error -- la app funciona --, pero dice que **cada** resultado de
BigQuery baja por el endpoint REST. Con el maestro ARTI, que son 653.000
filas, eso no es cosmetico: la Storage API entrega el mismo resultado en Arrow
y en streaming.

El detalle que hace peligroso el arreglo obvio: **la Storage API pide un
permiso IAM que el REST no pide** (`bigquery.readsessions.create`). La
libreria cae sola a REST cuando el paquete NO esta instalado, pero no cuando
esta y la cuenta de servicio no tiene el permiso: ahi levanta. O sea que
instalar el paquete a secas podria romper unos KPIs que hoy funcionan.

Por eso todas las lecturas pasan por `bigquery_a_dataframe`, que reintenta
por REST ante cualquier fallo. Estas pruebas fijan las dos mitades: que se
usa la via rapida, y que el respaldo existe y se usa.

Ejecutar:  python scripts/test_bigquery_storage.py
"""
import ast
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import app_matrixify  # noqa: E402


class JobFalso:
    """Un `QueryJob` de mentira que apunta como le pidieron el DataFrame."""

    def __init__(self, falla_la_via_rapida=False):
        self.falla_la_via_rapida = falla_la_via_rapida
        self.llamadas = []

    def to_dataframe(self, **kwargs):
        self.llamadas.append(kwargs)
        if self.falla_la_via_rapida and kwargs.get("create_bqstorage_client") is not False:
            raise RuntimeError("403 bigquery.readsessions.create denegado")
        return "DATAFRAME"


class TestLaViaRapida(unittest.TestCase):
    def test_se_pide_sin_forzar_el_rest(self):
        """Sin argumentos, la libreria usa la Storage API si la tiene."""
        job = JobFalso()
        self.assertEqual(app_matrixify.bigquery_a_dataframe(job), "DATAFRAME")
        self.assertEqual(job.llamadas, [{}])

    def test_no_se_consulta_dos_veces_cuando_todo_va_bien(self):
        job = JobFalso()
        app_matrixify.bigquery_a_dataframe(job)
        self.assertEqual(len(job.llamadas), 1)


class TestElRespaldoREST(unittest.TestCase):
    def test_un_fallo_de_permisos_no_deja_la_pantalla_sin_datos(self):
        job = JobFalso(falla_la_via_rapida=True)
        self.assertEqual(app_matrixify.bigquery_a_dataframe(job), "DATAFRAME")

    def test_el_reintento_pide_EXPLICITAMENTE_el_rest(self):
        job = JobFalso(falla_la_via_rapida=True)
        app_matrixify.bigquery_a_dataframe(job)
        self.assertEqual(job.llamadas, [{}, {"create_bqstorage_client": False}])

    def test_si_el_rest_tambien_falla_el_error_sube(self):
        """Un fallo de verdad -- red, credenciales -- no se puede tapar."""

        class SiempreFalla:
            def to_dataframe(self, **kwargs):
                raise RuntimeError("credenciales invalidas")

        with self.assertRaises(RuntimeError):
            app_matrixify.bigquery_a_dataframe(SiempreFalla())


def _arbol_y_lecturas(ruta):
    """El arbol del archivo y cada `.to_dataframe(...)` que hay dentro.

    Se parsea UNA vez y se devuelven los dos: los nodos de dos parseos
    distintos no son el mismo objeto, asi que compararlos por identidad
    -- que es como se sabe si una llamada esta dentro de un bloque --
    daria siempre que no.
    """
    arbol = ast.parse(Path(ruta).read_text(encoding="utf-8"))
    lecturas = [
        nodo for nodo in ast.walk(arbol)
        if isinstance(nodo, ast.Call)
        and isinstance(nodo.func, ast.Attribute)
        and nodo.func.attr == "to_dataframe"
    ]
    return arbol, lecturas


class TestNingunaLecturaSeQuedaFuera(unittest.TestCase):
    """El respaldo no sirve de nada si una lectura no pasa por el."""

    def test_app_matrixify_solo_llama_a_to_dataframe_dentro_del_helper(self):
        arbol, lecturas = _arbol_y_lecturas(ROOT / "app_matrixify.py")
        helper = next(
            n for n in ast.walk(arbol)
            if isinstance(n, ast.FunctionDef) and n.name == "bigquery_a_dataframe"
        )
        dentro = {id(n) for n in ast.walk(helper)}
        fuera = [n.lineno for n in lecturas if id(n) not in dentro]
        self.assertEqual(
            fuera, [],
            "hay lecturas de BigQuery que no pasan por bigquery_a_dataframe, "
            f"en las lineas {fuera}",
        )

    def test_el_generador_tambien_tiene_su_respaldo(self):
        """`generate_columbia_matrixify` corre tambien FUERA de Streamlit."""
        arbol, lecturas = _arbol_y_lecturas(ROOT / "generate_columbia_matrixify.py")
        ids_de_lecturas = {id(n) for n in lecturas}
        protegidas = []
        for nodo in ast.walk(arbol):
            if isinstance(nodo, ast.Try):
                for hijo in ast.walk(nodo):
                    if id(hijo) in ids_de_lecturas:
                        protegidas.append(hijo.lineno)
        todas = [n.lineno for n in lecturas]
        self.assertTrue(todas, "el generador ya no lee de BigQuery?")
        self.assertEqual(
            sorted(set(protegidas)), sorted(set(todas)),
            "alguna lectura del generador se quedo sin respaldo REST",
        )

    def test_el_reintento_del_generador_fuerza_el_rest(self):
        texto = (ROOT / "generate_columbia_matrixify.py").read_text(encoding="utf-8")
        self.assertIn("create_bqstorage_client=False", texto)


class TestElPaqueteEstaDeclarado(unittest.TestCase):
    def test_requirements_declara_bigquery_storage(self):
        texto = (ROOT / "requirements.txt").read_text(encoding="utf-8")
        self.assertIn("google-cloud-bigquery-storage", texto)

    def test_pyarrow_sigue_declarado(self):
        """La Storage API entrega Arrow: sin pyarrow no sirve de nada."""
        texto = (ROOT / "requirements.txt").read_text(encoding="utf-8")
        self.assertIn("pyarrow", texto)


if __name__ == "__main__":
    unittest.main(verbosity=2)
