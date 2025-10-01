import subprocess
import zipfile
import io
import json
from pathlib import Path

from pageplus.gui.cli_bridges.base import CLIBridge
from pageplus.gui.utils.settings import Settings
from pageplus.utils.constants import GUI_STORAGE_DIR


class SettingsBridge(CLIBridge):
    """Bridge for settings functionality."""

    def update_pip(self) -> None:
        """Update pip to the latest version."""
        try:
            subprocess.run(["pageplus", "system", "update-pip"], check=True)
        except subprocess.CalledProcessError as e:
            raise RuntimeError(f"Failed to update pip: {e}")

    def update_ssl(self) -> None:
        """Update SSL certificates."""
        try:
            subprocess.run(["pageplus", "system", "update-ssl"], check=True)
        except subprocess.CalledProcessError as e:
            raise RuntimeError(f"Failed to update SSL certificates: {e}")

    def clean_logs(self) -> None:
        """Clean all log files."""
        try:
            subprocess.run(["pageplus", "system", "clean-logs"], check=True)
        except subprocess.CalledProcessError as e:
            raise RuntimeError(f"Failed to clean logs: {e}")

    def set_user_agent(self, user_agent: str) -> None:
        """Set the user agent."""
        try:
            cmd = ["pageplus", "system", "set-user-agent", user_agent]
            subprocess.run(cmd, check=True)
        except subprocess.CalledProcessError as e:
            raise RuntimeError(f"Failed to set user agent: {e}")

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

    def activate_tesseract(self) -> None:
        """Activate Tesseract OCR."""
        try:
            from dotenv import set_key
            from pageplus.utils.envs import get_env_path
            set_key(get_env_path(), 'PAGEPLUS_OCR_TESSERACT', 'True')
        except Exception as e:
            raise RuntimeError(f"Failed to activate Tesseract OCR: {e}")

    def deactivate_tesseract(self) -> None:
        """Deactivate Tesseract OCR."""
        try:
            from dotenv import set_key
            from pageplus.utils.envs import get_env_path
            set_key(get_env_path(), 'PAGEPLUS_OCR_TESSERACT', 'False')
        except Exception as e:
            raise RuntimeError(f"Failed to deactivate Tesseract OCR: {e}")

    def get_export_files(self) -> dict[str, str]:
        """Returns a dictionary of configuration file names and their absolute paths."""
        files = {}
        settings = Settings()
        env_file = settings.env_file
        if env_file.exists():
            files[".env"] = str(env_file)

        storage_dir = GUI_STORAGE_DIR
        if storage_dir.exists():
            # Add JSON files directly in the storage directory
            for f in storage_dir.glob("*.json"):
                files[f.name] = str(f)

            # Add JSON files from the guidelines subdirectory
            guidelines_dir = storage_dir / "guidelines"
            if guidelines_dir.exists():
                for f in guidelines_dir.glob("**/*.json"):
                    relative_path = f.relative_to(storage_dir)
                    files[str(relative_path)] = str(f)
        return files

    def export_settings(self, files_to_export: list[str]) -> bytes:
        """Creates a zip archive of the selected files and returns it as bytes."""
        zip_buffer = io.BytesIO()
        storage_dir = GUI_STORAGE_DIR
        with zipfile.ZipFile(zip_buffer, "w", zipfile.ZIP_DEFLATED) as zip_file:
            for file_path_str in files_to_export:
                file_path = Path(file_path_str)
                if file_path.exists():
                    arcname = file_path.name
                    # For files in subdirectories of storage, create a relative path
                    if file_path.parent != storage_dir and file_path.is_relative_to(storage_dir):
                        arcname = str(file_path.relative_to(storage_dir))
                    zip_file.write(file_path, arcname)
        zip_buffer.seek(0)
        return zip_buffer.getvalue()

    def import_settings(self, zip_file_bytes: bytes, files_to_import: list[str], mode: str):
        """Extracts the zip file and imports the settings."""
        if not zip_file_bytes:
            raise ValueError("No file provided.")

        zip_buffer = io.BytesIO(zip_file_bytes)
        with zipfile.ZipFile(zip_buffer, "r") as zip_file:
            name_list = zip_file.namelist()
            for file_name in files_to_import:
                if file_name not in name_list:
                    continue

                content = zip_file.read(file_name)
                if file_name == ".env":
                    settings = Settings()
                    target_path = settings.env_file
                    self._import_env(content, target_path, mode)
                else:  # All other files are expected to be in the storage dir
                    storage_dir = GUI_STORAGE_DIR
                    target_path = storage_dir / file_name
                    target_path.parent.mkdir(parents=True, exist_ok=True)
                    self._import_json(content, target_path, mode)

    def _import_env(self, content: bytes, target_path: Path, mode: str):
        content_str = content.decode("utf-8")
        if mode == "overwrite":
            target_path.write_text(content_str)
        elif mode == "update":
            settings = Settings()
            current_values = settings.settings
            new_values = io.StringIO(content_str)
            # This is a simple way to parse .env content
            for line in new_values:
                line = line.strip()
                if line and not line.startswith('#') and '=' in line:
                    key, value = line.split('=', 1)
                    key = key.strip()
                    if key not in current_values:
                        settings.set(key, value.strip())

    def _import_json(self, content: bytes, target_path: Path, mode: str):
        new_data = json.loads(content)

        if mode == "overwrite" or not target_path.exists():
            target_path.write_text(json.dumps(new_data, indent=4))
        elif mode == "update":
            with open(target_path, "r") as f:
                existing_data = json.load(f)
            for key, value in new_data.items():
                if key not in existing_data:
                    existing_data[key] = value
            target_path.write_text(json.dumps(existing_data, indent=4))
