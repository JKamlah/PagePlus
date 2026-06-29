"""File and directory picker utilities supporting PyQt6 and Web-based pickers."""
import argparse
import json
import sys
from pathlib import Path
from typing import List, Tuple, Optional
import subprocess
import streamlit as st


def _run_picker_script(command: List[str]) -> List[str]:
    """Run the picker script as a subprocess and return the output."""
    try:
        process = subprocess.run(
            command,
            capture_output=True,
            text=True,
            check=True
        )
        selected_paths = json.loads(process.stdout.strip())
        return selected_paths
    except subprocess.CalledProcessError as e:
        # Avoid showing error in GUI as it's handled by the calling view
        print(f"Picker script failed: {e.stderr}", file=sys.stderr)
    except json.JSONDecodeError:
        print("Picker script returned invalid data.", file=sys.stderr)
    except Exception as e:
        print(f"An unexpected error occurred: {e}", file=sys.stderr)
    return []


@st.dialog("Select Directory", width="large")
def _show_web_directory_dialog(key: str, initial_dir: Optional[str] = None):
    """Streamlit dialog for web-based directory selection."""
    state_key = f"web_picker_curr_dir_{key}"
    if state_key not in st.session_state:
        if initial_dir and Path(initial_dir).is_dir():
            st.session_state[state_key] = str(Path(initial_dir).resolve())
        else:
            st.session_state[state_key] = str(Path.home().resolve())

    current_dir = Path(st.session_state[state_key])

    st.subheader("📁 Select Directory")
    
    col_path, col_btn_up = st.columns([5, 1])
    with col_path:
        new_path_str = st.text_input(
            "Current Folder Path:",
            value=str(current_dir),
            key=f"web_picker_input_{key}",
            help="Type path and press Enter to navigate"
        )
    with col_btn_up:
        st.markdown("<div style='height: 28px;'></div>", unsafe_allow_html=True)
        if st.button("⬆️ Up", key=f"web_picker_up_{key}", use_container_width=True):
            parent = current_dir.parent
            if parent != current_dir:
                st.session_state[state_key] = str(parent)
                st.rerun()

    # Navigate if path changed manually
    if new_path_str and Path(new_path_str).is_dir() and Path(new_path_str).resolve() != current_dir.resolve():
        st.session_state[state_key] = str(Path(new_path_str).resolve())
        st.rerun()

    # List items
    try:
        items = list(current_dir.iterdir())
    except Exception as e:
        st.error(f"Cannot read directory: {e}")
        items = []

    dirs = sorted([d for d in items if d.is_dir()], key=lambda x: x.name.lower())

    st.markdown("---")
    
    # Confirm current selection
    if st.button(f"✅ Select '{current_dir.name}'", type="primary", use_container_width=True, key=f"web_picker_confirm_{key}"):
        st.session_state[f"{key}_selected"] = str(current_dir)
        st.rerun()

    st.markdown("**Subdirectories:**")
    if not dirs:
        st.info("No subdirectories found.")
    else:
        # Render subdirs in a list/table format
        for d in dirs:
            if st.button(f"📁 {d.name}", key=f"web_picker_dir_{d.name}_{key}", use_container_width=True):
                st.session_state[state_key] = str(d)
                st.rerun()

    st.markdown("---")
    if st.button("❌ Cancel", use_container_width=True, key=f"web_picker_cancel_{key}"):
        st.session_state[f"{key}_selected"] = False
        st.rerun()


