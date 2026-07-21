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
    build_partial_diagnostic_table,
    filter_preview_by_diagnostic_ready,
    partial_diagnostic_summary,
    validate_partial_body_html,
    validate_partial_image_urls,
)


def test_body_blocks_script():
    status, problem = validate_partial_body_html("<script>alert(1)</script>")
    assert status == "Bloqueado"
    assert problem


def test_photos_block_invalid_url():
    status, problem, count, duplicates = validate_partial_image_urls("ftp://foto.jpg; https://ok.example/foto.jpg")
    assert status == "Bloqueado"
    assert count == 2
    assert duplicates == 0
    assert "inválida" in problem or "invalida" in problem


def test_size_guide_blocks_incompatible_catalog_row():
    preview = pd.DataFrame(
        [
            {
                "Operacion": "size_guides",
                "Mod-Col": "ABC-123",
                "Handle": "producto-prueba",
                "Campo": "Metafield: custom.guia_de_tallas",
                "Valor actual": "",
                "Valor nuevo": "GUIA_NO_EXISTE",
                "Marca": "Columbia",
                "Categoria": "Calzado",
                "Tipo": "Zapatillas",
                "Genero": "Mujer",
            }
        ]
    )
    diagnostic = build_partial_diagnostic_table(preview, operation="size_guides")
    assert diagnostic.iloc[0]["Estado validacion"] in {"Bloqueado", "Con observacion"}


def test_filter_only_ready_rows():
    preview = pd.DataFrame(
        [
            {"Mod-Col": "A-1", "Handle": "a", "Operacion": "body"},
            {"Mod-Col": "B-1", "Handle": "b", "Operacion": "body"},
        ]
    )
    diagnostic = pd.DataFrame(
        [
            {"Mod-Col": "A-1", "Handle": "a", "Estado validacion": "Listo"},
            {"Mod-Col": "B-1", "Handle": "b", "Estado validacion": "Bloqueado"},
        ]
    )
    filtered = filter_preview_by_diagnostic_ready(preview, diagnostic)
    assert list(filtered["Handle"]) == ["a"]


def test_body_diagnostic_reads_matrixify_body_html_column():
    preview = pd.DataFrame(
        [
            {
                "Operacion": "body",
                "Mod-Col": "ABC-123",
                "Handle": "producto-prueba",
                "Title": "Producto Prueba",
                "Body HTML": "<section><h3>Caracteristicas</h3><ul><li>Chaqueta impermeable para uso urbano diario con buena ventilacion.</li></ul></section><section><h3>Materiales</h3><ul><li>Exterior: 100% poliester.</li></ul></section><section><h3>Cuidados</h3><ul><li>Lavar con agua fria y secar a la sombra.</li></ul></section>",
            }
        ]
    )
    diagnostic = build_partial_diagnostic_table(preview, operation="body")
    assert diagnostic.iloc[0]["Estado validacion"] == "Listo"
    assert diagnostic.iloc[0]["Campo afectado"] == "Body HTML"


def test_photos_summary_counts_invalid_and_ready_rows():
    preview = pd.DataFrame(
        [
            {"Operacion": "photos", "Mod-Col": "A-1", "Handle": "a", "Image Src": "https://example.com/a.jpg; https://example.com/b.jpg"},
            {"Operacion": "photos", "Mod-Col": "B-1", "Handle": "b", "Image Src": ""},
        ]
    )
    diagnostic = build_partial_diagnostic_table(preview, operation="photos")
    summary = partial_diagnostic_summary(diagnostic, "photos").set_index("Indicador")["Valor"].to_dict()
    assert summary["Modelos analizados"] == 2
    assert summary["Listos para actualizar"] == 1
    assert summary["Bloqueados"] == 1


if __name__ == "__main__":
    test_body_blocks_script()
    test_photos_block_invalid_url()
    test_size_guide_blocks_incompatible_catalog_row()
    test_filter_only_ready_rows()
    test_body_diagnostic_reads_matrixify_body_html_column()
    test_photos_summary_counts_invalid_and_ready_rows()
    print("OK partial maintenance validations")
