from pathlib import Path
from typing import Any, Dict

from dotenv import dotenv_values, set_key
from pageplus.utils.constants import ENV_FILE


class Settings:
    """Handle application settings persistence using .env file."""

    def __init__(self):
        self.env_file = ENV_FILE
        self._ensure_env_file()
        self.settings = self._load_settings()

    def _ensure_env_file(self) -> None:
        """Ensure .env file exists with default values."""
        if not self.env_file.exists():
            default_settings = {
                "OUTPUT_DIRECTORY": str(Path.home() / "pageplus_output"),
                "DEFAULT_OCR_MODEL": "Tesseract",
                "DEFAULT_LANGUAGE": "English",
                "LLM_API_KEY": "",
                "GEMINI_API_KEY": "",
                "USE_BBOX_FALLBACK": "True"  # Use previous bbox with offset for entries without bbox
            }
            for key, value in default_settings.items():
                self.set(key, value)

    def _load_settings(self) -> None:
        """Load settings from .env file."""
        return dotenv_values(self.env_file)

    def _convert_key(self, key: str) -> str:
        """Convert key to UPPER_SNAKE_CASE if it's not already."""
        if key.isupper() and '_' in key:
            return key
        return ''.join(
            ['_' + c.upper() if c.isupper() else c.upper() for c in key]
        ).lstrip('_')

    def get(self, key: str, default: Any = None) -> str:
        """Get a setting value."""
        env_key = self._convert_key(key)
        return self.settings.get(env_key, default)

    def set(self, key: str, value: Any) -> None:
        """Set a setting value and save."""
        env_key = self._convert_key(key)
        # Convert value to string, handling None and other types
        str_value = str(value) if value is not None else ""
        set_key(self.env_file, env_key, str_value)
        self.settings = self._load_settings()  # Reload environment

    def update(self, settings: Dict[str, str]) -> None:
        """Update multiple settings at once and save."""
        for key, value in settings.items():
            self.set(key, value)
