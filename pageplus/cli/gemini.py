"""Typer CLI for the Gemini backend.

Thin wrappers over :class:`PagePlusOCRPipeline`. Command names and argument
signatures are kept stable so existing scripts and docs keep working; the
actual OCR logic now lives in ``pageplus/utils/llm/`` (backends, templates,
pipeline) and is shared with the LiteLLM CLI.
"""
import asyncio
import json
import subprocess
import sys
from importlib import util
from pathlib import Path
from typing import List, Optional

import typer
from rich import print
from typing_extensions import Annotated

from pageplus.utils.constants import ImageExtension, ProfileLevel, RecognizeLevel, UpdateElements
from pageplus.utils.fs import find_image, transform_inputs
from pageplus.utils.profile import profile, ProfileFnRet


app = typer.Typer()


def _install() -> None:
    subprocess.check_call([sys.executable, "-m", "pip", "install", "-I", "google-genai"])
    subprocess.check_call([sys.executable, "-m", "pip", "install", "-I", "json-repair"])


if util.find_spec('google') is None:

    @app.command()
    def install() -> None:
        """Install google-genai + json-repair into the current interpreter."""
        _install()

else:

    from pageplus.models.page import Page
    from pageplus.utils.constants import Environments
    from pageplus.utils.llm.core import (
        ExecutionStrategy,
        OCRBackendSpec,
        RetryPolicy,
        TaskMode,
    )
    from pageplus.utils.llm.pipeline import (
        PagePlusDocumentPage,
        PagePlusOCRPipeline,
    )
    from pageplus.utils.llm.settings import LLMSettings, spec_from_gemini_settings
    from pageplus.utils.workspace import Workspace

    llm_workspace = Workspace(Environments.GEMINI)
    llm_api = LLMSettings(Environments.GEMINI)

    # ------------------------------------------------------------------
    # PACKAGE / SETTINGS / MODELS commands (settings-only, no OCR work).
    # ------------------------------------------------------------------

    @app.command(rich_help_panel="Package")
    def update_package() -> None:
        """Reinstall google-genai + json-repair."""
        _install()

    @app.command(rich_help_panel="Settings")
    def set_api_key(api_key: Annotated[str, typer.Argument(help="API Key for Gemini")]) -> None:
        llm_api.api_key = api_key

    @app.command(rich_help_panel="Settings")
    def show_settings() -> None:
        llm_api.show_settings()

    @app.command()
    def check_valid_key() -> None:
        return llm_api.check_valid_key()

    @app.command()
    def show_models() -> None:
        return llm_api.show_models()

    @app.command()
    def show_modeldetails(model: str):
        details = llm_api.show_modeldetails(model)
        print(details)
        return details

    @app.command()
    def check_model(model: Annotated[str, typer.Argument(help="Gemini model name")]) -> None:
        llm_api.check_model(model)

    @app.command()
    def set_model(model: Annotated[str, typer.Argument(help="Gemini model name")]) -> None:
        llm_api.model = model

    @app.command()
    def show_model() -> None:
        print(f" Current model: {llm_api.model}")
        return llm_api.model

    # ------------------------------------------------------------------
    # OCR commands. Thin wrappers over PagePlusOCRPipeline.
    # ------------------------------------------------------------------

    def _collect_images(inputs: List[str], extensions: List[ImageExtension]) -> List[Path]:
        images: List[Path] = []
        for raw in inputs:
            p = Path(raw)
            if p.is_file():
                images.append(p)
            else:
                for ext in extensions:
                    images.extend(p.glob(f'*{ext.value}'))
        return images

    def _collect_xml_files(paths: List[str]) -> List[Path]:
        xml_paths: List[Path] = []
        for raw in paths:
            p = Path(raw)
            if p.is_file():
                xml_paths.append(p)
            else:
                xml_paths.extend(p.glob('*.xml'))
        return xml_paths

    def _pipeline(
        task_mode: TaskMode,
        *,
        calls_per_minute: int,
        thinking_budget: int,
        max_concurrency: int,
    ) -> PagePlusOCRPipeline:
        spec = spec_from_gemini_settings(
            llm_api,
            calls_per_minute=calls_per_minute,
            thinking_budget=thinking_budget,
        )
        spec.execution = ExecutionStrategy.WHOLE_PAGE
        return PagePlusOCRPipeline.from_spec(
            spec,
            task_mode=task_mode,
            retry_policy=RetryPolicy(max_attempts=3),
            max_concurrency=max_concurrency,
        )

    def _write_xml(xml_content: str, image_path: Path, outputdir: Optional[str]) -> Path:
        base_dir = Path(outputdir) if outputdir else image_path.parent
        out_path = base_dir / "page" / image_path.with_suffix('.xml').name
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(xml_content, encoding='utf-8')
        print(f"[green]Wrote PAGE XML to: {out_path}[/green]")
        return out_path

    def _write_json(result, image_path: Path, outputdir: Optional[str]) -> Optional[Path]:
        if result is None or result.structured is None:
            return None
        base_dir = Path(outputdir) if outputdir else image_path.parent
        out_path = base_dir / "json" / image_path.with_suffix('.json').name
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(json.dumps(result.structured, indent=4, ensure_ascii=False),
                            encoding='utf-8')
        return out_path

    @app.command()
    @profile('gemini-ocr')
    def ocr(
        inputs: Annotated[List[str], typer.Argument(exists=True, help="Image files or folders.",
                                                    callback=transform_inputs)] = None,
        outputdir: Annotated[str, typer.Option(help="Output directory.")] = None,
        image_extensions: Annotated[List[ImageExtension],
                                    typer.Option(help="Image extensions to glob.",
                                                 case_sensitive=False)] = ['.png', '.jpg', '.jpeg', '.tif', '.tiff'],
        task_mode: Annotated[TaskMode, typer.Option(help="Which PAGE-XML-aware workflow to run.",
                                                    case_sensitive=False)] = TaskMode.LAYOUT_AND_TEXT,
        calls_per_minute: Annotated[int, typer.Option(help="Rate limit per minute.")] = 150,
        thinking_budget: Annotated[int, typer.Option(help="Thinking budget in tokens (0 = off).")] = 0,
        create_page: Annotated[bool, typer.Option(help="Write PAGE XML alongside JSON.")] = True,
        profile: Annotated[str, typer.Option(help="Profile tag for analytics.")] = '',
        profilelevel: Annotated[List[ProfileLevel],
                                typer.Option(help="Profiling levels.")] = ("stats", "params", "analytics", "summary"),
        dry_run: Annotated[bool, typer.Option(help="Do not write any files.")] = False,
    ):
        """OCR one or more images. Default mode is ``layout_and_text`` (image -> coords + text)."""
        ocr.profile = ProfileFnRet()
        ocr.profile.name = profile
        ocr.profile.dir = Path(inputs[0]).absolute() if inputs else ''
        ocr.profile.stats = {'pages': 0, 'lines': 0}

        images_paths = _collect_images(inputs or [], image_extensions)
        if not images_paths:
            raise FileNotFoundError('No image files found in input directory')

        pipeline = _pipeline(task_mode,
                             calls_per_minute=calls_per_minute,
                             thinking_budget=thinking_budget,
                             max_concurrency=1)

        if 'params' in profilelevel:
            ocr.profile.params = {
                'model': llm_api.model,
                'task_mode': task_mode.value,
                'backend': 'gemini',
            }

        documents = [PagePlusDocumentPage(image_path=p) for p in images_paths]
        outputs = pipeline.ocr_pages(documents, continue_on_error=True)

        for out in outputs:
            if out.error:
                print(f"[red]Failed: {out.document.image_path}: {out.error}[/red]")
                continue
            ocr.profile.stats['pages'] += 1
            if not dry_run:
                _write_json(out.ocr_result, out.document.image_path, outputdir)
                if create_page and out.xml_content:
                    _write_xml(out.xml_content, out.document.image_path, outputdir)

    @app.command()
    def table_recognition(
        inputs: Annotated[List[str], typer.Argument(exists=True, help="Image files.",
                                                    callback=transform_inputs)],
        outputdir: Annotated[str, typer.Option(help="Output directory.")] = None,
        snippet_region: Annotated[str, typer.Option(help="Region ID to crop before processing.")] = None,
        create_page: Annotated[bool, typer.Option(help="Write PAGE XML.")] = True,
        thinking_budget: Annotated[int, typer.Option(help="Thinking tokens.")] = 0,
        dry_run: Annotated[bool, typer.Option()] = False,
    ):
        """Extract table structure from images using the Gemini table-recognition stage."""
        from pageplus.utils.llm.table_recognition import TableRecognitionStage

        stage = TableRecognitionStage(llm_api)
        for image_path in map(Path, inputs):
            print(f"Processing {image_path}...")
            region_polygon = None
            xml_path = None
            if snippet_region:
                xml_path = image_path.parent / "page" / image_path.with_suffix('.xml').name
                if not xml_path.exists():
                    xml_path = image_path.with_suffix('.xml')
                if xml_path.exists():
                    page = Page(xml_path)
                    target = None
                    for region in (page.regions.tableregions or []) + (page.regions.textregions or []):
                        if region.get_id() == snippet_region:
                            target = region
                            break
                    if target is not None:
                        coords_str = target.xml_element.find(f"{{{page.ns}}}Coords").get("points")
                        if coords_str:
                            from shapely.geometry import Polygon as ShapelyPolygon
                            pts = [tuple(map(int, pt.split(','))) for pt in coords_str.split()]
                            region_polygon = ShapelyPolygon(pts)

            tables = stage.extract_tables(image_path, region_polygon, thinking_budget)
            print(f"Extracted {len(tables)} tables.")

            if create_page and not dry_run:
                out_xml = Path(outputdir) / image_path.with_suffix('.xml').name if outputdir else image_path.with_suffix('.xml')
                if out_xml.exists():
                    page = Page(out_xml)
                    stage.table_json_to_page_xml(tables, page)
                    page.save_xml(out_xml)
                    print(f"Saved to {out_xml}")
                else:
                    print(f"[yellow]No existing PAGE XML at {out_xml}; skipping table merge.[/yellow]")

    @app.command()
    def ocr_multithread(
        inputs: Annotated[List[str], typer.Argument(exists=True, help="Image files or folders.",
                                                    callback=transform_inputs)],
        outputdir: Annotated[str, typer.Option(help="Output directory.")] = None,
        image_extension: Annotated[str, typer.Option(help="Image extension when 'inputs' is a folder.")] = '.jpg',
        task_mode: Annotated[TaskMode, typer.Option(help="Task mode to run.",
                                                    case_sensitive=False)] = TaskMode.LAYOUT_AND_TEXT,
        create_page: Annotated[bool, typer.Option()] = True,
        recognize_level: Annotated[RecognizeLevel, typer.Option(case_sensitive=False)] = RecognizeLevel.TextRegion,
        multi_stage: Annotated[bool, typer.Option(help="Run text_correction after layout_and_text.")] = False,
        jobs: Annotated[int, typer.Option()] = 4,
        calls_per_minute: Annotated[int, typer.Option()] = 150,
        dry_run: Annotated[bool, typer.Option()] = False,
        overwrite: Annotated[bool, typer.Option()] = True,
        thinking_budget: Annotated[int, typer.Option()] = 0,
    ):
        """Concurrent OCR over many images. Semaphore-bounded (``jobs``) async calls replace the old ThreadPoolExecutor."""
        images_paths: List[Path] = []
        for raw in inputs:
            p = Path(raw)
            if p.is_file():
                images_paths.append(p)
            else:
                images_paths.extend(p.glob(f'*{image_extension}'))
        if not images_paths:
            raise FileNotFoundError('No image files found in input directory')

        pipeline = _pipeline(task_mode,
                             calls_per_minute=calls_per_minute,
                             thinking_budget=thinking_budget,
                             max_concurrency=jobs)

        documents: List[PagePlusDocumentPage] = []
        for img in images_paths:
            base = Path(outputdir) if outputdir else img.parent
            out_file = base / "json" / img.with_suffix('.json').name
            if not overwrite and out_file.exists():
                print(f"Skipping {img}: {out_file} exists.")
                continue
            documents.append(PagePlusDocumentPage(image_path=img))

        print(f"Processing {len(documents)} images with {llm_api.model} (mode={task_mode.value})")
        outputs = asyncio.run(pipeline.aocr_pages(documents, continue_on_error=True))

        produced_xmls: List[Path] = []
        all_usage = []
        for idx, out in enumerate(outputs, 1):
            if out.error:
                print(f"[red]Failed {out.document.image_path}: {out.error}[/red]")
                continue
            all_usage.append(out.ocr_result.usage if out.ocr_result else {})
            if not dry_run:
                _write_json(out.ocr_result, out.document.image_path, outputdir)
                if create_page and out.xml_content:
                    produced_xmls.append(
                        _write_xml(out.xml_content, out.document.image_path, outputdir))
            print(f"[green]Done {out.document.image_path}[/green] ({idx}/{len(outputs)})")

        if multi_stage and produced_xmls:
            print(f"[cyan]Running text_correction over {len(produced_xmls)} produced XMLs...[/cyan]")
            reocr_multithread(
                xml_files=[str(p) for p in produced_xmls],
                image_files=[str(img) for img in images_paths],
                outputdir=outputdir,
                jobs=jobs,
                calls_per_minute=calls_per_minute,
                thinking_budget=thinking_budget,
                dry_run=dry_run,
                overwrite=overwrite,
            )

        return all_usage

    @app.command()
    def reocr_multithread(
        xml_files: Annotated[List[str], typer.Argument(exists=True, help="PAGE-XML files with existing text.")],
        image_files: Annotated[List[str], typer.Option(help="Corresponding image files.")] = None,
        image_folder: Annotated[str, typer.Option(help="Folder with images if image_files not given.")] = None,
        same_names: Annotated[bool, typer.Option(help="Match images by XML basename.")] = False,
        outputdir: Annotated[str, typer.Option(help="Unused; kept for backwards compatibility.")] = None,
        task_mode: Annotated[TaskMode, typer.Option(help="Task mode -- text_correction by default.",
                                                    case_sensitive=False)] = TaskMode.TEXT_CORRECTION,
        update_page: Annotated[bool, typer.Option(help="Persist the mutated PAGE XML.")] = True,
        recognize_level: Annotated[RecognizeLevel, typer.Option(case_sensitive=False)] = RecognizeLevel.TextRegion,
        update_elements: Annotated[List[UpdateElements], typer.Option(case_sensitive=False)] = [UpdateElements.TEXT, UpdateElements.TAGS],
        jobs: Annotated[int, typer.Option()] = 4,
        calls_per_minute: Annotated[int, typer.Option()] = 150,
        thinking_budget: Annotated[int, typer.Option()] = 0,
        dry_run: Annotated[bool, typer.Option()] = False,
        overwrite: Annotated[bool, typer.Option()] = True,
    ):
        """Re-OCR (default) or refine layout on pre-segmented PAGE-XML pages.

        ``task_mode`` picks the semantics:

        * ``text_correction`` (default)  : keep coords, correct text per line.
        * ``text_only``                  : keep coords, transcribe fresh.
        * ``layout_correction``          : keep text, refine coords.
        """
        if task_mode not in (TaskMode.TEXT_CORRECTION, TaskMode.TEXT_ONLY, TaskMode.LAYOUT_CORRECTION):
            raise typer.BadParameter(
                "reocr_multithread only accepts correction task modes; use 'ocr' for layout_and_text.")

        xml_paths = _collect_xml_files(xml_files)
        if not xml_paths:
            raise FileNotFoundError('No XML files found in input directory')

        documents: List[PagePlusDocumentPage] = []
        xml_by_name = {p.name: p for p in xml_paths}
        if image_files:
            for raw in image_files:
                p = Path(raw)
                targets = [p] if p.is_file() else list(p.glob('*.*'))
                for img in targets:
                    xml = xml_by_name.get(img.with_suffix('.xml').name)
                    if xml is not None:
                        documents.append(PagePlusDocumentPage(
                            image_path=img, page=Page(xml), output_xml_path=xml))
        else:
            if not image_folder:
                raise typer.BadParameter("Either image_files or image_folder must be provided")
            folder = Path(image_folder)
            if not folder.exists():
                raise FileNotFoundError(f"Image folder not found: {folder}")
            for xml in xml_paths:
                page = Page(xml)
                image_filename = (xml.with_suffix('.jpg').name if same_names
                                  else page.imageFilename())
                img_path = find_image(image_filename, folder)
                if img_path is None:
                    print(f"[yellow]No image for {xml.name}; skipping.[/yellow]")
                    continue
                documents.append(PagePlusDocumentPage(
                    image_path=img_path, page=page, output_xml_path=xml))

        if not documents:
            raise FileNotFoundError('No image/XML pairs resolved')

        pipeline = _pipeline(task_mode,
                             calls_per_minute=calls_per_minute,
                             thinking_budget=thinking_budget,
                             max_concurrency=jobs)

        print(f"Processing {len(documents)} XML files with {llm_api.model} (mode={task_mode.value})")
        outputs = asyncio.run(pipeline.aocr_pages(documents, continue_on_error=True))

        all_usage = []
        for idx, out in enumerate(outputs, 1):
            if out.error:
                print(f"[red]Failed {out.document.image_path}: {out.error}[/red]")
                continue
            all_usage.append(out.ocr_result.usage if out.ocr_result else {})
            if update_page and not dry_run and out.document.output_xml_path and out.page is not None:
                out.page.save_xml(out.document.output_xml_path)
                print(f"[green]Updated {out.document.output_xml_path}[/green] ({idx}/{len(outputs)})")

        return all_usage


if __name__ == "__main__":
    app()
