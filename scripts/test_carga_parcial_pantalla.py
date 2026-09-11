#!/usr/bin/env python3
"""La pantalla de Carga parcial: la opcion que no dibujaba donde subir nada.

Reportado con una captura: *"No puedo subir mi archivo con el codigo modelo
color, el nombre corto y la descripcion corta para que actualice los campos"*.

`Nombre corto y Descripcion corta` estaba en el menu, tenia su rama en
`build_shopify_update_preview`, su rama en `apply_shopify_preview` y estaba en
`OPERACIONES_PARCIALES_REMOTAS` -- todo el motor, completo -- pero **nadie
habia escrito su `st.file_uploader`**. Sin archivo, `update_ready` no podia ser
cierto nunca, asi que la pantalla se quedaba para siempre en "Sube los archivos
requeridos para generar la carga parcial" **sin nada que subir**.

Por que no lo vio ninguna de las 63 pruebas de `test_carga_parcial_remota`:
todas prueban el MOTOR y el pegamento con el job. El fallo estaba en la
pantalla, que es donde este repositorio ya se llevo dos (`render_status_de_carga`
con la clave con tilde, y los tres fallos que dejaron el Mantenedor de Tallas
sin efecto). Un motor perfecto al que no se le puede entregar el archivo no
sirve para nada.

Estas pruebas ENTRAN A LA APP y miran lo que se dibuja. La regla que fijan es
general, no un caso: **toda opcion de Carga parcial tiene que ofrecer por donde
darle sus datos**, salvo las que estan declaradas aqui como que trabajan sobre
el catalogo entero. Una opcion nueva sin subidor rompe esta prueba en vez de
llegar a produccion como un menu que no hace nada.
"""

from __future__ import annotations

import io
import sys
import unittest
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
if str(RAIZ) not in sys.path:
    sys.path.insert(0, str(RAIZ))

import pandas as pd  # noqa: E402
from streamlit.testing.v1 import AppTest  # noqa: E402

APP = str(RAIZ / "app_matrixify.py")
TIEMPO = 300

TEXTOS_CORTOS = "Nombre corto y Descripcion corta"
AVISO_SIN_ARCHIVOS = "Sube los archivos requeridos"

# Las opciones que NO necesitan que nadie suba nada, y por que. Cada una es una
# decision, no un olvido: por eso estan escritas y no se deducen. Una opcion
# nueva que no este aqui tiene que dibujar su subidor.
SIN_ARCHIVO = {
    # Recalcula los siblings de TODO el catalogo: la entrada es la tienda.
    "Siblings",
    # Pantallas propias: cortan antes del analizar/ejecutar de la carga parcial
    # y dibujan sus propios controles.
    "Mantenedor de Videos",
    "Mantenedor de Tallas",
}


def abrir_carga_parcial(opcion=None, fuente="Shopify API"):
    """La app abierta en Carga parcial, con la opcion ya elegida.

    Se fuerza `Shopify API` porque es donde estaba el usuario: con `Respaldo
    Excel` la pantalla dibuja SIEMPRE el subidor del respaldo del sitio, y ese
    subidor de mas tapaba el fallo -- habia un `file_uploader` en pantalla, solo
    que no era donde iban los codigos.
    """
    at = AppTest.from_file(APP, default_timeout=TIEMPO)
    at.session_state["authenticated"] = True
    at.session_state["auth_user"] = "hugo"
    at.session_state["operation_area_choice"] = "Carga de catálogo"
    at.session_state["operation_mode_choice"] = "Carga parcial"
    at.run()
    if opcion is None:
        return at
    selector = [s for s in at.selectbox if s.label == "Que quieres actualizar"][0]
    selector.set_value(opcion).run()
    for radio in at.radio:
        if "Fuente de datos" in (radio.label or ""):
            radio.set_value(fuente).run()
            break
    return at


def subidores(at):
    return list(at.get("file_uploader"))


def etiquetas_de_subidores(at):
    return [u.proto.label for u in subidores(at)]


def opciones_del_menu(at):
    return list([s for s in at.selectbox if s.label == "Que quieres actualizar"][0].options)


