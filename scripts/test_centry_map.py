"""Pruebas del motor Centry basado en la plantilla oficial.

La plantilla `data/plantilla_centry_productos.xlsx` es la fuente de verdad:
columnas, valores permitidos y categorias salen de ahi, no del codigo.

Ejecutar:  python scripts/test_centry_map.py
"""
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from engines import centry_map as cm  # noqa: E402


class TestLecturaDeLaPlantilla(unittest.TestCase):
    def test_siempre_tiene_las_26_columnas(self):
        self.assertEqual(len(cm.cargar_plantilla()["siempre"]), 26)

    def test_siempre_no_es_un_diccionario_sino_ejemplos(self):
        """Regresion: sus 2 filas son productos de ejemplo.

        Tomarlas como valores permitidos rechazaba todos los productos reales:
        "Casaca Lino Hombre Salento Rockford AZUL" no estaria "entre los valores
        permitidos" de la columna Nombre del Producto.
        """
        for columna in ("Nombre del Producto", "Marca", "Garantía", "Descripcion"):
            self.assertEqual(cm.valores_permitidos(columna), [], columna)
        self.assertTrue(cm.valor_valido("Nombre del Producto", "Casaca Cualquiera")[1])

    def test_cada_familia_suma_siempre_mas_lo_suyo(self):
        siempre = set(cm.cargar_plantilla()["siempre"])
        for familia in (cm.SUPERIOR, cm.INFERIOR, cm.CALZADO, cm.ACCESORIOS):
            columnas = cm.columnas_de(familia)
            self.assertTrue(siempre <= set(columnas), familia)
            self.assertGreater(len(columnas), len(siempre), familia)

    def test_la_columna_repetida_de_calzado_se_queda_con_el_diccionario(self):
        """Forma de la punta sale dos veces en Calzado; la primera va vacia."""
        columnas = cm.columnas_de(cm.CALZADO)
        punta = [c for c in columnas if c.startswith("Forma de la punta - Calzado")]
        self.assertEqual(len(punta), 1)
        self.assertEqual(
            cm.valores_permitidos(punta[0]),
            ["Redonda", "Cuadrada", "Abierta", "Puntiaguda"],
        )

    def test_las_hojas_de_tipo_si_traen_diccionarios(self):
        self.assertEqual(
            cm.valores_permitidos("Tipo de caña - Calzado (Falabella GSC Perú)"),
            ["Baja", "Alta", "Media"],
        )


class TestFamilia(unittest.TestCase):
    def test_reconoce_las_cuatro_familias(self):
        casos = [
            ("MOCASÍN", cm.CALZADO), ("Zapatillas", cm.CALZADO), ("Alpargatas", cm.CALZADO),
            ("CASACA", cm.SUPERIOR), ("Polo", cm.SUPERIOR), ("Hoody", cm.SUPERIOR),
            ("Pantalón", cm.INFERIOR), ("Short", cm.INFERIOR), ("Legging", cm.INFERIOR),
            ("Mochila", cm.ACCESORIOS), ("Chullo", cm.ACCESORIOS), ("Calcetines", cm.ACCESORIOS),
        ]
        for tipo, esperada in casos:
            self.assertEqual(cm.detectar_familia(tipo)[0], esperada, tipo)

    def test_ignora_tildes_y_mayusculas(self):
        self.assertEqual(cm.detectar_familia("mocasin")[0], cm.CALZADO)
        self.assertEqual(cm.detectar_familia("PANTALÓN")[0], cm.INFERIOR)

    def test_la_clase_sirve_de_respaldo(self):
        self.assertEqual(cm.detectar_familia("Algo Nuevo", clase="Calzado")[0], cm.CALZADO)

    def test_lo_dudoso_queda_pendiente_y_no_se_inventa(self):
        # Interior Termico y Ropa de Bano pueden ser superior o inferior.
        for tipo in ("Interior Térmico", "Ropa De Baño", "Algo Raro"):
            familia, motivo = cm.detectar_familia(tipo)
            self.assertEqual(familia, "", tipo)
            self.assertTrue(motivo)


class TestTipoPorDiccionario(unittest.TestCase):
    """El tipo pasa primero por el diccionario; si no esta, se acepta y avisa."""

    def test_devuelve_el_canonico_y_la_clase(self):
        tipo, clase, aviso = cm.resolver_tipo("MOCASÍN")
        self.assertEqual(tipo, "Mocasines")
        self.assertEqual(clase, "Calzado")
        self.assertEqual(aviso, "")

    def test_resuelve_sinonimos(self):
        self.assertEqual(cm.resolver_tipo("Chullo")[0], "Chullos")

    def test_lo_que_no_esta_se_acepta_con_advertencia(self):
        tipo, clase, aviso = cm.resolver_tipo("Inventado XYZ")
        self.assertEqual(tipo, "Inventado XYZ", "se acepta tal cual, no se descarta")
        self.assertEqual(clase, "")
        self.assertIn("no está en el diccionario", aviso)

    def test_sin_tipo_avisa(self):
        self.assertIn("no trae tipo", cm.resolver_tipo("")[2])


