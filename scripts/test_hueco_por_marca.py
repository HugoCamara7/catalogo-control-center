"""El panel del hueco por marca, y la vista previa de la carga de Supermall.

Ejecutar:  python scripts/test_hueco_por_marca.py

Que fija
--------
1. El reparto por marca sale de las fichas YA consolidadas: ninguna lectura
   extra, y los totales del titular no pueden discrepar de las filas.
2. **Cada barra es el 100 % de SU marca.** La primera version usaba una escala
   compartida y eso enganaba: con el reparto real medido, Sorel salia con una
   barra del 2,6 % del ancho -se leia como "esta bien"- cuando le falta el
   71 % de su catalogo.
3. La identidad nunca es solo color: leyenda con las cuatro etiquetas y su
   numero, etiqueta directa por fila y tabla con todo. Es lo que cubre el aviso
   de contraste bajo 3:1 de los colores de estado sobre fondo blanco.
4. Lo que se descarga es la vista previa COMPLETA y no escribe nada en Shopify.
"""
import inspect
import os
import re
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pandas as pd  # noqa: E402

import app_matrixify as app  # noqa: E402
from engines import carga_supermall as cs  # noqa: E402

# El reparto real medido en el maestro, para que las pruebas midan el caso de
# produccion y no uno inventado.
REPARTO = {
    "Hush Puppies": (8165, 120, 2752, 30),
    "Rockford": (2078, 40, 328, 8),
    "Columbia": (1200, 60, 2794, 45),
    "Vans": (790, 15, 151, 8),
    "Keds": (120, 5, 335, 3),
    "Sorel": (80, 2, 201, 1),
}


def fichas_de(reparto=None):
    fichas = []
    for marca, (visibles, sin_publicar, faltan, bloqueados) in (reparto or REPARTO).items():
        fichas += [{"Marca": marca, "Se puede cargar": True, "Ya esta en Supermall": True,
                    "Estado en Supermall": "Prendido y visible"}] * visibles
        fichas += [{"Marca": marca, "Se puede cargar": True, "Ya esta en Supermall": True,
                    "Estado en Supermall": "Borrador"}] * sin_publicar
        fichas += [{"Marca": marca, "Se puede cargar": True,
                    "Ya esta en Supermall": False}] * faltan
        fichas += [{"Marca": marca, "Se puede cargar": False,
                    "Ya esta en Supermall": False}] * bloqueados
    return fichas


def dibujar(filas, totales):
    piezas = []
    render_previo, caption_previo = app.render_html, app.st.caption
    app.render_html = lambda html, **kw: piezas.append(html)
    app.st.caption = lambda *a, **k: None
    try:
        app.render_hueco_por_marca(filas, totales)
    finally:
        app.render_html, app.st.caption = render_previo, caption_previo
    return "".join(piezas)


class TestElRepartoPorMarca(unittest.TestCase):
    def test_cuenta_los_cuatro_estados(self):
        filas = {f["Marca"]: f for f in cs.hueco_por_marca(fichas_de())}
        vans = filas["Vans"]
        self.assertEqual(vans[cs.YA_VISIBLE], 790)
        self.assertEqual(vans[cs.SIN_PUBLICAR], 15)
        self.assertEqual(vans[cs.FALTA_CARGAR], 151)
        self.assertEqual(vans[cs.NO_CARGABLE], 8)
        self.assertEqual(vans["Total"], 790 + 15 + 151 + 8)

    def test_lo_que_no_se_puede_cargar_va_APARTE_de_lo_que_falta(self):
        """Mezclarlos haria creer que con pulsar el boton se resuelven, y no:
        les falta el codigo, el nombre o el tipo en TODAS las webs."""
        filas = cs.hueco_por_marca([
            {"Marca": "X", "Se puede cargar": False, "Ya esta en Supermall": False},
        ])
        self.assertEqual(filas[0][cs.NO_CARGABLE], 1)
        self.assertEqual(filas[0][cs.FALTA_CARGAR], 0)

    def test_ordena_por_lo_que_falta(self):
        """La primera fila es donde hay mas trabajo, que es la razon de mirar
        el panel. Alfabetico obligaria a leer las diez filas."""
        filas = cs.hueco_por_marca(fichas_de())
        self.assertEqual([f["Marca"] for f in filas][:2], ["Columbia", "Hush Puppies"])
        faltan = [f[cs.FALTA_CARGAR] for f in filas]
        self.assertEqual(faltan, sorted(faltan, reverse=True))

    def test_los_totales_no_pueden_discrepar_de_las_filas(self):
        """Se suman las FILAS, no las fichas otra vez: dos calculos separados
        podrian dar numeros distintos, y un panel que se contradice consigo
        mismo no sirve para decidir."""
        filas = cs.hueco_por_marca(fichas_de())
        totales = cs.totales_del_hueco(filas)
        for clave in cs.SEGMENTOS:
            self.assertEqual(totales[clave], sum(f[clave] for f in filas), clave)
        self.assertEqual(totales["Total"], sum(f["Total"] for f in filas))
        self.assertEqual(totales["Marcas"], len(filas))

    def test_la_cobertura_es_lo_visible_sobre_el_total(self):
        filas = {f["Marca"]: f for f in cs.hueco_por_marca(fichas_de())}
        sorel = filas["Sorel"]
        self.assertAlmostEqual(sorel["Cobertura"], round(100 * 80 / 284, 1), places=1)

    def test_sin_marca_no_revienta(self):
        filas = cs.hueco_por_marca([{"Marca": "", "Se puede cargar": True,
                                     "Ya esta en Supermall": False}])
        self.assertEqual(filas[0]["Marca"], cs.SIN_MARCA)

    def test_sin_fichas_devuelve_vacio(self):
        self.assertEqual(cs.hueco_por_marca([]), [])
        self.assertEqual(cs.totales_del_hueco([])["Total"], 0)


