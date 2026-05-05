"""Registry of LiteLLM provider presets (a.k.a. "provider templates").

LiteLLM lets PagePlus talk to dozens of upstream LLM providers using a single
client. Each provider, however, needs a slightly different prefix, environment
variable, base URL, and preferred vision-capable model. This registry encodes
those per-provider defaults as :class:`LiteLLMProviderPreset` entries so that
CLI / GUI code can:

- list every preset that is configured on the current machine
  (``available_providers`` / ``list_providers``),
- build an :class:`OCRBackendSpec` for any preset without each caller having
  to know provider-specific details (``spec_from_preset``),
- pick a sensible vision-capable default model for each preset.

The registry intentionally stays *declarative*. Adding a new provider is a
matter of appending one more :class:`LiteLLMProviderPreset`, no code changes
elsewhere.

Env-var lookup order (first match wins):
    1. ``pageplus.gui.utils.settings.Settings`` (which reads ``.env``)
    2. ``os.environ``

All presets serve the full set of PAGE-XML-aware :class:`TaskMode` s out of
the box because ``TaskMode`` only influences the template layer, not the
transport.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

from pageplus.utils.llm.core.specs import (
    LiteLLMTransportConfig,
    OCRBackendSpec,
    TaskMode,
)


@dataclass(frozen=True)
class LiteLLMProviderPreset:
    """Declarative description of a LiteLLM-routable provider.

    :param id: stable short identifier (``"openai"``, ``"azure_openai"``, ...).
    :param display_name: human-readable label shown in CLIs/GUIs.
    :param litellm_prefix: prefix prepended to ``model`` when calling
        ``litellm.completion`` (``"openai"``, ``"azure"``, ``"anthropic"`` ...).
    :param env_api_key: environment variable (or ``.env`` key) holding the API key.
    :param env_api_base: optional env var for the custom API base URL.
    :param default_model: vision-capable model used as a sensible default.
    :param alt_models: extra suggested model names to surface in UIs.
    :param api_base_hint: informational hint for the expected base URL.
    :param requires_base_url: when ``True``, a base URL is mandatory (Ollama, Azure).
    :param vision_capable: whether this provider can run image-conditioned OCR.
    :param supports_json_schema: whether the provider honours
        ``response_format={"type": "json_schema"}``; if ``False`` we fall back
        to ``response_format={"type": "json_object"}``.
    :param task_modes: which :class:`TaskMode` s make sense on this provider.
        Default is the full set for vision-capable providers and the
        text-only subset otherwise.
    """

    id: str
    display_name: str
    litellm_prefix: str
    env_api_key: Optional[str] = None
    env_api_base: Optional[str] = None
    default_model: Optional[str] = None
    alt_models: Tuple[str, ...] = ()
    api_base_hint: Optional[str] = None
    requires_base_url: bool = False
    vision_capable: bool = True
    supports_json_schema: bool = True
    task_modes: Tuple[TaskMode, ...] = field(default_factory=lambda: tuple(TaskMode))

    # ------------------------------------------------------------------

    def is_configured(self) -> bool:
        """Return ``True`` if the environment holds the credentials this preset needs."""
        if self.env_api_key is None and not self.requires_base_url:
            # Providers like ``ollama`` / ``openai_compatible`` may work without
            # an API key -- we then consider them configured as long as the
            # base URL is present.
            return bool(self._get_env(self.env_api_base)) if self.env_api_base else True
        api_key = self._get_env(self.env_api_key) if self.env_api_key else None
        api_base = self._get_env(self.env_api_base) if self.env_api_base else None
        if self.requires_base_url and not api_base:
            return False
        if self.env_api_key and not api_key:
            return False
        return True

    def resolve_credentials(self) -> Tuple[Optional[str], Optional[str]]:
        """Return ``(api_key, api_base_url)`` resolved from env/.env."""
        api_key = self._get_env(self.env_api_key) if self.env_api_key else None
        api_base = self._get_env(self.env_api_base) if self.env_api_base else None
        return api_key, api_base

    def model_string(self, model: Optional[str] = None) -> str:
        """Return the ``<prefix>/<model>`` identifier LiteLLM expects."""
        chosen = model or self.default_model
        if not chosen:
            raise ValueError(f"Preset '{self.id}' has no default model; pass model=...")
        if "/" in chosen:
            # Caller already prefixed it; trust them.
            return chosen
        return f"{self.litellm_prefix}/{chosen}"

    @staticmethod
    def _get_env(name: Optional[str]) -> Optional[str]:
        if not name:
            return None
        # Prefer PagePlus-managed .env via Settings so CLI ``set-api-key`` writes
        # are picked up without reloading the process.
        try:
            from pageplus.gui.utils.settings import Settings  # local import to avoid GUI dep at import time
            value = Settings().get(name)
            if value:
                return value
        except Exception:
            pass
        value = os.environ.get(name)
        return value or None


# ---------------------------------------------------------------------------
# Built-in presets
# ---------------------------------------------------------------------------


_BUILTINS: Tuple[LiteLLMProviderPreset, ...] = (
    LiteLLMProviderPreset(
        id="openai",
        display_name="OpenAI",
        litellm_prefix="openai",
        env_api_key="OPENAI_API_KEY",
        default_model="gpt-4o",
        alt_models=("gpt-4o-mini", "gpt-4.1", "gpt-4.1-mini", "o4-mini"),
        api_base_hint="https://api.openai.com/v1",
    ),
    LiteLLMProviderPreset(
        id="azure_openai",
        display_name="Azure OpenAI",
        litellm_prefix="azure",
        env_api_key="AZURE_API_KEY",
        env_api_base="AZURE_API_BASE",
        default_model="gpt-4o",
        alt_models=("gpt-4o-mini", "gpt-4.1"),
        requires_base_url=True,
    ),
    LiteLLMProviderPreset(
        id="anthropic",
        display_name="Anthropic Claude",
        litellm_prefix="anthropic",
        env_api_key="ANTHROPIC_API_KEY",
        default_model="claude-sonnet-4-5-20250929",
        alt_models=(
            "claude-3-7-sonnet-20250219",
            "claude-3-5-sonnet-20241022",
            "claude-3-5-haiku-20241022",
        ),
    ),
    LiteLLMProviderPreset(
        id="mistral",
        display_name="Mistral",
        litellm_prefix="mistral",
        env_api_key="MISTRAL_API_KEY",
        default_model="pixtral-large-latest",
        alt_models=("pixtral-12b-2409", "mistral-large-latest"),
    ),
    LiteLLMProviderPreset(
        id="gemini",
        display_name="Google Gemini (via LiteLLM)",
        litellm_prefix="gemini",
        env_api_key="GEMINI_API_KEY",
        default_model="gemini-2.5-pro",
        alt_models=("gemini-2.5-flash", "gemini-1.5-pro", "gemini-1.5-flash"),
    ),
    LiteLLMProviderPreset(
        id="vertex_ai",
        display_name="Google Vertex AI",
        litellm_prefix="vertex_ai",
        env_api_key="GOOGLE_APPLICATION_CREDENTIALS",
        default_model="gemini-2.5-pro",
        alt_models=("gemini-2.5-flash",),
    ),
    LiteLLMProviderPreset(
        id="groq",
        display_name="Groq",
        litellm_prefix="groq",
        env_api_key="GROQ_API_KEY",
        default_model="llama-3.2-90b-vision-preview",
        alt_models=("llama-3.2-11b-vision-preview",),
    ),
    LiteLLMProviderPreset(
        id="deepseek",
        display_name="DeepSeek",
        litellm_prefix="deepseek",
        env_api_key="DEEPSEEK_API_KEY",
        default_model="deepseek-chat",
        alt_models=("deepseek-reasoner",),
        vision_capable=False,
        task_modes=(TaskMode.TEXT_ONLY, TaskMode.TEXT_CORRECTION),
    ),
    LiteLLMProviderPreset(
        id="cohere",
        display_name="Cohere",
        litellm_prefix="cohere",
        env_api_key="COHERE_API_KEY",
        default_model="command-r-plus",
        vision_capable=False,
        task_modes=(TaskMode.TEXT_ONLY, TaskMode.TEXT_CORRECTION),
    ),
    LiteLLMProviderPreset(
        id="ollama",
        display_name="Ollama (local)",
        litellm_prefix="ollama",
        env_api_base="OLLAMA_API_BASE",
        default_model="llama3.2-vision",
        alt_models=("llava", "minicpm-v"),
        requires_base_url=True,
        api_base_hint="http://localhost:11434",
        supports_json_schema=False,
    ),
    LiteLLMProviderPreset(
        id="openai_compatible",
        display_name="OpenAI-compatible server (vLLM, TGI, LM Studio, ...)",
        litellm_prefix="openai",
        env_api_key="OPENAI_COMPATIBLE_API_KEY",
        env_api_base="OPENAI_COMPATIBLE_API_BASE",
        default_model=None,
        requires_base_url=True,
        api_base_hint="http://localhost:8000/v1",
    ),
    LiteLLMProviderPreset(
        id="huggingface",
        display_name="Hugging Face Inference API",
        litellm_prefix="huggingface",
        env_api_key="HF_TOKEN",
        default_model="meta-llama/Meta-Llama-3.1-8B-Instruct",
        alt_models=("HuggingFaceM4/idefics2-8b",),
    ),
    LiteLLMProviderPreset(
        id="bedrock",
        display_name="AWS Bedrock",
        litellm_prefix="bedrock",
        env_api_key="AWS_ACCESS_KEY_ID",
        default_model="anthropic.claude-3-5-sonnet-20241022-v2:0",
    ),
    LiteLLMProviderPreset(
        id="sagemaker",
        display_name="AWS SageMaker",
        litellm_prefix="sagemaker",
        env_api_key="AWS_ACCESS_KEY_ID",
        default_model=None,
    ),
)


_REGISTRY: Dict[str, LiteLLMProviderPreset] = {p.id: p for p in _BUILTINS}


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def register_preset(preset: LiteLLMProviderPreset) -> None:
    """Add or override a preset in the registry."""
    _REGISTRY[preset.id] = preset


def get_preset(preset_id: str) -> LiteLLMProviderPreset:
    try:
        return _REGISTRY[preset_id]
    except KeyError:
        raise KeyError(
            f"Unknown LiteLLM provider preset '{preset_id}'. "
            f"Known: {sorted(_REGISTRY)}"
        )


def list_providers() -> List[LiteLLMProviderPreset]:
    """Return every registered preset, regardless of configuration status."""
    return list(_REGISTRY.values())


def available_providers() -> List[LiteLLMProviderPreset]:
    """Return every preset whose required credentials are present in the env."""
    return [p for p in _REGISTRY.values() if p.is_configured()]


def spec_from_preset(
    preset_id: str,
    *,
    model: Optional[str] = None,
    task_mode: Optional[TaskMode] = None,
    timeout: Optional[float] = None,
    json_object_mode: Optional[bool] = None,
    calls_per_minute: int = 120,
) -> OCRBackendSpec:
    """Build an :class:`OCRBackendSpec` for the given preset.

    The preset supplies provider prefix, API key, base URL, and a default model
    (overridable via ``model``). If ``task_mode`` is provided, we validate it
    against the preset's ``task_modes`` so the CLI fails fast when a user asks,
    e.g., a text-only provider for ``layout_and_text``.
    """
    preset = get_preset(preset_id)

    if task_mode is not None and task_mode not in preset.task_modes:
        supported = ", ".join(tm.value for tm in preset.task_modes)
        raise ValueError(
            f"Provider preset '{preset.id}' ({preset.display_name}) does not support "
            f"task mode '{task_mode.value}'. Supported: {supported}"
        )

    api_key, api_base = preset.resolve_credentials()
    resolved_json_object_mode = (
        json_object_mode if json_object_mode is not None else not preset.supports_json_schema
    )

    transport = LiteLLMTransportConfig(
        api_base_url=api_base,
        api_key=api_key,
        timeout=timeout if timeout is not None else 60.0,
        provider_prefix=preset.litellm_prefix,
        calls_per_minute=calls_per_minute,
        json_object_mode=resolved_json_object_mode,
    )

    return OCRBackendSpec(
        provider="litellm",
        model=preset.model_string(model),
        options=transport,
        metadata={
            "preset_id": preset.id,
            "preset_display_name": preset.display_name,
            "preset_vision_capable": preset.vision_capable,
        },
    )
