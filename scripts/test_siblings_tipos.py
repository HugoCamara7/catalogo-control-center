"""Pruebas del tipo con que se escriben los siblings y del fallo en bloque.

Origen (agosto 2026): "sale error cuando quiero actualizar siblings". Dos
causas distintas, las dos en el mismo metacampo:

1. La carga parcial mandaba `theme.siblings` y `custom.siblings` en la MISMA
   llamada a `metafieldsSet`, con el tipo escrito a mano en el código. La
   mutación es todo o nada: bastaba que uno de los dos no coincidiera con la
   definición de la tienda para que Shopify rechazara el lote entero y no se
   escribiera NINGUNO de los dos. La fila terminaba en ERROR.

2. `theme.siblings` normalmente no tiene definición en la tienda: Shopify le
   fija el tipo con la primera escritura y después rechaza cualquier otro. Ni
   la tabla de `engines/catalog_map` ni la cabecera de Matrixify pueden saber
   cuál quedó, y por eso el mismo metacampo entraba por un camino y fallaba
   por el otro. El mensaje de error sí lo dice, así que se lee de ahí y se
   reintenta una vez con ese tipo.

Ejecutar:  python scripts/test_siblings_tipos.py
"""
import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import pandas as pd  # noqa: E402

import app_matrixify as app  # noqa: E402

CONFIG = {"shop_domain": "prueba.myshopify.com", "token": "x"}
MARCA = {"site_label": "Columbia.pe", "site_key": "columbia"}


def producto(gid, handle, mod_col, siblings="", custom_siblings=""):
    return {
        "Product ID": gid,
        "Handle": handle,
        "Mod-Col": mod_col,
        "Siblings": siblings,
        "Custom Siblings": custom_siblings,
        "Siblings Color": "",
        "Custom Siblings Color": "",
        "Title": "Producto",
        "Tags": "",
        "Image Src": "",
        "Media IDs": "",
        "Variants": [],
    }


class _Tienda:
    """Shopify falso: rechaza el tipo que no coincide con el suyo, como el real."""

    def __init__(self, tipos=None, sin_permiso=()):
        # (namespace, key) -> tipo que la tienda acepta.
        self.tipos = tipos or {}
        self.sin_permiso = set(sin_permiso)
        self.llamadas = []

    def metafields_set(self, config, metafields):
        self.llamadas.append(list(metafields))
        for metafield in metafields:
            clave = (metafield["namespace"], metafield["key"])
            if clave in self.sin_permiso:
                raise RuntimeError('[{"message": "Access denied for metafields field."}]')
            esperado = self.tipos.get(clave)
            if esperado and metafield["type"] != esperado:
                raise RuntimeError(
                    '[{"message": "Type must be %s"}]' % esperado
                )
        return [{"id": "gid://shopify/Metafield/1"} for _ in metafields]

    def escritos(self):
        return [metafield for lote in self.llamadas for metafield in lote]

    def aceptados(self):
        salida = []
        for lote in self.llamadas:
            if all(
                not self.tipos.get((m["namespace"], m["key"]))
                or m["type"] == self.tipos[(m["namespace"], m["key"])]
                for m in lote
            ) and not any((m["namespace"], m["key"]) in self.sin_permiso for m in lote):
                salida.extend(lote)
        return salida


class _Sesion(dict):
    """st.session_state se usa como caché del tipo; un dict basta."""


class _ConTienda(unittest.TestCase):
    tipos = {}
    sin_permiso = ()

    def setUp(self):
        self.tienda = _Tienda(self.tipos, self.sin_permiso)
        self._metafields_set = app.metafields_set
        self._sesion = app.st.session_state
        app.metafields_set = self.tienda.metafields_set
        app.st.session_state = _Sesion()

    def tearDown(self):
        app.metafields_set = self._metafields_set
        app.st.session_state = self._sesion

    def vista_previa(self, productos):
        preview, _, _ = app.build_shopify_update_preview(productos, None, "siblings", MARCA)
        return preview


