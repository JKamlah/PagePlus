from pageplus.utils.workspace import Workspace
from pageplus.utils.constants import Environments
from dotenv import load_dotenv, find_dotenv, get_key, set_key
from pathlib import Path

import typer
from rich import print
from typing_extensions import Annotated

app = typer.Typer()


def current_workspace() -> Workspace:
    env = get_key(find_dotenv(), Environments.PAGEPLUS.as_prefix_environment())
    return Workspace(
        Environments[env]) if env else Workspace(
        Environments.PAGEPLUS)


def pp_workspace():
    return current_workspace()

# WORKSPACE #


def validate_workspace(
        ctx: typer.Context,
        param: typer.CallbackParam,
        value: str) -> str:
    """
    Callback function to validate the workspace option against the dynamic list,
    ensuring case-insensitive comparison.
    """
    return pp_workspace().validate(value)


@app.command(rich_help_panel="Workspace")
def show_workspaces() -> None:
    """
    Print all workspaces
    Returns:
    None
    """
    pp_workspace().show()


@app.command(rich_help_panel="Workspace")
def load_workspace(workspace: Annotated[str, typer.Argument(
        help="Set environmental name", callback=validate_workspace)]) -> None:
    """
    Set default workspace
    Returns:
    None
    """
    pp_workspace().load(workspace)


@app.command(rich_help_panel="Workspace")
def update_workspaces() -> None:
    """
    Check if the workspaces still exist and updates the dotenv
    Returns:
    None
    """
    pp_workspace().update()


@app.command(rich_help_panel="Workspace")
def backup_xmlfiles(backup_folder: Annotated[Path,
                                             typer.Argument(help="Foldername to the backup xml files")] = Path('Backup'),
                    workspace: Annotated[str,
                                         typer.Argument(help="Workspace name pointing to an existing path",
                                                        callback=validate_workspace)] = None,
                    ) -> None:
    """
    Create a backup of the xml files
    Returns:
    None
    """
    pp_workspace().backup(backup_folder, workspace)


@app.command(rich_help_panel="Workspace")
def restore_xmlfiles(backup_folder: Annotated[Path,
                                              typer.Argument(help="Foldername to the backup xml files")] = Path('Backup'),
                     workspace: Annotated[str,
                                          typer.Argument(help="Workspace name pointing to an existing path",
                                                         callback=validate_workspace)] = None,
                     ) -> None:
    """
    Create a backup of the xml files
    Returns:
    None
    """
    pp_workspace().restore(backup_folder, workspace)


@app.command(rich_help_panel="Workspace")
def delete_workspace(workspace: Annotated[str, typer.Argument(
        help="Set environmental name", callback=validate_workspace)]) -> None:
    """
    Deletes an existing workspace
    Returns:
    None
    """
    pp_workspace().delete(workspace)


@app.command(rich_help_panel="Workspace")
def copy_workspace(destination_path: Annotated[Path,
                                               typer.Argument(help="Path to the output directory where the text files will be saved")],
                   workspace: Annotated[str,
                                        typer.Argument(help="Workspace name pointing to an existing path",
                                                       callback=validate_workspace)] = None,
                   new_workspace: Annotated[str,
                                            typer.Option(help="If set a new workspace is created.")] = "") -> None:
    """
    Copy pages of from a workspace path to another location
    Returns:
    None
    """
    pp_workspace().copy(destination_path, workspace, new_workspace)


@app.command(rich_help_panel="Workspace")
def open_workspace(workspace: Annotated[
    str, typer.Argument(help="Workspace name pointing to an existing path",
                        callback=validate_workspace)] = None) -> None:
    """
    Open a workspace folder in the file explorer, works for Windows, macOS, and Linux.
    """
    pp_workspace().open(workspace)


@app.command(rich_help_panel="Document")
def load_local_document(inputdir: Annotated[Path,
                                            typer.Argument(help="Path to the output directory where the text files will be saved")],
                        workspace: Annotated[str,
                                             typer.Argument(help="Set environmental name")],
                        overwrite_workspace: Annotated[bool,
                                                       typer.Option(help="Overwrite environmental name")] = False,
                        loading: Annotated[bool,
                                           typer.Option(help="Load the created workspace as default")] = True):
    """
    Set an environmental variable to an existing folder
    Returns:
    None
    """
    # TODO: Validationcheck missing
    from pageplus.utils.envs import str_to_env
    load_dotenv()
    workspace = str_to_env(workspace)
    if workspace == '':
        print(
            "[red bold]Warning:[/red bold] Workspace name is not valid[/red bold]")
        return
    if workspace in pp_workspace().names() and not overwrite_workspace:
        print("[red bold]Warning:[/red bold] The environment variable {workspace} already exists."
              " Please set [green]overwrite-workspace[/green] "
              "to True, if you want to overwrite the workspace.")
    if inputdir.is_dir():
        set_key(find_dotenv(), pp_workspace().prefix_ws +
                workspace, str(inputdir.absolute()))
        if loading:
            load_workspace(workspace)
    else:
        print(
            "[red]Warning:[/red] The inputdir does not point to an existing folder.")


if __name__ == "__main__":
    app()
