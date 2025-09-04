"""File and directory picker utilities using PyQt6."""
import argparse
import json
import sys
from pathlib import Path
from typing import List, Tuple

from PyQt6.QtWidgets import QApplication, QFileDialog

from pageplus.utils.workspace import Environments, Workspace


def get_loaded_workspace_dir() -> Path:
    """Get the directory of the loaded workspace."""
    ws = Workspace(Environments.PAGEPLUS)
    workspace_names = ws.names()
    loaded_workspace = ws.loaded() if ws.loaded(
    ) and ws.loaded() in workspace_names else None
    if not loaded_workspace:
        return Path.home()
    return Path(ws.path(loaded_workspace))


def select_directory(initial_dir: str = None):
    """Opens a directory selection dialog and returns the selected path."""
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
