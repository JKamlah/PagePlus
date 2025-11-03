from pageplus.utils.logger import setup_logger, configure_external_logging

logger = setup_logger()
# Configure external logging
configure_external_logging()

import os
import signal
import time
import sys
# Disable Streamlit browser usage stats
os.environ["STREAMLIT_BROWSER_GATHERUSAGESTATS"] = "false"
os.environ["STREAMLIT_EMAIL"] = ""

import streamlit as st
from pathlib import Path
import threading
from pageplus.utils.constants import GUI_STORAGE_DIR, ENV_FILE, LOGO_PATH, LOADING_PATH
from pageplus.utils.filelock import AtomicFileLock
from pageplus.utils.monitor import monitor_sessions
from pageplus.gui.utils.settings import Settings

# Constants
STORAGE_FILE = GUI_STORAGE_DIR / "loaded_files.json"

def _is_monitor_running(lock_file: Path) -> bool:
    """
    Check if the monitor is already running by examining the lock file.

    Args:
        lock_file: Path to the lock file

    Returns:
        bool: True if monitor is already running, False otherwise
    """
    if not lock_file.exists():
        return False

    try:
        # Read the PID from the lock file
        with open(lock_file, 'r') as f:
            pid_str = f.read().strip()

        if not pid_str.isdigit():
            return False

        pid = int(pid_str)

        # Check if the process is still running
        try:
            os.kill(pid, 0)  # This will raise an exception if process doesn't exist
            return True
        except (OSError, ProcessLookupError):
            # Process doesn't exist, clean up stale lock file
            lock_file.unlink(missing_ok=True)
            return False

    except (OSError, IOError, ValueError):
        # Error reading lock file, assume not running
        lock_file.unlink(missing_ok=True)
        return False


# Place a container at the top
loading = st.empty()

# Show the loading GIF
with loading.container():
    st.markdown(
        """
        <style>
            .stApp {
                background-color: black;
            }
        </style>
        """,
        unsafe_allow_html=True,
    )
    _, col, _ = st.columns([1, 1, 1])
    col.image(LOADING_PATH)

from pageplus.gui.views import (
    workspace,
    load_files,
    viewer,
    gemini,
    guidelines,
    modification,
    validation,
    escriptorium,
    transkribus,
    evaluation,
    analysis,
    export,
    tesseract,
    kraken,
    kraken_new,
    mets,
    settings as settings_view,
    iiif
)
from pageplus.gui.cli_bridges.gemini import GeminiBridge
from pageplus.gui.cli_bridges.escriptorium import EscriptoriumBridge
from pageplus.gui.cli_bridges.transkribus import TranskribusBridge
from pageplus.gui.cli_bridges.mets import MetsBridge
from pageplus.gui.cli_bridges.dinglehopper import DinglehopperBridge
from pageplus.gui.cli_bridges.iiif import IIIFBridge
from pageplus.gui.cli_bridges.tesseract import TesseractBridge
from pageplus.gui.cli_bridges.kraken import KrakenBridge
from pageplus.gui.cli_bridges import (
    CLIBridge,
    AnalysisBridge,
    ExportBridge,
    SettingsBridge,
    ValidationBridge,
    WorkspaceBridge,
    ModificationBridge,
)

from typing import List
import json
import dotenv
import base64
from pageplus.gui.utils.undo import UndoManager

# Clear the placeholder and show main app
loading.empty()

# Set page config
st.set_page_config(
    page_title="PagePlus GUI",
    page_icon="📄",
    layout="wide"
)

# Initialize settings
settings = Settings()

# Read and encode the image
with open(LOGO_PATH, "rb") as img_file:
    LOGO = base64.b64encode(img_file.read()).decode()


