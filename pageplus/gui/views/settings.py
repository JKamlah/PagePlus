import streamlit as st
import dotenv
from pathlib import Path


def show_settings(cli_bridge):
    """Display settings page with configuration options."""
    st.title("⚙️ Settings")
    
    # Load current settings
    env_file = Path(__file__).parent.parent.parent / ".env"
    current_settings = dotenv.dotenv_values(env_file)
    
    # API Keys
    st.subheader("API Keys")
    openai_key = st.text_input(
        "OpenAI API Key",
        value=current_settings.get("OPENAI_API_KEY", ""),
        type="password"
    )
    gemini_key = st.text_input(
        "Gemini API Key",
        value=current_settings.get("GEMINI_API_KEY", ""),
        type="password"
    )
    
    # OCR Settings
    st.subheader("OCR Settings")
    tesseract_path = st.text_input(
        "Tesseract Model Path",
        value=current_settings.get("TESSERACT_MODEL_PATH", "")
    )
    kraken_path = st.text_input(
        "Kraken Model Path",
        value=current_settings.get("KRAKEN_MODEL_PATH", "")
    )
    
    # Output Settings
    st.subheader("Output Settings")
    output_dir = st.text_input(
        "Default Output Directory",
        value=current_settings.get("OUTPUT_DIR", "")
    )
    
    # Save settings
    if st.button("Save Settings"):
        try:
            # Update settings
            settings = {
                "OPENAI_API_KEY": openai_key,
                "GEMINI_API_KEY": gemini_key,
                "TESSERACT_MODEL_PATH": tesseract_path,
                "KRAKEN_MODEL_PATH": kraken_path,
                "OUTPUT_DIR": output_dir
            }
            
            # Save to .env file
            with open(env_file, "w") as f:
                for key, value in settings.items():
                    if value:  # Only write non-empty values
                        f.write(f"{key}={value}\n")
            
            st.success("Settings saved successfully!")
        except Exception as e:
            st.error(f"Error saving settings: {str(e)}") 