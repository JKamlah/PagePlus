"""Typer CLI for the unified **LLM-OCR** pipeline.

Replaces the old ``litellm`` CLI's OCR surface with a provider-agnostic one that
mirrors the LLM-OCR GUI tab: pick a *provider* (built-in LiteLLM preset, a saved
custom endpoint, or the scaffolded ``transformers`` backend) and a *step*
(All-in-One, Text Recognition, Segmentation, Table Recognition, Field-Tagging,
Reading-Order), with task mode / task level / tag filter / output mapping.

Commands are grouped into provider/preset/endpoint/tunnel management and the
``ocr`` (fresh, image -> new PAGE-XML) and ``reocr`` (correction, mutate
existing PAGE-XML) runners. The plaintext ``spellcheck_*`` helpers from the old
``litellm`` CLI are intentionally dropped.
"""
import asyncio
import subprocess
import sys
from importlib import util
from pathlib import Path
from typing import Annotated, List, Optional

import typer
from rich import print

from pageplus.io.logger import logging


app = typer.Typer()


def _install() -> None:
    subprocess.check_call([sys.executable, "-m", "pip", "install", "-I", "litellm"])
    subprocess.check_call([sys.executable, "-m", "pip", "install", "-I", "json-repair"])


if util.find_spec("litellm") is None:

    @app.command()
    def install() -> None:
        """Install litellm + json-repair into the current interpreter."""
        _install()

