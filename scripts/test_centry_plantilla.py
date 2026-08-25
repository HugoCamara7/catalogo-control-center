# -*- coding: utf-8 -*-
"""Pruebas del Centry contra la plantilla: valores, materiales y validacion.

Tres causas raiz, todas con el mismo sintoma -una pantalla llena de hallazgos
y campos vacios en el archivo-:

1. **El motor escribia valores que la plantilla no acepta.** Las columnas de
   marketplace se rellenaban con el valor crudo del catalogo: el tipo de prenda
   tal cual ("Zapatillas", cuando el diccionario dice "Zapatillas urbanas") y el
   genero tal cual ("Niños"/"Unisex", cuando dice "Niño"/"Unisex adulto").
   Centry rechaza esos valores, y la validacion los contaba uno por uno: 850
   hallazgos bloqueantes que eran UN problema escrito 850 veces.

2. **Encontraba los materiales y los pisaba con vacio.** Los pares del Body
   ("Forro: 100% Poliester") se volcaban en la fila y, tres lineas mas abajo,
   `centry_apply_apparel_fields` los sobrescribia con `material`, que venia
   vacio porque `centry_seccion_como_valor` rechaza el texto con etiquetas.
   De ahi el "atributos no aplicados: Forro: ..." con la columna en blanco.

3. **"Forro" y "Material exterior" no tenian destino** fuera del calzado, asi
   que en vestuario y accesorios el dato se descartaba.

Ejecutar:  python scripts/test_centry_plantilla.py
"""
import sys
import types
import unittest
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def _identity_decorator(*args, **kwargs):
    if args and callable(args[0]):
        return args[0]

    def _decorator(func):
        return func

    return _decorator


class _Secrets(dict):
    def get(self, key, default=None):
        return super().get(key, default if default is not None else {})


class _StreamlitStub(types.ModuleType):
    session_state = {}
    secrets = _Secrets()
    cache_data = staticmethod(_identity_decorator)
    cache_resource = staticmethod(_identity_decorator)

    def __getattr__(self, name):
        def _noop(*args, **kwargs):
            return None

        return _noop


if "streamlit" not in sys.modules:
    stub = _StreamlitStub("streamlit")
    comp = types.ModuleType("streamlit.components")
    comp_v1 = types.ModuleType("streamlit.components.v1")
    stub.__path__ = []
    comp.__path__ = []
    comp.v1 = comp_v1
    stub.components = comp
    sys.modules["streamlit"] = stub
    sys.modules["streamlit.components"] = comp
    sys.modules["streamlit.components.v1"] = comp_v1

import app_matrixify as app  # noqa: E402
import generate_columbia_matrixify as g  # noqa: E402
from engines import centry_map as cm  # noqa: E402

BODY = (
    '<div class="nweb__Descripcion"><p>Casaca ligera para lluvia.</p></div>'
    '<div class="nweb__Caracteristicas"><ul><li>Capucha ajustable</li></ul></div>'
    '<div class="nweb__Materiales"><ul>'
    '<li>Material exterior: 100% Nylon</li><li>Forro: 100% Poliester</li>'
    '<li>Composición: 100% Poliamida</li></ul></div>'
    '<div class="nweb__Cuidados"><ul><li>Lavar a mano</li></ul></div>'
)

COL_GENERO_ROPA = "Género de vestuario - Ropa y accesorios (Falabella GSC Perú)"
COL_GENERO_CALZADO = "Género - Calzado (Falabella GSC Perú)"
COL_MATERIAL_ROPA = "Material de vestuario - Ropa y accesorios (Falabella GSC Perú)"
COL_COMPOSICION = "Composición - Ropa y accesorios (Falabella GSC Perú)"


def fila(**valores):
    base = {columna: "" for columna in app.MATRIXIFY_COLUMNS}
    base.update(valores)
    return base


