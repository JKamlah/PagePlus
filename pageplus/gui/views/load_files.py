"""Page XML file loading utilities."""
from pathlib import Path
from typing import List
from datetime import datetime
from collections import defaultdict

import streamlit as st

from pageplus.gui.utils.picker import pick_directory, pick_files
from pageplus.io.logger import logging
from pageplus.utils.constants import Environments
from pageplus.utils.fs import collect_xml_files
from pageplus.utils.workspace import Workspace
from pageplus.gui.cli_bridges.workspace import WorkspaceBridge
from pageplus.gui.utils.undo import UndoManager


def get_loaded_files_from_session_state() -> List[Path]:
    """Get the list of loaded XML files from session state."""
    return st.session_state.get("loaded_files", [])


def set_loaded_files_in_session_state(files: List[Path]):
    """Sets the list of loaded XML files in session state."""
    st.session_state.loaded_files = files


def get_loaded_workspace_dir() -> Path:
    """Get the path of the loaded workspace directory."""
    ws = Workspace(Environments.PAGEPLUS)
    loaded_workspace = ws.loaded()
    if loaded_workspace:
        loaded_workspace_path = Path(ws.path(loaded_workspace))
        if loaded_workspace_path.exists():
            return loaded_workspace_path
    return Path.home()


class LoadFilesPage:
    """Page for loading PAGE XML files from a directory or file selection."""

    def __init__(self, workspace_bridge: WorkspaceBridge):
        """Initialize the Load Files page."""
        self.workspace_bridge = workspace_bridge
        if "loaded_files" not in st.session_state:
            st.session_state.loaded_files = []
        if "show_add_workspace" not in st.session_state:
            st.session_state.show_add_workspace = False
        if "files_to_remove" not in st.session_state:
            st.session_state.files_to_remove = set()
        if "search_filter" not in st.session_state:
            st.session_state.search_filter = ""
        if "group_by_directory" not in st.session_state:
            st.session_state.group_by_directory = True
        if "show_file_stats" not in st.session_state:
            st.session_state.show_file_stats = False
        if 'page_size' not in st.session_state:
            st.session_state.page_size = 100
        if 'current_page' not in st.session_state:
            st.session_state.current_page = 1
        if 'grouped_page_size' not in st.session_state:
            st.session_state.grouped_page_size = 25
        if 'grouped_current_page' not in st.session_state:
            st.session_state.grouped_current_page = 1

    def show(self):
        """Display the Load Files page."""
        st.title("📂 Load Files")

        # Create tabs for better organization
        tab1, tab2 = st.tabs(["➕ Add Files", "📋 Manage Files"])

        with tab1:
            self._show_add_files_tab()

        with tab2:
            self._show_manage_files_tab()

    def _show_add_files_tab(self):
        """Show the tab for adding files."""
        # System file loading
        with st.expander("🖥️ System Files", expanded=True):
            st.markdown("Load files from anywhere on your system")
            col1, col2 = st.columns(2)

            with col1:
                if st.button("📁 Add Directory", key="add_dir", use_container_width=True):
                    selected_paths = pick_directory()
                    if selected_paths:
                        self.load_xml_files(
                            [Path(selected_paths)],
                            from_directory=True
                        )
                    elif selected_paths is not None:
                        st.info("Directory selection cancelled.")

            with col2:
                if st.button("📄 Add Files", key="add_files", use_container_width=True):
                    selected_paths = pick_files()
                    if selected_paths:
                        self.load_xml_files(
                            [Path(p) for p in selected_paths],
                            from_directory=False
                        )
                    elif selected_paths is not None:
                        st.info("File selection cancelled.")

        # Workspace file loading
        with st.expander("🗂️ Workspace Files", expanded=True):
            st.markdown("Load files from your PagePlus workspaces")

            workspace = Workspace(Environments.PAGEPLUS)

            try:
                workspace_names = workspace.names()
                loaded_workspace = workspace.loaded()
                if loaded_workspace and loaded_workspace in workspace_names:
                    default_index = workspace_names.index(loaded_workspace)
                else:
                    default_index = None
            except Exception:
                default_index = None

            if not workspace_names:
                st.info("No workspaces available. Create a workspace in the Workspace page.")
                return

            selected_workspace = st.selectbox(
                "Select Workspace",
                workspace_names,
                index=default_index,
                key="workspace_selector"
            )

            if selected_workspace:
                current_path = self.workspace_bridge.workspace_path(selected_workspace)
                if current_path:
                    st.caption(f"📍 {current_path}")

                col1, col2, col3 = st.columns(3)

                with col1:
                    if st.button("📂 Add All", key="add_workspace", use_container_width=True):
                        selected_paths = Path(workspace.path(selected_workspace))
                        if selected_paths:
                            self.load_xml_files(
                                [selected_paths],
                                from_directory=True
                            )

                with col2:
                    if st.button("📁 Add Directory", key="add_ws_dir", use_container_width=True):
                        selected_paths = pick_directory(
                            initial_dir=Path(workspace.path(selected_workspace)))
                        if selected_paths:
                            self.load_xml_files(
                                [Path(selected_paths)],
                                from_directory=True
                            )
                        elif selected_paths is not None:
                            st.info("Directory selection cancelled.")

                with col3:
                    if st.button("📄 Add Files", key="add_ws_files", use_container_width=True):
                        selected_paths = pick_files(
                            initial_dir=Path(workspace.path(selected_workspace)))
                        if selected_paths:
                            self.load_xml_files(
                                [Path(p) for p in selected_paths],
                                from_directory=False
                            )

    def _show_manage_files_tab(self):
        """Show the tab for managing loaded files."""
        loaded_files = st.session_state.loaded_files

        if not loaded_files:
            st.info("📭 No PAGE XML files loaded yet. Use the 'Add Files' tab to load files.")
            return

        # Summary statistics
        show_stats = st.checkbox("Show statistics", key="show_file_stats")
        self._show_file_statistics(loaded_files, show_stats)

        st.divider()

        # Search and filter options
        col1, col2, col3 = st.columns([3, 1, 1])

        with col1:
            search_term = st.text_input(
                "🔍 Search files",
                value=st.session_state.search_filter,
                placeholder="Filter by filename or path...",
                key="search_input"
            )
            st.session_state.search_filter = search_term

        with col2:
            group_by = st.checkbox(
                "Group by directory",
                value=st.session_state.group_by_directory,
                key="group_checkbox"
            )
            st.session_state.group_by_directory = group_by

        with col3:
            if st.button("🗑️ Clear All", key="clear_all", use_container_width=True):
                st.session_state.loaded_files = []
                st.session_state.files_to_remove = set()
                st.session_state.search_filter = ""
                UndoManager.clear_stack()
                st.rerun()

        # Filter files based on search
        filtered_files = self._filter_files(loaded_files, search_term)

        if not filtered_files:
            st.warning(f"No files match the search term: '{search_term}'")
            return

        # Show files based on grouping preference
        if st.session_state.group_by_directory:
            self._show_files_grouped(filtered_files, show_stats)
        else:
            self._show_files_flat(filtered_files, show_stats)

        st.divider()
        # Remove selected files button
        if st.session_state.files_to_remove:
            col1, col2 = st.columns([1, 4])
            with col1:
                if st.button(
                    f"🗑️ Remove Selected ({len(st.session_state.files_to_remove)})",
                    key="remove_selected",
                    type="primary",
                    use_container_width=True
                ):
                    self._remove_selected_files()
            with col2:
                if st.button("❌ Clear Selection", key="clear_selection", use_container_width=True):
                    st.session_state.files_to_remove = set()
                    st.rerun()

    def _show_file_statistics(self, files: List[Path], show_stats: bool):
        """Show summary statistics for loaded files."""
        dir_counts = defaultdict(int)
        for f in files:
            dir_counts[f.parent] += 1

        columns = st.columns(3) if show_stats else st.columns(2)

        with columns[0]:
            st.metric("📊 Total Files", len(files))

        if show_stats:
            with columns[1]:
                total_size = sum(f.stat().st_size for f in files if f.exists())
                total_size_mb = total_size / (1024 * 1024)
                st.metric("💾 Total Size", f"{total_size_mb:.2f} MB")
            with columns[2]:
                st.metric("📁 Directories", len(dir_counts))
        else:
            with columns[1]:
                st.metric("📁 Directories", len(dir_counts))

    def _filter_files(self, files: List[Path], search_term: str) -> List[Path]:
        """Filter files based on search term."""
        if not search_term:
            return files

        search_lower = search_term.lower()
        return [
            f for f in files
            if search_lower in f.name.lower() or search_lower in str(f).lower()
        ]

    def _show_files_grouped(self, files: List[Path], show_stats: bool):
        """Show files grouped by directory."""
        # Group files by parent directory
        grouped = defaultdict(list)
        for f in files:
            grouped[f.parent].append(f)

        # Sort directories
        sorted_dirs = sorted(grouped.keys(), key=lambda x: str(x))

        # Pagination for files within each directory
        page_size = st.number_input(
            "Items per page (inside directories)",
            min_value=10,
            max_value=1000,
            value=st.session_state.grouped_page_size,
            step=10,
            key="grouped_page_size_input"
        )
        st.session_state.grouped_page_size = page_size

        st.info(f"Showing all {len(sorted_dirs)} directories. Files inside directories with more than {page_size} items will be paginated.")

        for directory in sorted_dirs:
            dir_files = sorted(grouped[directory], key=lambda x: x.name)

            with st.expander(
                f"📁 {directory} ({len(dir_files)} files)",
                expanded=len(sorted_dirs) <= 3
            ):
                total_files_in_dir = len(dir_files)

                if total_files_in_dir > page_size:
                    dir_page_key = f"grouped_page_for_{directory}"
                    if dir_page_key not in st.session_state:
                        st.session_state[dir_page_key] = 1

                    total_pages = (total_files_in_dir + page_size - 1) // page_size
                    if st.session_state[dir_page_key] > total_pages:
                        st.session_state[dir_page_key] = 1
                    current_page = st.session_state[dir_page_key]

                    # Pagination controls
                    c1, c2, c3 = st.columns([2, 8, 2])
                    with c1:
                        if st.button("◀️ Previous", key=f"prev_{directory}", use_container_width=True):
                            if current_page > 1:
                                st.session_state[dir_page_key] -= 1
                                st.rerun()
                    with c3:
                        if st.button("Next ▶️", key=f"next_{directory}", use_container_width=True):
                            if current_page < total_pages:
                                st.session_state[dir_page_key] += 1
                                st.rerun()
                    with c2:
                        st.markdown(f"<p style='text-align: center; vertical-align: middle;'>Page {current_page} of {total_pages}</p>", unsafe_allow_html=True)

                    start_index = (current_page - 1) * page_size
                    end_index = start_index + page_size
                    paginated_files = dir_files[start_index:end_index]
                    st.caption(f"Showing files {start_index + 1} to {min(end_index, total_files_in_dir)}")

                    for file_path in paginated_files:
                        self._show_file_row(file_path, show_stats)
                else:
                    for file_path in dir_files:
                        self._show_file_row(file_path, show_stats)

    def _show_files_flat(self, files: List[Path], show_stats: bool):
        """Show files in a flat list."""
        st.markdown("### Files")

        # Pagination for flat file list
        total_files = len(files)
        page_size = st.number_input(
            "Files per page",
            min_value=10,
            max_value=1000,
            value=st.session_state.page_size,
            step=10,
            key="page_size_input"
        )
        st.session_state.page_size = page_size

        total_pages = (total_files + page_size - 1) // page_size if total_files > 0 else 1

        if st.session_state.current_page > total_pages:
            st.session_state.current_page = 1

        current_page = st.number_input(
            "Page",
            min_value=1,
            max_value=total_pages,
            value=st.session_state.current_page,
            key="page_input"
        )
        st.session_state.current_page = current_page

        start_index = (current_page - 1) * page_size
        end_index = start_index + page_size
        paginated_files = sorted(files, key=lambda x: x.name)[start_index:end_index]

        st.info(f"Showing files {start_index + 1} to {min(end_index, total_files)} of {total_files}")

        # Create a scrollable container
        for file_path in paginated_files:
            self._show_file_row(file_path, show_stats)

    def _show_file_row(self, file_path: Path, show_stats: bool):
        """Show a single file row with checkbox and metadata."""
        if show_stats:
            col1, col2, col3, col4 = st.columns([0.3, 3, 1.5, 1])
        else:
            col1, col2 = st.columns([0.3, 5.5])

        with col1:
            is_selected = str(file_path) in st.session_state.files_to_remove
            if st.checkbox(
                "Select",
                value=is_selected,
                key=f"check_{hash(str(file_path))}",
                label_visibility="collapsed"
            ):
                st.session_state.files_to_remove.add(str(file_path))
            else:
                st.session_state.files_to_remove.discard(str(file_path))

        with col2:
            st.markdown(f"**{file_path.name}**")
            # st.caption(f"📍 {file_path.parent}")

        if show_stats:
            with col3:
                if file_path.exists():
                    file_size = file_path.stat().st_size / 1024  # KB
                    if file_size > 1024:
                        st.caption(f"💾 {file_size / 1024:.2f} MB")
                    else:
                        st.caption(f"💾 {file_size:.2f} KB")

            with col4:
                if file_path.exists():
                    mod_time = datetime.fromtimestamp(file_path.stat().st_mtime)
                    st.caption(f"🕐 {mod_time.strftime('%Y-%m-%d')}")
                else:
                    st.caption("⚠️ Missing")

    def _remove_selected_files(self):
        """Remove selected files from the loaded files list."""
        files_to_remove = st.session_state.files_to_remove

        if not files_to_remove:
            return

        # Filter out selected files
        st.session_state.loaded_files = [
            f for f in st.session_state.loaded_files
            if str(f) not in files_to_remove
        ]

        # Clear selection
        st.session_state.files_to_remove = set()

        st.success(f"Removed {len(files_to_remove)} file(s)")
        st.rerun()

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
                    UndoManager.clear_stack()

        except Exception as e:
            logging.error(
                f"Error loading files: {str(e)}",
                exc_info=True
            )
            st.error(f"An error occurred while loading files: {str(e)}")

    def get_loaded_files(self) -> List[Path]:
        """Get the list of loaded XML files."""
        return get_loaded_files_from_session_state()
