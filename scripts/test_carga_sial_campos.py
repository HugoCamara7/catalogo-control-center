"""La hoja Carga Sial: categoria, topes de las columnas y que tallas salen.

Ejecutar:  python scripts/test_carga_sial_campos.py

Cuatro cosas reportadas por el usuario, las cuatro reproducidas contra una
carga real antes de tocar nada:

    Categoria           vacia en TODA la carga completa
    Tipo de Material    65 caracteres  (tope 30)
    Tecnologias         71 caracteres  (tope 50)
    Caracteristicas    144 caracteres  (tope 130)

Y las tallas que no son tallas llegaban a la hoja del almacen.
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pandas as pd  # noqa: E402

import app_matrixify as app  # noqa: E402
import generate_columbia_matrixify as g  # noqa: E402
from engines import sial_campos as sc  # noqa: E402
from engines import tallas  # noqa: E402

ROCKFORD = g.get_brand_config("rockford")

LARGO_COLOR = "AZUL MARINO OSCURO INTENSO, BLANCO HUESO, ROJO CARMESI"
LARGO_MATERIAL = "100% Algodon organico certificado, Forro 100% Poliester reciclado"
LARGO_TECNOLOGIA = "Omni-Heat Reflective, Omni-Wick Advanced Evaporation, Omni-Shade UPF 50"
LARGO_FEATURES = ("Suela de goma vulcanizada | Plantilla acolchada de EVA | Refuerzo en el "
                  "talon | Cordones planos de algodon | Puntera reforzada | Costuras dobles")


def entrada(**extra):
    fila = {
        "Mod-Col": "RK1-WSA", "Marca": "Rockford", "Genero": "HOMBRE",
        "Clase": "Calzado", "Tipo de prenda": "ALPARGATA",
        "Color web/filtro": LARGO_COLOR, "Nombre de Producto": "Alpargata Hombre",
        "Descripcion": "Texto.", "Caracteristicas": LARGO_FEATURES,
        "Materiales": LARGO_MATERIAL, "Tecnologia": LARGO_TECNOLOGIA,
    }
    fila.update(extra)
    return pd.DataFrame([fila])


def maestro(tallas_maestro=("400", "410")):
    return pd.DataFrame([{
        "Mod-Col": "RK1-WSA", "COD MOD COL": "RK1-WSA", "CODINT_MA": f"SKU{i}",
        "TALNUM_MA": t, "MARCA_MA": "ROCKFORD", "Precio": "100", "CodBarras": "",
        "NombreModelo": "Alpargata", "TipoProducto": "ALPARGATA", "Genero": "HOMBRE",
    } for i, t in enumerate(tallas_maestro, 1)])


def carga_completa(tallas_maestro=("400", "410"), **extra):
    salida = g.build_columbia_matrixify(
        entrada(**extra), maestro(tallas_maestro),
        pd.DataFrame(columns=["Handle"]), ROCKFORD,
    )
    return salida[5], salida[2]  # (hoja Sial, hoja Revision)


def por_codigos(tallas_maestro=("400", "410")):
    mx, _ = app.build_centry_matrixify_from_master(
        ["RK1-WSA"], pd.DataFrame(), maestro(tallas_maestro), ROCKFORD)
    return app.build_sial_de_sitio_from_matrixify(mx, ROCKFORD)


class TestCategoriaEsLaClase(unittest.TestCase):
    """`Categoria ` salia VACIA en toda la carga completa: el input comercial
    llama a esa columna `Clase` -- es una de sus columnas obligatorias -- y
    `product_category` no la miraba."""

    def test_la_carga_completa_ya_trae_categoria(self):
        sial, _ = carga_completa()
        self.assertEqual(sial.iloc[0]["Categoria "], "CALZADO")

    def test_sale_de_la_columna_Clase_del_input(self):
        self.assertEqual(
            g.product_category(pd.Series({"Clase": "Vestuario"})), "VESTUARIO")

    def test_sin_Clase_se_deriva_del_tipo_de_prenda(self):
        """El diccionario de tipos es el respaldo: un ALPARGATA es Calzado se
        escriba o no. Es el MISMO que usa la hoja por codigos."""
        self.assertEqual(
            g.product_category(pd.Series({"Tipo de prenda": "ALPARGATA"})), "CALZADO")
        self.assertEqual(
            g.product_category(pd.Series({"Tipo de prenda": "Mochila"})), "ACCESORIOS")

    def test_las_dos_hojas_dicen_lo_mismo(self):
        """Si la carga completa dice CALZADO y la hoja por codigos otra cosa,
        es el mismo producto con dos categorias."""
        sial_completa, _ = carga_completa()
        sial_codigos = por_codigos()
        self.assertEqual(sial_completa.iloc[0]["Categoria "],
                         sial_codigos.iloc[0]["Categoria "])


class TestLasCabecerasSonLasDeLaPlantilla(unittest.TestCase):
    """16 cabeceras perdian el espacio final en la hoja por codigos.

    `repair_mojibake_dataframe` pasaba los nombres de columna por
    `repair_mojibake_text`, que empieza con `clean_value` y recorta espacios.
    SIAL espera `Categoria `, `Talla Web `, `Tecnologias `, `Product Name `...
    con el espacio, porque asi se llaman en su plantilla. La hoja de la carga
    completa no pasa por ahi, asi que las dos salian distintas.
    """

    def test_la_hoja_por_codigos_usa_los_nombres_exactos(self):
        faltan = [c for c in g.get_sial_columns(ROCKFORD) if c not in por_codigos().columns]
        self.assertEqual(faltan, [])

    def test_las_dos_hojas_tienen_las_mismas_columnas(self):
        completa, _ = carga_completa()
        self.assertEqual(list(completa.columns), list(por_codigos().columns))

    def test_el_mojibake_se_sigue_arreglando(self):
        self.assertEqual(app._repair_column_name("DescripciÃ³n"), "Descripción")

    def test_un_nombre_sin_mojibake_no_se_toca(self):
        for nombre in ("Categoria ", "Talla Web ", "Adicional 2 ", "Mod-Col"):
            self.assertEqual(app._repair_column_name(nombre), nombre)


class TestLosTopesDeLaHoja(unittest.TestCase):
    def test_ninguna_columna_con_tope_se_pasa(self):
        for hoja, nombre in ((carga_completa()[0], "carga completa"), (por_codigos(), "por codigos")):
            fila = hoja.iloc[0]
            for columna, (limite, _politica) in sc.LIMITES.items():
                if columna not in hoja.columns:
                    continue
                self.assertLessEqual(
                    len(str(fila[columna])), limite,
                    f"{nombre}: {columna} = {fila[columna]!r}")

    def test_el_color_se_corta_antes_de_la_coma(self):
        """30 caracteres, y la forma de acortarlo es quedarse con el color de
        antes de la coma -- no recortar la cadena."""
        sial, _ = carga_completa()
        self.assertEqual(sial.iloc[0]["Color Web"], "AZUL MARINO OSCURO INTENSO")

    def test_el_material_no_se_parte_por_la_mitad_de_una_palabra(self):
        sial, _ = carga_completa()
        material = sial.iloc[0]["Tipo de Material"]
        self.assertLessEqual(len(material), 30)
        self.assertFalse(material.endswith("-"))
        self.assertTrue(LARGO_MATERIAL.startswith(material))
        self.assertNotIn("organi ", material + " ")

    def test_la_tecnologia_se_queda_con_la_primera_o_se_vacia(self):
        sial, _ = carga_completa()
        self.assertEqual(sial.iloc[0]["Tecnologias "], "Omni-Heat Reflective")
        # Si ni la primera entra en 50, se deja VACIA: una tecnologia a medias
        # es peor que ninguna.
        larga = "Una tecnologia con un nombre absolutamente larguisimo que no entra"
        self.assertEqual(sc.acortar(larga, 50, sc.O_VACIO), ("", sc.acortar(larga, 50, sc.O_VACIO)[1]))

    def test_las_caracteristicas_se_recortan_a_130_en_palabra(self):
        sial, _ = carga_completa()
        features = sial.iloc[0]["Caracteristicas"]
        self.assertLessEqual(len(features), 130)
        self.assertTrue(LARGO_FEATURES.startswith(features))

    def test_lo_que_ya_entra_no_se_toca(self):
        for columna, (limite, politica) in sc.LIMITES.items():
            self.assertEqual(sc.acortar("AZUL", limite, politica), ("AZUL", ""))

    def test_nunca_devuelve_algo_mas_largo_que_el_tope(self):
        for valor in (LARGO_COLOR, LARGO_MATERIAL, LARGO_TECNOLOGIA, LARGO_FEATURES,
                      "unapalabramuylargasinseparadoresdeningunaclaseparaprobarelrecorteseco"):
            for columna, (limite, politica) in sc.LIMITES.items():
                nuevo, _ = sc.acortar(valor, limite, politica)
                self.assertLessEqual(len(nuevo), limite, (columna, valor))

    def test_cada_ajuste_se_reporta(self):
        """Un recorte silencioso es como se pierde un dato sin que nadie se
        entere."""
        _, revision = carga_completa()
        problemas = " ".join(str(v) for v in revision.get("Problema", []))
        for columna in ("Color Web", "Tipo de Material", "Tecnologias", "Caracteristicas"):
            self.assertIn(columna, problemas)

    def test_la_regla_esta_escrita_UNA_vez(self):
        """La hoja se emite desde dos sitios. Con la regla en cada uno, el
        arreglo siguiente se olvida en una de las dos."""
        import inspect
        self.assertIn("sial_campos.ajustar_fila", inspect.getsource(g.build_sial_row))
        self.assertIn("sial_campos.ajustar_fila",
                      inspect.getsource(app._filas_sial_desde_matrixify))


class TestQueTallasSalenEnLaHoja(unittest.TestCase):
    TODAS = ("400", "410", "K1201", "0", "K601", "04-Jun", "08-Oct", "Dic-18",
             "R", "REGRH", "6/6X")

    def test_las_internas_K_no_salen(self):
        for hoja in (carga_completa(self.TODAS)[0], por_codigos(self.TODAS)):
            for valor in hoja["Talla"]:
                self.assertFalse(g.is_internal_k_size(valor), valor)

    def test_los_codigos_internos_tampoco(self):
        """`R`, `REGRH`, `LLH`: el diccionario no los reconoce como talla y en
        la hoja del almacen no significan nada."""
        for hoja in (carga_completa(self.TODAS)[0], por_codigos(self.TODAS)):
            valores = {g.clean(v).upper() for v in hoja["Talla"]}
            self.assertNotIn("R", valores)
            self.assertNotIn("REGRH", valores)

    def test_las_fechas_de_excel_SI_salen_pero_decodificadas(self):
        """`04-Jun` no es basura: es la talla `4-6` que Excel convirtio al
        exportar el maestro. Borrarla dejaria al almacen sin una talla real --
        son ~7.800 filas del maestro."""
        for hoja in (carga_completa(self.TODAS)[0], por_codigos(self.TODAS)):
            valores = list(hoja["Talla"])
            self.assertIn("4-6", valores)
            self.assertIn("8-10", valores)
            self.assertIn("12-18", valores)
            self.assertNotIn("04-Jun", valores)
            self.assertNotIn("Dic-18", valores)

    def test_una_talla_de_nino_real_no_se_pierde(self):
        for hoja in (carga_completa(self.TODAS)[0], por_codigos(self.TODAS)):
            self.assertIn("6/6X", list(hoja["Talla"]))

    def test_el_codigo_del_maestro_se_conserva(self):
        """`Talla` es el codigo del MAESTRO, no la talla que ve el comprador:
        `400` se manda `400`. Eso no cambia."""
        hoja, _ = carga_completa(("400", "410"))
        self.assertEqual(list(hoja["Talla"]), ["400", "410"])

    def test_se_reporta_lo_que_quedo_fuera(self):
        _, revision = carga_completa(self.TODAS)
        problemas = " ".join(str(v) for v in revision.get("Problema", []))
        self.assertIn("no es una talla", problemas)
        self.assertIn("REGRH", problemas)

    def test_las_dos_hojas_dejan_las_mismas_tallas(self):
        completa = [g.clean(v) for v in carga_completa(self.TODAS)[0]["Talla"]]
        codigos = [g.clean(v) for v in por_codigos(self.TODAS)["Talla"]]
        self.assertEqual(sorted(completa), sorted(codigos))

    def test_el_criterio_esta_escrito_UNA_vez(self):
        import inspect
        self.assertIn("talla_sirve_para_sial", inspect.getsource(g.final_variant_filter))
        self.assertIn("talla_sirve_para_sial", inspect.getsource(app.filter_centry_size_rows))


class TestLaDecodificacionNoInventa(unittest.TestCase):
    def test_conserva_el_orden_del_texto_original(self):
        """No hay que adivinar cual de los dos numeros era el mes: el texto
        conserva la posicion. `03-JUN` es `3-6` y `DIC-18` es `12-18`."""
        self.assertEqual(tallas.normalizar("03-Jun"), "3-6")
        self.assertEqual(tallas.normalizar("Dic-18"), "12-18")
        self.assertEqual(tallas.normalizar("30-Oct"), "30-10")

    def test_no_toca_lo_que_no_es_una_fecha(self):
        for valor in ("400", "M", "O/S", "38.5", "S/M", "35-38", "K1201", "R"):
            self.assertEqual(tallas.normalizar(valor), valor)


if __name__ == "__main__":
    unittest.main(verbosity=2)
