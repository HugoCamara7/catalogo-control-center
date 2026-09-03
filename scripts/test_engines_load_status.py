"""Pruebas del motor de Status de carga de catalogos.

Origen: el seguimiento se llevaba a mano en `Status_Carga_Catalogo.xlsx`, con
las casillas de marca por sitio y los SKUs por clase escritos uno a uno. Se
reemplaza por datos vivos, y se agrega la columna que el Excel no tenia: de lo
que esta cargado, que quedo PRENDIDO Y VISIBLE en la web y que no.

Ejecutar:  python scripts/test_engines_load_status.py
"""
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from engines import load_status as ls  # noqa: E402

ETIQUETAS = {"rockford": "Rockford.pe", "columbia": "Columbia.pe", "hush_puppies": "HushPuppies.pe"}


def producto(mod_col, handle="", marca="", tipo="", estado="ACTIVE", publicado="SI",
             tags="", vendor="rockfordpe", fotos=""):
    return {
        "Mod-Col": mod_col,
        "Handle": handle or mod_col.lower(),
        "Marca": marca,
        "Vendor": vendor,
        "Type": tipo,
        "Status": estado,
        "Published Online Store": publicado,
        "Tags": tags,
        "Image Src": fotos,
    }


def solicitud(code, brand, status, model_colors=(), load_type="complete",
              created_at="2026-09-01T10:00:00", sites=("Rockford.pe",), products=0):
    return {
        "code": code,
        "brand": brand,
        "status": status,
        "sites": list(sites),
        "load_type": load_type,
        "created_at": created_at,
        "model_colors": list(model_colors),
        "summary": {"products": products},
        "requester_name": "Comercial",
        "brand_comment": "",
    }


CLASE_POR_TIPO = {"casaca": "Vestuario", "zapatilla": "Calzado", "gorro": "Accesorios"}


def clase_de_tipo(tipo):
    return CLASE_POR_TIPO.get(str(tipo).strip().casefold(), "")


class TestLecturaDelProducto(unittest.TestCase):
    def test_la_marca_sale_del_metacampo_no_del_vendor(self):
        # Vendor es del SITIO: contando por vendor, Rockford.pe tendria una
        # sola marca y Columbia, Patagonia y Sorel desaparecerian.
        p = producto("AB1234-620", marca="Columbia", vendor="rockfordpe")
        self.assertEqual(ls.marca_de_producto(p), "Columbia")

    def test_sin_metacampo_la_busca_en_los_tags(self):
        p = producto("AB1234-620", marca="", tags="Hombre, Vestuario, Patagonia, Azul")
        self.assertEqual(ls.marca_de_producto(p, ["Columbia", "Patagonia"]), "Patagonia")

    def test_sin_marca_en_ningun_lado(self):
        self.assertEqual(ls.marca_de_producto(producto("AB1-620"), ["Columbia"]), ls.SIN_MARCA)

    def test_la_clase_se_deriva_del_tipo(self):
        p = producto("AB1-620", tipo="Casaca")
        self.assertEqual(ls.clase_de_producto(p, clase_de_tipo), "Vestuario")

    def test_si_el_tipo_no_resuelve_cae_al_tag_de_clase(self):
        p = producto("AB1-620", tipo="Cosa rara", tags="Hombre, Calzado")
        self.assertEqual(ls.clase_de_producto(p, clase_de_tipo), "Calzado")

    def test_sin_tipo_ni_tag_queda_sin_clase(self):
        self.assertEqual(ls.clase_de_producto(producto("AB1-620"), clase_de_tipo), ls.SIN_CLASE)


class TestEstadoEnLaWeb(unittest.TestCase):
    def test_activo_y_publicado_esta_prendido(self):
        self.assertEqual(ls.estado_web(producto("A-1", estado="ACTIVE", publicado="SI")), ls.PRENDIDO)
        self.assertTrue(ls.visible_en_la_web(producto("A-1")))

    def test_activo_sin_publicar_no_lo_ve_nadie(self):
        p = producto("A-1", estado="ACTIVE", publicado="NO")
        self.assertEqual(ls.estado_web(p), ls.ACTIVO_SIN_PUBLICAR)
        self.assertFalse(ls.visible_en_la_web(p))

    def test_sin_dato_de_publicacion_no_se_da_por_publicado(self):
        # La tienda puede no exponer el canal. Inventar un SI seria reportar
        # como visible algo que quiza no lo esta.
        p = producto("A-1", estado="ACTIVE", publicado="")
        self.assertEqual(ls.estado_web(p), ls.ACTIVO_SIN_PUBLICAR)

    def test_borrador_y_archivado(self):
        self.assertEqual(ls.estado_web(producto("A-1", estado="DRAFT")), ls.BORRADOR)
        self.assertEqual(ls.estado_web(producto("A-1", estado="ARCHIVED")), ls.ARCHIVADO)