class TestLaBarraSeLeeBien(unittest.TestCase):
    def setUp(self):
        self.filas = cs.hueco_por_marca(fichas_de())
        self.totales = cs.totales_del_hueco(self.filas)
        self.html = dibujar(self.filas, self.totales)

    def _barras(self):
        """(marca, html de la barra COMPLETA). El cierre se ancla en
        `hueco-cifra`: con un `</div>` a secas la captura se corta en el primer
        segmento y la prueba mediria una barra incompleta."""
        return re.findall(
            r'hueco-marca" title="([^"]+)">[^<]*</div>'
            r'<div class="hueco-barra">(.*?)</div><div class="hueco-cifra"',
            self.html)

    def test_cada_barra_es_el_100_por_ciento_de_SU_marca(self):
        """La escala compartida enganaba: Sorel salia al 2,6 % del ancho y se
        leia como "esta bien" con el 71 % de su catalogo sin cargar."""
        for marca, cuerpo in self._barras():
            anchos = [float(a) for a in re.findall(r'width:([\d.]+)%', cuerpo)]
            self.assertAlmostEqual(sum(anchos), 100.0, places=1, msg=marca)

    def test_una_marca_mal_cubierta_se_VE_mal_cubierta(self):
        """Sorel tiene pocos productos pero le falta el 71 %: la barra tiene
        que salir mayoritariamente en el color de "falta"."""
        for marca, cuerpo in self._barras():
            if marca != "Sorel":
                continue
            falta = re.search(
                r'width:([\d.]+)%;background:' + re.escape(app.HUECO_COLORES[cs.FALTA_CARGAR]),
                cuerpo)
            self.assertIsNotNone(falta)
            self.assertGreater(float(falta.group(1)), 60.0)
            return
        self.fail("no encontre la fila de Sorel")

    def test_la_magnitud_absoluta_va_en_la_etiqueta(self):
        """La proporcion se compara en la barra; el numero se lee en texto.
        Sin el, una marca chica y una grande con el mismo porcentaje se leerian
        igual de urgentes."""
        self.assertIn("2.794", self.html)
        self.assertIn("por cargar", self.html)
        self.assertIn("cubierto", self.html)

    def test_la_leyenda_nombra_los_cuatro_estados_con_su_numero(self):
        """La identidad nunca puede ser solo color. Y es lo que cubre el aviso
        de contraste bajo 3:1 de los colores de estado sobre fondo blanco."""
        for clave in cs.SEGMENTOS:
            self.assertIn(clave, self.html, clave)
        self.assertIn("hueco-leyenda", self.html)

    def test_cada_segmento_lleva_su_dato_al_pasar_el_raton(self):
        segmentos = re.findall(r'<div class="hueco-seg"[^>]*>', self.html)
        self.assertTrue(segmentos)
        for segmento in segmentos:
            self.assertIn("title=", segmento)

    def test_no_hay_un_numero_en_cada_segmento(self):
        """Un valor pegado a cada segmento es ruido y no se lee: la etiqueta es
        selectiva -- lo que falta -- y el resto lo llevan leyenda y tabla."""
        self.assertEqual(self.html.count("por cargar"), len(self._barras()))

    def test_los_colores_son_los_de_ESTADO_de_la_app(self):
        """No es una paleta categorica: los cuatro valores son estados, de mejor
        a peor. Usar tokens de estado para identidad -o al reves- es el error
        que la guia de visualizacion llama por su nombre."""
        self.assertEqual(app.HUECO_COLORES[cs.YA_VISIBLE], "var(--c-ok)")
        self.assertEqual(app.HUECO_COLORES[cs.SIN_PUBLICAR], "var(--c-warn)")
        self.assertEqual(app.HUECO_COLORES[cs.FALTA_CARGAR], "var(--c-bad)")

    def test_con_muchas_marcas_se_acota_y_se_avisa(self):
        muchas = {f"Marca {i}": (10, 1, i, 0) for i in range(30)}
        html = dibujar(cs.hueco_por_marca(fichas_de(muchas)),
                       cs.totales_del_hueco(cs.hueco_por_marca(fichas_de(muchas))))
        self.assertEqual(len(re.findall(r'class="hueco-fila"', html)),
                         app.HUECO_MARCAS_VISIBLES)

    def test_sin_filas_no_dibuja_nada(self):
        self.assertEqual(dibujar([], {}), "")


