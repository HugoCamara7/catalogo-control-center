import sys
import types
from datetime import datetime
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))


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

from app_matrixify import build_brand_commercial_input_workbook, configured_commercial_brands, clean_value


def safe_file_brand(value):
    return "".join(ch if ch.isalnum() else "_" for ch in clean_value(value)).strip("_").upper()


def main():
    output_dir = ROOT_DIR / "outputs" / "input_templates"
    output_dir.mkdir(parents=True, exist_ok=True)
    date_tag = datetime.now().strftime("%Y%m%d")
    for brand in configured_commercial_brands():
        workbook = build_brand_commercial_input_workbook(brand)
        path = output_dir / f"Input_Catalogo_{safe_file_brand(brand)}_{date_tag}.xlsx"
        path.write_bytes(workbook.getvalue())
        print(path)


if __name__ == "__main__":
    main()