class TestTipoExigidoPorShopify(unittest.TestCase):
    def test_lee_el_tipo_del_mensaje(self):
        self.assertEqual(
            app._tipo_exigido_por_shopify('[{"message": "Type must be single_line_text_field"}]'),
            "single_line_text_field",
        )

    def test_la_lista_gana_al_texto_simple(self):
        # "single_line_text_field" es subcadena de "list.single_line_text_field":
        # buscando al reves siempre ganaria el corto y el reintento repetiria el error.
        self.assertEqual(
            app._tipo_exigido_por_shopify("The type must be list.single_line_text_field"),
            "list.single_line_text_field",
        )

    def test_reconoce_la_referencia_a_producto(self):
        self.assertEqual(
            app._tipo_exigido_por_shopify("type: expected list.product_reference"),
            "list.product_reference",
        )

    def test_un_error_que_no_habla_de_tipos_no_sugiere_ninguno(self):
        # Permisos o red: reintentar con otro tipo solo gastaria otra llamada.
        self.assertEqual(app._tipo_exigido_por_shopify("Access denied for metafields field"), "")
        self.assertEqual(app._tipo_exigido_por_shopify("Connection reset by peer"), "")

    def test_vacio(self):
        self.assertEqual(app._tipo_exigido_por_shopify(""), "")
        self.assertEqual(app._tipo_exigido_por_shopify(None), "")


class TestTipoPorClave(unittest.TestCase):
    def test_manda_la_tabla_central(self):
        self.assertEqual(
            app._tipo_metafield_por_clave("custom", "siblings"), "list.product_reference"
        )
        self.assertEqual(
            app._tipo_metafield_por_clave("theme", "siblings"), "list.single_line_text_field"
        )

    def test_sin_namespace_no_inventa_tipo(self):
        self.assertEqual(app._tipo_metafield_por_clave("", "siblings"), "")
        self.assertEqual(app._tipo_metafield_por_clave("custom", ""), "")


class TestEscribirUnMetafieldDeRelacion(_ConTienda):
    tipos = {("theme", "siblings"): "single_line_text_field"}

    def test_se_corrige_con_el_tipo_que_exige_la_tienda(self):
        ok, tipo, error = app._escribir_metafield_de_relacion(
            CONFIG, "gid://shopify/Product/1", "theme", "siblings",
            "list.single_line_text_field",
            ["gid://shopify/Product/1", "gid://shopify/Product/2"],
            ["polera-roja", "polera-azul"],
        )
        self.assertTrue(ok)
        self.assertEqual(tipo, "single_line_text_field")
        self.assertEqual(error, "")
        self.assertEqual(len(self.tienda.llamadas), 2)

    def test_el_valor_se_arma_segun_el_tipo_final_no_segun_el_supuesto(self):
        # Texto simple: handles separados por coma, no el JSON de la lista.
        app._escribir_metafield_de_relacion(
            CONFIG, "gid://shopify/Product/1", "theme", "siblings",
            "list.single_line_text_field",
            ["gid://shopify/Product/1"], ["polera-roja", "polera-azul"],
        )
        self.assertEqual(self.tienda.aceptados()[0]["value"], "polera-roja, polera-azul")

    def test_el_tipo_corregido_se_recuerda_y_no_se_repite_el_intento(self):
        for _ in range(3):
            app._escribir_metafield_de_relacion(
                CONFIG, "gid://shopify/Product/1", "theme", "siblings",
                "list.single_line_text_field", ["gid://shopify/Product/1"], ["polera-roja"],
            )
        # Un solo intento fallido en total: el primero. Los otros dos van directo.
        self.assertEqual(len(self.tienda.llamadas), 4)

    def test_no_reintenta_cuando_el_error_no_es_de_tipo(self):
        self.tienda.sin_permiso = {("custom", "siblings")}
        ok, _, error = app._escribir_metafield_de_relacion(
            CONFIG, "gid://shopify/Product/1", "custom", "siblings",
            "list.product_reference", ["gid://shopify/Product/2"], ["polera-azul"],
        )
        self.assertFalse(ok)
        self.assertIn("Access denied", error)
        self.assertEqual(len(self.tienda.llamadas), 1)


