"""Typer CLI for the LiteLLM-backed providers.

``ocr`` is a thin wrapper over :class:`PagePlusOCRPipeline` running the
``text_only`` task mode (image + existing PAGE-XML layout -> text per line).
This replaces the old per-line crop-and-complete loop; behaviour-compatible
for the common case (layout already segmented, text should be (re)generated)
and cleaner for every other case.

``spellcheck_lines`` / ``spellcheck_fulltext`` remain as-is because they are
plaintext (non-OCR) helpers that don't benefit from the image-aware pipeline.
"""
import asyncio
import json
import subprocess
import sys
from importlib import util
from pathlib import Path
from typing import Annotated, List, Optional

import typer
from rich import print

from pageplus.io.logger import logging
from pageplus.utils.fs import collect_xml_files, find_image, transform_inputs
from pageplus.utils.profile import profile, ProfileFnRet


app = typer.Typer()


def _install() -> None:
    subprocess.check_call([sys.executable, "-m", "pip", "install", "-I", "litellm"])
    subprocess.check_call([sys.executable, "-m", "pip", "install", "-I", "json-repair"])


if util.find_spec('litellm') is None:

    @app.command()
    def install() -> None:
        """Install litellm + json-repair into the current interpreter."""
        _install()

else:

    from pydantic import BaseModel

    from pageplus.models.page import Page
    from pageplus.utils.constants import Environments, ImageExtension, LLMProvider, ProfileLevel
    from pageplus.utils.llm.core import (
        RetryPolicy,
        TaskMode,
    )
    from pageplus.utils.llm.pipeline import (
        PagePlusDocumentPage,
        PagePlusOCRPipeline,
    )
    from pageplus.utils.llm.settings import LLMSettings, spec_from_litellm_settings
    from pageplus.utils.llm.provider_registry import (
        available_providers as _available_presets,
        list_providers as _list_presets,
        spec_from_preset,
    )
    from pageplus.utils.workspace import Workspace

    llm_workspace = Workspace(Environments.LLM)
    llm_api = LLMSettings(Environments.LLM)

    # ------------------------------------------------------------------
    # PACKAGE / SETTINGS / MODEL commands
    # ------------------------------------------------------------------

    @app.command(rich_help_panel="Package")
    def update_package() -> None:
        """Reinstall litellm + json-repair."""
        _install()

    @app.command(rich_help_panel="Settings")
    def set_provider(
        provider: Annotated[LLMProvider, typer.Argument(help="LiteLLM Provider")] = "OpenAI",
        service: Annotated[str, typer.Argument(help="Service")] = "DEFAULT",
    ) -> None:
        llm_api.__class__.provider.fset(llm_api, provider, service)

    @app.command(rich_help_panel="Settings")
    def set_api_base_url(url: Annotated[str, typer.Argument(help="URL to LLM")]) -> None:
        llm_api.api_base_url = url

    @app.command(rich_help_panel="Settings")
    def set_api_key(api_key: Annotated[str, typer.Argument(help="API Key")]) -> None:
        llm_api.api_key = api_key

    @app.command(rich_help_panel="Settings")
    def show_settings() -> None:
        llm_api.show_settings()

    @app.command()
    def check_valid_key() -> None:
        llm_api.check_valid_key()

    @app.command()
    def show_models():
        return llm_api.show_models()

    @app.command()
    def check_model(model: Annotated[str, typer.Argument(help="Model name")]) -> None:
        llm_api.check_model(model)

    @app.command()
    def set_model(model: Annotated[str, typer.Argument(help="Model name")]) -> None:
        llm_api.model = model

    # ------------------------------------------------------------------
    # Provider presets ("provider templates")
    # ------------------------------------------------------------------

    @app.command(rich_help_panel="Provider presets")
    def list_presets(
        only_configured: Annotated[bool, typer.Option(
            help="If True, show only presets whose credentials are present in the environment.",
        )] = False,
    ) -> None:
        """List every registered LiteLLM provider preset.

        Each preset encodes a LiteLLM prefix, the expected API-key env var,
        an optional API-base env var, a default vision-capable model, and
        the :class:`TaskMode` s it supports. Use ``preset-spec`` to preview
        the resolved backend spec, or pass ``--preset`` to ``ocr`` to run a
        preset end-to-end.
        """
        from rich.table import Table

        presets = _available_presets() if only_configured else _list_presets()
        if not presets:
            print("[orange]No LiteLLM provider presets are configured yet.[/orange]")
            return

        table = Table(title=f"[green]LiteLLM provider presets ({len(presets)})[/green]")
        table.add_column("id", style="cyan", no_wrap=True)
        table.add_column("name")
        table.add_column("prefix", style="magenta")
        table.add_column("default model")
        table.add_column("env", style="dim")
        table.add_column("task modes", style="dim")
        table.add_column("configured?", justify="center")

        for preset in presets:
            envs: List[str] = []
            if preset.env_api_key:
                envs.append(preset.env_api_key)
            if preset.env_api_base:
                envs.append(preset.env_api_base)
            modes = ",".join(tm.value for tm in preset.task_modes)
            ok = "[green]yes[/green]" if preset.is_configured() else "[red]no[/red]"
            table.add_row(
                preset.id,
                preset.display_name,
                preset.litellm_prefix,
                preset.default_model or "-",
                " + ".join(envs) if envs else "-",
                modes,
                ok,
            )
        print(table)

    @app.command(rich_help_panel="Provider presets")
    def preset_spec(
        preset: Annotated[str, typer.Argument(help="Preset id (see list-presets).")],
        model: Annotated[Optional[str], typer.Option(help="Override preset's default model.")] = None,
        task_mode: Annotated[TaskMode, typer.Option(case_sensitive=False)] = TaskMode.TEXT_ONLY,
    ) -> None:
        """Preview the OCRBackendSpec that would be built from a preset."""
        try:
            spec = spec_from_preset(preset, model=model, task_mode=task_mode)
        except Exception as exc:
            print(f"[red]{exc}[/red]")
            raise typer.Exit(code=1)
        print({
            "provider": spec.provider,
            "model": spec.model,
            "options": spec.options.__dict__,
            "metadata": spec.metadata,
            "task_mode": task_mode.value,
        })

    # ------------------------------------------------------------------
    # Helpers (shared with OCR)
    # ------------------------------------------------------------------

    def ocr_settings(ctx: typer.Context, param: typer.CallbackParam, value):
        """Allow overriding provider/url/model from the CLI without mutating .env."""
        model, api_key, api_url, _ = llm_api.model, llm_api.api_key, llm_api.api_base_url, llm_api.provider

        def copy_provider():
            set_provider(llm_api.llmprovider, 'OCR')
            llm_api.api_base_url = api_url
            llm_api.api_key = api_key
            llm_api.model = model

        match param.name:
            case "provider" if (value and value != llm_api.provider):
                copy_provider()
            case "api_base_url" if (value and value != llm_api.api_base_url):
                if not llm_api.provider.endswith('OCR'):
                    copy_provider()
                llm_api.api_base_url = value
            case "model_name" if (value and value != llm_api.model):
                if not llm_api.provider.endswith('OCR'):
                    copy_provider()
                llm_api.model = value
        return None

    # ------------------------------------------------------------------
    # OCR via pipeline (text_only on pre-segmented PAGE-XML)
    # ------------------------------------------------------------------

    @app.command()
    @profile('litellm-ocr')
    def ocr(
        inputs: Annotated[List[str], typer.Argument(exists=True, help="Paths to XML files or folders.",
                                                    callback=transform_inputs)] = None,
        image_folder: Annotated[str, typer.Option(exists=True,
                                                  help="Folder containing images.")] = '.',
        preset: Annotated[Optional[str], typer.Option(
            help="Use a configured LiteLLM provider preset (see `litellm list-presets`) "
                 "instead of the ad-hoc provider/api_base_url/model_name settings.",
        )] = None,
        provider: Annotated[str, typer.Option(help="Override provider on-the-fly.",
                                              callback=ocr_settings)] = None,
        api_base_url: Annotated[str, typer.Option(help="Override API base URL.",
                                                  callback=ocr_settings)] = None,
        model_name: Annotated[str, typer.Option(help="Override model name.",
                                                callback=ocr_settings)] = None,
        task_mode: Annotated[TaskMode,
                             typer.Option(help="Pipeline task mode.",
                                          case_sensitive=False)] = TaskMode.TEXT_ONLY,
        same_names: Annotated[bool, typer.Option(help="Match images by XML basename.")] = False,
        image_extensions: Annotated[List[ImageExtension],
                                    typer.Option(case_sensitive=False)] = ['.png', '.jpg', '.jpeg', '.tif', '.tiff'],
        json_object: Annotated[bool, typer.Option(help="Use json_object mode instead of json_schema.")] = False,
        calls_per_minute: Annotated[int, typer.Option()] = 120,
        jobs: Annotated[int, typer.Option(help="Concurrent backend calls.")] = 1,
        profile: Annotated[str, typer.Option(help="Profile tag.")] = '',
        profilelevel: Annotated[List[ProfileLevel], typer.Option()] = ("stats", "params", "analytics", "summary"),
        overwrite: Annotated[bool, typer.Option(help="Overwrite input XML in place.")] = False,
        dry_run: Annotated[bool, typer.Option()] = False,
    ):
        """OCR with a LiteLLM provider. Supports all five PAGE-XML task modes.

        Two ways to pick a provider:
          1. ``--preset <id>`` — apply a configured provider preset (``openai``,
             ``anthropic``, ``mistral``, ``azure_openai``, ``ollama``, ...). The
             preset supplies the LiteLLM prefix, credentials, and a default
             vision-capable model. The ``--task-mode`` value is validated
             against the preset's capability set.
          2. ``--provider/--api-base-url/--model-name`` — low-level overrides
             that apply on top of ``LLMSettings`` (backwards compatible).

        For task modes that require a bare image (``layout_only``,
        ``layout_and_text``), point ``--preset`` at a vision-capable provider.
        """
        ocr.profile = ProfileFnRet()
        ocr.profile.name = profile
        ocr.profile.dir = Path(inputs[0]).absolute() if inputs else ''
        ocr.profile.stats = {'pages': 0, 'lines': 0}

        xml_files = collect_xml_files(map(Path, inputs or []))
        if not xml_files:
            raise FileNotFoundError('No xml files found in input directory')

        documents: List[PagePlusDocumentPage] = []
        for xml_file in xml_files:
            page = Page(xml_file)
            if task_mode == TaskMode.TEXT_ONLY:
                page.delete_textlevel('TextRegion')
            if same_names:
                imagePath: Optional[Path] = None
                for ext in image_extensions:
                    candidate = xml_file.with_suffix(ext.value).name
                    imagePath = find_image(candidate, xml_file.parent / image_folder)
                    if imagePath:
                        break
            else:
                imagePath = find_image(page.imageFilename(), xml_file.parent / image_folder)
            if not imagePath:
                print(f"[yellow]Image for {xml_file.name} not found; skipping.[/yellow]")
                continue
            documents.append(PagePlusDocumentPage(
                image_path=imagePath,
                page=page,
                output_xml_path=xml_file if overwrite else xml_file.parent.joinpath(
                    (llm_api.model or preset or 'out').replace('.', '_').replace(':', '-')).joinpath(xml_file.name),
            ))

        if not documents:
            raise FileNotFoundError('No image/XML pairs resolved')

        if preset:
            try:
                spec = spec_from_preset(
                    preset,
                    model=model_name,
                    task_mode=task_mode,
                    json_object_mode=json_object or None,
                    calls_per_minute=calls_per_minute,
                )
            except ValueError as exc:
                raise typer.BadParameter(str(exc))
            effective_model = spec.model
            effective_base = spec.options.api_base_url
        else:
            spec = spec_from_litellm_settings(llm_api, json_object_mode=json_object)
            effective_model = llm_api.model_with_prefix
            effective_base = llm_api.api_base_url

        pipeline = PagePlusOCRPipeline.from_spec(
            spec,
            task_mode=task_mode,
            retry_policy=RetryPolicy(max_attempts=3),
            max_concurrency=jobs,
        )

        if 'params' in profilelevel:
            ocr.profile.params = {
                'preset': preset,
                'model': effective_model,
                'api_base': effective_base,
                'task_mode': task_mode.value,
            }

        print(f"Processing {len(documents)} pages with {effective_model} (mode={task_mode.value})")
        outputs = asyncio.run(pipeline.aocr_pages(documents, continue_on_error=True))

        all_usage = []
        for idx, out in enumerate(outputs, 1):
            if out.error:
                print(f"[red]Failed {out.document.image_path}: {out.error}[/red]")
                continue
            ocr.profile.stats['pages'] += 1
            if out.ocr_result is not None:
                all_usage.append(out.ocr_result.usage)
            if not dry_run and out.document.output_xml_path and out.page is not None:
                out.document.output_xml_path.parent.mkdir(parents=True, exist_ok=True)
                out.page.save_xml(out.document.output_xml_path)
                logging.info(f'Wrote modified xml file to: {out.document.output_xml_path}')
                print(f"[green]Updated {out.document.output_xml_path}[/green] ({idx}/{len(outputs)})")

        return all_usage

    # ------------------------------------------------------------------
    # Plain-text spellcheck helpers (no pipeline; still direct completion).
    # ------------------------------------------------------------------

    @app.command()
    def spellcheck_lines(
        inputs: Annotated[List[str], typer.Argument(exists=True, help="Paths to XML files.",
                                                    callback=transform_inputs)] = None,
        add_fulltext: Annotated[bool, typer.Option(help="Include full page text in the prompt.")] = False,
    ):
        """Spellcheck text lines via chat completion (no image context)."""
        import html

        def call_llm(input_data, fulltext):
            system = (
                "You are an expert in spellchecking.\n"
                "Analyse the input and find all possible OCR errors and misspelling.\n"
                "Preserve hyphenation as it appears. Absolutely do not merge words split by hyphens at the end of a line. "
                "The split must be preserved exactly as it appears in the original text.\n"
                "Each output line must correspond exactly to the original input line. "
                "Do not combine, merge, or alter the structure of the text.\n"
                "JSON <|input|>\n"
                "{'lines': [{'id': id, 'original': text},..]}\n"
                "JSON <|output|>\n"
                "{'lines': [{'id': id, 'corrected': corrected_text},..]}\n")
            try:
                from litellm import completion
                response = completion(
                    model=llm_api.model_with_prefix,
                    api_base=llm_api.api_base_url,
                    api_key=llm_api.api_key,
                    timeout=60.0,
                    stream=False,
                    temperature=0,
                    top_p=0,
                    n=1,
                    messages=[
                        {"role": "system", "content": [{"type": "text", "text": system}]},
                        {"role": "user", "content": [{"type": "text", "text": html.escape(f"{input_data}")}]},
                    ],
                    response_format={
                        "type": "json_schema",
                        "json_schema": {
                            "name": "correction_response",
                            "strict": True,
                            "schema": {
                                "type": "object",
                                "properties": {
                                    "lines": {
                                        "type": "array",
                                        "items": {
                                            "type": "object",
                                            "properties": {
                                                "id": {"type": "string"},
                                                "corrected": {"type": "string"},
                                            },
                                            "required": ["id", "corrected"],
                                            "additionalProperties": False,
                                        },
                                    },
                                },
                                "required": ["lines"],
                                "additionalProperties": False,
                            },
                        },
                    },
                    max_tokens=8192,
                )
            except Exception as e:
                print("An error occurred during completion:", e)
                return {}
            json_str = response.choices[0].message.content
            input_map = {item["id"]: item for item in input_data["lines"]}
            corrected_map = {item["id"]: item for item in json.loads(html.unescape(json_str))["lines"]}
            return {"lines": [{**corrected_map[key], **input_map[key]}
                              for key in input_map.keys() & corrected_map.keys()]}

        xml_files = collect_xml_files(map(Path, inputs))
        if not xml_files:
            raise FileNotFoundError('No xml files found in input directory')
        for xml_file in xml_files:
            page = Page(xml_file)
            fulltext = page.extract_fulltext()
            corrected = {'lines': []}
            for textregion in page.regions.textregions:
                chunk = {"lines": []}
                for line in textregion.textlines:
                    chunk['lines'].append({'id': line.get_id(), 'original': line.get_text() or ''})
                    if len(chunk['lines']) > 10:
                        corrected['lines'].append(call_llm(chunk, fulltext))
                        chunk = {"lines": []}
                if chunk['lines']:
                    corrected['lines'].append(call_llm(chunk, fulltext))
            with xml_file.with_suffix('.spellchecked.json').open('w', encoding='utf-8') as fout:
                json.dump(corrected, fout, indent=2, ensure_ascii=False)

    @app.command()
    def spellcheck_fulltext(
        inputs: Annotated[List[str], typer.Argument(exists=True, help="XML files.",
                                                    callback=transform_inputs)] = None,
    ):
        """Spellcheck the full page text at once."""
        xml_files = collect_xml_files(map(Path, inputs))
        if not xml_files:
            raise FileNotFoundError('No xml files found in input directory')
        system = (
            "You are an expert in spellchecking. Analyse the input and find all possible OCR errors.\n"
            "Return JSON {'text': [{'corrected': corrected_text}]} only.")

        class Corrections(BaseModel):
            corrections: str
            original: str

        class CorrectionsList(BaseModel):
            lines: list[Corrections]

        for xml_file in xml_files:
            page = Page(xml_file)
            page.delete_textlevel('region')
            fulltext = page.extract_fulltext()
            prompt = {'text': [{'original': ln} for ln in fulltext.split('\n')]}
            try:
                from litellm import completion
                response = completion(
                    model=llm_api.model_with_prefix,
                    api_base=llm_api.api_base_url,
                    api_key=llm_api.api_key,
                    timeout=60.0,
                    stream=False,
                    temperature=0,
                    top_p=0,
                    n=1,
                    messages=[
                        {"role": "system", "content": [{"type": "text", "text": system}]},
                        {"role": "user", "content": [{"type": "text", "text": f"{prompt}"}]},
                    ],
                    response_format={"type": "json_object"},
                    max_tokens=8000,
                )
                answer = response.choices[0].message.content
                with xml_file.with_suffix('.spellchecked.text').open('w', encoding='utf-8') as fout:
                    fout.write(answer)
            except Exception as e:
                print("An error occurred during completion:", e)


if __name__ == "__main__":
    app()
