import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from collections import defaultdict
from datetime import datetime
from enum import Enum
from importlib import util
from pathlib import Path
from shutil import rmtree
from typing import List
from dataclasses import dataclass, field

import requests
import typer
from rich import print
from rich.status import Status
from rich.table import Table
from typing_extensions import Annotated, Optional

from dotenv import load_dotenv, find_dotenv, get_key, dotenv_values, set_key, unset_key

from pageplus.utils.constants import PagePlus, Environments
from pageplus.utils.envs import str_to_env, filter_envs

@dataclass
class Workspace:
    environment: Environments = Environments.PAGEPLUS
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
        value = get_key(find_dotenv(), self.prefix_loaded_ws).replace(self.prefix_ws, '') \
            if value is None else value
        dynamic_options = self.names()
        env_value = str_to_env(value)
        if env_value not in dynamic_options:
            raise typer.BadParameter(f"Invalid option: {value}. Please choose from {dynamic_options}.")
        return env_value


    @staticmethod
    def dir(ws_dir: str = PagePlus.SYSTEM.as_prefix_workspace_dir()) -> Path:
        """
        Get current workspace directory (Default: Tempfolder)
        Returns:
        """
        dotfile = find_dotenv()
        ws_dir = get_key(dotfile, ws_dir)
        return Path(ws_dir) if (ws_dir and ws_dir != 'tmp') else Path(tempfile.gettempdir())

    @staticmethod
    def prefix_dir(prefix: str = Environments.PAGEPLUS.value) -> str:
        """
        Get workspace directory prefix with timestamp
        Returns:
        """
        return prefix + datetime.now().strftime('_%Y-%m-%d_')


    def show(self):
        table = Table(title=f"[green]{self.env} workspaces[/green]")
        table.add_column(f"{self.env} workspace", justify="right", style="cyan", no_wrap=True)
        table.add_column("Workspace folder")
        [table.add_row('[green bold]Loaded workspace[/green bold]',
                       f"[cyan]{key.replace(self.prefix_ws, '')}[/cyan]")
         for (var, key) in filter_envs(self.prefix_loaded_ws).items()]
        [table.add_row(var.replace(self.prefix_ws, ''), key) for (var, key)
         in filter_envs(self.prefix_ws).items()]
        print(table)


    def names(self):
        """
        Return workspace names directly, assuming these are valid
        Conversion to lowercase for case-insensitive handling is done in the callback
        """
        return [var.replace(self.prefix_ws, '') for var in filter_envs(self.prefix_ws).keys()]


    def load(self, workspace: str) -> None:
        """
        Set default workspace
        Returns:
        None
        """
        dotfile = find_dotenv()
        workspace = self.prefix_ws+str_to_env(workspace)
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
        dotenv_path = find_dotenv()
        for (var, key) in filter_envs(self.prefix_ws).items():
            if not Path(key).exists():
                print(f"Workspace {var.replace(self.prefix_ws, '')} does not exist anymore and will be deleted!")
                unset_key(dotenv_path, var)
        for (var, key) in filter_envs(self.prefix_loaded_ws).items():
            workspace = self.prefix_ws+get_key(dotenv_path, self.prefix_loaded_ws)
            if not get_key(dotenv_path, workspace):
                print(f"Loaded workspace does not exist anymore and will set to empty!")
                set_key(find_dotenv(), var, '')


    def delete(self, workspace: str) -> None:
        """
        Deletes an existing workspace
        Returns:
        None
        """
        dotenv_path = find_dotenv()
        workspace = self.prefix_ws + workspace
        wsfolder = Path(get_key(dotenv_path, workspace))
        if wsfolder.exists():
            shutil.rmtree(str(wsfolder.absolute()))
        unset_key(dotenv_path, workspace)
        if get_key(dotenv_path, self.prefix_loaded_ws) == workspace:
            set_key(dotenv_path, self.prefix_loaded_ws, '')
        print(f"Workspace {workspace.replace(self.prefix_ws, '')} was deleted!")


    def copy(self, destination_path: Path , workspace: str, new_workspace: str)-> None:
        """
        Copy pages of from a workspace path to another location
        Returns:
        None
        """
        load_dotenv()
        envs = dotenv_values()
        workspace = envs.get(self.prefix_loaded_ws, '').replace(self.prefix_ws, '') \
            if not workspace else str_to_env(workspace)
        if workspace == '':
            print("Please provide a valid workspace or load workspace.")
            return
        wsfolder = Path(get_key(find_dotenv(), self.prefix_ws + workspace))
        if wsfolder.exists():
            Path(destination_path).parent.mkdir(parents=True, exist_ok=True)
            shutil.copy(wsfolder, destination_path)
            if new_workspace != "":
                new_workspace = str_to_env(new_workspace)
                set_key(find_dotenv(), self.prefix_ws+new_workspace, str(Path(destination_path).absolute()))


    def open(self, workspace: Annotated[
        str, typer.Argument(help=f"Workspace name pointing to an existing path",
                            callback=validate)] = None) -> None:
        """
        Open a workspace folder in the file explorer, works for Windows, macOS, and Linux.
        """
        load_dotenv()
        envs = dotenv_values()
        workspace = envs.get(self.prefix_loaded_ws, '').replace(self.prefix_ws, '') \
            if not workspace else str_to_env(workspace)
        if workspace == '':
            print("Please provide a valid workspace or load workspace.")
            return
        wsfolder = Path(envs.get(self.prefix_ws + workspace, None))
        if wsfolder == '' or wsfolder is None or not Path(wsfolder).exists():
            print(f"{wsfolder} can't be opened!")
            return
        if sys.platform == "win32":
            # Windows
            os.startfile(wsfolder)
        elif sys.platform == "darwin":
            # macOS
            subprocess.run(["open", wsfolder])
        else:
            # Linux and other Unix-like OS
            subprocess.run(["xdg-open", wsfolder])
        print(f"Opened workspace [bold green]{workspace}[/bold green]: {wsfolder.absolute()}")


