from pageplus.cli import (
    litellm,
    system,
    analytics,
    validation,
    modification,
    ingest,
    export,
    workspace,
    projects,
    dinglehopper,
    gemini,
    mets,
    ocr_kraken,
    ocr_tesseract,
    escriptorium,
    transkribus)
import typer
from pageplus.utils.logger import configure_external_logging

# Configure external logging
configure_external_logging()


# Create Typer app
app = typer.Typer()
app.add_typer(system.app, name="system", rich_help_panel="System")
app.add_typer(escriptorium.app, name="escriptorium",
              rich_help_panel="Transcription-Platform")
app.add_typer(transkribus.app, name="transkribus",
              rich_help_panel="Transcription-Platform")
app.add_typer(dinglehopper.app, name="dinglehopper",
              rich_help_panel="PagePlus - external tools")
app.add_typer(
    litellm.app,
    name="litellm",
    rich_help_panel="PagePlus - external tools")
app.add_typer(
    gemini.app,
    name="gemini",
    rich_help_panel="PagePlus - external tools")
app.add_typer(
    ocr_kraken.app,
    name="kraken",
    rich_help_panel="Kraken - external tools")
app.add_typer(ocr_tesseract.app, name="tesseract",
              rich_help_panel="Tesseract - external tools")
app.add_typer(analytics.app, name="analytics", rich_help_panel="PagePlus")
app.add_typer(validation.app, name="validation", rich_help_panel="PagePlus")
# app.add_typer(visualize.app, name="visualize", rich_help_panel="PagePlus")
app.add_typer(
    modification.app,
    name="modification",
    rich_help_panel="PagePlus")
app.add_typer(mets.app, name="mets", rich_help_panel="PagePlus")
app.add_typer(workspace.app, name="workspace", rich_help_panel="PagePlus")
app.add_typer(ingest.app, name="ingest", rich_help_panel="PagePlus")
app.add_typer(export.app, name="export", rich_help_panel="PagePlus")
app.add_typer(
    projects.app,
    name="projects",
    rich_help_panel="PagePlus - projects")

if __name__ == "__main__":
    app()
