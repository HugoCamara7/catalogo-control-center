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
import ast
import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

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

    def test_sorel_se_convierte_con_la_guia_por_defecto_y_se_reporta(self):
        # El ejemplo era Columbia hasta que Columbia tuvo la suya (busca
        # `TABLA_COLUMBIA`). Sorel sigue sin guia publicada.
        talla, nota = gt.convertir("8", "SOREL", gt.CALZADO, "Masculino")
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
                gt.convertir("8", "SOREL", gt.CALZADO, "Masculino"), ("8", gt.SIN_GUIA))
        finally:
            gt.registrar_guia_por_defecto(gt.CALZADO, respaldo)

    def test_las_guias_del_codigo_son_las_DOS_confirmadas(self):
        """Si alguien agrega una guia, tiene que ser con su tabla. Esta prueba
        obliga a pasar por aqui y a decidirlo, no a colarla.

        Columbia entro en septiembre de 2026, buscada en la web a peticion del
        usuario. Faltan Hush Puppies, Keds, Sorel y Rockford."""
        self.assertEqual(gt.marcas_con_guia(gt.CALZADO), ["COLUMBIA", "VANS"])

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
                                product_type="Zapatilla", marca="SOREL",
                                avisos=avisos)
        self.assertEqual([a["Motivo"] for a in avisos], ["guia por defecto"])

    def test_y_con_la_guia_PROPIA_no_hay_salvedad_que_reportar(self):
        avisos = []
        talla = g.display_size_for_site("8", SUPERMALL, gender="Masculino",
                                       product_type="Zapatilla", marca="COLUMBIA",
                                       avisos=avisos)
        self.assertEqual(talla, "40.5")
        self.assertEqual(avisos, [])


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


