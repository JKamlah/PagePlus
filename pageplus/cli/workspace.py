import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import zipfile
from datetime import datetime
from enum import Enum
from importlib import util
from io import BytesIO
from pathlib import Path
from shutil import rmtree
from typing import List

import typer
from rich import print
from rich.table import Table
from typing_extensions import Annotated

app = typer.Typer()

from dotenv import load_dotenv, find_dotenv, get_key, set_key, dotenv_values, unset_key

from pageplus.utils.constants import Environments, WorkState, Bool2OnOff
from pageplus.utils.envs import str_to_env

ENV = Environments.PAGEPLUS.value
PREFIX = Environments.PAGEPLUS.as_prefix()
PREFIX_WS = Environments.PAGEPLUS.as_prefix_workspace()
PREFIX_LOADED_WS = Environments.PAGEPLUS.as_prefix_loaded_workspace()

def filter_envs(pattern: str) -> dict:
    """
    Filters dotenv values for a specific pattern (e.g. services, prefixes, ..)
    Returns:
        dict
    """
    load_dotenv()
    envs = dotenv_values()
    return dict(sorted([(var, key) for (var, key) in envs.items() if var.startswith(pattern)], key=lambda x: x[0]))


@app.command(rich_help_panel="Workspace")
def show_workspaces() -> None:
    """
    Print all workspaces
    Returns:
    None
    """
    table = Table(title=f"[green]{ENV} workspaces[/green]")
    table.add_column(f"{ENV} workspace", justify="right", style="cyan", no_wrap=True)
    table.add_column("Workspace folder")
    loaded = get_key(find_dotenv(), PREFIX_LOADED_WS)
    if loaded:
        key = ''.join([f"{loaded.replace(env.as_prefix_workspace(), '')} ({env.value})" for env in Environments if loaded.startswith(env.as_prefix_workspace())])
        table.add_row('[green bold]Loaded workspace[/green bold]', f"[cyan]{key}[/cyan]")
    [table.add_row(var.replace(PREFIX_WS, ''), key) for (var, key) in filter_envs(PREFIX_WS).items()]
    print(table)


def workspace_names(ws=PREFIX_WS):
    """
    Return workspace names directly, assuming these are valid
    Conversion to lowercase for case-insensitive handling is done in the callback
    """
    return [var.replace(ws, '') for var in filter_envs(ws).keys()]


def validate_workspace(ctx: typer.Context, param: typer.CallbackParam, value: str) -> str:
    """
    Callback function to validate the workspace option against the dynamic list,
    ensuring case-insensitive comparison.
    """
    value = get_key(find_dotenv(), PREFIX_LOADED_WS) if value is None else value
    dynamic_options = workspace_names('')
    env_value = str_to_env(value)
    if env_value not in dynamic_options:
        raise typer.BadParameter(f"Invalid option: {value}. Please choose from {dynamic_options}.")
    return env_value


def set_external_ws(ctx: typer.Context, param: typer.CallbackParam, value: Environments) -> Environments:
    """
    Callback function to validate the workspace option against the dynamic list,
    ensuring case-insensitive comparison.
    """
    os.environ[PREFIX+'LOADED_ENV'] = value.name
    return value.value


def validate_external_workspace(ctx: typer.Context, param: typer.CallbackParam, value: str) -> str:
    """
    Callback function to validate the workspace option against the dynamic list,
    ensuring case-insensitive comparison.
    """
    env = Environments[os.environ[PREFIX+'LOADED_ENV']]
    dynamic_options = workspace_names(env.as_prefix_workspace())
    env_value = str_to_env(value)
    if env_value not in dynamic_options:
        raise typer.BadParameter(f"Invalid option: {value}. Please choose from {dynamic_options}.")
    return env_value


@app.command(rich_help_panel="Workspace")
def set_environment(environment: Annotated[Environments, typer.Argument(help="Name of environment")]) -> None:
     """
     Set the default environment - you can use our environment workspace names as input in the pageplus functions
     and the loaded workspace is used if no input path is given
     """
     dotfile = find_dotenv()
     set_key(dotfile, Environments.PAGEPLUS.as_prefix_environment(), environment.name)


@app.command(rich_help_panel="Workspace")
def get_environment() -> None:
     """
     Get the default environment - you can use our environment workspace names as input in the pageplus functions
     and the loaded workspace is used if no input path is given
     """
     dotfile = find_dotenv()
     get_key(dotfile, Environments.PAGEPLUS.as_prefix_environment())
     table = Table(title=f"[green]{ENV} Environment[/green]")
     table.add_column("Setting", justify="right", style="cyan", no_wrap=True)
     table.add_column("Value")
     table.add_row(f"Loaded environment", Environments[get_key(dotfile, Environments.PAGEPLUS.as_prefix_environment())])
     print(table)


@app.command(rich_help_panel="Workspace")
def load_workspace(environment: Annotated[Environments, typer.Argument(help="Choose environment", callback=set_external_ws)],
                   workspace: Annotated[str, typer.Argument(help="Choose workspace",
                                                            callback=validate_external_workspace)]) -> None:
    """
    Set default workspace
    Returns:
    None
    """
    dotfile = find_dotenv()
    workspace = str_to_env(workspace)
    set_key(dotfile, PREFIX_LOADED_WS, environment.as_prefix_workspace()+workspace)


