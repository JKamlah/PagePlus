import subprocess
import sys
from typing import List
from typing_extensions import Annotated

import typer
from rich.console import Console

app = typer.Typer()
console = Console()

EXTRAS = ["dinglehopper", "transkribus", "escriptorium"]


def install_package(package: str):
    """Installs a single extra package."""
    console.print(f"Installing {package}...")
    try:
        command = ["poetry", "run", "pageplus", package, "install"]
        # Using sys.executable to ensure we use the python from the correct venv
        # command = [sys.executable, "-m", "pageplus", package, "install"] # This seems wrong as pageplus is a typer app.
        subprocess.run(command, check=True, capture_output=True, text=True)
        console.print(f"[green]Successfully installed {package}[/green]")
    except subprocess.CalledProcessError as e:
        console.print(f"[red]Failed to install {package}.[/red]")
        console.print(f"Stderr: {e.stderr}")
        sys.exit(1)
    except FileNotFoundError:
        console.print(
            "[red]Error: 'poetry' command not found. Make sure Poetry is installed and in your PATH.[/red]"
        )
        sys.exit(1)


@app.command()
def main(
    packages: Annotated[
        List[str],
        typer.Argument(
            help=f"Extras to install. Can be 'all' or a selection from {EXTRAS}."
        ),
    ]
):
    """
    Installs optional extras for pageplus.
    """
    if "all" in packages:
        packages_to_install = EXTRAS
    else:
        packages_to_install = packages
        # Validate packages
        for pkg in packages_to_install:
            if pkg not in EXTRAS:
                console.print(
                    f"[red]Error: Unknown extra '{pkg}'. Available extras are: {EXTRAS}[/red]"
                )
                sys.exit(1)

    console.print(f"Packages to install: {packages_to_install}")

    for package in packages_to_install:
        install_package(package)

    console.print("\n[bold green]All selected extras installed successfully.[/bold green]")


if __name__ == "__main__":
    app()
