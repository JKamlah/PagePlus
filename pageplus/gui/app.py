from pageplus.utils.logger import setup_logger, configure_external_logging

logger = setup_logger()
# Configure external logging
configure_external_logging()

from pageplus.gui.views.gemini import show_gemini
from pageplus.gui.views.modification import show_modification
from pageplus.gui.views.settings import show_settings
from pageplus.gui.views.export import show_export
from pageplus.gui.views.validation import show_validation
from pageplus.gui.views.analysis import show_analysis
from pageplus.gui.views.workspace import show_workspace
from pageplus.gui.views.load_files import LoadFilesPage
from pageplus.gui.views.escriptorium import show_escriptorium
from pageplus.gui.views.transkribus import show_transkribus
from pageplus.gui.views.mets import show_mets
from pageplus.gui.views.evaluation import show_evaluation
from pageplus.gui.utils.settings import Settings
from pageplus.gui.cli_bridges.gemini import GeminiBridge
from pageplus.gui.cli_bridges.escriptorium import EscriptoriumBridge
from pageplus.gui.cli_bridges.transkribus import TranskribusBridge
from pageplus.gui.cli_bridges.mets import MetsBridge
from pageplus.gui.cli_bridges.dinglehopper import DinglehopperBridge
from pageplus.gui.cli_bridges import (
    CLIBridge,
    AnalysisBridge,
    ExportBridge,
    SettingsBridge,
    ValidationBridge,
    WorkspaceBridge,
    ModificationBridge,
)
import streamlit as st
from pathlib import Path
from typing import List
import json
import dotenv
import base64
from pageplus.gui.utils.undo import UndoManager

# Initialize settings
settings = Settings()

# Set page config
st.set_page_config(
    page_title="PagePlus GUI",
    page_icon="📄",
    layout="wide"
)

# Constants
STORAGE_DIR = Path(__file__).parent / "storage"
STORAGE_FILE = STORAGE_DIR / "loaded_files.json"
PROJECT_ROOT = Path(__file__).resolve().parents[2]
ENV_FILE = PROJECT_ROOT / ".env"
LOGO_PATH = PROJECT_ROOT / 'assets/Tight_PagePlus_Logo.png'

# Read and encode the image
with open(LOGO_PATH, "rb") as img_file:
    LOGO = base64.b64encode(img_file.read()).decode()


def ensure_storage_dir():
    """Ensure the storage directory exists."""
    STORAGE_DIR.mkdir(parents=True, exist_ok=True)


def save_loaded_files(files: List[Path]):
    """Save the list of loaded files to persistent storage."""
    try:
        ensure_storage_dir()
        with open(STORAGE_FILE, 'w') as f:
            json.dump([str(file) for file in files], f, indent=4)
    except Exception as e:
        logger.error(f"Error saving loaded files: {str(e)}")


def load_previous_files() -> List[Path]:
    """Load the previously loaded files from persistent storage."""
    try:
        if STORAGE_FILE.exists():
            with open(STORAGE_FILE, 'r') as f:
                file_paths = json.load(f)
                return [Path(path)
                        for path in file_paths if Path(path).exists()]
    except Exception as e:
        logger.error(f"Error loading previous files: {str(e)}")
    return []


def load_env_settings() -> dict:
    """Load settings from .env file."""
    try:
        return dotenv.dotenv_values(ENV_FILE)
    except Exception as e:
        logger.error(f"Error loading .env file: {str(e)}")
        return {}


def save_env_settings(settings: dict):
    """Save settings to .env file."""
    try:
        with open(ENV_FILE, 'w') as f:
            for key, value in settings.items():
                f.write(f"{key}={value}\n")
    except Exception as e:
        logger.error(f"Error saving .env file: {str(e)}")


