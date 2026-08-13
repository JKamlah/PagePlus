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
    image_key: str = "image"
    prompt_key: str = "prompt"

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
        
        known_prefixes = {
            "openai", "azure", "anthropic", "mistral", "mistral_ocr", "gemini", "vertex_ai",
            "groq", "deepseek", "cohere", "ollama", "huggingface", "bedrock", "sagemaker", "curl"
        }
        has_prefix = False
        if "/" in chosen:
            first_part = chosen.split("/", 1)[0]
            if first_part in known_prefixes:
                has_prefix = True

        if has_prefix:
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
            if value and value.strip():
                return value.strip()
        except Exception:
            pass
        value = os.environ.get(name)
        if value:
            return value.strip()
        return None


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
        display_name="Mistral (Pixtral via LiteLLM)",
        litellm_prefix="mistral",
        env_api_key="MISTRAL_API_KEY",
        default_model="pixtral-large-latest",
        alt_models=("pixtral-12b-2409", "mistral-large-latest"),
    ),
    LiteLLMProviderPreset(
        id="mistral_ocr",
        display_name="Mistral Document OCR",
        litellm_prefix="mistral_ocr",
        env_api_key="MISTRAL_API_KEY",
        default_model="mistral-ocr-latest",
        alt_models=("mistral-ocr-2512", "mistral-ocr-4-0"),
        api_base_hint="https://api.mistral.ai/v1/ocr",
    ),
    LiteLLMProviderPreset(
        id="gemini",
        display_name="Google Gemini (via LiteLLM)",
        litellm_prefix="gemini",
        env_api_key="GEMINI_API_KEY",
        default_model="gemini-2.5-pro",
        alt_models=("gemini-3.5-flash", "gemini-2.5-flash", "gemini-1.5-pro", "gemini-1.5-flash"),
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
    LiteLLMProviderPreset(
        id="transformers",
        display_name="Local transformers (direct, scaffold)",
        litellm_prefix="transformers",
        env_api_key=None,
        default_model=None,
        api_base_hint="(in-process HuggingFace model id)",
        supports_json_schema=False,
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


def register_custom_endpoints() -> List[str]:
    """Load saved custom endpoints and register each as a provider preset.

    Returns the list of registered preset IDs (``custom_<name>``).  Already-
    registered custom presets are updated in place.

    Custom endpoints inject their credentials directly into ``os.environ``
    so that :meth:`LiteLLMProviderPreset.resolve_credentials` picks them up
    without needing ``.env`` entries.
    """
    from pageplus.utils.llm.endpoint_store import load_endpoints, normalize_base_url  # local to avoid circular

    registered: List[str] = []
    for ep in load_endpoints():
        preset_id = f"custom_{ep.name}"
        env_key_var = f"CUSTOM_{ep.name.upper()}_API_KEY"
        env_base_var = f"CUSTOM_{ep.name.upper()}_API_BASE"

        # Normalize the base URL per provider so legacy configs (e.g. a trailing
        # slash on an Ollama root that causes a 405) work without re-saving.
        base_url = normalize_base_url(ep.base_url, getattr(ep, "provider", "openai"))

        # Inject credentials into the process environment so the preset's
        # resolve_credentials() works without .env changes.
        os.environ[env_key_var] = ep.api_key or "EMPTY"
        os.environ[env_base_var] = base_url

        preset = LiteLLMProviderPreset(
            id=preset_id,
            display_name=f"Custom: {ep.name}",
            litellm_prefix=getattr(ep, "provider", "openai"),
            env_api_key=env_key_var,
            env_api_base=env_base_var,
            default_model=ep.default_model or None,
            alt_models=tuple(ep.alt_models) if ep.alt_models else (),
            requires_base_url=True,
            api_base_hint=base_url,
            supports_json_schema=False,
            image_key=getattr(ep, "image_key", "image") or "image",
            prompt_key=getattr(ep, "prompt_key", "prompt") or "prompt",
        )
        register_preset(preset)
        registered.append(preset_id)
    return registered


def unregister_custom_endpoint(name: str) -> None:
    """Remove a custom endpoint preset from the registry and clean up env vars."""
    preset_id = f"custom_{name}"
    _REGISTRY.pop(preset_id, None)
    env_key_var = f"CUSTOM_{name.upper()}_API_KEY"
    env_base_var = f"CUSTOM_{name.upper()}_API_BASE"
    os.environ.pop(env_key_var, None)
    os.environ.pop(env_base_var, None)


def spec_from_preset(
    preset_id: str,
    *,
    model: Optional[str] = None,
    task_mode: Optional[TaskMode] = None,
    timeout: Optional[float] = None,
    json_object_mode: Optional[bool] = None,
    calls_per_minute: int = 120,
    max_image_size: Optional[int] = 1000,
    is_batch: bool = False,
) -> OCRBackendSpec:
    """Build an :class:`OCRBackendSpec` for the given preset."""
    preset = get_preset(preset_id)

    if task_mode is not None and task_mode not in preset.task_modes:
        supported = ", ".join(tm.value for tm in preset.task_modes)
        raise ValueError(
            f"Provider preset '{preset.id}' ({preset.display_name}) does not support "
            f"task mode '{task_mode.value}'. Supported: {supported}"
        )

    api_key, api_base = preset.resolve_credentials()
    import logging
    logging.debug(
        "[registry] spec_from_preset resolved for %s (api_key set=%s, api_base set=%s)",
        preset_id, bool(api_key), bool(api_base),
    )

    # --- Transformers / HuggingFace backend -------------------------------
    if preset.litellm_prefix == "transformers" or preset_id == "transformers":
        from pageplus.utils.llm.core.specs import HuggingFaceOptions

        chosen_model = model or preset.default_model
        if not chosen_model:
            raise ValueError(
                f"Preset '{preset.id}' has no default model; pass a HuggingFace "
                f"model id via model=..."
            )
        return OCRBackendSpec(
            provider="transformers",
            model=chosen_model,
            options=HuggingFaceOptions(model_id=chosen_model),
            metadata={
                "preset_id": preset.id,
                "preset_display_name": preset.display_name,
                "preset_vision_capable": preset.vision_capable,
            },
        )

    # --- Curl REST backend (direct REST POST) -----------------------------
    if preset.litellm_prefix == "curl" or preset_id == "curl":
        from pageplus.utils.llm.core.specs import CurlHTTPOptions

        chosen_model = model or preset.default_model or "curl-default"
        url = api_base or preset.api_base_hint
        if not url:
            raise ValueError(f"Preset '{preset.id}' has no API base URL; pass api_base=...")
        options = CurlHTTPOptions(
            url=url,
            api_key=api_key,
            timeout=timeout if timeout is not None else 60.0,
            calls_per_minute=calls_per_minute,
            max_image_size=max_image_size,
        )
        return OCRBackendSpec(
            provider="curl",
            model=chosen_model,
            options=options,
            metadata={
                "preset_id": preset.id,
                "preset_display_name": preset.display_name,
                "preset_vision_capable": preset.vision_capable,
            },
        )

    # --- Mistral OCR backend (direct Document AI API) ---------------------
    if preset.litellm_prefix == "mistral_ocr" or preset_id == "mistral_ocr":
        from pageplus.utils.llm.core.specs import MistralOptions

        chosen_model = model or preset.default_model or "mistral-ocr-latest"
        options = MistralOptions(
            api_key=api_key,
            api_base_url=api_base or preset.api_base_hint or "https://api.mistral.ai/v1/ocr",
            model=chosen_model,
            table_format="html",
            include_blocks=True,
            timeout=timeout if timeout is not None else 60.0,
            calls_per_minute=calls_per_minute,
            max_image_size=max_image_size,
        )
        return OCRBackendSpec(
            provider="mistral_ocr",
            model=chosen_model,
            options=options,
            metadata={
                "preset_id": preset.id,
                "preset_display_name": preset.display_name,
                "preset_vision_capable": preset.vision_capable,
            },
        )

    # --- Native Gemini SDK backend (google-genai) ------------------------
    if preset.litellm_prefix == "gemini" or preset_id == "gemini":
        from pageplus.utils.llm.core.specs import GeminiOptions, GeminiBatchOptions

        chosen_model = model or preset.default_model or "gemini-2.5-flash"
        if "/" in chosen_model:
            chosen_model = chosen_model.split("/", 1)[1]

        if is_batch:
            options = GeminiBatchOptions(
                api_key=api_key,
                calls_per_minute=calls_per_minute if calls_per_minute != 120 else 60,
                service_tier="auto",
            )
        else:
            options = GeminiOptions(
                api_key=api_key,
                calls_per_minute=calls_per_minute,
                timeout=timeout if timeout is not None else 300.0,
                service_tier="auto",
            )
        return OCRBackendSpec(
            provider="gemini",
            model=chosen_model,
            options=options,
            metadata={
                "preset_id": preset.id,
                "preset_display_name": preset.display_name,
                "preset_vision_capable": preset.vision_capable,
            },
        )

    # --- Custom endpoints → direct OpenAI library or LiteLLM --------------
    if preset_id.startswith("custom_"):
        if preset.litellm_prefix == "openai":
            from pageplus.utils.llm.core.specs import OpenAICompatibleOptions

            # For the direct OpenAI backend, the model name is sent as-is to the
            # server (no litellm prefix).  Use the caller's override, the preset
            # default, or raise if neither is set.
            chosen_model = model or preset.default_model
            if not chosen_model:
                raise ValueError(
                    f"Preset '{preset.id}' has no default model; pass model=..."
                )

            options = OpenAICompatibleOptions(
                api_base_url=api_base or preset.api_base_hint or "http://localhost:8000/v1",
                api_key=api_key,
                timeout=timeout if timeout is not None else 60.0,
                max_image_size=max_image_size,
            )
            return OCRBackendSpec(
                provider="openai_direct",
                model=chosen_model,
                options=options,
                metadata={
                    "preset_id": preset.id,
                    "preset_display_name": preset.display_name,
                    "preset_vision_capable": preset.vision_capable,
                },
            )
        else:
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
                max_image_size=max_image_size,
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

    # --- Built-in presets → LiteLLM ---------------------------------------
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
        max_image_size=max_image_size,
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

