"""La hoja Products es Matrixify y solo Matrixify (septiembre 2026).

Reportado con una captura del Excel: la hoja `Products` llevaba columnas
`Temporada`, `Coleccion`, `Ocasion`, `Deporte`, `Categoria` y `SubCategoria`,
y `Categoria` con valores del maestro -- `CORE`, `TRAIL`, `VN_AC_C MENS`,
`COLUMBIA` -- que ni son de Matrixify ni son una categoria.

El propio codigo ya decia que esas columnas son de acarreo ("No son columnas
Matrixify: viajan solo entre esta funcion y el constructor de Centry"), pero
nadie las quitaba al escribir la hoja.

Aqui se fija todo lo que se corrigio de ese archivo:

1. La hoja `Products` solo lleva columnas que Matrixify entiende.
2. `Categoria` solo puede ser Accesorios, Calzado o Vestuario, y va tambien
   como metacampo, que es donde la lee la tienda.
3. `Body HTML` nunca sale en texto plano.
4. El color tiene respaldo en el maestro, y sin color no se escribe una opcion
   vacia.
5. Modelo + Color no se duplica, y se comprueba ANTES de exportar.

Ejecutar:  python scripts/test_export_matrixify_y_validacion.py
"""
import ast
import sys
import unittest
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import app_matrixify as app  # noqa: E402
import generate_columbia_matrixify as g  # noqa: E402

FUENTE = (ROOT / "app_matrixify.py").read_text(encoding="utf-8")
CLAVE = "Metafield: custom.codigo_modelo_color [id]"
CATEGORIA = "Metafield: custom.categoria [single_line_text_field]"
SUBCATEGORIA = "Metafield: custom.sub_categoria [single_line_text_field]"
COLOR = "Metafield: custom.color [single_line_text_field]"

MARCA = {"site_key": "supermall", "label": "Supermall",
         "allowed_arti_brands": ["COLUMBIA"], "escala_calzado": "PE",
         "sial_active_columns": ["13"], "sial_tail_columns": ["13"]}


def _cuerpo(nombre):
    for nodo in ast.walk(ast.parse(FUENTE)):
        if isinstance(nodo, (ast.FunctionDef, ast.AsyncFunctionDef)) and nodo.name == nombre:
            return ast.get_source_segment(FUENTE, nodo) or ""
    raise AssertionError(f"no se encontro {nombre}")


def maestro(codigo, tallas, **extra):
    base = {"MARCA_MA": "COLUMBIA", "Precio": "199.90",
            "NombreModelo": "Producto", "TipoProducto": "Casacas",
            "Genero": "Masculino", "ColorNombre": "", "DescripcionWeb": ""}
    base.update(extra)
    return pd.DataFrame([dict(
        base, **{"Mod-Col": codigo, "COD MOD COL": codigo,
                 "CODINT_MA": f"{codigo}-{i}", "TALNUM_MA": str(talla),
                 "CodBarras": f"77{i}"})
        for i, talla in enumerate(tallas)])


def origen(codigo, **extra):
    producto = {
        "Mod-Col": codigo, "Handle": "", "Title": "Casaca Hombre",
        "Body HTML": "", "Type": "Casacas", "Vendor": "columbiape",
        "Marca": "Columbia", "Status": "ACTIVE",
        "Published Online Store": "SI", "Variants": [],
    }
    producto.update(extra)
    return app.shopify_products_to_matrixify_df([producto])


def generar(codigo, tallas=("S", "M", "L"), maestro_extra=None, origen_extra=None):
    return app.build_centry_matrixify_from_master(
        [codigo], origen(codigo, **(origen_extra or {})),
        maestro(codigo, tallas, **(maestro_extra or {})), MARCA,
        destino_matrixify_df=pd.DataFrame(),
    )


