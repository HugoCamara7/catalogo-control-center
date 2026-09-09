"""Mantenedor de Tallas: orden y escala de lo que YA esta cargado.

Por que existe
--------------
Dos cosas que se ven en la ficha y que hasta ahora solo se arreglaban al CREAR
el producto, o sea nunca para el catalogo que ya esta cargado:

1. **El orden.** Una curva ampliada despues deja la 44 entre la 38 y la 39.
2. **La escala.** Vans entrega el calzado en US y la tienda lo publica en
   PE/EU (41, 42...). Lo cargado antes de esa regla sigue diciendo "8".

Y de paso destapo un fallo de ordenamiento que estaba en produccion:
`size_sort_key` miraba `SIZE_ORDER` antes que el numero, y como esa tabla no
tiene las MEDIAS tallas, una curva de calzado PE quedaba
`36, 39, 42, 38.5, 40.5, 44.5` -- las medias, todas al final.

Ejecutar:  python scripts/test_mantenedor_tallas.py
"""
import ast
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from engines import orden_tallas as ot  # noqa: E402
from engines.tallas_calzado import talla_pe  # noqa: E402

FUENTE_APP = (ROOT / "app_matrixify.py").read_text(encoding="utf-8-sig")
ARBOL_APP = ast.parse(FUENTE_APP)


def cuerpo_de(nombre, fuente=FUENTE_APP, arbol=ARBOL_APP):
    return ast.get_source_segment(fuente, next(
        n for n in ast.walk(arbol)
        if isinstance(n, ast.FunctionDef) and n.name == nombre))


def variantes(tallas, nombre="Talla", segunda=None):
    filas = []
    for talla in tallas:
        fila = {"Option1 Name": nombre, "Option1 Value": talla,
                "Variant GID": f"gid://shopify/ProductVariant/{talla}"}
        if segunda:
            fila["Option2 Name"] = "Color"
            fila["Option2 Value"] = segunda
        filas.append(fila)
    return filas


def producto(tallas, marca="Vans", tipo="Zapatilla", **extra):
    return dict({
        "Mod-Col": "VN1-001", "Handle": "old-skool", "Title": "Old Skool",
        "Marca": marca, "Type": tipo, "Product ID": "gid://shopify/Product/1",
        "Variants": variantes(tallas),
    }, **extra)


# El criterio de orden real de la app, no uno de mentira.
from generate_columbia_matrixify import size_sort_key as ORDEN  # noqa: E402


class TestOrden(unittest.TestCase):
    def test_detecta_una_curva_desordenada(self):
        plan = ot.plan_de_producto(producto(["40", "38", "42"], marca="Columbia"), ORDEN)
        self.assertEqual(plan["Situacion"], ot.DESORDENADO)
        self.assertEqual(plan["Propuesto"], ["38", "40", "42"])
        self.assertTrue(plan["Cambia_orden"])

    def test_una_curva_ordenada_no_se_toca(self):
        plan = ot.plan_de_producto(producto(["38", "40", "42"], marca="Columbia"), ORDEN)
        self.assertEqual(plan["Situacion"], ot.ORDENADO)
        self.assertFalse(plan["Cambia_orden"])
        self.assertEqual(ot.pendientes([plan]), [])

    def test_las_tallas_de_letra_se_ordenan_por_su_escala(self):
        plan = ot.plan_de_producto(producto(["XL", "S", "M", "L"], marca="Columbia", tipo="Polera"), ORDEN)
        self.assertEqual(plan["Propuesto"], ["S", "M", "L", "XL"])

    def test_las_medias_tallas_van_en_su_lugar(self):
        """El fallo que estaba en produccion: las medias tallas quedaban todas
        al final porque no estaban en SIZE_ORDER."""
        plan = ot.plan_de_producto(
            producto(["42", "40.5", "38.5", "39", "44.5", "36"], marca="Columbia"), ORDEN)
        self.assertEqual(plan["Propuesto"], ["36", "38.5", "39", "40.5", "42", "44.5"])

    def test_un_producto_con_dos_opciones_no_se_reordena(self):
        """Con Talla y Color las variantes van en matriz: reordenarlas solo por
        talla las mezclaria."""
        prod = producto(["40", "38"], marca="Columbia")
        prod["Variants"] = variantes(["40", "38"], segunda="Negro")
        plan = ot.plan_de_producto(prod, ORDEN)
        self.assertFalse(plan["Cambia_orden"])
        self.assertIn("mas de una opcion", plan["Nota"])

    def test_un_producto_sin_opcion_de_talla_se_reporta_aparte(self):
        prod = producto([], marca="Columbia")
        prod["Variants"] = [{"Option1 Name": "Color", "Option1 Value": "Negro"}]
        plan = ot.plan_de_producto(prod, ORDEN)
        self.assertEqual(plan["Situacion"], ot.SIN_TALLAS)
        self.assertEqual(ot.pendientes([plan]), [])

    def test_un_producto_sin_variantes_no_revienta(self):
        prod = producto([], marca="Columbia")
        prod["Variants"] = []
        self.assertEqual(ot.plan_de_producto(prod, ORDEN)["Situacion"], ot.SIN_TALLAS)

    def test_reconoce_la_opcion_aunque_se_llame_size(self):
        prod = producto([], marca="Columbia")
        prod["Variants"] = variantes(["40", "38"], nombre="Size")
        plan = ot.plan_de_producto(prod, ORDEN)
        self.assertEqual(plan["Opcion"], "Size")
        self.assertTrue(plan["Cambia_orden"])