class TestElCSSDeLaBarra(unittest.TestCase):
    def setUp(self):
        self.css = inspect.getsource(app.inject_custom_css)

    def test_las_clases_estan_declaradas(self):
        for clase in (".hueco-leyenda", ".hueco-grid", ".hueco-fila", ".hueco-marca",
                      ".hueco-barra", ".hueco-seg", ".hueco-cifra", ".hueco-punto"):
            self.assertIn(clase, self.css, clase)

    def test_las_llaves_van_dobladas(self):
        """`inject_custom_css` es un f-string: una llave simple lo convierte en
        interpolacion y la app revienta con NameError."""
        bloque = self.css[self.css.index(".hueco-leyenda"):self.css.index(".kpi-card-grid")]
        sin_dobles = bloque.replace("{{", "\x01").replace("}}", "\x02")
        self.assertEqual(re.findall(r"[{}]", sin_dobles), [])

    def test_la_separacion_entre_segmentos_no_es_un_borde(self):
        """Un borde ensucia el color y engorda la marca: se usa un hueco del
        color de la superficie."""
        bloque = self.css[self.css.index(".hueco-seg"):self.css.index(".hueco-cifra")]
        self.assertIn("inset -2px 0 0 var(--c-surface)", bloque)
        self.assertNotIn("border:", bloque)

    def test_hay_escalon_de_movil(self):
        self.assertIn("@media (max-width: 640px)", self.css)


class TestLaVistaPreviaDeLaCarga(unittest.TestCase):
    def matrixify(self):
        return pd.DataFrame([
            {"Metafield: custom.marca [single_line_text_field]": "Vans",
             "Metafield: custom.codigo_modelo_color [id]": "VN1-001"},
            {"Metafield: custom.marca [single_line_text_field]": "Vans",
             "Metafield: custom.codigo_modelo_color [id]": "VN1-001"},
            {"Metafield: custom.marca [single_line_text_field]": "Vans",
             "Metafield: custom.codigo_modelo_color [id]": "VN1-002"},
            {"Metafield: custom.marca [single_line_text_field]": "Columbia",
             "Metafield: custom.codigo_modelo_color [id]": "CO1-001"},
        ])

    def test_cuenta_productos_y_filas_de_talla_por_marca(self):
        resumen = app.resumen_matrixify_por_marca(self.matrixify())
        por_marca = {f["Marca"]: f for _, f in resumen.iterrows()}
        self.assertEqual(por_marca["Vans"]["Productos"], 2)
        self.assertEqual(por_marca["Vans"]["Filas de talla"], 3)
        self.assertEqual(por_marca["Columbia"]["Productos"], 1)

    def test_sale_del_propio_matrixify(self):
        """Si el resumen se calculara aparte podria discrepar del archivo que
        se sube, y entonces no sirve para revisar antes de cargar."""
        resumen = app.resumen_matrixify_por_marca(self.matrixify())
        self.assertEqual(resumen["Filas de talla"].sum(), len(self.matrixify()))

    def test_una_marca_vacia_se_nombra(self):
        df = pd.DataFrame([{"Metafield: custom.marca [single_line_text_field]": "",
                            "Metafield: custom.codigo_modelo_color [id]": "X-1"}])
        self.assertEqual(app.resumen_matrixify_por_marca(df).iloc[0]["Marca"], cs.SIN_MARCA)

    def test_sin_matrixify_no_revienta(self):
        self.assertTrue(app.resumen_matrixify_por_marca(pd.DataFrame()).empty)
        self.assertTrue(app.resumen_matrixify_por_marca(None).empty)

    def test_el_excel_lleva_la_hoja_de_resumen(self):
        cuerpo = inspect.getsource(app.render_carga_supermall)
        self.assertIn('"Resumen por marca": resumen_marcas', cuerpo)
        self.assertIn('"Products": matrixify_df', cuerpo)
        self.assertIn('"Carga Sial": sial_df', cuerpo)

    def test_dice_que_todavia_no_se_escribio_nada(self):
        """Es una vista previa: el usuario tiene que poder revisarla sabiendo
        que Shopify sigue intacto."""
        cuerpo = inspect.getsource(app.render_carga_supermall)
        self.assertIn("Todavía no se ha escrito nada en Shopify", cuerpo)

    def test_el_panel_se_dibuja_ANTES_de_generar(self):
        """El hueco se mira para decidir; si saliera despues de generar ya no
        decide nada."""
        cuerpo = inspect.getsource(app.render_carga_supermall)
        self.assertLess(cuerpo.index("render_hueco_por_marca("),
                        cuerpo.index("Generar la carga de Supermall"))

    def test_el_panel_no_escribe_en_shopify(self):
        cuerpo = (inspect.getsource(app.render_hueco_por_marca)
                  + inspect.getsource(cs.hueco_por_marca)
                  + inspect.getsource(app.resumen_matrixify_por_marca))
        for prohibido in ("apply_full_product_updates", "metafieldsSet", "update_product",
                          "productCreateMedia", "fetch_products"):
            self.assertNotIn(prohibido, cuerpo)


if __name__ == "__main__":
    unittest.main(verbosity=2)