class TestQueEsUnaColumnaDeMatrixify(unittest.TestCase):
    def test_las_estandar_y_los_prefijos_pasan(self):
        for columna in ("Handle", "Title", "Body HTML", "Variant SKU",
                        "Option1 Value", "Variant Inventory Qty",
                        "Metafield: custom.lo_que_sea [single_line_text_field]",
                        "Inventory Available: Centro de Distribución"):
            self.assertTrue(app.es_columna_matrixify(columna), columna)

    def test_las_de_acarreo_NO_pasan(self):
        for columna in ("Temporada", "Coleccion", "Ocasion", "Deporte",
                        "Categoria", "SubCategoria", "Composición", "Cuidados",
                        "Listado de características", "__CENTRY_RAW_SIZE"):
            self.assertFalse(app.es_columna_matrixify(columna), columna)

    def test_solo_columnas_matrixify_las_quita_y_ordena(self):
        df = pd.DataFrame([{"Variant SKU": "s", "Categoria": "CORE", "Handle": "h",
                            "__CENTRY_RAW_SIZE": "50", "ID": "gid://1", COLOR: "Azul"}])
        salida = app.solo_columnas_matrixify(df)
        self.assertEqual(list(salida.columns), ["ID", "Handle", "Variant SKU", COLOR])

    def test_no_se_pierde_ningun_metacampo(self):
        """Quitar de mas es peor que dejar de mas: seria perder un dato."""
        metacampos = [f"Metafield: custom.campo_{i} [single_line_text_field]" for i in range(5)]
        df = pd.DataFrame([{c: "x" for c in metacampos + ["Handle"]}])
        self.assertEqual(set(app.solo_columnas_matrixify(df).columns),
                         set(metacampos) | {"Handle"})

    def test_los_valores_no_cambian(self):
        df = pd.DataFrame([{"Handle": "h", "Variant SKU": "0012", "Option1 Value": "04-Jun",
                            "Categoria": "CORE"}])
        salida = app.solo_columnas_matrixify(df)
        self.assertEqual(list(salida["Variant SKU"]), ["0012"])
        self.assertEqual(list(salida["Option1 Value"]), ["04-Jun"])


class TestLaHojaProductsSaleLimpia(unittest.TestCase):
    def _hojas(self, escritor):
        return pd.read_excel(escritor, sheet_name=None, dtype=object)

    def test_la_exportacion_generica_limpia_Products_y_solo_Products(self):
        sucio = pd.DataFrame([{"Handle": "h", "Categoria": "CORE", "Temporada": "VERANO"}])
        hojas = self._hojas(app.dataframe_to_excel_bytes(
            {"Products": sucio, "Carga Sial": sucio}))
        self.assertNotIn("Categoria", hojas["Products"].columns)
        # La hoja Carga Sial tiene su propio formato: no se toca.
        self.assertIn("Categoria", hojas["Carga Sial"].columns)

    def test_la_carga_completa_tambien(self):
        sucio = pd.DataFrame([{"Handle": "h", "Title": "T", "Type": "Casacas",
                               "Vendor": "v", "Body HTML": "<p>x</p>",
                               "Variant SKU": "s", "Option1 Value": "M",
                               CLAVE: "A-1", "Temporada": "VERANO"}])
        vacio = pd.DataFrame()
        hojas = self._hojas(app.columbia_to_excel_bytes(sucio, vacio, vacio))
        self.assertNotIn("Temporada", hojas["Products"].columns)
        self.assertIn("Validacion", hojas)

    def test_la_carga_parcial_tambien(self):
        sucio = pd.DataFrame([{"Handle": "h", "Temporada": "VERANO"}])
        hojas = self._hojas(app.update_to_excel_bytes(sucio, pd.DataFrame()))
        self.assertNotIn("Temporada", hojas["Products"].columns)

    def test_la_carga_por_codigos_no_deja_ninguna(self):
        salida, _ = generar("AB1-N1")
        limpio = app.solo_columnas_matrixify(salida)
        self.assertTrue(all(app.es_columna_matrixify(c) for c in limpio.columns))
        self.assertFalse([c for c in limpio.columns if "centry" in str(c).lower()])


class TestCategoriaYSubcategoria(unittest.TestCase):
    def test_solo_tres_valores_posibles(self):
        for tipo, esperado in (("Botas", "Calzado"), ("Zapatillas", "Calzado"),
                               ("Blusas", "Vestuario"), ("Mochilas", "Accesorios")):
            self.assertEqual(app.categoria_de_catalogo(tipo), esperado, tipo)

    def test_lo_que_trae_el_maestro_no_pasa_por_categoria(self):
        """`CORE`, `TRAIL`, `VN_AC_C MENS` no son categorias."""
        for basura in ("CORE", "TRAIL", "VN_AC_C MENS", "COLUMBIA", "MALETINES"):
            self.assertIn(app.categoria_de_catalogo("", categoria_declarada=basura),
                          app.CATEGORIAS_DE_CATALOGO, basura)

    def test_lo_declarado_se_respeta_cuando_SI_es_una_clase(self):
        self.assertEqual(app.categoria_de_catalogo("", categoria_declarada="ACCESORIOS"),
                         "Accesorios")

    def test_van_como_metacampo_en_la_carga_por_codigos(self):
        """Y la `Categoria` basura del maestro no llega a ninguna parte."""
        salida, _ = generar("AB1-N1", origen_extra={"Type": "Botas"},
                            maestro_extra={"Categoria": "VN_AC_C MENS"})
        self.assertEqual(set(salida[CATEGORIA]), {"Calzado"})
        self.assertEqual(set(salida[SUBCATEGORIA]), {"Botas"})

    def test_sin_tipo_NO_se_inventa_una_clase(self):
        """Ponerle "Vestuario" a un producto sin tipo hace que
        `final_variant_filter` le borre la talla 0 -- y en un producto de una
        sola talla, eso es el producto entero."""
        self.assertEqual(app.categoria_de_catalogo("", por_defecto=""), "")
        salida, _ = generar("AB1-N1", origen_extra={"Type": ""},
                            maestro_extra={"TipoProducto": ""})
        self.assertEqual(set(salida[CATEGORIA]), {""})

    def test_pero_la_hoja_Sial_conserva_su_valor_por_defecto(self):
        self.assertEqual(app.categoria_de_catalogo(""), "Vestuario")

    def test_en_nombre_propio(self):
        self.assertEqual(app.subcategoria_de_catalogo("BOTAS"), "Botas")
        self.assertEqual(app.categoria_de_catalogo("Botas"), "Calzado")