@app.command(rich_help_panel="Workspace")
def set_workspace(environment: Annotated[Environments, typer.Argument(help="Choose environment", callback=set_external_ws)],
                  workspace: Annotated[str, typer.Argument(help="Choose workspace",
                                                            callback=validate_external_workspace)],
                  name: Annotated[str, typer.Argument(help="Choose name for the workspace",
                                                            callback=validate_external_workspace)]) -> None:
    """
    Set workspace from another environment
    Returns:
    None
    """
    dotfile = find_dotenv()
    workspace = str_to_env(workspace)
    set_key(dotfile, PREFIX_WS+str_to_env(name), environment.as_prefix_workspace()+workspace)


@app.command(rich_help_panel="Workspace")
def update_workspaces() -> None:
    """
    Check if the workspaces still exist and updates the dotenv
    Returns:
    None
    """
    dotenv_path = find_dotenv()
    for (var, key) in filter_envs(PREFIX_WS).items():
        if not Path(key).exists():
            print(f"Workspace {var.replace(PREFIX_WS, '')} does not exist anymore and will be deleted!")
            unset_key(dotenv_path, var)
    for (var, key) in filter_envs(PREFIX_LOADED_WS).items():
        workspace = PREFIX_WS+get_key(dotenv_path, PREFIX_LOADED_WS)
        if not get_key(dotenv_path, workspace):
            print(f"Loaded workspace does not exist anymore and will set to empty!")
            set_key(find_dotenv(), var, '')


@app.command(rich_help_panel="Workspace")
def delete_workspace(workspace: Annotated[str, typer.Argument(help="Set environmental name",
                                                              callback=validate_workspace)],
                     delete_data: Annotated[bool, typer.Option(help="Overwrite workspace name")] = False) -> None:
    """
    Deletes an existing workspace
    Returns:
    None
    """
    dotenv_path = find_dotenv()
    workspace = PREFIX_WS + workspace
    wsfolder = Path(get_key(dotenv_path, workspace))
    if wsfolder.exists() and delete_data:
        shutil.rmtree(str(wsfolder.absolute()))
    unset_key(dotenv_path, workspace)
    if get_key(dotenv_path, PREFIX_LOADED_WS) == workspace.replace(PREFIX_WS, ''):
        set_key(dotenv_path, PREFIX_LOADED_WS, '')
    print(f"Workspace {workspace.replace(PREFIX_WS, '')} was deleted!")


@app.command(rich_help_panel="Document")
def load_local_document(
        inputdir: Annotated[
            Path, typer.Argument(help="Path to the output directory where the text files will be saved")],
        workspace: Annotated[str, typer.Argument(help="Set workspace name")],
        overwrite_workspace: Annotated[bool, typer.Option(help="Overwrite workspace name")] = False,
        loading: Annotated[bool, typer.Option(help="Load the created workspace as default")] = True):
    """
    Set an environmental variable to an existing folder
    Returns:
    None
    """
    #TODO: Validationcheck missing
    load_dotenv()
    if workspace in workspace_names() and not overwrite_workspace:
        print(f"[red bold]Warning:[/red bold] The environment variable {workspace} already exists."
              " Please set [green]overwrite-workspace[/green] "
              "to True, if you want to overwrite the workspace.")
    if inputdir.is_dir():
        set_key(find_dotenv(), PREFIX_WS + workspace, str(inputdir.absolute()))
        if loading:
            load_workspace('PagePlus', PREFIX_WS + workspace)
    else:
        print(f"[red]Warning:[/red] The inputdir does not point to an existing folder.")


@app.command(rich_help_panel="Workspace")
def copy_workspace(destination_path: Annotated[Path,
                   typer.Argument(help="Path to the output directory where the text files will be saved")],
                   workspace: Annotated[str, typer.Option(help="A path or an workspace name pointing to an existing path",
                                                              callback=validate_workspace)] = None,
                   new_workspace: Annotated[str,
                   typer.Option(help=f"If set a new workspace is created.")] = "") -> None:
    """
    Copy pages of from a workspace path to another location
    Returns:
    None
    """
    load_dotenv()
    envs = dotenv_values()
    workspace = envs.get(PREFIX_LOADED_WS, '') if not workspace else str_to_env(workspace)
    if workspace == '':
        print("Please provide a valid workspace or load workspace.")
        return
    wsfolder = Path(envs.get(workspace, None)) if envs.get(workspace, None) else Path(envs.get(PREFIX_WS + workspace, None))
    if wsfolder.exists():
        Path(destination_path).parent.mkdir(parents=True, exist_ok=True)
        shutil.copy(wsfolder, destination_path)
        if new_workspace != "":
            new_workspace = str_to_env(new_workspace)
            set_key(find_dotenv(), PREFIX_WS+new_workspace, str(Path(destination_path).absolute()))


@app.command(rich_help_panel="Workspace")
def open_workspace(workspace: Annotated[str, typer.Option(help="A path or an environmental name pointing to an existing path",
                                                              callback=validate_workspace)] = None) -> None:
    """
    Open a workspace folder in the file explorer, works for Windows, macOS, and Linux.
    """
    load_dotenv()
    envs = dotenv_values()
    workspace = envs.get(PREFIX_LOADED_WS, '') if not workspace else str_to_env(workspace)
    if workspace == '':
        print("Please provide a valid workspace or load workspace.")
        return
    wsfolder = Path(envs.get(workspace, None)) if envs.get(workspace, None) else Path(envs.get(PREFIX_WS + workspace, None))
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


if __name__ == "__main__":
    app()
