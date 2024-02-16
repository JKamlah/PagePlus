import typer
from rich import print

app = typer.Typer()


## TODO: Template for adding project specific methods

@app.command()
def project_x():
    """
    Just a template for your project
    """
    print("Hello [bold red]ProjectX[/bold red]! :boom:")


if __name__ == "__main__":
    app()
