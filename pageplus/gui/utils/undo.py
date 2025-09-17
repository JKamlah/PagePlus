from __future__ import annotations

import datetime
from pathlib import Path
from typing import Dict, List, Optional

import streamlit as st

MAX_UNDO_STATES = 10


class UndoState:
    """Represents a single state in the undo history."""

    def __init__(self, description: str, files: Dict[Path, bytes]):
        self.description = description
        self.files = files
        self.timestamp = datetime.datetime.now()

    def __str__(self):
        return f"{self.timestamp.strftime('%H:%M:%S')}: {self.description}"


class UndoManager:
    """Manages the undo/redo stack for file modifications."""

    @staticmethod
    def _get_stack() -> List[UndoState]:
        if "undo_stack" not in st.session_state:
            st.session_state.undo_stack = []
        return st.session_state.undo_stack

    @staticmethod
    def _set_stack(stack: List[UndoState]):
        st.session_state.undo_stack = stack

    @staticmethod
    def add_undo_state(description: str, file_paths: Optional[List[Path]] = None):
        """Adds a new state to the undo stack.

        Args:
            description: A brief description of the operation.
            file_paths: A list of file paths to back up. If None, it uses
                        the currently loaded files from the session state.
        """
        if file_paths is None:
            if "loaded_files" not in st.session_state or not st.session_state.loaded_files:
                return
            file_paths = [Path(p) for p in st.session_state.loaded_files]

        files_content = {}
        for file_path in file_paths:
            if file_path.exists() and file_path.is_file():
                try:
                    with open(file_path, "rb") as f:
                        files_content[file_path] = f.read()
                except Exception as e:
                    st.warning(f"Could not back up file {file_path}: {e}")

        if not files_content:
            st.warning("No files could be backed up for undo operation.")
            return

        undo_state = UndoState(description, files_content)
        stack = UndoManager._get_stack()
        stack.insert(0, undo_state)
        UndoManager._set_stack(stack[:MAX_UNDO_STATES])

    @staticmethod
    def get_undo_states() -> List[UndoState]:
        """Returns the current undo stack."""
        return UndoManager._get_stack()

    @staticmethod
    def clear_stack():
        """Clears the undo stack."""
        UndoManager._set_stack([])

    @staticmethod
    def restore_state(state_index: int) -> Optional[str]:
        """Restores a state from the undo stack."""
        stack = UndoManager._get_stack()
        if 0 <= state_index < len(stack):
            state_to_restore = stack[state_index]

            try:
                # Write files back to disk
                for file_path, content in state_to_restore.files.items():
                    file_path.parent.mkdir(parents=True, exist_ok=True)
                    with open(file_path, "wb") as f:
                        f.write(content)
            except Exception as e:
                st.error(f"Failed to restore files: {e}")
                return None

            # On successful restore, remove the restored state and all subsequent states from the stack
            UndoManager._set_stack(stack[state_index + 1 :])

            return state_to_restore.description
        return None
