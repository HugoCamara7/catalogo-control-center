"""Vestidos en el diccionario, y por que se bloquea una carga.

Origen: una carga de Rockford con 22 filas mostraba UNA sola observacion
—"Tipo de prenda / VESTIDOS / Bloquea la carga"— y abajo el mensaje "La
solicitud no puede enviarse: existen 21 registros bloqueados". Parecia que
Rockford no aceptaba vestidos. Eran dos fallos distintos:

1. El diccionario NO tenia ningun tipo para vestido. No era una restriccion
   de la marca: el filtro por marca es por CATEGORIA (Rockford admite
   Vestuario), nunca por tipo.
2. "Tipo de prenda" esta en VALIDACIONES_SOLO_AVISO y NUNCA bloquea, pero la
   fila del reporte se guardaba con el estado de la FILA, no de la
   observacion. Una fila bloqueada por otra causa pintaba de rojo un campo
   que solo avisa. Y las causas reales de bloqueo (campo obligatorio vacio,
   PUBLICAR_ sin SI/NO, Clase no permitida, Marca cruzada, Fecha invalida)
   no dejaban NINGUNA fila en el reporte: los 21 bloqueos no se explicaban
   en ningun lado.

Ejecutar:  python scripts/test_tipos_vestido_y_bloqueos.py
"""
import io
import sys
import types
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def _identity(*a, **k):
    if a and callable(a[0]):
        return a[0]
    return lambda f: f


class _Stub(types.ModuleType):
    session_state = {}
    secrets = {}
    cache_data = staticmethod(_identity)
    cache_resource = staticmethod(_identity)

    def __getattr__(self, name):
        return lambda *a, **k: None


if "streamlit" not in sys.modules:
    s = _Stub("streamlit")
    c = types.ModuleType("streamlit.components")
    v = types.ModuleType("streamlit.components.v1")
    s.__path__ = []
    c.__path__ = []
    c.v1 = v
    s.components = c
    sys.modules["streamlit"] = s
    sys.modules["streamlit.components"] = c
    sys.modules["streamlit.components.v1"] = v

import pandas as pd  # noqa: E402

import catalog_rules as reglas  # noqa: E402
from app_matrixify import (  # noqa: E402
    VALIDACIONES_SOLO_AVISO,
    _acciones_por_campo_df,
    commercial_allowed_classes_for_brand,
    commercial_input_columns_for_brand,
    commercial_product_type_rules_for_brand,
    validate_brand_commercial_input,
)

MARCA = "Rockford"


def _fila_valida(cols, **cambios):
    """Una fila que pasa la validacion entera. Cada test rompe UNA cosa."""
    fila = {c: "" for c in cols}
    fila.update({
        "Mod-Col": "RK110021763-2VH",
        "Marca": MARCA,
        "Genero": "Mujer",
        "Clase": "Vestuario",
        "Tipo de prenda": "Vestidos",
        "Color Comercial": "Negro",
        "Color web/filtro": "Negro",
        "Nombre de Producto": "Vestido Mujer Terra Rockford",
        "Descripcion": "Vestido de algodon con caida suelta, pensado para el diario.",
        "Caracteristicas": "Tela liviana|Corte suelto",
    })
    for c in cols:
        if c.startswith("PUBLICAR_"):
            fila[c] = "SI"
    fila.update(cambios)
    return fila


def _validar(filas, marca=MARCA):
    buf = io.BytesIO()
    with pd.ExcelWriter(buf, engine="openpyxl") as w:
        pd.DataFrame(filas).to_excel(w, index=False, sheet_name="INPUT_COMERCIAL")
    buf.seek(0)
    return validate_brand_commercial_input(buf, marca)


class TestVestidoEnElDiccionario(unittest.TestCase):
    def test_vestidos_se_reconoce(self):
        self.assertIsNotNone(reglas.normalize_product_type("VESTIDOS"))

    def test_todas_las_formas_caen_en_el_mismo_tipo(self):
        for escrito in ("vestido", "Vestidos", "VESTIDO", "dress", "Dresses", "  vestidos "):
            regla = reglas.normalize_product_type(escrito)
            self.assertIsNotNone(regla, escrito)
            self.assertEqual(regla["plural"], "Vestidos", escrito)

    def test_es_vestuario_y_no_admite_talla_unica(self):
        regla = reglas.normalize_product_type("Vestidos")
        self.assertEqual(regla["category"], "Vestuario")
        self.assertEqual(regla["subcategory"], "Vestidos")
        self.assertFalse(regla["can_one_size"])

    def test_trae_grupo_de_guia_de_tallas(self):
        """Sin grupo, TOPS y BOTTOMS empatan y gana el orden de la lista."""
        self.assertEqual(reglas.normalize_product_type("Vestidos")["size_guide_group"], "TOPS")

    def test_ya_no_genera_observacion_de_tipo(self):
        decision = reglas.validate_catalog_row({
            "Mod-Col": "RK110021763-2VH", "Marca": MARCA, "Genero": "Mujer",
            "Categoria": "Vestuario", "Tipo de prenda": "VESTIDOS",
            "Guia de tallas": "", "Talla": "M", "SKU": "VALIDACION",
        })
        tipo = [i for i in decision["issues"] if i.get("field") == "Tipo de prenda"]
        self.assertEqual(tipo, [])

    def test_ningun_alias_apunta_a_dos_tipos(self):
        vistos = {}
        for regla in reglas.PRODUCT_TYPE_RULES:
            for campo in ("normalized", "singular", "plural", "received"):
                for parte in str(regla[campo]).split(","):
                    clave = reglas.normalize_key(parte)
                    if not clave:
                        continue
                    dueno = vistos.setdefault(clave, regla["normalized"])
                    self.assertEqual(dueno, regla["normalized"], f"alias repetido: {parte}")


