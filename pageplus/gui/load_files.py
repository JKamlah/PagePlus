import os
from pathlib import Path
from typing import List, Optional
import tkinter as tk
from tkinter import filedialog, ttk
from tkinter.messagebox import showinfo

from pageplus.utils.fs import collect_xml_files
from pageplus.io.logger import logging
import streamlit as st
import subprocess
import json
import sys

class LoadFilesPage:
    """Page for loading PAGE XML files from a directory or file selection."""

    def __init__(self):
        """Initialize the Load Files page."""
        if "loaded_files" not in st.session_state:
            st.session_state.loaded_files = []

    def _run_picker(self, mode: str) -> List[str]:
        """Internal helper to run the picker subprocess."""
        picker_path = Path(__file__).parent / "picker.py"
        command = [sys.executable, picker_path] # Use sys.executable for robustness
        if mode == "files":
            command.append("--files")

        try:
            # Setting encoding explicitly can sometimes help
            process = subprocess.run(
                command,
                capture_output=True, # Replaces stdout=PIPE, stderr=PIPE
                check=True,        # Raises CalledProcessError on non-zero exit
                text=True,         # Decode stdout/stderr as text
                encoding='utf-8'   # Be explicit about encoding
            )
            # process.check_returncode() # Already done by check=True
            try:
                # picker.py now always outputs a JSON list
                return json.loads(process.stdout.strip())
            except json.JSONDecodeError as json_err:
                st.error(f"Picker script returned invalid JSON: {json_err}")
                st.error(f"Picker stdout: '{process.stdout}'")
                st.error(f"Picker stderr: '{process.stderr}'")
                return []

        except FileNotFoundError:
            st.error(f"Error: 'picker.py' not found or '{sys.executable}' is not valid.")
            st.error("Ensure 'picker.py' is in the same directory as the Streamlit app.")
            return []
        except subprocess.CalledProcessError as proc_err:
            # This catches non-zero exit codes from picker.py (errors inside picker)
            st.error(f"File/Directory Picker script failed (Exit Code {proc_err.returncode}):")
            st.error(f"Picker stderr: '{proc_err.stderr}'") # Show error from picker.py
            logging.error(f"Picker script failed. Command: {command}, Error: {proc_err.stderr}")
            return []
        except Exception as e:
            # Catch any other unexpected errors during subprocess execution
            st.error(f"An unexpected error occurred while running the picker: {str(e)}")
            logging.error(f"Unexpected picker error. Command: {command}, Error: {e}")
            return []

    def pick_directory(self) -> List[str]:
        """Use a subprocess to open a native directory picker."""
        return self._run_picker("directory")

    def pick_files(self) -> List[str]:
        """Use a subprocess to open a native file picker."""
        return self._run_picker("files")

    def show(self):
        """Display the Load Files page."""
        st.title("📂 Load Files")

        col1, col2, col3 = st.columns(3)

        # Select directory
        with col1:
            if st.button("Add Directory", key="add_dir"): # Added key for potential stability
                selected_paths = self.pick_directory()
                if selected_paths: # Check if list is not empty (picker succeeded and wasn't cancelled)
                    self.load_xml_files([Path(p) for p in selected_paths], from_directory=True)
                elif selected_paths is not None: # Picker ran but returned empty list (likely cancel)
                    st.info("Directory selection cancelled.")


        # Select individual files
        with col2:
            if st.button("Add Files", key="add_files"): # Added key
                selected_paths = self.pick_files()
                if selected_paths: # Check if list is not empty
                     self.load_xml_files([Path(p) for p in selected_paths], from_directory=False)
                elif selected_paths is not None: # Picker ran but returned empty list (likely cancel)
                    st.info("File selection cancelled.")

        # Clear all loaded files
        with col3:
            if st.button("Clear Files", key="clear"): # Added key
                st.session_state.loaded_files = []
                st.rerun() # Ensure UI updates immediately after clear

        # Show loaded files
        st.subheader("Loaded Files")
        if st.session_state.loaded_files:
            # Use Path objects directly for display, converting to string where needed
            display_data = [{"File": p.name, "Path": str(p)} for p in st.session_state.loaded_files]
            st.dataframe(
                data=display_data,
                use_container_width=True
            )
            st.success(f"Total: {len(st.session_state.loaded_files)} files loaded.")
        else:
            st.info("No PAGE XML files loaded yet.")

    def load_xml_files(self, paths_to_process: List[Path], from_directory: bool):
        """Load XML files from directories or individual files."""
        # Ensure input is a list of Path objects
        if not isinstance(paths_to_process, list) or not all(isinstance(p, Path) for p in paths_to_process):
             logging.error(f"Invalid input to load_xml_files: {paths_to_process}")
             st.error("Internal error: Invalid path list received.")
             return

        try:
            with st.spinner("Loading files..."):
                newly_added_files = []

                if from_directory:
                    # Assuming collect_xml_files handles multiple directories in the list
                    # And returns a list of Path objects for found XML files
                    found_files = collect_xml_files(paths_to_process)
                else:
                    # Filter the explicitly selected files to ensure they are XML
                    # (picker.py already filters, but belt-and-suspenders)
                    found_files = [f for f in paths_to_process if f.is_file() and f.suffix.lower() == ".xml"]

                # Avoid duplicates - Convert existing to strings for set lookup
                existing_paths_str = {str(f) for f in st.session_state.loaded_files}
                
                for f in found_files:
                    if str(f) not in existing_paths_str:
                        st.session_state.loaded_files.append(f)
                        newly_added_files.append(f)
                        existing_paths_str.add(str(f)) # Add to set immediately

                if not newly_added_files:
                    if found_files: # Files were found, but they were already loaded
                         st.warning("Selected files/directories contained no *new* PAGE XML files.")
                    else: # No XML files were found at all in the selection
                         st.warning("No PAGE XML files found in the selection.")
                else:
                    # Log successful addition - info level might be more appropriate than success
                    logging.info(f"Added {len(newly_added_files)} new files.")
                    # The success message is now shown below the dataframe

        except Exception as e:
            logging.error(f"Error loading files: {str(e)}", exc_info=True) # Add stack trace to log
            st.error(f"An error occurred while loading files: {str(e)}")

    def get_loaded_files(self) -> List[Path]:
        """Get the list of loaded XML files."""
        # Ensure it's always a list, even if empty
        return st.session_state.get("loaded_files", [])

# Example usage (if running this file directly):
if __name__ == "__main__":
    # Make sure logging is configured
    logging.basicConfig(level=logging.INFO)
    page = LoadFilesPage()
    page.show()