import streamlit as st
from pathlib import Path
from typing import List, Optional
from pageplus.gui.utils.picker import (
    select_directory, select_files, get_loaded_workspace_dir
)

from pageplus.cli.export import ReadingOrderMode


def show_export(bridge):
    """Display export page."""
    st.title("📤 Export")
    
    # Check if files are loaded
    if not st.session_state.loaded_files:
        st.warning("Please load files first.")
        return

    # Select export format
    format_options = ["DSV", "ALTO", "Fulltext", "PDF"]
    export_format = st.selectbox(
        "Select Export Format",
        options=format_options,
        index=0
    )

    # Select output directory
    st.write("Output directory: The default is to create a new folder in the input directory.")
    if st.button("Select Output Directory"):
        selected_paths = select_directory()
        if selected_paths:
            st.session_state.export_dir = selected_paths
        elif selected_paths is not None:
            st.info("Directory selection cancelled.")

    if 'export_dir' in st.session_state:
        st.text_input(
            "Selected Output Directory",
            value=st.session_state.export_dir,
            disabled=True,
            label_visibility="visible"
        )

    # Format-specific settings
    with st.expander("Export Settings", expanded=True):
        if export_format == "DSV":
            delimiter = st.selectbox(
                "Delimiter",
                options=["\t", ",", ";", "|"],
                index=0
            )
            dehyphenate = st.checkbox("Dehyphenate Text", value=False)
            open_folder = st.checkbox("Open Folder After Export", value=True)

        elif export_format == "ALTO":
            st.info("Converts PAGE XML files to ALTO XML files.")
            st.info("No additional settings required for ALTO export.")

        elif export_format == "Fulltext":
            dehyphenate = st.checkbox("Dehyphenate Text", value=False)
            ro = st.checkbox("Use Reading Order", value=False)
            ro_mode = st.selectbox(
                "Reading Order Mode",
                options=["auto", "reading_order", "document"],
                index=0
            )
            open_folder = st.checkbox("Open Folder After Export", value=True)

        elif export_format == "PDF":
            # Input selection
            input_type = st.radio(
                "Select Input Type",
                ["Directory", "Files"],
                horizontal=True
            )
            
            if input_type == "Directory":
                st.write("Select Image Extensions to Search")
                selected_extensions = st.multiselect(
                    "Image Extensions",
                    options=['.jpg', '.jpeg', '.png', '.bmp', '.tiff', '.tif'],
                    default=['.jpg', '.jpeg', '.png', '.tiff', '.tif']
                )
                if st.button("Select Image Directory", 
                           key="select_pdf_image_dir_button"):
                    selected_dir = select_directory(
                        initial_dir=get_loaded_workspace_dir()
                    )
                    if selected_dir:
                        if selected_extensions:
                            selected_files = [
                                str(f) for f in Path(selected_dir).glob('*')
                                if f.suffix.lower() in selected_extensions
                            ]
                            if not selected_files:
                                st.warning(
                                    "No image files found in selected directory."
                                )
                            else:
                                st.session_state.pdf_input = {
                                    "type": "directory",
                                    "path": selected_dir,
                                    "files": selected_files,
                                    "extensions": selected_extensions
                                }
                                st.success(
                                    f"Found {len(selected_files)} image files."
                                )
                                st.rerun()
                        else:
                            st.warning(
                                "Please select at least one image extension."
                            )
            else:  # Files
                if st.button("Select Image Files", 
                           key="select_pdf_image_files_button"):
                    selected_files = select_files(
                        initial_dir=get_loaded_workspace_dir(),
                        filetypes=[
                            ("All image files", 
                             "*.jpg *.jpeg *.png *.bmp *.tiff *.tif"),
                            ("JPEG files", "*.jpg *.jpeg"),
                            ("PNG files", "*.png"),
                            ("BMP files", "*.bmp"),
                            ("TIFF files", "*.tiff *.tif")
                        ]
                    )
                    if selected_files:
                        st.session_state.pdf_input = {
                            "type": "files",
                            "files": selected_files
                        }
                        st.success(f"Selected {len(selected_files)} files.")
                        st.rerun()

            # Display selected input info
            if 'pdf_input' in st.session_state:
                pdf_input = st.session_state.pdf_input
                st.info(f"Selected: {pdf_input['type']} - "
                       f"{len(pdf_input['files'])} files")

            dpi = st.number_input("DPI", min_value=72, max_value=1200, value=None)
            draw_options = ["baseline", "border", "textline", "textregion"]
            draw = st.multiselect(
                "Draw Elements",
                options=draw_options,
                default=[]
            )
            output_filename = st.text_input(
                "Output Filename",
                value="PagePlus"
            )

    # Export button
    if st.button("Export"):
        if 'export_dir' not in st.session_state:
            st.session_state.export_dir = None
        try:
            # Prepare export parameters
            kwargs = {}
            if export_format == "DSV":
                kwargs.update({
                    "delimiter": delimiter,
                    "dehyphenate": dehyphenate,
                    "open_folder": open_folder,
                })
            elif export_format == "ALTO":
                # No additional parameters needed for ALTO export
                pass
            elif export_format == "Fulltext":
                kwargs.update({
                    "dehyphenate": dehyphenate,
                    "ro": ro,
                    "ro_mode": ro_mode,
                    "open_folder": open_folder,
                })
            elif export_format == "PDF":
                if 'pdf_input' not in st.session_state:
                    st.error("Please select image files or directory first.")
                    return
                
                pdf_input = st.session_state.pdf_input
                if pdf_input['type'] == 'directory':
                    image_folder = pdf_input['path']
                else:
                    # For files, we need to extract the directory from the first file
                    image_folder = str(Path(pdf_input['files'][0]).parent)
                
                kwargs.update({
                    "images": pdf_input['files'],
                    "max_resolution": None if dpi == 0 else dpi,
                    "draw": draw,
                    "output_filename": output_filename,
                })

            # Perform export
            exported_files = bridge.export_files(
                    files=st.session_state.loaded_files,
                    format=export_format,
                    output_dir=Path(st.session_state.export_dir) if st.session_state.export_dir else None,
                    **kwargs
                )
            st.success(f"Files exported successfully!")

        except Exception as e:
            st.error(f"Error during export: {str(e)}")


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
                    format="DSV",
                    delimiter=delimiter,
                    dehyphenate=dehyphenate,
                    output_dir=st.session_state.export_dir if st.session_state.export_dir else None
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
                    format="ALTO",
                    output_dir=st.session_state.export_dir if st.session_state.export_dir else None
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
        [ReadingOrderMode.auto.name, ReadingOrderMode.document.name, ReadingOrderMode.rog.name]
    )
    
    if st.button("Export to Fulltext"):
        with st.spinner("Exporting to Fulltext..."):
            try:
                results = cli_bridge.export_files(
                    files=st.session_state.loaded_files,
                    output_dir=st.session_state.export_dir if st.session_state.export_dir else None,
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
    image_folder = st.text_input(
        "Image Folder",
        value="images",
        label_visibility="visible"
    )
    dpi = st.number_input("DPI", value=400, min_value=72, max_value=1200)
    
    if st.button("Export to PDF"):
        with st.spinner("Exporting to PDF..."):
            try:
                results = cli_bridge.export_files(
                    files=st.session_state.loaded_files,
                    format="PDF",
                    output_dir=st.session_state.export_dir if st.session_state.export_dir else None,
                    images=st.session_state.pdf_input['files'],
                )
                st.success("Export completed!")
                st.write(f"Exported files: {results}")
            except Exception as e:
                st.error(f"Error during export: {str(e)}") 