import io
import contextlib
import logging

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