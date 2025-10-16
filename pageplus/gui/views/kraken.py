import streamlit as st
from pathlib import Path
import threading

from pageplus.gui.cli_bridges.kraken import KrakenBridge
from pageplus.gui.views.load_files import get_loaded_workspace_dir
from pageplus.gui.utils.picker import pick_directory, pick_files


def show_kraken(cli_bridge: KrakenBridge):
    """Display the Kraken OCR page."""
    st.title("🐙 Kraken OCR")

    st.markdown("""
    This page provides OCR functionality using Kraken OCR engine.
    Kraken is a powerful OCR system developed for historical documents and manuscripts.
    """)

    # Show configured environment info
    with st.expander("🔧 Kraken Environment Info"):
        python_path = cli_bridge.get_python_env_path()
        st.success("✅ Kraken is properly configured")
        st.code(f"Python path: {python_path}", language="text")
        st.info("To change the configuration, go to Settings → OCR Engines → Kraken OCR")

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
                            st.session_state.kraken_input = {
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
                file_types = [
                    ("Image Files", " ".join(f"*{ext}" for ext in selected_extensions)),
                    ("All files", "*")
                ]
                selected_paths = pick_files(
                    initial_dir=get_loaded_workspace_dir(),
                    filetypes=file_types
                )
                if selected_paths:
                    st.session_state.kraken_input = {
                        "type": "files",
                        "files": selected_paths
                    }
                    st.success(f"Selected {len(selected_paths)} files.")
                    st.rerun()

        if 'kraken_input' in st.session_state:
            # Display selected files in a dataframe
            st.subheader("Selected Files")
            if st.session_state.kraken_input["type"] == "directory":
                # For directory input, show directory path and file count
                st.write(
                    f"Directory: {st.session_state.kraken_input['path']}")
                st.write(
                    f"Extensions: {', '.join(st.session_state.kraken_input['extensions'])}")
                st.write(
                    f"Total files: {len(st.session_state.kraken_input['files'])}")

                # Create a dataframe with file information
                import pandas as pd
                files_df = pd.DataFrame([
                    {
                        'Filename': Path(f).name,
                        'Extension': Path(f).suffix,
                        'Size (KB)': round(Path(f).stat().st_size / 1024, 2),
                        'Full Path': f
                    }
                    for f in st.session_state.kraken_input['files']
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
                    for f in st.session_state.kraken_input['files']
                ])
                st.dataframe(files_df, width='stretch')

        # Output directory
        st.subheader("Output Directory")
        st.info("Leave empty to overwrite input files (recommended with backup)")

        if st.button("Select Output Directory", key="select_output_dir_button"):
            selected_dir = pick_directory(initial_dir=get_loaded_workspace_dir())
            if selected_dir:
                st.session_state.kraken_output_dir = selected_dir
                st.rerun()

        if 'kraken_output_dir' in st.session_state:
            st.text_input(
                "Selected Output Directory",
                value=st.session_state.kraken_output_dir,
                disabled=True
            )
            if st.button("Clear Output Directory", key="clear_output_dir_button"):
                del st.session_state.kraken_output_dir
                st.rerun()

    with tab_processing:
        # Check if files are selected
        if 'kraken_input' not in st.session_state:
            st.warning("Please select image files in the I/O tab first.")
            return

        selected_files = st.session_state.kraken_input["files"]

        # Create sub-tabs for CLI and PagePlus modes
        tab_cli, tab_pageplus = st.tabs(["🖥️ CLI Mode", "🔧 PagePlus Mode"])

        with tab_cli:
            _show_cli_mode(cli_bridge, selected_files)

        with tab_pageplus:
            _show_pageplus_mode(cli_bridge, selected_files)


def _show_cli_mode(cli_bridge, selected_files):
    """Show CLI mode interface."""
    st.markdown("""
    **Native Kraken CLI Functions**

    These modes use Kraken's native CLI commands directly for maximum performance.
    Perfect for standard segmentation and OCR workflows.
    """)

    # Processing Mode Selection for CLI
    st.subheader("🎯 Processing Mode")

    processing_mode = st.radio(
        "Select Processing Mode",
        ["Segmentation Only", "Recognition Only (requires XML)", "Segmentation + Recognition"],
        help="""
        - Segmentation Only: Create PAGE-XML with layout regions from images
        - Recognition Only: Add text to existing PAGE-XML files
        - Segmentation + Recognition: Complete pipeline from images to text
        """,
        horizontal=False,
        key="cli_mode"
    )

    # Help section based on mode
    with st.expander("ℹ️ Help & Tips"):
        if processing_mode == "Segmentation Only":
            st.markdown("""
            **Segmentation Mode:**

            - Creates PAGE-XML files with layout regions (text lines, baselines)
            - Requires a **segmentation model** (.mlmodel)
            - Use this to prepare images for OCR
            - Output: PAGE-XML files with coordinates but no text

            **Model Selection:**
            - Choose models trained for layout analysis (e.g., 'blla.mlmodel')
            - Find models at: https://zenodo.org/communities/ocr_models
            """)
        elif processing_mode == "Recognition Only (requires XML)":
            st.markdown("""
            **Recognition Mode:**

            - Adds text to existing PAGE-XML files
            - Requires **recognition model** (.mlmodel) and existing XML files
            - Use this after segmentation or with pre-segmented documents

            **Requirements:**
            - PAGE-XML files must exist for each image
            - XML files must contain layout information (baselines, regions)
            """)
        else:  # Segmentation + Recognition
            st.markdown("""
            **Combined Mode:**

            - Complete pipeline: Image → Layout → Text
            - Requires both **segmentation** and **recognition** models
            - Best for processing new images from scratch

            **Workflow:**
            1. Segmentation creates layout structure
            2. Recognition adds text to the layout
            3. Output: Complete PAGE-XML files
            """)

    # Configuration section
    seg_model_name, rec_model_name, model_dir, seg_text_direction, rec_text_direction = _show_model_configuration(
        cli_bridge, processing_mode, key_prefix="cli"
    )

    # Performance Options
    device, jobs, template, threads = _show_performance_options(key_prefix="cli", mode=processing_mode)

    # Processing section
    st.subheader("⚡ Processing")

    button_text = {
        "Segmentation Only": "🚀 Start Segmentation",
        "Recognition Only (requires XML)": "🚀 Start Recognition",
        "Segmentation + Recognition": "🚀 Start Full Pipeline"
    }

    if st.button(button_text[processing_mode], type="primary", key="cli_process_btn"):
        # Validate models
        if processing_mode == "Segmentation Only":
            if not seg_model_name or not model_dir:
                st.error("Please select a segmentation model first!")
                return
        elif processing_mode == "Recognition Only (requires XML)":
            if not rec_model_name or not model_dir:
                st.error("Please select a recognition model first!")
                return
        else:  # Segmentation + Recognition
            if not seg_model_name or not rec_model_name or not model_dir:
                st.error("Please select both segmentation and recognition models!")
                return

        # Run processing
        _run_cli_processing(
            cli_bridge, processing_mode, selected_files,
            seg_model_name, rec_model_name, model_dir, device, seg_text_direction, rec_text_direction, jobs, template, threads
        )


def _show_pageplus_mode(cli_bridge, selected_files):
    """Show PagePlus mode interface."""
    st.markdown("""
    **PagePlus Advanced Functions**

    Advanced OCR mode with fine-grained control over processing.
    Includes text filters, region filters, and other PagePlus-specific features.
    """)

    st.info("📝 **Note:** This mode requires existing PAGE-XML files with layout information.")

    # Configuration section
    _, rec_model_name, model_dir, _, _ = _show_model_configuration(
        cli_bridge, "Advanced", key_prefix="pageplus"
    )

    # Filtering options
    st.subheader("🎯 Filtering Options")

    col1, col2, col3 = st.columns(3)

    with col1:
        text_filter = st.text_input(
            "Text Filter (Regex)",
            value="",
            help="Regular expression to filter specific textlines",
            key="pageplus_text_filter"
        )

    with col2:
        region_tagfilter = st.text_input(
            "Region Tag Filter",
            value="",
            help="Filter specific region tags",
            key="pageplus_region_filter"
        )

    with col3:
        textline_tagfilter = st.text_input(
            "Textline Tag Filter",
            value="",
            help="Filter specific textline tags",
            key="pageplus_textline_filter"
        )

    # Additional options
    st.subheader("🔧 Additional Options")

    col1, col2 = st.columns(2)

    with col1:
        save_snippets = st.checkbox(
            "Save Snippets",
            value=False,
            help="Save image snippets for debugging",
            key="pageplus_save_snippets"
        )

    with col2:
        dry_run = st.checkbox(
            "Dry Run",
            value=False,
            help="Process without saving changes",
            key="pageplus_dry_run"
        )

    # Processing section
    st.subheader("⚡ Processing")

    if st.button("🚀 Start Advanced OCR", type="primary", key="pageplus_process_btn"):
        if not rec_model_name or not model_dir:
            st.error("Please select a recognition model first!")
            return

        # Find corresponding XML files
        xml_files = []
        for image_file in selected_files:
            image_path = Path(image_file)
            xml_file = image_path.with_suffix('.xml')
            if xml_file.exists():
                xml_files.append(str(xml_file))
            else:
                st.warning(f"No corresponding XML file found for {image_path.name}")

        if not xml_files:
            st.error("No corresponding XML files found for the selected images!")
            st.info("PagePlus mode requires existing PAGE-XML files.")
            return

        # Run advanced OCR
        _run_pageplus_processing(
            cli_bridge, selected_files, xml_files,
            rec_model_name, model_dir,
            text_filter, region_tagfilter, textline_tagfilter,
            save_snippets, dry_run
        )


def _show_model_configuration(cli_bridge, processing_mode, key_prefix=""):
    """Show model configuration UI."""
    st.subheader("🔧 Model Configuration")

    # Get default model path from settings
    from pageplus.gui.utils.settings import Settings
    settings = Settings()
    default_model_path = settings.get("KRAKEN_MODEL_PATH", "")

    # Model directory selection
    col1, col2 = st.columns([3, 1])
    with col1:
        model_dir_input = st.text_input(
            "Model Directory",
            value=st.session_state.get(f'{key_prefix}_kraken_model_dir', default_model_path),
            placeholder="/path/to/kraken/models",
            help="Directory containing Kraken model files (configured in Settings)",
            key=f"{key_prefix}_model_dir_input"
        )

    with col2:
        st.write("")
        st.write("")
        if st.button("🔍 Browse", key=f"{key_prefix}_browse_model_dir"):
            initial_dir = model_dir_input if model_dir_input else get_loaded_workspace_dir()
            selected_dir = pick_directory(initial_dir=initial_dir)
            if selected_dir:
                st.session_state[f'{key_prefix}_kraken_model_dir'] = selected_dir
                st.rerun()

    # Option to filter models by type
    filter_models = st.checkbox(
        "🔍 Filter models by type (slower, but shows only correct models)",
        value=st.session_state.get(f'{key_prefix}_filter_models', False),
        help="Enable to automatically detect and filter segmentation/recognition models. Disable for faster loading.",
        key=f"{key_prefix}_filter_models_checkbox"
    )
    st.session_state[f'{key_prefix}_filter_models'] = filter_models

    # Model selection based on processing mode
    seg_model_name = None
    rec_model_name = None
    model_dir = None
    seg_text_direction = "horizontal-lr"  # Default
    rec_text_direction = "horizontal-tb"  # Default

    if model_dir_input:
        model_dir = Path(model_dir_input)
        if model_dir.exists():
            # Get all available models
            all_models = cli_bridge.get_available_models(model_dir)

            if not all_models:
                st.warning("No Kraken models (.mlmodel) found in the specified directory.")
            else:
                # If filtering is enabled, categorize by type
                if filter_models:
                    models_by_type = cli_bridge.get_models_by_type(model_dir)
                    seg_models = models_by_type['segmentation']
                    rec_models = models_by_type['recognition']
                else:
                    # No filtering - all models available for all modes
                    seg_models = all_models
                    rec_models = all_models
                    models_by_type = {'segmentation': [], 'recognition': [], 'unknown': all_models}

                if processing_mode == "Segmentation Only":
                    if filter_models and not seg_models:
                        st.warning("⚠️ No segmentation models found. Disable filtering or add segmentation models.")
                        seg_models = all_models

                    col1, col2, _ = st.columns(3)
                    with col1:
                        seg_model_name = st.selectbox(
                            "Segmentation Model",
                            options=seg_models if seg_models else all_models,
                            help="Select a segmentation model (e.g., blla.mlmodel)",
                            key=f"{key_prefix}_seg_model"
                        )
                    with col2:
                        seg_text_direction = st.selectbox(
                            "Text Direction (Segmentation)",
                            options=["horizontal-lr", "horizontal-rl", "vertical-lr", "vertical-rl"],
                            index=0,
                            help="Text direction for segmentation",
                            key=f"{key_prefix}_seg_text_direction"
                        )
                    st.caption(f"📁 Model path: `{model_dir / seg_model_name}`")

                    # Show model info
                    if filter_models and models_by_type['segmentation']:
                        st.info(f"✅ {len(models_by_type['segmentation'])} segmentation model(s) found")

                elif processing_mode == "Recognition Only (requires XML)" or processing_mode == "Advanced":
                    if filter_models and not rec_models:
                        st.warning("⚠️ No recognition models found. Disable filtering or add recognition models.")
                        rec_models = all_models

                    col1, col2, _ = st.columns(3)
                    with col1:
                        rec_model_name = st.selectbox(
                            "Recognition Model",
                            options=rec_models if rec_models else all_models,
                            help="Select a recognition/OCR model",
                            key=f"{key_prefix}_rec_model"
                        )
                    with col2:
                        rec_text_direction = st.selectbox(
                            "Text Direction (Recognition)",
                            options=["horizontal-tb", "vertical-lr", "vertical-rl"],
                            index=0,
                            help="Sets principal text direction in serialization output",
                            key=f"{key_prefix}_rec_text_direction"
                        )
                    st.caption(f"📁 Model path: `{model_dir / rec_model_name}`")

                    # Show model info
                    if filter_models and models_by_type['recognition']:
                        st.info(f"✅ {len(models_by_type['recognition'])} recognition model(s) found")

                elif processing_mode == "Segmentation + Recognition":
                    if filter_models:
                        if not seg_models:
                            st.warning("⚠️ No segmentation models found. Showing all models.")
                            seg_models = all_models
                        if not rec_models:
                            st.warning("⚠️ No recognition models found. Showing all models.")
                            rec_models = all_models

                    st.write("**Segmentation**")
                    col1, col2, _ = st.columns(3)
                    with col1:
                        seg_model_name = st.selectbox(
                            "Segmentation Model",
                            options=seg_models if seg_models else all_models,
                            help="Select a segmentation model",
                            key=f"{key_prefix}_seg_model_combined"
                        )
                    with col2:
                        seg_text_direction = st.selectbox(
                            "Text Direction (Segmentation)",
                            options=["horizontal-lr", "horizontal-rl", "vertical-lr", "vertical-rl"],
                            index=0,
                            help="Text direction for segmentation",
                            key=f"{key_prefix}_seg_text_direction_combined"
                        )

                    st.write("**Recognition**")
                    col1, col2, _ = st.columns(3)
                    with col1:
                        rec_model_name = st.selectbox(
                            "Recognition Model",
                            options=rec_models if rec_models else all_models,
                            help="Select a recognition model",
                            key=f"{key_prefix}_rec_model_combined"
                        )
                    with col2:
                        rec_text_direction = st.selectbox(
                            "Text Direction (Recognition)",
                            options=["horizontal-tb", "vertical-lr", "vertical-rl"],
                            index=0,
                            help="Sets principal text direction in serialization output",
                            key=f"{key_prefix}_rec_text_direction_combined"
                        )
                    st.caption(f"📁 Seg: `{model_dir / seg_model_name}` | Rec: `{model_dir / rec_model_name}`")

                    # Show model counts
                    if filter_models and (models_by_type['segmentation'] or models_by_type['recognition']):
                        col1, col2 = st.columns(2)
                        with col1:
                            st.info(f"✅ {len(models_by_type['segmentation'])} segmentation model(s)")
                        with col2:
                            st.info(f"✅ {len(models_by_type['recognition'])} recognition model(s)")
        else:
            st.error("Model directory does not exist")
            st.info("💡 Configure the default model path in Settings → OCR Engines → Kraken OCR")
    else:
        st.info("Please select a model directory")
        st.caption("💡 Set a default path in Settings → OCR Engines → Kraken OCR → Model Path Configuration")

    return seg_model_name, rec_model_name, model_dir, seg_text_direction, rec_text_direction


def _show_performance_options(key_prefix="", mode=None):
    """Show performance options UI."""
    st.subheader("⚡ Performance Options")

    col1, col2 = st.columns(2)

    with col1:
        device_option = st.selectbox(
            "Device",
            options=["cpu", "cuda:0"],
            help="Select processing device. CUDA requires NVIDIA GPU and proper setup.",
            key=f"{key_prefix}_device"
        )

        if device_option.startswith("cuda"):
            st.info("🎮 CUDA selected. Ensure PyTorch with CUDA support is installed in the Kraken environment.")

    with col2:
        # When using GPU, jobs should be 1 to avoid VRAM exhaustion and freezes.
        jobs_disabled = device_option.startswith("cuda")
        jobs_value = 1 if jobs_disabled else st.session_state.get(f"{key_prefix}_jobs", 1)

        if jobs_disabled:
            st.info("Parallel jobs are disabled when using a GPU.")

        jobs = st.number_input(
            "Parallel Jobs",
            min_value=1,
            max_value=1 if jobs_disabled else 16,
            value=jobs_value,
            help="Number of parallel jobs. Disabled when using GPU.",
            key=f"{key_prefix}_jobs",
            disabled=jobs_disabled
        )

    threads = st.number_input(
        "Threads",
        min_value=1,
        max_value=32,
        value=1,
        help="Size of thread pools for intra-op parallelization.",
        key=f"{key_prefix}_threads"
    )

    # Template selection
    st.subheader("📄 Output Template")

    # Get custom templates
    import pageplus
    template_dir = Path(pageplus.__file__).parent / "utils" / "kraken" / "template"
    custom_templates = [f.name for f in template_dir.iterdir() if f.is_file()]

    template_options = ["page", "alto"] + custom_templates

    template = st.selectbox(
        "Template",
        options=template_options,
        index=template_options.index("pageplus") if "pageplus" in template_options else 0,
        help="Select the output template for Kraken.",
        key=f"{key_prefix}_template"
    )

    return device_option, jobs, template, threads


def _run_cli_processing(cli_bridge, processing_mode, selected_files,
                        seg_model_name, rec_model_name, model_dir, device, seg_text_direction, rec_text_direction, jobs, template, threads):
    """Run CLI mode processing."""
    
    # --- Model Validation ---
    if processing_mode == "Segmentation Only":
        model_type = cli_bridge.get_model_type(model_dir / seg_model_name)
        if model_type != 'segmentation':
            st.error(f"'{seg_model_name}' is not a valid segmentation model. Please select a different model.")
            return
            
    elif processing_mode == "Recognition Only (requires XML)":
        model_type = cli_bridge.get_model_type(model_dir / rec_model_name)
        if model_type != 'recognition':
            st.error(f"'{rec_model_name}' is not a valid recognition model. Please select a different model.")
            return

    elif processing_mode == "Segmentation + Recognition":
        seg_model_type = cli_bridge.get_model_type(model_dir / seg_model_name)
        if seg_model_type != 'segmentation':
            st.error(f"'{seg_model_name}' is not a valid segmentation model. Please select a different model for segmentation.")
            return
        
        rec_model_type = cli_bridge.get_model_type(model_dir / rec_model_name)
        if rec_model_type != 'recognition':
            st.error(f"'{rec_model_name}' is not a valid recognition model. Please select a different model for recognition.")
            return
    # --- End of Model Validation ---

    total_files = len(selected_files)
    processed_count = 0
    lock = threading.Lock()

    # Create progress containers
    progress_container = st.container()

    with progress_container:
        st.write("**Processing Progress**")
        progress_bar = st.progress(0)
        status_text = st.empty()
        status_text.text(f"Processing {total_files} files...")

    def progress_callback():
        nonlocal processed_count
        with lock:
            processed_count += 1
            progress_percent = processed_count / total_files
            progress_bar.progress(progress_percent)
            status_text.text(f"Processed {processed_count}/{total_files} files...")

    with st.spinner("Kraken is working its magic... 🐙", show_time=True):
        try:
            if processing_mode == "Segmentation Only":
                result = cli_bridge.run_segmentation(
                    image_files=selected_files,
                    model_path=model_dir / seg_model_name,
                    outputdir=st.session_state.get('kraken_output_dir', None),
                    device=device,
                    text_direction=seg_text_direction,
                    jobs=jobs,
                    template=template,
                    threads=threads,
                    progress_callback=progress_callback
                )

            elif processing_mode == "Recognition Only (requires XML)":
                result = cli_bridge.run_recognition(
                    image_files=selected_files,
                    model_path=model_dir / rec_model_name,
                    outputdir=st.session_state.get('kraken_output_dir', None),
                    device=device,
                    text_direction=rec_text_direction,
                    jobs=jobs,
                    template=template,
                    threads=threads,
                    progress_callback=progress_callback
                )

            else:  # Segmentation + Recognition
                result = cli_bridge.run_segment_and_recognize(
                    image_files=selected_files,
                    seg_model_path=model_dir / seg_model_name,
                    rec_model_path=model_dir / rec_model_name,
                    outputdir=st.session_state.get('kraken_output_dir', None),
                    device=device,
                    seg_text_direction=seg_text_direction,
                    rec_text_direction=rec_text_direction,
                    jobs=jobs,
                    template=template,
                    threads=threads,
                    progress_callback=progress_callback
                )

            # Update progress bar to 100%
            with progress_container:
                progress_bar.progress(1.0)
                status_text.text("✅ Processing completed!")

            if result.get("success", False):
                st.success("✅ Processing completed successfully!")

                # Show statistics
                col1, col2, col3 = st.columns(3)
                with col1:
                    st.metric("Files Processed", result.get("processed_files", 0))
                with col2:
                    st.metric("Total Files", result.get("total_files", 0))
                with col3:
                    st.metric("Processing Time", f"{result.get('processing_time', 0):.2f}s")
            else:
                st.error(f"❌ Processing failed: {result.get('error', 'Unknown error')}")
                if "error_details" in result and result["error_details"]:
                    with st.expander("Error Details"):
                        st.json(result["error_details"])

        except Exception as e:
            st.error(f"❌ Error during processing: {str(e)}")


def _run_pageplus_processing(cli_bridge, selected_files, xml_files,
                             rec_model_name, model_dir,
                             text_filter, region_tagfilter, textline_tagfilter,
                             save_snippets, dry_run):
    """Run PagePlus mode processing."""
    progress_container = st.container()

    with progress_container:
        st.write("**Advanced OCR Processing Progress**")
        progress_bar = st.progress(0)
        status_text = st.empty()
        status_text.text(f"Processing {len(xml_files)} files...")

    try:
        result = cli_bridge.run_ocr(
            inputs=xml_files,
            image_folder=".",
            outputdir=st.session_state.get('kraken_output_dir', None),
            model_name=rec_model_name,
            model_dir=model_dir,
            same_names=True,
            image_extensions=[Path(f).suffix for f in selected_files],
            save_snippets=save_snippets,
            text_filter=text_filter if text_filter else None,
            region_tagfilter=region_tagfilter if region_tagfilter else None,
            textline_tagfilter=textline_tagfilter if textline_tagfilter else None,
            dry_run=dry_run
        )

        with progress_container:
            progress_bar.progress(1.0)
            status_text.text("✅ Processing completed!")

        if result.get("success", False):
            st.success("✅ Advanced OCR completed successfully!")

            col1, col2, col3 = st.columns(3)
            with col1:
                st.metric("Files Processed", result.get("processed_files", 0))
            with col2:
                st.metric("Total Files", result.get("total_files", 0))
            with col3:
                st.metric("Processing Time", f"{result.get('processing_time', 0):.2f}s")
        else:
            st.error(f"❌ Processing failed: {result.get('error', 'Unknown error')}")
            if "error_details" in result and result["error_details"]:
                with st.expander("Error Details"):
                    st.json(result["error_details"])

    except Exception as e:
        st.error(f"❌ Error during processing: {str(e)}")
