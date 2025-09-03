import logging
import sys
import warnings
from pathlib import Path
from typing import Optional


def setup_logger(log_file: Optional[Path] = None) -> logging.Logger:
    """
    Set up the logger with the specified configuration.

    Args:
        log_file (Optional[Path]): Path to the log file. If None, logs will only go to console.
    Returns:
        logging.Logger: Configured logger instance
    """
    # Create logger
    logger = logging.getLogger('PagePlus')
    logger.setLevel(logging.INFO)

    # Create formatters
    file_formatter = logging.Formatter(
        '%(asctime)s - %(name)s - %(levelname)s - %(message)s')
    console_formatter = logging.Formatter('%(levelname)s: %(message)s')

    # Create console handler
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(logging.INFO)
    console_handler.setFormatter(console_formatter)
    logger.addHandler(console_handler)

    # Create file handler if log_file is provided
    if log_file:
        file_handler = logging.FileHandler(log_file)
        file_handler.setLevel(logging.DEBUG)
        file_handler.setFormatter(file_formatter)
        logger.addHandler(file_handler)

    return logger


def configure_external_logging() -> None:
    """
    Configure logging levels for external libraries to reduce noise in logs.
    """
    # Silence external library logs
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
    logging.getLogger(
        'watchdog.observers.inotify_buffer').setLevel(logging.INFO)
    logging.getLogger('watchdog.').setLevel(logging.WARNING)
    logging.getLogger(
        "streamlit.runtime.scriptrunner.script_runner").setLevel(logging.ERROR)

    # Filter warnings
    warnings.filterwarnings("ignore", category=UserWarning, module="pydantic")
