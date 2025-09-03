from pathlib import Path
from typing import List

import pandas as pd

from pageplus.gui.cli_bridges.base import CLIBridge, capture_logging, logger


class ValidationBridge(CLIBridge):
    """Bridge for validation functionality."""

    def validate_files(self, files: List[Path]) -> pd.DataFrame:
        """Validate processed files."""
        try:
            from pageplus.cli.validation import validate_all
            result = capture_logging(validate_all, files)
            return self._parse_validation_logs(result)
        except Exception as e:
            logger.error(f"Error validating files: {str(e)}")
            return pd.DataFrame()

    def _parse_validation_logs(self, log_text: str) -> pd.DataFrame:
        """Parse validation logs into a DataFrame."""
        import re
        rows = []

        current_file = None
        coords_re = re.compile(r'\[\((?:\d+, \d+)(?:\), \(\d+, \d+)*\)\]')

        # Patterns to detect types
        message_types = [
            (re.compile(r'validating file', re.IGNORECASE), "Validating File"),
            (re.compile(r'missing baseline', re.IGNORECASE), "Missing Baseline"),
            (re.compile(r'baseline.*just one point', re.IGNORECASE),
             "Single Point Baseline"),
            (re.compile(r'baseline.*outside.*textregion', re.IGNORECASE),
             "Baseline Outside Region"),
            (re.compile(r'some points.*outside.*textregion', re.IGNORECASE),
             "Partial Baseline Outside"),
            (re.compile(r'empty text', re.IGNORECASE), "Empty Text"),
            (re.compile(r'text is empty', re.IGNORECASE), "Empty Text"),
            (re.compile(r'no text', re.IGNORECASE), "Empty Region"),
            (re.compile(r'region contains no text', re.IGNORECASE), "Empty Region"),
            (re.compile(r'insufficient coord', re.IGNORECASE),
             "Insufficient Coordinates"),
            (re.compile(r'self-intersection', re.IGNORECASE),
             "Polygon Self-Intersection"),
            (re.compile(r'not valid.*region', re.IGNORECASE),
             "Invalid Region Polygon"),
            (re.compile(r'outside.*parent region', re.IGNORECASE),
             "Outside Parent Region"),
            (re.compile(r'error during validation', re.IGNORECASE),
             "Validation Error"),
        ]

        current_file = ""
        valid = False
        for line in log_text.strip().splitlines()[:-1]:
            if ":" not in line:
                continue

            parts = line.split(":", maxsplit=2)
            if len(parts) == 2:
                level, message = parts
                element = None
            else:
                level, element, message = parts

            message = message.strip()

            # Determine short message type
            short_description = "Info"
            for pattern, desc in message_types:
                if pattern.search(message):
                    short_description = desc
                    break

            # Valid file
            if valid and element == "Validating file":
                rows.append({
                    "Level": 'Info',
                    "Filename": current_file,
                    "Validation Type": '✅ Valid',
                    "Element ID": None,
                    "Coordinates": None,
                    "Message": None,
                })
            valid = False
            if element == "Validating file":
                current_file = message
                valid = True
                continue

            # Coordinates
            coords_match = coords_re.search(message)
            coords = None
            if coords_match:
                try:
                    coords = eval(coords_match.group())
                except Exception:
                    coords = None

            # Final message
            full_message = f"{message}"

            rows.append({
                "Level": level.strip(),
                "Filename": current_file,
                "Validation Type": short_description,
                "Element ID": element,
                "Coordinates": coords,
                "Message": full_message,
            })

        return pd.DataFrame(rows)
