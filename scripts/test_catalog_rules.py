import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from catalog_rules import (
    build_catalog_handle,
    is_invalid_size_for_creation,
    normalize_product_type,
    resolve_size_guide,
    sanitize_body_html,
    validate_catalog_row,
)


def assert_true(condition, message):
    if not condition:
        raise AssertionError(message)


def main():
    shoe_rule = normalize_product_type("zapatillas")
    assert_true(shoe_rule and shoe_rule["category"] == "Calzado", "Zapatillas debe normalizar a Calzado")

    handle = build_catalog_handle("Casacas", "Mujer", "Columbia", "2092991-NRY")
    assert_true(handle == "casacas-mujer-columbia-2092991-nry", "Handle debe ser tipo-genero-marca-modcol")

    jacket_rule = normalize_product_type("jacket")
    assert_true(jacket_rule and jacket_rule["plural"] == "Casacas", "Jacket debe pluralizar a Casacas")

    assert_true(is_invalid_size_for_creation("000"), "000 debe bloquearse")
    assert_true(is_invalid_size_for_creation("K"), "K debe bloquearse")
    assert_true(not is_invalid_size_for_creation("M"), "M debe ser talla valida")

    blocked = resolve_size_guide(
        brand="Columbia",
        category="Calzado",
        gender="Hombre",
        current_guide="CLB_HOMBRE_VESTUARIO",
    )
    assert_true(blocked["status"] == "blocked", "Calzado con guia vestuario debe bloquearse")

    approved = resolve_size_guide(brand="Columbia", category="Vestuario", gender="Mujer")
    assert_true(approved["guide"] == "CLB_MUJER_TOPS", "Vestuario mujer Columbia debe sugerir guia mujer tops")

    approved_top = resolve_size_guide(
        brand="Columbia",
        category="Vestuario",
        product_type="Casacas",
        gender="Mujer",
    )
    assert_true(approved_top["guide"] == "CLB_MUJER_TOPS", "Casacas mujer debe usar guia TOPS")

    approved_bottom = resolve_size_guide(
        brand="Columbia",
        category="Vestuario",
        product_type="Pantalones",
        gender="Mujer",
    )
    assert_true(approved_bottom["guide"] == "CLB_MUJER_BOTTOMS", "Pantalones mujer debe usar guia BOTTOMS")

    blocked_bottom = resolve_size_guide(
        brand="Columbia",
        category="Vestuario",
        product_type="Shorts",
        gender="Hombre",
        current_guide="CLB_HOMBRE_TOPS",
    )
    assert_true(blocked_bottom["status"] == "blocked", "Bottom con guia TOPS debe bloquearse")

    row_result = validate_catalog_row(
        {
            "Mod-Col": "2092991-NRY",
            "Marca": "Columbia",
            "Genero": "Mujer",
            "Categoria": "Vestuario",
            "Tipo de prenda": "Casacas",
            "Color web": "Negro",
            "Title": "Casaca Mujer",
            "Talla": "M",
            "SKU": "5327440",
            "Precio": "299.90",
        }
    )
    assert_true(not any(i["level"] == "bloqueo" for i in row_result["issues"]), "Fila ejemplo no debe bloquearse")

    clean_html, changes = sanitize_body_html("<script>x()</script><p onclick='x'>Hola</p>")
    assert_true("<script" not in clean_html.lower(), "Debe remover scripts")
    assert_true(changes, "Debe reportar cambios de HTML")

    print("OK catalog_rules")


if __name__ == "__main__":
    main()