class TestCargaParcialNoFallaEnBloque(_ConTienda):
    # theme.siblings quedo como texto simple en la tienda; custom.siblings es
    # referencia. Antes esta combinacion dejaba los dos sin escribir.
    tipos = {
        ("theme", "siblings"): "single_line_text_field",
        ("custom", "siblings"): "list.product_reference",
    }

    def _aplicar(self):
        productos = [
            producto("gid://shopify/Product/1", "polera-roja", "AB1234-620"),
            producto("gid://shopify/Product/2", "polera-azul", "AB1234-410"),
        ]
        return app.apply_shopify_preview(CONFIG, self.vista_previa(productos))

    def test_los_dos_metacampos_se_escriben(self):
        resultado = self._aplicar()
        self.assertEqual(list(resultado["Resultado"]), ["OK", "OK"])
        claves = {(m["namespace"], m["key"]) for m in self.tienda.aceptados()}
        self.assertEqual(claves, {("theme", "siblings"), ("custom", "siblings")})

    def test_cada_metacampo_va_en_su_propia_llamada(self):
        self._aplicar()
        self.assertTrue(all(len(lote) == 1 for lote in self.tienda.llamadas))

    def test_la_referencia_recibe_ids_y_el_tema_recibe_handles(self):
        self._aplicar()
        por_clave = {}
        for metafield in self.tienda.aceptados():
            por_clave[(metafield["namespace"], metafield["key"])] = metafield
        self.assertEqual(
            json.loads(por_clave[("custom", "siblings")]["value"]),
            ["gid://shopify/Product/1", "gid://shopify/Product/2"],
        )
        self.assertEqual(
            por_clave[("theme", "siblings")]["value"], "polera-roja, polera-azul"
        )

    def test_si_uno_falla_el_otro_igual_se_escribe(self):
        self.tienda.sin_permiso = {("theme", "siblings")}
        resultado = self._aplicar()
        self.assertEqual(list(resultado["Resultado"]), ["PARCIAL", "PARCIAL"])
        claves = {(m["namespace"], m["key"]) for m in self.tienda.aceptados()}
        self.assertEqual(claves, {("custom", "siblings")})
        self.assertIn("theme.siblings", resultado["Mensaje"].iloc[0])

    def test_los_dos_fallando_es_error(self):
        self.tienda.sin_permiso = {("theme", "siblings"), ("custom", "siblings")}
        resultado = self._aplicar()
        self.assertEqual(list(resultado["Resultado"]), ["ERROR", "ERROR"])


class TestVistaPreviaIdempotente(_ConTienda):
    def test_no_propone_cambios_cuando_ya_esta_correcto(self):
        # Shopify devuelve el JSON sin espacios; json.dumps lo escribe con ", ".
        # Comparando texto crudo, TODOS los productos salian como cambiados.
        productos = [
            producto(
                "gid://shopify/Product/1", "polera-roja", "AB1234-620",
                siblings='["polera-roja","polera-azul"]',
                custom_siblings='["gid://shopify/Product/1","gid://shopify/Product/2"]',
            ),
            producto(
                "gid://shopify/Product/2", "polera-azul", "AB1234-410",
                siblings='["polera-roja","polera-azul"]',
                custom_siblings='["gid://shopify/Product/1","gid://shopify/Product/2"]',
            ),
        ]
        self.assertTrue(self.vista_previa(productos).empty)

    def test_tampoco_si_el_tema_quedo_como_texto_con_comas(self):
        productos = [
            producto(
                "gid://shopify/Product/1", "polera-roja", "AB1234-620",
                siblings="polera-roja, polera-azul",
                custom_siblings='["gid://shopify/Product/1", "gid://shopify/Product/2"]',
            ),
            producto(
                "gid://shopify/Product/2", "polera-azul", "AB1234-410",
                siblings="polera-roja, polera-azul",
                custom_siblings='["gid://shopify/Product/1", "gid://shopify/Product/2"]',
            ),
        ]
        self.assertTrue(self.vista_previa(productos).empty)

    def test_un_color_nuevo_si_aparece(self):
        productos = [
            producto(
                "gid://shopify/Product/1", "polera-roja", "AB1234-620",
                siblings='["polera-roja"]',
                custom_siblings='["gid://shopify/Product/1"]',
            ),
            producto("gid://shopify/Product/2", "polera-azul", "AB1234-410"),
        ]
        preview = self.vista_previa(productos)
        self.assertEqual(len(preview), 2)


class TestCargaParcialDeTecnologias(_ConTienda):
    """La rama de tecnologias usaba `brand_config`, que esta funcion no recibe.

    Era un NameError: la fila terminaba en ERROR sin haber intentado escribir.
    """

    def test_escribe_la_tecnologia_sin_reventar(self):
        preview = pd.DataFrame(
            [
                {
                    "Operacion": "technologies",
                    "Handle": "polera-roja",
                    "Mod-Col": "AB1234-620",
                    "Product ID": "gid://shopify/Product/1",
                    "Campo": "Metafield: custom.tecnologia",
                    "Valor nuevo": "Omni-Heat, Omni-Shield",
                    "Tipo tecnologia": "list.single_line_text_field",
                }
            ]
        )
        resultado = app.apply_shopify_preview(CONFIG, preview)
        self.assertEqual(resultado["Resultado"].iloc[0], "OK")
        escrito = self.tienda.aceptados()[0]
        self.assertEqual((escrito["namespace"], escrito["key"]), ("custom", "tecnologia"))
        self.assertEqual(json.loads(escrito["value"]), ["Omni-Heat", "Omni-Shield"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