def centry_de(sitio, marca, cod, tipo, genero, tallas, body=BODY):
    """Genera el Centry de un producto, con su maestro completo."""
    cfg = g.get_brand_config(sitio)
    mx, arti = [], []
    for indice, talla in enumerate(tallas):
        sku = str(7000000 + indice)
        mx.append(fila(**{
            "Handle": cod.lower(),
            "Title": f"{tipo} {marca}" if indice == 0 else "",
            "Body HTML": body if indice == 0 else "",
            "Vendor": marca if indice == 0 else "",
            "Type": tipo if indice == 0 else "",
            "Image Src": "https://cdn/f.jpg" if indice == 0 else "",
            "Variant SKU": sku,
            "Option1 Value": talla,
            "Variant Price": "199",
            "Metafield: custom.codigo_modelo_color [id]": cod if indice == 0 else "",
            "Metafield: custom.genero [single_line_text_field]": genero if indice == 0 else "",
        }))
        arti.append({
            "CODINT_MA": sku, "COD MOD COL": cod, "TALNUM_MA": talla,
            "MARCA_MA": marca.upper(), "CodBarras": f"77987{sku}",
            "ColorNombre": "Negro", "Precio": "199", "Genero": genero,
            "TipoProducto": tipo,
        })
    return app.build_centry_from_matrixify(pd.DataFrame(mx), cfg, arti_df=pd.DataFrame(arti))


class TestGeneroDeMarketplace(unittest.TestCase):
    """Los OCHO valores que acepta la plantilla, ni uno mas."""

    def test_traduce_los_generos_del_catalogo(self):
        self.assertEqual(app.centry_gender_marketplace("Masculino"), "Hombre")
        self.assertEqual(app.centry_gender_marketplace("Femenino"), "Mujer")
        self.assertEqual(app.centry_gender_marketplace("Niños"), "Niño")
        self.assertEqual(app.centry_gender_marketplace("Unisex"), "Unisex adulto")

    def test_un_unisex_infantil_no_es_un_unisex_adulto(self):
        self.assertEqual(app.centry_gender_marketplace("Unisex", "Niños"), "Unisex niño")

    def test_todo_lo_que_devuelve_esta_en_la_plantilla(self):
        permitidos = set(cm.valores_permitidos(COL_GENERO_ROPA))
        for entrada in ["Masculino", "Femenino", "Niños", "Niñas", "Unisex", "Bebe niño"]:
            valor = app.centry_gender_marketplace(entrada)
            with self.subTest(entrada=entrada):
                self.assertTrue(not valor or valor in permitidos, f"{entrada} -> {valor}")

    def test_lo_que_no_tiene_equivalencia_queda_vacio(self):
        """Mejor un campo sin llenar que un valor que Centry va a rechazar."""
        self.assertEqual(app.centry_gender_marketplace("Algo raro"), "")
        self.assertEqual(app.centry_gender_marketplace(""), "")


class TestPuertaDeLaPlantilla(unittest.TestCase):
    """Nada sale del motor si la plantilla no lo acepta."""

    def test_vacia_el_valor_que_no_esta_en_el_diccionario(self):
        fila_centry = {COL_GENERO_ROPA: "Niños"}
        descartes = app.centry_depurar_valores_de_plantilla(fila_centry)
        self.assertEqual(fila_centry[COL_GENERO_ROPA], "")
        self.assertEqual(len(descartes), 1)
        self.assertEqual(descartes[0][0], COL_GENERO_ROPA)

    def test_deja_el_valor_bueno_con_la_ortografia_de_la_plantilla(self):
        fila_centry = {COL_GENERO_ROPA: "niño"}
        app.centry_depurar_valores_de_plantilla(fila_centry)
        self.assertEqual(fila_centry[COL_GENERO_ROPA], "Niño")

    def test_no_toca_las_columnas_de_texto_libre(self):
        fila_centry = {COL_MATERIAL_ROPA: "100% Nylon reciclado"}
        descartes = app.centry_depurar_valores_de_plantilla(fila_centry)
        self.assertEqual(fila_centry[COL_MATERIAL_ROPA], "100% Nylon reciclado")
        self.assertEqual(descartes, [])

    def test_una_columna_vacia_no_es_un_descarte(self):
        fila_centry = {COL_GENERO_ROPA: ""}
        self.assertEqual(app.centry_depurar_valores_de_plantilla(fila_centry), [])


