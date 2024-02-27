from pathlib import Path
import shutil
import subprocess
import sys
import tempfile


from dotenv import load_dotenv, dotenv_values
import typer
from rich import print


app = typer.Typer()

@app.command()
def update_pip() -> None:
    """
    Updates pip version

    Returns:
    None
    """
    subprocess.check_call([sys.executable, "-m", "pip", "install", "-U", "pip"])

@app.command()
def update_pageplus() -> None:
    """
    Updates PagePlus dependencies

    Returns:
    None
    """
    subprocess.check_call(["poetry", "update"])

@app.command()
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

@app.command()
def clean_temp() -> None:
    """
    Cleans all folders containing 'PagePlus' in their names within the specified temp folder.
    Which are no longer defined in the dot environment file.
    """
    load_dotenv()
    envs = dotenv_values()
    for pp_folder in Path(tempfile.gettempdir()).glob('*PagePlus_*'):
        if str(pp_folder) not in list(envs.values()):
            try:
                shutil.rmtree(pp_folder)
                print(f"Deleted folder: {pp_folder}")
            except Exception as e:
                print(f"Error deleting folder {pp_folder}: {e}")

@app.command()
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