class TestCategoria(unittest.TestCase):
    def test_la_marca_concreta_gana_sobre_todos(self):
        categoria, _ = cm.resolver_categoria("Columbia", "Zapatillas", "Hombre")
        self.assertIn("Outdoor", categoria)

    def test_usa_todos_si_no_hay_regla_de_marca(self):
        categoria, _ = cm.resolver_categoria("Rockford", "Mocasines", "Mujer")
        self.assertTrue(categoria.startswith("Calzados / Calzados Femeninos"))

    def test_normaliza_genero(self):
        for genero in ("Hombre", "MASCULINO", "varón"):
            categoria, _ = cm.resolver_categoria("Rockford", "Mocasines", genero)
            self.assertTrue(categoria.startswith("Calzados / Calzados Masculinos"), genero)

    def test_entre_general_y_especifica_elige_la_general_y_avisa(self):
        categoria, aviso = cm.resolver_categoria("Rockford", "Botas y botines", "Hombre")
        self.assertEqual(categoria, "Calzados / Calzados Masculinos / Botas, bototos y botines")
        self.assertIn("revisar", aviso.lower())

    def test_si_las_opciones_estan_al_mismo_nivel_no_elige(self):
        # Guantes / Unisex Adultos duda entre Deporte Masculino y Femenino.
        categoria, aviso = cm.resolver_categoria("Rockford", "Guantes", "Unisex Adultos")
        self.assertEqual(categoria, "")
        self.assertIn("igual de especificas", aviso)

    def test_sin_coincidencia_queda_pendiente(self):
        categoria, aviso = cm.resolver_categoria("Rockford", "Tipo Inexistente", "Hombre")
        self.assertEqual(categoria, "")
        self.assertIn("no hay categoria", aviso)

    def test_genero_desconocido_no_inventa(self):
        categoria, aviso = cm.resolver_categoria("Rockford", "Mocasines", "Marciano")
        self.assertEqual(categoria, "")
        self.assertIn("no reconocido", aviso)


class TestValores(unittest.TestCase):
    def test_devuelve_la_ortografia_de_la_plantilla(self):
        valor, ok = cm.valor_valido("Tipo de caña - Calzado (Falabella GSC Perú)", "BAJA")
        self.assertTrue(ok)
        self.assertEqual(valor, "Baja")

    def test_marca_lo_que_no_esta_permitido(self):
        _, ok = cm.valor_valido("Tipo de caña - Calzado (Falabella GSC Perú)", "Altísima")
        self.assertFalse(ok)

    def test_el_texto_libre_pasa_siempre(self):
        _, ok = cm.valor_valido("Material principal - Calzado (Falabella GSC Perú)", "Cuero raro")
        self.assertTrue(ok)

    def test_el_vacio_es_valido(self):
        self.assertEqual(
            cm.valor_valido("Tipo de caña - Calzado (Falabella GSC Perú)", ""), ("", True)
        )