class TestMaterialesPorFamilia(unittest.TestCase):
    """Lo que se encuentra se coloca, en la columna que toque."""

    TEXTO = "Material exterior: 100% Nylon|Forro: 100% Poliester|Composición: 100% Poliamida"

    def test_vestuario_coloca_los_tres(self):
        aplicados, ignorados = cm.atributos_desde_caracteristicas(self.TEXTO, "superior")
        self.assertEqual(ignorados, [])
        self.assertEqual(aplicados[COL_MATERIAL_ROPA], "100% Nylon")
        self.assertEqual(aplicados[COL_COMPOSICION], "100% Poliamida")

    def test_calzado_usa_su_columna_de_forro(self):
        aplicados, ignorados = cm.atributos_desde_caracteristicas(self.TEXTO, "calzado")
        self.assertEqual(ignorados, [])
        self.assertEqual(
            aplicados["Material del forro - Calzado (Falabella GSC Perú)"], "100% Poliester"
        )
        self.assertEqual(
            aplicados["Material principal - Calzado (Falabella GSC Perú)"], "100% Nylon"
        )

    def test_accesorios_tambien_los_aprovecha(self):
        aplicados, ignorados = cm.atributos_desde_caracteristicas(self.TEXTO, "accesorios")
        self.assertEqual(ignorados, [])
        self.assertEqual(
            aplicados["Material del accesorio - Ropa y accesorios (Falabella GSC Perú)"],
            "100% Nylon",
        )

    def test_la_composicion_le_gana_al_forro_en_su_columna(self):
        """El forro usa la columna de composicion solo como respaldo."""
        aplicados, _ = cm.atributos_desde_caracteristicas(self.TEXTO, "superior")
        self.assertEqual(aplicados[COL_COMPOSICION], "100% Poliamida")

    def test_el_forro_solo_ocupa_la_composicion_si_esta_libre(self):
        aplicados, ignorados = cm.atributos_desde_caracteristicas(
            "Forro: 100% Poliester", "superior"
        )
        self.assertEqual(ignorados, [])
        self.assertEqual(aplicados[COL_COMPOSICION], "100% Poliester")


class TestNoSePisaLoEncontrado(unittest.TestCase):
    def test_no_sobrescribe_una_columna_con_valor(self):
        fila_centry = {COL_MATERIAL_ROPA: "100% Nylon"}
        app.centry_poner_si_vacio(fila_centry, COL_MATERIAL_ROPA, "Otros")
        self.assertEqual(fila_centry[COL_MATERIAL_ROPA], "100% Nylon")

    def test_rellena_la_que_esta_vacia(self):
        fila_centry = {COL_MATERIAL_ROPA: ""}
        app.centry_poner_si_vacio(fila_centry, COL_MATERIAL_ROPA, "Otros")
        self.assertEqual(fila_centry[COL_MATERIAL_ROPA], "Otros")

    def test_un_valor_vacio_no_borra_nada(self):
        fila_centry = {COL_MATERIAL_ROPA: "100% Nylon"}
        app.centry_poner_si_vacio(fila_centry, COL_MATERIAL_ROPA, "")
        self.assertEqual(fila_centry[COL_MATERIAL_ROPA], "100% Nylon")


class TestVariasMarcas(unittest.TestCase):
    """El mismo producto, en las cuatro familias y cinco marcas."""

    CASOS = [
        ("columbia", "Columbia", "2115991-8CL", "Cortavientos", "Niños", ["XS", "S", "M"]),
        ("columbia", "Columbia", "2070961-97G", "Gorros", "Unisex", ["O/S"]),
        ("columbia", "Columbia", "2136841-2OO", "Polares", "Masculino", ["S", "M"]),
        ("rockford", "Rockford", "RK110021743-5ZV", "Zapatos", "Masculino", ["38", "39"]),
        ("hush_puppies", "Hush Puppies", "HP2020112-SKO", "Zapatillas", "Femenino", ["36", "37"]),
        ("vans", "Vans", "VN0A5JMH-BLK", "Zapatillas", "Unisex", ["38", "39"]),
    ]

    def test_ninguna_marca_deja_hallazgos_bloqueantes(self):
        """Regresion: Columbia daba 850 hallazgos bloqueantes."""
        for caso in self.CASOS:
            with self.subTest(marca=caso[1], cod=caso[2]):
                centry, _ = centry_de(*caso)
                validacion = centry.attrs.get("validacion")
                if validacion is None or validacion.empty:
                    continue
                bloqueantes = validacion[validacion["Severidad"] == "Bloqueante"]
                self.assertEqual(len(bloqueantes), 0, list(bloqueantes["Campo"]))

    def test_el_sku_de_la_variante_nunca_es_el_ean(self):
        for caso in self.CASOS:
            with self.subTest(marca=caso[1]):
                centry, _ = centry_de(*caso)
                for _, f in centry.iterrows():
                    sku = str(f.get("SKU de la variante"))
                    ean = str(f.get("Código de barra variante (EAN/UPC/ISBN)"))
                    self.assertTrue(sku)
                    self.assertNotEqual(sku, ean)

    def test_cada_variante_sale_con_su_ean(self):
        for caso in self.CASOS:
            with self.subTest(marca=caso[1]):
                centry, _ = centry_de(*caso)
                vacios = [f for _, f in centry.iterrows()
                          if not str(f.get("Código de barra variante (EAN/UPC/ISBN)")).strip()]
                self.assertEqual(vacios, [])

    def test_los_materiales_llegan_al_listado(self):
        for caso in self.CASOS:
            with self.subTest(marca=caso[1]):
                centry, _ = centry_de(*caso)
                listado = str(centry.iloc[0].get("Listado de características"))
                self.assertIn("Material", listado)
                self.assertIn("Composición", listado)

    def test_el_genero_sale_en_la_columna_de_su_familia(self):
        centry, _ = centry_de(*self.CASOS[2])   # Polares Masculino -> vestuario
        self.assertEqual(centry.iloc[0].get(COL_GENERO_ROPA), "Hombre")
        centry, _ = centry_de(*self.CASOS[3])   # Zapatos Masculino -> calzado
        self.assertEqual(centry.iloc[0].get(COL_GENERO_CALZADO), "Hombre")

    def test_ningun_valor_del_archivo_queda_fuera_de_la_plantilla(self):
        restringidas = app.centry_columnas_con_diccionario()
        for caso in self.CASOS:
            with self.subTest(marca=caso[1]):
                centry, _ = centry_de(*caso)
                for _, f in centry.iterrows():
                    for columna in restringidas:
                        valor = str(f.get(columna, "")).strip()
                        if not valor:
                            continue
                        _, ok = cm.valor_valido(columna, valor)
                        self.assertTrue(ok, f"{columna} = {valor}")


