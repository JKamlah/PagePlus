import streamlit as st

from pageplus.gui.utils.settings import Settings


def show_settings(cli_bridge):
    """Display settings page with configuration options."""
    st.title("⚙️ Settings")

    # Initialize settings
    settings = Settings()

    tab_credentials, tab_system = st.tabs(["Credentials", "System"])

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

   
