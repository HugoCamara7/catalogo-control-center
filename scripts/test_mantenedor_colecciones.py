"""Mantenedor de Colecciones y Boost del orden de la PLP (septiembre 2026).

Estas pruebas **EJECUTAN** el codigo: publican contra un Shopify falso, parten
en bloques de verdad, simulan los movimientos que Shopify aplicaria uno a uno y
entran a la app con `AppTest`. No leen el codigo fuente.

Es la leccion de `start_suelto` (seccion 5 duotrigies): sus ocho pruebas leian
el texto de la funcion con `inspect.getsource` y ninguna la llamaba, asi que un
`AttributeError` que la hacia imposible de ejecutar sobrevivio a las 42 pruebas
del archivo.

Ejecutar:  python scripts/test_mantenedor_colecciones.py
"""
import random
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from engines import colecciones_admin as motor  # noqa: E402
import shopify_api  # noqa: E402

CONFIG = {"shop_domain": "tienda.myshopify.com", "admin_access_token": "x", "api_version": "2026-04"}


def producto(codigo, handle="", titulo="", tipo="", genero="", marca="", tags="", stock=0,
             product_id=""):
    """Un producto del catalogo. El codigo puede venir VACIO a proposito: es lo
    que mas abunda en produccion y lo que destapo el fallo de `clave_de_producto`."""
    return {
        "Product ID": product_id or f"gid://shopify/Product/{handle or codigo or 'x'}",
        "Handle": handle or (codigo or "").lower(),
        "Title": titulo or codigo,
        "Type": tipo,
        "Genero": genero,
        "Marca": marca,
        "Tags": tags,
        "Vendor": "tiendape",
        "Mod-Col": codigo,
        "Metafield: custom.codigo_modelo_color [single_line_text_field]": codigo,
        "Metafield: custom.genero [single_line_text_field]": genero,
        "Metafield: custom.color [single_line_text_field]": "",
        "Variants": [{"Variant Inventory Qty": stock}],
    }


class ShopifyFalso:
    """Una tienda de mentira que responde como la de verdad.

    Guarda lo que se le manda para poder comprobar QUE se escribio, y lleva la
    cuenta de las llamadas para poder comprobar CUANTAS.
    """

    def __init__(self, soporta_argumento_nuevo=True):
        self.llamadas = []
        self.soporta_argumento_nuevo = soporta_argumento_nuevo
        self.colecciones = {}
        self.agregados = []
        self.quitados = []
        self.movimientos = []
        self.jobs_pendientes = {}

    def __call__(self, shop_domain, token, query, variables=None, api_version=None,
                 timeout=20, max_retries=2):
        self.llamadas.append((query, variables))
        variables = variables or {}
        if "collectionCreate" in query:
            if "CollectionCreateInput" in query and not self.soporta_argumento_nuevo:
                raise shopify_api.ShopifyApiError(
                    "variableMismatch: CollectionCreateInput isn't a defined input type")
            entrada = variables["entrada"]
            identificador = "gid://shopify/Collection/%d" % (len(self.colecciones) + 1)
            self.colecciones[identificador] = dict(entrada)
            return {"collectionCreate": {
                "collection": {"id": identificador,
                               "handle": entrada.get("handle") or "coleccion",
                               "title": entrada.get("title"),
                               "sortOrder": entrada.get("sortOrder") or "MANUAL"},
                "userErrors": []}}
        if "collectionUpdate" in query:
            if "CollectionUpdateInput" in query and not self.soporta_argumento_nuevo:
                raise shopify_api.ShopifyApiError("Unknown argument 'collection'")
            entrada = variables["entrada"]
            self.colecciones.setdefault(entrada["id"], {}).update(entrada)
            return {"collectionUpdate": {"collection": {"id": entrada["id"]}, "userErrors": []}}
        if "collectionAddProductsV2" in query:
            self.agregados.append(list(variables["productIds"]))
            return {"collectionAddProductsV2": {
                "job": {"id": "gid://shopify/Job/add%d" % len(self.agregados), "done": False},
                "userErrors": []}}
        if "collectionRemoveProducts" in query:
            self.quitados.append(list(variables["productIds"]))
            return {"collectionRemoveProducts": {
                "job": {"id": "gid://shopify/Job/rm%d" % len(self.quitados), "done": False},
                "userErrors": []}}
        if "collectionReorderProducts" in query:
            self.movimientos.append(list(variables["moves"]))
            return {"collectionReorderProducts": {
                "job": {"id": "gid://shopify/Job/mv%d" % len(self.movimientos), "done": False},
                "userErrors": []}}
        if "job(id" in query:
            return {"job": {"id": variables["id"], "done": True}}
        if "publishablePublish" in query:
            return {"publishablePublish": {"publishable": {"id": variables["id"]},
                                           "userErrors": []}}
        return {}


class ConShopifyFalso(unittest.TestCase):
    def setUp(self):
        self.tienda = ShopifyFalso()
        self._real = shopify_api.graphql_request
        shopify_api.graphql_request = self.tienda
        # Sin esto cada espera de job dormiria 1,5 s de verdad.
        self._sleep = shopify_api.time.sleep
        shopify_api.time.sleep = lambda _s: None

    def tearDown(self):
        shopify_api.graphql_request = self._real
        shopify_api.time.sleep = self._sleep


