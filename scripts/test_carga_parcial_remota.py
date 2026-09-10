#!/usr/bin/env python3
"""La carga PARCIAL tambien corre en el runner de GitHub Actions.

Pedido del usuario: *"voy a necesitar que me ayudes haciendo este worker o sea
los job de carga en actions en todas mis cargas parciales para poder cargar los
body html de todos los productos"* y, a continuacion, *"todo eso debemos ver la
manera que siempre este al aire funcionando"*.

La carga parcial se aplicaba SOLO dentro de la sesion de Streamlit. Una
Mantencion de Body HTML sobre el catalogo entero son miles de productos y horas
de reloj: cerrar la pestaña la detenia a medio camino, que es exactamente el
problema para el que se monto el runner -- solo que la carga completa lo tenia
y la parcial no.

**No se escribio un segundo motor**, y eso es lo que estas pruebas fijan: el
despacho por modo ya vivia en `_sync_job_run_one_product`, asi que un job con
`mode = "partial_<operacion>"` se aplica con `apply_shopify_preview` sin que el
worker tenga una sola rama nueva de carga. Lo que faltaba era que el registro
del job pudiera DECIR que es parcial y que la pantalla subiera la vista previa.

Y se EJECUTA, no se lee. Es la leccion de `start_suelto`, que llevaba semanas
roto con un `AttributeError` que ocho pruebas de `inspect.getsource` no podian
ver: leer el codigo no es ejecutarlo.
"""

from __future__ import annotations

import ast
import importlib.util
import inspect
import sys
import unittest
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
if str(RAIZ) not in sys.path:
    sys.path.insert(0, str(RAIZ))

import pandas as pd  # noqa: E402

from engines import carga_remota as cr  # noqa: E402


def cargar_worker():
    """El worker por RUTA, no como paquete.

    Es la misma forma que usa `test_carga_remota`: `scripts/` no es un paquete
    y convertirlo en uno con un `__init__.py` cambiaria como se importa cada
    prueba del repositorio para ahorrarse una linea aqui.
    """
    if "worker_carga_shopify" in sys.modules:
        return sys.modules["worker_carga_shopify"]
    spec = importlib.util.spec_from_file_location(
        "worker_carga_shopify", RAIZ / "scripts" / "worker_carga_shopify.py")
    modulo = importlib.util.module_from_spec(spec)
    sys.modules["worker_carga_shopify"] = modulo
    spec.loader.exec_module(modulo)
    return modulo


def preview(operacion="body", cuantos=2, **extra):
    """Una vista previa de carga parcial, como la arma `build_shopify_update_preview`."""
    filas = []
    for indice in range(1, cuantos + 1):
        fila = {
            "Accion": "Actualizar",
            "Sitio": "Vans.pe",
            "Operacion": operacion,
            "Mod-Col": f"AB-{indice}",
            "Product ID": f"gid://shopify/Product/{indice}",
            "Handle": f"zapatilla-ab-{indice}",
            "Campo": "Body HTML",
            "Valor actual": "",
            "Valor nuevo": f"<p>Descripcion {indice}</p>",
            "Estado": "OK",
            "Observacion": "",
        }
        fila.update(extra)
        filas.append(fila)
    return pd.DataFrame(filas)


class AlmacenFalso:
    """El repositorio de datos, en memoria. No sale a la red."""

    def __init__(self):
        self.jobs = {}
        self.archivos = {}
        self.prefix = "catalog_tickets"

    def ruta_de_matrixify(self, job_id, filename=""):
        return f"{self.prefix}/catalog_jobs/{job_id}/{filename or 'entrada.xlsx'}"

    def guardar_archivo(self, ruta, contenido, mensaje=""):
        self.archivos[ruta] = contenido

    def leer_archivo(self, ruta):
        return self.archivos[ruta]

    def guardar(self, job, sha=None, mensaje=""):
        self.jobs[job["id"]] = dict(job)
        return "sha-nuevo"

    def leer(self, job_id):
        job = self.jobs.get(job_id)
        return (dict(job) if job else None), "sha-viejo"


# --------------------------------------------------------------------------


class TestElRegistroSabeQueEsUnaCargaParcial(unittest.TestCase):
    """Hasta ahora el unico modo que llegaba al repositorio de datos era
    "complete". Un job que no puede decir que es parcial se ejecuta como si
    fuera un catalogo entero."""

    def test_el_modo_parcial_deja_la_operacion_a_la_vista(self):
        job = cr.nuevo_registro_job(
            codigo_solicitud="X", site_key="vans", matrixify_path="p",
            claves_producto=["a"], mode="partial_body")
        self.assertEqual(job["mode"], "partial_body")
        self.assertEqual(job["operacion"], "body")

    def test_la_hoja_del_excel_la_decide_el_modo(self):
        """Y no la pantalla: dos sitios eligiendo el nombre se separan sin que
        nadie lo note, y el runner bajaria un archivo donde no hay filas."""
        parcial = cr.nuevo_registro_job(
            codigo_solicitud="X", site_key="vans", matrixify_path="p",
            claves_producto=["a"], mode="partial_tags")
        completa = cr.nuevo_registro_job(
            codigo_solicitud="X", site_key="vans", matrixify_path="p",
            claves_producto=["a"])
        self.assertEqual(parcial["input_sheet"], cr.HOJA_VISTA_PREVIA)
        self.assertEqual(completa["input_sheet"], cr.HOJA_MATRIXIFY)

    def test_una_carga_parcial_NO_activa_el_inventario_en_sucursales(self):
        """Toca UN campo del producto. Activar de paso el inventario en todas
        las sucursales es un efecto que nadie pidio -- y es lo que ya hace el
        panel local, que pasa `activate_inventory_locations=False`."""
        parcial = cr.nuevo_registro_job(
            codigo_solicitud="X", site_key="vans", matrixify_path="p",
            claves_producto=["a"], mode="partial_body")
        completa = cr.nuevo_registro_job(
            codigo_solicitud="X", site_key="vans", matrixify_path="p",
            claves_producto=["a"])
        self.assertFalse(parcial["activate_inventory_locations"])
        self.assertTrue(completa["activate_inventory_locations"])

    def test_el_dato_explicito_manda_sobre_el_deducido(self):
        job = cr.nuevo_registro_job(
            codigo_solicitud="X", site_key="vans", matrixify_path="p",
            claves_producto=["a"], mode="partial_body", activar_sucursales=True)
        self.assertTrue(job["activate_inventory_locations"])

    def test_es_modo_parcial_distingue_los_dos(self):
        self.assertTrue(cr.es_modo_parcial("partial_body"))
        self.assertTrue(cr.es_modo_parcial("partial_technologies"))
        self.assertFalse(cr.es_modo_parcial("complete"))
        self.assertFalse(cr.es_modo_parcial(""))

    def test_el_prefijo_es_el_MISMO_que_mira_el_motor(self):
        """`_sync_job_run_one_product` deriva a `apply_shopify_preview` con
        `clean_value(mode).startswith("partial")`. Si aqui el prefijo fuera
        otro, el job parcial se cargaria como catalogo completo."""
        import app_matrixify as app
        fuente = inspect.getsource(app._sync_job_run_one_product)
        self.assertIn('startswith("partial")', fuente)
        self.assertTrue(cr.PREFIJO_MODO_PARCIAL.startswith("partial"))