class TestEscala(unittest.TestCase):
    """Vans: de tallas americanas a europeas, con la guia oficial."""

    def convertir(self, genero="Masculino"):
        return lambda talla: talla_pe(talla, genero)

    def test_convierte_la_curva_de_hombre(self):
        plan = ot.plan_de_producto(producto(["9", "8", "10", "8.5"]), ORDEN,
                                   convertir=self.convertir())
        self.assertEqual(plan["Renombrar"], {"8": "40.5", "8.5": "41", "9": "42", "10": "43"})
        self.assertEqual(plan["Propuesto"], ["40.5", "41", "42", "43"])
        self.assertEqual(plan["Situacion"], ot.ESCALA_Y_ORDEN)

    def test_el_mismo_numero_es_otra_talla_segun_el_genero(self):
        """Un 8 de hombre es PE 40.5 y un 8 de mujer es PE 38.5. Dos tallas y
        media de diferencia."""
        hombre = ot.plan_de_producto(producto(["8"]), ORDEN, convertir=self.convertir("Masculino"))
        mujer = ot.plan_de_producto(producto(["8"]), ORDEN, convertir=self.convertir("Femenino"))
        self.assertEqual(hombre["Renombrar"]["8"], "40.5")
        self.assertEqual(mujer["Renombrar"]["8"], "38.5")

    def test_lo_que_ya_esta_en_pe_no_se_toca(self):
        plan = ot.plan_de_producto(producto(["40.5", "41", "42"]), ORDEN,
                                   convertir=self.convertir())
        self.assertEqual(plan["Renombrar"], {})
        self.assertEqual(plan["Situacion"], ot.ORDENADO)

    def test_las_infantiles_no_son_ambiguas(self):
        plan = ot.plan_de_producto(producto(["1Y", "2Y", "13C"]), ORDEN,
                                   convertir=lambda t: talla_pe(t, ""))
        self.assertEqual(plan["Renombrar"], {"13C": "30.5", "1Y": "31.5", "2Y": "32.5"})

    def test_dos_tallas_que_caen_en_la_misma_pe_no_se_renombran(self):
        """Serian dos valores iguales en la misma opcion y Shopify rechaza el
        duplicado. No se elige cual sobra: se avisa."""
        plan = ot.plan_de_producto(producto(["8", "40.5"]), ORDEN, convertir=self.convertir())
        self.assertEqual(plan["Renombrar"], {})
        self.assertIn("repetidas", plan["Nota"])

    def test_una_talla_que_no_esta_en_la_tabla_se_deja_como_esta(self):
        plan = ot.plan_de_producto(producto(["99"]), ORDEN, convertir=self.convertir())
        self.assertEqual(plan["Renombrar"], {})

    def test_la_conversion_sigue_la_guia_oficial_de_vans(self):
        """Fijado contra la guia que confirmo el usuario (Guia_de_Tallas_Vans).
        Si alguien toca la tabla, esto falla."""
        oficial_hombre = {"6.5": "38.5", "7": "39", "8": "40.5", "9.5": "42.5",
                          "10": "43", "12": "46", "16": "50"}
        for us, pe in oficial_hombre.items():
            self.assertEqual(talla_pe(us, "Masculino")[0], pe, f"US Men {us}")
        oficial_mujer = {"5": "34.5", "6": "36", "8": "38.5", "11.5": "43"}
        for us, pe in oficial_mujer.items():
            self.assertEqual(talla_pe(us, "Femenino")[0], pe, f"US Women {us}")


