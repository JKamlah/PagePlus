from pathlib import Path
from typing import List
import json
import logging
import subprocess
import sys

import streamlit as st

from pageplus.cli.export import ReadingOrderMode
from pageplus.gui.utils.picker import pick_directory
from pageplus.gui.views.load_files import get_loaded_workspace_dir
from pageplus.models.page import Page
from pageplus.utils.guidelines.lib.settings import load_profiles
from pageplus.utils.constants import GUIDELINES_DIR


def get_mapping_profiles():
    """Load mapping profiles from the JSON file."""
    try:
        mappings_path = GUIDELINES_DIR / "profiles" / "mappings.json"
        mappings = load_profiles(mappings_path.as_posix())
        return list(mappings.keys())
    except Exception:
        return []


def _run_picker_script(command: List[str]) -> List[str]:
    """Run the picker script as a subprocess and return the output."""
    try:
        process = subprocess.run(
            command,
            capture_output=True,
            text=True,
            check=True
        )
        # The script prints the selected paths as a JSON string to stdout
        selected_paths = json.loads(process.stdout.strip())
        return selected_paths
    except subprocess.CalledProcessError as e:
        logging.error(f"Picker script failed: {e.stderr}")
        st.error(f"File picker failed: {e.stderr}")
    except json.JSONDecodeError:
        logging.error("Picker script returned invalid data.")
        st.error("File picker returned invalid data.")
    except Exception as e:
        logging.error(f"An unexpected error occurred with the picker: {e}")
        st.error(f"An unexpected error occurred: {e}")
    return []


def pick_files(initial_dir: str = None, filetypes: List = None) -> List[str]:
    """Use a subprocess to open a native file picker."""
    # Note: The filetypes argument is not yet passed to the subprocess picker.
    # This would require adding support for it in picker.py.
    picker_script_path = Path(__file__).parent.parent / "utils" / "picker.py"
    command = [sys.executable, str(picker_script_path), "--files"]
    if initial_dir:
        command.extend(["--initial-dir", str(initial_dir)])
    return _run_picker_script(command)