else:
    from rich.table import Table

    from pageplus.models.page import Page
    from pageplus.utils.constants import ImageExtension
    from pageplus.utils.fs import collect_xml_files, find_image, transform_inputs
    from pageplus.utils.llm.core import RetryPolicy, TaskMode, ExecutionStrategy
    from pageplus.utils.llm.filters import make_tag_filter
    from pageplus.utils.llm.ocr_presets import (
        LLMOCRPresetManager,
        STEP_DEFINITIONS,
        STEP_NAMES,
        build_profile,
        step_family,
    )
    from pageplus.utils.llm.pipeline import (
        PagePlusDocumentPage,
        PagePlusOCRPipeline,
    )
    from pageplus.utils.llm.provider_registry import (
        available_providers,
        list_providers,
        spec_from_preset,
        register_custom_endpoints,
    )

    _presets = LLMOCRPresetManager()
    register_custom_endpoints()

    # ------------------------------------------------------------------
    # Package
    # ------------------------------------------------------------------

    @app.command(rich_help_panel="Package")
    def update_package() -> None:
        """Reinstall litellm + json-repair."""
        _install()

    # ------------------------------------------------------------------
    # Providers + presets
    # ------------------------------------------------------------------

    @app.command(rich_help_panel="Providers")
    def list_provider(
        only_configured: Annotated[bool, typer.Option(help="Only show configured providers.")] = False,
    ) -> None:
        """List provider presets (LiteLLM-routable, custom endpoints, transformers)."""
        providers = available_providers() if only_configured else list_providers()
        table = Table(title=f"[green]Providers ({len(providers)})[/green]")
        table.add_column("id", style="cyan")
        table.add_column("name")
        table.add_column("prefix", style="magenta")
        table.add_column("default model")
        table.add_column("configured?", justify="center")
        for p in providers:
            table.add_row(p.id, p.display_name, p.litellm_prefix, p.default_model or "-",
                          "[green]yes[/green]" if p.is_configured() else "[red]no[/red]")
        print(table)

    @app.command(rich_help_panel="Presets")
    def list_presets() -> None:
        """List the rich LLM-OCR presets (step + prompt + mapping + level)."""
        table = Table(title="[green]LLM-OCR presets[/green]")
        table.add_column("id", style="cyan")
        table.add_column("name")
        table.add_column("step", style="magenta")
        table.add_column("task mode")
        table.add_column("level")
        table.add_column("mapping")
        for p in _presets.list_presets():
            table.add_row(p["id"], p["name"], p.get("step", ""), p.get("task_mode", ""),
                          p.get("task_level", ""), p.get("mapping", ""))
        print(table)

    @app.command(rich_help_panel="Presets")
    def preset_show(preset_id: Annotated[str, typer.Argument(help="Preset id.")]) -> None:
        """Print one preset's full definition."""
        preset = _presets.get_preset(preset_id)
        if not preset:
            print(f"[red]Preset '{preset_id}' not found.[/red]")
            raise typer.Exit(code=1)
        print(preset)

    @app.command(rich_help_panel="Presets")
    def list_steps() -> None:
        """List processing steps and their default task mode / mapping / level."""
        table = Table(title="[green]Steps[/green]")
        table.add_column("step", style="cyan")
        table.add_column("task mode")
        table.add_column("level")
        table.add_column("mapping")
        table.add_column("family")
        for name in STEP_NAMES:
            sd = STEP_DEFINITIONS[name]
            table.add_row(name, sd["task_mode"], sd["task_level"], sd["mapping"], sd["family"])
        print(table)

    # ------------------------------------------------------------------
    # Custom endpoints + SSH tunnels
    # ------------------------------------------------------------------

    @app.command(rich_help_panel="Endpoints")
    def list_endpoints() -> None:
        """List saved custom OpenAI-compatible endpoints."""
        from pageplus.utils.llm.endpoint_store import load_endpoints
        table = Table(title="[green]Custom endpoints[/green]")
        table.add_column("name", style="cyan")
        table.add_column("provider")
        table.add_column("base url")
        table.add_column("model")
        table.add_column("ssh")
        for ep in load_endpoints():
            table.add_row(ep.name, getattr(ep, "provider", "openai"), ep.base_url,
                          ep.default_model or "-", "yes" if ep.ssh_enabled else "-")
        print(table)

    @app.command(rich_help_panel="Endpoints")
    def add_endpoint(
        name: Annotated[str, typer.Argument(help="Short alias.")],
        base_url: Annotated[str, typer.Argument(help="Base URL incl. /v1 for openai.")],
        api_key: Annotated[str, typer.Option(help="API key.")] = "EMPTY",
        model: Annotated[str, typer.Option(help="Default model.")] = "",
        provider: Annotated[str, typer.Option(help="Upstream protocol.")] = "openai",
        ssh_command: Annotated[str, typer.Option(help="Optional SSH tunnel command.")] = "",
    ) -> None:
        """Create or update a custom endpoint preset (``custom_<name>``)."""
        from pageplus.utils.llm.endpoint_store import SavedEndpoint, save_endpoint
        from pageplus.utils.llm.provider_registry import register_custom_endpoints
        save_endpoint(SavedEndpoint(
            name=name, base_url=base_url, api_key=api_key, default_model=model,
            ssh_enabled=bool(ssh_command), ssh_command=ssh_command, provider=provider,
        ))
        register_custom_endpoints()
        print(f"[green]Saved endpoint '{name}' (preset 'custom_{name}').[/green]")

    @app.command(rich_help_panel="Endpoints")
    def delete_endpoint(name: Annotated[str, typer.Argument(help="Endpoint name.")]) -> None:
        """Delete a custom endpoint."""
        from pageplus.utils.llm.endpoint_store import delete_endpoint as _del
        from pageplus.utils.llm.provider_registry import unregister_custom_endpoint
        ok = _del(name)
        unregister_custom_endpoint(name)
        print(f"[green]Deleted '{name}'.[/green]" if ok else f"[red]'{name}' not found.[/red]")

    @app.command(rich_help_panel="Endpoints")
    def tunnel(
        action: Annotated[str, typer.Argument(help="start | stop | status")],
        name: Annotated[str, typer.Argument(help="Endpoint name.")],
    ) -> None:
        """Control the SSH tunnel for a custom endpoint."""
        from pageplus.utils.llm.endpoint_store import get_endpoint
        from pageplus.utils.ssh_tunnel import start_tunnel, stop_tunnel, tunnel_status
        if action == "status":
            print(tunnel_status(name))
            return
        if action == "stop":
            print(stop_tunnel(name))
            return
        ep = get_endpoint(name)
        if ep is None or not ep.ssh_command:
            print(f"[red]Endpoint '{name}' has no SSH command.[/red]")
            raise typer.Exit(code=1)
        print(start_tunnel(name, ep.ssh_command))

    # ------------------------------------------------------------------
    # OCR / ReOCR runners
    # ------------------------------------------------------------------

    def _execute_task(
        *, provider_id: str, preset: dict, step: str, mode: "TaskMode", task_level: str,
        tags: List[str], tag_regex: bool, model: Optional[str], inputs: List[str],
        image_folder: str, same_names: bool, image_extensions: List[ImageExtension],
        jobs: int, calls_per_minute: int, json_object: bool, overwrite: bool, dry_run: bool,
    ) -> List[Path]:
        """Run one task (preset + step + provider) over inputs; return written paths."""
        family = step_family(step)
        use_snippets = task_level in ("TextRegion", "Textline") and family == "correction"
        predicate = make_tag_filter(tags, regex=tag_regex) if tags else None
        region_filter = predicate if (task_level == "TextRegion" or family == "fresh") else None
        line_filter = predicate if (task_level == "Textline" and family == "correction") else None

        documents: List[PagePlusDocumentPage] = []
        if family == "fresh":
            image_paths: List[Path] = []
            for raw in inputs:
                p = Path(raw)
                if p.is_dir():
                    for ext in image_extensions:
                        image_paths.extend(sorted(p.glob(f"*{ext.value}")))
                elif p.suffix.lower() in [e.value for e in image_extensions]:
                    image_paths.append(p)
            for img in image_paths:
                documents.append(PagePlusDocumentPage(
                    image_path=img, page=None, output_xml_path=img.with_suffix(".xml")))
        else:
            xml_files = collect_xml_files(map(Path, inputs or []))
            for xml_file in xml_files:
                page = Page(xml_file)
                if mode == TaskMode.TEXT_ONLY and not use_snippets:
                    page.delete_textlevel('TextRegion')
                if same_names:
                    img_path = None
                    for ext in image_extensions:
                        img_path = find_image(xml_file.with_suffix(ext.value).name, xml_file.parent / image_folder)
                        if img_path:
                            break
                else:
                    img_path = find_image(page.imageFilename(), xml_file.parent / image_folder)
                if not img_path:
                    print(f"[yellow]Image for {xml_file.name} not found; skipping.[/yellow]")
                    continue
                out_xml = xml_file if overwrite else xml_file.parent / "llm_ocr_out" / xml_file.name
                documents.append(PagePlusDocumentPage(
                    image_path=img_path, page=page, output_xml_path=out_xml,
                    region_filter=region_filter, line_filter=line_filter,
                ))

        if not documents:
            print("[yellow]No image/XML pairs resolved for this task.[/yellow]")
            return []

        try:
            spec = spec_from_preset(
                provider_id, model=model or (preset.get("model") or None), task_mode=mode,
                json_object_mode=json_object or None, calls_per_minute=calls_per_minute,
            )
        except ValueError as exc:
            raise typer.BadParameter(str(exc))

        if use_snippets:
            spec.execution = ExecutionStrategy.PER_SNIPPET
        profile = build_profile(preset, spec, mode)

        pipeline = PagePlusOCRPipeline.from_spec(
            spec, task_mode=mode, profile=profile,
            retry_policy=RetryPolicy(max_attempts=3), max_concurrency=max(1, jobs),
            snippet_level=task_level if task_level in ("TextRegion", "Textline") else "Textline",
        )

        print(f"Processing {len(documents)} page(s) with {spec.model} "
              f"(step={step}, mode={mode.value}, level={task_level})")
        outputs = asyncio.run(pipeline.aocr_pages(documents, continue_on_error=True))

        written: List[Path] = []
        for out in outputs:
            if out.error:
                print(f"[red]Failed {out.document.image_path.name}: {out.error}[/red]")
                continue
            if dry_run or out.document.output_xml_path is None:
                continue
            target = out.document.output_xml_path
            target.parent.mkdir(parents=True, exist_ok=True)
            if out.page is not None:
                out.page.save_xml(target)
                written.append(target)
            elif out.xml_content:
                target.write_text(out.xml_content, encoding="utf-8")
                written.append(target)
            logging.info("Wrote %s", target)
        return written

    def _resolve_task(task: dict):
        """Fill a pipeline task with preset + step defaults; return parts."""
        preset = _presets.get_preset(task.get("preset_id")) if task.get("preset_id") else None
        preset = dict(preset) if preset else {"id": "adhoc", "step": task.get("step", "All-in-One"),
                                              "filters": {}}
        step = task.get("step") or preset.get("step") or "All-in-One"
        sd = STEP_DEFINITIONS.get(step, {})
        mode = TaskMode(task.get("task_mode") or preset.get("task_mode") or sd.get("task_mode", "layout_and_text"))
        level = task.get("task_level") or preset.get("task_level") or sd.get("task_level", "Page")
        tags = task.get("tags") or (preset.get("filters") or {}).get("tags") or []
        return preset, step, mode, level, tags

    def _run(
        *, provider_id: str, preset_id: Optional[str], inputs: List[str],
        image_folder: str, model: Optional[str], same_names: bool,
        image_extensions: List[ImageExtension], tag_filter: List[str], tag_regex: bool,
        jobs: int, calls_per_minute: int, json_object: bool, overwrite: bool,
        dry_run: bool, fresh: bool,
    ) -> None:
        preset = _presets.get_preset(preset_id) if preset_id else None
        if preset is None:
            print(f"[red]Preset '{preset_id}' not found. See `list-presets`.[/red]")
            raise typer.Exit(code=1)
        preset = dict(preset)
        step = preset.get("step", "All-in-One")
        family = step_family(step)
        if fresh and family != "fresh":
            print(f"[red]Step '{step}' is a correction step; use `reocr`.[/red]")
            raise typer.Exit(code=1)
        if not fresh and family != "correction":
            print(f"[red]Step '{step}' is a fresh step; use `ocr`.[/red]")
            raise typer.Exit(code=1)
        try:
            mode = TaskMode(preset["task_mode"])
        except ValueError:
            print(f"[red]Invalid task mode '{preset.get('task_mode')}'.[/red]")
            raise typer.Exit(code=1)

        task_level = preset.get("task_level", "Page")
        tags = tag_filter or (preset.get("filters") or {}).get("tags") or []
        written = _execute_task(
            provider_id=provider_id, preset=preset, step=step, mode=mode, task_level=task_level,
            tags=tags, tag_regex=tag_regex, model=model, inputs=inputs, image_folder=image_folder,
            same_names=same_names, image_extensions=image_extensions, jobs=jobs,
            calls_per_minute=calls_per_minute, json_object=json_object, overwrite=overwrite,
            dry_run=dry_run,
        )
        print(f"[green]Done. Wrote {len(written)} file(s).[/green]")

    @app.command()
    def ocr(
        provider: Annotated[str, typer.Argument(help="Provider id (see list-provider).")],
        inputs: Annotated[List[str], typer.Argument(help="Image files or folders.",
                                                     callback=transform_inputs)] = None,
        preset: Annotated[str, typer.Option(help="LLM-OCR preset id (fresh step).")] = "allinone",
        model: Annotated[Optional[str], typer.Option(help="Override model.")] = None,
        image_extensions: Annotated[List[ImageExtension],
                                    typer.Option(case_sensitive=False)] = ['.png', '.jpg', '.jpeg', '.tif', '.tiff'],
        tag_filter: Annotated[List[str], typer.Option(help="Process only these tags.")] = None,
        tag_regex: Annotated[bool, typer.Option(help="Treat tag filters as regex.")] = False,
        jobs: Annotated[int, typer.Option(help="Concurrent calls.")] = 4,
        calls_per_minute: Annotated[int, typer.Option()] = 120,
        json_object: Annotated[bool, typer.Option()] = False,
        dry_run: Annotated[bool, typer.Option()] = False,
    ) -> None:
        """Fresh OCR: image(s) -> new PAGE-XML (All-in-One, Segmentation, Table, Markdown)."""
        _run(provider_id=provider, preset_id=preset, inputs=inputs or [], image_folder='.',
             model=model, same_names=False, image_extensions=image_extensions,
             tag_filter=tag_filter or [], tag_regex=tag_regex, jobs=jobs,
             calls_per_minute=calls_per_minute, json_object=json_object,
             overwrite=False, dry_run=dry_run, fresh=True)

    @app.command()
    def reocr(
        provider: Annotated[str, typer.Argument(help="Provider id (see list-provider).")],
        inputs: Annotated[List[str], typer.Argument(exists=True, help="PAGE-XML files or folders.",
                                                     callback=transform_inputs)] = None,
        preset: Annotated[str, typer.Option(help="LLM-OCR preset id (correction step).")] = "textrec_line",
        image_folder: Annotated[str, typer.Option(help="Folder with page images.")] = '.',
        model: Annotated[Optional[str], typer.Option(help="Override model.")] = None,
        same_names: Annotated[bool, typer.Option(help="Match images by XML basename.")] = False,
        image_extensions: Annotated[List[ImageExtension],
                                    typer.Option(case_sensitive=False)] = ['.png', '.jpg', '.jpeg', '.tif', '.tiff'],
        tag_filter: Annotated[List[str], typer.Option(help="Process only these tags.")] = None,
        tag_regex: Annotated[bool, typer.Option(help="Treat tag filters as regex.")] = False,
        jobs: Annotated[int, typer.Option(help="Concurrent calls.")] = 4,
        calls_per_minute: Annotated[int, typer.Option()] = 120,
        json_object: Annotated[bool, typer.Option()] = False,
        overwrite: Annotated[bool, typer.Option(help="Overwrite input XML in place.")] = False,
        dry_run: Annotated[bool, typer.Option()] = False,
    ) -> None:
        """Correction ReOCR on existing PAGE-XML (Text Recognition, Field-Tagging, Reading-Order)."""
        _run(provider_id=provider, preset_id=preset, inputs=inputs or [], image_folder=image_folder,
             model=model, same_names=same_names, image_extensions=image_extensions,
             tag_filter=tag_filter or [], tag_regex=tag_regex, jobs=jobs,
             calls_per_minute=calls_per_minute, json_object=json_object,
             overwrite=overwrite, dry_run=dry_run, fresh=False)

    # ------------------------------------------------------------------
    # Pipelines (saved multi-task chains)
    # ------------------------------------------------------------------

    from pageplus.utils.llm.pipeline_store import LLMOCRPipelineStore

    _pipelines = LLMOCRPipelineStore()

    @app.command(rich_help_panel="Pipelines")
    def list_pipelines() -> None:
        """List saved LLM-OCR pipelines (created in the GUI or via JSON)."""
        table = Table(title="[green]LLM-OCR pipelines[/green]")
        table.add_column("id", style="cyan")
        table.add_column("name")
        table.add_column("mode", style="magenta")
        table.add_column("tasks", justify="right")
        for p in _pipelines.list_pipelines():
            table.add_row(p["id"], p.get("name", ""), p.get("execution_mode", "stepwise"),
                          str(len(p.get("tasks", []))))
        print(table)

    @app.command(rich_help_panel="Pipelines")
    def pipeline_show(pipeline_id: Annotated[str, typer.Argument(help="Pipeline id.")]) -> None:
        """Print a saved pipeline's task chain."""
        pl = _pipelines.get_pipeline(pipeline_id)
        if not pl:
            print(f"[red]Pipeline '{pipeline_id}' not found.[/red]")
            raise typer.Exit(code=1)
        print(pl)

    @app.command(rich_help_panel="Pipelines")
    def run_pipeline(
        pipeline_id: Annotated[str, typer.Argument(help="Saved pipeline id.")],
        inputs: Annotated[List[str], typer.Argument(help="Images (fresh first step) or PAGE-XML.",
                                                    callback=transform_inputs)] = None,
        mode: Annotated[Optional[str], typer.Option(help="Override execution mode: stepwise|pagewise.")] = None,
        image_folder: Annotated[str, typer.Option(help="Folder with images for correction steps.")] = '.',
        same_names: Annotated[bool, typer.Option(help="Match images by XML basename.")] = True,
        image_extensions: Annotated[List[ImageExtension],
                                    typer.Option(case_sensitive=False)] = ['.png', '.jpg', '.jpeg', '.tif', '.tiff'],
        jobs: Annotated[int, typer.Option(help="Concurrent calls / pages.")] = 4,
        calls_per_minute: Annotated[int, typer.Option()] = 120,
        json_object: Annotated[bool, typer.Option()] = False,
        dry_run: Annotated[bool, typer.Option()] = False,
    ) -> None:
        """Run a saved pipeline (chained tasks) over images or PAGE-XML."""
        pl = _pipelines.get_pipeline(pipeline_id)
        if not pl:
            print(f"[red]Pipeline '{pipeline_id}' not found. See `list-pipelines`.[/red]")
            raise typer.Exit(code=1)
        tasks = pl.get("tasks", [])
        if not tasks:
            print("[red]Pipeline has no tasks.[/red]")
            raise typer.Exit(code=1)
        exec_mode = mode or pl.get("execution_mode", "stepwise")
        inputs = inputs or []

        def _one(task: dict, task_inputs: List[str], *, overwrite: bool) -> List[Path]:
            preset, step, t_mode, level, tags = _resolve_task(task)
            return _execute_task(
                provider_id=task.get("provider_id", ""), preset=preset, step=step, mode=t_mode,
                task_level=level, tags=tags, tag_regex=bool(task.get("tag_regex", False)),
                model=task.get("model") or None, inputs=task_inputs, image_folder=image_folder,
                same_names=same_names, image_extensions=image_extensions, jobs=jobs,
                calls_per_minute=calls_per_minute, json_object=json_object,
                overwrite=overwrite, dry_run=dry_run,
            )

        total_written: List[Path] = []
        if exec_mode == "pagewise":
            first_fresh = step_family(tasks[0].get("step", "All-in-One")) == "fresh"
            for unit in inputs:
                working = None if first_fresh else unit
                for i, task in enumerate(tasks, start=1):
                    fam = step_family(task.get("step", "All-in-One"))
                    src = [unit] if fam == "fresh" else ([working] if working else [])
                    if not src:
                        print(f"[yellow]page {Path(unit).name}: no XML for step {i}; skipping.[/yellow]")
                        continue
                    w = _one(task, [str(s) for s in src], overwrite=True)
                    if w:
                        working = str(w[0])
                        total_written.extend(w)
        else:  # stepwise
            working_xmls: Optional[List[str]] = None
            for i, task in enumerate(tasks, start=1):
                fam = step_family(task.get("step", "All-in-One"))
                print(f"[cyan]=== Step {i}/{len(tasks)}: {task.get('step')} ({fam}) ===[/cyan]")
                if fam == "fresh":
                    w = _one(task, inputs, overwrite=False)
                    if w:
                        working_xmls = [str(p) for p in w]
                else:
                    src = working_xmls or [str(x) for x in inputs]
                    if not src:
                        print("[yellow]No XML available for correction step; skipping.[/yellow]")
                        continue
                    w = _one(task, src, overwrite=True)
                    if w:
                        working_xmls = [str(p) for p in w]
                total_written.extend(w)
        print(f"[green]Pipeline done. Wrote {len(total_written)} file(s).[/green]")


if __name__ == "__main__":
    app()
