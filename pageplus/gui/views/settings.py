import streamlit as st
import zipfile
import io
from datetime import datetime
from pathlib import Path

from pageplus.gui.utils.settings import Settings
from dotenv import set_key
from pageplus.utils.envs import get_env_path


def show_settings(cli_bridge):
    """Display settings page with configuration options."""
    st.title("⚙️ Settings")

    # Initialize settings
    settings = Settings()

    tab_credentials, tab_system, tab_ocr, tab_backup = st.tabs(["🔑 Credentials", "🖥️ System", "🔡 OCR Engines", "💾 Backup & Restore"])

    with tab_credentials:
        # API Keys
        st.subheader("API Keys")
        openai_key = st.text_input(
            "OpenAI API Key",
            value=settings.get("OPENAI_API_KEY", ""),
            type="password"
        )
        gemini_key = st.text_input(
            "Gemini API Key",
            value=settings.get("GEMINI_API_KEY", ""),
            type="password"
        )

    with tab_system:
        # Output Settings
        st.subheader("Output Settings")
        output_dir = st.text_input(
            "Default Output Directory",
            value=settings.get("OUTPUT_DIRECTORY", "")
        )

        # GUI Settings
        st.subheader("GUI Settings")
        redirect_url = st.text_input(
            "Redirect URL on Shutdown",
            value=settings.get("PAGEPLUS_REDIRECT_URL", "https://google.com")
        )
        user_agent = st.text_input(
            "User Agent",
            value=settings.get("PAGEPLUS_USER_AGENT", "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")
        )
        file_picker_type = st.selectbox(
            "File Picker Type",
            options=["Native (PyQt6)", "Web (Server-side)"],
            index=1 if settings.get("FILE_PICKER_TYPE", "Native (PyQt6)") == "Web (Server-side)" else 0,
            help="Choose 'Native (PyQt6)' if running locally, or 'Web (Server-side)' if running PagePlus on a remote server."
        )
        # Save settings
        if st.button("Save Settings"):
            try:
                # Update settings
                settings.update({
                    "OPENAI_API_KEY": openai_key,
                    "GEMINI_API_KEY": gemini_key,
                    "OUTPUT_DIRECTORY": output_dir,
                    "PAGEPLUS_REDIRECT_URL": redirect_url,
                    "PAGEPLUS_USER_AGENT": user_agent,
                    "FILE_PICKER_TYPE": file_picker_type,
                })
                st.rerun()
            except Exception as e:
                st.error(f"Error saving settings: {str(e)}")

        # System Settings
        st.subheader("System Operations")
        if st.button("Update Pip"):
            try:
                cli_bridge.update_pip()
                st.success("Pip updated successfully!")
            except RuntimeError as e:
                st.error(str(e))

        if st.button("Update SSL Certificates"):
            try:
                cli_bridge.update_ssl()
                st.success("SSL certificates updated successfully!")
            except RuntimeError as e:
                st.error(str(e))

        if st.button("Clean Logs"):
            try:
                cli_bridge.clean_logs()
                st.success("Logs cleaned successfully!")
            except RuntimeError as e:
                st.error(str(e))

    with tab_ocr:
        # OCR Engine Settings
        st.subheader("OCR Engine Settings")

        # Tesseract OCR Settings
        st.markdown("### 🔤 Tesseract OCR")

        # Check if Tesseract is activated
        tesseract_activated = settings.get("PAGEPLUS_OCR_TESSERACT", "False") == "True"

        # Get default data path
        from pageplus.gui.cli_bridges.tesseract import TesseractBridge
        tesseract_bridge = TesseractBridge()
        default_datapath = tesseract_bridge.get_default_datapath()

        # Tesseract Model Path setting
        st.markdown("#### Model Path Configuration")
        current_model_path = settings.get("TESSERACT_MODEL_PATH", default_datapath)
        if (current_model_path == "" or current_model_path is None or Path(current_model_path).exists() is False) and default_datapath != "":
            set_key(get_env_path(), "TESSERACT_MODEL_PATH", default_datapath)
            current_model_path = default_datapath

        col_path, col_pick = st.columns([3, 1])

        with col_path:
            model_path = st.text_input(
                "Tesseract Model Path",
                value=current_model_path,
                help="Path to the Tesseract models directory (tessdata)",
                key="tesseract_model_path_input"
            )

        with col_pick:
            if st.button("📁 Pick Directory", help="Select directory using file picker", key="pick_tesseract_dir"):
                st.session_state.show_directory_picker = True

        # Directory picker
        if st.session_state.get("show_directory_picker", False):
            from pageplus.gui.utils.picker import pick_directory
            selected_path = pick_directory(current_model_path, key="tesseract_dir")
            if selected_path is not None:
                st.session_state.show_directory_picker = False
                if selected_path:
                    st.session_state.tesseract_new_path = selected_path
                st.rerun()

        # Update model_path if a new path was selected
        if st.session_state.get("tesseract_new_path"):
            model_path = st.session_state.tesseract_new_path

        # Save model path setting - Always show button for clarity
        col_save, col_status = st.columns([1, 3])
        with col_save:
            if st.button("💾 Save Model Path", help="Save the Tesseract model path setting", use_container_width=True, key="save_tesseract_path"):
                try:
                    settings.set("TESSERACT_MODEL_PATH", model_path)
                    # Clear the temporary new path
                    if "tesseract_new_path" in st.session_state:
                        del st.session_state.tesseract_new_path
                    st.success("Model path saved successfully!")
                    st.rerun()
                except Exception as e:
                    st.error(f"Error saving model path: {e}")

        with col_status:
            if model_path != current_model_path:
                st.warning("⚠️ Path has been modified. Click 'Save Model Path' to apply changes.")
            elif Path(model_path).exists():
                st.success("✅ Current path is valid and saved")

        # Debug info (can be removed in production)
        with st.expander("Debug Info"):
            st.write(f"Current PAGEPLUS_OCR_TESSERACT value: {settings.get('PAGEPLUS_OCR_TESSERACT', 'Not set')}")
            st.write(f"Tesseract activated: {tesseract_activated}")
            st.write(f"Default data path: {default_datapath}")
            st.write(f"Current model path: {current_model_path}")

        col1, col2 = st.columns([2, 1])

        with col1:
            tesseract_enabled = st.checkbox(
                "Enable Tesseract OCR",
                value=tesseract_activated,
                help="Enable Tesseract OCR functionality in the GUI"
            )

        with col2:
            if tesseract_enabled != tesseract_activated:
                if st.button("Apply Tesseract Settings"):
                    try:
                        if tesseract_enabled:
                            cli_bridge.activate_tesseract()
                            st.success("Tesseract OCR activated!")
                        else:
                            cli_bridge.deactivate_tesseract()
                            st.success("Tesseract OCR deactivated!")
                        # Force a rerun to update the navigation
                        st.rerun()
                    except Exception as e:
                        st.error(f"Error updating Tesseract settings: {e}")

        # Tesseract installation status
        if tesseract_enabled:
            st.markdown("#### Installation Status")

            try:
                # Import the Tesseract bridge to check status
                from pageplus.gui.cli_bridges.tesseract import TesseractBridge
                tesseract_bridge = TesseractBridge()

                status = tesseract_bridge.check_tesseract_installation()

                # Show available models
                if status["tesseract_installed"]:
                    models = tesseract_bridge.get_available_models(model_path)
                    if models:
                        with st.expander("Available Language Models", expanded=False):
                            # Create a dataframe with model information
                            import pandas as pd

                            # Process models to extract clean names and full paths
                            model_data = []
                            for model in models:
                                clean_name = model.replace('.traineddata', '')
                                model_data.append({
                                    "Language Code": clean_name,
                                    "Full Path": model,
                                    "Status": "Available"
                                })

                            # Sort by language code
                            model_data.sort(key=lambda x: x["Language Code"])

                            # Create dataframe
                            df = pd.DataFrame(model_data)

                            # Display the dataframe
                            st.dataframe(
                                df,
                                hide_index=True,
                                column_config={
                                    "Language Code": st.column_config.TextColumn(
                                        "Language Code",
                                        help="Language code used in Tesseract commands"
                                    ),
                                    "Full Path": st.column_config.TextColumn(
                                        "Full Path",
                                        help="Complete path to the model file"
                                    ),
                                    "Status": st.column_config.TextColumn(
                                        "Status",
                                        help="Model availability status"
                                    )
                                }
                            )

                            st.info(f"Total models available: {len(models)}")

                if status["status"] == "ready":
                    st.success("✅ Tesseract OCR is ready to use")
                    if status["tesseract_version"]:
                        st.info(f"Tesseract version: {status['tesseract_version']}")
                elif status["status"] == "missing_tesserocr":
                    st.warning("⚠️ Tesseract is installed but tesserocr Python package is missing")
                    if st.button("Install tesserocr"):
                        try:
                            if tesseract_bridge.install():
                                st.success("tesserocr installed successfully!")
                                st.rerun()
                            else:
                                st.error("Failed to install tesserocr")
                        except Exception as e:
                            st.error(f"Error installing tesserocr: {e}")
                elif status["status"] == "missing_tesseract":
                    st.error("❌ Tesseract is not installed on the system")
                    st.info("Please install Tesseract OCR on your system first")

            except Exception as e:
                st.error(f"Error checking Tesseract status: {e}")

        # Kraken OCR Settings
        st.markdown("---")
        st.markdown("### 🐙 Kraken OCR")

        # Check if Kraken is configured
        from pageplus.gui.cli_bridges.kraken import KrakenBridge
        kraken_bridge = KrakenBridge()

        st.markdown("#### Python Environment Configuration")
        st.info("""
        Kraken OCR runs in a separate Python environment to avoid dependency conflicts.
        Please provide the path to the Python executable where Kraken is installed.
        """)

        # Show installation instructions
        with st.expander("📖 Installation Instructions", expanded=False):
            st.markdown(kraken_bridge.get_installation_instructions())

        # Get current configuration
        current_python_path = kraken_bridge.get_python_env_path()
        current_path_str = str(current_python_path) if current_python_path else ""

        col_path, col_pick = st.columns([3, 1])

        with col_path:
            python_path = st.text_input(
                "Kraken Python Executable Path",
                value=current_path_str,
                placeholder="/path/to/kraken_env/bin/python",
                help="Path to the Python executable in your Kraken environment",
                key="kraken_python_path_input"
            )

        with col_pick:
            if st.button("📁 Browse", help="Select Python executable", key="pick_kraken_python"):
                st.session_state.show_kraken_python_picker = True

        # File picker
        if st.session_state.get("show_kraken_python_picker", False):
            from pageplus.gui.utils.picker import pick_files
            selected_files = pick_files(
                initial_dir=str(Path.home()),
                filetypes=[("Python Executable", "python*"), ("All files", "*")],
                key="kraken_python"
            )
            if selected_files is not None:
                st.session_state.show_kraken_python_picker = False
                if selected_files:
                    st.session_state.kraken_new_python_path = selected_files[0]
                st.rerun()

        # Update python_path if a new path was selected
        if st.session_state.get("kraken_new_python_path"):
            python_path = st.session_state.kraken_new_python_path

        # Save and Clear buttons
        col_save, col_clear, col_status = st.columns([1, 1, 2])

        with col_save:
            if st.button("💾 Save Path", help="Save the Kraken Python path", use_container_width=True, key="save_kraken_path"):
                if python_path:
                    result = kraken_bridge.set_python_env(Path(python_path))
                    if result.get("success"):
                        # Clear the temporary new path
                        if "kraken_new_python_path" in st.session_state:
                            del st.session_state.kraken_new_python_path
                        st.success(result.get("message"))
                        st.rerun()
                    else:
                        st.error(f"❌ {result.get('error')}")
                        if result.get("hint"):
                            st.info(result.get("hint"))
                else:
                    st.error("Please provide a Python executable path")

        with col_clear:
            if current_python_path:
                if st.button("🗑️ Clear", help="Clear the Kraken configuration", use_container_width=True, key="clear_kraken_path"):
                    result = kraken_bridge.clear_python_env()
                    if result.get("success"):
                        if "kraken_new_python_path" in st.session_state:
                            del st.session_state.kraken_new_python_path
                        st.success(result.get("message"))
                        st.rerun()

        with col_status:
            if python_path != current_path_str:
                st.warning("⚠️ Path has been modified. Click 'Save Path' to apply.")
            elif current_python_path and current_python_path.exists():
                st.success("✅ Path is valid and saved")

        # Model Path Configuration
        st.markdown("#### Model Path Configuration")
        current_model_path = settings.get("KRAKEN_MODEL_PATH", "")

        col_path, col_pick = st.columns([3, 1])

        with col_path:
            kraken_model_path = st.text_input(
                "Kraken Model Directory",
                value=current_model_path,
                placeholder="/path/to/kraken/models",
                help="Path to the directory containing Kraken model files (.mlmodel)",
                key="kraken_model_path_input"
            )

        with col_pick:
            if st.button("📁 Pick Directory", help="Select directory using file picker", key="pick_kraken_model_dir"):
                st.session_state.show_kraken_model_dir_picker = True

        # Directory picker
        if st.session_state.get("show_kraken_model_dir_picker", False):
            from pageplus.gui.utils.picker import pick_directory
            selected_path = pick_directory(
                current_model_path if current_model_path else str(Path.home()),
                key="kraken_model_dir"
            )
            if selected_path is not None:
                st.session_state.show_kraken_model_dir_picker = False
                if selected_path:
                    st.session_state.kraken_new_model_path = selected_path
                st.rerun()

        # Update model_path if a new path was selected
        if st.session_state.get("kraken_new_model_path"):
            kraken_model_path = st.session_state.kraken_new_model_path

        # Save model path setting
        col_save, col_status = st.columns([1, 3])
        with col_save:
            if st.button("💾 Save Model Path", help="Save the Kraken model path setting", use_container_width=True, key="save_kraken_model_path"):
                try:
                    settings.set("KRAKEN_MODEL_PATH", kraken_model_path)
                    # Clear the temporary new path
                    if "kraken_new_model_path" in st.session_state:
                        del st.session_state.kraken_new_model_path
                    st.success("Model path saved successfully!")
                    st.rerun()
                except Exception as e:
                    st.error(f"Error saving model path: {e}")

        with col_status:
            if kraken_model_path != current_model_path:
                st.warning("⚠️ Path has been modified. Click 'Save Model Path' to apply changes.")
            elif kraken_model_path and Path(kraken_model_path).exists():
                # Show available models
                available_models = kraken_bridge.get_available_models(Path(kraken_model_path))
                if available_models:
                    st.success(f"✅ Valid path with {len(available_models)} model(s)")
                else:
                    st.info("📁 Path is valid but no .mlmodel files found")
            elif kraken_model_path:
                st.warning("⚠️ Path does not exist")

        # Show installation status if configured
        if current_python_path:
            st.markdown("#### Installation Status")
            verification = kraken_bridge.verify_installation()

            if verification.get("installed"):
                kraken_exe = verification.get("kraken_executable")

                if kraken_exe:
                    st.success("✅ Kraken is properly installed and ready to use")
                    st.code(f"Python path: {verification.get('python_path')}\nKraken CLI: {kraken_exe}", language="text")
                else:
                    st.warning("⚠️ Kraken module installed but CLI executable not found")
                    st.code(f"Python path: {verification.get('python_path')}", language="text")
                    st.info("The Kraken CLI executable should be in the same directory as the Python executable.")

                # Show warning if any
                if verification.get("warning"):
                    st.warning(verification.get("warning"))

                # Show model directory helper
                with st.expander("📁 Model Directory", expanded=False):
                    st.info("""
                    Kraken models (.mlmodel files) should be stored in a directory.
                    You'll need to specify this directory when using Kraken OCR.

                    You can download Kraken models from:
                    - https://zenodo.org/communities/ocr_models
                    - https://github.com/mittagessen/kraken
                    """)
            else:
                st.error(f"❌ {verification.get('error')}")
                st.info("Please install Kraken in the specified environment:")
                st.code(f"{current_python_path} -m pip install kraken", language="bash")

        # Debug info
        with st.expander("Debug Info"):
            st.write(f"Configured Python path: {current_path_str or 'Not configured'}")
            st.write(f"Path exists: {current_python_path.exists() if current_python_path else 'N/A'}")
            st.write(f"Is configured: {kraken_bridge.is_configured()}")

    with tab_backup:
        st.subheader("Export Settings")

        try:
            exportable_files = cli_bridge.get_export_files()
            selected_files_to_export = st.multiselect(
                "Select files to export",
                options=list(exportable_files.keys()),
                default=list(exportable_files.keys())
            )

            if st.button("Export Selected Files"):
                if selected_files_to_export:
                    selected_file_paths = [exportable_files[fname] for fname in selected_files_to_export]
                    zip_bytes = cli_bridge.export_settings(selected_file_paths)

                    st.download_button(
                        label="Download Settings Backup",
                        data=zip_bytes,
                        file_name=f"pageplus_settings_backup_{datetime.now().strftime('%Y%m%d_%H%M%S')}.zip",
                        mime="application/zip"
                    )
                else:
                    st.warning("Please select at least one file to export.")

        except Exception as e:
            st.error(f"Could not get files for export: {e}")

        from pageplus.utils.constants import USER_DATA_DIR
        st.caption("Storage directory: " + str(USER_DATA_DIR))
        st.divider()

        st.subheader("Import Settings")
        uploaded_file = st.file_uploader("Upload settings backup (.zip)", type="zip")

        if uploaded_file:
            try:
                zip_buffer = io.BytesIO(uploaded_file.getvalue())
                with zipfile.ZipFile(zip_buffer, "r") as zip_ref:
                    files_in_zip = zip_ref.namelist()

                selected_files_to_import = st.multiselect(
                    "Select files to import from the backup",
                    options=files_in_zip,
                    default=files_in_zip
                )

                import_mode = st.radio(
                    "Import mode",
                    options=["overwrite", "update"],
                    format_func=lambda x: "Overwrite existing" if x == "overwrite" else "Add new only",
                    index=1
                )

                if st.button("Import Selected Files"):
                    if selected_files_to_import:
                        try:
                            cli_bridge.import_settings(
                                uploaded_file.getvalue(),
                                selected_files_to_import,
                                import_mode
                            )
                            st.success("Settings imported successfully! Restart PagePlus for all changes to take effect.")
                            st.rerun()
                        except Exception as e:
                            st.error(f"Error importing settings: {e}")
                    else:
                        st.warning("Please select at least one file to import.")

            except Exception as e:
                st.error(f"Failed to process uploaded file: {e}")
