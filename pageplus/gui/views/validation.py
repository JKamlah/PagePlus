import re

import pandas as pd
import streamlit as st
from rich.table import Table

from pageplus.gui.cli_bridges.validation import ValidationBridge


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


def show_validation(bridge: ValidationBridge) -> None:
    """Show validation view."""
    if not st.session_state.loaded_files:
        st.warning("Please load files first in the 'Input' page.")
        return

    st.title("Validation")

    # Info text about validation
    with st.expander("About Validation", expanded=False):
        st.info("""
        This validation tool checks your PageXML files for various issues:

        - **Missing Baseline**: Text lines without baseline coordinates
        - **Single Point Baseline**: Baselines with only one point
        - **Baseline Outside Region**: Baselines extending beyond text region
        - **Partial Baseline Outside**: Some baseline points outside text region
        - **Empty Text**: Text lines or regions without content
        - **Empty Region**: Regions without any text content
        - **Insufficient Coordinates**: Elements with too few coordinate points
        - **Polygon Self-Intersection**: Invalid polygon shapes
        - **Invalid Region Polygon**: Regions with invalid polygon structure
        - **Outside Parent Region**: Elements outside their parent region
        - **Validation Error**: General validation errors
        """)

    # Get available files from session state
    selected_files = [str(f) for f in st.session_state.loaded_files]

    # Initialize validation results in session state if not present
    if 'validation_results' not in st.session_state:
        st.session_state.validation_results = None

    if st.button("Run Validation"):
        with st.spinner("Running validation..."):
            st.session_state.validation_results = bridge.validate_files(
                selected_files)

    # Show results and filters if validation has been run
    if st.session_state.validation_results is not None:
        result = st.session_state.validation_results

        if not result.empty:
            # Get unique filenames and validation types from results
            available_filenames = sorted(result['Filename'].unique())
            available_types = sorted(result['Validation Type'].unique())

            # Add filters after results are available
            st.subheader("Filter Results")

            # Create two columns for filters
            col1, col2 = st.columns(2)

            with col1:
                # Filename filter
                selected_filename = st.selectbox(
                    "Select file to display",
                    options=["All Files"] + available_filenames,
                    index=0
                )

            with col2:
                # Validation type selection
                selected_types = st.multiselect(
                    "Select validation types to display",
                    available_types,
                    default=available_types
                )

            # Filter results by selected filename and validation types
            filtered_result = result
            if selected_filename != "All Files":
                filtered_result = filtered_result[
                    filtered_result['Filename'] == selected_filename
                ]
            if selected_types:
                filtered_result = filtered_result[
                    filtered_result['Validation Type'].isin(selected_types)
                ]

            st.dataframe(filtered_result)
            st.success(f"Found {len(filtered_result)} validation results.")
        else:
            st.error("No validation results found.")