class TestRedireccionDeTipos(unittest.TestCase):
    """Nuestros tipos, redirigidos al nombre que usa la plantilla Centry.

    No son tipos nuevos: son los mismos, con el nombre que espera cada canal.
    Casi todo son diferencias de escritura o de numero ("Suecos"/"Zuecos",
    "Cortavientos"/"Cortaviento") y unos pocos el sinonimo del marketplace
    ("Casacas" -> "Chaquetas").

    Antes, esas columnas salian VACIAS: el catalogo escribia "Zapatillas", la
    plantilla pedia "Zapatillas urbanas" y la puerta de plantilla lo borraba.
    """

    CALZADO = "Tipo - Calzado (Falabella GSC Perú)"
    CALZADO_ML = "Tipo de calzado (MercadoLibre Perú)"
    CHAQUETA = "Tipo de chaqueta/chaleco - Ropa y accesorios (Falabella GSC Perú)"

    def test_el_calzado_generico_encuentra_su_valor(self):
        for tipo, esperado in [("Zapatillas", "Zapatillas urbanas"),
                               ("Zapatos", "Zapatos casuales"),
                               ("Slip Ons", "Zapatillas urbanas"),
                               ("Suecos", "Zuecos")]:
            with self.subTest(tipo=tipo):
                aplicados, _ = cm.tipo_para_columnas(tipo, "calzado")
                self.assertEqual(aplicados.get(self.CALZADO), esperado)

    def test_tambien_para_mercadolibre(self):
        aplicados, _ = cm.tipo_para_columnas("Zapatos", "calzado")
        self.assertEqual(aplicados.get(self.CALZADO_ML), "Zapatos casuales")

    def test_el_vestuario_redirige_a_su_sinonimo(self):
        for tipo, esperado in [("Casacas", "Chaquetas"),
                               ("Cortavientos", "Cortaviento"),
                               ("Polares", "Polar")]:
            with self.subTest(tipo=tipo):
                aplicados, _ = cm.tipo_para_columnas(tipo, "superior")
                self.assertEqual(aplicados.get(self.CHAQUETA), esperado)

    def test_lo_que_ya_coincidia_no_cambia(self):
        aplicados, _ = cm.tipo_para_columnas("Botines", "calzado")
        self.assertEqual(aplicados.get(self.CALZADO), "Botines")

    def test_la_equivalencia_nunca_cuela_un_valor_invalido(self):
        """El diccionario de la columna sigue mandando: si el destino no esta
        permitido ahi, no se escribe nada."""
        for tipo in ["Zapatillas", "Zapatos", "Casacas", "Cortavientos", "Suecos"]:
            aplicados, _ = cm.tipo_para_columnas(tipo, "calzado")
            for columna, valor in aplicados.items():
                with self.subTest(tipo=tipo, columna=columna):
                    _limpio, ok = cm.valor_valido(columna, valor)
                    self.assertTrue(ok, f"{columna} = {valor}")

    def test_un_tipo_que_no_existe_no_inventa_nada(self):
        aplicados, _ = cm.tipo_para_columnas("Cosa Rara", "calzado")
        self.assertEqual(aplicados, {})


