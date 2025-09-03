import contextlib
import io
import logging
import tempfile
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)


def capture_output(func, *args, **kwargs):
    """Capture stdout from a function call."""
    buffer = io.StringIO()
    with contextlib.redirect_stdout(buffer):
        func(*args, **kwargs)
    return buffer.getvalue()


def capture_logging(func, *args, **kwargs):
    """Capture both stdout and logging output from a function call."""
    buffer = io.StringIO()

    # Capture stdout and stderr
    with contextlib.redirect_stdout(buffer):
        # Capture logging
        logger = logging.getLogger()
        handler = logging.StreamHandler(buffer)
        formatter = logging.Formatter('%(levelname)s:%(message)s')
        handler.setFormatter(formatter)
        logger.addHandler(handler)

        try:
            func(*args, **kwargs)
        finally:
            logger.removeHandler(handler)

    return buffer.getvalue()


class CLIBridge:
    """Base bridge between GUI and CLI functionality."""

    def __init__(self, output_dir: Optional[Path] = None):
        self.output_dir = output_dir or Path(tempfile.mkdtemp())
        self.output_dir.mkdir(parents=True, exist_ok=True)
