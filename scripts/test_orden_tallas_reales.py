"""El orden de tallas, contra el maestro DE VERDAD.

Ejecutar:  python scripts/test_orden_tallas_reales.py

Por que esta prueba y no otra
-----------------------------
Cambiar `size_sort_key` toca la carga de TODAS las marcas. Un juego de casos
escritos a mano no sirve para eso: prueba lo que a uno se le ocurre, y lo que
rompe una carga es justo lo que no se le ocurrio a nadie. Es el mismo error que
ya se pago en septiembre de 2026 con el lector del maestro de VTEX, que paso
sus 62 pruebas porque se probo con una muestra de 500 filas.

Aqui se recorren los **~70.000 modelo-color** de `data/arti.zip` -653.431 filas
del maestro real- y se arma la curva de cada uno tal y como la arma la carga.

La garantia es una sola frase:

    En todo producto cuyas tallas el criterio VIEJO ya reconocia todas, el
    orden nuevo es identico, talla por talla.

Eso es lo que asegura que Rockford (3 productos afectados de 9.785), Hush
Puppies (2 de 14.581) y el 97,7 % de Columbia no se muevan. Lo que cambia
cambia SOLO donde antes se ordenaba alfabeticamente, que era el fallo.
"""
import collections
import csv
import io
import os
import sys
import unittest
import zipfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from engines import tallas  # noqa: E402
import generate_columbia_matrixify as g  # noqa: E402

MAESTRO = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                       "data", "arti.zip")


def criterio_viejo(value):
    """El `size_sort_key` que habia antes del diccionario, copiado tal cual.

    Se conserva AQUI y no en el codigo de produccion: es el patron contra el
    que se compara, no una alternativa que se pueda elegir.
    """
    import re
    size = g.normalize_size(value)
    alpha_order = {"XXXS": 1, "XXS": 2, "XS": 3, "S": 4, "S/M": 5, "M": 6,
                   "M/L": 7, "L": 8, "L/XL": 9, "XL": 10, "XXL": 11,
                   "XXXL": 12, "O/S": 99}
    if size in alpha_order:
        return (0, alpha_order[size], size)
    if re.fullmatch(r"\d+(\.\d+)?", size):
        return (1, float(size), size)
    match = re.fullmatch(r"(\d+(\.\d+)?)/(\d+(\.\d+)?)", size)
    if match:
        return (2, float(match.group(1)), float(match.group(3)), size)
    return (9, 9999, size)


def reconocida_por_el_viejo(size):
    return criterio_viejo(size)[0] != 9


def curvas_del_maestro():
    """{(marca, mod-col): [tallas normalizadas, sin repetir]} del maestro real.

    Se aplican los mismos filtros que la carga: fuera las tallas internas K y
    las talla-0, que nunca llegan a Shopify.
    """
    curvas = collections.defaultdict(list)
    with zipfile.ZipFile(MAESTRO) as z:
        with z.open("arti.csv") as crudo:
            lector = csv.DictReader(io.TextIOWrapper(crudo, encoding="utf-8", errors="replace"))
            for fila in lector:
                marca = (fila.get("MARCA_MA") or "").strip().upper()
                clave = (fila.get("COD MOD COL") or "").strip().upper()
                bruta = (fila.get("TALNUM_MA") or "").strip()
                if not clave or not bruta:
                    continue
                if g.is_internal_k_size(bruta) or g.is_zero_size(bruta):
                    continue
                talla = g.normalize_size(bruta)
                if talla and talla not in curvas[(marca, clave)]:
                    curvas[(marca, clave)].append(talla)
    return curvas


CURVAS = None


def curvas():
    global CURVAS
    if CURVAS is None:
        CURVAS = curvas_del_maestro()
    return CURVAS