class TestLaGuiaDeColumbia(unittest.TestCase):
    """Buscada en la web a peticion del usuario (septiembre 2026).

    Columbia publica **US -> largo de pie en cm**, no US -> EU, y su traduccion
    a EU tiene fama de poco fiable. El PE se deriva del CENTIMETRO con la misma
    columna CM de la tabla que ya usa la tienda, que es el dato fisico.
    """

    def test_esta_registrada_como_TABLA(self):
        self.assertIn("COLUMBIA", gt.marcas_con_guia(gt.CALZADO))
        self.assertEqual(len(gt.TABLA_COLUMBIA[0]), 5, "(US Men, US Women, US Boy, PE, CM)")

    def test_el_PE_sale_del_CENTIMETRO_de_la_tabla_que_ya_usa_la_tienda(self):
        """Si alguna fila no cuadrara con la columna CM, el catalogo tendria
        dos escalas PE distintas segun la marca."""
        for _men, _women, _boy, pe, cm in gt.TABLA_COLUMBIA:
            with self.subTest(cm=cm):
                self.assertEqual(tallas_calzado.POR_CM.get(cm), pe)

    def test_en_HOMBRE_y_NINO_coincide_con_la_guia_de_Vans(self):
        """Las dos marcas dan el mismo cm para el mismo US, asi que el PE es el
        mismo. Es lo que permite comprobar que la tabla nueva no se invento."""
        for genero, tallas in (("Masculino", ("7", "8", "9", "10", "12", "13")),
                               ("Ninos", ("1", "2", "3", "4"))):
            for talla in tallas:
                with self.subTest(genero=genero, talla=talla):
                    self.assertEqual(
                        gt.convertir(talla, "COLUMBIA", gt.CALZADO, genero)[0],
                        gt.convertir(talla, "VANS", gt.CALZADO, genero)[0],
                    )

    def test_en_MUJER_hay_media_talla_de_diferencia(self):
        """La mujer de Columbia calza 0,5 cm mas que la de Vans en el mismo
        numero US: su US 8 son 25 cm -> PE 39, y en Vans son 24,5 -> PE 38.5.
        Es justo la razon por la que hacia falta buscar su guia."""
        self.assertEqual(gt.convertir("8", "COLUMBIA", gt.CALZADO, "Femenino")[0], "39")
        self.assertEqual(gt.convertir("8", "VANS", gt.CALZADO, "Femenino")[0], "38.5")

    def test_una_talla_fuera_de_SU_tabla_se_convierte_con_la_por_defecto(self):
        """La guia de Columbia empieza en el US 7 de hombre y el maestro trae
        numeros por debajo. Sin respaldo se quedarian en US justo al lado de
        las que si se convirtieron -- que es lo que la guia por defecto existe
        para evitar."""
        convertida, nota = gt.convertir("5", "COLUMBIA", gt.CALZADO, "Masculino")
        self.assertEqual(convertida, "36.5")
        self.assertEqual(nota, gt.FUERA_DE_LA_GUIA)

    def test_pero_lo_que_no_esta_en_NINGUNA_no_se_inventa(self):
        """La nota es ahora `FUERA_DE_ESCALA` y no `desconocida`: dice cual es
        el problema -- ese numero no esta en la columna de ESE genero -- en vez
        de "no esta en la guia" a secas. Lo que no cambia es lo importante: la
        talla sale como venia y se reporta."""
        self.assertEqual(gt.convertir("99", "COLUMBIA", gt.CALZADO, "Masculino"),
                         ("99", gt.FUERA_DE_ESCALA))

    def test_sin_genero_sigue_sin_convertirse(self):
        self.assertEqual(gt.convertir("8", "COLUMBIA", gt.CALZADO, "")[1], gt.SIN_GENERO)

    def test_una_talla_que_ya_viene_en_PE_no_se_toca(self):
        self.assertEqual(gt.convertir("40.5", "COLUMBIA", gt.CALZADO, "Masculino"),
                         ("40.5", ""))

    def test_una_talla_de_NINO_fuera_de_su_columna_NO_se_cruza_de_escala(self):
        """La tabla infantil llega al US 7 y el maestro trae curvas de nino con
        numeracion infantil (US 8 a 13). Antes se buscaba ese numero en la
        columna de HOMBRE y se publicaba `43`: una zapatilla de nino en talla
        de adulto. Ahora se devuelve la de origen y se reporta."""
        convertida, nota = gt.convertir("10", "COLUMBIA", gt.CALZADO, "Ninos")
        self.assertEqual(convertida, "10")
        self.assertEqual(nota, gt.FUERA_DE_ESCALA)

    def test_las_marcas_sin_tabla_verificada_NO_se_inventan(self):
        """Se buscaron en la web (septiembre 2026) y no entraron: sus sitios
        estan bloqueados por la politica de salida, y la unica copia alcanzable
        de la de Sorel esta corrida una fila. Se convierten con la guia por
        defecto y salen avisadas, que es para lo que existe la salvedad."""
        for marca in ("HUSH PUPPIES", "KEDS", "SOREL", "ROCKFORD"):
            with self.subTest(marca=marca):
                self.assertIsNone(gt.guia_para(marca, gt.CALZADO))
                talla, nota = gt.convertir("8", marca, gt.CALZADO, "Masculino")
                self.assertEqual(talla, "40.5")
                self.assertEqual(nota, gt.POR_DEFECTO)