class TestInventario(unittest.TestCase):
    def test_un_modelo_color_se_cuenta_una_vez_por_sitio(self):
        catalogos = {"rockford": [
            producto("AB1234-620", handle="uno", marca="Columbia"),
            producto("AB1234-620", handle="duplicado", marca="Columbia"),
        ]}
        filas = ls.inventario(catalogos, clase_de_tipo, ["Columbia"], ETIQUETAS)
        self.assertEqual(len(filas), 1)

    def test_el_mismo_modelo_en_dos_sitios_da_dos_filas(self):
        catalogos = {
            "rockford": [producto("AB1234-620", marca="Columbia")],
            "columbia": [producto("AB1234-620", marca="Columbia")],
        }
        filas = ls.inventario(catalogos, clase_de_tipo, ["Columbia"], ETIQUETAS)
        self.assertEqual(len(filas), 2)
        self.assertEqual({f["Sitio"] for f in filas}, {"Rockford.pe", "Columbia.pe"})

    def test_un_sitio_vacio_no_aporta_filas(self):
        filas = ls.inventario({"rockford": [], "columbia": None}, clase_de_tipo, [], ETIQUETAS)
        self.assertEqual(filas, [])


class TestMatrizMarcasPorSitio(unittest.TestCase):
    def setUp(self):
        self.catalogos = {
            "rockford": [
                producto("RK1-620", marca="Rockford", tipo="Zapatilla"),
                producto("CO1-410", marca="Columbia", tipo="Casaca"),
            ],
            "columbia": [producto("CO1-410", marca="Columbia", tipo="Casaca")],
            "hush_puppies": [producto("HP1-100", marca="Hush Puppies", tipo="Zapatilla")],
        }
        self.filas = ls.inventario(self.catalogos, clase_de_tipo,
                                   ["Rockford", "Columbia", "Hush Puppies"], ETIQUETAS)
        self.tabla = {f["Marca"]: f for f in ls.matriz_marcas_por_sitio(
            self.filas, ["Rockford.pe", "Columbia.pe", "HushPuppies.pe"])}

    def test_la_casilla_se_marca_donde_hay_catalogo(self):
        self.assertEqual(self.tabla["Columbia"]["Rockford.pe"], ls.MARCADO)
        self.assertEqual(self.tabla["Columbia"]["Columbia.pe"], ls.MARCADO)
        self.assertEqual(self.tabla["Columbia"]["HushPuppies.pe"], ls.SIN_MARCAR)

    def test_cuenta_los_sitios_activos(self):
        self.assertEqual(self.tabla["Columbia"]["Sitios activos"], 2)
        self.assertEqual(self.tabla["Rockford"]["Sitios activos"], 1)

    def test_el_sku_en_dos_sitios_no_se_cuenta_dos_veces(self):
        # Columbia tiene UN modelo publicado en dos sitios: son 1 SKU, no 2.
        self.assertEqual(self.tabla["Columbia"]["Total SKUs"], 1)
        self.assertEqual(self.tabla["Columbia"]["SKUs Vestuario"], 1)
        self.assertEqual(self.tabla["Columbia"]["SKUs Calzado"], 0)


class TestResumenPorClase(unittest.TestCase):
    def test_suma_por_marca_y_cierra_con_el_total(self):
        catalogos = {"rockford": [
            producto("RK1-620", marca="Rockford", tipo="Zapatilla"),
            producto("RK2-620", marca="Rockford", tipo="Casaca"),
            producto("CO1-410", marca="Columbia", tipo="Gorro"),
        ]}
        filas = ls.inventario(catalogos, clase_de_tipo, ["Rockford", "Columbia"], ETIQUETAS)
        tabla = {f["Marca"]: f for f in ls.resumen_por_clase(filas)}
        self.assertEqual(tabla["Rockford"]["Calzado"], 1)
        self.assertEqual(tabla["Rockford"]["Vestuario"], 1)
        self.assertEqual(tabla["Rockford"]["Total"], 2)
        self.assertEqual(tabla["Columbia"]["Accesorios"], 1)
        self.assertEqual(tabla["Total"]["Total"], 3)


