"""Reassign Control Center - Forus Peru.

Automatiza la reasignacion de pedidos que no pudieron despacharse:

    Subir archivo -> Validar -> Consultar BigQuery -> Reasignar -> Revisar -> Descargar

BigQuery se usa **solo para leer stock**. El descuento de unidades ocurre en
memoria durante la corrida, para no comprometer dos veces el mismo stock.
"""

from __future__ import annotations

import hmac
from datetime import datetime
from typing import Any

import pandas as pd
import streamlit as st

from config import settings
from core import engine, excel_io
from core.priority import load_priority, priority_to_frame
from core.stock_source import (
    ManualStockSource,
    build_stock_index,
    is_bigquery_configured,
    resolve_stock_table,
    secrets_to_source,
    stock_cutoff,
)
from core.excel_io import normalize_status
from core.validation import resolve_columns, validate
from scripts.build_priority_template import build_bytes as build_priority_bytes
from ui import components as ui
from ui.theme import apply_login_theme, apply_theme

st.set_page_config(
    page_title=settings.APP_NAME,
    page_icon="RC",
    layout="wide",
    initial_sidebar_state="expanded",
)


# ---------------------------------------------------------------------------
# Secretos y sesion
# ---------------------------------------------------------------------------
def secrets_section(name: str) -> dict[str, Any]:
    try:
        if name in st.secrets:
            return dict(st.secrets[name])
    except Exception:
        pass
    return {}


def bigquery_secrets() -> dict[str, Any]:
    config = secrets_section("bigquery")
    account = secrets_section("gcp_service_account")
    if account:
        config["service_account_info"] = account
    return config


def require_login() -> bool:
    """Pantalla de acceso. Solo se exige si existe la seccion [app_auth].

    Sin esa seccion en `secrets.toml` la app queda abierta, para que un
    despliegue nuevo no se bloquee a si mismo antes de configurarse.
    """
    auth = secrets_section("app_auth")
    if not auth:
        return True
    if st.session_state.get("authenticated"):
        return True

    users = {str(key).strip().casefold(): str(value) for key, value in dict(auth.get("users", {})).items()}
    if not users and auth.get("username"):
        users[str(auth["username"]).strip().casefold()] = str(auth.get("password", ""))

    apply_login_theme()
    with st.container(key="login_card"):
        ui.login_header()
        with st.container(key="login_form_area"):
            with st.form("login_form"):
                email = st.text_input("Correo electronico", placeholder="nombre.apellido@forus.pe")
                password = st.text_input("Contrasena", type="password", placeholder="********")
                submitted = st.form_submit_button("Ingresar", type="primary", width="stretch")
        ui.login_note()
    ui.login_footer()

    if submitted:
        expected = users.get(email.strip().casefold())
        if expected and hmac.compare_digest(str(password), expected):
            st.session_state["authenticated"] = True
            st.session_state["auth_user"] = email.strip().casefold()
            st.rerun()
        st.error("Usuario o contrasena incorrectos.")
    return False


def reset_run(keep_config: bool = True) -> None:
    for key in ("payload", "report", "stock", "result", "stock_error"):
        st.session_state.pop(key, None)
    if not keep_config:
        st.session_state.pop("priority_bytes", None)


def current_step() -> int:
    if "result" in st.session_state:
        return 5
    if "stock" in st.session_state:
        return 4
    if "report" in st.session_state and not st.session_state["report"].has_errors:
        return 3
    if "payload" in st.session_state:
        return 2
    return 1


