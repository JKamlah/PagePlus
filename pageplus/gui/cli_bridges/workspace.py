import logging
import subprocess
from pathlib import Path

from pageplus.cli.workspace import (backup_xmlfiles, copy_workspace,
                                    delete_workspace, load_local_document,
                                    load_workspace, open_workspace,
                                    restore_xmlfiles, update_workspaces)
from pageplus.gui.cli_bridges import CLIBridge
from pageplus.utils.constants import Environments
from pageplus.utils.workspace import Workspace

logger = logging.getLogger(__name__)


class WorkspaceBridge(CLIBridge):
    """Bridge for workspace functionality."""

    def show_workspaces(self) -> None:
        """Show all available workspaces."""
        try:
            ws = Workspace(Environments.PAGEPLUS)
            ws.names()
            ws.loaded()
        except subprocess.CalledProcessError as e:
            raise RuntimeError(f"Failed to show workspaces: {e}")

    def workspace_path(self, workspace: str) -> None:
        """Get path of a workspace."""
        try:
            ws = Workspace(Environments.PAGEPLUS)
            return ws.path(workspace)
        except subprocess.CalledProcessError as e:
            raise RuntimeError(f"Failed to get workspace path: {e}")

    def set_workspace_path(self, workspace: str, path: str) -> None:
        """Set path of a workspace."""
        try:
            ws = Workspace(Environments.PAGEPLUS)
            ws.update_path(workspace, path)
        except subprocess.CalledProcessError as e:
            raise RuntimeError(f"Failed to set workspace path: {e}")

    def load_workspace(self, workspace: str) -> None:
        """Load a specific workspace."""
        try:
            load_workspace(workspace)
        except subprocess.CalledProcessError as e:
            raise RuntimeError(f"Failed to load workspace: {e}")

    def update_workspaces(self) -> None:
        """Update workspace information."""
        try:
            update_workspaces()
        except subprocess.CalledProcessError as e:
            raise RuntimeError(f"Failed to update workspaces: {e}")

    def backup_xmlfiles(
            self,
            backup_folder: str,
            workspace: str = None,
            as_zip: bool = False) -> None:
        """Backup XML files from a workspace."""
        try:
            backup_xmlfiles(backup_folder, workspace, as_zip)
        except subprocess.CalledProcessError as e:
            raise RuntimeError(f"Failed to backup XML files: {e}")

    def restore_xmlfiles(
            self,
            backup_folder: str,
            workspace: str = None,
            from_zip: bool = False) -> None:
        """Restore XML files to a workspace."""
        try:
            restore_xmlfiles(backup_folder, workspace, from_zip)
        except subprocess.CalledProcessError as e:
            raise RuntimeError(f"Failed to restore XML files: {e}")

    def delete_workspace(self, workspace: str, all_files: bool = False) -> None:
        """Delete a workspace."""
        try:
            delete_workspace(workspace, all_files)
        except subprocess.CalledProcessError as e:
            raise RuntimeError(f"Failed to delete workspace: {e}")

    def copy_workspace(self, destination_path: str, workspace: str = None,
                       new_workspace: str = "") -> None:
        """Copy a workspace to a new location."""
        try:
            copy_workspace(destination_path, workspace, new_workspace)
        except subprocess.CalledProcessError as e:
            raise RuntimeError(f"Failed to copy workspace: {e}")

    def open_workspace(self, workspace: str = None) -> None:
        """Open a workspace in the file explorer."""
        try:
            open_workspace(workspace)
        except subprocess.CalledProcessError as e:
            raise RuntimeError(f"Failed to open workspace: {e}")

    def load_local_document(self, inputdir: str, workspace: str,
                            overwrite_workspace: bool = False,
                            loading: bool = True) -> None:
        """Load a local document into a workspace."""
        try:
            load_local_document(Path(inputdir), workspace,
                                overwrite_workspace, loading)
        except subprocess.CalledProcessError as e:
            raise RuntimeError(f"Failed to load local document: {e}")
