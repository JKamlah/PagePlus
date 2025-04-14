from __future__ import annotations
from enum import Enum


class WorkState(str, Enum):
    """
    State of the current data
    """
    ORIGINAL = "original"
    MODIFIED = "modified"


class ProfileLevel(str, Enum):
    """
    Level of function profiling
    """
    stats = "stats"
    params = "params"
    results = "results"
    analytics = "analytics"
    summary = "summary"

class OutputFormats(str, Enum):
    """
    Level of function profiling
    """
    txt = "txt"
    page = "page"
    alto = "alto"
    json = "json"


class DrawingsPDF(str, Enum):
    """
    Level of function profiling
    """
    region = "region"
    line = "line"
    baseline = "baseline"
    word = "word"


class PagePlus(str, Enum):
    """
    Pageplus configuration
    """
    SYSTEM = "System"

    def as_prefix(self):
        return f"{self.name.upper()}_"

    def as_prefix_workspace_dir(self):
        return f"{self.name.upper()}_WS_DIR"


class Provider(str, Enum):
    pass


class LLMProvider(Provider):
    OPENAI              = "OpenAI"
    OLLAMA              = "Ollama"
    GROQ                = "Groq"
    AZURE               = "Azure"
    DEEPSEEK            = "Deepseek"
    MISTRAL_AZURE       = "Mistral Azure"
    VERTEX_AI           = "Vertex AI"
    PALM                = "PaLM"
    GEMINI              = "Gemini"
    MISTRAL             = "Mistral"
    ANTHROPIC           = "Anthropic"
    AWS_SAGEMAKER       = "Sagemaker"
    AWS_BEDROCK         = "Bedrock"
    ANYSCALE            = "Anyscale"
    HUGGINGFACE         = "Huggingface"


class Environments(str, Enum):
    """
    Service names are used as prefixes with _ for dotenvs variables
    """
    PAGEPLUS        = "PagePlus"
    #METS           = "METS"
    #IIIF           = "IIIF"
    ESCRIPTORIUM    = "eScriptorium"
    TRANSKRIBUS     = "Transkribus"
    DINGLEHOPPER    = "Dinglehopper"
    LLM             = "LLM"
    GEMINI          = "GEMINI"

    def as_prefix(self):
        return f"{self.name.upper()}_"

    def as_prefix_workspace(self):
        return f"{self.name.upper()}_WS_"

    def as_prefix_loaded_workspace(self):
        return f"{self.name.upper()}_LOADED_WS"

    def as_prefix_environment(self):
        return f"{self.name.upper()}_ENVIRONMENT"

    def as_prefix_workstate(self, state: WorkState):
        if state == "original":
            return f"{self.name.upper()}_ORIGINAL"
        else:
            return f"{self.name.upper()}_MODIFIED"


# Converts boolean values to on and off
Bool2OnOff = {True: "on", False: "off"}

MIME_IMAGE_EXTENSIONS = {
    'image/jpeg': '.jpg',
    'image/pjpeg': '.jpg',
    'image/png': '.png',
    'image/gif': '.gif',
    'image/webp': '.webp',
    'image/bmp': '.bmp',
    'image/x-windows-bmp': '.bmp',
    'image/x-icon': '.ico',
    'image/vnd.microsoft.icon': '.ico',
    'image/tiff': '.tiff',
    'image/x-tiff': '.tiff',
    'image/svg+xml': '.svg',
    'image/heic': '.heic',
    'image/heif': '.heif',
    'image/avif': '.avif',
    'image/vnd.adobe.photoshop': '.psd',
}