class TestPorMarcaYNoPorSitio(unittest.TestCase):
    """Supermall.pe lleva Vans, Columbia y Hush Puppies en la MISMA tienda: una
    bandera de sitio convertiria todo el calzado del sitio o nada."""

    def setUp(self):
        import app_matrixify as app
        self.app = app
        self.supermall = app.get_brand_config("supermall")

    def test_vans_convierte_aunque_el_sitio_no_tenga_la_bandera(self):
        self.assertFalse(self.supermall.get("tallas_calzado_pe"))
        prod = producto(["8"], marca="Vans", tipo="Zapatilla")
        self.assertIsNotNone(self.app.tallas_convertidor_para(prod, self.supermall))

    def test_otra_marca_del_mismo_sitio_convierte_con_la_guia_por_defecto(self):
        """Septiembre de 2026: el usuario pidio que TODO el calzado saliera con
        la guia. El mantenedor tiene que decir lo MISMO que la carga -- si la
        carga convierte y el mantenedor no, el mismo producto sale distinto
        segun por donde pase."""
        prod = producto(["8"], marca="Hush Puppies", tipo="Zapatilla")
        self.assertIsNotNone(self.app.tallas_convertidor_para(prod, self.supermall))

    def test_sin_ninguna_guia_el_mantenedor_no_convierte(self):
        from engines import guias_tallas as gt
        respaldo = gt.guia_por_defecto(gt.CALZADO)
        gt._POR_DEFECTO.pop(gt._clave("", gt.CALZADO)[1], None)
        try:
            prod = producto(["8"], marca="Hush Puppies", tipo="Zapatilla")
            self.assertIsNone(self.app.tallas_convertidor_para(prod, self.supermall))
        finally:
            gt.registrar_guia_por_defecto(gt.CALZADO, respaldo)

    def test_el_vestuario_de_vans_tampoco_convierte(self):
        """En vestuario una talla "12" es de nino, no un US 12."""
        prod = producto(["12"], marca="Vans", tipo="Polera")
        self.assertIsNone(self.app.tallas_convertidor_para(prod, self.supermall))

    def test_la_lista_de_marcas_esta_en_el_motor_y_no_repartida(self):
        self.assertIn("VANS", ot.MARCAS_TALLA_PE)
        self.assertTrue(ot.marca_publica_en_pe("vans"))
        self.assertFalse(ot.marca_publica_en_pe("Columbia"))


