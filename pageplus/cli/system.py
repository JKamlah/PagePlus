from pathlib import Path
import shutil
import subprocess
import sys
from typing import Annotated

from dotenv import load_dotenv, dotenv_values, find_dotenv, set_key, unset_key
import typer
from rich import print

from pageplus.utils.constants import Environments
from pageplus.utils.fs import workspace_dir

app = typer.Typer()

@app.command(rich_help_panel="PagePlus")
def update_pip() -> None:
    """
    Updates pip version

    Returns:
    None
    """
    subprocess.check_call([sys.executable, "-m", "pip", "install", "-U", "pip"])

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

@app.command(rich_help_panel="Workspace")
def set_workspace_dir(dir: Annotated[Path,
                       typer.Argument(help="Path to the directory where all workspaces get stored. Default: Tempfolder")],) -> None:
    dotfile = find_dotenv()
    dir.mkdir(parents=True, exist_ok=True)
    set_key(dotfile, f"{Environments.PAGEPLUS.name}_WS_DIR", str(dir.absolute()))

@app.command(rich_help_panel="Workspace")
def unset_workspace_dir(rich_help_panel="Workspace") -> None:
    dotfile = find_dotenv()
    unset_key(dotfile, f"{Environments.PAGEPLUS.name}_WS_DIR")

@app.command(rich_help_panel="Workspace")
def clean_workspace_dir() -> None:
    """
    Cleans all folders containing 'PagePlus' in their names within the specified workspace directory.
    Which are no longer defined in the dot environment file.
    """
    load_dotenv()
    envs = dotenv_values()
    tempdir = workspace_dir()
    for pp_folder in tempdir.glob('*PagePlus_*'):
        if str(pp_folder) not in list(envs.values()):
            try:
                shutil.rmtree(pp_folder)
                print(f"Deleted folder: {pp_folder}")
            except Exception as e:
                print(f"Error deleting folder {pp_folder}: {e}")

@app.command(rich_help_panel="Settings")
def create_empty_dotenv() -> None:
    """
    This will also overwrite an existing .env file
    Returns:
    """
    path = Path(__file__).parents[2].joinpath('.env')
    with open(path, 'w') as f:
        f.write("""PAGEPLUS_ORIGINAL=''
PAGEPLUS_MODIFIED='PagePlusOutput'""")


if not Path(__file__).parents[2].joinpath('.env').exists():
    create_empty_dotenv()

if __name__ == "__main__":
    app()
