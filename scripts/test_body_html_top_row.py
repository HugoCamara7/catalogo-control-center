"""Pruebas de que el Body HTML y los metafields sobreviven al filtro final.

Origen: una carga de 67 productos Rockford salio con las 450 filas correctas
pero con el Body HTML, el Top Row y los ~20 metafields completamente vacios, y
la sincronizacion escribio en Shopify un solo metafield por producto.

El bloque de producto se escribe una sola vez, en la primera variante. En
Rockford las tallas cero se muestran como "Talla Unica", ordenan primeras y se
llevaban esa posicion 1; despues `final_variant_filter` las borraba por ser
talla unica en calzado y se iba con ellas la descripcion del producto entero.

Ejecutar:  python scripts/test_body_html_top_row.py
"""
import sys
import unittest
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from generate_columbia_matrixify import (  # noqa: E402
    clean,
    collapse_top_row_block,
    display_size_for_site,
    final_variant_filter,
    get_brand_config,
    spread_top_row_block,
)

CUERPO = "<section><p>El mocasin Auckland es la eleccion perfecta.</p></section>"
METAFIELD_CODIGO = "Metafield: custom.codigo_modelo_color [id]"
METAFIELD_GENERO = "Metafield: custom.genero [single_line_text_field]"


def producto_rockford(tallas_arti):
    """Un calzado Rockford tal como sale del bucle: bloque solo en la fila 1."""
    config = get_brand_config("rockford")
    filas = []
    for posicion, talla in enumerate(tallas_arti, start=1):
        primera = posicion == 1
        filas.append(
            {
                "Handle": "mocasin-cuero-mujer-rockford-rk202011432-645-marron",
                "Title": "Mocasin Cuero Mujer Rockford",
                "Type": "Mocasines",
                "Tags": "Mujer, Mocasin, Rockford, Calzado",
                "Body HTML": CUERPO if primera else "",
                "Top Row": "TRUE" if primera else "",
                "Row #": posicion,
                "Variant Position": posicion,
                "Option1 Value": display_size_for_site(talla, config),
                "Variant SKU": f"SKU{posicion:03d}",
                METAFIELD_CODIGO: "RK202011432-645" if primera else "",
                METAFIELD_GENERO: "MUJER" if primera else "",
            }
        )
    return pd.DataFrame(filas)


def pipeline(output_df):
    """Los tres pasos tal como los encadena build_columbia_matrixify."""
    output_df = spread_top_row_block(output_df)
    output_df, _, _ = final_variant_filter(output_df, pd.DataFrame(), pd.DataFrame())
    return collapse_top_row_block(output_df)


class TestBloqueDeProducto(unittest.TestCase):
    def test_sobrevive_aunque_el_filtro_borre_la_primera_fila(self):
        # Las dos tallas cero se vuelven "Talla Unica" y el filtro las elimina.
        salida = pipeline(producto_rockford(["0", "0", "350", "360", "370"]))

        self.assertEqual(len(salida), 3, "solo deben quedar las tallas reales")
        primera = salida.iloc[0]
        self.assertEqual(clean(primera["Body HTML"]), CUERPO)
        self.assertEqual(clean(primera["Top Row"]).upper(), "TRUE")
        self.assertEqual(clean(primera[METAFIELD_CODIGO]), "RK202011432-645")
        self.assertEqual(clean(primera[METAFIELD_GENERO]), "MUJER")

    def test_el_bloque_queda_en_una_sola_fila(self):
        salida = pipeline(producto_rockford(["0", "0", "350", "360", "370"]))

        for columna in ("Body HTML", "Top Row", METAFIELD_CODIGO, METAFIELD_GENERO):
            con_valor = (salida[columna].map(clean) != "").sum()
            self.assertEqual(con_valor, 1, f"{columna} debe quedar solo en la fila 1")

    def test_renumera_desde_uno(self):
        salida = pipeline(producto_rockford(["0", "0", "350", "360", "370"]))

        self.assertEqual(list(salida["Row #"]), [1, 2, 3])
        self.assertEqual(list(salida["Variant Position"]), [1, 2, 3])

    def test_no_toca_al_producto_que_no_pierde_su_primera_fila(self):
        entrada = producto_rockford(["350", "360", "370"])
        salida = pipeline(entrada)

        self.assertEqual(len(salida), 3)
        self.assertEqual(clean(salida.iloc[0]["Body HTML"]), CUERPO)
        self.assertEqual(list(salida["Row #"]), [1, 2, 3])

    def test_cada_producto_conserva_su_propio_bloque(self):
        uno = producto_rockford(["0", "350", "360"])
        otro = producto_rockford(["0", "370", "380"])
        otro["Handle"] = "sueco-cuero-mujer-rockford-rk228011233-n31"
        otro["Body HTML"] = otro["Body HTML"].replace({CUERPO: "<p>Otro cuerpo</p>"})
        otro[METAFIELD_CODIGO] = otro[METAFIELD_CODIGO].replace(
            {"RK202011432-645": "RK228011233-N31"}
        )

        salida = pipeline(pd.concat([uno, otro], ignore_index=True))

        por_handle = salida[salida["Top Row"].map(clean).str.upper() == "TRUE"]
        self.assertEqual(len(por_handle), 2, "una fila de cabecera por producto")
        cuerpos = dict(zip(por_handle["Handle"], por_handle["Body HTML"].map(clean)))
        codigos = dict(zip(por_handle["Handle"], por_handle[METAFIELD_CODIGO].map(clean)))
        self.assertEqual(cuerpos["mocasin-cuero-mujer-rockford-rk202011432-645-marron"], CUERPO)
        self.assertEqual(cuerpos["sueco-cuero-mujer-rockford-rk228011233-n31"], "<p>Otro cuerpo</p>")
        self.assertEqual(
            codigos["sueco-cuero-mujer-rockford-rk228011233-n31"], "RK228011233-N31"
        )


if __name__ == "__main__":
    unittest.main(verbosity=2)