# =========================================================================
# 1. El Excel
# =========================================================================
class TestExcel(unittest.TestCase):
    def test_lee_codigo_y_orden(self):
        items, descartes = motor.filas_de_asignacion([
            {"Código Modelo Color": "AB123-XY", "Orden": 2},
            {"Código Modelo Color": "CD456-ZW", "Orden": 1},
        ])
        self.assertEqual([i["codigo"] for i in items], ["AB123-XY", "CD456-ZW"])
        self.assertEqual([i["orden"] for i in items], [2, 1])
        self.assertEqual(descartes, [])

    def test_la_cabecera_no_distingue_tildes_ni_mayusculas(self):
        for cabecera in ("Código Modelo Color", "CODIGO MODELO COLOR", "codigo_modelo_color",
                         "Cod Mod Col", "MOD-COL"):
            with self.subTest(cabecera=cabecera):
                items, _ = motor.filas_de_asignacion([{cabecera: "AB123-XY"}])
                self.assertEqual([i["codigo"] for i in items], ["AB123-XY"])

    def test_sin_columna_de_orden_manda_el_archivo(self):
        items, _ = motor.filas_de_asignacion([{"Código": "B"}, {"Código": "A"}])
        self.assertEqual([i["codigo"] for i in items], ["B", "A"])
        self.assertEqual([i["orden"] for i in items], [None, None])

    def test_el_duplicado_se_descarta_Y_SE_EXPLICA(self):
        """Pedir 3 y procesar 2 se lee igual de bien que procesar 3 si nadie
        dice que paso con el tercero."""
        items, descartes = motor.filas_de_asignacion([
            {"Código": "A"}, {"Código": "B"}, {"Código": "a"},
        ])
        self.assertEqual([i["codigo"] for i in items], ["A", "B"])
        self.assertEqual(len(descartes), 1)
        self.assertIn("Duplicado", descartes[0]["Motivo"])
        self.assertEqual(descartes[0]["Fila"], 4)

    def test_un_orden_repetido_se_avisa_en_vez_de_desempatar_al_azar(self):
        items, descartes = motor.filas_de_asignacion([
            {"Código": "A", "Orden": 1}, {"Código": "B", "Orden": 1},
        ])
        self.assertEqual([i["codigo"] for i in items], ["A"])
        self.assertIn("ya lo pidió", descartes[0]["Motivo"])

    def test_un_orden_que_no_es_numero_se_descarta_con_su_motivo(self):
        items, descartes = motor.filas_de_asignacion([{"Código": "A", "Orden": "primero"}])
        self.assertEqual(items, [])
        self.assertIn("no es un número", descartes[0]["Motivo"])

    def test_sin_columna_de_codigo_lo_dice(self):
        items, descartes = motor.filas_de_asignacion([{"Comentario": "hola"}])
        self.assertEqual(items, [])
        self.assertIn("Código Modelo Color", descartes[0]["Motivo"])

    def test_un_excel_vacio_no_revienta(self):
        self.assertEqual(motor.filas_de_asignacion([])[0], [])
        self.assertEqual(motor.filas_de_asignacion(None)[0], [])