class TestUnaGuiaNuevaEntraPorEXCEL(unittest.TestCase):
    """`data/guias_tallas.xlsx`: una guia nueva sin tocar codigo.

    El docstring de `registrar_tabla` prometia este Excel desde que se escribio
    y **no lo leia nadie**, asi que agregar la guia de Hush Puppies seguia
    siendo un commit. Es lo que hace falta para las cuatro marcas que hoy no
    tienen tabla verificada.
    """

    def setUp(self):
        self.directorio = tempfile.mkdtemp()
        self.ruta = Path(self.directorio) / "guias_tallas.xlsx"
        g._guias_del_excel = None

    def tearDown(self):
        g._guias_del_excel = None
        for marca in ("MARCAX", "MARCAROTA", "HUSH PUPPIES"):
            gt._GUIAS.pop(gt._clave(marca, gt.CALZADO), None)
        shutil.rmtree(self.directorio, ignore_errors=True)

    def _escribir(self, hojas):
        import pandas as pd
        with pd.ExcelWriter(self.ruta) as libro:
            for nombre, filas in hojas.items():
                pd.DataFrame(filas).to_excel(libro, sheet_name=nombre, index=False)

    def test_una_hoja_por_marca_queda_registrada(self):
        self._escribir({"Hush Puppies": [
            {"US Men": "8", "US Women": "9.5", "US Boy": "", "PE": "41", "CM": "25.4"},
            {"US Men": "9", "US Women": "10.5", "US Boy": "", "PE": "42", "CM": "26.2"},
        ]})
        marcas, avisos = g.cargar_guias_de_tallas(self.ruta)
        self.assertEqual(marcas, ["HUSH PUPPIES"])
        self.assertEqual(avisos, [])
        self.assertEqual(gt.convertir("8", "HUSH PUPPIES", gt.CALZADO, "Masculino"),
                         ("41", ""))

    def test_lo_del_EXCEL_manda_sobre_lo_del_codigo(self):
        """Si alguien consigue la guia oficial de una marca que aqui esta
        aproximada, la suya gana sin tener que borrar nada."""
        self._escribir({"Vans": [
            {"US Men": "8", "US Women": "", "US Boy": "", "PE": "99", "CM": "26"},
        ]})
        g.cargar_guias_de_tallas(self.ruta)
        try:
            self.assertEqual(gt.convertir("8", "VANS", gt.CALZADO, "Masculino")[0], "99")
        finally:
            gt.registrar_guia("VANS", gt.CALZADO, gt.Guia(
                nombre="Guia de Tallas Vans 2026", marca="VANS", clase=gt.CALZADO,
                convertidor=gt._convertir_con_vans,
                ya_en_destino=tallas_calzado.ya_es_pe))
            gt.registrar_guia_por_defecto(gt.CALZADO, gt.guia_para("VANS", gt.CALZADO))

    def test_una_hoja_rota_no_se_lleva_a_las_demas(self):
        """Perder la conversion de todas las marcas porque una hoja tiene una
        columna mal escrita seria peor que el problema."""
        self._escribir({
            "MarcaX": [{"US Men": "8", "US Women": "", "US Boy": "", "PE": "44", "CM": "26"}],
            "MarcaRota": [{"Talla": "8"}],
        })
        marcas, avisos = g.cargar_guias_de_tallas(self.ruta)
        self.assertEqual(marcas, ["MARCAX"])
        self.assertEqual(len(avisos), 1)
        self.assertIn("MarcaRota", avisos[0])

    def test_sin_archivo_no_pasa_nada(self):
        """Es el caso normal: hoy el Excel no existe."""
        self.assertEqual(g.cargar_guias_de_tallas(self.ruta), ([], []))
        self.assertEqual(gt.convertir("8", "VANS", gt.CALZADO, "Masculino"), ("40.5", ""))

    def test_se_lee_UNA_vez(self):
        """Perezoso y memoizado: leerlo en cada conversion seria un viaje a
        disco por talla."""
        self._escribir({"MarcaX": [
            {"US Men": "8", "US Women": "", "US Boy": "", "PE": "44", "CM": "26"}]})
        primera = g.cargar_guias_de_tallas(self.ruta)
        self.ruta.unlink()
        self.assertEqual(g.cargar_guias_de_tallas(self.ruta), primera)

    def test_no_se_lee_en_tiempo_de_IMPORT(self):
        """Leer el Excel al importar costaria en cada arranque de la app, se
        convierta una talla o no. Es la leccion de `CENTRY_COLUMNS`."""
        arbol = ast.parse(Path(g.__file__).read_text(encoding="utf-8"))
        for nodo in arbol.body:
            if isinstance(nodo, ast.Expr) and isinstance(nodo.value, ast.Call):
                nombre = getattr(nodo.value.func, "id", "")
                self.assertNotEqual(nombre, "cargar_guias_de_tallas")


if __name__ == "__main__":
    unittest.main(verbosity=2)
