"""Small helper that wraps the env-var-based settings previously mixed into
``LITELLMAPI`` / ``GEMINIAPI``.

Separating settings from the backend protocol keeps credentials + model
selection orthogonal to how the model is actually invoked. Typer CLI commands
(``set-api-key``, ``show-settings``, ``show-models`` …) continue to work on
this class; the pipeline consumes a :class:`~pageplus.utils.llm.core.OCRBackendSpec`
that *may* be built from these settings via :func:`spec_from_litellm_settings`
and :func:`spec_from_gemini_settings`.
"""
from __future__ import annotations

from dataclasses import dataclass
from importlib import util
from typing import Optional

import requests
import typer
from dotenv import get_key, set_key
from rich import print
from rich.table import Table
from typing_extensions import Annotated

from pageplus.utils.api import API
from pageplus.utils.constants import Environments, LLMProvider
from pageplus.utils.envs import get_env_path
from pageplus.utils.llm.core.specs import (
    GeminiOptions,
    LiteLLMTransportConfig,
    OCRBackendSpec,
)


@dataclass
class LLMSettings(API):
    """Shared env-var-backed settings for any LLM provider.

    Replaces the old ``LITELLMAPI`` / ``GEMINIAPI`` classes. CLI commands that
    manage credentials/model continue to work against this class. Backends are
    constructed separately from an :class:`OCRBackendSpec` that is built from
    these settings via the ``spec_from_*`` helpers below.
    """
    environment: Environments = Environments.PAGEPLUS
    keep_alive_time: float = 60.0

    @property
    def llmprovider(self) -> LLMProvider:
        prov = self.provider.split('__')[0] if self.provider else ''
        try:
            return LLMProvider[prov]
        except KeyError:
            return LLMProvider.OPENAI

    @property
    def model_with_prefix(self) -> str:
        """LiteLLM-style ``<provider>/<model>`` string; empty when no model is set."""
        if not self.model:
            return ''
        return f"{self.llmprovider.name.lower()}/{self.model}"

    @property
    def model(self) -> str:
        modelname = get_key(
            get_env_path(),
            self.environment.as_prefix() + self.prefix_provider() + 'MODEL')
        return modelname if modelname else ''

    @model.setter
    def model(self, modelname: Annotated[str, typer.Argument(help="Model name")]) -> None:
        try:
            if not self.check_model(modelname):
                return
            set_key(
                get_env_path(),
                self.environment.as_prefix() + self.prefix_provider() + 'MODEL',
                modelname)
            print(f"[green]Model updated successfully to:[/green] {self.model}")
        except Exception as e:
            print(f"ERROR: {e}")
            print(f"[red]Failed to update the current model:[/red] {self.model}")

    # ---- Provider-agnostic checks ---------------------------------------

    def check_valid_key(self) -> bool:
        """Best-effort API key validation. Uses LiteLLM when available,
        falls back to a simple models endpoint probe for plain OpenAI-compatible
        servers. Gemini overrides this."""
        if self.environment == Environments.GEMINI:
            return self._gemini_check_valid_key()
        if util.find_spec('litellm') is not None:
            import litellm  # noqa: WPS433
            try:
                ok = litellm.check_valid_key(self.model_with_prefix, self.api_key)
            except Exception as exc:  # pragma: no cover - best-effort
                print(f"[red]Key check raised: {exc}[/red]")
                return False
            print("[green]Valid API key[green]" if ok else "[red]Not a valid API key[red]")
            return bool(ok)
        print("[red]litellm not installed; cannot validate key.[/red]")
        return False

    def check_model(self, modelname: str) -> bool:
        if self.environment == Environments.GEMINI:
            return self._gemini_check_model(modelname)
        # LiteLLM/OpenAI-compatible path: probe the provider's /models endpoint.
        if not self.api_base_url:
            # No endpoint to probe; accept optimistically.
            return True
        try:
            response = requests.get(
                f"{self.api_base_url}/models",
                headers={"Authorization": f"Bearer {self.api_key}"},
                timeout=10.0)
            response.raise_for_status()
            data = response.json()
        except Exception as exc:
            print(f"[orange]Model check failed ({exc}); accepting optimistically.[/orange]")
            return True
        modellist = [m.get('id') for m in data.get('data', [])]
        if not modellist:
            print("[ModelCheck] [orange]No model list available; accepting.[/orange]")
            return True
        ok = modelname in modellist
        print(f"[ModelCheck] {'[green]' + modelname + ' exists.[/green]' if ok else '[red]' + modelname + ' not in provider model list.[/red]'}")
        return ok

    def show_models(self) -> Optional[Table]:
        if self.environment == Environments.GEMINI:
            return self._gemini_show_models()
        if not self.api_base_url:
            print("[red]No API base URL set; cannot list models.[/red]")
            return None
        try:
            response = requests.get(
                f"{self.api_base_url}/models",
                headers={"Authorization": f"Bearer {self.api_key}"},
                timeout=10.0)
            response.raise_for_status()
            data = response.json()
        except Exception as exc:
            print(f"[red]Could not list models: {exc}[/red]")
            return None
        modellist = data.get('data', [])
        if not modellist:
            print("[orange]Provider returned no models.[/orange]")
            return None
        table = Table(title="[green]Models overview[/green]")
        table.add_column("Provider", justify="right", style="cyan", no_wrap=True)
        table.add_column("Model")
        table.add_row(self.provider.replace('__', ' - '),
                      '\n'.join([m.get('id', '') for m in modellist]))
        print(table)
        return table

    # ---- Gemini specifics (thin convenience wrappers) -------------------

    def _gemini_client(self):
        try:
            from google import genai  # noqa: WPS433
        except ImportError as exc:  # pragma: no cover
            raise RuntimeError("google-genai is not installed") from exc
        return genai.Client(api_key=self.api_key)

    def client(self):
        """Backwards-compatible accessor: returns a ``genai.Client`` for the
        legacy table-recognition helpers that still poke the SDK directly.
        Prefer building an ``OCRBackendSpec`` via :func:`spec_from_gemini_settings`
        and going through the pipeline for new code."""
        if self.environment != Environments.GEMINI:
            raise RuntimeError(
                "LLMSettings.client() is only meaningful for the GEMINI environment; "
                "use build_ocr_backend(spec) for other providers.")
        return self._gemini_client()

    def _gemini_check_valid_key(self) -> bool:
        try:
            self._gemini_client()
            print("[green]Valid API key[green]")
            return True
        except Exception as exc:
            print(f"ERROR: {exc}")
            print('[red]Not a valid API key[red]')
            return False

    def _gemini_check_model(self, model: str) -> bool:
        try:
            self._gemini_client().models.get(model=model)
            print(f"[ModelCheck] [green]{model} exists.[/green]")
            return True
        except Exception as exc:
            print(f"{exc}")
            print(f"[ModelCheck] [red]{model} does not exist.[/red]")
            return False

    def _gemini_show_models(self) -> Optional[Table]:
        try:
            modellist = list(self._gemini_client().models.list())
        except Exception as exc:
            print(f"[red]Could not list Gemini models: {exc}[/red]")
            return None
        if not modellist:
            print("[orange]No Gemini models returned.[/orange]")
            return None
        table = Table(title="[green]Models overview[/green]")
        table.add_column("Model")
        for model in modellist:
            table.add_row(getattr(model, "name", str(model)))
        print(table)
        return table

    def show_modeldetails(self, model: str):
        if self.environment != Environments.GEMINI:
            print("[red]show_modeldetails currently only implemented for GEMINI.[/red]")
            return None
        try:
            details = self._gemini_client().models.get(model=model)
            print(details)
            return details
        except Exception as exc:
            print(f"{exc}")
            return str(exc)