class TestBodyHtml(unittest.TestCase):
    def test_el_texto_plano_se_convierte(self):
        self.assertEqual(g.asegurar_body_html("Una descripcion."), "<p>Una descripcion.</p>")

    def test_lo_que_ya_es_html_no_se_toca(self):
        html = '<div class="x"><p>Ya estaba</p></div>'
        self.assertEqual(g.asegurar_body_html(html), html)

    def test_los_caracteres_especiales_se_escapan(self):
        self.assertEqual(g.asegurar_body_html("Cuero & Gamuza"), "<p>Cuero &amp; Gamuza</p>")

    def test_los_parrafos_y_los_saltos_se_respetan(self):
        self.assertEqual(g.asegurar_body_html("A\nB\n\nC"), "<p>A<br>B</p><p>C</p>")

    def test_vacio_sigue_vacio(self):
        self.assertEqual(g.asegurar_body_html(""), "")
        self.assertEqual(g.asegurar_body_html(None), "")

    def test_la_carga_por_codigos_nunca_deja_texto_plano(self):
        salida, _ = generar("AB1-N1", maestro_extra={"DescripcionWeb": "Texto plano del maestro."})
        cuerpos = [app.clean_value(v) for v in salida["Body HTML"] if app.clean_value(v)]
        self.assertTrue(cuerpos)
        self.assertTrue(all("<" in c for c in cuerpos), cuerpos[:2])

    def test_y_avisa_cuando_no_hay_descripcion_en_ninguna_fuente(self):
        _salida, revision = generar("AB1-N1")
        self.assertTrue(any("Body HTML" in p for p in revision["Problema"]))


class TestElColor(unittest.TestCase):
    def test_sale_del_maestro_cuando_shopify_no_lo_tiene(self):
        salida, _ = generar("AB1-N1", maestro_extra={"ColorNombre": "AZUL MARINO"})
        self.assertEqual(set(salida[COLOR]), {"Azul Marino"})
        self.assertEqual(set(salida["Option2 Value"]), {"Azul Marino"})
        self.assertIn("azul-marino", salida["Handle"].iloc[0])

    def test_shopify_manda_sobre_el_maestro(self):
        salida, _ = generar(
            "AB1-N1", maestro_extra={"ColorNombre": "VERDE"},
            origen_extra={COLOR: "Rojo Ladrillo"})
        self.assertEqual(set(salida[COLOR]), {"Rojo Ladrillo"})

    def test_sin_color_NO_se_escribe_una_opcion_vacia(self):
        """Un `Option2 Name` con el valor vacio es una opcion sin valor."""
        salida, revision = generar("AB1-N1")
        self.assertEqual(set(salida["Option2 Name"]), {""})
        self.assertEqual(set(salida["Option2 Value"]), {""})
        self.assertTrue(any("color" in p.lower() for p in revision["Problema"]))


