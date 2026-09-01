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


class TestSinStreamlit(unittest.TestCase):
    def test_el_motor_no_importa_streamlit(self):
        fuente = (ROOT / "engines" / "load_status.py").read_text(encoding="utf-8")
        self.assertNotIn("import streamlit", fuente)


if __name__ == "__main__":
    unittest.main(verbosity=2)
