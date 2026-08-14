"""Pruebas de engines/catalog_map.py — configuracion central del catalogo.

Cada bloque fija uno de los fallos medidos en produccion:
  - `[id]` mandaba un tipo que Shopify no acepta -> Codigo Modelo-Color perdido
  - los tags adicionales reemplazaban a los genericos en vez de sumarse
  - habia dos build_handle y uno descartaba el nombre del producto
"""

import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from engines import catalog_map as mapa
from engines.catalog_map import (
    LISTA_TEXTO,
    TEXTO,
    build_handle,
    build_metafields,
    build_tags,
    campo_por_columna,
    campos_para_sitio,
    es_seudotipo,
    metafields_perdidos,
    namespace_key,
    separar_lista,
    slug,
    nombre_propio,
    tipo_shopify,
)


class TestArquitectura(unittest.TestCase):
    def test_no_importa_streamlit_ni_pandas(self):
        fuente = (ROOT / "engines" / "catalog_map.py").read_text(encoding="utf-8")
        self.assertNotIn("import streamlit", fuente)
        self.assertNotIn("import pandas", fuente)

    def test_no_hay_claves_repetidas(self):
        claves = [c[0] for c in mapa.CAMPOS]
        self.assertEqual(len(claves), len(set(claves)))

    def test_todo_campo_declara_un_tipo_valido(self):
        for campo in mapa.CAMPOS_POR_CLAVE.values():
            self.assertIn(campo.tipo, mapa.TIPOS_VALIDOS, campo.clave)


class TestTipoShopify(unittest.TestCase):
    """El fallo que dejaba productos sin Codigo Modelo-Color."""

    def test_id_no_es_un_tipo_de_shopify(self):
        columna = "Metafield: custom.codigo_modelo_color [id]"
        self.assertNotEqual(tipo_shopify(columna), "id")
        self.assertEqual(tipo_shopify(columna), TEXTO)

    def test_el_seudotipo_se_detecta(self):
        self.assertTrue(es_seudotipo("Metafield: custom.codigo_modelo_color [id]"))
        self.assertFalse(es_seudotipo("Metafield: custom.marca [single_line_text_field]"))

    def test_un_tipo_valido_se_respeta(self):
        self.assertEqual(tipo_shopify("Metafield: custom.marca [single_line_text_field]"), TEXTO)
        self.assertEqual(
            tipo_shopify("Metafield: custom.tecnologia [list.single_line_text_field]"), LISTA_TEXTO)

    def test_un_tipo_inventado_cae_a_texto(self):
        self.assertEqual(tipo_shopify("Metafield: custom.raro [no_existe]"), TEXTO)

    def test_sin_corchetes(self):
        self.assertEqual(tipo_shopify("Metafield: custom.algo"), TEXTO)

    def test_la_tabla_manda_sobre_los_corchetes(self):
        """Si la cabecera miente, gana la tabla central."""
        self.assertEqual(tipo_shopify("Metafield: custom.marca [id]"), TEXTO)

    def test_namespace_y_key(self):
        self.assertEqual(namespace_key("Metafield: custom.marca [single_line_text_field]"),
                         ("custom", "marca"))
        self.assertEqual(namespace_key("Vendor"), ("", ""))
        self.assertEqual(namespace_key("Metafield: sinpunto [text]"), ("", ""))


