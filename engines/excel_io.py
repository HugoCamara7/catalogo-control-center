"""Motor de lectura y generacion de Excel.

Sin dependencias de Streamlit."""

import io

import pandas as pd

from engines.normalize import clean_value


def read_excel(uploaded_file):
    return pd.read_excel(uploaded_file, dtype=object).dropna(how="all")


def dataframe_to_excel_bytes(sheets):
    buffer = io.BytesIO()
    with pd.ExcelWriter(buffer, engine="openpyxl") as writer:
        for sheet_name, df in sheets.items():
            safe_name = sheet_name[:31]
            df = repair_mojibake_dataframe(df)
            df.to_excel(writer, index=False, sheet_name=safe_name)
        for sheet in writer.book.worksheets:
            sheet.freeze_panes = "A2"
            for column_cells in sheet.columns:
                sheet.column_dimensions[column_cells[0].column_letter].width = 22
    buffer.seek(0)
    return buffer


def columbia_to_excel_bytes(matrixify_df, summary_df, issues_df, type_warnings_df=None, skipped_df=None, sial_df=None, centry_df=None, centry_issues_df=None):
    matrixify_df = repair_mojibake_dataframe(coalesce_duplicate_columns(matrixify_df))
    summary_df = repair_mojibake_dataframe(coalesce_duplicate_columns(summary_df))
    issues_df = repair_mojibake_dataframe(coalesce_duplicate_columns(issues_df))
    type_warnings_df = repair_mojibake_dataframe(coalesce_duplicate_columns(type_warnings_df))
    skipped_df = repair_mojibake_dataframe(coalesce_duplicate_columns(skipped_df))
    sial_df = repair_mojibake_dataframe(coalesce_duplicate_columns(sial_df))
    centry_df = repair_mojibake_dataframe(coalesce_duplicate_columns(centry_df))
    centry_issues_df = repair_mojibake_dataframe(coalesce_duplicate_columns(centry_issues_df))
    buffer = io.BytesIO()
    with pd.ExcelWriter(buffer, engine="openpyxl") as writer:
        matrixify_df.to_excel(writer, index=False, sheet_name="Products")
        summary_df.to_excel(writer, index=False, sheet_name="Resumen")
        issues_df.to_excel(writer, index=False, sheet_name="Revision")
        if sial_df is not None:
            sial_df.to_excel(writer, index=False, sheet_name="Carga Sial")
        if centry_df is not None:
            centry_df.to_excel(writer, index=False, sheet_name="Centry")
            centry_review_df = centry_issues_df if centry_issues_df is not None else pd.DataFrame(columns=["Mod-Col", "Problema"])
            centry_review_df.to_excel(writer, index=False, sheet_name="Revision Centry")
        if type_warnings_df is not None:
            type_warnings_df.to_excel(writer, index=False, sheet_name="Tipos nuevos")
        if skipped_df is not None:
            skipped_df.to_excel(writer, index=False, sheet_name="Omitidos sin cambios")

        for sheet in writer.book.worksheets:
            sheet.freeze_panes = "A2"
            for column_cells in sheet.columns:
                sheet.column_dimensions[column_cells[0].column_letter].width = 18

    buffer.seek(0)
    return buffer


def update_to_excel_bytes(matrixify_df, issues_df):
    matrixify_df = repair_mojibake_dataframe(matrixify_df)
    issues_df = repair_mojibake_dataframe(issues_df)
    buffer = io.BytesIO()
    with pd.ExcelWriter(buffer, engine="openpyxl") as writer:
        matrixify_df.to_excel(writer, index=False, sheet_name="Products")
        issues_df.to_excel(writer, index=False, sheet_name="Revision")
        for sheet in writer.book.worksheets:
            sheet.freeze_panes = "A2"
            for column_cells in sheet.columns:
                sheet.column_dimensions[column_cells[0].column_letter].width = 22
    buffer.seek(0)
    return buffer