def main():
    """Run the PagePlus application."""
    # Initialize session state
    if 'loaded_files' not in st.session_state:
        st.session_state.loaded_files = load_previous_files()

    # Initialize bridges
    if 'bridges' not in st.session_state:
        st.session_state.bridges = {
            'base': CLIBridge(),
            'analysis': AnalysisBridge(),
            'export': ExportBridge(),
            'settings': SettingsBridge(),
            'validation': ValidationBridge(),
            'workspace': WorkspaceBridge(),
            'modification': ModificationBridge(),
            'gemini': GeminiBridge(),
            'escriptorium': EscriptoriumBridge(),
            'transkribus': TranskribusBridge(),
            'mets': MetsBridge(),
            'dinglehopper': DinglehopperBridge(),
        }

    # Initialize pages
    load_page = LoadFilesPage(st.session_state.bridges['workspace'])

    # Sidebar navigation
    st.sidebar.markdown(
        f"""
        <div style="text-align: left;">
            <img src="data:image/png;base64,{LOGO}" width="100">
        </div>
        """,
        unsafe_allow_html=True
    )
    st.sidebar.title("Navigation")
    page = st.sidebar.radio(
        "Select Page",
        ["✨ Home",
         "📂 Input",
         "📜 eScriptorium",
         "🐇 Transkribus",
         "📚 METS",
         "🔍 Analytics",
         "✅ Validation",
         "📊 Evaluation",
         "🛠️ Modification",
         "🌟 Gemini",
         "📤 Export",
         "🗂️ Workspace",
         "⚙️ Settings"]
    )

    # Display selected page
    if page == "✨ Home":
        show_home()
    elif page == "📂 Input":
        load_page.show()
        st.session_state.loaded_files = load_page.get_loaded_files()
        save_loaded_files(st.session_state.loaded_files)
    elif page == "📜 eScriptorium":
        show_escriptorium(st.session_state.bridges['escriptorium'])
    elif page == "🐇 Transkribus":
        show_transkribus(st.session_state.bridges['transkribus'])
    elif page == "📚 METS":
        show_mets(st.session_state.bridges['mets'])
    elif page == "🔍 Analytics":
        if not st.session_state.loaded_files:
            st.warning("Please load files first in the 'Input' page.")
        else:
            show_analysis(st.session_state.bridges['analysis'])
    elif page == "✅ Validation":
        if not st.session_state.loaded_files:
            st.warning("Please load files first in the 'Input' page.")
        else:
            show_validation(st.session_state.bridges['validation'])
    elif page == "📊 Evaluation":
        show_evaluation()
    elif page == "🛠️ Modification":
        if not st.session_state.loaded_files:
            st.warning("Please load files first in the 'Input' page.")
        else:
            show_modification(st.session_state.bridges['modification'])
    elif page == "🌟 Gemini":
        if not st.session_state.loaded_files:
            st.warning("Please load files first in the 'Input' page.")
        else:
            show_gemini(st.session_state.bridges['gemini'])
    elif page == "📤 Export":
        if not st.session_state.loaded_files:
            st.warning("Please load files first in the 'Input' page.")
        else:
            show_export(st.session_state.bridges['export'])
    elif page == "🗂️ Workspace":
        show_workspace(st.session_state.bridges['workspace'])
    elif page == "⚙️ Settings":
        show_settings(st.session_state.bridges['settings'])

    # Undo History
    undo_states = UndoManager.get_undo_states()
    if undo_states:
        st.sidebar.subheader("Undo History")

        # Create a list of descriptions for the dropdown
        undo_options = [f"Undo: {state.description}" for state in undo_states]

        # Add a placeholder at the beginning of the list
        undo_options.insert(0, "Select an action to undo...")

        selected_action = st.sidebar.selectbox(
            "Select an action to undo",
            options=undo_options,
            index=0,
            key="undo_selectbox"
        )

        if selected_action != "Select an action to undo...":
            # Find the index of the selected action
            action_index = undo_options.index(selected_action) - 1  # Adjust for the placeholder

            # A button to confirm the action
            if st.sidebar.button("Confirm Undo", key=f"confirm_undo_{action_index}"):
                restored_action = UndoManager.restore_state(action_index)
                if restored_action:
                    st.sidebar.success(f"Restored state before: '{restored_action}'")
                    # Reset the selectbox after the action
                    # st.session_state.undo_selectbox = "Select an action to undo..."
                    st.rerun()


def show_home():
    """Display the home page."""
    st.markdown(
        f"""
        <div style="text-align: left;">
            <img src="data:image/png;base64,{LOGO}" width="200">
        </div>
        """,
        unsafe_allow_html=True
    )
    st.header("✨ Welcome to PagePlus ✨")
    st.write("""
    This is the GUI interface for PagePlus, a PAGE-XML file multi-tool.  
    Disclaimer: A lot of the functionality is still under development and results should be checked carefully.
    
    Use the sidebar to navigate between different sections:  
    📂 Input: Load PAGE-XML files to process  
    📜 eScriptorium: Work with eScriptorium  
    🐇 Transkribus: Work with Transkribus  
    📚 METS Tools: Work with METS/MODS files   
    🔍 Analytics: Analyze the content of PAGE-XML files  
    ✅ Validation: Validate PAGE-XML files  
    📊 Evaluation: Evaluate PAGE-XML files  
    🛠️ Modification: Modify processed documents  
    🖋️ OCR: Do OCR on PAGE-XML files with several OCR engines  
    🤖 LLM: Perform different tasks on PAGE-XML files with LLMs  
    🌟 Gemini: Use Gemini to process images and validate PAGE-XML output  
    📤 Export: Export PAGE-XML files to different formats (ALTO, PDF, Text)  
    🗂️ Workspace: Manage workspaces  
    ⚙️ Settings: Configure application settings  
    """)


if __name__ == "__main__":
    main()