# =========================================================================
# 2. La validacion contra el catalogo
# =========================================================================
class TestValidacion(unittest.TestCase):
    def setUp(self):
        self.catalogo = [producto("AB123-XY", titulo="Casaca"), producto("CD456-ZW", titulo="Polo")]
        self.indice = motor.indice_de_catalogo(self.catalogo)

    def test_separa_listos_de_inexistentes(self):
        items, _ = motor.filas_de_asignacion([{"Código": "AB123-XY"}, {"Código": "NO-EXISTE"}])
        informe = motor.validar_asignacion(items, self.indice)
        self.assertEqual([f["codigo"] for f in informe["listos"]], ["AB123-XY"])
        self.assertEqual([f["codigo"] for f in informe["no_encontrados"]], ["NO-EXISTE"])
        self.assertTrue(informe["bloqueado"])

    def test_lo_que_ya_esta_dentro_no_se_vuelve_a_agregar(self):
        """Agregar lo que ya esta es un viaje de balde; en una lista de 5.000
        son 20 llamadas que no escriben nada."""
        items, _ = motor.filas_de_asignacion([{"Código": "AB123-XY"}, {"Código": "CD456-ZW"}])
        informe = motor.validar_asignacion(items, self.indice, ya_en_coleccion=["AB123-XY"])
        self.assertEqual([f["codigo"] for f in informe["listos"]], ["CD456-ZW"])
        self.assertEqual([f["codigo"] for f in informe["ya_estaban"]], ["AB123-XY"])
        self.assertFalse(informe["bloqueado"])

    def test_un_codigo_en_dos_productos_es_AMBIGUO_no_el_primero_que_caiga(self):
        catalogo = [producto("AB123-XY", handle="uno"), producto("AB123-XY", handle="dos")]
        items, _ = motor.filas_de_asignacion([{"Código": "AB123-XY"}])
        informe = motor.validar_asignacion(items, motor.indice_de_catalogo(catalogo))
        self.assertEqual(len(informe["ambiguos"]), 1)
        self.assertEqual(informe["listos"], [])
        self.assertTrue(informe["bloqueado"])

    def test_el_handle_tambien_sirve_como_codigo(self):
        items, _ = motor.filas_de_asignacion([{"Código": "AB123-XY"}])
        informe = motor.validar_asignacion(items, self.indice)
        self.assertEqual(len(informe["listos"]), 1)
        items, _ = motor.filas_de_asignacion([{"Código": "ab123-xy"}])
        informe = motor.validar_asignacion(items, self.indice)
        self.assertEqual(len(informe["listos"]), 1, "el handle tiene que valer como codigo")

    def test_un_producto_SIN_codigo_no_colapsa_con_los_demas(self):
        """El fallo de `clave_de_producto`: contando por `Mod-Col` pelado, todos
        los productos sin metacampo comparten la cadena vacia."""
        catalogo = [producto("", handle="sin-codigo-uno"), producto("", handle="sin-codigo-dos")]
        indice = motor.indice_de_catalogo(catalogo)
        items, _ = motor.filas_de_asignacion([
            {"Código": "SIN-CODIGO-UNO"}, {"Código": "SIN-CODIGO-DOS"}])
        informe = motor.validar_asignacion(items, indice)
        self.assertEqual(len(informe["listos"]), 2)
        self.assertEqual(len({f["clave"] for f in informe["listos"]}), 2,
                         "dos productos sin Mod-Col no pueden compartir clave")

    def test_hay_que_revisar_no_es_lo_mismo_que_bloqueado(self):
        items, _ = motor.filas_de_asignacion([{"Código": "AB123-XY"}])
        informe = motor.validar_asignacion(items, self.indice)
        self.assertFalse(informe["bloqueado"])
        self.assertFalse(motor.hay_que_revisar(informe))


# =========================================================================
# 3. Las reglas de coleccion inteligente
# =========================================================================
class TestReglas(unittest.TestCase):
    def test_una_regla_por_tag_no_necesita_definicion(self):
        regla, error = motor.regla_de_concepto("tag", "EQUALS", "Hiking")
        self.assertEqual(error, "")
        self.assertEqual(regla["campo"], "TAG")
        self.assertNotIn("definicion_id", regla)

    def test_la_marca_SIN_definicion_habilitada_se_RECHAZA(self):
        """Shopify aceptaria la regla y la coleccion saldria VACIA. Es el fallo
        silencioso que hay que impedir antes de crearla."""
        regla, error = motor.regla_de_concepto("marca", "EQUALS", "Columbia", definiciones={})
        self.assertIsNone(regla)
        self.assertIn("condición de colección", error)
        self.assertIn("custom.marca", error)

    def test_la_marca_CON_definicion_lleva_su_id(self):
        definiciones = {("custom", "marca"): "gid://shopify/MetafieldDefinition/7"}
        regla, error = motor.regla_de_concepto("marca", "EQUALS", "Columbia", definiciones)
        self.assertEqual(error, "")
        self.assertEqual(regla["definicion_id"], "gid://shopify/MetafieldDefinition/7")

    def test_un_concepto_numerico_no_admite_CONTAINS(self):
        regla, error = motor.regla_de_concepto("precio", "CONTAINS", "100")
        self.assertIsNone(regla)
        self.assertIn("no vale", error)
        self.assertIn("GREATER_THAN", motor.relaciones_de("precio"))

    def test_una_regla_sin_valor_se_rechaza_sin_levantar(self):
        regla, error = motor.regla_de_concepto("tag", "EQUALS", "")
        self.assertIsNone(regla)
        self.assertIn("Falta el valor", error)

    def test_no_se_usa_el_campo_DEPRECADO_de_taxonomia(self):
        """`PRODUCT_TAXONOMY_NODE_ID` esta deprecado en favor de
        `PRODUCT_CATEGORY_ID`."""
        campos = {datos["campo"] for datos in motor.CONCEPTOS.values()}
        self.assertIn("PRODUCT_CATEGORY_ID", campos)
        self.assertNotIn("PRODUCT_TAXONOMY_NODE_ID", campos)

    def test_la_vista_previa_reparte_dentro_fuera_y_NO_SE_SABE(self):
        catalogo = [
            producto("A", tags="Hiking, Verano", tipo="Casacas"),
            producto("B", tags="Running", tipo="Polos"),
        ]
        dentro, dudosos = motor.previsualizar_reglas(
            catalogo, [{"campo": "TAG", "relacion": "EQUALS", "valor": "Hiking"}])
        self.assertEqual([p["Mod-Col"] for p in dentro], ["A"])
        self.assertEqual(dudosos, [])

    def test_una_regla_por_precio_es_NO_SE_SABE_no_es_NO(self):
        """Devolver False dejaria al producto fuera sin que nadie se entere."""
        catalogo = [producto("A", tags="Hiking")]
        dentro, dudosos = motor.previsualizar_reglas(
            catalogo, [{"campo": "VARIANT_PRICE", "relacion": "GREATER_THAN", "valor": "100"}])
        self.assertEqual(dentro, [])
        self.assertEqual(len(dudosos), 1)

    def test_la_vista_previa_por_metacampo_lee_el_metacampo(self):
        catalogo = [producto("A", marca="Columbia"), producto("B", marca="Vans")]
        regla = {"campo": "PRODUCT_METAFIELD_DEFINITION", "relacion": "EQUALS",
                 "valor": "Columbia", "concepto": "marca",
                 "definicion_id": "gid://shopify/MetafieldDefinition/7"}
        dentro, _ = motor.previsualizar_reglas(catalogo, [regla])
        self.assertEqual([p["Mod-Col"] for p in dentro], ["A"])

    def test_TODAS_manda_sobre_UNA(self):
        catalogo = [producto("A", tags="Hiking", tipo="Casacas"),
                    producto("B", tags="Hiking", tipo="Polos")]
        reglas = [{"campo": "TAG", "relacion": "EQUALS", "valor": "Hiking"},
                  {"campo": "TYPE", "relacion": "EQUALS", "valor": "Casacas"}]
        todas, _ = motor.previsualizar_reglas(catalogo, reglas, disyuntiva=False)
        una, _ = motor.previsualizar_reglas(catalogo, reglas, disyuntiva=True)
        self.assertEqual([p["Mod-Col"] for p in todas], ["A"])
        self.assertEqual([p["Mod-Col"] for p in una], ["A", "B"])