def show_export(bridge):
    """Display export page."""
    st.title("📤 Export")

    # Check if files are loaded
    if not st.session_state.loaded_files:
        st.warning("Please load files first.")
        return

    # Select output directory
    st.write(
        "Output directory: The default is to create a new folder in the input directory.")
    if st.button("Select Output Directory"):
        selected_paths = pick_directory(initial_dir=get_loaded_workspace_dir())
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
    
    mapping_profiles = get_mapping_profiles()
    selected_profile = st.selectbox(
        "Select a mapping profile (optional)",
        options=["None"] + mapping_profiles,
        index=0
    )

    # Tag filtering option
    if "export_available_tags" not in st.session_state:
        st.session_state.export_available_tags = []
    if "export_selected_tags" not in st.session_state:
        st.session_state.export_selected_tags = []

    c_tag1, c_tag2 = st.columns([1, 4])
    with c_tag1:
        if st.button("Update Tags", help="Scan loaded files to show all structure tags in a list view"):
            all_tags = set()
            for f in st.session_state.loaded_files:
                try:
                    all_tags.update(Page(Path(f)).get_tags(levels=['TextRegion', 'Textline', 'TableRegion']))
                except Exception:
                    pass
            cleaned_tags = sorted([t for t in all_tags if t and t.strip()])
            st.session_state.export_available_tags = cleaned_tags
            st.session_state.export_selected_tags = list(cleaned_tags)
            st.rerun()

    excluded_tags = []
    if st.session_state.export_available_tags:
        with c_tag2:
            st.caption("Remove tags with 'x' that you do not want in the export (e.g. 'header', 'footer'):")
        selected_tags = st.multiselect(
            "Tags to Export",
            options=st.session_state.export_available_tags,
            default=st.session_state.export_selected_tags,
            key="export_tags_multiselect",
            help="Active tags for export. Click 'x' on any tag to exclude it."
        )
        excluded_tags = [t for t in st.session_state.export_available_tags if t not in selected_tags]
        if excluded_tags:
            st.info(f"🚫 Excluded from export: {', '.join(excluded_tags)}")
    else:
        with c_tag2:
            st.caption("Press 'Update Tags' to scan loaded files for structure tags to include/exclude (e.g. 'header', 'footer').")

    tab_dsv, tab_alto, tab_fulltext, tab_markdown, tab_pdf, tab_tei = st.tabs(["💾 DSV", "💾 ALTO", "📝 Fulltext", "📝 Markdown", "📕 PDF", "💾 TEI"])

    with tab_tei:
        st.header("TEI Export")
        st.info("Converts PAGE XML files to TEI XML files.")
        
        tei_format = st.selectbox(
            "TEI Format",
            options=["fsl"],
            key="tab_tei_format"
        )
        
        if tei_format == "fsl":
            werkteil = st.text_input("Werkteil", value="Grammatik", key="tab_tei_werkteil")
            editor = st.text_input("Editorname", value="", key="tab_tei_editor", help="Johann Kirchmaier (empty default)")
            who = st.text_input("Bearbeiter-Abkürzung (who)", value="", key="tab_tei_who", help="e.g. lisa")
            status = st.selectbox(
                "Status",
                options=["Work in Progress", "Done"],
                index=0,
                key="tab_tei_status"
            )
            open_folder = st.checkbox("Open Folder After Export", value=True, key="tab_tei_open_folder")
            if st.button("Export to TEI"):
                if 'export_dir' not in st.session_state:
                    st.session_state.export_dir = None
                try:
                    status_val = "work_in_progress" if status == "Work in Progress" else "done"
                    kwargs = {
                        "werkteil": werkteil,
                        "editor": editor,
                        "who": who,
                        "status": status_val,
                        "open_folder": open_folder,
                        "mapping_profile": selected_profile if selected_profile != "None" else None,
                        "exclude_tags": excluded_tags if excluded_tags else None,
                        "tei_format": "fsl"
                    }
                    bridge.export_files(
                        files=st.session_state.loaded_files, format="TEI", output_dir=Path(
                            st.session_state.export_dir) if st.session_state.export_dir else None, **kwargs)
                    st.success("Files exported successfully!")
                except Exception as e:
                    st.error(f"Error during export: {str(e)}")

    with tab_dsv:
        st.header("DSV Export")
        delimiter = st.selectbox(
            "Delimiter",
            options=["\t", ",", ";", "|"],
            index=0
        )
        dehyphenate = st.checkbox("Dehyphenate Text", value=False)
        open_folder = st.checkbox("Open Folder After Export", value=True)
        if st.button("Export to DSV"):
            if 'export_dir' not in st.session_state:
                st.session_state.export_dir = None
            try:
                kwargs = {
                    "delimiter": delimiter,
                    "dehyphenate": dehyphenate,
                    "open_folder": open_folder,
                    "mapping_profile": selected_profile if selected_profile != "None" else None,
                    "exclude_tags": excluded_tags if excluded_tags else None,
                }
                bridge.export_files(
                    files=st.session_state.loaded_files, format="DSV", output_dir=Path(
                        st.session_state.export_dir) if st.session_state.export_dir else None, **kwargs)
                st.success("Files exported successfully!")
            except Exception as e:
                st.error(f"Error during export: {str(e)}")

    with tab_alto:
        st.header("ALTO Export")
        st.info("Converts PAGE XML files to ALTO XML files.")
        st.info("No additional settings required for ALTO export.")
        if st.button("Export to ALTO"):
            if 'export_dir' not in st.session_state:
                st.session_state.export_dir = None
            try:
                kwargs = {
                    "mapping_profile": selected_profile if selected_profile != "None" else None,
                    "exclude_tags": excluded_tags if excluded_tags else None,
                }
                bridge.export_files(
                    files=st.session_state.loaded_files, format="ALTO", output_dir=Path(
                        st.session_state.export_dir) if st.session_state.export_dir else None, **kwargs)
                st.success("Files exported successfully!")
            except Exception as e:
                st.error(f"Error during export: {str(e)}")

    with tab_fulltext:
        st.header("Fulltext Export")
        dehyphenate = st.checkbox("Dehyphenate Text", value=False, key="ft_dehyphenate")
        ro = st.checkbox("Use Reading Order", value=True, key="ft_ro")
        ro_mode = st.selectbox(
            "Reading Order Mode",
            options=["auto", "document", "reading-order-group"],
            index=0,
            key="ft_ro_mode"
        )
        single_file = st.checkbox(
            "Combine all pages into one document",
            value=False,
            key="ft_single_file"
        )
        if single_file:
            single_file_name = st.text_input(
                "Combined Document Filename",
                value="fulltext_combined.txt",
                key="ft_single_file_name"
            )
            separator = st.text_input(
                "Page Separator",
                value="-- Page {page-number}: {page-name} --",
                help="Separator between pages. Supported placeholders: {page-number}, {page-name}, or '..'",
                key="ft_separator"
            )
        else:
            single_file_name = "fulltext_combined.txt"
            separator = "-- Page {page-number}: {page-name} --"

        open_folder = st.checkbox("Open Folder After Export", value=True, key="ft_open_folder")
        if st.button("Export to Fulltext"):
            if 'export_dir' not in st.session_state:
                st.session_state.export_dir = None
            try:
                kwargs = {
                    "dehyphenate": dehyphenate,
                    "ro": ro,
                    "ro_mode": ro_mode,
                    "single_file": single_file,
                    "single_file_name": single_file_name,
                    "separator": separator,
                    "open_folder": open_folder,
                    "mapping_profile": selected_profile if selected_profile != "None" else None,
                    "exclude_tags": excluded_tags if excluded_tags else None,
                }
                exported_files = bridge.export_files(
                    files=st.session_state.loaded_files, format="Fulltext", output_dir=Path(
                        st.session_state.export_dir) if st.session_state.export_dir else None, **kwargs)
                if exported_files:
                    st.success(f"Successfully exported {len(exported_files)} file(s)!")
                else:
                    st.success("Files exported successfully!")
            except Exception as e:
                st.error(f"Error during export: {str(e)}")

    with tab_markdown:
        st.header("Markdown Export")
        dehyphenate = st.checkbox("Dehyphenate Text", value=False, key="md_dehyphenate")
        ro = st.checkbox("Use Reading Order", value=True, key="md_ro")
        ro_mode = st.selectbox(
            "Reading Order Mode",
            options=["auto", "document", "reading-order-group"],
            index=0,
            key="md_ro_mode"
        )
        col_m1, col_m2 = st.columns(2)
        with col_m1:
            export_table_snippets = st.checkbox(
                "Export Table Snippets",
                value=True,
                key="md_table_snippets",
                help="Crop and export image snippets for TableRegions"
            )
        with col_m2:
            export_image_snippets = st.checkbox(
                "Export Image Snippets",
                value=True,
                key="md_image_snippets",
                help="Crop and export image snippets for ImageRegions"
            )

        single_file = st.checkbox(
            "Combine all pages into one document",
            value=False,
            key="md_single_file"
        )
        if single_file:
            single_file_name = st.text_input(
                "Combined Document Filename",
                value="document_combined.md",
                key="md_single_file_name"
            )
            separator = st.text_input(
                "Page Separator",
                value="-- Page {page-number}: {page-name} --",
                help="Separator between pages in combined markdown. Supported placeholders: {page-number}, {page-name}, or '..'",
                key="md_separator"
            )
        else:
            single_file_name = "document_combined.md"
            separator = "-- Page {page-number}: {page-name} --"

        snippet_folder = st.text_input(
            "Snippets Subfolder",
            value="images",
            key="md_snippet_folder",
            help="Subfolder name for cropped table and image snippets (relative to markdown file)"
        )

        st.write("##### 🖼️ Image Source Directory")
        if "md_image_dir" not in st.session_state:
            # Auto-detect default: check if parent or parent.parent has images
            detected_dir = ""
            if st.session_state.get("loaded_files"):
                first_f = Path(st.session_state.loaded_files[0])
                if any(first_f.parent.glob("*.png")) or any(first_f.parent.glob("*.jpg")):
                    detected_dir = str(first_f.parent)
                elif any(first_f.parent.parent.glob("*.png")) or any(first_f.parent.parent.glob("*.jpg")):
                    detected_dir = str(first_f.parent.parent)
            st.session_state.md_image_dir = detected_dir

        c_dir_btn, c_dir_txt = st.columns([1, 3])
        with c_dir_btn:
            if st.button("Select Image Directory", key="select_md_image_dir_btn"):
                chosen = pick_directory(initial_dir=st.session_state.md_image_dir or get_loaded_workspace_dir())
                if chosen:
                    st.session_state.md_image_dir = str(chosen)
                    st.rerun()
        with c_dir_txt:
            img_dir_val = st.text_input(
                "Image Directory",
                value=st.session_state.md_image_dir,
                key="md_image_dir_input",
                help="Folder where the page images are located (for cropping table and image snippets)."
            )
            st.session_state.md_image_dir = img_dir_val

        if st.session_state.md_image_dir and Path(st.session_state.md_image_dir).is_dir():
            img_count = len([f for f in Path(st.session_state.md_image_dir).glob("*") if f.suffix.lower() in ('.png', '.jpg', '.jpeg', '.tif', '.tiff', '.webp', '.bmp')])
            st.caption(f"📁 Image Directory: `{st.session_state.md_image_dir}` ({img_count} image(s) found)")
        elif st.session_state.md_image_dir:
            st.warning(f"⚠️ Directory does not exist: `{st.session_state.md_image_dir}`")

        open_folder = st.checkbox("Open Folder After Export", value=True, key="md_open_folder")
        if st.button("Export to Markdown"):
            if 'export_dir' not in st.session_state:
                st.session_state.export_dir = None
            try:
                kwargs = {
                    "image_folder": st.session_state.md_image_dir if st.session_state.md_image_dir else None,
                    "dehyphenate": dehyphenate,
                    "ro": ro,
                    "ro_mode": ro_mode,
                    "export_table_snippets": export_table_snippets,
                    "export_image_snippets": export_image_snippets,
                    "snippet_folder": snippet_folder,
                    "single_file": single_file,
                    "single_file_name": single_file_name,
                    "separator": separator,
                    "open_folder": open_folder,
                    "mapping_profile": selected_profile if selected_profile != "None" else None,
                    "exclude_tags": excluded_tags if excluded_tags else None,
                }
                exported_files = bridge.export_files(
                    files=st.session_state.loaded_files, format="Markdown", output_dir=Path(
                        st.session_state.export_dir) if st.session_state.export_dir else None, **kwargs)
                if exported_files:
                    st.success(f"Successfully exported {len(exported_files)} file(s)!")
                else:
                    st.success("Files exported successfully!")
            except Exception as e:
                st.error(f"Error during export: {str(e)}")

    with tab_pdf:
        st.header("PDF Export")
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
                selected_dir = pick_directory(initial_dir=get_loaded_workspace_dir())
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
                selected_files = pick_files(
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

        dpi = st.number_input(
            "DPI", min_value=18, max_value=1200, value=None)
        draw_options = ["Baseline", "Textline", "TextRegion"]
        draw = st.multiselect(
            "Draw Elements",
            options=draw_options,
            default=[]
        )
        line_thickness = st.slider(
            "Line Thickness (pt)", min_value=0.5, max_value=10.0, value=1.5, step=0.5)
        output_filename = st.text_input(
            "Output Filfilename",
            value="PagePlus"
        )
        if st.button("Export to PDF"):
            if 'export_dir' not in st.session_state:
                st.session_state.export_dir = None
            if 'pdf_input' not in st.session_state:
                st.error("Please select image files or directory first.")
            else:
                try:
                    pdf_input = st.session_state.pdf_input
                    kwargs = {
                        "images": pdf_input['files'],
                        "max_resolution": None if dpi == 0 else dpi,
                        "draw": draw,
                        "line_thickness": line_thickness,
                        "output_filename": output_filename,
                        "mapping_profile": selected_profile if selected_profile != "None" else None,
                        "exclude_tags": excluded_tags if excluded_tags else None,
                    }
                    bridge.export_files(
                        files=st.session_state.loaded_files, format="PDF", output_dir=Path(
                            st.session_state.export_dir) if st.session_state.export_dir else None, **kwargs)
                    st.success("Files exported successfully!")
                except Exception as e:
                    st.error(f"Error during export: {str(e)}")


def show_dsv_export(cli_bridge):
    """Display DSV export options and results."""
    st.subheader("DSV Export")

    # DSV options
    delimiter = st.selectbox("Delimiter", ["Tab", "Comma", "Semicolon"])
    dehyphenate = st.checkbox("Dehyphenate", value=False)

    if st.button("Export to DSV"):
        with st.spinner("Exporting to DSV...", show_time=True):
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
        with st.spinner("Exporting to ALTO...", show_time=True):
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
    ro_mode = st.selectbox("Reading Order Mode",
                           [ReadingOrderMode.auto.name,
                            ReadingOrderMode.document.name,
                            ReadingOrderMode.rog.name])

    if st.button("Export to Fulltext"):
        with st.spinner("Exporting to Fulltext...", show_time=True):
            try:
                results = cli_bridge.export_files(
                    files=st.session_state.loaded_files,
                    output_dir=st.session_state.export_dir if st.session_state.export_dir else None,
                    format="fulltext",
                    dehyphenate=dehyphenate,
                    ro=ro,
                    ro_mode=ro_mode)
                st.success("Export completed!")
                st.write(f"Exported files: {results}")
            except Exception as e:
                st.error(f"Error during export: {str(e)}")


def show_pdf_export(cli_bridge):
    """Display PDF export options and results."""
    st.subheader("PDF Export")

    # PDF options
    # image_folder = st.text_input(
    #    "Image Folder",
    #    value="images",
    #    label_visibility="visible"
    # )
    # dpi = st.number_input("DPI", value=400, min_value=72, max_value=1200)

    if st.button("Export to PDF"):
        with st.spinner("Exporting to PDF...", show_time=True):
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


def show_tei_export(cli_bridge):
    """Display TEI export options and results."""
    st.subheader("TEI Export")
    
    tei_format = st.selectbox(
        "TEI Format",
        options=["fsl"],
        key="tei_format"
    )
    
    if tei_format == "fsl":
        werkteil = st.text_input("Werkteil", value="Grammatik", key="tei_fsl_werkteil")
        editor = st.text_input("Editorname", value="", key="tei_fsl_editor", help="Johann Kirchmaier (empty default)")
        who = st.text_input("Bearbeiter-Abkürzung (who)", value="", key="tei_fsl_who", help="e.g. lisa")
        status = st.selectbox(
            "Status",
            options=["Work in Progress", "Done"],
            index=0,
            key="tei_fsl_status"
        )
        open_folder = st.checkbox("Open Folder After Export", value=True, key="tei_fsl_open_folder")

        if st.button("Export to TEI (FSL)"):
            with st.spinner("Exporting to TEI...", show_time=True):
                try:
                    status_val = "work_in_progress" if status == "Work in Progress" else "done"
                    results = cli_bridge.export_files(
                        files=st.session_state.loaded_files,
                        format="TEI",
                        tei_format="fsl",
                        werkteil=werkteil,
                        editor=editor,
                        who=who,
                        status=status_val,
                        open_folder=open_folder,
                        output_dir=st.session_state.export_dir if st.session_state.export_dir else None
                    )
                    st.success("Export completed!")
                    st.write(f"Exported files: {results}")
                except Exception as e:
                    st.error(f"Error during export: {str(e)}")

