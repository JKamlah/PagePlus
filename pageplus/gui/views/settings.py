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
        # OCR Settings
        st.subheader("OCR Settings")
        tesseract_path = st.text_input(
            "Tesseract Model Path",
            value=settings.get("TESSERACT_MODEL_PATH", "")
        )
        kraken_path = st.text_input(
            "Kraken Model Path",
            value=settings.get("KRAKEN_MODEL_PATH", "")
        )

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
        # Save settings
        if st.button("Save Settings"):
            try:
                # Update settings
                settings.update({
                    "OPENAI_API_KEY": openai_key,
                    "GEMINI_API_KEY": gemini_key,
                    "TESSERACT_MODEL_PATH": tesseract_path,
                    "KRAKEN_MODEL_PATH": kraken_path,
                    "OUTPUT_DIRECTORY": output_dir,
                    "PAGEPLUS_REDIRECT_URL": redirect_url,
                    "PAGEPLUS_USER_AGENT": user_agent,
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
            selected_path = pick_directory(current_model_path)
            if selected_path:
                st.session_state.tesseract_new_path = selected_path
                st.session_state.show_directory_picker = False
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

        # Other OCR engines can be added here in the future
        st.markdown("### Other OCR Engines")
        st.info("Additional OCR engines will be added in future updates.")

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