class TestEstadoDeVisibilidad(unittest.TestCase):
    def setUp(self):
        self.catalogos = {"rockford": [
            producto("RK1-620", marca="Rockford", tipo="Zapatilla", estado="ACTIVE", publicado="SI"),
            producto("RK2-620", marca="Rockford", tipo="Zapatilla", estado="ACTIVE", publicado="NO"),
            producto("RK3-620", marca="Rockford", tipo="Zapatilla", estado="DRAFT"),
            producto("RK4-620", marca="Rockford", tipo="Zapatilla", estado="ACTIVE", publicado="SI"),
        ]}
        self.filas = ls.inventario(self.catalogos, clase_de_tipo, ["Rockford"], ETIQUETAS)

    def test_separa_lo_prendido_de_lo_que_no_se_ve(self):
        fila = ls.estado_de_visibilidad(self.filas)[0]
        self.assertEqual(fila["Cargados"], 4)
        self.assertEqual(fila[ls.PRENDIDO], 2)
        self.assertEqual(fila[ls.ACTIVO_SIN_PUBLICAR], 1)
        self.assertEqual(fila[ls.BORRADOR], 1)
        self.assertEqual(fila["No visibles"], 2)
        self.assertEqual(fila["% visible"], 50.0)

    def test_el_detalle_lista_solo_los_apagados(self):
        detalle = ls.productos_no_visibles(self.filas)
        self.assertEqual({f["Mod-Col"] for f in detalle}, {"RK2-620", "RK3-620"})

    def test_el_limite_recorta(self):
        self.assertEqual(len(ls.productos_no_visibles(self.filas, limite=1)), 1)


class TestRegistroDeCargas(unittest.TestCase):
    def test_una_fila_por_solicitud_con_sus_skus(self):
        solicitudes = [
            solicitud("SOL-1", "Columbia", "completed", model_colors=["A-1", "A-2", "A-3"]),
            solicitud("SOL-2", "Patagonia", "loading", model_colors=["B-1"], load_type="partial"),
        ]
        tabla = {f["Codigo"]: f for f in ls.registro_de_cargas(solicitudes, lambda e: e)}
        self.assertEqual(tabla["SOL-1"]["Cantidad de SKUs"], 3)
        self.assertEqual(tabla["SOL-1"]["Tipo de carga"], "Carga nueva")
        self.assertEqual(tabla["SOL-2"]["Tipo de carga"], "Actualizacion")
        self.assertEqual(tabla["SOL-2"]["Marca"], "Patagonia")

    def test_solicitud_vieja_sin_model_colors_usa_el_resumen(self):
        tabla = ls.registro_de_cargas([solicitud("SOL-3", "Vans", "completed", products=42)], lambda e: e)
        self.assertEqual(tabla[0]["Cantidad de SKUs"], 42)


class TestAvanceDeSolicitudes(unittest.TestCase):
    def setUp(self):
        self.finales = ("Finalizada",)
        self.mapa = {"completed": "Finalizada", "loading": "En ejecución", "observed": "Observada"}
        self.visible = lambda estado: self.mapa.get(str(estado), "Pendiente de revisión")
        self.solicitudes = [
            solicitud("S1", "Columbia", "completed", model_colors=["A-1", "A-2"]),
            solicitud("S2", "Columbia", "loading", model_colors=["A-3"]),
            solicitud("S3", "Patagonia", "observed", model_colors=["B-1", "B-2", "B-3"]),
        ]

    def test_lo_que_falta_es_lo_inyectado_menos_lo_terminado(self):
        tabla = {f["Marca"]: f for f in ls.resumen_de_solicitudes(
            self.solicitudes, self.visible, self.finales)}
        self.assertEqual(tabla["Columbia"]["SKUs inyectados"], 3)
        self.assertEqual(tabla["Columbia"]["SKUs terminados"], 2)
        self.assertEqual(tabla["Columbia"]["SKUs en curso"], 1)
        self.assertEqual(tabla["Patagonia"]["SKUs en curso"], 3)
        self.assertEqual(tabla["Patagonia"]["% avance"], 0.0)

    def test_agrupa_por_estado_visible(self):
        tabla = {f["Estado"]: f for f in ls.solicitudes_por_estado(self.solicitudes, self.visible)}
        self.assertEqual(tabla["Finalizada"]["SKUs"], 2)
        self.assertEqual(tabla["Observada"]["SKUs"], 3)
        self.assertEqual(tabla["En ejecución"]["Solicitudes"], 1)

    def test_respeta_el_orden_pedido(self):
        orden = ["Pendiente de revisión", "En ejecución", "Finalizada", "Observada"]
        estados = [f["Estado"] for f in ls.solicitudes_por_estado(self.solicitudes, self.visible, orden)]
        self.assertEqual(estados, ["En ejecución", "Finalizada", "Observada"])