class TestNoEsUnaRestriccionDeMarca(unittest.TestCase):
    """El filtro por marca es por categoria, no por tipo de prenda."""

    def test_rockford_admite_vestuario(self):
        self.assertIn("Vestuario", commercial_allowed_classes_for_brand(MARCA))

    def test_vestidos_aparece_en_los_tipos_de_rockford(self):
        tipos = {r["plural"] for r in commercial_product_type_rules_for_brand(MARCA)}
        self.assertIn("Vestidos", tipos)

    def test_todas_las_marcas_de_vestuario_lo_admiten(self):
        for marca in ("Rockford", "Columbia", "Vans", "Patagonia"):
            tipos = {r["plural"] for r in commercial_product_type_rules_for_brand(marca)}
            self.assertIn("Vestidos", tipos, marca)

    def test_una_fila_de_vestido_de_rockford_queda_lista(self):
        cols = commercial_input_columns_for_brand(MARCA)
        preview, _, _ = _validar([_fila_valida(cols)])
        self.assertFalse(preview.empty)
        self.assertEqual(preview.iloc[0]["Estado"], "Listo", preview.iloc[0]["Mensaje"])


class TestElEstadoEsDeLaObservacionNoDeLaFila(unittest.TestCase):
    def setUp(self):
        self.cols = commercial_input_columns_for_brand(MARCA)

    def test_tipo_de_prenda_sigue_siendo_solo_aviso(self):
        self.assertIn("Tipo de prenda", VALIDACIONES_SOLO_AVISO)

    def test_un_tipo_desconocido_en_fila_bloqueada_no_sale_como_bloqueante(self):
        """El caso exacto del reporte: la tarjeta roja era la del campo que no bloquea."""
        fila = _fila_valida(self.cols, **{"Tipo de prenda": "TipoQueNoExiste", "Genero": ""})
        preview, reporte, _ = _validar([fila])
        self.assertEqual(preview.iloc[0]["Estado"], "Bloqueado")
        tipo = reporte[reporte["Campo"].eq("Tipo de prenda")]
        self.assertFalse(tipo.empty, "el aviso de tipo desaparecio del reporte")
        self.assertEqual(set(tipo["Estado"]), {"Con advertencia"})

    def test_la_causa_real_si_sale_como_bloqueante(self):
        fila = _fila_valida(self.cols, **{"Tipo de prenda": "TipoQueNoExiste", "Genero": ""})
        _, reporte, _ = _validar([fila])
        genero = reporte[reporte["Campo"].eq("Genero")]
        self.assertFalse(genero.empty, "el campo obligatorio vacio no llego al reporte")
        self.assertEqual(set(genero["Estado"]), {"Bloqueado"})

    def test_la_hoja_que_hacer_marca_bien_cada_campo(self):
        fila = _fila_valida(self.cols, **{"Tipo de prenda": "TipoQueNoExiste", "Genero": ""})
        _, reporte, _ = _validar([fila])
        acciones = _acciones_por_campo_df(reporte).set_index("Campo")["Bloquea la carga"].to_dict()
        self.assertEqual(acciones.get("Genero"), "SI")
        self.assertEqual(acciones.get("Tipo de prenda"), "NO")