class TestReglasDelCodigo(unittest.TestCase):
    def test_el_analisis_no_escribe_nada_en_shopify(self):
        """Sin esto, en un catalogo de 800 productos se empieza a arreglar y uno
        se entera a mitad de camino."""
        for nombre in ("tallas_planificar_catalogo", "tallas_convertidor_para"):
            cuerpo = cuerpo_de(nombre)
            for prohibido in ("product_option_update", "product_variants_bulk_reorder",
                              "metafields_set", "product_update"):
                self.assertNotIn(prohibido, cuerpo, f"{nombre} escribe en Shopify")

    def test_antes_de_escribir_se_relee_el_producto(self):
        """El plan salio del catalogo cacheado; entre el analisis y el arreglo
        alguien pudo tocarlo. Escribir sobre una lectura vieja es como se
        duplican productos."""
        cuerpo = cuerpo_de("tallas_aplicar_producto")
        self.assertIn("fetch_product_options_and_variants", cuerpo)
        leer = cuerpo.index("fetch_product_options_and_variants")
        escribir = min(
            (cuerpo.index(m) for m in ("product_option_update", "product_variants_bulk_reorder")
             if m in cuerpo),
            default=len(cuerpo),
        )
        self.assertLess(leer, escribir, "se escribe antes de releer")

    def test_primero_se_renombra_y_despues_se_ordena(self):
        """Ordenar primero dejaria las etiquetas nuevas en las posiciones
        viejas."""
        cuerpo = cuerpo_de("tallas_aplicar_producto")
        self.assertLess(cuerpo.index("product_option_update"),
                        cuerpo.index("product_variants_bulk_reorder"))

    def test_el_orden_se_verifica_despues_de_escribir(self):
        """Quedar mal ordenado sin que nadie lo diga es el peor error
        silencioso, igual que un video en la posicion equivocada."""
        cuerpo = cuerpo_de("tallas_aplicar_producto")
        self.assertGreater(cuerpo.index("Verificar"), cuerpo.index("product_variants_bulk_reorder"))

    def test_se_procesa_por_bloques_y_se_guarda_dentro_del_bucle(self):
        cuerpo = cuerpo_de("render_mantenedor_tallas")
        self.assertIn("png_bloques(", cuerpo)
        bucle = cuerpo.index("for bloque in png_bloques(")
        self.assertGreater(cuerpo.index("st.session_state[f\"{estado_key}_resultados\"]"), bucle)

    def test_usa_el_mismo_criterio_de_orden_que_la_carga_completa(self):
        """Un segundo criterio se separa del primero sin que nadie lo note, y
        entonces la ficha queda en un orden y el Matrixify en otro."""
        cuerpo = cuerpo_de("tallas_orden_clave")
        self.assertIn("master_size_sort_key", cuerpo)

    def test_el_motor_no_importa_streamlit_ni_pandas(self):
        fuente = (ROOT / "engines" / "orden_tallas.py").read_text(encoding="utf-8")
        self.assertNotIn("import streamlit", fuente)
        self.assertNotIn("import pandas", fuente)

    def test_el_motor_no_trae_su_propia_tabla_de_tallas(self):
        """La conversion y el orden se INYECTAN, para que sean los mismos que
        usa la Carga completa."""
        fuente = (ROOT / "engines" / "orden_tallas.py").read_text(encoding="utf-8")
        self.assertNotIn("from engines.tallas_calzado", fuente)
        self.assertIn("orden_clave", fuente)

    def test_la_pantalla_tiene_llamador(self):
        self.assertIn("render_mantenedor_tallas(brand_config, shopify_config)", FUENTE_APP)
        self.assertIn('TALLAS_LABEL: "tallas"', FUENTE_APP)

    def test_las_claves_del_resumen_existen(self):
        """La leccion de load_status: una clave mal escrita con `.get()` no
        revienta, devuelve None y el numero no aparece nunca."""
        cuerpo = cuerpo_de("render_tallas_resumen")
        disponibles = set(ot.resumen([]))
        pedidas = {
            n.slice.value
            for n in ast.walk(ast.parse(cuerpo.strip()))
            if isinstance(n, ast.Subscript) and isinstance(n.slice, ast.Constant)
            and isinstance(n.slice.value, str)
            and isinstance(n.value, ast.Name) and n.value.id == "resumen"
        }
        self.assertTrue(pedidas)
        self.assertEqual(pedidas - disponibles, set())

    def test_size_sort_key_pone_los_numeros_por_valor(self):
        """El fallo de produccion: SIZE_ORDER no tiene medias tallas, asi que
        las conocidas caian en un grupo y las medias en otro, siempre detras."""
        import app_matrixify as app
        self.assertEqual(
            sorted(["42", "40.5", "38.5", "39"], key=app.size_sort_key),
            ["38.5", "39", "40.5", "42"],
        )
        # Y las de letra siguen igual que siempre.
        self.assertEqual(
            sorted(["XL", "S", "M", "L", "XXL", "XS"], key=app.size_sort_key),
            ["XS", "S", "M", "L", "XL", "XXL"],
        )

    def test_los_dos_criterios_de_orden_coinciden_en_numeros(self):
        import app_matrixify as app
        from generate_columbia_matrixify import size_sort_key as maestro
        tallas = ["42", "40.5", "38.5", "39", "44.5", "36", "8.5", "9"]
        self.assertEqual(sorted(tallas, key=app.size_sort_key), sorted(tallas, key=maestro))


class TestResumenYTabla(unittest.TestCase):
    def test_cuenta_cada_situacion(self):
        planes = [
            ot.plan_de_producto(producto(["38", "40"], marca="Columbia"), ORDEN),
            ot.plan_de_producto(producto(["40", "38"], marca="Columbia"), ORDEN),
            ot.plan_de_producto(producto(["8", "9"]), ORDEN,
                                convertir=lambda t: talla_pe(t, "Masculino")),
        ]
        resumen = ot.resumen(planes)
        self.assertEqual(resumen["Productos revisados"], 3)
        self.assertEqual(resumen["Ya estan bien"], 1)
        self.assertEqual(resumen["Fuera de orden"], 1)
        self.assertEqual(resumen["Escala equivocada"], 1)
        self.assertEqual(resumen["Por arreglar"], 2)

    def test_la_tabla_aplana_las_listas(self):
        plan = ot.plan_de_producto(producto(["40", "38"], marca="Columbia"), ORDEN)
        fila = ot.filas_para_tabla([plan])[0]
        self.assertEqual(fila["Tallas ahora"], "40, 38")
        self.assertEqual(fila["Tallas propuestas"], "38, 40")
        self.assertEqual(fila["Cambia orden"], "SI")

    def test_sin_planes_no_revienta(self):
        self.assertEqual(ot.resumen([])["Productos revisados"], 0)
        self.assertEqual(ot.filas_para_tabla(None), [])


