"""OCR backend implementations.

Each ``*_backend.py`` module registers itself with :func:`register_backend`
at import time, so ``build_ocr_backend(spec)`` can resolve the provider name
without hard-coded imports at the call site.

Importing this package is what makes the registry populated; the builder
does this lazily on the first call.
"""
from __future__ import annotations

from importlib import util as _util

# Each module guards its own optional deps (google-genai, litellm, etc.)
# so importing this package never fails in a minimal environment.
from pageplus.utils.llm.backends import base  # noqa: F401

if _util.find_spec("google") is not None and _util.find_spec("google.genai") is not None:
    from pageplus.utils.llm.backends import gemini_backend  # noqa: F401

if _util.find_spec("litellm") is not None:
    from pageplus.utils.llm.backends import litellm_backend  # noqa: F401

if _util.find_spec("openai") is not None:
    from pageplus.utils.llm.backends import openai_direct_backend  # noqa: F401

# The direct HuggingFace ``transformers`` backend is a lightweight scaffold and
# is always registered (it raises a clear error on use until inference lands),
# so the LLM-OCR tab can always offer it as a provider kind.
from pageplus.utils.llm.backends import transformers_backend  # noqa: F401