class TestConstruirProducto(unittest.TestCase):
    def _datos(self):
        return {
            "Nombre del Producto": "Mocasín Cuero Mujer Rockford",
            "Marca": "Rockford",
            "SKU del producto": "RK202011432-645",
            "SKU de la variante": "5455311",
            "Color": "Marrón",
            "Talla": "36",
            "URL imagen principal": "https://ejemplo/1.jpg",
            "Tipo de caña - Calzado (Falabella GSC Perú)": "baja",
        }

    def _mocasin(self, datos=None):
        return cm.construir_producto(
            datos or self._datos(), marca="Rockford", tipo="Mocasines", genero="Mujer"
        )

    def test_arma_solo_las_columnas_de_su_familia(self):
        resultado = self._mocasin()
        self.assertEqual(resultado["familia"], cm.CALZADO)
        self.assertEqual(set(resultado["columnas"]), set(cm.columnas_de(cm.CALZADO)))
        self.assertNotIn(
            "Tipo de prenda para la parte superior - Ropa y accesorios (Falabella GSC Perú)",
            resultado["fila"],
        )

    def test_resuelve_la_categoria_sola(self):
        self.assertTrue(
            self._mocasin()["fila"]["Categoría"].startswith("Calzados / Calzados Femeninos")
        )

    def test_corrige_la_ortografia_del_diccionario(self):
        fila = self._mocasin()["fila"]
        self.assertEqual(fila["Tipo de caña - Calzado (Falabella GSC Perú)"], "Baja")

    def test_rellena_los_valores_de_una_sola_opcion(self):
        fila = self._mocasin()["fila"]
        self.assertEqual(
            fila["Incluir en Falabella Global Peru / FalabellaGlobalProduction"], "SI"
        )
        self.assertEqual(fila["Incluir en MercadoLibrePe / MercadoLibrePe"], "SI")

    def test_avisa_de_los_obligatorios_vacios(self):
        datos = self._datos()
        datos["Color"] = ""
        campos = {p["campo"] for p in self._mocasin(datos)["pendientes"]}
        self.assertIn("Color", campos)

    def test_avisa_del_valor_fuera_del_diccionario(self):
        datos = self._datos()
        datos["Tipo de caña - Calzado (Falabella GSC Perú)"] = "Altísima"
        problemas = " ".join(p["problema"] for p in self._mocasin(datos)["pendientes"])
        self.assertIn("no está entre los valores permitidos", problemas)

    def test_sin_familia_el_producto_sale_igual_con_advertencia(self):
        """El producto no puede desaparecer del archivo por un tipo no reconocido."""
        resultado = cm.construir_producto(
            self._datos(), marca="Rockford", tipo="Interior Térmico", genero="Mujer",
            mod_col="RK202011432-645", talla="M",
        )
        self.assertEqual(resultado["familia"], "")
        self.assertTrue(resultado["fila"], "la fila tiene que salir igual")
        # Lleva SIEMPRE y la cola, pero no los atributos de marketplace.
        for columna in cm.cargar_plantilla()["siempre"]:
            self.assertIn(columna, resultado["fila"])
        self.assertNotIn("Tipo de caña - Calzado (Falabella GSC Perú)", resultado["fila"])
        self.assertIn("no se pudo deducir la familia", resultado["fila"][cm.COLUMNA_ADVERTENCIA])

    def test_la_validacion_junta_los_pendientes_por_sku(self):
        datos = self._datos()
        datos["Color"] = ""
        avisos = cm.validar_productos([{"sku": "5455311", "resultado": self._mocasin(datos)}])
        self.assertTrue(avisos)
        self.assertEqual(avisos[0]["SKU"], "5455311")
        self.assertEqual(avisos[0]["Familia"], "Calzado")


class TestColumnasClave(unittest.TestCase):
    """COD MOD, COD COL y TALLA cierran el archivo; no vienen en la plantilla."""

    def _construir(self, mod_col="RK202011432-645", talla="36", tipo="Mocasines"):
        datos = {
            "Nombre del Producto": "Mocasín Cuero Mujer", "Marca": "Rockford",
            "SKU del producto": "RK202011432-645", "SKU de la variante": "5455311",
            "Color": "Marrón", "Talla": talla, "URL imagen principal": "https://x/1.jpg",
        }
        return cm.construir_producto(
            datos, marca="Rockford", tipo=tipo, genero="Mujer", mod_col=mod_col, talla=talla
        )

    def test_van_al_final_y_en_orden(self):
        for familia in ("", cm.SUPERIOR, cm.INFERIOR, cm.CALZADO, cm.ACCESORIOS):
            columnas = cm.columnas_de(familia)
            self.assertEqual(columnas[-4:], list(cm.COLUMNAS_CLAVE) + [cm.COLUMNA_ADVERTENCIA], familia)

    def test_parte_el_mod_col_en_modelo_y_color(self):
        fila = self._construir()["fila"]
        self.assertEqual(fila["COD MOD"], "RK202011432")
        self.assertEqual(fila["COD COL"], "645")
        self.assertEqual(fila["TALLA"], "36")

    def test_sin_guion_todo_es_modelo(self):
        fila = self._construir(mod_col="RK202011432")["fila"]
        self.assertEqual(fila["COD MOD"], "RK202011432")
        self.assertEqual(fila["COD COL"], "")

    def test_avisa_si_una_clave_queda_vacia(self):
        pendientes = self._construir(mod_col="")["pendientes"]
        campos = {p["campo"] for p in pendientes}
        self.assertIn("COD MOD", campos)

    def test_la_advertencia_resume_todos_los_pendientes(self):
        resultado = self._construir(mod_col="", tipo="Tipo Inexistente")
        aviso = resultado["fila"][cm.COLUMNA_ADVERTENCIA]
        self.assertIn("COD MOD", aviso)
        self.assertIn("Categoría", aviso)

    def test_sin_pendientes_la_advertencia_va_vacia(self):
        fila = self._construir()["fila"]
        self.assertEqual(fila[cm.COLUMNA_ADVERTENCIA], "")



if __name__ == "__main__":
    unittest.main(verbosity=2)