# ---------------------------------------------------------------------------
# Spec builders -- turn env-var settings into an OCRBackendSpec the pipeline
# can consume. These are the *only* officially supported adapters between the
# settings layer and the backend layer.
# ---------------------------------------------------------------------------

def spec_from_litellm_settings(
    settings: LLMSettings,
    *,
    json_object_mode: bool = False,
    timeout: Optional[float] = None,
) -> OCRBackendSpec:
    transport = LiteLLMTransportConfig(
        api_base_url=settings.api_base_url,
        api_key=settings.api_key,
        timeout=timeout if timeout is not None else settings.keep_alive_time,
        provider_prefix=settings.llmprovider.name.lower() if settings.provider else None,
        json_object_mode=json_object_mode,
    )
    return OCRBackendSpec(
        provider="litellm",
        model=settings.model_with_prefix or settings.model,
        options=transport,
    )


def spec_from_gemini_settings(
    settings: LLMSettings,
    *,
    calls_per_minute: int = 150,
    thinking_budget: int = 0,
    temperature: float = 1e-7,
    top_p: float = 1e-8,
    max_output_tokens: int = 65536,
    service_tier: Optional[str] = None,
    is_batch: bool = False,
) -> OCRBackendSpec:
    from pageplus.utils.llm.core.specs import GeminiOptions, GeminiBatchOptions
    stier = service_tier or settings.get("GEMINI_SERVICE_TIER", "auto")
    if is_batch:
        options = GeminiBatchOptions(
            api_key=settings.api_key,
            thinking_budget=thinking_budget,
            temperature=temperature,
            top_p=top_p,
            max_output_tokens=max_output_tokens,
            calls_per_minute=60,
            service_tier=stier,
        )
    else:
        options = GeminiOptions(
            api_key=settings.api_key,
            thinking_budget=thinking_budget,
            temperature=temperature,
            top_p=top_p,
            max_output_tokens=max_output_tokens,
            timeout=settings.keep_alive_time or 300.0,
            calls_per_minute=calls_per_minute,
            service_tier=stier,
        )
    return OCRBackendSpec(
        provider="gemini",
        model=settings.model,
        options=options,
    )

