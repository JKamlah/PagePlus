import typer

from pageplus.cli import system, analytics, validation, modification, export, escriptorium, transkribus, workspace, projects

app = typer.Typer()
app.add_typer(system.app, name="system", rich_help_panel="System")
app.add_typer(escriptorium.app, name="escriptorium", rich_help_panel="Transcription-Platform")
app.add_typer(transkribus.app, name="transkribus", rich_help_panel="Transcription-Platform")
app.add_typer(analytics.app, name="analytics", rich_help_panel="PagePlus")
app.add_typer(validation.app, name="validation", rich_help_panel="PagePlus")
app.add_typer(modification.app, name="modification", rich_help_panel="PagePlus")
app.add_typer(projects.app, name="projects", rich_help_panel="PagePlus")
app.add_typer(workspace.app, name="workspace", rich_help_panel="PagePlus")
app.add_typer(export.app, name="export", rich_help_panel="PagePlus")

if __name__ == "__main__":
    app()