class TestNombrePropio(unittest.TestCase):
    """Categoria, Subcategoria, Tipo, Clase y Color: siempre Nombre Propio."""

    def test_mayusculas_y_minusculas_dan_lo_mismo(self):
        for entrada in ("VESTUARIO", "vestuario", "Vestuario", "vEsTuArIo"):
            self.assertEqual(nombre_propio(entrada), "Vestuario", entrada)

    def test_los_conectores_van_en_minuscula(self):
        self.assertEqual(nombre_propio("LENTES DE SOL"), "Lentes de Sol")
        self.assertEqual(nombre_propio("ropas de bano"), "Ropas de Bano")
        self.assertEqual(nombre_propio("ROPA PARA NINO"), "Ropa para Nino")

    def test_el_conector_al_principio_si_se_capitaliza(self):
        self.assertEqual(nombre_propio("de vestir"), "De Vestir")

    def test_las_tildes_y_la_enye_se_conservan(self):
        self.assertEqual(nombre_propio("NIÑO"), "Niño")
        self.assertEqual(nombre_propio("ropas de baño"), "Ropas de Baño")

    def test_el_guion_separa_palabras(self):
        self.assertEqual(nombre_propio("polo manga-corta"), "Polo Manga-Corta")

    def test_los_codigos_no_se_tocan(self):
        for codigo in ("HP2020-SMV", "IM5678-011", "22397-ORH"):
            self.assertEqual(nombre_propio(codigo), codigo, codigo)

    def test_espacios_sobrantes(self):
        self.assertEqual(nombre_propio("  VESTUARIO   CASUAL  "), "Vestuario Casual")

    def test_vacio(self):
        self.assertEqual(nombre_propio(""), "")
        self.assertEqual(nombre_propio(None), "")

    def test_los_metafields_salen_normalizados(self):
        fila = {"Mod-Col": "im5678-011", "Categoria": "VESTUARIO",
                "Subcategoria": "chalecos", "Genero": "HOMBRE", "Color Web": "azul marino"}
        v = {f'{m["namespace"]}.{m["key"]}': m["value"] for m in build_metafields(fila, "rockford")}
        self.assertEqual(v["custom.categoria"], "Vestuario")
        self.assertEqual(v["custom.sub_categoria"], "Chalecos")
        self.assertEqual(v["custom.tipo"], "Chalecos")
        self.assertEqual(v["custom.genero"], "Hombre")
        self.assertEqual(v["custom.color_forus"], "Azul Marino")
        self.assertEqual(v["custom.codigo_modelo_color"], "IM5678-011")

    def test_los_tags_tambien(self):
        tags = build_tags({"Genero": "HOMBRE", "Categoria": "vestuario",
                           "Tipo": "CHALECOS"}, "rockford")
        for esperado in ("Hombre", "Vestuario", "Chalecos"):
            self.assertIn(esperado, tags, esperado)


class TestSiblings(unittest.TestCase):
    """El mismo metafield estaba declarado con tipos distintos segun la ruta."""

    def test_custom_siblings_es_referencia_de_producto(self):
        """El mantenedor y la API ya usaban este tipo; otras 4 rutas, no."""
        for columna in ("Metafield: custom.siblings [single_line_text_field]",
                        "Metafield: custom.siblings [list.product_reference]",
                        "Metafield: custom.siblings [id]"):
            self.assertEqual(tipo_shopify(columna), "list.product_reference", columna)

    def test_theme_siblings_es_lista_de_texto(self):
        for columna in ("Metafield: theme.siblings [single_line_text_field]",
                        "Metafield: theme.siblings [list.single_line_text_field]"):
            self.assertEqual(tipo_shopify(columna), LISTA_TEXTO, columna)

    def test_los_color_son_texto_simple(self):
        for columna in ("Metafield: custom.siblings_color [single_line_text_field]",
                        "Metafield: theme.siblings_color [single_line_text_field]"):
            self.assertEqual(tipo_shopify(columna), TEXTO, columna)

    def test_no_se_confunden_custom_y_theme(self):
        self.assertNotEqual(tipo_shopify("Metafield: custom.siblings [x]"),
                            tipo_shopify("Metafield: theme.siblings [x]"))

    def test_mismos_criterios_en_todos_los_sitios(self):
        """El usuario lo confirmo: no hay variacion por sitio."""
        for clave in ("siblings", "siblings_color", "siblings_tema", "siblings_color_tema"):
            self.assertIsNone(mapa.CAMPOS_POR_CLAVE[clave].sitios, clave)
        for sitio in ("columbia", "vans", "rockford", "hush_puppies", "patagonia"):
            claves = {c.clave for c in campos_para_sitio(sitio)}
            self.assertIn("siblings", claves, sitio)
            self.assertIn("siblings_tema", claves, sitio)

    def test_los_cuatro_salen_juntos(self):
        fila = {"Mod-Col": "A-1", "Siblings": "handle-uno|handle-dos",
                "Siblings Color": "Negro"}
        rutas = {f'{m["namespace"]}.{m["key"]}': m for m in build_metafields(fila, "rockford")}
        self.assertEqual(rutas["custom.siblings"]["type"], "list.product_reference")
        self.assertEqual(rutas["theme.siblings"]["type"], LISTA_TEXTO)
        self.assertEqual(json.loads(rutas["theme.siblings"]["value"]),
                         ["handle-uno", "handle-dos"])
        self.assertEqual(rutas["custom.siblings_color"]["value"], "Negro")
        self.assertEqual(rutas["theme.siblings_color"]["value"], "Negro")