class TestStartSueltoLanzaUnaParcial(unittest.TestCase):
    """Se EJECUTA el adaptador entero, con un almacen y un disparador falsos."""

    def _adaptador(self, almacen):
        disparos = []
        adaptador = cr.AdaptadorCargaActions(
            almacen, owner="o", repo="r", workflow="w.yml", ref="main", token="t")
        adaptador._disparar = lambda **kw: disparos.append(kw)
        return adaptador, disparos

    def test_el_job_guardado_lleva_modo_operacion_y_hoja(self):
        almacen = AlmacenFalso()
        adaptador, disparos = self._adaptador(almacen)
        resumen = adaptador.start_suelto(
            site_key="vans", matrixify_bytes=b"xlsx", filename="v.xlsx",
            claves_producto=["a", "b"], modo="partial_body", operacion="body",
            activar_sucursales=False)
        self.assertNotEqual(resumen["status"], cr.JOB_SIN_DISPARAR)
        guardado = almacen.jobs[resumen["id"]]
        self.assertEqual(guardado["mode"], "partial_body")
        self.assertEqual(guardado["operacion"], "body")
        self.assertEqual(guardado["input_sheet"], cr.HOJA_VISTA_PREVIA)
        self.assertFalse(guardado["activate_inventory_locations"])
        self.assertEqual(len(disparos), 1)

    def test_el_archivo_se_sube_ANTES_que_el_registro(self):
        """Con el registro guardado y el archivo no, el runner arrancaria para
        morir leyendo una ruta que no existe."""
        almacen = AlmacenFalso()
        orden = []
        almacen_guardar = almacen.guardar
        almacen_archivo = almacen.guardar_archivo
        almacen.guardar = lambda *a, **k: (orden.append("registro"), almacen_guardar(*a, **k))[1]
        almacen.guardar_archivo = lambda *a, **k: (orden.append("archivo"), almacen_archivo(*a, **k))[1]
        adaptador, _ = self._adaptador(almacen)
        adaptador.start_suelto(
            site_key="vans", matrixify_bytes=b"xlsx", modo="partial_tags", operacion="tags")
        self.assertEqual(orden[0], "archivo")

    def test_sin_vista_previa_el_mensaje_habla_de_carga_parcial(self):
        """"Pulsa Analizar input" manda a una pantalla que en parcial no
        existe. Un aviso que manda a hacer algo que no se puede hacer no tiene
        salida."""
        almacen = AlmacenFalso()
        adaptador, _ = self._adaptador(almacen)
        resumen = adaptador.start_suelto(
            site_key="vans", matrixify_bytes=b"", modo="partial_body")
        self.assertEqual(resumen["status"], cr.JOB_SIN_DISPARAR)
        self.assertIn("carga parcial", resumen["message"].lower())

    def test_la_carga_completa_no_cambio(self):
        almacen = AlmacenFalso()
        adaptador, _ = self._adaptador(almacen)
        resumen = adaptador.start_suelto(
            site_key="vans", matrixify_bytes=b"xlsx", claves_producto=["a"])
        guardado = almacen.jobs[resumen["id"]]
        self.assertEqual(guardado["mode"], "complete")
        self.assertEqual(guardado["input_sheet"], cr.HOJA_MATRIXIFY)
        self.assertTrue(guardado["activate_inventory_locations"])
        self.assertEqual(guardado["operacion"], "")


class TestLaVistaPreviaSobreviveAlExcel(unittest.TestCase):
    """La hoja NO puede llamarse `Products`.

    `dataframe_to_excel_bytes` le aplica `solo_columnas_matrixify` a esa hoja la
    escriba quien la escriba (seccion 5 untrigies), y `Operacion`,
    `Valor nuevo`, `Media IDs` y `Modo fotos` no son columnas de Matrixify: el
    archivo llegaria al runner con la identidad y sin una sola instruccion.
    """

    def _ida_y_vuelta(self, hoja, df):
        import app_matrixify as app
        from catalog_engine import read_matrixify_excel
        import tempfile
        payload = app.dataframe_to_excel_bytes({hoja: df})
        if hasattr(payload, "getvalue"):
            payload = payload.getvalue()
        with tempfile.NamedTemporaryFile(suffix=".xlsx", delete=False) as archivo:
            archivo.write(payload)
            ruta = archivo.name
        return read_matrixify_excel(ruta, sheet_name=hoja)

    def test_en_la_hoja_Vista_previa_no_se_pierde_ninguna_columna(self):
        original = preview()
        leido = self._ida_y_vuelta(cr.HOJA_VISTA_PREVIA, original)
        self.assertEqual(list(leido.columns), list(original.columns))
        self.assertEqual(leido["Valor nuevo"].tolist(), original["Valor nuevo"].tolist())

    def test_en_una_hoja_Products_se_pierde_TODO_lo_que_dice_que_escribir(self):
        """El contraste, medido: de 11 columnas sobrevive `Handle`."""
        leido = self._ida_y_vuelta("Products", preview())
        self.assertNotIn("Operacion", leido.columns)
        self.assertNotIn("Valor nuevo", leido.columns)

    def test_las_columnas_de_fotos_y_tecnologias_tambien_sobreviven(self):
        original = preview(
            operacion="photos", **{"Media IDs": "gid://1;gid://2", "Modo fotos": "replace"})
        leido = self._ida_y_vuelta(cr.HOJA_VISTA_PREVIA, original)
        self.assertIn("Media IDs", leido.columns)
        self.assertIn("Modo fotos", leido.columns)


