"""Factory for instantiating OCR backends from declarative specs.

Provider name -> backend class registry lives here. Backends register
themselves on import (see :mod:`pageplus.utils.llm.backends`). CLI and GUI
code call :func:`build_ocr_backend` and never instantiate backends directly.
"""
from __future__ import annotations

from typing import Callable, Dict, TYPE_CHECKING

from pageplus.utils.llm.core.errors import ConfigurationError
from pageplus.utils.llm.core.specs import OCRBackendSpec

if TYPE_CHECKING:  # pragma: no cover
    from pageplus.utils.llm.backends.base import OCRBackend


_REGISTRY: Dict[str, Callable[[OCRBackendSpec], "OCRBackend"]] = {}


def register_backend(provider: str,
                     factory: Callable[[OCRBackendSpec], "OCRBackend"]) -> None:
    """Register a backend factory under a provider name.

    Intended to be called at import time from each ``backends/*_backend.py``
    module. Re-registration is allowed (last one wins) to support tests.
    """
    _REGISTRY[provider.lower()] = factory


def build_ocr_backend(spec: OCRBackendSpec) -> "OCRBackend":
    """Resolve ``spec.provider`` to a backend instance.

    Raises :class:`ConfigurationError` with a helpful message if no backend is
    registered under that provider name.
    """
    _ensure_backends_loaded()
    key = spec.provider.lower()
    try:
        factory = _REGISTRY[key]
    except KeyError as exc:
        available = ", ".join(sorted(_REGISTRY.keys())) or "<none>"
        raise ConfigurationError(
            f"No OCR backend registered for provider '{spec.provider}'. "
            f"Known providers: {available}",
            provider=spec.provider,
            model=spec.model,
        ) from exc
    return factory(spec)


def available_providers() -> list[str]:
    """Return sorted list of registered provider names."""
    _ensure_backends_loaded()
    return sorted(_REGISTRY.keys())


_BACKENDS_LOADED = False


def _ensure_backends_loaded() -> None:
    """Import the backends package once so each module can self-register."""
    global _BACKENDS_LOADED
    if _BACKENDS_LOADED:
        return
    _BACKENDS_LOADED = True
    # Imported here to avoid a circular import at module-load time.
    try:  # pragma: no cover - defensive
        import pageplus.utils.llm.backends  # noqa: F401
    except ImportError:
        # Backends package not yet present; ``register_backend`` can still be
        # called manually by tests.
        pass