# =========================================================================
# 4. El Boost
# =========================================================================
class TestMovimientos(unittest.TestCase):
    def simular(self, actual, moves):
        """Como los aplica Shopify: uno detras de otro, sacando e insertando."""
        lista = list(actual)
        for movimiento in moves:
            lista.remove(movimiento["clave"])
            lista.insert(movimiento["posicion"], movimiento["clave"])
        return lista

    def test_llegan_al_orden_pedido_en_mil_permutaciones_aleatorias(self):
        """La prueba que de verdad importa: no que los movimientos "parezcan"
        bien, sino que aplicados SECUENCIALMENTE den el orden pedido."""
        aleatorio = random.Random(20260914)
        for cuantos in (1, 2, 3, 8, 40, 120):
            for _ in range(150):
                actual = [f"P{i}" for i in range(cuantos)]
                deseado = actual[:]
                aleatorio.shuffle(deseado)
                moves = motor.movimientos(actual, deseado)
                self.assertEqual(self.simular(actual, moves), deseado,
                                 f"con {cuantos} productos")

    def test_sin_cambios_no_hay_ni_un_movimiento(self):
        orden = ["A", "B", "C"]
        self.assertEqual(motor.movimientos(orden, orden), [])

    def test_la_posicion_EMPIEZA_EN_CERO(self):
        """Confundirla con la que ve una persona deja todo corrido un puesto."""
        moves = motor.movimientos(["A", "B", "C"], ["C", "A", "B"])
        self.assertEqual(moves, [{"clave": "C", "posicion": 0}])

    def test_mover_uno_solo_cuesta_un_solo_movimiento(self):
        actual = [f"P{i}" for i in range(50)]
        deseado = ["P49"] + actual[:49]
        self.assertEqual(len(motor.movimientos(actual, deseado)), 1)

    def test_lo_que_no_esta_en_la_coleccion_no_genera_movimiento(self):
        """Eso es un alta y va por `collectionAddProductsV2`."""
        moves = motor.movimientos(["A", "B"], ["NUEVO", "A", "B"])
        self.assertEqual([m["clave"] for m in moves], [])