class TestElRunnerAPLICALaCargaParcial(unittest.TestCase):
    """Se ejecuta el bloque de verdad, con un Shopify falso.

    Estas son las pruebas que importan: comprueban que un job parcial escribe
    en el producto correcto el valor correcto, no que el codigo lo diga.
    """

    def _correr_un_bloque(self, df, modo, parches):
        import app_matrixify as app
        previos = {nombre: getattr(app, nombre) for nombre in parches}
        for nombre, valor in parches.items():
            setattr(app, nombre, valor)
        try:
            job = app._create_sync_job(
                "vans", modo, df, batch_size=20, activate_inventory_locations=False)
            return app.process_sync_job_next_block(job["id"], {"shop_domain": "x", "admin_access_token": "y"})
        finally:
            for nombre, valor in previos.items():
                setattr(app, nombre, valor)

    def test_el_body_html_llega_al_producto(self):
        escrituras = []
        resultado = self._correr_un_bloque(
            preview(), "partial_body",
            {"product_update": lambda config, pid, **kw: escrituras.append((pid, kw))})
        self.assertEqual(len(escrituras), 2)
        self.assertEqual(escrituras[0][0], "gid://shopify/Product/1")
        self.assertEqual(escrituras[0][1]["body_html"], "<p>Descripcion 1</p>")
        self.assertEqual(resultado["ok_products"], 2)
        self.assertEqual(resultado["error_products"], 0)

    def test_el_titulo_tambien(self):
        escrituras = []
        df = preview(operacion="title")
        df["Valor nuevo"] = ["Nombre corto 1", "Nombre corto 2"]
        self._correr_un_bloque(
            df, "partial_title",
            {"product_update": lambda config, pid, **kw: escrituras.append((pid, kw))})
        self.assertEqual([kw["title"] for _, kw in escrituras],
                         ["Nombre corto 1", "Nombre corto 2"])

    def test_el_job_se_reanuda_y_no_reescribe_lo_ya_hecho(self):
        """Es lo que hace que un runner que muere a la mitad no vuelva a
        escribir en Shopify los productos que ya estaban bien."""
        import app_matrixify as app
        escrituras = []
        previo = app.product_update
        app.product_update = lambda config, pid, **kw: escrituras.append(pid)
        try:
            job = app._create_sync_job(
                "vans", "partial_body", preview(cuantos=4), batch_size=2,
                activate_inventory_locations=False)
            config = {"shop_domain": "x", "admin_access_token": "y"}
            app.process_sync_job_next_block(job["id"], config)
            self.assertEqual(len(escrituras), 2)
            app.process_sync_job_next_block(job["id"], config)
            self.assertEqual(len(escrituras), 4)
            self.assertEqual(len(set(escrituras)), 4, "un producto se cargo dos veces")
            final = app.process_sync_job_next_block(job["id"], config)
            self.assertEqual(len(escrituras), 4)
            self.assertEqual(final["status"], "completed")
        finally:
            app.product_update = previo

    def test_un_producto_que_falla_no_detiene_el_bloque(self):
        import app_matrixify as app

        def rompe(config, pid, **kw):
            if pid.endswith("/1"):
                raise RuntimeError("Shopify dijo que no")

        resultado = self._correr_un_bloque(
            preview(cuantos=3), "partial_body", {"product_update": rompe})
        self.assertEqual(resultado["error_products"], 1)
        self.assertEqual(resultado["ok_products"], 2)
        self.assertEqual(resultado["processed_products"], 3)


class TestElWorkerLeeLaHojaYLaBanderaDelRegistro(unittest.TestCase):
    def test_lee_la_hoja_del_registro_y_no_una_fija(self):
        worker = cargar_worker()
        fuente = inspect.getsource(worker._ejecutar)
        self.assertIn('job.get("input_sheet")', fuente)
        self.assertIn("sheet_name=hoja", fuente)

    def test_no_activa_sucursales_a_ciegas(self):
        """Estaba clavado en True. En una carga parcial eso activa inventario
        en todas las sucursales de productos a los que solo se les cambia el
        Body HTML."""
        worker = cargar_worker()
        arbol = ast.parse(inspect.getsource(worker._ejecutar).strip())
        valores = set()
        for nodo in ast.walk(arbol):
            if isinstance(nodo, ast.keyword) and nodo.arg == "activate_inventory_locations":
                valores.add(ast.unparse(nodo.value))
        self.assertEqual(len(valores), 1, valores)
        self.assertNotIn("True", valores)
        self.assertIn("activate_inventory_locations", valores.pop())

    def test_corta_si_la_hoja_no_es_una_vista_previa(self):
        """Sin la columna `Operacion`, `apply_shopify_preview` deja cada fila en
        OMITIDO y el job terminaria "completado" sin haber tocado un producto.
        Un exito falso es peor que un fallo."""
        worker = cargar_worker()
        fuente = inspect.getsource(worker._ejecutar)
        self.assertIn('"Operacion" not in matrixify_df.columns', fuente)