class TestElPegamentoDeLaPantalla(unittest.TestCase):
    """Los tres fallos que dejaban el Mantenedor de Tallas sin efecto.

    Ninguna de las 34 pruebas anteriores los atrapo porque todas prueban el
    MOTOR, y los tres estaban en el pegamento entre el motor y la pantalla.
    Las tres de aqui fallan con el codigo anterior.
    """

    def test_el_motor_expone_indice_de_opcion_sin_guion_bajo(self):
        """`app_matrixify` llamaba a `orden_tallas._indice_de_opcion`, que no
        existe: la funcion se llama `indice_de_opcion`. Era un AttributeError
        sin capturar en `tallas_aplicar_producto`, o sea que "Aplicar" moria en
        el primer producto que hubiera que reordenar y se llevaba la pantalla
        por delante."""
        self.assertTrue(hasattr(ot, "indice_de_opcion"))
        self.assertEqual(ot.indice_de_opcion(variantes(["38", "40"]), "Talla"), "1")

    def test_la_app_no_llama_a_una_funcion_privada_que_no_existe(self):
        import inspect
        import app_matrixify as app
        cuerpo = inspect.getsource(app.tallas_aplicar_producto)
        self.assertNotIn("_indice_de_opcion", cuerpo)
        self.assertIn("orden_tallas.indice_de_opcion", cuerpo)

    def test_el_plan_lleva_el_tipo_y_el_genero(self):
        """Antes de escribir se REPLANIFICA sobre el producto releido. Si el
        plan no lleva `Type`, el conversor sale None en ese segundo pase y el
        cambio de escala **no se aplica nunca**: la pantalla contesta "Ya
        estaba bien al releerlo" y no escribe nada."""
        plan = ot.plan_de_producto(
            producto(["8", "9"], marca="Vans", tipo="Zapatilla", Genero="Masculino"),
            ORDEN,
        )
        self.assertEqual(plan["Type"], "Zapatilla")
        self.assertEqual(plan["Genero"], "Masculino")

    def test_al_replanificar_el_conversor_sigue_existiendo(self):
        """El recorrido completo: con el plan que devuelve el motor, el
        conversor de la pantalla tiene que seguir saliendo. Con el codigo
        anterior salia None porque `plan.get("Type")` era ""."""
        import app_matrixify as app
        plan = ot.plan_de_producto(
            producto(["8", "9"], marca="Vans", tipo="Zapatilla", Genero="Masculino"),
            ORDEN,
        )
        registro = {
            k: plan.get(k, "")
            for k in ("Mod-Col", "Handle", "Title", "Marca", "Product ID", "Type", "Genero")
        }
        self.assertIsNotNone(app.tallas_convertidor_para(registro, app.get_brand_config("vans")))

    def test_reorder_product_sizes_no_deja_codigo_muerto(self):
        import inspect
        import app_matrixify as app
        cuerpo = inspect.getsource(app._reorder_product_sizes)
        # Se mira la ASIGNACION, no la palabra: el comentario que explica por
        # que se quito la nombra a proposito.
        self.assertNotIn("values_in_order =", cuerpo)
        self.assertNotIn("values_in_order.extend", cuerpo)


class TestOrdenDeColumbia(unittest.TestCase):
    """Lo que reporto el usuario: `S/R M/R ... XXL/R` salia empezando por L/R."""

    def test_la_curva_con_largo_se_detecta_desordenada(self):
        plan = ot.plan_de_producto(
            producto(["L/R", "M/R", "S/R", "XL/R", "XS/R"], marca="Columbia", tipo="Casaca"),
            ORDEN,
        )
        self.assertEqual(plan["Situacion"], ot.DESORDENADO)
        self.assertEqual(plan["Propuesto"], ["XS/R", "S/R", "M/R", "L/R", "XL/R"])

    def test_columbia_no_cambia_de_escala(self):
        """Columbia solo necesita ORDEN. No hay guia de conversion suya, y sin
        guia no se convierte: una talla adivinada es peor que una en US."""
        plan = ot.plan_de_producto(
            producto(["L/R", "M/R", "S/R"], marca="Columbia", tipo="Casaca"), ORDEN,
        )
        self.assertFalse(plan["Cambia_escala"])
        self.assertEqual(plan["Renombrar"], {})


if __name__ == "__main__":
    unittest.main(verbosity=2)