class TestTodaCausaDeBloqueoSeExplica(unittest.TestCase):
    """Cada motivo de bloqueo deja su fila en el reporte, con campo y accion."""

    def setUp(self):
        self.cols = commercial_input_columns_for_brand(MARCA)
        self.publicar = next(c for c in self.cols if c.startswith("PUBLICAR_"))

    def _reporte_de(self, **cambios):
        _, reporte, _ = _validar([_fila_valida(self.cols, **cambios)])
        return reporte

    def _asegurar(self, reporte, campo):
        """El campo deja fila en el reporte, marcada como bloqueante y con accion.

        Se pide "al menos una" y no "todas": un mismo campo puede juntar un
        bloqueo y un aviso. Descripcion es el caso: llega basura (bloquea) y
        ademas queda bajo el minimo de caracteres (solo avisa).
        """
        self.assertFalse(reporte.empty, f"{campo}: el reporte quedo vacio")
        filas = reporte[reporte["Campo"].eq(campo)]
        self.assertFalse(filas.empty, f"{campo} no aparece en el reporte: {list(reporte['Campo'])}")
        bloqueantes = filas[filas["Estado"].eq("Bloqueado")]
        self.assertFalse(bloqueantes.empty, f"{campo} no quedo marcado como bloqueante")
        self.assertTrue(all(str(v).strip() for v in bloqueantes["Accion recomendada"]), campo)
        return bloqueantes

    def test_campo_obligatorio_vacio(self):
        self._asegurar(self._reporte_de(**{"Color web/filtro": ""}), "Color web/filtro")

    def test_campo_obligatorio_con_texto_basura(self):
        """El valor basura se muestra tal cual, para saber que borrar.

        Se usa "pendiente" y no "n/a": pandas convierte "n/a" en NaN al leer el
        Excel, asi que a la app le llega vacio y se reporta como "(vacio)".
        """
        filas = self._asegurar(self._reporte_de(**{"Descripcion": "pendiente"}), "Descripcion")
        self.assertIn("pendiente", " ".join(str(v) for v in filas["Valor original"]))

    def test_publicar_sin_si_ni_no(self):
        self._asegurar(self._reporte_de(**{self.publicar: "TAL VEZ"}), self.publicar)

    def test_publicar_vacio(self):
        filas = self._asegurar(self._reporte_de(**{self.publicar: ""}), self.publicar)
        self.assertIn("(vacio)", " ".join(str(v) for v in filas["Valor original"]))

    def test_clase_no_permitida(self):
        filas = self._asegurar(self._reporte_de(**{"Clase": "Mascotas"}), "Clase")
        self.assertIn("Vestuario", " ".join(str(v) for v in filas["Accion recomendada"]))

    def test_marca_cruzada(self):
        filas = self._asegurar(self._reporte_de(**{"Marca": "Columbia"}), "Marca")
        self.assertIn("Columbia", " ".join(str(v) for v in filas["Valor original"]))

    def test_fecha_de_publicacion_invalida(self):
        if "Fecha publicacion" not in self.cols:
            self.skipTest("la marca no declara Fecha publicacion")
        self._asegurar(self._reporte_de(**{"Fecha publicacion": "el jueves"}), "Fecha publicacion")

    def test_ninguna_fila_bloqueada_se_queda_sin_explicacion(self):
        """Lo que fallaba: 21 bloqueos y ninguna tarjeta que los nombrara."""
        filas = [
            _fila_valida(self.cols, **{"Mod-Col": "RK-1", "Genero": ""}),
            _fila_valida(self.cols, **{"Mod-Col": "RK-2", "Clase": "Mascotas"}),
            _fila_valida(self.cols, **{"Mod-Col": "RK-3", self.publicar: ""}),
            _fila_valida(self.cols, **{"Mod-Col": "RK-4", "Tipo de prenda": "TipoQueNoExiste"}),
        ]
        preview, reporte, resumen = _validar(filas)
        bloqueados = int(resumen[resumen["Indicador"].eq("Registros bloqueados")]["Valor"].iloc[0])
        self.assertEqual(bloqueados, 3)
        explicadas = set(reporte[reporte["Estado"].eq("Bloqueado")]["Mod-Col"])
        con_bloqueo = set(preview[preview["Estado"].eq("Bloqueado")]["Mod-Col"])
        self.assertEqual(con_bloqueo - explicadas, set())

    def test_el_duplicado_avisa_pero_no_bloquea(self):
        filas = [_fila_valida(self.cols), _fila_valida(self.cols)]
        preview, reporte, _ = _validar(filas)
        self.assertNotIn("Bloqueado", set(preview["Estado"]))
        dup = reporte[reporte["Campo"].eq("Mod-Col")]
        self.assertFalse(dup.empty)
        self.assertEqual(set(dup["Estado"]), {"Con advertencia"})


class TestElPanelPonePrimeroLoQueBloquea(unittest.TestCase):
    def test_las_tarjetas_bloqueantes_van_arriba(self):
        import app_matrixify

        dibujado = []
        original = app_matrixify.st.markdown
        app_matrixify.st.markdown = lambda html, **k: dibujado.append(html)
        try:
            reporte = pd.DataFrame([
                {"Fila": 2, "Mod-Col": "RK-1", "Campo": "Tipo de prenda", "Valor original": "VESTIDOS",
                 "Valor normalizado": "", "Estado": "Con advertencia", "Mensaje": "no esta en el diccionario",
                 "Accion recomendada": "Avisar al equipo."},
                {"Fila": 3, "Mod-Col": "RK-2", "Campo": "Genero", "Valor original": "(vacio)",
                 "Valor normalizado": "", "Estado": "Bloqueado", "Mensaje": "obligatorio vacio",
                 "Accion recomendada": "Completa Genero."},
            ])
            app_matrixify._render_resumen_observaciones(reporte)
        finally:
            app_matrixify.st.markdown = original
        html = "".join(dibujado)
        self.assertIn("Genero", html)
        self.assertIn("Tipo de prenda", html)
        self.assertLess(html.index("Genero"), html.index("Tipo de prenda"),
                        "el campo que bloquea tiene que salir primero")


if __name__ == "__main__":
    unittest.main(verbosity=2)