# ---------------------------------------------------------------------------
# Barra lateral
# ---------------------------------------------------------------------------
def render_sidebar(config, bq_ready: bool) -> str:
    ui.sidebar_brand()
    ui.sidebar_steps(current_step())

    st.sidebar.markdown('<p class="rcc-side-label">Prioridad de tiendas</p>', unsafe_allow_html=True)
    uploaded = st.sidebar.file_uploader(
        "Configuracion (.xlsx)",
        type=["xlsx"],
        key="priority_upload",
        help="Hojas: Prioridad, Tiendas, Parametros. La app nunca usa una prioridad escrita en codigo.",
    )
    if uploaded is not None:
        st.session_state["priority_bytes"] = uploaded.getvalue()

    st.sidebar.download_button(
        "Descargar plantilla",
        data=build_priority_bytes(),
        file_name="prioridad_tiendas.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        width="stretch",
    )

    if config.rules:
        ui.sidebar_card(
            "Configuracion activa",
            [
                f"Origen: <b>{config.source}</b>",
                f"Tiendas: <b>{config.store_count}</b> &nbsp;|&nbsp; Sitios: <b>{config.site_count}</b>",
                f"Estados: <b>{', '.join(config.target_statuses)}</b>",
                f"Excluir tienda origen: <b>{'SI' if config.flag('excluir_tienda_origen') else 'NO'}</b>",
            ],
        )
    else:
        ui.sidebar_card("Configuracion activa", ["<b>Sin lista de prioridad cargada.</b>"])

    st.sidebar.markdown('<p class="rcc-side-label">Fuente de stock</p>', unsafe_allow_html=True)
    options = ["BigQuery (solo lectura)", "Archivo de stock"]
    mode = st.sidebar.radio(
        "Fuente",
        options,
        index=0 if bq_ready else 1,
        label_visibility="collapsed",
        key="stock_mode",
    )

    if mode == options[0]:
        if bq_ready:
            table = resolve_stock_table(bigquery_secrets())
            ui.sidebar_card(
                "BigQuery",
                [
                    "Estado: <b>configurado</b>",
                    f"Tabla: <b>{table.split('.')[-1]}</b>",
                    "Modo: <b>solo lectura</b>",
                ],
            )
        else:
            ui.sidebar_card(
                "BigQuery",
                [
                    "Estado: <b>sin configurar</b>",
                    "Completa <b>.streamlit/secrets.toml</b> o usa un archivo de stock.",
                ],
            )
    else:
        stock_file = st.sidebar.file_uploader(
            "Stock (.xlsx / .csv)",
            type=["xlsx", "xls", "csv"],
            key="stock_upload",
            help="Columnas minimas: sku, cod_tienda, stock.",
        )
        if stock_file is not None:
            st.session_state["stock_file"] = (stock_file.getvalue(), stock_file.name)
        if st.session_state.get("stock_file"):
            ui.sidebar_card("Archivo de stock", [f"Cargado: <b>{st.session_state['stock_file'][1]}</b>"])

    st.sidebar.divider()
    if st.sidebar.button("Reiniciar proceso", width="stretch"):
        reset_run()
        st.rerun()

    if st.session_state.get("authenticated"):
        if st.sidebar.button("Cerrar sesion", width="stretch"):
            st.session_state.clear()
            st.rerun()
        st.sidebar.caption(f"Sesion: {st.session_state.get('auth_user', '')}")

    st.sidebar.caption(f"{settings.APP_NAME} v{settings.APP_VERSION}")
    return mode


# ---------------------------------------------------------------------------
# Pasos
# ---------------------------------------------------------------------------
def step_upload() -> None:
    ui.section("Paso 1", "Subir archivo de pedidos", "Formato de carga de reasignacion (.xls o .xlsx).")
    uploaded = st.file_uploader(
        "Arrastra el archivo o selecciona uno",
        type=["xls", "xlsx"],
        key="orders_upload",
        label_visibility="collapsed",
    )
    if uploaded is None:
        return

    signature = (uploaded.name, uploaded.size)
    if st.session_state.get("orders_signature") == signature and "payload" in st.session_state:
        return

    try:
        payload = excel_io.read_orders(uploaded.getvalue(), uploaded.name)
    except Exception as exc:
        ui.note("bad", "No se pudo leer el archivo", str(exc))
        return

    st.session_state["payload"] = payload
    st.session_state["orders_signature"] = signature
    for key in ("report", "stock", "result", "stock_error"):
        st.session_state.pop(key, None)
    st.rerun()


def available_statuses(payload) -> list[str]:
    """Estados presentes en el archivo, ordenados por frecuencia."""
    resolved = resolve_columns(payload.headers)
    column = resolved.get(settings.COL_STATUS)
    if not column:
        return []
    counts = payload.df[column].map(normalize_status).value_counts()
    return [status for status in counts.index.tolist() if status]


