import re
import subprocess
import sys
from collections import Counter
from importlib import util
from pathlib import Path
from typing import List, Annotated

import typer
from rich import print
from dotenv import load_dotenv, dotenv_values, set_key

from pageplus.io.logger import logging
from pageplus.models.page import Page
from pageplus.utils.constants import ProfileLevel, ImageExtension
from pageplus.utils.fs import collect_xml_files, find_image
from pageplus.utils.fs import transform_inputs
from pageplus.utils.image import get_image, crop_image_by_polygon
from pageplus.utils.profile import profile, ProfileFnRet
from pageplus.utils.envs import get_env_path

app = typer.Typer(
    no_args_is_help=True,
)


@app.callback()
def callback():
    load_dotenv(dotenv_path=get_env_path())
    envs = dotenv_values(dotenv_path=get_env_path())
    if envs.get("PAGEPLUS_OCR_TESSERACT") == "True":
        try:
            import pytesseract
            from pageplus.cli.dinglehopper import get_metrics, summarize_metrics
        except ImportError:
            print("Tesseract OCR is not activated. Please activate it first.")
            set_key(get_env_path(), 'PAGEPLUS_OCR_TESSERACT', 'False')


@app.command(rich_help_panel="Tesseract")
def install() -> None:
    """Install tesserocr"""
    try:
        import subprocess
        import sys
        subprocess.check_call(
            [sys.executable, "-m", "pip", "install", "tesserocr"])
        set_key(get_env_path(), 'PAGEPLUS_OCR_TESSERACT', 'True')
        print("tesserocr has been installed.")
    except:
        print("Could not install tesserocr.")
        print("Please install it manually.")
        set_key(get_env_path(), 'PAGEPLUS_OCR_TESSERACT', 'False')


@app.command(rich_help_panel="Tesseract")
def uninstall() -> None:
    """Uninstall tesserocr"""
    try:
        import subprocess
        import sys
        subprocess.check_call(
            [sys.executable, "-m", "pip", "uninstall", "-y", "tesserocr"])
        set_key(get_env_path(), 'PAGEPLUS_OCR_TESSERACT', 'False')
        print("tesserocr has been uninstalled.")
    except:
        print("Could not uninstall tesserocr.")
        print("Please uninstall it manually.")


if __name__ == "__main__":
    app()
