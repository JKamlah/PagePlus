import streamlit as st
from pathlib import Path

from pageplus.gui.cli_bridges.tesseract import TesseractBridge
from pageplus.utils.constants import TesseractLanguageNames
from pageplus.gui.views.load_files import get_loaded_workspace_dir
from pageplus.gui.utils.picker import pick_directory


def show_tesseract(cli_bridge: TesseractBridge):
    """Display the Tesseract OCR page."""
    st.title("🔤 Tesseract OCR")

    st.markdown("""
    This page provides OCR functionality using Tesseract with parallel processing capabilities.
    Process your PAGE-XML files to extract text from images using the tesserocr library.
    """)

    # Check if Tesseract is activated
    if not cli_bridge.is_activated():
        st.warning("⚠️ Tesseract OCR is not activated. Please activate it in Settings first.")
        st.info("Go to **Settings** → **OCR Engines** → **Enable Tesseract OCR** to activate this feature.")
        if st.button("Go to Settings"):
            st.session_state.main_page_selection = "⚙️ Settings"
            st.rerun()
        return
    # Create tabs for different sections
    tab_io, tab_processing = st.tabs(["📁 I/O", "⚡ Processing"])

    with tab_io:
        # Input selection
        input_type = st.radio(
            "Select Input Type",
            ["Directory", "Files"],
            horizontal=True
        )
        selected_extensions = st.multiselect(
            "Image Extensions",
            options=['.jpg', '.jpeg', '.png', '.bmp', '.tiff', '.tif'],
            default=['.jpg', '.jpeg', '.png', '.tiff', '.tif']
        )

        if input_type == "Directory":
            st.write("Select Image Extensions to Search")

            if st.button("Select Image Directory", key="select_image_dir_button"):
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
                            st.session_state.tesseract_input = {
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
            if st.button("Select Image Files", key="select_image_files_button"):
                from pageplus.gui.utils.picker import pick_files
                from pageplus.gui.cli_bridges.workspace import WorkspaceBridge

                workspace_bridge = WorkspaceBridge()
                initial_dir = workspace_bridge.get_loaded_workspace_dir() if hasattr(workspace_bridge, 'get_loaded_workspace_dir') else "."

                file_types = [
                    ("Image Files", " ".join(f"*{ext}" for ext in selected_extensions)),
                    ("All files", "*")
                ]
                selected_paths = pick_files(
                    initial_dir=get_loaded_workspace_dir(),
                    filetypes=file_types
                )
                if selected_paths:
                    st.session_state.tesseract_input = {
                        "type": "files",
                        "files": selected_paths
                    }
                    st.success(f"Selected {len(selected_paths)} files.")
                    st.rerun()

        if 'tesseract_input' in st.session_state:
            # Display selected files in a dataframe
            st.subheader("Selected Files")
            if st.session_state.tesseract_input["type"] == "directory":
                # For directory input, show directory path and file count
                st.write(
                    f"Directory: {st.session_state.tesseract_input['path']}")
                st.write(
                    f"Extensions: {', '.join(st.session_state.tesseract_input['extensions'])}")
                st.write(
                    f"Total files: {len(st.session_state.tesseract_input['files'])}")

                # Create a dataframe with file information
                import pandas as pd
                files_df = pd.DataFrame([
                    {
                        'Filename': Path(f).name,
                        'Extension': Path(f).suffix,
                        'Size (KB)': round(Path(f).stat().st_size / 1024, 2),
                        'Full Path': f
                    }
                    for f in st.session_state.tesseract_input['files']
                ])
                st.dataframe(files_df, width='stretch')
            else:
                # For file input, show list of selected files
                import pandas as pd
                files_df = pd.DataFrame([
                    {
                        'Filename': Path(f).name,
                        'Extension': Path(f).suffix,
                        'Size (KB)': round(Path(f).stat().st_size / 1024, 2),
                        'Full Path': f
                    }
                    for f in st.session_state.tesseract_input['files']
                ])
                st.dataframe(files_df, width='stretch')

            # selected_files_for_ocr = st.session_state.tesseract_input["files"]

            # Select output directory
            st.subheader("Output Directory")
            st.write(
                "Output directory: The default is to overwrite the input files "
                "(recommended with backup strategy).")
            if st.button("Select Output Directory", key="select_output_dir_button"):
                from pageplus.gui.utils.picker import pick_files
                from pageplus.gui.cli_bridges.workspace import WorkspaceBridge

                workspace_bridge = WorkspaceBridge()
                initial_dir = workspace_bridge.get_loaded_workspace_dir() if hasattr(workspace_bridge, 'get_loaded_workspace_dir') else "."

                selected_paths = pick_files(
                    initial_dir=initial_dir,
                    filetypes=[("All files", "*")]
                )
                if selected_paths:
                    st.session_state.tesseract_output_dir = selected_paths[0]
                elif selected_paths is not None:
                    st.info("Directory selection cancelled.")

            if 'tesseract_output_dir' in st.session_state:
                st.text_input(
                    "Selected Output Directory",
                    value=st.session_state.tesseract_output_dir,
                    disabled=True,
                    label_visibility="visible"
                )
                if st.button("Clear Output Directory",
                             key="clear_output_dir_button"):
                    del st.session_state.tesseract_output_dir
                    st.rerun()

    with tab_processing:
        # Check if files are selected
        if 'tesseract_input' not in st.session_state:
            st.warning("Please select files in the I/O tab first.")
            return

        # Show selected files info
        selected_files = st.session_state.tesseract_input["files"]
        # Help section
        with st.expander("ℹ️ Help & Tips"):
            st.markdown("""
            **Tesseract OCR Configuration:**

            - **Model Name**: Specify the language model (e.g., 'eng' for English, 'deu' for German)
            - **Parallel Jobs**: Number of files to process simultaneously (recommended: 2-4)
            - **Same Names**: If checked, looks for images with the same name as the XML file
            - **Image Folder**: Relative path to the folder containing images

            **Filtering Options:**

            - **Text Filter**: Use regular expressions to process only specific textlines
            - **Region/Textline Tag Filters**: Filter by specific XML tags

            **Performance Tips:**

            - Use parallel processing for better performance
            - Start with a small number of files to test configuration
            - Use dry run mode to test without making changes
            """)
        # Configuration section
        st.subheader("🔧 Configuration")

        # Get model path from settings
        from pageplus.gui.utils.settings import Settings
        settings = Settings()
        model_path = settings.get("TESSERACT_MODEL_PATH", None)

        # Get available models
        available_models = cli_bridge.get_available_models(model_path)

        if not available_models:
            st.warning("No Tesseract models found. Please check your Tesseract installation.")
            model_name = "eng"  # Fallback
        else:
            # Create a mapping of display names to actual model names
            model_options = {}

            # Use language names from constants

            for model in available_models:
                # Remove only .traineddata extension, keep the rest of the path
                clean_name = model.replace('.traineddata', '')

                # Create display name with language name if available
                if clean_name in TesseractLanguageNames:
                    display_name = f"{TesseractLanguageNames[clean_name]} ({clean_name})"
                else:
                    display_name = clean_name

                model_options[display_name] = model

            # Default to 'eng' if available, otherwise use the first model
            default_model = None
            for display_name, model_name in model_options.items():
                if model_name == "eng":
                    default_model = display_name
                    break

            if default_model is None and model_options:
                default_model = list(model_options.keys())[0]

            # Model selection with refresh option
            col_model, _ = st.columns([1, 3])

            with col_model:
                selected_display_name = st.selectbox(
                    "Language Model",
                    options=list(model_options.keys()),
                    index=list(model_options.keys()).index(default_model) if default_model and default_model in model_options else 0,
                    help="Select the Tesseract language model for OCR processing"
                )

            # Show current model path
            if model_path:
                st.caption(f"📁 Using model path: `{model_path}`")
            else:
                st.caption("📁 Using default Tesseract model path")

            # Get the actual model name for processing
            model_name = model_options.get(selected_display_name, "eng")

        col_jobs, _ = st.columns([1, 3])
        with col_jobs:
            jobs = st.number_input(
                "Parallel Jobs",
                min_value=1,
                max_value=16,
                value=4,
                help="Number of parallel jobs for processing"
            )

        dry_run = st.checkbox(
            "Dry Run",
            value=False,
            help="Process without saving changes"
        )

        # Processing level selection
        st.subheader("🎯 Processing Level")
        col_processing_level, _ = st.columns([1, 4])
        with col_processing_level:
            processing_level = st.selectbox(
                "Process on level:",
                ["Textline", "TextRegion", "Page"],
                index=0,  # Default to Textline
                help="Select the level at which to apply OCR processing. Page creates a new output file. TextRegion creates new lines in the regions. Textline only updates the text (based on the Textines Polyongs)."
            )

        # Options based on processing level
        st.subheader("🔧 Options")

        if processing_level == "Textline":
            col1, col2, col3 = st.columns(3)

            with col1:
                text_filter = st.text_input(
                    "Text Filter (Regex)",
                    value="",
                    help="Regular expression to filter specific textlines"
                )

            with col2:
                region_tagfilter = st.text_input(
                    "Region Tag Filter",
                    value="",
                    help="Filter specific region tags"
                )

            with col3:
                textline_tagfilter = st.text_input(
                    "Textline Tag Filter",
                    value="",
                    help="Filter specific textline tags"
                )

        elif processing_level == "TextRegion":
            col1, col2 = st.columns(2)

            with col1:
                region_tagfilter = st.text_input(
                    "TextRegion Tag Filter",
                    value="",
                    help="Filter specific textregion tags"
                )

            with col2:
                st.info("Only textregion-level processing is available for this level")

            # Set unused filters to None
            text_filter = None
            textline_tagfilter = None

        else:  # Page level

            # Format selection for Page level
            output_formats = st.multiselect(
                "Select Output Formats:",
                options=["PageXML", "ALTO", "TEXT", "HOCR", "TSV"],
                default=["PageXML"],
                help="Select the output formats for Page-level processing"
            )

            # PageXML specific options
            if "PageXML" in output_formats:
                create_polygon = st.checkbox(
                    "Create Polygon",
                    value=False,
                    help="Create polygon coordinates for text regions in PageXML output"
                )
                remove_textregion_text = st.checkbox(
                    "Remove TextRegion Text",
                    value=True,
                    help="After OCR, remove all text from TextRegion elements, keeping only the layout."
                )
            else:
                create_polygon = False
                remove_textregion_text = False

            create_subfolder = st.checkbox(
                "Create subfolders for output",
                value=True,
                help="Create subfolders for each output format (e.g., 'page/', 'alto/')."
            )
            rename_page_xml = st.checkbox(
                "Rename .page.xml to .xml",
                value=True,
                help="Rename the final PageXML file from '.page.xml' to '.xml'."
            )

            # Initialize session state for parameters if not exists
            if 'tesseract_custom_params' not in st.session_state:
                st.session_state.tesseract_custom_params = []

            # Display existing parameters
            for i, param in enumerate(st.session_state.tesseract_custom_params):
                col_key, col_value, col_remove = st.columns([2, 2, 1])

                with col_key:
                    param_key = st.text_input(
                        "Parameter Key",
                        value=param.get("key", ""),
                        key=f"param_key_{i}",
                        placeholder="e.g., tessedit_create_page_xml"
                    )

                with col_value:
                    param_value = st.text_input(
                        "Parameter Value",
                        value=param.get("value", ""),
                        key=f"param_value_{i}",
                        placeholder="e.g., 1"
                    )

                with col_remove:
                    if st.button("➖", key=f"param_remove_{i}"):
                        st.session_state.tesseract_custom_params.pop(i)
                        st.rerun()

                # Update the parameter in session state
                st.session_state.tesseract_custom_params[i] = {
                    "key": param_key,
                    "value": param_value
                }

            # Add new parameter button
            if st.button("➕ Add Parameter", key="param_add"):
                st.session_state.tesseract_custom_params.append({"key": "", "value": ""})
                st.rerun()

            # Set all filters to None for page level
            text_filter = None
            region_tagfilter = None
            textline_tagfilter = None

        # Processing section
        st.subheader("⚡ Processing")

        # Process button
        if st.button("🚀 Start OCR Processing", type="primary"):
            # Find corresponding XML files for the selected image files
            xml_files = []
            for image_file in selected_files:
                image_path = Path(image_file)
                # Look for XML file with same name but .xml extension
                xml_file = image_path.with_suffix('.xml')
                if xml_file.exists():
                    xml_files.append(str(xml_file))
                elif processing_level != "Page":
                    st.warning(f"No corresponding XML file found for {image_path.name}")

            if not xml_files and processing_level != "Page":
                st.error("No corresponding XML files found for the selected images!")
                return

            # Prepare parameters
            params = {
                "inputs": xml_files,  # XML files as inputs
                "image_files": selected_files,  # Image files as image_files
                "model_name": model_name if model_name else None,
                "model_path": model_path,
                "save_snippets": False,
                "text_filter": text_filter if text_filter else None,
                "region_tagfilter": region_tagfilter if region_tagfilter else None,
                "textline_tagfilter": textline_tagfilter if textline_tagfilter else None,
                "processing_level": processing_level,
                "jobs": jobs,
                "outputdir": st.session_state.get('tesseract_output_dir', None),
                "dry_run": dry_run
            }

            # Add Page-level specific parameters
            if processing_level == "Page":
                params["output_formats"] = output_formats
                params["custom_params"] = st.session_state.get('tesseract_custom_params', [])
                params["create_polygon"] = create_polygon
                params["remove_textregion_text"] = remove_textregion_text
                params["create_subfolder"] = create_subfolder
                params["rename_page_xml"] = rename_page_xml

            # Process files with progress tracking
            try:
                # Create progress containers
                progress_container = st.container()
                # status_container = st.container()

                with progress_container:
                    st.write("**OCR Processing Progress**")
                    progress_bar = st.progress(0)
                    status_text = st.empty()
                    status_text.text(f"Processing file 1 of {len(params['inputs'])}")
                    stats_text = st.empty()

                # Progress callback function
                def update_progress(progress_info):
                    with progress_container:
                        progress_bar.progress(progress_info['percentage'] / 100)
                        status_text.text(f"Processing file {progress_info['current']} of {progress_info['total']}")
                        stats_text.text(f"✅ Successful: {progress_info['successful']} | ❌ Failed: {progress_info['current'] - progress_info['successful']}")

                # Add progress callback to params
                params['progress_callback'] = update_progress

                # Start processing
                with st.spinner("Tesseract is processing your files... 🔤", show_time=True):
                    result = cli_bridge.run_ocr(**params)

                # Update progress bar to 100% when complete
                with progress_container:
                    progress_bar.progress(1.0)
                    status_text.text("✅ Processing completed!")
                    stats_text.text("")

                if result.get("success", False):
                    st.success("✅ OCR processing completed successfully!")

                    # Show statistics
                    col1, col2, col3 = st.columns(3)
                    with col1:
                        st.metric("Files Processed", result.get("processed_files", 0))
                    with col2:
                        st.metric("Total Files", result.get("total_files", 0))
                    with col3:
                        st.metric("Processing Time", f"{result.get('processing_time', 0):.2f}s")

                else:
                    st.error(f"❌ OCR processing failed: {result.get('error', 'Unknown error')}")

            except Exception as e:
                st.error(f"❌ Error during OCR processing: {str(e)}")