class TestOrdenar(unittest.TestCase):
    def contexto(self):
        return {
            "productos": {
                "A": producto("A", titulo="Zeta", tipo="Casacas", genero="Mujer", stock=5),
                "B": producto("B", titulo="Alfa", tipo="Polos", genero="Hombre", stock=90),
                "C": producto("C", titulo="Beta", tipo="Casacas", genero="Mujer", stock=0),
            },
            "rango_ventas": {"B": 0, "A": 1},
            "rango_novedad": {"C": 0, "B": 1, "A": 2},
            "orden": {"C": 1, "A": 2},
            "prioridad_genero": ["Mujer", "Hombre"],
            "prioridad_tipo": ["Casacas", "Polos"],
        }

    def test_un_solo_criterio(self):
        self.assertEqual(
            motor.ordenar(["A", "B", "C"], [{"clave": "ventas"}], self.contexto()),
            ["B", "A", "C"])

    def test_el_que_NO_TIENE_EL_DATO_va_al_final_siempre(self):
        """Un producto del que no sabemos las ventas no puede colarse arriba
        porque su valor sea cero -- y tampoco al reves al invertir el orden."""
        contexto = self.contexto()
        ascendente = motor.ordenar(["A", "B", "C"], [{"clave": "ventas"}], contexto)
        descendente = motor.ordenar(["A", "B", "C"],
                                    [{"clave": "ventas", "descendente": True}], contexto)
        self.assertEqual(ascendente[-1], "C")
        self.assertEqual(descendente[-1], "C", "sin dato va al final en las dos direcciones")

    def test_la_PRIORIDAD_manda_el_segundo_solo_desempata(self):
        contexto = self.contexto()
        # Genero manda: las dos Mujer primero; dentro, desempata el stock.
        self.assertEqual(
            motor.ordenar(["A", "B", "C"],
                          [{"clave": "genero"}, {"clave": "stock"}], contexto),
            ["A", "C", "B"])
        # Al reves manda el stock y el genero no llega a importar.
        self.assertEqual(
            motor.ordenar(["A", "B", "C"],
                          [{"clave": "stock"}, {"clave": "genero"}], contexto),
            ["B", "A", "C"])

    def test_el_orden_del_excel(self):
        self.assertEqual(
            motor.ordenar(["A", "B", "C"], [{"clave": "excel"}], self.contexto()),
            ["C", "A", "B"], "B no esta en el Excel: va al final")

    def test_es_DETERMINISTA_entre_ejecuciones(self):
        """Un plan que cambia entre dos ejecuciones no se puede comparar con el
        anterior. Es el fallo que ya se pago en `avisos_de_talla_a_issues`."""
        contexto = self.contexto()
        # Todos empatan en el criterio, asi que solo manda el orden de origen.
        criterios = [{"clave": "genero"}]
        primero = motor.ordenar(["C", "A", "B"], criterios, contexto)
        for _ in range(20):
            self.assertEqual(motor.ordenar(["C", "A", "B"], criterios, contexto), primero)

    def test_el_empate_se_rompe_por_la_posicion_de_ORIGEN(self):
        contexto = self.contexto()
        self.assertEqual(motor.ordenar(["A", "C"], [{"clave": "genero"}], contexto), ["A", "C"])
        self.assertEqual(motor.ordenar(["C", "A"], [{"clave": "genero"}], contexto), ["C", "A"])

    def test_criterios_disponibles_dice_QUE_FALTA(self):
        """Un criterio que se ofrece sin su dato produce un orden que no cambia
        nada, y eso se lee como «el Boost no funciona»."""
        disponibles = {c["clave"]: c for c in motor.criterios_disponibles({})}
        self.assertFalse(disponibles["ventas"]["listo"])
        self.assertTrue(disponibles["titulo"]["listo"], "el titulo no necesita ningun dato extra")
        disponibles = {c["clave"]: c for c in motor.criterios_disponibles({"rango_ventas": {"A": 0}})}
        self.assertTrue(disponibles["ventas"]["listo"])

    def test_un_criterio_desconocido_se_ignora_sin_levantar(self):
        self.assertEqual(
            motor.ordenar(["A", "B"], [{"clave": "inventado"}], self.contexto()), ["A", "B"])


class TestPlan(unittest.TestCase):
    def test_por_defecto_el_excel_AGREGA_no_vacia(self):
        """Un Excel de 2 codigos sobre una coleccion de 3 no le quita 1."""
        plan = motor.plan_de_coleccion({}, ["A", "B", "C"], ["A", "D"])
        self.assertEqual(plan["agregar"], ["D"])
        self.assertEqual(plan["quitar"], [])

    def test_quitar_sobrantes_se_pide_explicitamente(self):
        plan = motor.plan_de_coleccion({}, ["A", "B", "C"], ["A", "D"], quitar_sobrantes=True)
        self.assertEqual(plan["agregar"], ["D"])
        self.assertEqual(sorted(plan["quitar"]), ["B", "C"])

    def test_los_movimientos_se_calculan_TRAS_agregar_no_antes(self):
        """`collectionAddProductsV2` agrega al FINAL. Calculando sobre el estado
        de ahora, los movimientos saldrian todos corridos."""
        plan = motor.plan_de_coleccion({}, ["A", "B"], ["NUEVO", "A", "B"])
        self.assertEqual(plan["agregar"], ["NUEVO"])
        # Tras agregar queda [A, B, NUEVO]; para dejarlo primero hace falta un
        # movimiento, que sobre el estado de antes no se habria emitido.
        self.assertEqual(plan["movimientos"], [{"clave": "NUEVO", "posicion": 0}])

    def test_cuenta_las_llamadas_con_el_tope_real_de_shopify(self):
        actuales = [f"P{i}" for i in range(600)]
        plan = motor.plan_de_coleccion({}, actuales, list(reversed(actuales)))
        self.assertEqual(plan["agregar"], [])
        # 599 movimientos -> 3 bloques de 250.
        self.assertEqual(len(motor.bloques(plan["movimientos"], 250)), 3)
        self.assertEqual(plan["llamadas"], 3)

    def test_sin_cambios_lo_dice(self):
        plan = motor.plan_de_coleccion({}, ["A", "B"], ["A", "B"])
        self.assertTrue(plan["sin_cambios"])