class TestLaOpcionDeTextosCortosPideSuArchivo(unittest.TestCase):
    def test_dibuja_un_subidor(self):
        """El fallo exacto del reporte: con Shopify API no habia ni un
        `file_uploader` en toda la pantalla."""
        at = abrir_carga_parcial(TEXTOS_CORTOS)
        self.assertEqual(
            [str(e.value)[:300] for e in at.exception], [],
            "la pantalla revento al elegir la opcion")
        self.assertTrue(
            subidores(at),
            "la opcion de textos cortos no ofrece donde subir el Excel")

    def test_el_subidor_nombra_las_tres_columnas(self):
        """Un subidor sin decir que columnas espera obliga a adivinar."""
        at = abrir_carga_parcial(TEXTOS_CORTOS)
        etiqueta = " ".join(etiquetas_de_subidores(at)).lower()
        for palabra in ("modelo color", "nombre corto", "descripción corta"):
            self.assertIn(palabra, etiqueta)

    def test_acepta_excel(self):
        at = abrir_carga_parcial(TEXTOS_CORTOS)
        self.assertEqual(list(subidores(at)[-1].proto.type), [".xlsx", ".xls"])

    def test_tambien_lo_pide_con_respaldo_excel(self):
        """Con `Respaldo Excel` hay dos archivos: el catalogo del sitio y el de
        los textos. El segundo tiene que seguir estando."""
        at = abrir_carga_parcial(TEXTOS_CORTOS, fuente="Respaldo Excel")
        etiquetas = etiquetas_de_subidores(at)
        self.assertEqual(len(etiquetas), 2, etiquetas)
        self.assertIn("respaldo", etiquetas[0].lower())
        self.assertIn("nombre corto", etiquetas[1].lower())

    def test_dice_que_vacio_no_borra(self):
        """La regla que mas importa de esta operacion tiene que estar a la
        vista: un Excel con solo una de las dos columnas no puede leerse como
        que va a vaciar la otra en todo el catalogo."""
        at = abrir_carga_parcial(TEXTOS_CORTOS)
        pantalla = " ".join(str(c.value) for c in at.caption).lower()
        self.assertIn("no borra", pantalla)
        self.assertIn("custom.nombre_corto", pantalla)
        self.assertIn("custom.descripcion_corta", pantalla)


class TestNingunaOpcionSeQuedaSinPorDondeEntrar(unittest.TestCase):
    """La regla general. Es la prueba que habria atrapado el fallo el dia que
    se agrego la opcion al menu."""

    def test_cada_opcion_ofrece_donde_darle_sus_datos(self):
        menu = opciones_del_menu(abrir_carga_parcial())
        self.assertIn(TEXTOS_CORTOS, menu)
        for opcion in menu:
            if opcion in SIN_ARCHIVO:
                continue
            with self.subTest(opcion=opcion):
                at = abrir_carga_parcial(opcion)
                entradas = len(subidores(at)) + len(at.text_input)
                self.assertTrue(
                    entradas,
                    f"la opcion {opcion!r} no dibuja ni un subidor ni un campo: "
                    "no hay forma de darle los datos. Si de verdad trabaja sobre "
                    "el catalogo entero, decláralo en SIN_ARCHIVO.")

    def test_las_declaradas_sin_archivo_siguen_en_el_menu(self):
        """Si una de ellas se renombra, la excepcion de arriba deja de aplicar
        a nada y la prueba se vuelve un adorno."""
        menu = set(opciones_del_menu(abrir_carga_parcial()))
        self.assertEqual(SIN_ARCHIVO - menu, set())


class TestConElArchivoLaPantallaAvanza(unittest.TestCase):
    """Que el subidor exista no basta: hay que comprobar que el archivo
    desbloquea el analisis. Es la leccion de `start_suelto` -- leer el codigo
    no es ejecutarlo."""

    EXCEL = None

    @classmethod
    def setUpClass(cls):
        buffer = io.BytesIO()
        pd.DataFrame([
            {"Cod Mod Col": "AB-1", "Nombre Corto": "Trail",
             "Descripción Corta": "Chaqueta ligera"},
        ]).to_excel(buffer, index=False)
        cls.EXCEL = buffer.getvalue()

    def _subir(self, at):
        subidor = subidores(at)[-1]
        if not hasattr(subidor, "upload"):
            # AppTest solo sabe subir archivos desde streamlit 1.63. En una
            # version anterior el elemento se dibuja igual -- lo comprueban las
            # pruebas de arriba, que si corren siempre -- pero no se puede
            # rellenar desde la prueba.
            raise unittest.SkipTest(
                "este streamlit no permite subir archivos desde AppTest")
        subidor.upload("textos.xlsx", self.EXCEL)
        at.run()
        return at

    def test_con_el_excel_aparece_el_boton_de_analizar(self):
        at = self._subir(abrir_carga_parcial(TEXTOS_CORTOS))
        self.assertEqual([str(e.value)[:300] for e in at.exception], [])
        etiquetas = [b.label for b in at.button]
        # Sin Shopify en Secrets la pantalla corta con su aviso de
        # configuracion, que es correcto; lo que NO puede seguir diciendo es
        # que faltan archivos, porque ya se le dio el que pedia.
        avisos = [str(i.value) for i in at.info]
        falta_archivo = any(AVISO_SIN_ARCHIVOS in aviso for aviso in avisos)
        boton = any("Analizar carga parcial" in etiqueta for etiqueta in etiquetas)
        sin_shopify = any("Shopify API configurada" in str(e.value) for e in at.error)
        self.assertTrue(
            boton or sin_shopify,
            f"con el Excel subido la pantalla no ofrece analizar. Botones: {etiquetas}")
        self.assertFalse(
            falta_archivo,
            "la pantalla sigue pidiendo archivos despues de subir el Excel")