class TestLaPantallaOfreceElServidor(unittest.TestCase):
    def test_solo_las_operaciones_que_de_verdad_escriben(self):
        """`size_guides` devuelve OMITIDO -- `custom.guia_de_tallas` es
        page_reference --, asi que mandarla al runner gastaria una ejecucion
        entera para no escribir nada. `centry` y `sial` producen un Excel."""
        import app_matrixify as app
        self.assertNotIn("size_guides", app.OPERACIONES_PARCIALES_REMOTAS)
        self.assertNotIn("centry", app.OPERACIONES_PARCIALES_REMOTAS)
        self.assertIn("body", app.OPERACIONES_PARCIALES_REMOTAS)

    def test_son_exactamente_las_que_la_pantalla_deja_aplicar(self):
        """La lista del boton remoto y la de `can_apply` tienen que decir lo
        mismo: una operacion que se puede aplicar en la sesion y no en el
        servidor -- o al reves -- es un camino que aparece y desaparece.

        Habia dos listas escritas a mano, una en cada sitio. Ahora `can_apply`
        lee la constante, asi que no pueden discrepar; esta prueba falla si
        alguien vuelve a escribir la tupla dentro de `main`.
        """
        import app_matrixify as app
        fuente = inspect.getsource(app.main)
        linea = next(l for l in fuente.splitlines() if "can_apply = update_operation in" in l)
        self.assertIn("OPERACIONES_PARCIALES_REMOTAS", linea, linea.strip())

    def test_cada_operacion_remota_sabe_escribir(self):
        """Toda operacion de la lista tiene que tener su rama en
        `apply_shopify_preview`. Una que no la tenga se manda al runner, gasta
        una ejecucion entera y deja cada fila en OMITIDO."""
        import app_matrixify as app
        fuente = inspect.getsource(app.apply_shopify_preview)
        for operacion in app.OPERACIONES_PARCIALES_REMOTAS:
            self.assertIn(f'operation == "{operacion}"', fuente, operacion)

    def test_cada_operacion_remota_esta_en_el_menu(self):
        """Una operacion que el motor sabe hacer y el menu no ofrece no existe
        para quien usa la app."""
        import app_matrixify as app
        fuente = inspect.getsource(app.main)
        for operacion in app.OPERACIONES_PARCIALES_REMOTAS:
            self.assertIn(f'"{operacion}",', fuente, operacion)



    def test_la_vista_previa_va_en_la_hoja_IMPORTADA_no_en_una_escrita_a_mano(self):
        import app_matrixify as app
        self.assertEqual(app.HOJA_VISTA_PREVIA_CARGA, cr.HOJA_VISTA_PREVIA)
        fuente = inspect.getsource(app.render_boton_carga_remota_parcial)
        self.assertIn("HOJA_VISTA_PREVIA_CARGA", fuente)
        self.assertNotIn('{"Products"', fuente)

    def test_dice_que_falta_en_vez_de_no_dibujarse(self):
        """Un boton que no se dibuja y no explica por que se lee como "no
        funciona". Es la misma regla de `render_boton_carga_remota`."""
        import app_matrixify as app
        fuente = inspect.getsource(app.render_boton_carga_remota_parcial)
        self.assertIn("render_aviso_carga_remota()", fuente)
        self.assertIn("no está configurada", fuente)

    def test_la_parcial_pide_explicitamente_no_activar_sucursales(self):
        import app_matrixify as app
        fuente = inspect.getsource(app.render_boton_carga_remota_parcial)
        self.assertIn("activar_sucursales=False", fuente)

    def test_no_se_escribio_un_segundo_lanzador(self):
        """Dos motores de carga se separan sin que nadie lo note."""
        import app_matrixify as app
        fuente = inspect.getsource(app.render_boton_carga_remota_parcial)
        self.assertIn("lanzar_carga_remota_suelta(", fuente)
        arbol = ast.parse(Path(RAIZ / "app_matrixify.py").read_text(encoding="utf-8"))
        lanzadores = [n.name for n in ast.walk(arbol)
                      if isinstance(n, ast.FunctionDef) and "start_suelto" in ast.unparse(n)]
        self.assertEqual(lanzadores, ["lanzar_carga_remota_suelta"], lanzadores)


class TestNombreCortoYDescripcionCorta(unittest.TestCase):
    """La operacion parcial nueva: `short_texts`.

    `custom.nombre_corto` y `custom.descripcion_corta` se ven en la PLP y en la
    PDP, y hasta ahora **solo** se podian escribir con una carga COMPLETA, que
    exige el input comercial entero. Para corregirlos en el catalogo ya cargado
    no habia ningun camino.
    """

    BRAND = {"site_label": "Vans.pe", "site_key": "vans", "label": "Vans"}

    def _producto(self, mod_col, nombre_corto="", descripcion_corta=""):
        return {
            "Mod-Col": mod_col, "Handle": f"zapa-{mod_col.lower()}",
            "Product ID": f"gid://shopify/Product/{mod_col[-1]}", "Title": mod_col,
            "Metafield: custom.nombre_corto [single_line_text_field]": nombre_corto,
            "Metafield: custom.descripcion_corta [single_line_text_field]": descripcion_corta,
            "Variants": [],
        }

    def _vista_previa(self, productos, entrada):
        import app_matrixify as app
        return app.build_shopify_update_preview(
            productos, pd.DataFrame(entrada), "short_texts", self.BRAND)

    def test_escribe_los_dos_metafields(self):
        prev, _, _ = self._vista_previa(
            [self._producto("AB-1", nombre_corto="Viejo")],
            [{"Mod-Col": "AB-1", "Nombre corto": "Trail Runner",
              "Descripcion corta": "Ligera y respirable"}])
        self.assertEqual(sorted(prev["Metafield"].tolist()),
                         ["custom.descripcion_corta", "custom.nombre_corto"])
        self.assertEqual(set(prev["Tipo metafield"]), {"single_line_text_field"})

    def test_vacio_NO_borra(self):
        """Un Excel que solo trae la columna Nombre corto no puede dejar sin
        descripcion a todo el catalogo. Es la regla que la guia del input
        comercial ya declara para la carga completa."""
        prev, _, _ = self._vista_previa(
            [self._producto("AB-1", descripcion_corta="La buena")],
            [{"Mod-Col": "AB-1", "Nombre corto": "Trail Runner", "Descripcion corta": ""}])
        self.assertEqual(prev["Metafield"].tolist(), ["custom.nombre_corto"])

    def test_lo_que_ya_dice_lo_mismo_no_se_reescribe(self):
        prev, issues, _ = self._vista_previa(
            [self._producto("AB-1", nombre_corto="Igual")],
            [{"Mod-Col": "AB-1", "Nombre corto": "Igual"}])
        self.assertTrue(prev.empty)
        self.assertIn("Sin cambios", issues["Problema"].iloc[0])

    def test_los_alias_del_excel_son_los_MISMOS_de_la_carga_completa(self):
        """Se importan de `engines/catalog_map`. Un segundo diccionario de
        alias haria que el mismo Excel se leyera distinto segun por donde
        pasara -- la trampa de las dos `normalize_size`."""
        for columna in ("Nombre Corto", "Nombre breve", "Short name"):
            prev, _, _ = self._vista_previa(
                [self._producto("AB-1")], [{"Mod-Col": "AB-1", columna: "Trail"}])
            self.assertEqual(prev["Valor nuevo"].tolist(), ["Trail"], columna)

    def test_no_se_copio_la_tabla_de_metafields(self):
        import app_matrixify as app
        fuente = inspect.getsource(app.build_shopify_update_preview)
        self.assertIn("from engines.catalog_map import CAMPOS_POR_CLAVE, valor_de_entrada", fuente)

    def test_se_aplica_de_verdad_contra_shopify(self):
        """Se EJECUTA el bloque, con un Shopify falso."""
        import app_matrixify as app
        prev, _, _ = self._vista_previa(
            [self._producto("AB-1")],
            [{"Mod-Col": "AB-1", "Nombre corto": "Trail", "Descripcion corta": "Ligera"}])
        escrituras = []
        previo = app.metafields_set
        app.metafields_set = lambda cfg, mf: escrituras.append(mf[0])
        try:
            job = app._create_sync_job(
                "vans", "partial_short_texts", prev, batch_size=10,
                activate_inventory_locations=False)
            resultado = app.process_sync_job_next_block(
                job["id"], {"shop_domain": "x", "admin_access_token": "y"})
        finally:
            app.metafields_set = previo
        self.assertEqual(
            {(e["namespace"], e["key"], e["value"]) for e in escrituras},
            {("custom", "nombre_corto", "Trail"), ("custom", "descripcion_corta", "Ligera")})
        self.assertEqual(resultado["error_products"], 0)

    def test_una_fila_sin_metafield_no_borra_nada(self):
        """El contrato al ESCRIBIR, no solo al previsualizar: un valor vacio
        que llegue al aplicador se omite en vez de escribir "" en la tienda."""
        import app_matrixify as app
        fila = pd.DataFrame([{
            "Operacion": "short_texts", "Handle": "h", "Mod-Col": "AB-1",
            "Product ID": "gid://shopify/Product/1",
            "Metafield": "custom.nombre_corto", "Tipo metafield": "single_line_text_field",
            "Valor nuevo": "",
        }])
        escrituras = []
        previo = app.metafields_set
        app.metafields_set = lambda cfg, mf: escrituras.append(mf)
        try:
            resultado = app.apply_shopify_preview({"shop_domain": "x"}, fila)
        finally:
            app.metafields_set = previo
        self.assertEqual(escrituras, [])
        self.assertEqual(resultado["Resultado"].iloc[0], "OMITIDO")