class TestCamposPorSitio(unittest.TestCase):
    def test_los_comunes_aplican_a_todos(self):
        for sitio in ("columbia", "vans", "rockford", "hush_puppies"):
            claves = {c.clave for c in campos_para_sitio(sitio)}
            self.assertIn("codigo_modelo_color", claves, sitio)
            self.assertIn("categoria", claves, sitio)
            self.assertIn("genero", claves, sitio)

    def test_familia_es_solo_de_vans(self):
        self.assertIn("familia", {c.clave for c in campos_para_sitio("vans")})
        self.assertNotIn("familia", {c.clave for c in campos_para_sitio("columbia")})

    def test_estilo_es_solo_de_hush(self):
        self.assertIn("estilo", {c.clave for c in campos_para_sitio("hush_puppies")})
        self.assertNotIn("estilo", {c.clave for c in campos_para_sitio("rockford")})

    def test_tecnologia_es_el_mismo_tipo_en_todos_los_sitios(self):
        """Un metafield, un tipo. Dos entradas para la misma clave hacian que
        tipo_shopify() devolviera la primera sin mirar el sitio."""
        for sitio in ("columbia", "rockford", "vans", "hush_puppies"):
            campos = {c.clave: c for c in campos_para_sitio(sitio)}
            self.assertIn("tecnologia", campos, sitio)
            self.assertEqual(campos["tecnologia"].tipo, LISTA_TEXTO, sitio)
        self.assertNotIn("tecnologia_texto", mapa.CAMPOS_POR_CLAVE)

    def test_ninguna_clave_de_metafield_esta_repetida(self):
        """Dos campos con el mismo namespace.key hacen ambiguo el tipo."""
        rutas = [f"{c.namespace}.{c.key}" for c in mapa.CAMPOS_POR_CLAVE.values()]
        self.assertEqual(len(rutas), len(set(rutas)), "hay namespace.key duplicados")

    def test_campo_por_columna(self):
        campo = campo_por_columna("Metafield: custom.familia [single_line_text_field]")
        self.assertIsNotNone(campo)
        self.assertEqual(campo.clave, "familia")

    def test_columna_generada(self):
        campo = mapa.CAMPOS_POR_CLAVE["codigo_modelo_color"]
        self.assertEqual(campo.columna,
                         "Metafield: custom.codigo_modelo_color [single_line_text_field]")


class TestHushPuppies(unittest.TestCase):
    """Todos los campos que declara la plantilla de Hush tienen que salir."""

    PLANTILLA = {
        "custom.categoria", "custom.codigo_modelo_color", "custom.color_forus",
        "custom.descripcion_corta", "custom.genero", "custom.grupo_color",
        "custom.guia_de_tallas", "custom.marca", "custom.materialidad",
        "custom.nombre_corto", "custom.pais_de_fabricacion", "custom.siblings_color",
        "custom.sub_categoria", "custom.tecnologia", "custom.tipo",
    }

    def test_no_falta_ninguno(self):
        tengo = {f"{c.namespace}.{c.key}" for c in campos_para_sitio("hush_puppies")}
        self.assertEqual(self.PLANTILLA - tengo, set())

    def test_la_clave_lleva_guion_bajo(self):
        """En Shopify es custom.sub_categoria. Sin el guion es OTRO metafield."""
        self.assertEqual(mapa.CAMPOS_POR_CLAVE["subcategoria"].key, "sub_categoria")

    def test_pais_y_guia_aplican_a_todos_los_sitios(self):
        for sitio in ("columbia", "vans", "rockford", "hush_puppies"):
            claves = {c.clave for c in campos_para_sitio(sitio)}
            self.assertIn("pais_de_fabricacion", claves, sitio)
            self.assertIn("guia_de_tallas", claves, sitio)

    def test_la_guia_de_tallas_la_escribe_matrixify(self):
        campo = mapa.CAMPOS_POR_CLAVE["guia_de_tallas"]
        self.assertEqual(campo.tipo, mapa.REFERENCIA_PAGINA)
        self.assertFalse(campo.escribible_por_api())

    def test_una_ficha_completa_de_hush_sale_entera(self):
        fila = {"Mod-Col": "HP2020-SMV", "Marca": "Hush Puppies", "Categoria": "Calzado",
                "Subcategoria": "Mocasines", "Genero": "Mujer", "Color Web": "Azul",
                "Material": "Cuero", "Pais de Fabricacion": "Brasil", "Estilo": "Casual"}
        rutas = {f'{m["namespace"]}.{m["key"]}' for m in build_metafields(fila, "hush_puppies")}
        for esperado in ("custom.codigo_modelo_color", "custom.sub_categoria",
                         "custom.pais_de_fabricacion", "custom.estilo", "custom.tipo"):
            self.assertIn(esperado, rutas, esperado)
        self.assertEqual(metafields_perdidos(fila, "hush_puppies",
                                             build_metafields(fila, "hush_puppies")), [])