def ensure_status_selection(payload, config) -> None:
    """Fija la seleccion inicial de estados antes de dibujar nada.

    Tiene que correr antes que la barra lateral y la validacion: si se hiciera
    dentro del propio selector, la primera pasada validaria con los estados
    viejos y mostraria un error que ya no corresponde.
    """
    if "estados_objetivo_sel" in st.session_state:
        return
    found = available_statuses(payload)
    if not found:
        return
    coincidencias = [status for status in found if status in config.target_statuses]
    # Si el archivo no trae ninguno de los estados configurados, se preselecciona
    # el mas frecuente: es lo que el usuario venia a reasignar.
    st.session_state["estados_objetivo_sel"] = coincidencias or found[:1]


def render_status_picker(payload) -> None:
    """Selector de estados a reasignar, con lo que trae el archivo.

    Sin esto habria que editar la hoja 'Parametros' del Excel de configuracion
    cada vez que el sistema de origen cambia el nombre de un estado.
    """
    found = available_statuses(payload)
    if not found:
        return

    ui.section(
        "Paso 2",
        "Elegir que pedidos reasignar",
        "Marca los estados que la app debe intentar reasignar. El resto de las filas "
        "se conservan intactas en el archivo final.",
    )

    counts = payload.df[resolve_columns(payload.headers)[settings.COL_STATUS]].map(normalize_status).value_counts()
    st.multiselect(
        "Estados a reasignar",
        options=found,
        key="estados_objetivo_sel",
        format_func=lambda status: f"{status}  ({counts.get(status, 0)} filas)",
        help="Tambien puede fijarse en la hoja 'Parametros' de la configuracion de prioridad.",
    )


def step_validate(config) -> None:
    payload = st.session_state["payload"]
    ui.section(
        "Paso 2",
        "Validar estructura y reglas",
        f"{payload.source_name} • hoja '{payload.sheet_name}' • "
        f"{payload.n_rows:,} filas • {len(payload.headers)} columnas.".replace(",", " "),
    )

    report = validate(payload.df, payload.headers, config)
    st.session_state["report"] = report

    ui.kpi_grid(
        [
            ("Filas leidas", report.total_rows, "neutral", f"{len(report.columns)} columnas"),
            ("Pedidos a reasignar", report.target_rows, "", ", ".join(config.target_statuses)),
            ("Estados distintos", len(report.statuses), "", "Ver detalle abajo"),
            ("Alertas", len(report.warnings), "warn", "Revisar antes de continuar"),
            ("Errores", len(report.errors), "bad", "Bloquean el proceso"),
        ]
    )

    for note_text in payload.notes:
        ui.note("info", "Lectura del archivo", note_text)
    for issue in config.issues:
        ui.note("warn", "Configuracion de prioridad", issue)

    ui.validation_block(report)

    left, right = st.columns([1, 1])
    with left:
        with st.expander("Estados encontrados", expanded=True):
            statuses = pd.DataFrame(
                [
                    {
                        "Estado": status or "(vacio)",
                        "Filas": count,
                        "Se reasigna": "SI" if status in config.target_statuses else "NO",
                    }
                    for status, count in sorted(report.statuses.items(), key=lambda item: -item[1])
                ]
            )
            st.dataframe(statuses, width="stretch", hide_index=True)
    with right:
        with st.expander("Columnas reconocidas", expanded=False):
            mapping = pd.DataFrame(
                [
                    {"Campo del motor": key, "Columna del archivo": value}
                    for key, value in report.resolved.items()
                ]
            )
            st.dataframe(mapping, width="stretch", hide_index=True)

    with st.expander("Lista de prioridad activa", expanded=False):
        st.dataframe(priority_to_frame(config), width="stretch", hide_index=True, height=280)


def step_stock(config, mode: str) -> None:
    payload = st.session_state["payload"]
    report = st.session_state["report"]
    skus = engine.target_skus(payload.df, report.resolved, config)

    ui.section(
        "Paso 3",
        "Consultar stock disponible",
        f"{len(skus):,} SKU unicos a consultar. La consulta es de solo lectura: "
        "BigQuery nunca se modifica.".replace(",", " "),
    )

    if st.session_state.get("stock_error"):
        ui.note("bad", "Fallo la consulta de stock", st.session_state["stock_error"])

    columns = st.columns([1, 1, 2])
    launch = columns[0].button("Consultar stock", type="primary", width="stretch")

    if not launch:
        return

    st.session_state.pop("stock_error", None)
    include_central = config.flag("incluir_stock_bodega_central")

    try:
        with st.spinner("Consultando stock..."):
            if mode.startswith("BigQuery"):
                source = secrets_to_source(bigquery_secrets(), include_central)
                stock = source.fetch(skus)
            else:
                cached = st.session_state.get("stock_file")
                if not cached:
                    raise ValueError("Sube un archivo de stock en la barra lateral.")
                frame = excel_io.read_stock_file(cached[0], cached[1])
                stock = ManualStockSource(frame, include_central).fetch(skus)
    except Exception as exc:
        st.session_state["stock_error"] = str(exc)
        st.rerun()
        return

    st.session_state["stock"] = stock
    st.session_state.pop("result", None)
    st.rerun()