# =========================================================================
# 5. La capa GraphQL, EJECUTADA
# =========================================================================
class TestGraphQL(ConShopifyFalso):
    def test_crear_una_coleccion_manual(self):
        creada = shopify_api.collection_create(CONFIG, "Hiking", handle="hiking",
                                               sort_order="MANUAL")
        self.assertEqual(creada["handle"], "hiking")
        entrada = self.tienda.llamadas[-1][1]["entrada"]
        self.assertEqual(entrada["title"], "Hiking")
        self.assertEqual(entrada["sortOrder"], "MANUAL")
        self.assertNotIn("ruleSet", entrada, "una coleccion manual no lleva reglas")

    def test_usa_el_argumento_NUEVO_cuando_la_tienda_lo_acepta(self):
        shopify_api.collection_create(CONFIG, "Hiking")
        consulta = self.tienda.llamadas[-1][0]
        self.assertIn("CollectionCreateInput", consulta)
        self.assertIn("collection: $entrada", consulta)
        self.assertEqual(len(self.tienda.llamadas), 1, "no deberia hacer falta el respaldo")

    def test_cae_al_argumento_VIEJO_si_la_version_no_conoce_el_nuevo(self):
        self.tienda.soporta_argumento_nuevo = False
        creada = shopify_api.collection_create(CONFIG, "Hiking")
        self.assertEqual(creada["handle"], "coleccion")
        self.assertEqual(len(self.tienda.llamadas), 2)
        self.assertIn("CollectionInput", self.tienda.llamadas[-1][0])
        self.assertIn("input: $entrada", self.tienda.llamadas[-1][0])

    def test_un_error_que_NO_es_de_argumento_no_se_reintenta(self):
        """Reintentar taparia el motivo real y mandaria a mirar donde no es."""
        def rechaza(*args, **kwargs):
            raise shopify_api.ShopifyApiError("Access denied for collectionCreate field")
        shopify_api.graphql_request = rechaza
        with self.assertRaises(shopify_api.ShopifyApiError) as caja:
            shopify_api.collection_create(CONFIG, "Hiking")
        self.assertIn("Access denied", str(caja.exception))

    def test_la_regla_por_metacampo_manda_su_conditionObjectId(self):
        """Sin el, Shopify acepta la regla y la coleccion sale VACIA."""
        shopify_api.collection_create(CONFIG, "Columbia", reglas=[{
            "campo": "PRODUCT_METAFIELD_DEFINITION", "relacion": "EQUALS",
            "valor": "Columbia", "definicion_id": "gid://shopify/MetafieldDefinition/7"}])
        regla = self.tienda.llamadas[-1][1]["entrada"]["ruleSet"]["rules"][0]
        self.assertEqual(regla["conditionObjectId"], "gid://shopify/MetafieldDefinition/7")
        self.assertEqual(regla["column"], "PRODUCT_METAFIELD_DEFINITION")

    def test_update_NO_manda_lo_que_no_se_le_paso(self):
        """Mandar `descriptionHtml: ""` porque la pantalla no lo tocaba BORRARIA
        la descripcion. Es la misma regla de «vacio no borra»."""
        shopify_api.collection_update(CONFIG, "gid://shopify/Collection/1", sort_order="MANUAL")
        entrada = self.tienda.llamadas[-1][1]["entrada"]
        self.assertEqual(set(entrada), {"id", "sortOrder"})

    def test_agregar_600_productos_son_3_bloques_de_250(self):
        ids = [f"gid://shopify/Product/{i}" for i in range(600)]
        shopify_api.collection_add_products(CONFIG, "gid://shopify/Collection/1", ids)
        self.assertEqual([len(b) for b in self.tienda.agregados], [250, 250, 100])
        # Y no se pierde ninguno por el camino.
        self.assertEqual([i for bloque in self.tienda.agregados for i in bloque], ids)

    def test_cada_bloque_ESPERA_a_su_job_antes_del_siguiente(self):
        """Lanzar el bloque 2 sin esperar al 1 deja el orden a medias, y un
        orden a medias se ve normal y llega al comprador."""
        ids = [f"gid://shopify/Product/{i}" for i in range(300)]
        shopify_api.collection_add_products(CONFIG, "gid://shopify/Collection/1", ids)
        tipos = ["add" if "collectionAddProductsV2" in q else "job" if "job(id" in q else "?"
                 for q, _ in self.tienda.llamadas]
        self.assertEqual(tipos, ["add", "job", "add", "job"])

    def test_reordenar_manda_la_posicion_EN_TEXTO(self):
        """`newPosition` es `UnsignedInt64`: va en texto, no como numero."""
        shopify_api.collection_reorder_products(
            CONFIG, "gid://shopify/Collection/1",
            [{"id": "gid://shopify/Product/7", "newPosition": 3}])
        movimiento = self.tienda.movimientos[0][0]
        self.assertEqual(movimiento, {"id": "gid://shopify/Product/7", "newPosition": "3"})
        self.assertIsInstance(movimiento["newPosition"], str)

    def test_reordenar_parte_en_bloques_de_250(self):
        moves = [{"id": f"gid://shopify/Product/{i}", "newPosition": i} for i in range(300)]
        shopify_api.collection_reorder_products(CONFIG, "gid://shopify/Collection/1", moves)
        self.assertEqual([len(b) for b in self.tienda.movimientos], [250, 50])

    def test_una_lista_vacia_no_gasta_ni_un_viaje(self):
        self.assertEqual(shopify_api.collection_add_products(CONFIG, "gid://x", []), [])
        self.assertEqual(shopify_api.collection_reorder_products(CONFIG, "gid://x", []), [])
        self.assertEqual(self.tienda.llamadas, [])

    def test_un_userError_se_levanta_en_vez_de_pasar_por_exito(self):
        def con_error(shop_domain, token, query, variables=None, **kwargs):
            return {"collectionCreate": {"collection": None,
                                         "userErrors": [{"field": ["handle"],
                                                         "message": "Handle ya usado"}]}}
        shopify_api.graphql_request = con_error
        with self.assertRaises(shopify_api.ShopifyApiError) as caja:
            shopify_api.collection_create(CONFIG, "Hiking", handle="hiking")
        self.assertIn("Handle ya usado", str(caja.exception))

    def test_esperar_un_job_que_no_termina_devuelve_False_no_levanta(self):
        """El trabajo sigue del lado de Shopify: decir «no termino a tiempo» es
        cierto, decir «fallo» no lo seria."""
        shopify_api.graphql_request = lambda *a, **k: {"job": {"id": "gid://x", "done": False}}
        self.assertFalse(shopify_api.wait_job(CONFIG, "gid://x", attempts=2, delay_seconds=0))

    def test_publicar_la_coleccion_usa_publishablePublish(self):
        shopify_api.collection_publish(CONFIG, "gid://shopify/Collection/1",
                                       publication_id="gid://shopify/Publication/1")
        consulta = self.tienda.llamadas[-1][0]
        self.assertIn("publishablePublish", consulta)
        self.assertIn("on Collection", consulta)


