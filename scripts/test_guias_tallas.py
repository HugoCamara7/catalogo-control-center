"""Las guias de tallas: por marca y clase, nunca por sitio.

Ejecutar:  python scripts/test_guias_tallas.py

Lo que fija
-----------
1. La guia de Vans del repositorio es **la del Excel oficial**, fila a fila.
2. La escala de publicacion la manda el SITIO (`escala_calzado`) y la tabla de
   conversion la manda la MARCA. Con un booleano de sitio no se puede tener
   "Vans en PE y el resto en origen" dentro de la misma tienda, que es lo que
   Supermall.pe pide.
3. **Sin guia no se convierte, y se reporta.** Nunca se adivina.
4. **Sin genero no se convierte, y se reporta.** Un mismo numero US son dos
   tallas distintas segun el genero: el fallo que reporto el usuario era que
   se aplicaba la columna de hombre en silencio.
5. Nada de esto detiene la carga.
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from engines import guias_tallas as gt  # noqa: E402
from engines import tallas_calzado  # noqa: E402
import generate_columbia_matrixify as g  # noqa: E402

VANS = g.get_brand_config("vans")
SUPERMALL = g.get_brand_config("supermall")
COLUMBIA = g.get_brand_config("columbia")
ROCKFORD = g.get_brand_config("rockford")


class TestLaGuiaDeVansEsLaOficial(unittest.TestCase):
    def test_las_equivalencias_que_pidio_el_usuario(self):
        """`5, 6, 7 -> 35, 36, 37` era la columna de MUJER. La app devolvia
        `36.5, 38, 39`, que es la de hombre: dos tallas y media de mas."""
        for us, pe in (("5.5", "35"), ("6", "36"), ("7", "37")):
            self.assertEqual(gt.convertir(us, "VANS", gt.CALZADO, "Femenino"), (pe, ""))

    def test_el_mismo_numero_es_dos_tallas_segun_el_genero(self):
        self.assertEqual(gt.convertir("8", "VANS", gt.CALZADO, "Masculino")[0], "40.5")
        self.assertEqual(gt.convertir("8", "VANS", gt.CALZADO, "Femenino")[0], "38.5")

    def test_una_talla_que_ya_esta_en_pe_no_se_toca(self):
        for pe in ("39", "40.5", "44"):
            self.assertEqual(gt.convertir(pe, "VANS", gt.CALZADO, "Masculino"), (pe, ""))

    def test_convertir_dos_veces_es_inofensivo(self):
        una, _ = gt.convertir("8", "VANS", gt.CALZADO, "Femenino")
        dos, _ = gt.convertir(una, "VANS", gt.CALZADO, "Femenino")
        self.assertEqual(una, dos)

    def test_las_infantiles_no_necesitan_genero(self):
        """Llevan sufijo (`10.5C`, `1Y`) y no son ambiguas."""
        self.assertEqual(gt.convertir("10.5C", "VANS", gt.CALZADO, "")[0], "27")
        self.assertEqual(gt.convertir("1Y", "VANS", gt.CALZADO, "")[1], "")


class TestSinGuiaPropiaSeUsaLaPorDefecto(unittest.TestCase):
    """Septiembre de 2026: el usuario pidio que TODO el calzado saliera con la
    guia. La de Vans es la unica confirmada, asi que es la guia por defecto.

    Lo que NO cambia: la conversion se REPORTA. Nunca se inventa en silencio.
    """

    def test_columbia_se_convierte_con_la_guia_por_defecto_y_se_reporta(self):
        talla, nota = gt.convertir("8", "COLUMBIA", gt.CALZADO, "Masculino")
        self.assertEqual(talla, "40.5")
        self.assertEqual(nota, gt.POR_DEFECTO)

    def test_una_talla_que_YA_esta_en_pe_no_se_reporta(self):
        """Hush Puppies y Rockford entregan casi todo su calzado ya en PE: ahi
        no se convirtio nada, asi que no hay nada que advertir."""
        talla, nota = gt.convertir("40", "HUSH PUPPIES", gt.CALZADO, "Masculino")
        self.assertEqual(talla, "40")
        self.assertEqual(nota, "")

    def test_la_guia_PROPIA_de_la_marca_manda_sobre_la_por_defecto(self):
        gt.registrar_tabla("Propia", "MARCAPROPIA", gt.CALZADO, [
            ("8", "9.5", "", "44", "26"),
        ])
        self.assertEqual(
            gt.convertir("8", "MARCAPROPIA", gt.CALZADO, "Masculino"), ("44", ""))
        gt._GUIAS.pop(gt._clave("MARCAPROPIA", gt.CALZADO), None)

    def test_sin_guia_por_defecto_no_se_convierte_nada(self):
        """La puerta se puede cerrar: es una linea de registro, no un `if`."""
        respaldo = gt.guia_por_defecto(gt.CALZADO)
        gt._POR_DEFECTO.pop(gt._clave("", gt.CALZADO)[1], None)
        try:
            self.assertEqual(
                gt.convertir("8", "COLUMBIA", gt.CALZADO, "Masculino"), ("8", gt.SIN_GUIA))
        finally:
            gt.registrar_guia_por_defecto(gt.CALZADO, respaldo)

    def test_solo_vans_viene_con_guia_en_el_codigo(self):
        """Si alguien agrega una guia, tiene que ser con su tabla. Esta prueba
        obliga a pasar por aqui y a decidirlo, no a colarla."""
        self.assertEqual(gt.marcas_con_guia(gt.CALZADO), ["VANS"])

    def test_una_guia_nueva_entra_como_TABLA_no_como_if(self):
        gt.registrar_tabla("Prueba", "MARCAPRUEBA", gt.CALZADO, [
            ("7", "8.5", "", "39", "25"),
            ("8", "9.5", "", "40.5", "26"),
        ])
        try:
            self.assertEqual(gt.convertir("7", "MARCAPRUEBA", gt.CALZADO, "Masculino"),
                             ("39", ""))
            self.assertEqual(gt.convertir("8.5", "MARCAPRUEBA", gt.CALZADO, "Femenino"),
                             ("39", ""))
            self.assertEqual(gt.convertir("39", "MARCAPRUEBA", gt.CALZADO, "")[0], "39")
        finally:
            gt._GUIAS.pop(("MARCAPRUEBA", gt.CALZADO), None)


class TestSinGeneroNoSeConvierte(unittest.TestCase):
    def test_se_devuelve_la_talla_de_origen_y_se_avisa(self):
        talla, nota = gt.convertir("8", "VANS", gt.CALZADO, "")
        self.assertEqual(talla, "8")
        self.assertEqual(nota, gt.SIN_GENERO)

    def test_no_se_aplica_la_columna_de_hombre_a_ciegas(self):
        """El fallo concreto: sin genero salia 40.5, la de hombre."""
        self.assertNotEqual(gt.convertir("8", "VANS", gt.CALZADO, "")[0], "40.5")

    def test_la_carga_no_se_detiene(self):
        """Se avisa y se sigue. Parar una carga entera porque a un producto le
        falta el genero es peor que publicarlo con la talla de origen."""
        avisos = []
        talla = g.display_size_for_site(
            "8", SUPERMALL, gender="", product_type="Zapatilla",
            marca="VANS", avisos=avisos,
        )
        self.assertEqual(talla, "8")
        self.assertEqual(len(avisos), 1)
        self.assertEqual(avisos[0]["Motivo"], gt.SIN_GENERO)

    def test_los_avisos_llegan_a_la_hoja_de_revision(self):
        filas = g.avisos_de_talla_a_issues([
            {"Talla": "8", "Marca": "VANS", "Motivo": gt.SIN_GENERO},
            {"Talla": "9", "Marca": "VANS", "Motivo": gt.SIN_GENERO},
            {"Talla": "8", "Marca": "COLUMBIA", "Motivo": gt.SIN_GUIA},
        ])
        self.assertEqual(len(filas), 2)
        textos = " ".join(f["Problema"] for f in filas)
        self.assertIn("VANS", textos)
        self.assertIn("COLUMBIA", textos)
        self.assertIn("SIN convertir", textos)


class TestLaEscalaLaMandaElSitio(unittest.TestCase):
    def test_supermall_publica_el_calzado_en_pe(self):
        self.assertEqual(g.escala_de_calzado(SUPERMALL), "PE")

    def test_vans_sigue_publicando_en_pe(self):
        self.assertEqual(g.escala_de_calzado(VANS), "PE")

    def test_los_demas_sitios_siguen_en_origen(self):
        for clave in ("columbia", "rockford", "hush_puppies", "patagonia",
                      "mountain_hardwear", "sorel"):
            config = g.get_brand_config(clave)
            if not config:
                continue
            self.assertEqual(g.escala_de_calzado(config), "ORIGEN", clave)

    def test_la_bandera_vieja_sigue_funcionando(self):
        """`tallas_calzado_pe` se conserva como respaldo: un sitio configurado
        a la vieja usanza no puede cambiar de comportamiento."""
        self.assertEqual(g.escala_de_calzado({"tallas_calzado_pe": True}), "PE")
        self.assertEqual(g.escala_de_calzado({}), "ORIGEN")

    def test_vans_en_supermall_ya_sale_en_pe(self):
        """Era el agujero: con un booleano de sitio, Vans cargado en Supermall
        salia en US."""
        self.assertEqual(
            g.display_size_for_site("8", SUPERMALL, gender="Masculino",
                                    product_type="Zapatilla", marca="VANS"),
            "40.5",
        )

    def test_columbia_en_supermall_tambien_sale_en_pe(self):
        """Misma tienda, otra marca, MISMA escala: Supermall publica en PE.

        Antes se quedaba en US porque Columbia no tiene guia propia, y la
        tienda acababa con US y PE mezclados -- que es justo lo que el filtro de
        talla no puede resolver. Ahora cae en la guia por defecto y se reporta.
        """
        self.assertEqual(
            g.display_size_for_site("8", SUPERMALL, gender="Masculino",
                                    product_type="Zapatilla", marca="COLUMBIA"),
            "40.5",
        )

    def test_y_queda_constancia_de_con_que_guia_se_convirtio(self):
        avisos = []
        g.display_size_for_site("8", SUPERMALL, gender="Masculino",
                                product_type="Zapatilla", marca="COLUMBIA",
                                avisos=avisos)
        self.assertEqual([a["Motivo"] for a in avisos], ["guia por defecto"])


class TestSoloCalzado(unittest.TestCase):
    def test_una_talla_de_vestuario_no_se_convierte(self):
        """En vestuario un "12" es una talla de nino, no un US 12."""
        self.assertEqual(
            g.display_size_for_site("12", SUPERMALL, gender="Ninos",
                                    product_type="Poleras", marca="VANS"),
            "12",
        )

    def test_sin_tipo_de_prenda_no_se_convierte(self):
        self.assertEqual(
            g.display_size_for_site("8", SUPERMALL, gender="Masculino", marca="VANS"),
            "8",
        )


class TestLaTablaCoincideConElExcelOficial(unittest.TestCase):
    def test_las_34_filas_de_la_guia(self):
        """Comparado contra el Excel que envio el usuario. Las unicas filas que
        el codigo agrega son las de US Men por debajo de 6.5, derivadas del
        desfase de 1.5 de la propia tabla y documentadas en el modulo."""
        self.assertEqual(len(tallas_calzado.TABLA_VANS), 34)
        esperado = {
            "27": ("", "", "10.5C"), "31": ("", "", "13.5C"), "34": ("", "", "3Y"),
            "34.5": ("3.5", "5", "3.5"), "38.5": ("6.5", "8", ""),
            "40.5": ("8", "9.5", ""), "43": ("10", "11.5", ""),
            "46": ("12", "", ""), "50": ("16", "", ""),
        }
        por_pe = {fila[3]: fila[:3] for fila in tallas_calzado.TABLA_VANS}
        for pe, columnas in esperado.items():
            self.assertEqual(por_pe[pe], columnas, f"PE {pe}")


if __name__ == "__main__":
    unittest.main(verbosity=2)