def ensure_storage_dir():
    """Ensure the storage directory exists."""
    GUI_STORAGE_DIR.mkdir(parents=True, exist_ok=True)


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
    # Start the session monitor thread only once per server instance
    lock_file = GUI_STORAGE_DIR / "session_monitor.lock"

    # Check if monitor is already running
    if not _is_monitor_running(lock_file):
        # Start monitor thread with lock file - it will handle the locking internally
        monitor_thread = threading.Thread(target=monitor_sessions, args=(lock_file,), daemon=True)
        monitor_thread.start()
        logger.info("Session monitor thread started")
    else:
        logger.debug("Session monitor is already running, skipping thread creation")

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
            'iiif': IIIFBridge(),
            'tesseract': TesseractBridge(),
            'kraken': KrakenBridge(),
            'kraken_new': KrakenBridge,  # Added Kraken OCR New
        }

    # Initialize pages
    load_page = load_files.LoadFilesPage(st.session_state.bridges['workspace'])

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

    # Initialize session state for navigation
    if 'main_page_selection' not in st.session_state:
        st.session_state.main_page_selection = "✨ Home"
    if 'external_page_selection' not in st.session_state:
        st.session_state.external_page_selection = None

    def clear_other_nav(nav_type):
        if nav_type == 'main' and st.session_state.external_page_selection is not None:
            st.session_state.external_page_selection = None
        elif nav_type == 'external' and st.session_state.main_page_selection is not None:
            st.session_state.main_page_selection = None

    # Check if Tesseract OCR is activated
    settings = Settings()
    tesseract_activated = settings.get("PAGEPLUS_OCR_TESSERACT", "False") == "True"

    # Check if Kraken OCR is configured
    from pageplus.cli.ocr_kraken import get_kraken_python_path
    kraken_configured = get_kraken_python_path() is not None

    main_pages = ["✨ Home", "🗂️ Workspace", "📂 Input", "🖼️ Viewer", "🔍 Analytics", "📝 Guidelines", "✅ Validation",
                  "📊 Evaluation", "🛠️ Modification", "🌟 Gemini", "📤 Export",
                  "⚙️ Settings"]

    # Add OCR pages if configured/activated
    ocr_insert_position = -2  # Position before Settings
    if tesseract_activated:
        main_pages.insert(ocr_insert_position, "🔤 Tesseract OCR")
    if kraken_configured:
        main_pages.insert(ocr_insert_position, "🐙 Kraken OCR")

    st.sidebar.radio(
        "Select Page",
        main_pages,
        key='main_page_selection',
        on_change=lambda: clear_other_nav('main')
    )

    with st.sidebar.expander("External Resources"):
        external_pages = ["📜 eScriptorium", "🐇 Transkribus", "🏛️ METS", "📑 IIIF"]
        st.radio(
            "Select External Ressource Page",
            external_pages,
            key='external_page_selection',
            on_change=lambda: clear_other_nav('external')
        )
    page = st.session_state.main_page_selection or st.session_state.external_page_selection

    # Display selected page
    if page == "✨ Home":
        show_home()
    elif page == "📂 Input":
        load_page.show()
        st.session_state.loaded_files = load_page.get_loaded_files()
        save_loaded_files(st.session_state.loaded_files)
    elif page == "📜 eScriptorium":
        escriptorium.show_escriptorium(st.session_state.bridges['escriptorium'])
    elif page == "🐇 Transkribus":
        transkribus.show_transkribus(st.session_state.bridges['transkribus'])
    elif page == "🏛️ METS":
        mets.show_mets(st.session_state.bridges['mets'])
    elif page == "📑 IIIF":
        iiif.show_iiif_downloader(st.session_state.bridges['iiif'])
    elif page == "🖼️ Viewer":
        if not st.session_state.loaded_files:
            st.warning("Please load files first in the 'Input' page.")
        else:
            viewer.show_viewer()
    elif page == "🔍 Analytics":
        if not st.session_state.loaded_files:
            st.warning("Please load files first in the 'Input' page.")
        else:
            analysis.show_analysis(st.session_state.bridges['analysis'])
    elif page == "📝 Guidelines":
        if not st.session_state.loaded_files:
            st.warning("Please load files first in the 'Input' page.")
        else:
            guidelines.show_guidelines()
    elif page == "✅ Validation":
        if not st.session_state.loaded_files:
            st.warning("Please load files first in the 'Input' page.")
        else:
            validation.show_validation(st.session_state.bridges['validation'])
    elif page == "📊 Evaluation":
        evaluation.show_evaluation()
    elif page == "🛠️ Modification":
        if not st.session_state.loaded_files:
            st.warning("Please load files first in the 'Input' page.")
        else:
            modification.show_modification(st.session_state.bridges['modification'])
    elif page == "🔤 Tesseract OCR":
        tesseract.show_tesseract(st.session_state.bridges['tesseract'])
    elif page == "🐙 Kraken OCR":
        kraken.show_kraken(st.session_state.bridges['kraken'])
    elif page == "🌟 Gemini":
        if not st.session_state.loaded_files:
            st.warning("Please load files first in the 'Input' page.")
        else:
            gemini.show_gemini(st.session_state.bridges['gemini'])
    elif page == "📤 Export":
        if not st.session_state.loaded_files:
            st.warning("Please load files first in the 'Input' page.")
        else:
            export.show_export(st.session_state.bridges['export'])
    elif page == "🗂️ Workspace":
        workspace.show_workspace(st.session_state.bridges['workspace'])
    elif page == "⚙️ Settings":
        settings_view.show_settings(st.session_state.bridges['settings'])
    # Undo History
    undo_states = UndoManager.get_undo_states()
    if undo_states:
        st.sidebar.subheader("🔄 Undo History")

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

    # Exit button
    st.sidebar.markdown("---")

    def shutdown():
        # Target URL
        dotenv.load_dotenv()
        target_url = os.environ.get("PAGEPLUS_REDIRECT_URL", "https://google.com")
        print(f"Shutting down and redirecting to {target_url}")

        # HTML meta tag to redirect instantly
        redirect_html = f"""<meta http-equiv="refresh" content="0; url={target_url}">"""
        st.markdown(redirect_html, unsafe_allow_html=True)
        time.sleep(1)
        # Stop the server
        os.kill(os.getpid(), signal.SIGTERM)
    if st.sidebar.button("Shutdown", icon=":material/power_settings_new:"):
        shutdown()
    if st.sidebar.button("Reboot", icon=":material/refresh:"):
        import subprocess
        shutdown()
        subprocess.run(["pageplus-gui"])


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
    🖼️ Viewer: View PAGE-XML files with images  
    🔍 Analytics: Analyze the content of PAGE-XML files  
    📜 Guidelines: Evaluate and normalize text based on guideline profiles  
    ✅ Validation: Validate PAGE-XML files  
    📊 Evaluation: Evaluate PAGE-XML files  
    🛠️ Modification: Modify processed documents  
    🤖 LLM: Perform different tasks on PAGE-XML files with LLMs  
    🌟 Gemini: Use Gemini to process images and validate PAGE-XML output  
    🔤 Tesseract OCR: Do OCR on PAGE-XML files with Tesseract (if activated)  
    🐙 Kraken OCR: Do OCR on PAGE-XML files with Kraken (if activated)  
    📤 Export: Export PAGE-XML files to different formats (ALTO, PDF, Text)  
    🗂️ Workspace: Manage workspaces  
    ⚙️ Settings: Configure application settings

    External Resources:  
    📜 eScriptorium: Work with eScriptorium  
    🐇 Transkribus: Work with Transkribus  
    🏛️ METS Tools: Work with METS/MODS files   
    📑 IIIF: Download images from IIIF manifests  
    """)


if __name__ == "__main__":
    main()