# =========================================================================
# 6. El recorrido entero, de punta a punta
# =========================================================================
class TestDePuntaAPunta(ConShopifyFalso):
    def test_excel_validacion_plan_y_escritura(self):
        catalogo = [producto("A-1", titulo="Casaca", product_id="gid://shopify/Product/1"),
                    producto("B-2", titulo="Polo", product_id="gid://shopify/Product/2"),
                    producto("C-3", titulo="Short", product_id="gid://shopify/Product/3")]
        items, descartes = motor.filas_de_asignacion([
            {"Código Modelo Color": "C-3", "Orden": 1},
            {"Código Modelo Color": "A-1", "Orden": 2},
            {"Código Modelo Color": "B-2", "Orden": 3},
        ])
        self.assertEqual(descartes, [])
        informe = motor.validar_asignacion(items, motor.indice_de_catalogo(catalogo),
                                           ya_en_coleccion=["A-1"])
        self.assertFalse(informe["bloqueado"])

        pedidos = sorted(informe["listos"] + informe["ya_estaban"], key=lambda f: f["orden"])
        plan = motor.plan_de_coleccion({}, ["A-1"], [f["clave"] for f in pedidos])
        # `agregar` conserva el orden PEDIDO por el Excel (C-3 va primero), y
        # eso ahorra movimientos: agregados en ese orden, luego solo hay que
        # mover uno.
        self.assertEqual(plan["agregar"], ["C-3", "B-2"])

        gid = {p["Mod-Col"]: p["Product ID"] for p in catalogo}
        shopify_api.collection_add_products(CONFIG, "gid://shopify/Collection/1",
                                            [gid[c] for c in plan["agregar"]])
        shopify_api.collection_reorder_products(
            CONFIG, "gid://shopify/Collection/1",
            [{"id": gid[m["clave"]], "newPosition": m["posicion"]} for m in plan["movimientos"]])

        # Tras agregar la coleccion es [A-1, C-3, B-2]; el Excel la quiere
        # [C-3, A-1, B-2], que es UN solo movimiento.
        self.assertEqual(self.tienda.agregados, [["gid://shopify/Product/3",
                                                  "gid://shopify/Product/2"]])
        self.assertEqual(self.tienda.movimientos,
                         [[{"id": "gid://shopify/Product/3", "newPosition": "0"}]])

    def test_el_boost_de_punta_a_punta_llega_al_orden_que_se_vio_en_pantalla(self):
        """Lo que se aplica tiene que ser EXACTAMENTE lo que se previsualizo."""
        claves = ["A", "B", "C", "D"]
        contexto = {
            "productos": {c: producto(c, stock=stock) for c, stock in
                          zip(claves, (0, 50, 10, 99))},
            "rango_ventas": {"D": 0, "A": 1, "B": 2, "C": 3},
        }
        deseado = motor.ordenar(claves, [{"clave": "ventas"}], contexto)
        self.assertEqual(deseado, ["D", "A", "B", "C"])
        moves = motor.movimientos(claves, deseado)

        gid = {c: f"gid://shopify/Product/{c}" for c in claves}
        shopify_api.collection_reorder_products(
            CONFIG, "gid://shopify/Collection/1",
            [{"id": gid[m["clave"]], "newPosition": m["posicion"]} for m in moves])

        # Se aplica el resultado real sobre el orden real y tiene que dar el
        # orden previsualizado.
        final = list(claves)
        for bloque in self.tienda.movimientos:
            for movimiento in bloque:
                clave = movimiento["id"].rsplit("/", 1)[-1]
                final.remove(clave)
                final.insert(int(movimiento["newPosition"]), clave)
        self.assertEqual(final, deseado)


