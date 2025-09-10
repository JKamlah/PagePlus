"""Page XML file loading utilities."""
import subprocess
import sys
from pathlib import Path
from typing import List
import json

import streamlit as st

from pageplus.gui.utils.picker import pick_directory, pick_files
from pageplus.io.logger import logging
from pageplus.utils.constants import Environments
from pageplus.utils.fs import collect_xml_files
from pageplus.utils.workspace import Workspace


class LoadFilesPage:
    """Page for loading PAGE XML files from a directory or file selection."""

    def __init__(self):
        """Initialize the Load Files page."""
        if "loaded_files" not in st.session_state:
            st.session_state.loaded_files = []
        if "show_add_workspace" not in st.session_state:
            st.session_state.show_add_workspace = False

    def show(self):
        """Display the Load Files page."""
        st.title("📂 Load Files")

        st.subheader("System")
        # File loading options
        col1, col2, col3 = st.columns(3)

        # Select directory
        with col1:
            if st.button("Add Directory", key="add_dir"):
                selected_paths = pick_directory()
                if selected_paths:
                    self.load_xml_files(
                        [Path(selected_paths)],
                        from_directory=True
                    )
                elif selected_paths is not None:
                    st.info("Directory selection cancelled.")

        # Select individual files
        with col2:
            if st.button("Add Files", key="add_files"):
                selected_paths = pick_files()
                if selected_paths:
                    self.load_xml_files(
                        [Path(p) for p in selected_paths],
                        from_directory=False
                    )
                elif selected_paths is not None:
                    st.info("File selection cancelled.")

        # Workspace section
        st.subheader("Workspace")

        # Initialize workspace manager
        workspace = Workspace(Environments.PAGEPLUS)
        workspaces = workspace.names()

        # Workspace dropdown
        selected_workspace = st.selectbox(
            "Select Workspace",
            workspaces,
            index=None,
        )

        col1, col2, col3 = st.columns(3)

        with col1:
            if st.button("Add Workspace", key="add_workspace"):
                if selected_workspace:
                    selected_paths = Path(workspace.path(selected_workspace))
                    if selected_paths:
                        self.load_xml_files(
                            [selected_paths],
                            from_directory=True
                        )
                    elif selected_paths is not None:
                        st.info("Workspace is empty.")
                else:
                    st.info("Please select a workspace first.")
        # Select directory
        with col2:
            if st.button("Add Directory", key="add_ws_dir"):
                if selected_workspace:
                    selected_paths = pick_directory(
                        initial_dir=Path(workspace.path(selected_workspace)))
                    if selected_paths:
                        self.load_xml_files(
                            [Path(selected_paths)],
                            from_directory=True
                        )
                    elif selected_paths is not None:
                        st.info("Directory selection cancelled.")
                else:
                    st.info("Please select a workspace first.")

        # Select individual files
        with col3:
            if st.button("Add Files", key="add_ws_files"):
                if selected_workspace:
                    selected_paths = pick_files(
                        initial_dir=Path(workspace.path(selected_workspace)))
                    if selected_paths:
                        self.load_xml_files(
                            [Path(p) for p in selected_paths],
                            from_directory=False
                        )
                    else:
                        st.info("File selection cancelled.")
                else:
                    st.info("Please select a workspace first.")

        # Show loaded files
        st.subheader("Loaded Files")
        if st.button("Clear Files", key="clear"):
            st.session_state.loaded_files = []
            st.rerun()

        if st.session_state.loaded_files:
            display_data = [
                {"File": p.name, "Path": str(p)}
                for p in st.session_state.loaded_files
            ]
            st.dataframe(
                data=display_data,
                width='stretch'
            )
            st.success(
                f"Total: {len(st.session_state.loaded_files)} files loaded."
            )
        else:
            st.info("No PAGE XML files loaded yet.")

    def load_xml_files(
        self,
        paths_to_process: List[Path],
        from_directory: bool
    ):
        """Load XML files from directories or individual files."""
        if not isinstance(paths_to_process, list) or not all(
            isinstance(p, Path) for p in paths_to_process
        ):
            logging.error(
                f"Invalid input to load_xml_files: {paths_to_process}"
            )
            st.error("Internal error: Invalid path list received.")
            return

        try:
            with st.spinner("Loading files...", show_time=True):
                newly_added_files = []

                if from_directory:
                    found_files = collect_xml_files(paths_to_process)
                else:
                    found_files = [
                        f for f in paths_to_process
                        if f.is_file() and f.suffix.lower() == ".xml"
                    ]

                existing_paths_str = {
                    str(f) for f in st.session_state.loaded_files
                }

                for f in found_files:
                    if str(f) not in existing_paths_str:
                        st.session_state.loaded_files.append(f)
                        newly_added_files.append(f)
                        existing_paths_str.add(str(f))

                if not newly_added_files:
                    if found_files:
                        st.warning(
                            "Selected files/directories contained no *new* "
                            "PAGE XML files."
                        )
                    else:
                        st.warning(
                            f"No PAGE XML files found in the selection: "
                            f"{paths_to_process}."
                        )
                else:
                    logging.info(
                        f"Added {len(newly_added_files)} new files."
                    )

        except Exception as e:
            logging.error(
                f"Error loading files: {str(e)}",
                exc_info=True
            )
            st.error(f"An error occurred while loading files: {str(e)}")

    def get_loaded_files(self) -> List[Path]:
        """Get the list of loaded XML files."""
        return st.session_state.get("loaded_files", [])