class OrdenNuevoNoMueveLoQueYaFuncionaba(unittest.TestCase):
    """La garantia principal. Si esta falla, NO se entrega."""

    def test_curvas_ya_reconocidas_salen_identicas(self):
        revisadas = 0
        distintas = []
        for (marca, clave), curva in curvas().items():
            if len(curva) < 2:
                continue
            if not all(reconocida_por_el_viejo(t) for t in curva):
                continue  # aqui el criterio viejo se equivocaba: puede cambiar
            revisadas += 1
            viejo = sorted(curva, key=criterio_viejo)
            nuevo = sorted(curva, key=g.size_sort_key)
            if viejo != nuevo and len(distintas) < 20:
                distintas.append((marca, clave, viejo, nuevo))
        self.assertGreater(revisadas, 50000,
                           "la prueba tiene que recorrer el maestro entero")
        self.assertEqual(
            distintas, [],
            "el orden cambio en curvas que el criterio viejo ya ordenaba bien:\n"
            + "\n".join(f"  {m} {k}\n    antes: {a}\n    ahora: {b}" for m, k, a, b in distintas),
        )

    def test_las_dos_capas_ordenan_igual(self):
        """`app_matrixify.size_sort_key` y el del maestro tienen que coincidir.

        Antes no coincidian en las tallas compuestas, y entonces la ficha
        quedaba en un orden y la vista previa en otro.
        """
        import app_matrixify as app
        for (_marca, _clave), curva in list(curvas().items())[:4000]:
            self.assertEqual(
                sorted(curva, key=app.size_sort_key),
                sorted(curva, key=g.size_sort_key),
            )


class LoQueEstabaMalAhoraSaleBien(unittest.TestCase):
    """Los casos concretos, sacados del maestro real. Todos fallan con el
    criterio viejo."""

    def ordenar(self, curva):
        return sorted(curva, key=g.size_sort_key)

    def test_letra_con_largo(self):
        # Columbia 2135771-2OO. Es el caso que reporto el usuario.
        curva = ["L/R", "M/R", "S/R", "XL/R", "XS/R"]
        self.assertEqual(self.ordenar(curva), ["XS/R", "S/R", "M/R", "L/R", "XL/R"])
        self.assertNotEqual(sorted(curva, key=criterio_viejo), self.ordenar(curva))

    def test_letra_con_largo_hasta_xxl(self):
        curva = ["XXL/R", "L/R", "M/R", "S/R", "XL/R", "XS/R"]
        self.assertEqual(self.ordenar(curva),
                         ["XS/R", "S/R", "M/R", "L/R", "XL/R", "XXL/R"])

    def test_numero_con_largo(self):
        # Columbia 2135811-5HD: hoy sale 10/R, 12/R, 2/R, 4/R...
        curva = ["10/R", "12/R", "2/R", "4/R", "6/R", "8/R"]
        self.assertEqual(self.ordenar(curva),
                         ["2/R", "4/R", "6/R", "8/R", "10/R", "12/R"])

    def test_letra_con_copa(self):
        # Columbia 2094731-TVR. Y `S/ 8` con espacio es la misma que `S/8`.
        curva = ["L/6", "L/8", "M/6", "M/8", "S/ 8", "S/ 6", "XL/6", "XL/8", "XXL/6"]
        self.assertEqual(
            self.ordenar(curva),
            ["S/ 6", "S/ 8", "M/6", "M/8", "L/6", "L/8", "XL/6", "XL/8", "XXL/6"],
        )

    def test_fechas_de_excel(self):
        # Columbia 1523741-3HS: 3-6, 6-12 y 12-18 meses, que Excel convirtio.
        curva = ["18/24", "03-JUN", "06-DIC", "DIC-18"]
        self.assertEqual(self.ordenar(curva), ["03-JUN", "06-DIC", "DIC-18", "18/24"])

    def test_patagonia_short_y_tall(self):
        curva = ["M", "L", "LS", "LT", "MS", "MT", "ST"]
        self.assertEqual(self.ordenar(curva), ["M", "L", "ST", "MS", "MT", "LS", "LT"])

    def test_meses_de_bebe(self):
        curva = ["12M", "3-6M", "24M", "6-9M", "18M", "9-12M"]
        self.assertEqual(self.ordenar(curva),
                         ["3-6M", "6-9M", "9-12M", "12M", "18M", "24M"])

    def test_2xl_y_3xl_no_van_al_final_por_texto(self):
        curva = ["3XL", "S", "2XL", "M", "L", "XL"]
        self.assertEqual(self.ordenar(curva), ["S", "M", "L", "XL", "2XL", "3XL"])

    def test_medias_tallas_de_calzado(self):
        """El fallo que ya se habia arreglado y que no puede volver."""
        curva = ["42", "40.5", "38.5", "39", "36", "44.5"]
        self.assertEqual(self.ordenar(curva),
                         ["36", "38.5", "39", "40.5", "42", "44.5"])

    def test_infantil_de_la_guia_de_vans(self):
        curva = ["1Y", "10.5C", "3Y", "13C", "2.5Y", "13.5C"]
        self.assertEqual(self.ordenar(curva),
                         ["10.5C", "13C", "13.5C", "1Y", "2.5Y", "3Y"])