def step_reassign(config) -> None:
    payload = st.session_state["payload"]
    report = st.session_state["report"]
    stock = st.session_state["stock"]
    cutoff = stock_cutoff(stock)

    covered = stock["sku"].nunique() if not stock.empty else 0
    requested = len(engine.target_skus(payload.df, report.resolved, config))

    ui.section(
        "Paso 4",
        "Reasignar",
        "Recorre la lista de prioridad y descuenta el stock en memoria a medida que asigna.",
    )
    ui.kpi_grid(
        [
            ("SKU consultados", requested, "neutral", "Estados objetivo"),
            ("SKU con stock", covered, "ok" if covered else "warn", f"{requested - covered} sin stock en ninguna tienda"),
            ("Combinaciones SKU/tienda", len(stock), "", "Filas devueltas"),
            ("Unidades disponibles", int(stock["stock"].sum()) if not stock.empty else 0, "", "Antes de descuentos"),
            ("Fecha de corte", cutoff or "-", "neutral", "Ultimo cierre de stock"),
        ]
    )

    include_trace = st.checkbox(
        "Incluir columnas de trazabilidad en el Excel final",
        value=False,
        help=(
            "Agrega Reasig_Resultado, Reasig_Stock_Disponible, etc. "
            "Desactivalo si la plataforma destino solo acepta las columnas originales."
        ),
    )

    if st.button("Ejecutar reasignacion", type="primary", width="content"):
        with st.spinner("Reasignando..."):
            result = engine.reassign(
                df=payload.df,
                headers=payload.headers,
                resolved=report.resolved,
                config=config,
                stock_index=build_stock_index(stock),
                stock_cutoff=cutoff,
                include_trace=include_trace,
            )
        st.session_state["result"] = result
        st.rerun()