class TestElMantenedorDeTallasTambienCorreEnElServidor(unittest.TestCase):
    """Revisar el catalogo entero de un sitio y arreglarlo son miles de
    productos, y cada uno son tres viajes a Shopify. Dentro de la sesion eso se
    detiene al cerrar la pestaña.

    Lo que NO se hizo: un tercer formato de archivo en el worker. El plan de
    tallas se convierte en una vista previa de carga parcial y se aplica con la
    MISMA `apply_shopify_preview`, asi que hereda el job, el worker, los
    bloques, la reanudacion y el panel de estado sin una linea nueva de carga.
    """

    def _plan(self, **extra):
        plan = {
            "Mod-Col": "VN-1", "Handle": "vans-1", "Title": "Old Skool", "Marca": "Vans",
            "Product ID": "gid://shopify/Product/1", "Type": "Zapatillas",
            "Genero": "Masculino", "Actual": ["8", "9"], "Propuesto": ["40.5", "42"],
            "Nota": "",
        }
        plan.update(extra)
        return plan

    def test_la_vista_previa_lleva_lo_que_el_aplicador_necesita(self):
        import app_matrixify as app
        prev = app.tallas_vista_previa([self._plan()], app.get_brand_config("vans"))
        for campo in app.CAMPOS_PLAN_DE_TALLAS:
            self.assertIn(campo, prev.columns, campo)
        self.assertEqual(prev["Operacion"].tolist(), ["tallas"])
        self.assertEqual(prev["Site key"].tolist(), ["vans"])

    def test_el_TIPO_y_el_GENERO_viajan(self):
        """Sin ellos el conversor sale None al replanificar y el cambio de
        escala **no se aplica nunca** -- la pantalla contesta "Ya estaba bien al
        releerlo". Es el fallo de la seccion 5 sexdecies, que ninguna de las 34
        pruebas del motor vio porque estaba en el pegamento."""
        import app_matrixify as app
        prev = app.tallas_vista_previa([self._plan()], app.get_brand_config("vans"))
        self.assertEqual(prev["Type"].tolist(), ["Zapatillas"])
        self.assertEqual(prev["Genero"].tolist(), ["Masculino"])

    def test_se_aplica_con_la_MISMA_funcion_de_la_pantalla(self):
        import app_matrixify as app
        prev = app.tallas_vista_previa([self._plan()], app.get_brand_config("vans"))
        vistos = []
        previo = app.tallas_aplicar_producto
        app.tallas_aplicar_producto = lambda cfg, plan, bc: (
            vistos.append((plan["Product ID"], bc.get("site_key"), plan["Type"], plan["Genero"])),
            (True, [{"Paso": "Cambiar escala", "Estado": "ok", "Detalle": "8 -> 40.5"}]))[1]
        try:
            resultado = app.apply_shopify_preview({"shop_domain": "x"}, prev)
        finally:
            app.tallas_aplicar_producto = previo
        self.assertEqual(vistos, [("gid://shopify/Product/1", "vans", "Zapatillas", "Masculino")])
        self.assertEqual(resultado["Resultado"].tolist(), ["OK"])

    def test_sin_sitio_NO_se_adivina(self):
        """Escribir en la tienda equivocada es peor que no escribir."""
        import app_matrixify as app
        fila = pd.DataFrame([{
            "Operacion": "tallas", "Handle": "h", "Mod-Col": "VN-1",
            "Product ID": "gid://1", "Site key": "", "Estado": "OK"}])
        llamadas = []
        previo = app.tallas_aplicar_producto
        app.tallas_aplicar_producto = lambda *a, **k: llamadas.append(a)
        try:
            resultado = app.apply_shopify_preview({"shop_domain": "x"}, fila)
        finally:
            app.tallas_aplicar_producto = previo
        self.assertEqual(llamadas, [])
        self.assertEqual(resultado["Resultado"].iloc[0], "ERROR")

    def test_ya_estaba_bien_no_se_reporta_como_arreglado(self):
        """`tallas_aplicar_producto` devuelve ok=True cuando al releer el
        producto ya estaba correcto. Decirlo OK a secas haria creer que se
        escribio algo."""
        import app_matrixify as app
        prev = app.tallas_vista_previa([self._plan()], app.get_brand_config("vans"))
        previo = app.tallas_aplicar_producto
        app.tallas_aplicar_producto = lambda cfg, plan, bc: (
            True, [{"Paso": "Comparar", "Estado": "aviso",
                    "Detalle": "Ya estaba bien al releerlo. No se escribio nada."}])
        try:
            resultado = app.apply_shopify_preview({"shop_domain": "x"}, prev)
        finally:
            app.tallas_aplicar_producto = previo
        self.assertEqual(resultado["Resultado"].iloc[0], "OMITIDO")

    def test_el_bloque_por_bloque_funciona_igual_que_en_las_demas(self):
        """La razon de ser de todo esto: si el runner muere, se retoma."""
        import app_matrixify as app
        planes = [self._plan(**{"Mod-Col": f"VN-{i}", "Handle": f"vans-{i}",
                                "Product ID": f"gid://shopify/Product/{i}"}) for i in range(1, 5)]
        prev = app.tallas_vista_previa(planes, app.get_brand_config("vans"))
        hechos = []
        previo = app.tallas_aplicar_producto
        app.tallas_aplicar_producto = lambda cfg, plan, bc: (
            hechos.append(plan["Product ID"]),
            (True, [{"Paso": "Cambiar escala", "Estado": "ok", "Detalle": "d"}]))[1]
        try:
            job = app._create_sync_job("vans", "partial_tallas", prev, batch_size=2,
                                       activate_inventory_locations=False)
            config = {"shop_domain": "x", "admin_access_token": "y"}
            app.process_sync_job_next_block(job["id"], config)
            self.assertEqual(len(hechos), 2)
            final = app.process_sync_job_next_block(job["id"], config)
            self.assertEqual(len(set(hechos)), 4)
            self.assertEqual(final["status"], "completed")
        finally:
            app.tallas_aplicar_producto = previo

    def test_el_camino_REMOTO_entero_funciona(self):
        """Vista previa -> Excel -> lo que lee el runner -> escritura.

        En memoria no basta: lo que el runner ve es el archivo, y `Site key`,
        `Type` y `Genero` no son columnas de Matrixify. Si la hoja se llamara
        `Products` las tres desaparecerian y el conversor saldria `None`.
        """
        import tempfile
        import app_matrixify as app
        from catalog_engine import read_matrixify_excel

        prev = app.tallas_vista_previa([self._plan()], app.get_brand_config("vans"))
        payload = app.dataframe_to_excel_bytes({cr.HOJA_VISTA_PREVIA: prev})
        if hasattr(payload, "getvalue"):
            payload = payload.getvalue()
        with tempfile.NamedTemporaryFile(suffix=".xlsx", delete=False) as archivo:
            archivo.write(payload)
            ruta = archivo.name
        leido = read_matrixify_excel(ruta, sheet_name=cr.hoja_de_entrada("partial_tallas"))
        for columna in ("Site key", "Type", "Genero", "Product ID"):
            self.assertIn(columna, leido.columns, columna)

        vistos = []
        previo = app.tallas_aplicar_producto
        app.tallas_aplicar_producto = lambda cfg, plan, bc: (
            vistos.append((bc.get("site_key"), plan["Type"], plan["Genero"])),
            (True, [{"Paso": "Cambiar escala", "Estado": "ok", "Detalle": "d"}]))[1]
        try:
            resultado = app.apply_shopify_preview({"shop_domain": "x"}, leido)
        finally:
            app.tallas_aplicar_producto = previo
        self.assertEqual(vistos, [("vans", "Zapatillas", "Masculino")])
        self.assertEqual(resultado["Resultado"].tolist(), ["OK"])

    def test_la_pantalla_ofrece_el_servidor_antes_que_la_sesion(self):
        import app_matrixify as app
        fuente = inspect.getsource(app.render_mantenedor_tallas)
        self.assertIn("render_boton_carga_remota_parcial(", fuente)
        self.assertIn("tallas_vista_previa(", fuente)
        posicion_remoto = fuente.index("render_boton_carga_remota_parcial(")
        posicion_local = fuente.index('st.button("Aplicar"')
        self.assertLess(posicion_remoto, posicion_local)

    def test_no_se_reimplemento_el_arreglo_de_tallas(self):
        """Un segundo camino que escriba tallas se separa del primero sin que
        nadie lo note. La rama del aplicador llama a la funcion de siempre."""
        import app_matrixify as app
        fuente = inspect.getsource(app.apply_shopify_preview)
        rama = fuente.split('operation == "tallas"', 1)[1].split("elif operation ==", 1)[0]
        self.assertIn("tallas_aplicar_producto(", rama)
        for prohibida in ("product_option_update(", "product_reorder_variants("):
            self.assertNotIn(prohibida, rama, prohibida)