class TestLaValidacionAntesDeExportar(unittest.TestCase):
    def _base(self, **extra):
        fila = {"Handle": "a-1", "Title": "A", "Type": "Blusas", "Vendor": "v",
                "Body HTML": "<p>x</p>", CLAVE: "A-1", "Variant SKU": "s1",
                "Option1 Value": "S", CATEGORIA: "Vestuario"}
        fila.update(extra)
        return fila

    def test_un_archivo_sano_no_reporta_nada(self):
        salida = app.validar_matrixify(pd.DataFrame([self._base()]))
        self.assertTrue(salida.empty)
        self.assertEqual(app.resumen_de_validacion(salida), (0, 0))

    def test_el_mismo_mod_col_con_dos_handles_BLOQUEA(self):
        df = pd.DataFrame([self._base(), self._base(Handle="a-2", **{"Variant SKU": "s2"})])
        salida = app.validar_matrixify(df)
        self.assertIn("Modelo + Color", set(salida["Campo"]))
        self.assertEqual(app.resumen_de_validacion(salida)[0], 1)

    def test_dos_mod_col_compartiendo_handle_BLOQUEAN(self):
        df = pd.DataFrame([self._base(), self._base(**{CLAVE: "B-1", "Variant SKU": "s2"})])
        self.assertIn("Handle", set(app.validar_matrixify(df)["Campo"]))

    def test_el_mismo_sku_dos_veces_BLOQUEA(self):
        df = pd.DataFrame([self._base(), self._base(**{"Option1 Value": "M"})])
        self.assertIn("Variante", set(app.validar_matrixify(df)["Campo"]))

    def test_una_categoria_fuera_de_las_tres_BLOQUEA(self):
        df = pd.DataFrame([self._base(**{CATEGORIA: "VN_AC_C MENS"})])
        salida = app.validar_matrixify(df)
        self.assertIn("Categoria", set(salida["Campo"]))
        self.assertEqual(app.resumen_de_validacion(salida)[0], 1)

    def test_una_opcion_con_nombre_y_sin_valor_BLOQUEA(self):
        df = pd.DataFrame([self._base(**{"Option2 Name": "Color", "Option2 Value": ""})])
        self.assertIn("Option2", set(app.validar_matrixify(df)["Campo"]))

    def test_un_producto_sin_titulo_BLOQUEA(self):
        df = pd.DataFrame([self._base(Title="")])
        salida = app.validar_matrixify(df)
        self.assertIn("Title", set(salida["Campo"]))

    def test_las_filas_de_variante_vacias_NO_son_un_fallo(self):
        """Matrixify escribe los campos de producto solo en la primera fila."""
        df = pd.DataFrame([
            self._base(),
            self._base(Title="", Type="", Vendor="", **{"Body HTML": "", CLAVE: "",
                                                        "Variant SKU": "s2",
                                                        "Option1 Value": "M"}),
        ])
        self.assertTrue(app.validar_matrixify(df).empty)

    def test_mezclar_letras_y_numeros_AVISA(self):
        df = pd.DataFrame([self._base(), self._base(**{"Variant SKU": "s2",
                                                       "Option1 Value": "40"})])
        salida = app.validar_matrixify(df)
        self.assertIn("Tallas", set(salida["Campo"]))
        self.assertEqual(app.resumen_de_validacion(salida)[0], 0)

    def test_las_columnas_de_acarreo_conocidas_NO_se_reportan(self):
        """Un aviso que salta siempre enseña a ignorar el panel."""
        df = pd.DataFrame([self._base(Temporada="VERANO", Categoria="CORE")])
        self.assertTrue(app.validar_matrixify(df).empty)

    def test_pero_una_columna_desconocida_SI(self):
        df = pd.DataFrame([self._base(ColumnaNueva="x")])
        self.assertIn("Columna", set(app.validar_matrixify(df)["Campo"]))


class TestLaCargaEnElServidor(unittest.TestCase):
    """El proceso corre en un runner, no en la pestaña."""

    def test_el_lanzador_acepta_un_archivo_explicito(self):
        cuerpo = _cuerpo("lanzar_carga_remota_suelta")
        self.assertIn("matrixify_bytes=None", cuerpo)
        self.assertIn("if matrixify_bytes is not None:", cuerpo)

    def test_supermall_lo_usa_en_vez_de_escribir_otro(self):
        """Dos motores de carga se separan sin que nadie lo note."""
        cuerpo = _cuerpo("render_carga_supermall")
        self.assertIn("lanzar_carga_remota_suelta(", cuerpo)
        self.assertIn("matrixify_bytes=", cuerpo)

    def test_supermall_no_deja_cargar_con_bloqueos(self):
        cuerpo = _cuerpo("render_carga_supermall")
        self.assertLess(cuerpo.index("if bloqueos:"),
                        cuerpo.index('"Cargar a Shopify en el servidor"'))

    def test_hay_panel_de_estado_y_lee_el_registro_real(self):
        cuerpo = _cuerpo("render_estado_carga_remota")
        for etapa in ("Pendiente", "Procesando", "Completado", "Error"):
            self.assertIn(etapa, cuerpo, etapa)
        self.assertIn("almacen.leer(job_id)", cuerpo)

    def test_las_dos_pantallas_lo_dibujan(self):
        for nombre in ("render_carga_supermall",):
            self.assertIn("render_estado_carga_remota(", _cuerpo(nombre), nombre)
        self.assertIn("render_estado_carga_remota(", FUENTE)


if __name__ == "__main__":
    unittest.main(verbosity=2)
