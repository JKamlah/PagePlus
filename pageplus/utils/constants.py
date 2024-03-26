from __future__ import annotations
from enum import Enum


class WorkState(str, Enum):
    """
    State of the current data
    """
    ORIGINAL = "original"
    MODIFIED = "modified"


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
    GRADIO              = "Gradio"
    H2O                 = "H2O"
    CUSTOM              = "Custom"
    OPENAI              = "OpenAI"
    CUSTOM_OPENAI       = "Custom OpenAI"
    AZURE               = "Azure"
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
    OLLAMA              = "Ollama"
    PERPLEXITY          = "Perplexity"
    GROQ                = "Groq"
    VLLM                = "VLLM"
    XINFERENCE          = "Xinference"
    CLOUDFLARE          = "Cloudflare"
    DEEPINFRA           = "DeepInfra"
    AI21                = "AI21"
    NLP_CLOUD           = "NLP Cloud"
    REPLICATE           = "Replicate"
    COHERE              = "Cohere"
    TOGETHER_AI         = "Together AI"
    VOYAGE              = "Voyage"
    ALEPHALPHA          = "AlephAlpha"
    BASETEN             = "Baseten"
    OPENROUTER          = "OpenRouter"
    PETALS              = "Petals"

    def litellm_name(self):
        return f"{self.value.lower()}"


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