class TestElMantenedorDeVideosTambienCorreEnElServidor(unittest.TestCase):
    """Es donde MAS se nota.

    Cada video son decenas de MB bajados del bucket y vueltos a subir, y ademas
    `wait_video_media_ready` espera hasta **20 x 6 s por video** a que Shopify
    termine de procesarlo -- por eso `VIDEO_MODELOS_POR_BLOQUE` es 5 y no 20.
    Una lista de 50 codigos puede pasar de una hora con el navegador abierto, y
    cerrarlo la corta a la mitad.
    """

    def _filas(self):
        return [
            {"Código Modelo Color": "2044361-6RX", "Marca": "Columbia",
             "Origen de la marca": "columna Marca del Excel", "Estado": "Listo para cargar",
             "URL": "https://b/COLUMBIA/2044361_6RX_2.mp4", "Handle": "h1",
             "Product ID": "gid://1", "Detalle": ""},
            {"Código Modelo Color": "1424692-2KQ", "Marca": "Columbia",
             "Origen de la marca": "metacampo del producto", "Estado": "Sin confirmar",
             "URL": "https://b/COLUMBIA/1424692_2KQ_2.mp4", "Handle": "h2",
             "Product ID": "gid://2", "Detalle": ""},
        ]

    def _previa(self, **kw):
        import app_matrixify as app
        return app.video_vista_previa(
            self._filas(), app.get_brand_config("vans"), **kw)

    def test_la_marca_del_EXCEL_solo_viaja_si_de_ahi_salio(self):
        """`video_publicar` distingue la columna Marca del Excel de la marca de
        la pantalla, y ese orden decide **la carpeta del bucket**. Mandar la del
        metacampo como si fuera del Excel buscaria el mp4 donde no esta."""
        prev = self._previa(marca_pantalla="Vans", reemplazar=False)
        self.assertEqual(prev["Marca excel"].tolist(), ["Columbia", ""])
        self.assertEqual(prev["Marca pantalla"].tolist(), ["Columbia", "Columbia"])

    def test_se_publica_con_la_MISMA_funcion_de_la_pantalla(self):
        import app_matrixify as app
        prev = self._previa(marca_pantalla="Vans", reemplazar=True)
        llamadas = []
        previo = app.video_publicar

        def falso(cfg, site_key, mod_col, marca_excel="", marca_pantalla="",
                  reemplazar=False, progreso=None):
            llamadas.append((site_key, mod_col, marca_excel, reemplazar))
            return {"ok": True, "Posición": 2, "pasos": {"subir": {"estado": "ok", "detalle": "d"}}}

        app.video_publicar = falso
        try:
            resultado = app.apply_shopify_preview({"shop_domain": "x"}, prev)
        finally:
            app.video_publicar = previo
        self.assertEqual(llamadas, [
            ("vans", "2044361-6RX", "Columbia", True),
            ("vans", "1424692-2KQ", "", True),
        ])
        self.assertEqual(resultado["Resultado"].tolist(), ["OK", "OK"])

    def test_la_posicion_equivocada_se_reporta_como_FALLO(self):
        """Regla de la seccion 5 sexies: un video en la posicion 3 se ve
        normal en la ficha y no lo revisa nadie. Es el peor error silencioso."""
        import app_matrixify as app
        prev = self._previa(marca_pantalla="Vans")
        previo = app.video_publicar
        app.video_publicar = lambda *a, **k: {"ok": True, "Posición": 3, "pasos": {}}
        try:
            resultado = app.apply_shopify_preview({"shop_domain": "x"}, prev.head(1))
        finally:
            app.video_publicar = previo
        self.assertEqual(resultado["Resultado"].iloc[0], "ERROR")
        self.assertIn("posicion 3", resultado["Mensaje"].iloc[0])

    def test_sobrevive_al_Excel_que_lee_el_runner(self):
        import tempfile
        import app_matrixify as app
        from catalog_engine import read_matrixify_excel

        prev = self._previa(marca_pantalla="Vans", reemplazar=True)
        payload = app.dataframe_to_excel_bytes({cr.HOJA_VISTA_PREVIA: prev})
        if hasattr(payload, "getvalue"):
            payload = payload.getvalue()
        with tempfile.NamedTemporaryFile(suffix=".xlsx", delete=False) as archivo:
            archivo.write(payload)
            ruta = archivo.name
        leido = read_matrixify_excel(ruta, sheet_name=cr.hoja_de_entrada("partial_videos"))
        for columna in ("Site key", "Marca excel", "Marca pantalla", "Reemplazar"):
            self.assertIn(columna, leido.columns, columna)

    def test_sin_sitio_NO_se_publica(self):
        import app_matrixify as app
        fila = pd.DataFrame([{
            "Operacion": "videos", "Mod-Col": "X-1", "Handle": "h", "Site key": "",
            "Estado": "OK"}])
        llamadas = []
        previo = app.video_publicar
        app.video_publicar = lambda *a, **k: llamadas.append(a)
        try:
            resultado = app.apply_shopify_preview({"shop_domain": "x"}, fila)
        finally:
            app.video_publicar = previo
        self.assertEqual(llamadas, [])
        self.assertEqual(resultado["Resultado"].iloc[0], "ERROR")

    def test_la_pantalla_ofrece_el_servidor_antes_que_la_sesion(self):
        import app_matrixify as app
        fuente = inspect.getsource(app.render_video_maintainer)
        self.assertIn("render_boton_carga_remota_parcial(", fuente)
        self.assertLess(fuente.index("render_boton_carga_remota_parcial("),
                        fuente.index("videos en Shopify"))

    def test_no_se_reimplemento_la_publicacion_de_videos(self):
        import app_matrixify as app
        fuente = inspect.getsource(app.apply_shopify_preview)
        rama = fuente.split('operation == "videos"', 1)[1].split("elif operation ==", 1)[0]
        self.assertIn("video_publicar(", rama)
        for prohibida in ("stagedUploadsCreate", "productCreateMedia", "productReorderMedia"):
            self.assertNotIn(prohibida, rama, prohibida)


