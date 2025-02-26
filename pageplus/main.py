from logging import DEBUG

import typer
import logging
import warnings


# Silence!
logging.getLogger("requests").setLevel(logging.WARNING)
logging.getLogger("urllib3").setLevel(logging.WARNING)
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("LiteLLM").setLevel(logging.WARNING)
logging.getLogger("httpcore").setLevel(logging.WARNING)
logging.getLogger("openai._base_client").setLevel(logging.WARNING)
logging.getLogger("websockets").setLevel(logging.WARNING)
logging.getLogger("asyncio").setLevel(logging.WARNING)
logging.getLogger("kraken").setLevel(logging.WARNING)
logging.getLogger("pytesseract").setLevel(logging.WARNING)
logging.getLogger("PIL").setLevel(logging.WARNING)
logging.getLogger("pikepdf").setLevel(logging.WARNING)
warnings.filterwarnings("ignore", category=UserWarning, module="pydantic")



from pageplus.cli import (system, analytics, validation, modification, export, workspace, projects,
                          dinglehopper, llm, ocr_kraken, ocr_tesseract, escriptorium, transkribus)

app = typer.Typer()
app.add_typer(system.app, name="system", rich_help_panel="System")
app.add_typer(escriptorium.app, name="escriptorium", rich_help_panel="Transcription-Platform")
app.add_typer(transkribus.app, name="transkribus", rich_help_panel="Transcription-Platform")
app.add_typer(dinglehopper.app, name="dinglehopper", rich_help_panel="PagePlus - external tools")
app.add_typer(llm.app, name="llm", rich_help_panel="PagePlus - external tools")
app.add_typer(ocr_kraken.app, name="kraken", rich_help_panel="Kraken - external tools")
app.add_typer(ocr_tesseract.app, name="tesseract", rich_help_panel="Tesseract - external tools")
app.add_typer(analytics.app, name="analytics", rich_help_panel="PagePlus")
app.add_typer(validation.app, name="validation", rich_help_panel="PagePlus")
app.add_typer(modification.app, name="modification", rich_help_panel="PagePlus")
app.add_typer(workspace.app, name="workspace", rich_help_panel="PagePlus")
app.add_typer(export.app, name="export", rich_help_panel="PagePlus")
app.add_typer(projects.app, name="projects", rich_help_panel="PagePlus - projects")

if __name__ == "__main__":
    app()