def step_review(config) -> None:
    payload = st.session_state["payload"]
    result: engine.ReassignmentResult = st.session_state["result"]
    kpis = result.kpis

    ui.section("Paso 5", "Revisar resultado", "KPIs de la corrida y detalle pedido por pedido.")
    ui.kpi_from_result(kpis)

    if kpis.sin_stock:
        ui.note(
            "warn",
            f"{kpis.sin_stock} pedidos quedaron como '{settings.RESULT_NO_OPTION}'",
            "Revisa la pestana 'Sin opcion' para ver el motivo exacto de cada uno.",
        )
    if kpis.errores:
        ui.note("bad", f"{kpis.errores} filas con error", "Filas sin SKU legible: no se pudo consultar stock.")
    if not kpis.sin_stock and not kpis.errores and kpis.pedidos_a_reasignar:
        ui.note("ok", "Todos los pedidos fueron reasignados", "El archivo esta listo para descargar.")

    preview = result.preview
    tabs = st.tabs(["Vista previa", "Reasignados", "Sin opcion", "Por tienda", "Validacion"])

    with tabs[0]:
        search = st.text_input("Buscar por pedido, SKU o tienda", key="preview_search")
        view = preview
        if search.strip():
            needle = search.strip().lower()
            mask = view.apply(
                lambda row: needle in " ".join(str(value).lower() for value in row.values), axis=1
            )
            view = view[mask]
        st.dataframe(view, width="stretch", hide_index=True, height=430)
        st.caption(f"{len(view):,} de {len(preview):,} filas.".replace(",", " "))

    with tabs[1]:
        done = result.detail[result.detail["Resultado"].isin([settings.RESULT_REASSIGNED, engine.RESULT_PARTIAL])]
        st.dataframe(done, width="stretch", hide_index=True, height=430)

    with tabs[2]:
        missing = result.detail[result.detail["Resultado"] != settings.RESULT_REASSIGNED]
        missing = missing[missing["Resultado"] != engine.RESULT_PARTIAL]
        st.dataframe(missing, width="stretch", hide_index=True, height=430)

    with tabs[3]:
        if result.store_summary.empty:
            st.info("Ninguna tienda recibio unidades en esta corrida.")
        else:
            st.dataframe(result.store_summary, width="stretch", hide_index=True, height=430)
            st.bar_chart(
                result.store_summary.set_index("nom_tienda")["unidades_reasignadas"],
                width="stretch",
            )

    with tabs[4]:
        st.dataframe(st.session_state["report"].to_frame(), width="stretch", hide_index=True)

    # --- descarga ----------------------------------------------------------
    ui.section(
        "Paso 6",
        "Descargar Excel final",
        f"Mantiene las {len(payload.headers)} columnas originales y escribe la tienda en "
        f"'{result.output_column}'.",
    )

    stamp = datetime.now().strftime("%Y%m%d_%H%M")
    with st.spinner("Generando archivos..."):
        final_bytes = excel_io.write_orders(
            result.output_df, result.output_headers, sheet_name=payload.sheet_name
        )
        report_bytes = excel_io.write_report(
            {
                "KPIs": kpis.to_frame(),
                "Detalle": result.detail,
                "Por tienda": result.store_summary,
                "Validacion": st.session_state["report"].to_frame(),
                "Prioridad usada": priority_to_frame(config),
            }
        )

    left, right = st.columns(2)
    left.download_button(
        "Descargar Excel de carga",
        data=final_bytes,
        file_name=f"reasignacion_{stamp}.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        type="primary",
        width="stretch",
    )
    right.download_button(
        "Descargar reporte operativo",
        data=report_bytes,
        file_name=f"reporte_reasignacion_{stamp}.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        width="stretch",
    )

    ui.note(
        "info",
        "Que contiene cada archivo",
        "El Excel de carga conserva el formato de origen y es el que se sube a la plataforma. "
        "El reporte operativo es interno: KPIs, detalle por pedido, uso por tienda y validaciones.",
    )


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main() -> None:
    # El intro pinta su propio tema (fondo oscuro, sin sidebar); el tema
    # principal solo se aplica una vez que hay sesion.
    if not require_login():
        return
    apply_theme()

    config = load_priority(st.session_state.get("priority_bytes"))
    payload = st.session_state.get("payload")
    if payload is not None:
        ensure_status_selection(payload, config)
    seleccion = st.session_state.get("estados_objetivo_sel")
    if seleccion:
        config.params["estados_objetivo"] = ",".join(seleccion)
    bq_secrets = bigquery_secrets()
    bq_ready = is_bigquery_configured(bq_secrets)
    mode = render_sidebar(config, bq_ready)

    step = current_step()
    chips: list[tuple[str, str]] = [
        (f"Paso {step} de 6", ""),
        ("BigQuery conectado" if bq_ready else "BigQuery sin configurar", "ok" if bq_ready else "warn"),
        (f"{config.store_count} tiendas en prioridad" if config.rules else "Sin prioridad cargada",
         "ok" if config.rules else "warn"),
        ("Solo lectura de stock", "ok"),
    ]
    ui.hero(
        "Reasignacion de pedidos sin stock",
        "Sube el archivo de pedidos, la app identifica los estados "
        f"{' y '.join(config.target_statuses)}, consulta el stock disponible y reasigna "
        "cada pedido a la tienda de mayor prioridad que pueda despacharlo.",
        chips,
    )

    step_upload()
    if "payload" not in st.session_state:
        ui.note(
            "info",
            "Esperando el archivo de pedidos",
            "Se aceptan .xls y .xlsx. Se lee la primera hoja del libro y se conservan todas las columnas.",
        )
        return

    render_status_picker(st.session_state["payload"])
    if not st.session_state.get("estados_objetivo_sel"):
        ui.note(
            "warn",
            "Selecciona al menos un estado",
            "Sin estados marcados no hay pedidos que reasignar.",
        )
        return
    step_validate(config)
    report = st.session_state["report"]
    if report.has_errors:
        ui.note("bad", "Corrige los errores para continuar", "El proceso se detiene en el paso de validacion.")
        return

    step_stock(config, mode)
    if "stock" not in st.session_state:
        return

    step_reassign(config)
    if "result" not in st.session_state:
        return

    step_review(config)


if __name__ == "__main__":
    main()