class TestLaIdentidadEsElCodigoModeloColor(unittest.TestCase):
    """Pregunta del usuario: *"todo eso deberia de ser leido por codigo modelo
    color, estamos en lo correcto?"*.

    A medias, y por eso se cambio. El Excel que se sube SI se leia por codigo
    -- eso no cambia --, pero la clave con la que el job agrupa y reanuda era
    el **handle primero**. La identidad canonica de la app es al reves
    (`clave_de_producto`, seccion 5 quater): Modelo-Color, y `handle:` con
    prefijo solo de respaldo.
    """

    def _claves(self, filas):
        import app_matrixify as app
        return app._sync_job_product_key_series(
            pd.DataFrame(filas), mode="partial_body").tolist()

    def test_manda_el_codigo_modelo_color(self):
        self.assertEqual(
            self._claves([{"Mod-Col": "AB-1", "Handle": "zapa-ab-1", "Product ID": "gid://1"}]),
            ["AB-1"])

    def test_dos_Mod_Col_con_el_MISMO_handle_ya_no_colapsan(self):
        """Medido con el codigo anterior: compartian clave y el job los contaba
        como UN producto. Pasa cuando una fila del input no trae codigo
        reconocible y `build_shopify_update_preview` la casa por handle."""
        claves = self._claves([
            {"Mod-Col": "AB-1", "Handle": "mismo", "Product ID": "gid://1"},
            {"Mod-Col": "AB-2", "Handle": "mismo", "Product ID": "gid://2"},
        ])
        self.assertEqual(claves, ["AB-1", "AB-2"])

    def test_sin_codigo_cae_al_handle_CON_prefijo(self):
        """El prefijo no es cosmetico: sin el, un handle que se parezca a un
        codigo podria chocar con uno real."""
        self.assertEqual(
            self._claves([{"Mod-Col": "", "Handle": "zapa-ab-1", "Product ID": "gid://1"}]),
            ["handle:zapa-ab-1"])

    def test_sin_codigo_ni_handle_no_colapsan_en_la_cadena_vacia(self):
        """Es exactamente el fallo que `clave_de_producto` existe para
        impedir: todos los productos sin metacampo compartiendo una sola
        llave."""
        claves = self._claves([
            {"Mod-Col": "", "Handle": "", "Product ID": "gid://1"},
            {"Mod-Col": "", "Handle": "", "Product ID": "gid://2"},
        ])
        self.assertEqual(len(set(claves)), 2, claves)

    def test_el_codigo_no_distingue_mayusculas(self):
        self.assertEqual(self._claves([{"Mod-Col": "ab-1", "Handle": "h"}]), ["AB-1"])

    def test_coincide_FILA_A_FILA_con_la_identidad_canonica(self):
        """La prueba que impide que se separen. Un segundo criterio de
        identidad se aparta del primero sin que nadie lo note -- es la trampa
        de las dos `normalize_size`."""
        from engines.load_status import clave_de_producto
        filas = [
            {"Mod-Col": "AB-1", "Handle": "zapa-ab-1"},
            {"Mod-Col": "ab-2", "Handle": "zapa-ab-2"},
            {"Mod-Col": "", "Handle": "solo-handle"},
            {"Mod-Col": "AB-3", "Handle": ""},
        ]
        # `Product ID` vacio para que el ultimo respaldo no entre en juego: es
        # el unico escalon que la canonica no tiene, porque alli siempre hay
        # handle y aqui la fila puede venir de un Excel a medias.
        con_id = [dict(f, **{"Product ID": ""}) for f in filas]
        self.assertEqual(self._claves(con_id), [clave_de_producto(f) for f in filas])

    def test_las_dos_filas_de_short_texts_siguen_siendo_UN_producto(self):
        """Comparten Modelo-Color, asi que caen en el mismo bloque y se
        aplican juntas. Si se separaran, un producto contaria como dos."""
        claves = self._claves([
            {"Mod-Col": "AB-1", "Handle": "h", "Metafield": "custom.nombre_corto"},
            {"Mod-Col": "AB-1", "Handle": "h", "Metafield": "custom.descripcion_corta"},
        ])
        self.assertEqual(len(set(claves)), 1)

    def test_no_se_pierde_NINGUNA_fila(self):
        """Lo que de verdad no puede pasar: que una fila de la vista previa no
        caiga en ningun bloque y no se escriba nunca."""
        import app_matrixify as app
        filas = [
            {"Mod-Col": "AB-1", "Handle": "h1", "Product ID": "gid://1"},
            {"Mod-Col": "AB-2", "Handle": "h1", "Product ID": "gid://2"},
            {"Mod-Col": "", "Handle": "h3", "Product ID": "gid://3"},
            {"Mod-Col": "", "Handle": "", "Product ID": "gid://4"},
        ]
        df = pd.DataFrame(filas)
        serie = app._sync_job_product_key_series(df, mode="partial_body")
        total = sum(
            len(app._sync_job_subset_df(df, clave, mode="partial_body", keys=serie))
            for clave in app._sync_job_product_keys(df, mode="partial_body"))
        self.assertEqual(total, len(filas))

    def test_la_carga_COMPLETA_no_se_toco(self):
        """El Matrixify se agrupa por handle con `ffill` -- los campos de
        producto van solo en la primera fila y las variantes debajo --, asi
        que ahi el handle ES la identidad del bloque. Cambiarlo partiria cada
        producto en tantos bloques como variantes."""
        import app_matrixify as app
        df = pd.DataFrame([
            {"Handle": "zapa-ab-1", "Title": "Zapa", "Option1 Value": "40"},
            {"Handle": "", "Title": "", "Option1 Value": "41"},
        ])
        self.assertEqual(
            app._sync_job_product_key_series(df, mode="full").tolist(),
            ["zapa-ab-1", "zapa-ab-1"])

    def test_un_job_VIEJO_sigue_encontrando_sus_productos(self):
        """Sin el respaldo heredado, un job creado antes del cambio tiene
        handles guardados como pendientes y fallaria con "No se encontro el
        producto dentro del snapshot" en TODOS sus productos. Comprobado."""
        import app_matrixify as app
        df = pd.DataFrame([{"Operacion": "body", "Mod-Col": "AB-1",
                            "Handle": "zapa-ab-1", "Product ID": "gid://1"}])
        serie = app._sync_job_product_key_series(df, mode="partial_body")
        heredada = app._sync_job_subset_df(df, "zapa-ab-1", mode="partial_body", keys=serie)
        self.assertEqual(len(heredada), 1)

    def test_una_clave_que_no_existe_sigue_sin_encontrar_nada(self):
        """El respaldo no puede convertirse en un comodin."""
        import app_matrixify as app
        df = pd.DataFrame([{"Operacion": "body", "Mod-Col": "AB-1",
                            "Handle": "zapa-ab-1", "Product ID": "gid://1"}])
        serie = app._sync_job_product_key_series(df, mode="partial_body")
        self.assertTrue(
            app._sync_job_subset_df(df, "no-existe", mode="partial_body", keys=serie).empty)

    def test_el_respaldo_heredado_NO_se_consulta_en_una_carga_completa(self):
        import app_matrixify as app
        fuente = inspect.getsource(app._sync_job_subset_df)
        self.assertIn('startswith("partial")', fuente)


if __name__ == "__main__":
    unittest.main(verbosity=2)
