import os
from pathlib import Path
from typing import Dict, Any
from dotenv import load_dotenv, set_key


class Settings:
    """Handle application settings persistence using .env file."""
    
    def __init__(self):
        self.config_dir = Path.home() / ".pageplus"
        self.env_file = self.config_dir / ".env"
        self._ensure_env_file()
        self._load_settings()
    
    def _ensure_env_file(self) -> None:
        """Ensure .env file exists with default values."""
        self.config_dir.mkdir(parents=True, exist_ok=True)
        if not self.env_file.exists():
            default_settings = {
                "OUTPUT_DIRECTORY": str(Path.home() / "pageplus_output"),
                "DEFAULT_OCR_MODEL": "Tesseract",
                "DEFAULT_LANGUAGE": "English",
                "LLM_API_KEY": "",
                "GEMINI_API_KEY": ""
            }
            for key, value in default_settings.items():
                self.set(key, value)
    
    def _load_settings(self) -> None:
        """Load settings from .env file."""
        load_dotenv(self.env_file)
    
    def get(self, key: str, default: Any = None) -> str:
        """Get a setting value."""
        # Convert from camelCase to UPPER_SNAKE_CASE
        env_key = ''.join(
            ['_' + c.upper() if c.isupper() else c.upper() for c in key]
        ).lstrip('_')
        return os.getenv(env_key, default)
    
    def set(self, key: str, value: str) -> None:
        """Set a setting value and save."""
        # Convert from camelCase to UPPER_SNAKE_CASE
        env_key = ''.join(
            ['_' + c.upper() if c.isupper() else c.upper() for c in key]
        ).lstrip('_')
        set_key(self.env_file, env_key, value)
        self._load_settings()  # Reload environment
    
    def update(self, settings: Dict[str, str]) -> None:
        """Update multiple settings at once and save."""
        for key, value in settings.items():
            self.set(key, value) 