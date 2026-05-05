"""Registry of :class:`OCRModelProfile` s.

A profile encodes "for task mode X on provider Y (optionally with model Z),
render template T, expect JSON schema S, and postprocess with function F".

Profiles are resolved in priority order:
    1. exact ``(provider, model, task_mode)`` match
    2. ``(provider, "*", task_mode)`` match (provider default for that task)
    3. ``("*", "*", task_mode)`` match (global fallback)

If no profile matches, :func:`resolve_profile` raises
:class:`ConfigurationError` with a list of task modes the provider supports.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Iterable, List, Tuple

from pageplus.utils.llm.core.errors import ConfigurationError
from pageplus.utils.llm.core.specs import OCRModelProfile, TaskMode


ProfileKey = Tuple[str, str, TaskMode]  # (provider, model, task_mode); "*" = wildcard


_REGISTRY: Dict[ProfileKey, OCRModelProfile] = {}


def register_profile(
    profile: OCRModelProfile,
    *,
    provider: str = "*",
    model: str = "*",
) -> None:
    key: ProfileKey = (provider.lower(), model, profile.task_mode)
    _REGISTRY[key] = profile


def get_profile(provider: str, model: str, task_mode: TaskMode) -> OCRModelProfile | None:
    for key in _candidate_keys(provider, model, task_mode):
        prof = _REGISTRY.get(key)
        if prof is not None:
            return prof
    return None


def resolve_profile(provider: str, model: str, task_mode: TaskMode) -> OCRModelProfile:
    prof = get_profile(provider, model, task_mode)
    if prof is None:
        modes = sorted({key[2].value for key in _REGISTRY if key[0] in (provider.lower(), "*")})
        raise ConfigurationError(
            f"No profile registered for provider='{provider}', model='{model}', task_mode='{task_mode.value}'. "
            f"Supported task modes for this provider (or globally): {modes}",
            provider=provider, model=model,
        )
    return prof


def supported_task_modes(provider: str | None = None) -> List[TaskMode]:
    if provider is None:
        return sorted({k[2] for k in _REGISTRY}, key=lambda m: m.value)
    prov = provider.lower()
    return sorted({k[2] for k in _REGISTRY if k[0] in (prov, "*")}, key=lambda m: m.value)


def _candidate_keys(provider: str, model: str, task_mode: TaskMode) -> Iterable[ProfileKey]:
    prov = provider.lower()
    yield (prov, model, task_mode)
    yield (prov, "*", task_mode)
    yield ("*", "*", task_mode)


# ---------------------------------------------------------------------------
# JSON schemas (reused by multiple profiles).
# ---------------------------------------------------------------------------

_COORDS_POINTS_STRING = {"type": "string"}

_LINE_LAYOUT_ITEM = {
    "type": "object",
    "properties": {
        "id": {"type": "string"},
        "coords": _COORDS_POINTS_STRING,
        "baseline": _COORDS_POINTS_STRING,
    },
    "required": ["id", "coords"],
    "additionalProperties": True,
}

_REGION_LAYOUT_ITEM = {
    "type": "object",
    "properties": {
        "id": {"type": "string"},
        "type": {"type": "string"},
        "coords": _COORDS_POINTS_STRING,
        "textlines": {"type": "array", "items": _LINE_LAYOUT_ITEM},
    },
    "required": ["id", "coords"],
    "additionalProperties": True,
}

LAYOUT_ONLY_SCHEMA = {
    "type": "object",
    "properties": {
        "regions": {"type": "array", "items": _REGION_LAYOUT_ITEM},
    },
    "required": ["regions"],
    "additionalProperties": False,
}

_LAYOUT_AND_TEXT_ITEM = {
    "type": "object",
    "properties": {
        "box_2d": {"type": "array", "items": {"type": "integer"}, "minItems": 4, "maxItems": 4},
        "text_content": {"type": "string"},
        "region": {"type": "integer"},
        "type": {"type": "string"},
    },
    "required": ["box_2d", "text_content"],
    "additionalProperties": True,
}

LAYOUT_AND_TEXT_SCHEMA = {
    "type": "array",
    "items": _LAYOUT_AND_TEXT_ITEM,
}

_TEXT_REGION_ITEM = {
    "type": "object",
    "properties": {
        "id": {"type": "string"},
        "type": {"type": "string"},
        "textlines": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "id": {"type": "string"},
                    "text_content": {"type": "string"},
                    "type": {"type": "string"},
                },
                "required": ["id", "text_content"],
                "additionalProperties": True,
            },
        },
    },
    "required": ["id", "textlines"],
    "additionalProperties": True,
}

TEXT_ONLY_SCHEMA = {
    "type": "object",
    "properties": {
        "regions": {"type": "array", "items": _TEXT_REGION_ITEM},
    },
    "required": ["regions"],
    "additionalProperties": False,
}

TEXT_CORRECTION_SCHEMA = TEXT_ONLY_SCHEMA

LAYOUT_CORRECTION_SCHEMA = LAYOUT_ONLY_SCHEMA


# ---------------------------------------------------------------------------
# Built-in profiles.
# ---------------------------------------------------------------------------

# Generic/default profiles -- work on any provider that can follow the template.
_BUILTINS = [
    OCRModelProfile(
        name="default_layout_only",
        task_mode=TaskMode.LAYOUT_ONLY,
        template="layout_only",
        postprocess="layout_only_to_xml",
        schema=LAYOUT_ONLY_SCHEMA,
    ),
    OCRModelProfile(
        name="default_layout_and_text",
        task_mode=TaskMode.LAYOUT_AND_TEXT,
        template="layout_and_text",
        postprocess="layout_and_text_to_xml",
        schema=LAYOUT_AND_TEXT_SCHEMA,
    ),
    OCRModelProfile(
        name="default_layout_correction",
        task_mode=TaskMode.LAYOUT_CORRECTION,
        template="layout_correction",
        postprocess="layout_correction_apply",
        schema=LAYOUT_CORRECTION_SCHEMA,
    ),
    OCRModelProfile(
        name="default_text_only",
        task_mode=TaskMode.TEXT_ONLY,
        template="text_only",
        postprocess="text_only_apply",
        schema=TEXT_ONLY_SCHEMA,
    ),
    OCRModelProfile(
        name="default_text_correction",
        task_mode=TaskMode.TEXT_CORRECTION,
        template="text_correction",
        postprocess="text_correction_apply",
        schema=TEXT_CORRECTION_SCHEMA,
    ),
]


for _p in _BUILTINS:
    register_profile(_p, provider="*", model="*")


# Provider-specific overrides go below. They can customise just the fields
# that differ from the default; inherit everything else by copying.


def _clone(profile: OCRModelProfile, **overrides) -> OCRModelProfile:
    from dataclasses import replace
    return replace(profile, **overrides)


# Gemini: JSON schema is a hint, not enforced via response_format (we use
# response_mime_type=application/json instead). Postprocessors are the same.
for _mode, _default_name in [
    (TaskMode.LAYOUT_ONLY, "default_layout_only"),
    (TaskMode.LAYOUT_AND_TEXT, "default_layout_and_text"),
    (TaskMode.LAYOUT_CORRECTION, "default_layout_correction"),
    (TaskMode.TEXT_ONLY, "default_text_only"),
    (TaskMode.TEXT_CORRECTION, "default_text_correction"),
]:
    _base = next(p for p in _BUILTINS if p.task_mode == _mode)
    register_profile(_clone(_base, name=f"gemini_{_mode.value}"),
                     provider="gemini", model="*")

# LiteLLM: same template family, but the backend uses json_schema strict mode
# when the provider supports it -- the profile's schema is already set above.
for _mode in TaskMode:
    _base = next(p for p in _BUILTINS if p.task_mode == _mode)
    register_profile(_clone(_base, name=f"litellm_{_mode.value}"),
                     provider="litellm", model="*")

