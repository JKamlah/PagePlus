import streamlit as st
from rich.table import Table
import pandas as pd
import re

from pageplus.gui.utils.output_transform import (
    strip_rich_text,
    rich_table_to_dataframe
)

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
        ["Text Statistics", "Confidences", "Tags"]
    )
    
    if analysis_type == "Text Statistics":
        show_text_statistics(cli_bridge)
    elif analysis_type == "Confidences":
        show_confidences(cli_bridge)
    elif analysis_type == "Tags":
        show_tags(cli_bridge)

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


def show_tags(cli_bridge):
    """Display tag analysis options and results."""
    st.subheader("Tags")
    
    # Initialize session state for results if not exists
    if 'tag_analysis_results' not in st.session_state:
        st.session_state.tag_analysis_results = None
    
    if st.button("Run Tags Analysis"):
        with st.spinner("Analyzing tags..."):
            try:
                results = cli_bridge.analyse_tags(
                    files=st.session_state.loaded_files)
                st.success("Analysis completed!")
                
                # Convert results to DataFrame if it's not already
                if not isinstance(results, pd.DataFrame):
                    results = pd.DataFrame(results)
                
                # Store results in session state
                st.session_state.tag_analysis_results = results
            except Exception as e:
                st.error(f"Error during analysis: {str(e)}")
    
    # Display results if they exist in session state
    if st.session_state.tag_analysis_results is not None:
        results = st.session_state.tag_analysis_results
        
        # Add row filter
        if not results.empty:
            # Get unique rows for selection
            row_options = results.index.unique()
            selected_row = st.selectbox(
                "Select row to filter",
                row_options,
                format_func=lambda x: str(x)
            )
            
            # Filter columns for selected row
            row_data = results.loc[selected_row]
            non_none_columns = row_data[row_data.notna()].index.tolist()
            
            # Display filtered dataframe
            st.write("Showing only columns with values for selected row:")
            filtered_df = results[non_none_columns]
            st.dataframe(filtered_df)
        else:
            st.dataframe(results)