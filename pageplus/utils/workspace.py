import os
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Type
import zipfile

import typer
from dotenv import (dotenv_values, get_key, load_dotenv, set_key,
                    unset_key)
from rich import print
from rich.table import Table
from typing_extensions import Annotated

from pageplus.utils.constants import Environments, PagePlus
from pageplus.utils.envs import filter_dotenv, str_to_env, get_env_path
from pageplus.io.logger import logging

logger = logging.getLogger(__name__)


@dataclass
class Workspace:
    environment: Environments | Type[Environments] = Environments.PAGEPLUS
    env_value: str = field(init=False)
    env_prefix: str = field(init=False)
    prefix_ws: str = field(init=False)
    prefix_loaded_ws: str = field(init=False)

    def __post_init__(self):
        self.env = self.environment.value
        self.prefix = self.environment.as_prefix()
        self.prefix_ws = self.environment.as_prefix_workspace()
        self.prefix_loaded_ws = self.environment.as_prefix_loaded_workspace()

    def validate(self, value: str) -> str:
        """
        Callback function to validate the workspace option against the dynamic list,
        ensuring case-insensitive comparison.
        """
        value = get_key(
            get_env_path(),
            self.prefix_loaded_ws).replace(
            self.prefix_ws,
            '') if value is None else value
        dynamic_options = self.names()
        # Check if value is empty or None before calling str_to_env
        if not value or value.strip() == '':
            raise typer.BadParameter(
                "Empty workspace name. Please provide a valid workspace name.")
        env_value = str_to_env(value)
        if env_value not in dynamic_options:
            raise typer.BadParameter(
                f"Invalid option: {value}. Please choose from {dynamic_options}.")
        return env_value

    @staticmethod
    def dir(ws_dir: str = PagePlus.SYSTEM.as_prefix_workspace_dir()) -> Path:
        """
        Get current workspace directory (Default: Tempfolder)
        Returns:
        """
        dotfile = get_env_path()
        ws_dir = get_key(dotfile, ws_dir)
        return Path(ws_dir) if (
            ws_dir and ws_dir != 'tmp') else Path(
            tempfile.gettempdir())

    @staticmethod
    def prefix_dir(prefix: str = Environments.PAGEPLUS.value) -> str:
        """
        Get workspace directory prefix with timestamp
        Returns:
        """
        return prefix + datetime.now().strftime('_%Y-%m-%d_')

    def show(self):
        table = Table(title=f"[green]{self.env} workspaces[/green]")
        table.add_column(f"{self.env} workspace",
                         justify="right", style="cyan", no_wrap=True)
        table.add_column("Workspace folder")
        [table.add_row('[green bold]Loaded workspace[/green bold]',
                       f"[cyan]{key.replace(self.prefix_ws, '')}[/cyan]")
         for (val, key) in filter_dotenv(self.prefix_loaded_ws).items()]
        [table.add_row(val.replace(self.prefix_ws, ''), key) for (val, key)
         in filter_dotenv(self.prefix_ws).items()]
        print(table)

    def names(self):
        """
        Return workspace names directly, assuming these are valid
        Conversion to lowercase for case-insensitive handling is done in the callback
        """
        return [key.replace(self.prefix_ws, '')
                for key in filter_dotenv(self.prefix_ws).keys()]

    def loaded(self):
        """
        Get name of the loaded workspace
        Returns:
            str or None: The loaded workspace name, or None if no workspace is loaded
        """
        loaded_workspaces = [
            val.replace(
                self.prefix_ws,
                '') for val in filter_dotenv(
                self.prefix_loaded_ws).values()]
        return loaded_workspaces[0] if loaded_workspaces else None

    def path(self, workspace: str) -> str:
        """
        Get path of a workspace
        Returns:
        """
        return get_key(get_env_path(), self.prefix_ws + workspace)

    def update_path(self, workspace: str, path: str) -> None:
        """
        Set path of a workspace
        Returns:
        """
        return set_key(get_env_path(), self.prefix_ws + workspace, path) if Path(path).exists() else None

    def load(self, workspace: str) -> None:
        """
        Set default workspace
        Returns:
        None
        """
        dotfile = get_env_path()
        if workspace == '':
            set_key(dotfile, self.prefix_loaded_ws, workspace)
        else:
            workspace = self.prefix_ws + str_to_env(workspace)
            if get_key(dotfile, workspace):
                set_key(dotfile, self.prefix_loaded_ws, workspace)
            else:
                print(f"[red]Warning: {workspace} workspace not found![/red]")

    def update(self) -> None:
        """
        Check if the workspaces still exist and updates the dotenv
        Returns:
        None
        """
        dotenv_path = get_env_path()
        for (var, key) in filter_dotenv(self.prefix_ws).items():
            if not Path(key).exists():
                print(
                    f"Workspace {var.replace(self.prefix_ws, '')} does not exist anymore and will be deleted!")
                unset_key(dotenv_path, var)
        for (var, key) in filter_dotenv(self.prefix_loaded_ws).items():
            workspace = self.prefix_ws + \
                get_key(dotenv_path, self.prefix_loaded_ws)
            if not get_key(dotenv_path, workspace):
                print(
                    "Loaded workspace does not exist anymore and will set to empty!")
                set_key(get_env_path(), var, '')

    def delete(self, workspace: str, all_files: bool = False) -> None:
        """
        Deletes an existing workspace
        Returns:
        None
        """
        dotenv_path = get_env_path()
        workspace = self.prefix_ws + workspace
        wsfolder = Path(get_key(dotenv_path, workspace))
        if wsfolder.exists() and all_files:
            shutil.rmtree(str(wsfolder.absolute()))
        unset_key(dotenv_path, workspace)
        if get_key(dotenv_path, self.prefix_loaded_ws) == workspace:
            set_key(dotenv_path, self.prefix_loaded_ws, '')
        print(f"Workspace {workspace.replace(self.prefix_ws, '')} was deleted!")

    def copy(
            self,
            destination_path: Path,
            workspace: str,
            new_workspace: str) -> None:
        """
        Copy pages of from a workspace path to another location
        Returns:
        None
        """
        load_dotenv()
        envs = dotenv_values()
        workspace = envs.get(
            self.prefix_loaded_ws,
            '').replace(
            self.prefix_ws,
            '') if not workspace else str_to_env(workspace)
        if workspace == '':
            print("Please provide a valid workspace or load workspace.")
            return
        wsfolder = Path(get_key(get_env_path(), self.prefix_ws + workspace))
        if wsfolder.exists():
            Path(destination_path).parent.mkdir(parents=True, exist_ok=True)
            shutil.copy(wsfolder, destination_path)
            if new_workspace != "":
                new_workspace = str_to_env(new_workspace)
                set_key(get_env_path(), self.prefix_ws +
                        new_workspace, str(Path(destination_path).absolute()))

    def backup(
            self,
            backup_folder: Path = Path('Backup'),
            workspace: str = None,
            as_zip: bool = False) -> None:
        """
        Create a backup of files in the workspace.
        If as_zip is True, create a flat zip archive containing only XML files.
        Otherwise, it backs up all files into a directory.
        """
        load_dotenv()
        envs = dotenv_values()
        workspace = envs.get(
            self.prefix_loaded_ws,
            '').replace(
            self.prefix_ws,
            '') if not workspace else str_to_env(workspace)
        if not workspace:
            print("Please provide a valid workspace or load a workspace.")
            return

        wsfolder = Path(get_key(get_env_path(), self.prefix_ws + workspace))
        if not wsfolder.exists():
            print(f"Workspace folder not found: {wsfolder}")
            return

        backup_path = wsfolder.joinpath(backup_folder)
        if as_zip:
            zip_path = wsfolder.joinpath(backup_folder).with_suffix('.zip')
            with zipfile.ZipFile(zip_path, 'w') as zipf:
                for file in wsfolder.glob("*.xml"):
                    if file.is_file():
                        zipf.write(file, file.name)
            print(f"Backup created: [bold green]{zip_path.name}[/bold green]")
        else:
            backup_path.mkdir(parents=True, exist_ok=True)
            files = [f for f in wsfolder.glob("*.xml") if f.is_file()]
            for file in files:
                shutil.copy(file, backup_path.joinpath(file.name))
            print(f"Backup created: [bold green]{len(files)} files[/bold green]")

    def restore(
            self,
            backup_folder: Path = Path('Backup'),
            workspace: str = None,
            from_zip: bool = False) -> None:
        """
        Restore a backup of the workspace files.
        """
        load_dotenv()
        envs = dotenv_values()
        workspace = envs.get(
            self.prefix_loaded_ws,
            '').replace(
            self.prefix_ws,
            '') if not workspace else str_to_env(workspace)
        if not workspace:
            print("Please provide a valid workspace or load a workspace.")
            return

        wsfolder = Path(get_key(get_env_path(), self.prefix_ws + workspace))
        if from_zip:
            backup_path = wsfolder.joinpath(backup_folder).with_suffix('.zip')
            if backup_path.exists():
                shutil.unpack_archive(backup_path, wsfolder)
                print("Restored: [bold green]files from zip[/bold green]")
            else:
                print(f"Backup zip not found: {backup_path}")
        else:
            backup_path = wsfolder.joinpath(backup_folder)
            if wsfolder.exists() and backup_path.exists():
                files = [f for f in backup_path.iterdir() if f.is_file()]
                for file in files:
                    shutil.copy(file, wsfolder)
                print(f"Restored: [bold green]{len(files)} files[/bold green]")
            else:
                print(f"Backup folder not found: {backup_path}")

    def open(self, workspace: str = None) -> None:
        """
        Open a workspace folder in the file explorer, works for Windows, macOS, and Linux.
        """
        load_dotenv()

        # If no workspace is provided, try to use the loaded one.
        if not workspace:
            workspace = self.loaded()

        # If still no workspace, inform the user and exit.
        if not workspace:
            print("No workspace specified or loaded. Please load a workspace first.")
            return

        # Get the path for the workspace.
        wsfolder_path_str = self.path(workspace)

        # Check if the path is valid.
        if not wsfolder_path_str:
            print(f"Path for workspace '{workspace}' not found.")
            return

        wsfolder = Path(wsfolder_path_str)
        if not wsfolder.exists():
            print(f"Path '{wsfolder}' does not exist. It can't be opened!")
            return

        # Open the folder using the appropriate command for the OS.
        if sys.platform == "win32":
            os.startfile(wsfolder)
        elif sys.platform == "darwin":
            # macOS
            subprocess.run(["open", wsfolder])
        else:
            # Linux and other Unix-like OS
            subprocess.run(["xdg-open", wsfolder])
        print(
            f"Opened workspace [bold green]{workspace}[/bold green]: {wsfolder.absolute()}")