class TestKpis(unittest.TestCase):
    def test_el_titular_cuadra_con_las_tablas(self):
        catalogos = {
            "rockford": [
                producto("RK1-620", marca="Rockford", tipo="Zapatilla", publicado="SI"),
                producto("RK2-620", marca="Rockford", tipo="Zapatilla", publicado="NO"),
            ],
            "columbia": [producto("RK1-620", marca="Rockford", tipo="Zapatilla", publicado="SI")],
        }
        filas = ls.inventario(catalogos, clase_de_tipo, ["Rockford"], ETIQUETAS)
        visible = lambda estado: "Finalizada" if estado == "completed" else "En ejecución"
        solicitudes = [
            solicitud("S1", "Rockford", "completed", model_colors=["RK1-620"]),
            solicitud("S2", "Rockford", "loading", model_colors=["RK3-620", "RK4-620"]),
        ]
        k = ls.kpis(filas, solicitudes, visible, ("Finalizada",))
        self.assertEqual(k["Productos cargados"], 3)      # 2 en Rockford + 1 en Columbia
        self.assertEqual(k["Modelo-Color unicos"], 2)     # RK1 y RK2
        self.assertEqual(k["Prendidos y visibles"], 2)
        self.assertEqual(k["No visibles"], 1)
        self.assertEqual(k["SKUs inyectados"], 3)
        self.assertEqual(k["SKUs terminados"], 1)
        self.assertEqual(k["SKUs en curso"], 2)
        self.assertEqual(k["Solicitudes en curso"], 1)
        self.assertEqual(k["Sitios con catalogo"], 2)

    def test_catalogo_vacio_no_divide_entre_cero(self):
        k = ls.kpis([], [], lambda e: e, ())
        self.assertEqual(k["% visible"], 0.0)
        self.assertEqual(k["Productos cargados"], 0)


class TestLaPantallaPideLoQueElMotorDa(unittest.TestCase):
    """La pantalla y el motor tienen que hablar el mismo idioma.

    Origen: `render_status_de_carga` pedia `kpis["Marcas con catálogo"]` CON
    tilde, y el motor la devuelve SIN tilde como todas las suyas. Un solo
    caracter, y la pantalla entera caia con `KeyError` en produccion.

    No lo atrapo ninguna prueba porque estaban todas sobre el motor y sobre el
    armado de tablas; la funcion que DIBUJA no la tocaba nadie. Esto la revisa
    sin necesidad de levantar Streamlit: se leen del arbol las claves que pide
    y se comparan con las que el motor produce.
    """

    def _claves_que_pide(self, funcion, variable):
        import ast
        fuente = (ROOT / "app_matrixify.py").read_text(encoding="utf-8-sig")
        for nodo in ast.walk(ast.parse(fuente)):
            if isinstance(nodo, ast.FunctionDef) and nodo.name == funcion:
                claves = set()
                for sub in ast.walk(nodo):
                    if (isinstance(sub, ast.Subscript)
                            and isinstance(sub.value, ast.Name)
                            and sub.value.id == variable
                            and isinstance(sub.slice, ast.Constant)
                            and isinstance(sub.slice.value, str)):
                        claves.add(sub.slice.value)
                    # Tambien `kpis.get("...")`. Un `.get()` con la clave mal
                    # escrita NO revienta: devuelve None y el numero o el aviso
                    # simplemente no aparece nunca. Es peor que el KeyError,
                    # porque nadie se entera.
                    elif (isinstance(sub, ast.Call)
                            and isinstance(sub.func, ast.Attribute)
                            and sub.func.attr == "get"
                            and isinstance(sub.func.value, ast.Name)
                            and sub.func.value.id == variable
                            and sub.args
                            and isinstance(sub.args[0], ast.Constant)
                            and isinstance(sub.args[0].value, str)):
                        claves.add(sub.args[0].value)
                return claves
        raise AssertionError(f"No existe la funcion {funcion}")

    def test_los_kpis_que_dibuja_la_pantalla_existen(self):
        pedidas = self._claves_que_pide("render_status_de_carga", "kpis")
        self.assertTrue(pedidas, "No se encontro ninguna clave; cambio la pantalla")
        producidas = set(ls.kpis([], [], lambda e: e, ()))
        faltan = pedidas - producidas
        self.assertEqual(faltan, set(),
                         f"La pantalla pide KPIs que el motor no devuelve: {sorted(faltan)}")

    def test_las_tablas_que_dibuja_la_pantalla_existen(self):
        # Mismo riesgo con las tablas: la pantalla lee `tablas["registro"]` y
        # compania, que arma `construir_status_de_carga`.
        pedidas = self._claves_que_pide("render_status_de_carga", "tablas")
        armadas = self._claves_que_pide("construir_status_de_carga", "tablas")
        # `construir_status_de_carga` las devuelve en un literal, no por indice:
        # se leen del diccionario que retorna.
        import ast
        fuente = (ROOT / "app_matrixify.py").read_text(encoding="utf-8-sig")
        for nodo in ast.walk(ast.parse(fuente)):
            if isinstance(nodo, ast.FunctionDef) and nodo.name == "construir_status_de_carga":
                for sub in ast.walk(nodo):
                    if isinstance(sub, ast.Dict):
                        armadas |= {k.value for k in sub.keys
                                    if isinstance(k, ast.Constant) and isinstance(k.value, str)}
        faltan = pedidas - armadas
        self.assertEqual(faltan, set(),
                         f"La pantalla pide tablas que nadie arma: {sorted(faltan)}")


