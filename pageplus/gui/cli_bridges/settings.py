import subprocess
from pathlib import Path

from pageplus.gui.cli_bridges.base import CLIBridge, logger


class SettingsBridge(CLIBridge):
    """Bridge for settings functionality."""

    def update_pip(self) -> None:
        """Update pip to the latest version."""
        try:
            subprocess.run(["pageplus", "system", "update-pip"], check=True)
        except subprocess.CalledProcessError as e:
            raise RuntimeError(f"Failed to update pip: {e}")

    def set_workspace_dir(self, wsdir: str) -> None:
        """Set the workspace directory."""
        try:
            cmd = ["pageplus", "system", "set-workspace-dir", wsdir]
            subprocess.run(cmd, check=True)
        except subprocess.CalledProcessError as e:
            raise RuntimeError(f"Failed to set workspace directory: {e}")

    def set_workspace_dir_to_tempfolder(self) -> None:
        """Set workspace directory to temp folder."""
        try:
            cmd = ["pageplus", "system", "set-workspace-dir-to-tempfolder"]
            subprocess.run(cmd, check=True)
        except subprocess.CalledProcessError as e:
            msg = "Failed to set workspace directory to temp folder"
            raise RuntimeError(f"{msg}: {e}")

    def clean_workspace_dir(self) -> None:
        """Clean the workspace directory."""
        try:
            cmd = ["pageplus", "system", "clean-workspace-dir"]
            subprocess.run(cmd, check=True)
        except subprocess.CalledProcessError as e:
            raise RuntimeError(f"Failed to clean workspace directory: {e}") 