class TestElCaminoDeRespaldoExcelTambienLaConoce(unittest.TestCase):
    """La pantalla ofrece las dos fuentes. Con `Respaldo Excel` el motor es
    otro (`build_matrixify_updates`), y ahi la operacion no existia: devolvia
    "Operacion no soportada" despues de haber subido los dos archivos."""

    def _catalogo(self, nombre_corto="", descripcion_corta=""):
        from generate_columbia_matrixify import PRODUCT_KEY_COLUMN
        from engines.catalog_map import CAMPOS_POR_CLAVE
        return pd.DataFrame([{
            "ID": "111",
            "Handle": "chaqueta-ab-1",
            "Title": "Chaqueta",
            PRODUCT_KEY_COLUMN: "AB-1",
            CAMPOS_POR_CLAVE["nombre_corto"].columna: nombre_corto,
            CAMPOS_POR_CLAVE["descripcion_corta"].columna: descripcion_corta,
        }])

    def _correr(self, entrada, catalogo=None):
        from generate_columbia_matrixify import build_matrixify_updates
        return build_matrixify_updates(
            catalogo if catalogo is not None else self._catalogo(),
            update_input_df=pd.DataFrame(entrada),
            operation="short_texts",
        )

    def test_escribe_los_dos_metafields(self):
        from engines.catalog_map import CAMPOS_POR_CLAVE
        filas, issues = self._correr(
            [{"Mod-Col": "AB-1", "Nombre Corto": "Trail",
              "Descripción Corta": "Chaqueta ligera"}])
        self.assertEqual(len(filas), 1, issues.to_dict("records"))
        fila = filas.iloc[0]
        self.assertEqual(fila["Command"], "MERGE")
        self.assertEqual(fila[CAMPOS_POR_CLAVE["nombre_corto"].columna], "Trail")
        self.assertEqual(
            fila[CAMPOS_POR_CLAVE["descripcion_corta"].columna], "Chaqueta ligera")

    def test_vacio_no_borra(self):
        """Un Excel que solo trae una columna no puede dejar sin la otra a todo
        el catalogo. Es la misma regla que ya cumple la ruta de Shopify API."""
        from engines.catalog_map import CAMPOS_POR_CLAVE
        filas, _ = self._correr(
            [{"Mod-Col": "AB-1", "Nombre Corto": "Trail", "Descripción Corta": ""}],
            catalogo=self._catalogo(descripcion_corta="La que ya tenia"))
        self.assertEqual(len(filas), 1)
        self.assertNotIn(
            CAMPOS_POR_CLAVE["descripcion_corta"].columna, filas.columns)

    def test_lo_que_ya_dice_lo_mismo_no_se_reescribe(self):
        filas, issues = self._correr(
            [{"Mod-Col": "AB-1", "Nombre Corto": "Trail"}],
            catalogo=self._catalogo(nombre_corto="Trail"))
        self.assertTrue(filas.empty)
        self.assertEqual(
            issues["Problema"].tolist(),
            ["Sin cambios: las columnas vienen vacias o ya dicen lo mismo"])

    def test_no_se_copiaron_los_alias(self):
        """Los alias y el tipo salen de `engines/catalog_map`, el mismo
        diccionario de la carga completa y de la ruta de Shopify API. Un
        segundo juego de alias es la trampa de las dos `normalize_size`."""
        import inspect
        import generate_columbia_matrixify as gen
        fuente = " ".join(inspect.getsource(gen.build_matrixify_updates).split())
        self.assertIn("from engines.catalog_map import", fuente)
        for nombre in ("CAMPOS_POR_CLAVE", "CLAVES_TEXTOS_CORTOS", "valor_de_entrada"):
            self.assertIn(nombre, fuente)

    def test_los_dos_caminos_escriben_la_misma_columna(self):
        """Si la ruta de Shopify API y la del respaldo eligieran el nombre del
        metafield por su cuenta, el mismo Excel escribiria en dos sitios
        distintos segun por donde entrara."""
        import app_matrixify as app
        from engines.catalog_map import CAMPOS_POR_CLAVE
        producto = {
            "Mod-Col": "AB-1", "Handle": "chaqueta-ab-1",
            "Product ID": "gid://shopify/Product/1",
        }
        prev, _, _ = app.build_shopify_update_preview(
            [producto],
            pd.DataFrame([{"Mod-Col": "AB-1", "Nombre Corto": "Trail"}]),
            "short_texts",
            {"site_label": "Vans.pe", "site_key": "vans"},
        )
        campo = CAMPOS_POR_CLAVE["nombre_corto"]
        self.assertEqual(prev["Campo"].tolist(), [campo.columna])
        filas, _ = self._correr([{"Mod-Col": "AB-1", "Nombre Corto": "Trail"}])
        self.assertIn(campo.columna, filas.columns)


if __name__ == "__main__":
    unittest.main(verbosity=2)