# =========================================================================
# 7. LA PANTALLA. Un motor perfecto al que no se le puede entregar el archivo
#    no sirve para nada (seccion 5 octotrigies).
# =========================================================================
from streamlit.testing.v1 import AppTest  # noqa: E402

APP = str(ROOT / "app_matrixify.py")
TIEMPO = 420

AVISOS_DE_CONFIGURACION = (
    "no tiene Shopify configurado", "no tiene Shopify API configurada",
    "falta la sección", "no hay credenciales", "BigQuery", "no esta configurado",
)


def abrir(**estado):
    at = AppTest.from_file(APP, default_timeout=TIEMPO)
    at.session_state["authenticated"] = True
    at.session_state["auth_user"] = "hugo"
    for clave, valor in estado.items():
        at.session_state[clave] = valor
    at.run()
    return at


def problemas(at):
    """`at.error` ademas de `at.exception`: `run_app()` convierte toda excepcion
    en `st.error`, asi que mirar solo `at.exception` diria «sin excepciones» con
    la pantalla rota. Es la regla 4 de CLAUDE.md."""
    fallos = [f"EXCEPCION {type(e.value).__name__}: {e.value}"[:400] for e in at.exception]
    fallos += [str(e.value)[:400] for e in at.error
               if not any(m.lower() in str(e.value).lower() for m in AVISOS_DE_CONFIGURACION)]
    return fallos


class TestLaPantalla(unittest.TestCase):
    def test_las_dos_secciones_se_dibujan(self):
        import app_matrixify as app
        for etiqueta in (app.COLECCIONES_LABEL, app.BOOST_LABEL):
            with self.subTest(seccion=etiqueta):
                at = abrir(operation_area_choice=etiqueta)
                self.assertEqual(problemas(at), [], f"la pantalla {etiqueta!r} no se dibuja")

    def test_las_dos_secciones_estan_en_el_menu(self):
        """Una pantalla a la que no se puede llegar no existe.

        Se le pregunta al MODELO del menu, no al texto del archivo: desde que
        el menu se dibuja recorriendo `nav_grupos()`, la clave del boton es una
        variable y el regex encontraba CERO -- o sea que esta prueba se habria
        quedado verde sin comprobar nada el dia que las dos pantallas salieran
        del menu.
        """
        import app_matrixify as app

        claves = {item["boton"] for grupo in app.nav_grupos(puede_auditar=True)
                  for item in grupo["items"]}
        self.assertIn("operation_nav_mantenedor", claves)
        self.assertIn("operation_nav_boost", claves)
        areas = app.nav_areas(puede_auditar=True)
        self.assertIn(app.COLECCIONES_LABEL, areas)
        self.assertIn(app.BOOST_LABEL, areas)

    def test_cada_boton_del_menu_esta_en_LAS_CINCO_listas_de_CSS(self):
        """Un boton nuevo hay que registrarlo en cinco listas de selectores y
        darle su dibujo. Nada en el codigo lo obliga: «Status de carga» salio en
        su dia sin icono y con otra tipografia."""
        import re
        fuente = (ROOT / "app_matrixify.py").read_text(encoding="utf-8")
        for clave in ("operation_nav_mantenedor", "operation_nav_boost"):
            with self.subTest(clave=clave):
                self.assertGreaterEqual(fuente.count(f"st-key-{clave} button"), 5)
                self.assertIn(f"st-key-{clave} button::before {{{{", fuente,
                              "le falta su dibujo de icono")

    def test_sin_shopify_lo_DICE_en_vez_de_dibujar_una_pantalla_inutil(self):
        import app_matrixify as app
        at = abrir(operation_area_choice=app.COLECCIONES_LABEL)
        textos = " ".join(str(e.value) for e in at.error)
        self.assertTrue(at.error, "sin Secrets la pantalla tiene que decir que falta")
        self.assertIn("Shopify", textos)

    def test_la_pantalla_no_escribe_NADA_en_shopify_al_dibujarse(self):
        """Regla 1: nada se escribe sin confirmar. Si el solo hecho de entrar
        llamara a una mutacion, la vista previa no serviria de nada."""
        import app_matrixify as app
        escrituras = []
        for nombre in ("collection_create", "collection_update", "collection_add_products",
                       "collection_remove_products", "collection_reorder_products",
                       "collection_publish"):
            original = getattr(app, nombre)

            def espia(*args, _n=nombre, **kwargs):
                escrituras.append(_n)
                return {}
            setattr(app, nombre, espia)
        try:
            for etiqueta in (app.COLECCIONES_LABEL, app.BOOST_LABEL):
                abrir(operation_area_choice=etiqueta)
        finally:
            pass
        self.assertEqual(escrituras, [], "dibujar la pantalla escribio en la tienda")


if __name__ == "__main__":
    unittest.main(verbosity=2)