class TestElTipoLlegaAlArchivo(unittest.TestCase):
    """De punta a punta: la columna de tipo sale llena en el Centry."""

    def test_calzado_de_rockford(self):
        centry, _ = centry_de("rockford", "Rockford", "RK1-ABC", "Zapatos",
                              "Masculino", ["40", "41"])
        fila_centry = centry.iloc[0]
        self.assertEqual(
            fila_centry["Tipo - Calzado (Falabella GSC Perú)"], "Zapatos casuales"
        )

    def test_calzado_de_vans(self):
        centry, _ = centry_de("vans", "Vans", "VN1-BLK", "Zapatillas",
                              "Masculino", ["8", "9"])
        self.assertEqual(
            centry.iloc[0]["Tipo - Calzado (Falabella GSC Perú)"], "Zapatillas urbanas"
        )

    def test_vestuario_de_columbia(self):
        centry, _ = centry_de("columbia", "Columbia", "CO1-XYZ", "Casacas",
                              "Masculino", ["S", "M"])
        fila_centry = centry.iloc[0]
        self.assertEqual(
            fila_centry["Tipo de prenda para la parte superior - Ropa y accesorios (Falabella GSC Perú)"],
            "Casacas",
        )
        self.assertEqual(
            fila_centry["Tipo de chaqueta/chaleco - Ropa y accesorios (Falabella GSC Perú)"],
            "Chaquetas",
        )

    def test_ya_no_quedan_avisos_de_plantilla_por_el_tipo(self):
        """Regresion: cada producto dejaba un aviso "se dejo vacia"."""
        for caso in [("rockford", "Rockford", "RK1-ABC", "Zapatos", "Masculino", ["40"]),
                     ("vans", "Vans", "VN1-BLK", "Zapatillas", "Masculino", ["8"]),
                     ("columbia", "Columbia", "CO1-XYZ", "Casacas", "Masculino", ["S"])]:
            with self.subTest(marca=caso[1]):
                _centry, issues = centry_de(*caso)
                avisos = [r for r in issues.to_dict("records")
                          if "plantilla" in str(r.get("Mod-Col"))
                          and "Tipo" in str(r.get("Problema"))]
                self.assertEqual(avisos, [])


class TestResumenDeLaPantalla(unittest.TestCase):
    """Listos | Con observaciones | Bloqueados."""

    def _validacion(self, filas):
        return pd.DataFrame(filas, columns=["Mod-Col", "Campo", "Problema", "Valor",
                                            "Variantes", "SKUs", "Severidad"])

    def test_clasifica_cada_producto(self):
        centry = pd.DataFrame([
            {"SKU del producto": "A-1"}, {"SKU del producto": "B-1"}, {"SKU del producto": "C-1"},
        ])
        validacion = self._validacion([
            {"Mod-Col": "B-1", "Campo": "Material", "Problema": "", "Valor": "",
             "Variantes": 1, "SKUs": "", "Severidad": "Advertencia"},
            {"Mod-Col": "C-1", "Campo": "EAN", "Problema": "", "Valor": "",
             "Variantes": 1, "SKUs": "", "Severidad": "Bloqueante"},
        ])
        estados = app.centry_estado_por_producto(centry, validacion)
        self.assertEqual(estados["A-1"], "Listo")
        self.assertEqual(estados["B-1"], "Con observaciones")
        self.assertEqual(estados["C-1"], "Bloqueado")

    def test_un_bloqueante_manda_sobre_la_advertencia(self):
        centry = pd.DataFrame([{"SKU del producto": "A-1"}])
        validacion = self._validacion([
            {"Mod-Col": "A-1", "Campo": "Material", "Problema": "", "Valor": "",
             "Variantes": 1, "SKUs": "", "Severidad": "Advertencia"},
            {"Mod-Col": "A-1", "Campo": "EAN", "Problema": "", "Valor": "",
             "Variantes": 1, "SKUs": "", "Severidad": "Bloqueante"},
        ])
        self.assertEqual(app.centry_estado_por_producto(centry, validacion)["A-1"], "Bloqueado")

    def test_sin_validacion_todos_estan_listos(self):
        centry = pd.DataFrame([{"SKU del producto": "A-1"}, {"SKU del producto": "B-1"}])
        estados = app.centry_estado_por_producto(centry, pd.DataFrame())
        self.assertEqual(set(estados.values()), {"Listo"})


if __name__ == "__main__":
    unittest.main(verbosity=2)