@st.dialog("Select File(s)", width="large")
def _show_web_files_dialog(key: str, initial_dir: Optional[str] = None, filetypes: Optional[List[Tuple[str, str]]] = None):
    """Streamlit dialog for web-based file selection."""
    state_key = f"web_picker_curr_dir_{key}"
    if state_key not in st.session_state:
        if initial_dir and Path(initial_dir).is_dir():
            st.session_state[state_key] = str(Path(initial_dir).resolve())
        else:
            st.session_state[state_key] = str(Path.home().resolve())

    current_dir = Path(st.session_state[state_key])

    st.subheader("📄 Select Files")
    
    col_path, col_btn_up = st.columns([5, 1])
    with col_path:
        new_path_str = st.text_input(
            "Current Folder Path:",
            value=str(current_dir),
            key=f"web_picker_input_{key}",
            help="Type path and press Enter to navigate"
        )
    with col_btn_up:
        st.markdown("<div style='height: 28px;'></div>", unsafe_allow_html=True)
        if st.button("⬆️ Up", key=f"web_picker_up_{key}", use_container_width=True):
            parent = current_dir.parent
            if parent != current_dir:
                st.session_state[state_key] = str(parent)
                st.rerun()

    # Navigate if path changed manually
    if new_path_str and Path(new_path_str).is_dir() and Path(new_path_str).resolve() != current_dir.resolve():
        st.session_state[state_key] = str(Path(new_path_str).resolve())
        st.rerun()

    # List items
    try:
        items = list(current_dir.iterdir())
    except Exception as e:
        st.error(f"Cannot read directory: {e}")
        items = []

    dirs = sorted([d for d in items if d.is_dir()], key=lambda x: x.name.lower())
    files = sorted([f for f in items if f.is_file()], key=lambda x: x.name.lower())

    # Apply file extension filtering
    if filetypes:
        allowed_exts = []
        for name, patterns in filetypes:
            for pat in patterns.split():
                ext = pat.replace("*", "").lower()
                if ext:
                    allowed_exts.append(ext)
        if allowed_exts and "*" not in allowed_exts and "*.*" not in allowed_exts:
            files = [f for f in files if any(f.name.lower().endswith(e) for e in allowed_exts)]

    st.markdown("---")

    col_dirs, col_files = st.columns([2, 3])

    with col_dirs:
        st.markdown("**Subdirectories:**")
        if not dirs:
            st.caption("No subfolders.")
        else:
            for d in dirs:
                if st.button(f"📁 {d.name}", key=f"web_picker_dir_{d.name}_{key}", use_container_width=True):
                    st.session_state[state_key] = str(d)
                    st.rerun()

    selected_files = []
    with col_files:
        st.markdown("**Files:**")
        if not files:
            st.info("No matching files found.")
        else:
            for f in files:
                try:
                    sz = f.stat().st_size
                    if sz > 1024 * 1024:
                        sz_str = f"{sz / (1024 * 1024):.1f} MB"
                    else:
                        sz_str = f"{sz / 1024:.1f} KB"
                except Exception:
                    sz_str = "unknown size"

                if st.checkbox(f"📄 {f.name} ({sz_str})", key=f"web_picker_chk_{f.name}_{key}"):
                    selected_files.append(str(f))

    st.markdown("---")
    col_confirm, col_cancel = st.columns(2)
    with col_confirm:
        if st.button("✅ Confirm Selection", type="primary", use_container_width=True, disabled=not selected_files, key=f"web_picker_confirm_{key}"):
            st.session_state[f"{key}_selected"] = selected_files
            st.rerun()
    with col_cancel:
        if st.button("❌ Cancel", use_container_width=True, key=f"web_picker_cancel_{key}"):
            st.session_state[f"{key}_selected"] = False
            st.rerun()


def pick_directory(initial_dir: str = None, key: str = None) -> Optional[str]:
    """Pick a directory using native PyQt6 or Web-based server picker depending on settings."""
    from pageplus.gui.utils.settings import Settings
    settings = Settings()
    picker_type = settings.get("FILE_PICKER_TYPE", "Native (PyQt6)")

    if picker_type == "Web (Server-side)":
        if not key:
            key = f"dir_picker_{hash(initial_dir) & 0xffffffff}"

        result_key = f"{key}_selected"
        if result_key in st.session_state:
            res = st.session_state.pop(result_key)
            return res

        # Trigger dialog
        _show_web_directory_dialog(key=key, initial_dir=initial_dir)
        return None

    # Native PyQt6 subprocess mode
    picker_script_path = Path(__file__).resolve()
    command = [sys.executable, str(picker_script_path)]
    if initial_dir:
        command.extend(["--initial-dir", str(initial_dir)])
    paths = _run_picker_script(command)
    return paths[0] if paths else False


