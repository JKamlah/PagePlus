from pathlib import Path
import shutil
import subprocess
import sys
from typing import Annotated

import typer
from rich import print

from pageplus.utils.constants import PagePlus
from pageplus.utils.workspace import Workspace
from pageplus.utils.envs import get_env_path
from dotenv import load_dotenv, dotenv_values, set_key

app = typer.Typer()


@app.command(rich_help_panel="PagePlus")
def update_pip() -> None:
    """
    Updates pip version

    Returns:
    None
    """
    subprocess.check_call(
        [sys.executable, "-m", "pip", "install", "-U", "pip"])


@app.command(rich_help_panel="PagePlus")
def update_ssl() -> None:
    """
    Updates ssl-certificates for download options
    Returns:
    None
    """
    subprocess.check_call([sys.executable,
                           "-m",
                           "pip",
                           "install",
                           "-U",
                           "PyOpenSSL",
                           "cryptography",
                           "ndg-httpsclient"])


@app.command(rich_help_panel="PagePlus")
def update_pageplus() -> None:
    """
    Updates PagePlus dependencies

    Returns:
    None
    """
    subprocess.check_call(["poetry", "update"])


@app.command(rich_help_panel="Logs")
def clean_logs() -> None:
    """
    Clean all log files.

    Returns:
    None
    """
    # Create a Path object for the directory
    path = Path(__file__).parents[2].joinpath('logs')
    print(path)
    # Iterate over all files in the directory
    for log_file in path.glob('*.log'):
        try:
            log_file.unlink()  # Delete the file
            print(f"Deleted log file: {log_file}")
        except OSError as e:
            print(f"Error: {e} - {log_file}")


@app.command(rich_help_panel="Default Settings")
def set_open_folder_default(default_true: Annotated[bool, typer.Argument(
        help="Opens the folder with the results after processing.")] = True) -> None:
    """Set the directory where all workspaces by all environments get stored"""
    dotfile = get_env_path()
    set_key(
        dotfile,
        PagePlus.SYSTEM.as_prefix() +
        'OPEN_FOLDER',
        str(default_true))


@app.command(rich_help_panel="Workspace")
def set_workspace_dir(wsdir: Annotated[Path, typer.Argument(
        help="Path to the directory where all workspaces get stored. Default: Tempfolder")],) -> None:
    """Set the directory where all workspaces by all environments get stored"""
    dotfile = get_env_path()
    wsdir.mkdir(parents=True, exist_ok=True)
    set_key(
        dotfile, PagePlus.SYSTEM.as_prefix_workspace_dir(), str(
            wsdir.absolute()))


@app.command(rich_help_panel="Workspace")
def set_workspace_dir_to_tempfolder() -> None:
    """Is workspace directory is unset, the data is stored in the temp folder."""
    dotfile = get_env_path()
    set_key(dotfile, PagePlus.SYSTEM.as_prefix_workspace_dir(), 'tmp')


@app.command(rich_help_panel="Workspace")
def clean_workspace_dir() -> None:
    """
    Cleans all folders containing 'PagePlus' in their names within the specified workspace directory.
    Which are no longer defined in the dot environment file.
    """
    load_dotenv()
    envs = dotenv_values()
    tempdir = Workspace().dir()
    for pp_folder in tempdir.glob('*PagePlus_*'):
        if str(pp_folder) not in list(envs.values()):
            try:
                shutil.rmtree(pp_folder)
                print(f"Deleted folder: {pp_folder}")
            except Exception as e:
                print(f"Error deleting folder {pp_folder}: {e}")


@app.command(rich_help_panel="Dotenv")
def set_result_dir(
    path: Annotated[Path,
                    typer.Argument(help="Path to the result directory.",
                                   exists=True,
                                   file_okay=False,
                                   dir_okay=True,
                                   writable=True,
                                   readable=True,
                                   resolve_path=True)]) -> None:
    """
    Set the directory where all results get stored.
    """

    dotfile = get_env_path()
    set_key(dotfile, "PAGEPLUS_RESULT", str(path))
    print(f"The result directory has been set to {path}")


@app.command(rich_help_panel="Dotenv")
def set_modified_dir(
    path: Annotated[Path,
                    typer.Argument(help="Path to the modified directory.",
                                   exists=True,
                                   file_okay=False,
                                   dir_okay=True,
                                   writable=True,
                                   readable=True,
                                   resolve_path=True)]) -> None:
    """
    Set the directory where all modified files get stored.
    """
    dotfile = get_env_path()
    set_key(dotfile, "PAGEPLUS_MODIFIED", str(path))
    print(f"The modified directory has been set to {path}")


@app.command(rich_help_panel="Dotenv")
def set_user_agent(agent: Annotated[str, typer.Argument(help="Set the user agent for all requests.")]) -> None:
    """
    Set the user agent for all requests.
    """
    dotfile = get_env_path()
    set_key(dotfile, "PAGEPLUS_USER_AGENT", agent)
    print(f"The user agent has been set to {agent}")


@app.command(rich_help_panel="Dotenv")
def set_redirect_url(url: Annotated[str, typer.Argument(help="Set the redirect url for the gui shutdown.")]) -> None:
    """
    Set the redirect url for the gui shutdown.
    """
    dotfile = get_env_path()
    set_key(dotfile, "PAGEPLUS_REDIRECT_URL", url)
    print(f"The redirect url has been set to {url}")


@app.command(rich_help_panel="Dotenv")
def show_dotenv() -> None:
    """
    Show all dotenv variables.
    """
    load_dotenv(dotenv_path=get_env_path())
    envs = dotenv_values(dotenv_path=get_env_path())
    for var, key in envs.items():
        print(f"{var}={key}")


@app.command(rich_help_panel="Dotenv")
def create_empty_dotenv() -> None:
    """
    Create an empty .env file if it not exist.
    """
    if not get_env_path().exists():
        with open(get_env_path(), "w") as f:
            f.write("""PAGEPLUS_ORIGINAL=''
PAGEPLUS_MODIFIED='PagePlusOutput'
PAGEPLUS_ENVIRONMENT='PagePlus'
PAGEPLUS_LOADED_WS=''
SYSTEM_WS_DIR='tmp'
SYSTEM_OPEN_FOLDER = 'True'
ESCRIPTORIUM_URL=''
ESCRIPTORIUM_BASE_URL=''
ESCRIPTORIUM_USERNAME=''
ESCRIPTORIUM_PASSWORD=''
TRANSKRIBUS_USERNAME=''
TRANSKRIBUS_PASSWORD=''
LLM_PROVIDER='OPENAI__DEFAULT'
LLM_OPENAI__DEFAULT_API_KEY=''
LLM_OPENAI__DEFAULT_MODEL=''
LLM_OPENAI__DEFAULT_API_BASE=''""")
        print("An empty .env file has been created.")


if __name__ == "__main__":
    create_empty_dotenv()
    app()