class TestProductosSinElMetacampoDelCodigo(unittest.TestCase):
    """Los productos sin `custom.codigo_modelo_color` tienen que contarse igual.

    Origen del error: `Mod-Col` sale de ese metacampo, y los productos viejos
    no lo tienen. Todas las tablas contaban con `set()` sobre ese campo, asi
    que TODOS los productos sin metacampo compartian la misma llave -- la
    cadena vacia -- y el conjunto los colapsaba en uno solo.

    No lo atrapo ninguna de las 28 pruebas anteriores porque el helper
    `producto()` exige el codigo como primer argumento y ningun caso pasaba
    uno vacio. Cero cobertura de lo que mas abunda en produccion.
    """

    def _filas(self, productos, site_key="columbia"):
        return ls.inventario({site_key: productos}, clase_de_tipo,
                             ["Columbia"], ETIQUETAS)

    def test_cada_producto_sin_codigo_se_cuenta_por_separado(self):
        filas = self._filas([
            producto("CO1-620", marca="Columbia", tipo="Zapatilla"),
            producto("", handle="vieja-1", marca="Columbia", tipo="Zapatilla"),
            producto("", handle="vieja-2", marca="Columbia", tipo="Zapatilla"),
            producto("", handle="vieja-3", marca="Columbia", tipo="Zapatilla"),
        ])
        k = ls.kpis(filas, [], lambda e: "", ())
        # Con el error: 2 (el codigo real + todos los vacios juntos).
        self.assertEqual(k["Productos cargados"], 4)
        self.assertEqual(k["Productos sin codigo Modelo-Color"], 3)
        # `Modelo-Color unicos` SI cuenta solo los que tienen codigo: es otra
        # pregunta y no debe inventar codigos que no existen.
        self.assertEqual(k["Modelo-Color unicos"], 1)

    def test_la_resta_de_no_visibles_no_se_come_los_apagados(self):
        """El peor caso: decia que todo estaba visible con la mitad apagada."""
        filas = self._filas([
            producto("", handle="visible", marca="Columbia", tipo="Zapatilla",
                     estado="ACTIVE", publicado="SI"),
            producto("", handle="borrador", marca="Columbia", tipo="Zapatilla",
                     estado="DRAFT", publicado="NO"),
        ])
        k = ls.kpis(filas, [], lambda e: "", ())
        self.assertEqual(k["Productos cargados"], 2)
        self.assertEqual(k["Prendidos y visibles"], 1)
        # Con el error: 0, porque la cadena vacia estaba en los dos conjuntos.
        self.assertEqual(k["No visibles"], 1)
        self.assertEqual(k["% visible"], 50.0)

    def test_el_handle_distingue_pero_no_choca_con_un_codigo_real(self):
        """Dos productos sin codigo y sin handle no se pueden distinguir."""
        self.assertEqual(ls.clave_de_producto({"Mod-Col": "CO1-620"}), "CO1-620")
        self.assertEqual(ls.clave_de_producto({"Handle": "vieja-1"}), "handle:vieja-1")
        self.assertEqual(ls.clave_de_producto({}), "")
        # El prefijo evita que un handle llamado como un codigo se confunda.
        self.assertNotEqual(ls.clave_de_producto({"Handle": "CO1-620"}), "CO1-620")

    def test_un_duplicado_de_verdad_sigue_contando_una_vez(self):
        """Arreglar lo anterior no puede romper la deduplicacion real."""
        filas = self._filas([
            producto("CO1-620", handle="a", marca="Columbia", tipo="Zapatilla"),
            producto("CO1-620", handle="b", marca="Columbia", tipo="Zapatilla"),
        ])
        self.assertEqual(len(filas), 1)
        k = ls.kpis(filas, [], lambda e: "", ())
        self.assertEqual(k["Productos cargados"], 1)

    def test_sin_marca_no_cuenta_como_marca(self):
        filas = self._filas([
            producto("CO1-620", marca="Columbia", tipo="Zapatilla"),
            producto("CO2-620", marca="", tipo="Zapatilla"),
        ])
        k = ls.kpis(filas, [], lambda e: "", ())
        # Con el error: 2, porque "Sin marca" entraba al conjunto de marcas.
        self.assertEqual(k["Marcas con catalogo"], 1)
        self.assertEqual(k["Productos sin marca"], 1)