def pick_files(initial_dir: str = None, filetypes: List[Tuple[str, str]] = None, key: str = None) -> List[str]:
    """Pick files using native PyQt6 or Web-based server picker depending on settings."""
    from pageplus.gui.utils.settings import Settings
    settings = Settings()
    picker_type = settings.get("FILE_PICKER_TYPE", "Native (PyQt6)")

    if picker_type == "Web (Server-side)":
        if not key:
            key = f"files_picker_{hash(initial_dir) & 0xffffffff}"

        result_key = f"{key}_selected"
        if result_key in st.session_state:
            res = st.session_state.pop(result_key)
            return res

        # Trigger dialog
        _show_web_files_dialog(key=key, initial_dir=initial_dir, filetypes=filetypes)
        return None

    # Native PyQt6 subprocess mode
    picker_script_path = Path(__file__).resolve()
    command = [sys.executable, str(picker_script_path), "--files"]
    if initial_dir:
        command.extend(["--initial-dir", str(initial_dir)])
    if filetypes:
        command.extend(["--file-types", json.dumps(filetypes)])
    paths = _run_picker_script(command)
    return paths if paths else False


def select_directory(initial_dir: str = None) -> List[str]:
    """Opens a directory selection dialog and returns the selected path."""
    from PyQt6.QtWidgets import QApplication, QFileDialog
    app = QApplication.instance() or QApplication(sys.argv)
    if not initial_dir:
        initial_dir = str(Path.home())
    directory = QFileDialog.getExistingDirectory(
        None,
        "Select Directory",
        str(initial_dir),  # Ensure initial_dir is a string
    )
    return directory if directory else None


def select_files(initial_dir: str = None, filetypes: List[Tuple[str, str]] = None):
    """Opens a file selection dialog and returns selected paths."""
    from PyQt6.QtWidgets import QApplication, QFileDialog
    if filetypes is None:
        filetypes = [("XML files", "*.xml"), ("All files", "*.*")]

    app = QApplication.instance() or QApplication(sys.argv)
    if not initial_dir:
        initial_dir = str(Path.home())

    # Format filetypes for PyQt6
    filter_str = ";;".join([f"{name} ({patterns})" for name, patterns in filetypes])

    files, _ = QFileDialog.getOpenFileNames(
        None,
        "Select PAGE XML Files",
        str(initial_dir),  # Ensure initial_dir is a string
        filter_str
    )
    return files if files else []


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="PyQt6 File/Directory Picker"
    )
    parser.add_argument(
        '--files',
        action='store_true',
        help="Select files instead of a directory"
    )
    parser.add_argument(
        '--initial-dir',
        type=str,
        default=None,
        help="The initial directory to open the dialog in."
    )
    parser.add_argument(
        '--file-types',
        type=str,
        default=None,
        help='A JSON string representing the file types to filter, e.g., \'[[\"Image files\", \"*.jpg *.png\"]]\''
    )
    args = parser.parse_args()

    selected_paths = None
    try:
        file_types_list = json.loads(args.file_types) if args.file_types else None
        if args.files:
            selected_paths = select_files(
                initial_dir=args.initial_dir,
                filetypes=file_types_list
            )  # Returns a list
            if not selected_paths:  # User cancelled
                print("[]", file=sys.stdout)
                sys.exit(0)
        else:
            selected_dir = select_directory(initial_dir=args.initial_dir)  # Returns a string or None
            if selected_dir:
                selected_paths = [selected_dir]  # Wrap single dir in a list
            else:  # User cancelled
                print("[]", file=sys.stdout)
                sys.exit(0)

        print(json.dumps(selected_paths), file=sys.stdout)
        sys.exit(0)

    except Exception as e:
        print(f"Error in picker script: {str(e)}", file=sys.stderr)
        sys.exit(1)
