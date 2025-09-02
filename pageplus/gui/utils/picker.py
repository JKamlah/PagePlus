"""File and directory picker utilities using tkinter."""
import tkinter as tk
from tkinter import filedialog
import sys
import json
import argparse
from typing import List, Tuple
from pathlib import Path

from pageplus.utils.workspace import Workspace, Environments


def get_loaded_workspace_dir() -> Path:
    """Get the directory of the loaded workspace."""
    ws = Workspace(Environments.PAGEPLUS)
    workspace_names = ws.names()
    loaded_workspace = ws.loaded() if ws.loaded() and ws.loaded() in workspace_names else None
    return Path(ws.path(loaded_workspace))


def select_directory(initial_dir: str = None):
    """Opens a directory selection dialog and returns the selected path."""
    root = tk.Tk()
    root.withdraw()  # Hide the main Tkinter window
    root.attributes("-topmost", True)  # Try to bring dialog to front
    if not initial_dir:
        initial_dir = str(Path.home())
    directory = filedialog.askdirectory(
        mustexist=True, 
        title="Select Directory",
        initialdir=initial_dir
    )
    root.destroy()
    return directory if directory else None


def select_files(initial_dir: str = None, 
                 filetypes: List[Tuple[str, str]] = [("XML files", "*.xml"), ("All files", "*.*")]):
    """Opens a file selection dialog for XML files and returns selected paths."""
    root = tk.Tk()
    root.withdraw()  # Hide the main Tkinter window
    root.attributes("-topmost", True) 
    if not initial_dir:
        initial_dir = str(Path.home()) # Try to bring dialog to front
    files = filedialog.askopenfilenames(
        title="Select PAGE XML Files",
        filetypes=filetypes,
        initialdir=initial_dir
    )
    root.destroy()
    # askopenfilenames returns a tuple, convert to list
    return list(files) if files else []


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Tkinter File/Directory Picker"
    )
    parser.add_argument(
        '--files', 
        action='store_true',
        help="Select files instead of a directory"
    )
    args = parser.parse_args()

    selected_paths = None
    try:
        if args.files:
            selected_paths = select_files()  # Returns a list
            if not selected_paths:  # User cancelled
                print("[]", file=sys.stdout)  # Output empty JSON list
                sys.exit(0)  # Exit successfully even on cancel
        else:
            selected_dir = select_directory()  # Returns a string or None
            if selected_dir:
                selected_paths = [selected_dir]  # Wrap single dir in a list
            else:  # User cancelled
                print("[]", file=sys.stdout)  # Output empty JSON list
                sys.exit(0)  # Exit successfully even on cancel

        # Print the selected paths as a JSON list to stdout
        print(json.dumps(selected_paths), file=sys.stdout)
        sys.exit(0)

    except Exception as e:
        # Print error message to stderr for Streamlit to potentially capture
        print(f"Error in picker script: {str(e)}", file=sys.stderr)
        sys.exit(1)  # Indicate failure with non-zero exit code 