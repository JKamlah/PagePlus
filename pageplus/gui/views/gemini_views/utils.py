from pageplus.utils.constants import GUI_STORAGE_DIR
import json

def get_available_models():
    """Get available Gemini models from cached JSON file."""
    models_file = GUI_STORAGE_DIR / "gemini_models.json"

    # Try to load from file
    if models_file.exists():
        try:
            with open(models_file, 'r', encoding='utf-8') as f:
                data = json.load(f)
                return data.get('models', [])
        except (json.JSONDecodeError, IOError):
            pass

    # Return empty list if file doesn't exist or can't be read
    return []






