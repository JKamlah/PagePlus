from pathlib import Path

import typer
from rich import print
from rich.table import Table
from typing_extensions import Annotated

app = typer.Typer()

from dotenv import load_dotenv, find_dotenv, get_key, set_key

from pageplus.utils.constants import Environments
from pageplus.utils.workspace import Workspace


def current_workspace() -> Workspace:
    env = get_key(find_dotenv(), Environments.PAGEPLUS.as_prefix_environment())
    return Workspace(Environments[env]) if env else Workspace(Environments.PAGEPLUS)


pp_workspace = current_workspace()


### Environment ###
@app.command(rich_help_panel="Environment")
def set_environment(environment: Annotated[Environments, typer.Argument(help="Name of environment")]) -> None:
     """
     Set the default environment - you can use our environment workspace names as input in the pageplus functions
     and the loaded workspace is used if no input path is given
     """
     dotfile = find_dotenv()
     set_key(dotfile, Environments.PAGEPLUS.as_prefix_environment(), environment.name)
     print(f"[green]Environment is updated:[green] {environment.value}")


@app.command(rich_help_panel="Environment")
def get_environment() -> None:
     """
     Get the default environment - you can use our environment workspace names as input in the pageplus functions
     and the loaded workspace is used if no input path is given
     """
     dotfile = find_dotenv()
     get_key(dotfile, Environments.PAGEPLUS.as_prefix_environment())
     table = Table(title=f"[green]{Environments.PAGEPLUS.value} Environment[/green]")
     table.add_column("Setting", justify="right", style="cyan", no_wrap=True)
     table.add_column("Value")
     table.add_row(f"Loaded environment",
                   Environments[get_key(dotfile, Environments.PAGEPLUS.as_prefix_environment())])
     print(table)


### WORKSPACE ###
def validate_workspace(ctx: typer.Context, param: typer.CallbackParam, value: str) -> str:
    """
    Callback function to validate the workspace option against the dynamic list,
    ensuring case-insensitive comparison.
    """
    return pp_workspace.validate(value)


@app.command(rich_help_panel="Workspace")
def show_workspaces() -> None:
    """
    Print all workspaces
    Returns:
    None
    """
    pp_workspace.show()


@app.command(rich_help_panel="Workspace")
def load_workspace(workspace: Annotated[str, typer.Argument(help="Set environmental name",
                                                              callback=validate_workspace)]) -> None:
    """
    Set default workspace
    Returns:
    None
    """
    pp_workspace.load(workspace)


@app.command(rich_help_panel="Workspace")
def update_workspaces() -> None:
    """
    Check if the workspaces still exist and updates the dotenv
    Returns:
    None
    """
    pp_workspace.update()


@app.command(rich_help_panel="Workspace")
def delete_workspace(workspace: Annotated[str, typer.Argument(help="Set environmental name",
                                                              callback=validate_workspace)]) -> None:
    """
    Deletes an existing workspace
    Returns:
    None
    """
    pp_workspace.delete(workspace)


@app.command(rich_help_panel="Workspace")
def copy_workspace(destination_path: Annotated[Path,
                   typer.Argument(help="Path to the output directory where the text files will be saved")],
                    workspace: Annotated[str,
                   typer.Argument(help=f"Workspace name pointing to an existing path",
                                  callback=validate_workspace)] = None,
                   new_workspace: Annotated[str,
                   typer.Option(help=f"If set a new workspace is created.")] = "") \
        -> None:
    """
    Copy pages of from a workspace path to another location
    Returns:
    None
    """
    pp_workspace.copy(destination_path, workspace, new_workspace)


@app.command(rich_help_panel="Workspace")
def open_workspace(workspace: Annotated[
    str, typer.Argument(help=f"Workspace name pointing to an existing path",
                        callback=validate_workspace)] = None) -> None:
    """
    Open a workspace folder in the file explorer, works for Windows, macOS, and Linux.
    """
    pp_workspace.open(workspace)


@app.command(rich_help_panel="Document")
def load_local_document(
        inputdir: Annotated[
            Path, typer.Argument(help="Path to the output directory where the text files will be saved")],
        workspace: Annotated[str, typer.Argument(help="Set environmental name")],
        overwrite_workspace: Annotated[bool, typer.Option(help="Overwrite environmental name")] = False,
        loading: Annotated[bool, typer.Option(help="Load the created workspace as default")] = True):
    """
    Set an environmental variable to an existing folder
    Returns:
    None
    """
    #TODO: Validationcheck missing
    load_dotenv()
    if workspace in pp_workspace.names() and not overwrite_workspace:
        print(f"[red bold]Warning:[/red bold] The environment variable {workspace} already exists."
              " Please set [green]overwrite-workspace[/green] "
              "to True, if you want to overwrite the workspace.")
    if inputdir.is_dir():
        set_key(find_dotenv(), pp_workspace.prefix_ws + workspace, str(inputdir.absolute()))
        if loading:
            load_workspace(pp_workspace.prefix_ws + workspace)
    else:
        print(f"[red]Warning:[/red] The inputdir does not point to an existing folder.")


if __name__ == "__main__":
    app()
