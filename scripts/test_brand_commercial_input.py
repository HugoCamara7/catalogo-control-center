import io
import sys
import types
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

import pandas as pd


def _identity_decorator(*args, **kwargs):
    if args and callable(args[0]):
        return args[0]

    def _decorator(func):
        return func

    return _decorator


class _StreamlitStub(types.ModuleType):
    session_state = {}
    cache_data = staticmethod(_identity_decorator)
    cache_resource = staticmethod(_identity_decorator)

    def __getattr__(self, name):
        def _noop(*args, **kwargs):
            return None

        return _noop


if "streamlit" not in sys.modules:
    streamlit_stub = _StreamlitStub("streamlit")
    components_pkg = types.ModuleType("streamlit.components")
    components_v1 = types.ModuleType("streamlit.components.v1")
    streamlit_stub.__path__ = []
    components_pkg.__path__ = []
    components_v1.html = lambda *args, **kwargs: None
    streamlit_stub.components = components_pkg
    components_pkg.v1 = components_v1
    sys.modules["streamlit"] = streamlit_stub
    sys.modules["streamlit.components"] = components_pkg
    sys.modules["streamlit.components.v1"] = components_v1

from app_matrixify import (
    build_body_html_from_commercial_row,
    build_brand_commercial_input_workbook,
    commercial_allowed_classes_for_brand,
    commercial_input_columns_for_brand,
    validate_brand_commercial_input,
)


def _to_upload(df):
    buffer = io.BytesIO()
    with pd.ExcelWriter(buffer, engine="openpyxl") as writer:
        df.to_excel(writer, index=False, sheet_name="INPUT_COMERCIAL")
    buffer.seek(0)
    return buffer


def test_brand_input_workbook_structure():
    workbook = build_brand_commercial_input_workbook("Columbia")
    xls = pd.ExcelFile(workbook)
    assert set(xls.sheet_names) == {"INPUT_COMERCIAL", "GUIA", "DICCIONARIO"}
    assert len(xls.sheet_names) <= 3
    columns = list(pd.read_excel(xls, sheet_name="INPUT_COMERCIAL", nrows=0).columns)
    assert "Body HTML" not in columns
    assert "Talla" not in columns
    assert "Tags sugeridos" not in columns
    assert "Tags adicionales" in columns
    assert "Nombre de Producto" in columns
    assert "Materiales" in columns
    assert "PUBLICAR_COLUMBIA_PE" in columns
    assert "PUBLICAR_ROCKFORD_PE" in columns


def test_brand_specific_allowed_classes():
    assert commercial_allowed_classes_for_brand("Columbia") == ["Calzado", "Vestuario", "Accesorios"]
    assert commercial_allowed_classes_for_brand("Rockford") == ["Calzado", "Vestuario", "Accesorios"]
    assert commercial_allowed_classes_for_brand("Vans") == ["Calzado", "Vestuario", "Accesorios"]
    assert commercial_allowed_classes_for_brand("Mountain Hardwear") == ["Vestuario", "Accesorios"]
    assert commercial_allowed_classes_for_brand("Patagonia") == ["Vestuario", "Accesorios"]
    assert commercial_allowed_classes_for_brand("Sorel") == ["Calzado"]
    assert commercial_allowed_classes_for_brand("Hush Puppies") == ["Calzado", "Accesorios"]
    assert commercial_allowed_classes_for_brand("Hush Puppies Kids") == ["Calzado", "Vestuario", "Accesorios"]


def test_brand_input_examples_respect_allowed_classes():
    sorel = pd.ExcelFile(build_brand_commercial_input_workbook("Sorel"))
    sorel_guide = pd.read_excel(sorel, sheet_name="GUIA")
    sorel_text = "\n".join(sorel_guide["Detalle"].dropna().astype(str).tolist())
    assert "Clase: Calzado" in sorel_text
    assert "Clase: Vestuario" not in sorel_text
    assert "Clase: Accesorios" not in sorel_text

    mountain = pd.ExcelFile(build_brand_commercial_input_workbook("Mountain Hardwear"))
    mountain_guide = pd.read_excel(mountain, sheet_name="GUIA")
    mountain_text = "\n".join(mountain_guide["Detalle"].dropna().astype(str).tolist())
    assert "Clase: Vestuario" in mountain_text
    assert "Clase: Accesorios" in mountain_text
    assert "Clase: Calzado" not in mountain_text


def test_brand_input_validation_blocks_bad_site_value():
    columns = commercial_input_columns_for_brand("Columbia")
    row = {column: "" for column in columns}
    row.update(
        {
            "Codigo modelo": "2092991",
            "Mod-Col": "2092991-NRY",
            "Marca": "Columbia",
            "Genero": "Mujer",
            "Clase": "Vestuario",
            "Tipo de prenda": "Casacas",
            "Color web/filtro": "Negro",
            "Nombre de Producto": "Casaca Impermeable Mujer Arcadia II",
            "Descripcion": "Casaca impermeable respirable para lluvia diaria con tecnologia de proteccion y uso outdoor.",
            "PUBLICAR_COLUMBIA_PE": "TAL VEZ",
            "PUBLICAR_ROCKFORD_PE": "NO",
        }
    )
    _, report, summary = validate_brand_commercial_input(_to_upload(pd.DataFrame([row])), "Columbia")
    assert not report.empty
    assert int(summary.loc[summary["Indicador"].eq("Registros bloqueados"), "Valor"].iloc[0]) == 1


def test_brand_input_validation_blocks_disallowed_class():
    columns = commercial_input_columns_for_brand("Sorel")
    row = {column: "" for column in columns}
    row.update(
        {
            "Mod-Col": "SRL-TEST-001",
            "Marca": "Sorel",
            "Genero": "Mujer",
            "Clase": "Vestuario",
            "Tipo de prenda": "Casacas",
            "Color web/filtro": "Negro",
            "Nombre de Producto": "Casaca Mujer Sorel No Permitida",
            "Descripcion": "Producto de prueba con una clase que no corresponde a la marca Sorel dentro del formato comercial.",
        }
    )
    for column in columns:
        if column.startswith("PUBLICAR_"):
            row[column] = "SI"
    _, report, summary = validate_brand_commercial_input(_to_upload(pd.DataFrame([row])), "Sorel")
    assert not report.empty
    assert report["Mensaje"].astype(str).str.contains("no permitida", case=False).any()
    assert int(summary.loc[summary["Indicador"].eq("Registros bloqueados"), "Valor"].iloc[0]) == 1


def test_body_html_is_generated_from_business_fields():
    body = build_body_html_from_commercial_row(
        {
            "Descripcion": "Descripcion comercial limpia.",
            "Caracteristicas": "Impermeable|Respirable",
            "Materiales": "Exterior: 100% poliester",
            "Cuidados": "Lavar con agua fria|No usar lejia",
        }
    )
    assert "<h3>Descripcion</h3>" in body
    assert "<h3>Caracteristicas</h3>" in body
    assert "<h3>Materiales</h3>" in body
    assert "<h3>Cuidados</h3>" in body


if __name__ == "__main__":
    test_brand_input_workbook_structure()
    test_brand_specific_allowed_classes()
    test_brand_input_examples_respect_allowed_classes()
    test_brand_input_validation_blocks_bad_site_value()
    test_brand_input_validation_blocks_disallowed_class()
    test_body_html_is_generated_from_business_fields()
    print("OK brand commercial input")