class TestBuildMetafields(unittest.TestCase):
    FILA = {
        "Mod-Col": "im5678-011",
        "Marca": "Columbia",
        "Categoria": "Vestuario",
        "Género": "Hombre",
        "Tecnología": "Omni-Heat | Omni-Shield",
        "Familia": "Classics",
    }

    def test_el_codigo_modelo_color_siempre_sale(self):
        for sitio in ("columbia", "vans", "rockford", "hush_puppies", "patagonia"):
            claves = {m["clave"]: m for m in build_metafields(self.FILA, sitio)}
            self.assertIn("codigo_modelo_color", claves, sitio)
            self.assertEqual(claves["codigo_modelo_color"]["value"], "IM5678-011", sitio)
            self.assertEqual(claves["codigo_modelo_color"]["type"], TEXTO, sitio)

    def test_lee_alias_con_y_sin_tilde(self):
        claves = {m["clave"] for m in build_metafields({"Genero": "Mujer"}, "vans")}
        self.assertIn("genero", claves)

    def test_no_rellena_lo_que_no_aplica(self):
        """Familia no debe aparecer en Columbia aunque el Excel la traiga."""
        claves = {m["clave"] for m in build_metafields(self.FILA, "columbia")}
        self.assertNotIn("familia", claves)
        self.assertIn("familia", {m["clave"] for m in build_metafields(self.FILA, "vans")})

    def test_tecnologia_como_lista_json_en_columbia(self):
        claves = {m["clave"]: m for m in build_metafields(self.FILA, "columbia")}
        self.assertEqual(json.loads(claves["tecnologia"]["value"]),
                         ["Omni-Heat", "Omni-Shield"])

    def test_tecnologia_como_lista_en_rockford(self):
        claves = {m["clave"]: m for m in build_metafields(self.FILA, "rockford")}
        self.assertEqual(json.loads(claves["tecnologia"]["value"]),
                         ["Omni-Heat", "Omni-Shield"])

    def test_los_vacios_no_se_envian(self):
        claves = {m["clave"] for m in build_metafields({"Mod-Col": "A-1", "Marca": ""}, "vans")}
        self.assertNotIn("marca", claves)

    def test_entrada_vacia(self):
        self.assertEqual(build_metafields({}, "vans"), [])
        self.assertEqual(build_metafields(None, "vans"), [])


class TestMetafieldsPerdidos(unittest.TestCase):
    """La validacion previa que pedia el usuario."""

    def test_detecta_lo_que_desaparece(self):
        fila = {"Mod-Col": "A-1", "Marca": "Vans", "Familia": "Classics"}
        payload = [{"namespace": "custom", "key": "codigo_modelo_color", "value": "A-1"}]
        perdidos = {p["campo"] for p in metafields_perdidos(fila, "vans", payload)}
        self.assertIn("familia", perdidos)
        self.assertIn("marca", perdidos)
        self.assertNotIn("codigo_modelo_color", perdidos)

    def test_sin_perdidas_devuelve_vacio(self):
        fila = {"Mod-Col": "A-1"}
        payload = build_metafields(fila, "vans")
        self.assertEqual(metafields_perdidos(fila, "vans", payload), [])

    def test_un_campo_sin_dato_no_se_reporta(self):
        self.assertEqual(metafields_perdidos({"Marca": ""}, "vans", []), [])

    def test_acepta_un_diccionario_como_payload(self):
        fila = {"Mod-Col": "A-1", "Marca": "Vans"}
        perdidos = metafields_perdidos(fila, "vans", {"custom.codigo_modelo_color": "A-1"})
        self.assertEqual({p["campo"] for p in perdidos}, {"marca"})

    def test_explica_el_motivo(self):
        perdidos = metafields_perdidos({"Marca": "Vans"}, "vans", [])
        self.assertIn("input", perdidos[0]["motivo"])


