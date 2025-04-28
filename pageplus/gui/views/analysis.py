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


def show_analysis(cli_bridge):
    """Display analytics page with file analysis options."""
    st.title("🔍 Analytics")
    
    if not st.session_state.loaded_files:
        st.warning("Please load files first in the 'Input' page.")
        return
    
    # Analytics options
    st.subheader("Analysis Options")
    
    # Select analysis type
    analysis_type = st.selectbox(
        "Select Analysis Type",
        ["Text Statistics", "Confidences"]
    ) 
    if analysis_type == "Text Statistics":
        show_text_statistics(cli_bridge)
    elif analysis_type == "Confidences":
        show_confidences(cli_bridge)


def show_text_statistics(cli_bridge):
    """Display text statistics analysis."""
    st.subheader("Text Statistics")
    if st.button("Run Text Analysis"):
        with st.spinner("Analyzing text..."):
            try:
                results = cli_bridge.analyse_statistics(
                    files=st.session_state.loaded_files)
                st.success("Analysis completed!")
                st.dataframe(results)
            except Exception as e:
                st.error(f"Error during analysis: {str(e)}")


def show_confidences(cli_bridge):
    """Display confidences."""
    st.subheader("Confidences")
    if st.button("Run Confidence Analysis"):
        with st.spinner("Analyzing text..."):
            try:
                results = cli_bridge.analyse_confidences(
                    files=st.session_state.loaded_files)
                st.success("Analysis completed!")
                df = rich_table_to_dataframe(results)
                st.dataframe(df)
            except Exception as e:
                st.error(f"Error during analysis: {str(e)}") 