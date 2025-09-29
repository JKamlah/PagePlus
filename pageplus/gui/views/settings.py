import streamlit as st
import zipfile
import io
from datetime import datetime

from pageplus.gui.utils.settings import Settings


def show_settings(cli_bridge):
    """Display settings page with configuration options."""
    st.title("⚙️ Settings")

    # Initialize settings
    settings = Settings()

    tab_credentials, tab_system, tab_backup = st.tabs(["Credentials", "System", "Backup & Restore"])

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