class TestTags(unittest.TestCase):
    """Los adicionales SUMAN; nunca reemplazan."""

    def test_los_adicionales_no_borran_los_de_tags(self):
        fila = {"Tags": "Hombre, Vestuario", "Tags adicionales": "Chalecos, Sweaters"}
        tags = build_tags(fila)
        for esperado in ("Hombre", "Vestuario", "Chalecos", "Sweaters"):
            self.assertIn(esperado, tags, esperado)

    def test_genera_los_genericos_sin_columna_tags(self):
        """Rockford creaba productos pelados porque no habia genericos."""
        fila = {"Genero": "Hombre", "Categoria": "Vestuario", "Tipo": "Chalecos",
                "Mod-Col": "IM5678-011", "Marca": "Rockford"}
        tags = build_tags(fila, "rockford")
        for esperado in ("Hombre", "Vestuario", "Chalecos", "IM5678-011", "Rockford"):
            self.assertIn(esperado, tags, esperado)

    def test_sin_repetidos_ni_por_tildes(self):
        fila = {"Genero": "Hombre", "Tags": "hombre, HOMBRE", "Tags adicionales": "Hómbre"}
        self.assertEqual(len([t for t in build_tags(fila) if t.casefold().startswith("h")]), 1)

    def test_reglas_del_sitio_se_suman(self):
        tags = build_tags({"Tags": "Base"}, "vans", reglas_sitio=["Skate", "Classics"])
        self.assertIn("Skate", tags)
        self.assertIn("Base", tags)

    def test_orden_generico_base_sitio_adicional(self):
        fila = {"Genero": "Hombre", "Tags": "Base", "Tags adicionales": "Extra"}
        tags = build_tags(fila, reglas_sitio=["Sitio"])
        self.assertLess(tags.index("Hombre"), tags.index("Base"))
        self.assertLess(tags.index("Base"), tags.index("Extra"))

    def test_separadores(self):
        self.assertEqual(len(build_tags({"Tags": "a, b; c | d"})), 4)

    def test_vacio(self):
        self.assertEqual(build_tags({}), [])
        self.assertEqual(build_tags(None), [])


class TestHandle(unittest.TestCase):
    def test_el_nombre_no_se_pierde(self):
        """El fallo: el Mod-Col reemplazaba al nombre del producto."""
        handle = build_handle("Chaleco Powder Lite", "Hombre", "IM5678-011", "Negro")
        self.assertTrue(handle.startswith("chaleco-powder-lite"))
        self.assertIn("im5678-011", handle)

    def test_estructura_completa(self):
        self.assertEqual(build_handle("Chaleco Powder Lite", "Hombre", "IM5678-011", "Negro"),
                         "chaleco-powder-lite-hombre-im5678-011-negro")

    def test_sin_tildes_ni_enye(self):
        self.assertEqual(build_handle("Camisa Niño Añil", "", "A-1", ""), "camisa-nino-anil-a-1")

    def test_sin_caracteres_especiales(self):
        self.assertEqual(build_handle("Polo 100% Algodón (New)", "", "A-1", ""),
                         "polo-100-algodon-new-a-1")

    def test_sin_dobles_guiones_ni_sobrantes(self):
        handle = build_handle("  Chaleco   --  Lite  ", "", "A-1", "")
        self.assertNotIn("--", handle)
        self.assertFalse(handle.startswith("-") or handle.endswith("-"))

    def test_no_repite_partes(self):
        self.assertEqual(build_handle("Negro", "", "A-1", "Negro"), "negro-a-1")

    def test_sin_nombre_queda_el_modcol(self):
        self.assertEqual(build_handle("", "", "IM5678-011", ""), "im5678-011")

    def test_todo_vacio(self):
        self.assertEqual(build_handle("", "", "", ""), "")

    def test_slug(self):
        self.assertEqual(slug("Añil & Café"), "anil-y-cafe")


class TestSepararLista(unittest.TestCase):
    def test_corta_por_pipe(self):
        self.assertEqual(separar_lista("Omni-Heat | Omni-Shield"), ["Omni-Heat", "Omni-Shield"])

    def test_el_pipe_decimal_no_corta(self):
        """5|3-oz son 5.3 oz, no dos materiales."""
        self.assertEqual(separar_lista("5|3-oz"), ["5|3-oz"])

    def test_mezcla(self):
        self.assertEqual(separar_lista("Nylon 5|3-oz | Poliester"), ["Nylon 5|3-oz", "Poliester"])

    def test_vacio(self):
        self.assertEqual(separar_lista(""), [])
        self.assertEqual(separar_lista(None), [])


if __name__ == "__main__":
    unittest.main(verbosity=2)
