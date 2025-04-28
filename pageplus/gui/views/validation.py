import streamlit as st
from rich.table import Table
import pandas as pd
import re


def strip_rich_text(text: str) -> str:
    """Strip rich text formatting from a string."""
    pattern = r"\[(\w+)\](.*?)\[/\1\]"
    matches = re.findall(pattern, text)
    if matches:
        return " ".join(match[1] for match in matches)
    return text  # return original if no matches


def rich_table_to_dataframe(rich_table: Table) -> pd.DataFrame:
    """Convert a rich table to a pandas DataFrame."""
    headers = [strip_rich_text(col.header) for col in rich_table.columns]
    column_cells = []
    for col in rich_table.columns:
        column_cells.append([strip_rich_text(cell) for cell in col._cells])
    data_rows = list(map(list, zip(*column_cells))) if column_cells else []
    return pd.DataFrame(data_rows, columns=headers)


def show_validation(cli_bridge):
    """Display validation page with validation options."""
    st.title("✅ Validation")
    
    if not st.session_state.loaded_files:
        st.warning("Please load files first in the 'Input' page.")
        return
    
    # Validation options
    st.subheader("Validation Options")
    
    # Select validation type
    validation_type = st.selectbox(
        "Select Validation Type",
        ["Text Validation", "Layout Validation"]
    )
    
    if validation_type == "Text Validation":
        show_text_validation(cli_bridge)
    elif validation_type == "Layout Validation":
        show_layout_validation(cli_bridge)


def show_text_validation(cli_bridge):
    """Display text validation options and results."""
    st.subheader("Text Validation")
    
    # Text validation options
    check_spelling = st.checkbox("Check Spelling", value=True)
    check_grammar = st.checkbox("Check Grammar", value=True)
    check_consistency = st.checkbox("Check Consistency", value=True)
    
    if st.button("Run Text Validation"):
        with st.spinner("Validating text..."):
            try:
                results = cli_bridge.validate_files(
                    files=st.session_state.loaded_files
                )
                st.success("Validation completed!")
                st.dataframe(results)
            except Exception as e:
                st.error(f"Error during validation: {str(e)}")


def show_layout_validation(cli_bridge):
    """Display layout validation options and results."""
    st.subheader("Layout Validation")
    
    # Layout validation options
    check_margins = st.checkbox("Check Margins", value=True)
    check_spacing = st.checkbox("Check Spacing", value=True)
    check_alignment = st.checkbox("Check Alignment", value=True)
    
    if st.button("Run Layout Validation"):
        with st.spinner("Validating layout..."):
            try:
                results = cli_bridge.validate_files(
                    files=st.session_state.loaded_files
                )
                st.success("Validation completed!")
                st.dataframe(results)
            except Exception as e:
                st.error(f"Error during validation: {str(e)}") 