class TestElTitularCuadraConLasTablasSiempre(unittest.TestCase):
    """El KPI de arriba y la tabla de abajo tienen que dar el mismo numero.

    Son dos caminos distintos: el KPI cuenta conjuntos y la tabla de
    visibilidad cuenta filas. Mientras cuenten lo mismo da igual; en cuanto uno
    colapsa filas, la pantalla se contradice sola y el usuario deja de creerle.
    Esta prueba recorre catalogos con y sin metacampo y exige que coincidan.
    """

    def _catalogos(self):
        return [
            ("todos con codigo", [
                producto("CO1-620", marca="Columbia", tipo="Zapatilla", publicado="SI"),
                producto("CO2-620", marca="Columbia", tipo="Chaqueta", publicado="NO"),
            ]),
            ("ninguno con codigo", [
                producto("", handle="v1", marca="Columbia", tipo="Zapatilla", publicado="SI"),
                producto("", handle="v2", marca="Columbia", tipo="Chaqueta", publicado="NO"),
                producto("", handle="v3", marca="Columbia", tipo="Chaqueta", estado="DRAFT"),
            ]),
            ("mezclado", [
                producto("CO1-620", marca="Columbia", tipo="Zapatilla", publicado="SI"),
                producto("", handle="v1", marca="Columbia", tipo="Zapatilla", publicado="SI"),
                producto("", handle="v2", marca="", tipo="Chaqueta", estado="ARCHIVED"),
                producto("CO2-620", marca="Columbia", tipo="Chaqueta", publicado="NO"),
            ]),
        ]

    def test_cargados_y_no_visibles_coinciden_en_los_dos_caminos(self):
        for nombre, productos in self._catalogos():
            with self.subTest(nombre):
                filas = ls.inventario({"columbia": productos}, clase_de_tipo,
                                      ["Columbia"], ETIQUETAS)
                k = ls.kpis(filas, [], lambda e: "", ())
                vis = ls.estado_de_visibilidad(filas)
                self.assertEqual(k["Productos cargados"], sum(r["Cargados"] for r in vis))
                self.assertEqual(k["Prendidos y visibles"],
                                 sum(r[ls.PRENDIDO] for r in vis))
                self.assertEqual(k["No visibles"], sum(r["No visibles"] for r in vis))
                # Y con el numero de productos que de verdad manda Shopify.
                self.assertEqual(k["Productos cargados"], len(productos))

    def test_el_detalle_de_apagados_tiene_tantas_filas_como_dice_el_kpi(self):
        for nombre, productos in self._catalogos():
            with self.subTest(nombre):
                filas = ls.inventario({"columbia": productos}, clase_de_tipo,
                                      ["Columbia"], ETIQUETAS)
                k = ls.kpis(filas, [], lambda e: "", ())
                self.assertEqual(k["No visibles"], len(ls.productos_no_visibles(filas)))


class TestSinStreamlit(unittest.TestCase):
    def test_el_motor_no_importa_streamlit(self):
        fuente = (ROOT / "engines" / "load_status.py").read_text(encoding="utf-8")
        self.assertNotIn("import streamlit", fuente)


if __name__ == "__main__":
    unittest.main(verbosity=2)
