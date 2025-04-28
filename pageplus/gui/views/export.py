import streamlit as st
from pathlib import Path


def show_export(cli_bridge):
    """Display export page with export options."""
    st.title("📤 Export")
    
    if not st.session_state.loaded_files:
        st.warning("Please load files first in the 'Input' page.")
        return
    
    # Export options
    st.subheader("Export Options")
    
    # Select export format
    export_format = st.selectbox(
        "Select Export Format",
        ["DSV", "ALTO", "Fulltext", "PDF"]
    )
    
    # Export options based on format
    if export_format == "DSV":
        show_dsv_export(cli_bridge)
    elif export_format == "ALTO":
        show_alto_export(cli_bridge)
    elif export_format == "Fulltext":
        show_fulltext_export(cli_bridge)
    elif export_format == "PDF":
        show_pdf_export(cli_bridge)


def show_dsv_export(cli_bridge):
    """Display DSV export options and results."""
    st.subheader("DSV Export")
    
    # DSV options
    delimiter = st.selectbox("Delimiter", ["Tab", "Comma", "Semicolon"])
    dehyphenate = st.checkbox("Dehyphenate", value=False)
    
    if st.button("Export to DSV"):
        with st.spinner("Exporting to DSV..."):
            try:
                results = cli_bridge.export_files(
                    files=st.session_state.loaded_files,
                    format="dsv",
                    delimiter=delimiter,
                    dehyphenate=dehyphenate
                )
                st.success("Export completed!")
                st.write(f"Exported files: {results}")
            except Exception as e:
                st.error(f"Error during export: {str(e)}")


def show_alto_export(cli_bridge):
    """Display ALTO export options and results."""
    st.subheader("ALTO Export")
    
    if st.button("Export to ALTO"):
        with st.spinner("Exporting to ALTO..."):
            try:
                results = cli_bridge.export_files(
                    files=st.session_state.loaded_files,
                    format="alto"
                )
                st.success("Export completed!")
                st.write(f"Exported files: {results}")
            except Exception as e:
                st.error(f"Error during export: {str(e)}")


def show_fulltext_export(cli_bridge):
    """Display Fulltext export options and results."""
    st.subheader("Fulltext Export")
    
    # Fulltext options
    dehyphenate = st.checkbox("Dehyphenate", value=False)
    ro = st.checkbox("Reading Order", value=False)
    ro_mode = st.selectbox(
        "Reading Order Mode",
        ["auto", "left-to-right", "right-to-left", "top-to-bottom"]
    )
    
    if st.button("Export to Fulltext"):
        with st.spinner("Exporting to Fulltext..."):
            try:
                results = cli_bridge.export_files(
                    files=st.session_state.loaded_files,
                    format="fulltext",
                    dehyphenate=dehyphenate,
                    ro=ro,
                    ro_mode=ro_mode
                )
                st.success("Export completed!")
                st.write(f"Exported files: {results}")
            except Exception as e:
                st.error(f"Error during export: {str(e)}")


def show_pdf_export(cli_bridge):
    """Display PDF export options and results."""
    st.subheader("PDF Export")
    
    # PDF options
    image_folder = st.text_input("Image Folder", value="images")
    same_names = st.checkbox("Use Same Names", value=True)
    image_extension = st.selectbox("Image Extension", [".jpg", ".png", ".tif"])
    dpi = st.number_input("DPI", value=400, min_value=72, max_value=1200)
    
    if st.button("Export to PDF"):
        with st.spinner("Exporting to PDF..."):
            try:
                results = cli_bridge.export_files(
                    files=st.session_state.loaded_files,
                    format="pdf",
                    image_folder=image_folder,
                    same_names=same_names,
                    image_extension=image_extension,
                    dpi=dpi
                )
                st.success("Export completed!")
                st.write(f"Exported files: {results}")
            except Exception as e:
                st.error(f"Error during export: {str(e)}") 