"""JSON-backed store for user-defined OpenAI-compatible endpoints.

Saved endpoints are persisted as ``custom_endpoints.json`` next to the
PagePlus ``.env`` file (``USER_DATA_DIR``).  Each entry describes a remote
server (e.g. a vLLM instance on a DGX node) with an optional SSH tunnel
command so the GUI can open and close the tunnel on the user's behalf.

Usage::

    from pageplus.utils.llm.endpoint_store import load_endpoints, save_endpoint

    save_endpoint(SavedEndpoint(name="spark", base_url="http://localhost:8082/v1", ...))
    endpoints = load_endpoints()
"""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Dict, List, Optional

from pageplus.utils.constants import USER_DATA_DIR

_STORE_FILE = USER_DATA_DIR / "custom_endpoints.json"


@dataclass
class SavedEndpoint:
    """A user-defined OpenAI-compatible endpoint."""

    name: str
    """Short alias shown in the preset picker (e.g. ``spark``)."""

    base_url: str
    """Full base URL including ``/v1`` suffix (e.g. ``http://localhost:8082/v1``)."""

    api_key: str = "EMPTY"
    """API key sent with requests.  ``EMPTY`` is common for local vLLM."""

    default_model: str = ""
    """Default model name to use (e.g. ``Infinity-Parser2-Pro``)."""

    alt_models: List[str] = field(default_factory=list)
    """Additional suggested model names."""

    ssh_enabled: bool = False
    """Whether an SSH tunnel should be opened before connecting."""

    ssh_command: str = ""
    """Full SSH command for the tunnel (e.g.
    ``ssh -N -L 8082:localhost:8082 root@spark01.bib.uni-mannheim.de``)."""

    provider: str = "openai"
    """Upstream provider protocol/prefix for LiteLLM (e.g. ``openai``, ``gemini``, ``ollama``, ``curl``)."""

    image_key: str = "image"
    """The JSON payload key for the base64-encoded image (used when provider='curl')."""

    prompt_key: str = "prompt"
    """The JSON payload key for the prompt string (used when provider='curl')."""


# ---------------------------------------------------------------------------
# URL normalization
# ---------------------------------------------------------------------------


def normalize_base_url(url: str, provider: str = "openai") -> str:
    """Return a base URL in the shape the upstream provider expects.

    * Ensures an ``http(s)://`` scheme and strips trailing slashes (a trailing
      slash makes LiteLLM build ``http://host//api/generate`` for Ollama, which
      triggers a redirect that downgrades POST→GET and yields ``405 method not
      allowed``).
    * ``openai`` servers (vLLM, TGI, ollama's OpenAI-compat port, …) need the
      ``/v1`` suffix; native ``ollama`` / ``gemini`` endpoints must NOT have it
      (they use ``/api/...`` resp. their own routes off the server root).
    """
    u = (url or "").strip()
    if not u:
        return u
    if not u.lower().startswith(("http://", "https://")):
        u = "http://" + u
    u = u.rstrip("/")

    # Strip API call paths that belong to the request, not the base URL
    # (e.g. a user pasting ".../api/generate" or ".../v1/chat/completions").
    for suffix in ("/api/generate", "/api/chat", "/api/embeddings", "/api/embed",
                   "/api/tags", "/api/show", "/chat/completions", "/completions"):
        if u.lower().endswith(suffix):
            u = u[: -len(suffix)].rstrip("/")
            break

    low = u.lower()
    if provider == "openai":
        if not low.endswith("/v1"):
            u = u + "/v1"
    else:
        if low.endswith("/v1"):
            u = u[: -len("/v1")].rstrip("/")
        elif low.endswith("/api"):
            u = u[: -len("/api")].rstrip("/")
    return u


# ---------------------------------------------------------------------------
# CRUD helpers
# ---------------------------------------------------------------------------


def _read_store() -> Dict[str, dict]:
    """Read the raw JSON store, returning ``{}`` on any error."""
    if not _STORE_FILE.exists():
        return {}
    try:
        data = json.loads(_STORE_FILE.read_text(encoding="utf-8"))
        if isinstance(data, dict):
            return data
    except Exception:
        pass
    return {}


def _write_store(data: Dict[str, dict]) -> None:
    _STORE_FILE.parent.mkdir(parents=True, exist_ok=True)
    _STORE_FILE.write_text(
        json.dumps(data, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )


def load_endpoints() -> List[SavedEndpoint]:
    """Return all saved endpoints, sorted by name."""
    store = _read_store()
    endpoints: List[SavedEndpoint] = []
    for name, blob in sorted(store.items()):
        try:
            blob["name"] = name  # ensure key matches
            endpoints.append(SavedEndpoint(**{
                k: v for k, v in blob.items()
                if k in SavedEndpoint.__dataclass_fields__
            }))
        except Exception:
            continue
    return endpoints


def get_endpoint(name: str) -> Optional[SavedEndpoint]:
    """Return a single endpoint by name, or ``None``."""
    store = _read_store()
    blob = store.get(name)
    if blob is None:
        return None
    blob["name"] = name
    try:
        return SavedEndpoint(**{
            k: v for k, v in blob.items()
            if k in SavedEndpoint.__dataclass_fields__
        })
    except Exception:
        return None


def save_endpoint(endpoint: SavedEndpoint) -> None:
    """Create or update a saved endpoint (base URL normalized per provider)."""
    endpoint.base_url = normalize_base_url(endpoint.base_url, getattr(endpoint, "provider", "openai"))
    store = _read_store()
    store[endpoint.name] = asdict(endpoint)
    _write_store(store)


def delete_endpoint(name: str) -> bool:
    """Remove a saved endpoint.  Returns ``True`` if it existed."""
    store = _read_store()
    if name not in store:
        return False
    del store[name]
    _write_store(store)
    return True
