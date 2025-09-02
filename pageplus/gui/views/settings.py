import streamlit as st
from pageplus.gui.utils.settings import Settings


def show_settings(cli_bridge):
    """Display settings page with configuration options."""
    st.title("⚙️ Settings")
    
    # Initialize settings
    settings = Settings()
    
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
    
    # Save settings
    if st.button("Save Settings"):
        try:
            # Update settings
            settings.update({
                "OPENAI_API_KEY": openai_key,
                "GEMINI_API_KEY": gemini_key,
                "TESSERACT_MODEL_PATH": tesseract_path,
                "KRAKEN_MODEL_PATH": kraken_path,
                "OUTPUT_DIRECTORY": output_dir
            })
            
            st.success("Settings saved successfully!")
        except Exception as e:
            st.error(f"Error saving settings: {str(e)}") 