class LoQueNoSeToca(unittest.TestCase):
    def test_talla_unica_sigue_donde_estaba(self):
        """`O/S` va en la escala de letras, en 99. Sacarlo a familia propia
        cambiaria el orden de los productos que lo mezclan con numeros
        -- PARFOIS tiene varios -- y ahi hoy O/S va primero."""
        curva = ["O/S", "S", "M", "L", "38", "36"]
        self.assertEqual(sorted(curva, key=g.size_sort_key),
                         sorted(curva, key=criterio_viejo))

    def test_one_y_osfa_siguen_al_final(self):
        curva = ["S", "M", "L", "XL", "ONE"]
        self.assertEqual(sorted(curva, key=g.size_sort_key),
                         ["S", "M", "L", "XL", "ONE"])

    def test_rangos_de_calzado_no_se_mueven(self):
        # Rockford RK2890114-MA0 y Hush Puppies HP21001113195-U61.
        curva = ["35", "36", "37", "38", "39", "40", "35-36", "37-38", "39-40", "41-42"]
        self.assertEqual(sorted(curva, key=g.size_sort_key),
                         sorted(curva, key=criterio_viejo))


class SeReportaLoQueNoSeEntiende(unittest.TestCase):
    def test_una_forma_nueva_se_puede_nombrar(self):
        """Una talla que el diccionario no reconoce se ordena por texto, que es
        el fallo que este modulo arregla. Tiene que poder REPORTARSE, no
        esconderse."""
        self.assertEqual(tallas.no_reconocidas(["S", "M", "XLXXL"]), ["XLXXL"])
        self.assertEqual(tallas.no_reconocidas(["S", "M", "L"]), [])

    def test_cuantas_formas_quedan_sin_reconocer_en_el_maestro(self):
        """Deja constancia de cuanto cubre el diccionario. Si alguien lo
        empeora, este numero sube y la prueba falla."""
        sueltas = collections.Counter()
        for (_marca, _clave), curva in curvas().items():
            for talla in curva:
                if not tallas.es_reconocida(talla):
                    sueltas[talla] += 1
        productos_afectados = sum(
            1 for curva in curvas().values()
            if any(not tallas.es_reconocida(t) for t in curva)
        )
        total = len(curvas())
        print(f"\n  Formas sin reconocer: {len(sueltas):,} distintas · "
              f"{productos_afectados:,} de {total:,} modelo-color "
              f"({100.0 * productos_afectados / max(total, 1):.2f} %)")
        print("  Las 15 mas frecuentes:", sueltas.most_common(15))
        self.assertLess(
            productos_afectados / max(total, 1), 0.02,
            "el diccionario deberia cubrir mas del 98 % de los modelo-color",
        )


if __name__ == "__main__":
    unittest.main(verbosity=2)
