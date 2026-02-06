import subprocess
import json
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from importlib import util
from pathlib import Path
from threading import Lock
from typing import List
from enum import Enum

import typer
from rich import print
from typing_extensions import Annotated

from pageplus.utils.constants import ProfileLevel, ImageExtension, RecognizeLevel, UpdateElements
from pageplus.utils.fs import transform_inputs
from pageplus.utils.image import get_image
from pageplus.utils.profile import profile, ProfileFnRet
from pageplus.utils.io import gemini2d_to_page, segmentation_to_page
from pageplus.utils.fs import find_image
from pageplus.models.page import Page


app = typer.Typer()


def _install() -> None:
    """
    Before llm can be used, please use this install command
    to install litellm!
    """
    subprocess.check_call([sys.executable, "-m", "pip",
                          "install", "-I", "google-genai"])
    subprocess.check_call([sys.executable, "-m", "pip",
                          "install", "-I", "json-repair"])


if (spec := util.find_spec('google')) is None:

    @app.command()
    def install() -> None:
        """
        Before gemini can be used, please use this install command
        to install google-genai lib!
        """
        _install()

else:

    from pageplus.utils.constants import Environments
    from pageplus.utils.workspace import Workspace
    from pageplus.utils.llm.api import GEMINIAPI

    import json_repair
    from google.genai import types

    llm_workspace = Workspace(Environments.GEMINI)
    llm_api = GEMINIAPI(Environments.GEMINI)

    # PACKAGE

    @app.command(rich_help_panel="Package")
    def update_package() -> None:
        """
        Updates litellm by the BerriAI team!
        """
        _install()

    # SETTINGS

    @app.command(rich_help_panel="Settings")
    def set_api_key(api_key: Annotated[str, typer.Argument(
            help="API Key for the provider")]) -> None:
        """
        Set the API Key for the provider
        Returns:
        None
        """
        llm_api.api_key = api_key

    @app.command(rich_help_panel="Settings")
    def show_settings() -> None:
        """
        Print your current settings from the .env file
        Returns:
        None
        """
        llm_api.show_settings()

    @app.command()
    def check_valid_key() -> None:
        return llm_api.check_valid_key()

    # MODELS

    @app.command()
    def show_models() -> None:
        return llm_api.show_models()

    @app.command()
    def show_modeldetails(model: str):
        details = llm_api.show_modeldetails(model)
        print(details)
        return details

    @app.command()
    def check_model(model: Annotated[str, typer.Argument(
            help="Set model for LLM Provider")]) -> None:
        llm_api.check_model(model)

    @app.command()
    def set_model(model: Annotated[str, typer.Argument(
            help="Set model for LLM Provider")]) -> None:
        llm_api.model = model

    @app.command()
    def show_model() -> None:
        print(f" Current model: {llm_api.model}")
        return llm_api.model

    def ocr_settings(ctx: typer.Context, param: typer.CallbackParam, value):
        model, _, _, _ = llm_api.model, llm_api.api_key, llm_api.api_base_url, llm_api.provider
        match param.name:
            case "api_base_url" if (value and value != llm_api.api_base_url):
                llm_api.api_base_url = model
            case "model_name" if (value and value != llm_api.model):
                llm_api.model = value
            case _:
                pass
        return None

    def preprocess_json(data, image):
        """
            Reads JSON bounding box data, calculates absolute coordinates,
            and splits multi-line text boxes vertically.

            Args:
                data (List[dict]): JSON object
                image (Image): Image object

            Returns:
                list: A list of dictionaries, where each dictionary represents
                      a single line of text and contains 'line_text' and
                      'line_bbox_abs' (absolute pixel coordinates [xmin, ymin, xmax, ymax]).
                      Returns an empty list if errors occur.
            """

        processed_lines = []
        # Adjust these keys based on your actual JSON structure
        bbox_key = 'box_2d'  # CHANGE if your bbox key is different
        text_key = 'text'  # CHANGE if your text key is different
        text_subkeys = ['text_content', 'label', 'label_content']
        img_width, img_height = image.size
        for i, entry in enumerate(data):
            try:
                # --- 4. Get Relative Bbox and Text ---
                relative_bbox = entry.get(bbox_key)
                # Default to empty string if no text
                text = entry.get(text_key, "")
                if text == "":
                    for subkey in text_subkeys:
                        if subkey in entry.keys():
                            text = entry.get(subkey, "")
                            break

                if not relative_bbox or len(relative_bbox) != 4:
                    print(
                        f"Warning: Skipping entry {i} due to missing or invalid bbox: {relative_bbox}")
                    continue

                xmin_rel, ymin_rel, xmax_rel, ymax_rel = relative_bbox

                # --- 5. Calculate Absolute Bbox ---
                from math import ceil
                xmin_abs = ceil(xmin_rel * img_width / 1000)
                ymin_abs = ceil(ymin_rel * img_height / 1000)
                xmax_abs = ceil(xmax_rel * img_width / 1000)
                ymax_abs = ceil(ymax_rel * img_height / 1000)

                original_box_height_abs = ymax_abs - ymin_abs

                # --- 6. Split Text by Newlines ---
                lines = text.split('\n')
                num_lines = len(lines)

                if num_lines == 0:  # Should not happen with split, but safety check
                    continue
                if original_box_height_abs < 0:
                    print(
                        f"Warning: Skipping entry {i} due to negative box height: {relative_bbox}")
                    continue

                # --- 7. Calculate Bbox for Each Line ---
                if num_lines == 1:
                    # Only one line, use the original absolute bbox
                    processed_lines.append({
                        'line_text': lines[0],
                        'line_bbox_abs': [xmin_abs, ymin_abs, xmax_abs, ymax_abs],
                        'original_entry_index': i
                    })
                else:
                    # Multiple lines, divide the original box height
                    # Avoid division by zero if height is zero
                    line_box_height = (
                        original_box_height_abs /
                        num_lines) if original_box_height_abs > 0 else 0

                    for line_index, line_text in enumerate(lines):
                        line_ymin = ymin_abs + line_index * line_box_height
                        line_ymax = line_ymin + line_box_height
                        # Ensure ymax doesn't exceed original box due to float precision
                        # or zero height case
                        if line_index == num_lines - 1:
                            line_ymax = ymax_abs  # Last line ends exactly at original ymax

                        processed_lines.append({
                            'line_text': line_text,
                            'line_bbox_abs': [xmin_abs, ceil(line_ymin), xmax_abs, ceil(line_ymax)],
                            'original_entry_index': i,
                            'line_index': line_index
                        })

            except KeyError as e:
                print(f"Warning: Skipping entry {i} due to missing key: {e}")
            except Exception as e:
                print(
                    f"Warning: Skipping entry {i} due to unexpected error: {e}")

        return processed_lines

    @app.command()
    @profile('gemini-ocr')
    def ocr(inputs: Annotated[List[str],
                              typer.Argument(exists=True,
                                             help="Paths to the image files to be checked.",
                                             callback=transform_inputs)] = None,
            outputdir: Annotated[str,
                                 typer.Option(help="Path to the output directory where the text files will be saved. "
                                              "If not specified, the output will be created "
                                              "in the image directory.")] = None,
            image_extensions: Annotated[List[ImageExtension],
                                        typer.Option(help="Image file extensions to try (only active with 'same_names')",
                                                     case_sensitive=False)] = ['.png',
                                                                               '.jpg',
                                                                               '.jpeg',
                                                                               '.tif',
                                                                               '.tiff'],
            calls_per_minute: Annotated[int,
                                        typer.Option(help="API call rate limit per minute")] = 150,
            create_page: Annotated[bool,
                                   typer.Option(help="Tries to create a PAGE XML file from the JSON output.")] = True,
            profile: Annotated[str,
                               typer.Option(help="Profile function with tag (default:'' no profiling active.")] = '',
            profilelevel: Annotated[List[ProfileLevel],
                                    typer.Option(help="Level of profiling. Options: 'stats' (always true), 'params', 'results', 'analytics', 'summary'")] = ("stats",
                                                                                                                                                             "params",
                                                                                                                                                             "analytics",
                                                                                                                                                             "summary"),
            dry_run: Annotated[bool,
                               typer.Option(help="If True, the function will not write any files.")] = False):
        """
        OCR with the existing layout information. Existing text will be overwritten.
        """
        # API details
        # Turn profiling on
        ocr.profile = ProfileFnRet()
        ocr.profile.name = profile
        ocr.profile.dir = Path(inputs[0]).absolute() if len(inputs) > 0 else ''
        ocr.profile.stats = {'pages': 0, 'lines': 0}
        system_prompt = (
            """**Role:** You are a hyper-precise Optical Character Recognition (OCR) engine.
**Task:** Process the provided image and extract absolutely all discernible textual content, no matter how small or isolated.
**Accuracy:** Prioritize extreme accuracy and completeness. Your primary directive is to detect and transcribe *every* visible textual element. This explicitly includes:
    *   Single, isolated characters (alphanumeric, e.g., 'A', '1').
    *   Single, isolated symbols and punctuation (e.g., '-', '_', '.', ',', '*', '$', '%', '+', '=', '/', '\\', '©', '®', '™', and any other Unicode characters).
    *   Fragmented or partially obscured characters/symbols.
    *   Separate the fraction from the number before it with a space.
**Contextual Sensitivity:** Pay **critical attention** to structured layouts like tables, forms, lists, and diagrams. Ensure that the content within **every distinct area** (like table cells, form fields) is extracted, *even if that content is solely a single character or symbol* (e.g., a hyphen '-' used as a placeholder or connector in a table cell). Do not dismiss small marks if they represent textual information.
**Output Format:** Generate a JSON output containing a list of detected text objects.
**JSON Object Structure:** Each object in the list must represent a single detected text line and contain the following key-value pairs:
    *   `"box_2d"`: A list of four integers representing the bounding box coordinates of the detected text line in the format `[x_min, y_min, x_max, y_max]`.
    *   `"text_content"`: A string containing the exact text transcribed from the bounding box. Preserve case, spacing, and all characters precisely as detected.
    *   `"region"`: An integer representing the logical block or paragraph number this text line belongs to. Text lines visually grouped together (like in a paragraph or a single table cell's content if multi-line) should share the same region number. Start numbering regions from 1.Try to find meaningful paragraph/regions.
    *   `"type"`: One of the following contextual roles or styles of the line: "heading", "header", "paragraph", "table-header-{Nr.}", "table-column-{Nr.}", "page-number", "marginalia", "footnote", "drop-capital", "toc", "music, "chem", "advert", "map", "maths", "graphic", "image"
**Granularity:** Operate at the highest possible granularity. If a single character or symbol exists independently in a location (like a hyphen in an otherwise empty table cell), it MUST be detected and reported as its own text object (or as part of the cell's content if appropriate for the region grouping).
**Strictness:** Adhere strictly to the specified JSON structure and content requirements. Do not add extra keys, omit required keys, or deviate from the requested format. Report everything detected.""")

        user_prompt = ("<|input|>\n")
        if 'params' in profilelevel:
            ocr.profile.params = {
                'model': llm_api.model,
                'api_base': llm_api.api_base_url,
                'prompts': {
                    'system': system_prompt,
                    'user': user_prompt}}
        # Read XML
        images_paths = []
        for image_path in map(Path, inputs):
            if image_path.is_file():
                images_paths.append(image_path)
            else:
                # Try each extension
                for ext in image_extensions:
                    images_paths.extend(image_path.glob(f'*{ext}'))
        # Raise error if no xml files are found
        if not images_paths:
            raise FileNotFoundError('No images files found in input directory')
        request_timestamps = []
        for image_path in images_paths:
            image, image_format = get_image(image_path)
            # text_dict = {}
            # page_metrics = []
            # Find Textlines
            now = time.time()
            # Remove timestamps older than 60 seconds
            request_timestamps = [
                t for t in request_timestamps if now - t < 60]
            if len(request_timestamps) >= calls_per_minute:
                wait_time = 60 - (now - request_timestamps[0])
                print(
                    f"[red]Rate limit reached.[/red] Waiting {wait_time:.2f} seconds...")
                time.sleep(wait_time)
            # Add the current timestamp
            request_timestamps.append(time.sleep(time.time()))
            try:
                file_upload = llm_api.client().files.upload(file=image_path)

                response = llm_api.client().models.generate_content(
                    model=llm_api.model,
                    contents=[
                        types.Part.from_uri(
                            file_uri=file_upload.uri,
                            mime_type=file_upload.mime_type,
                        ),
                        user_prompt,
                    ],
                    config=types.GenerateContentConfig(
                        temperature=0,
                        response_mime_type="application/json",
                        system_instruction=system_prompt,
                    ),
                )
                try:
                    usage = response.usage_metadata
                    print(usage)
                    data = json_repair.repair_json(
                        response.text, return_objects=True)
                    if not dry_run:
                        outputdir = Path(
                            outputdir) if outputdir else image_path.parent
                        output_path = outputdir.joinpath(
                            "json/").joinpath(image_path.with_suffix('.json').name)
                        output_path.parent.mkdir(exist_ok=True, parents=True)
                        with output_path.open("w", encoding="utf-8") as jf:
                            json.dump(data, jf, indent=4, ensure_ascii=False)
                        if create_page:
                            xml_content = gemini2d_to_page(data, image_path, use_bbox_fallback=use_bbox_fallback)
                            output_path = outputdir.joinpath(
                                "page/").joinpath(image_path.with_suffix('.xml').name)
                            output_path.parent.mkdir(
                                exist_ok=True, parents=True)
                            try:
                                with open(output_path, 'w', encoding='utf-8') as f_out:
                                    f_out.write(xml_content)
                                print(
                                    f"Successfully wrote PAGE XML to: {output_path}")
                            except Exception as e:
                                print(
                                    f"Error writing PAGE XML file '{output_path}': {e}")
                except BaseException:
                    print("[red] Error: No valid output[/red]")
            except Exception as e:
                print("An error occurred during completion:", e)
                continue
lock = Lock()
timestamps = []


def rate_limit(calls_per_minute):
    with lock:
        now = time.time()
        while timestamps and now - timestamps[0] > 60:
            timestamps.pop(0)
        if len(timestamps) >= calls_per_minute:
            sleep_time = 60 - (now - timestamps[0])
            print(
                f"[red]Rate limit reached.[/red] Waiting {sleep_time:.2f} seconds...")
            time.sleep(sleep_time)
        timestamps.append(time.time())


def ocr_single_image(
        image_path,
        outputdir,
        system_prompt,
        user_prompt,
        calls_per_minute,
        create_page,
        dry_run=False,
        retries=1,
        overwrite=True,
        thinking_budget=0,
        use_bbox_fallback=None):
    attempt = 0
    while attempt <= retries:
        rate_limit(calls_per_minute)
        try:
            print(f"Processing: {image_path} (Attempt {attempt + 1})")

            outputdir_path = Path(
                outputdir) if outputdir else image_path.parent
            output_path = outputdir_path / "json"
            output_path.mkdir(parents=True, exist_ok=True)
            output_file = output_path / image_path.with_suffix('.json').name
            if not overwrite and output_file.exists():
                print(
                    f"Skipping {image_path} because {output_file} already exists.\n")
                return image_path, True, None, None, None

            image, image_format = get_image(image_path)

            file_upload = llm_api.client().files.upload(file=image_path)
            response = llm_api.client().models.generate_content(
                model=llm_api.model,
                contents=[
                    types.Part.from_uri(
                        file_uri=file_upload.uri,
                        mime_type=file_upload.mime_type,
                    ),
                    user_prompt,
                ],
                config=types.GenerateContentConfig(
                    temperature=0.000001,
                    top_p=0.000001,
                    top_k=1,
                    seed=123,
                    response_mime_type="application/json",
                    system_instruction=system_prompt,
                    thinking_config=types.ThinkingConfig(
                        include_thoughts=False if thinking_budget == 0 else True,
                        thinking_budget=thinking_budget)),
            )
            data = json_repair.repair_json(response.text, return_objects=True)
            usage = response.usage_metadata
            print(f'Successfully OCR: {image_path.name}')
            xml_output_path = None
            if not dry_run:
                with output_file.open("w", encoding="utf-8") as jf:
                    json.dump(data, jf, indent=4, ensure_ascii=False)
                if create_page:
                    if isinstance(data, dict) and "regions" in data:
                        xml_content = segmentation_to_page(data, image_path)
                    else:
                        xml_content = gemini2d_to_page(data, image_path, use_bbox_fallback=use_bbox_fallback)
                    output_path = outputdir_path.joinpath(
                        "page/").joinpath(image_path.with_suffix('.xml').name)
                    output_path.parent.mkdir(exist_ok=True, parents=True)
                    try:
                        with open(output_path, 'w', encoding='utf-8') as f_out:
                            f_out.write(xml_content)
                        print(f"Successfully wrote PAGE XML to: {output_path}")
                        xml_output_path = output_path
                    except Exception as e:
                        print(
                            f"Error writing PAGE XML file '{output_path}': {e}")

            return image_path, True, None, usage, xml_output_path

        except Exception as e:
            print(f"An error occurred processing {image_path}: {e}")
            attempt += 1
            if attempt <= retries and e.code != 429:
                print("[yellow]Retrying after 60 seconds...[/yellow]")
                time.sleep(60)
            else:
                if e.code == 429:
                    print(
                        "[red]Rate limit reached. Or this model is not supported for free quota tier.[/red]")
                return image_path, False, str(e), None, None
    return None


@app.command()
def table_recognition(
    inputs: Annotated[List[str], typer.Argument(exists=True, help="Paths to the image files to be checked.", callback=transform_inputs)],
    outputdir: Annotated[str, typer.Option(help="Path to the output directory.")] = None,
    snippet_region: Annotated[str, typer.Option(help="Region ID to use as snippet (if processing a specific region).")] = None,
    create_page: Annotated[bool, typer.Option(help="Create PAGE XML file.")] = True,
    thinking_budget: Annotated[int, typer.Option(help="Thinking budget in tokens.")] = 0,
    dry_run: Annotated[bool, typer.Option(help="Perform a dry run.")] = False
):
    """
    Extract tables from images or regions using Gemini.
    """
    from pageplus.utils.llm.table_recognition import TableRecognitionStage
    from pageplus.models.page import Page
    from pageplus.utils.image import get_image # Re-import if needed or use existing
    
    stage = TableRecognitionStage(llm_api)
    
    for image_path in map(Path, inputs):
        print(f"Processing {image_path}...")
        
        region_polygon = None
        if snippet_region:
            # Need XML to find region polygon
            xml_path = image_path.parent / "page" / image_path.with_suffix('.xml').name
            if not xml_path.exists():
                # Try sibling
                xml_path = image_path.with_suffix('.xml')
            
            if xml_path.exists():
                page = Page(xml_path)
                # Find region by ID
                # Page methods usually iterate regions, let's assume we can get it
                # Logic to find region by ID:
                target_region = None
                for region in page.regions.tableregions + page.regions.textregions:
                    if region.get_id() == snippet_region:
                        target_region = region
                        break
                
                if target_region:
                    # coords points
                    # We need shapely Polygon
                    # region.get_coordinates(returntype="polygon")?
                    # Page object has get_coordinates but Region object?
                    # Let's check Region class or just parse points string
                    coords_str = target_region.xml_element.find(f"{{{page.ns}}}Coords").get("points")
                    if coords_str:
                        from shapely.geometry import Polygon as ShapelyPolygon
                        points = []
                        for pt in coords_str.split():
                            x, y = map(int, pt.split(','))
                            points.append((x, y))
                        region_polygon = ShapelyPolygon(points)
                else:
                    print(f"[red]Region {snippet_region} not found in {xml_path}[/red]")
            else:
                 print(f"[red]XML not found for {image_path} to extract snippet {snippet_region}[/red]")

        tables = stage.extract_tables(image_path, region_polygon, thinking_budget)
        print(f"Extracted {len(tables)} tables.")
        
        if create_page and not dry_run:
            # If we used an existing XML for snippet, we should update it? 
            # Or create new one if starting from image?
            # Command argument says "create_page".
            
            if snippet_region and 'xml_path' in locals() and xml_path.exists():
                # Update existing XML
                page = Page(xml_path) # Reload to be safe
                pass
            else:
                # Create new XML
                # We need a basic Page object. 
                # Can we use gemini2d_to_page logic or manually create?
                # For now let's reuse Page class to load a template or create fresh?
                # Page class requires a filename.
                # If we want to create a new XML from scratch, we might need a template.
                # But typically we process existing PAGE XMLs in this pipeline or create new one.
                # Let's assume we create a minimal PAGE XML structure if it doesn't exist.
                
                out_xml_path = image_path.with_suffix('.xml')
                if outputdir:
                     out_xml_path = Path(outputdir) / image_path.with_suffix('.xml').name
                
                if out_xml_path.exists():
                    page = Page(out_xml_path)
                else:
                    # Create blank page XML
                    # We don't have a helper for blank page in imports seen so far, 
                    # but maybe we can use helper or just skip if no XML exists for now, 
                    # or better: rely on user providing XML if they want to update.
                    # As a fallback, try to create from image size.
                    img, _ = get_image(image_path)
                    w, h = img.size
                    
                    # Manual XML strings creation as fallback
                    # But better to use Page object if possible.
                    # Let's just warn if no XML to update for now, or assume usage on existing project.
                    print("[yellow]Creating new XML not fully supported without template, trying to use input image name as base.[/yellow]")
                    # For execution safety, let's SKIP creating specific new XML logic here unless required. 
                    # But we must save the tables.
                    # Let's try to pass a dummy path to Page() if it supports creating new?
                    # Page(filepath) loads it.
                     
            if 'page' in locals():
                 stage.table_json_to_page_xml(tables, page)
                 
                 # Save
                 out_xml_path = image_path.with_suffix('.xml')
                 if outputdir:
                      out_xml_path = Path(outputdir) / image_path.with_suffix('.xml').name
                      
                 page.save_xml(out_xml_path)
                 print(f"Saved to {out_xml_path}")

@app.command()
def ocr_multithread(inputs: Annotated[List[str], typer.Argument(exists=True)],
                    outputdir: Annotated[str, typer.Option()] = None,
                    system_prompt: Annotated[str, typer.Option()] = None,
                    image_extension: Annotated[str, typer.Option()] = '.jpg',
                    create_page: Annotated[bool, typer.Option()] = True,
                    recognize_level: Annotated[RecognizeLevel, typer.Option(
                        case_sensitive=False, help="Level to recognize.")] = RecognizeLevel.TextRegion,
                    multi_stage: Annotated[bool, typer.Option(help="Run ReOCR stage after OCR.")] = False,
                    jobs: Annotated[int, typer.Option()] = 4,
                    calls_per_minute: Annotated[int, typer.Option()] = 150,
                    dry_run: Annotated[bool, typer.Option()] = False,
                    overwrite: Annotated[bool, typer.Option()] = True,
                    thinking_budget: Annotated[int, typer.Option(help="Thinking budget in tokens.(0 = no thinking)")] = 0):
    system_prompt = system_prompt if system_prompt else (
        """**Role:** You are a hyper-precise Optical Character Recognition (OCR) engine.
    **Task:** Process the provided image and extract absolutely all discernible textual content, no matter how small or isolated.
    **Accuracy:** Prioritize extreme accuracy and completeness. Your primary directive is to detect and transcribe *every* visible textual element. This explicitly includes:
        *   Single, isolated characters (alphanumeric, e.g., 'A', '1').
        *   Single, isolated symbols and punctuation (e.g., '-', '_', '.', ',', '*', '$', '%', '+', '=', '/', '\\', '©', '®', '™', and any other Unicode characters).
        *   Fragmented or partially obscured characters/symbols.
        *   Separate the fraction from the number before it with a space.
    **Contextual Sensitivity:** Pay **critical attention** to structured layouts like tables, forms, lists, and diagrams. Ensure that the content within **every distinct area** (like table cells, form fields) is extracted, *even if that content is solely a single character or symbol* (e.g., a hyphen '-' used as a placeholder or connector in a table cell). Do not dismiss small marks if they represent textual information.
    **Output Format:** Generate a JSON output containing a list of detected text objects and preserve reading order.
    **JSON Object Structure:** Each object in the list must represent a single detected text line and contain the following key-value pairs:
        *   `"box_2d"`: A list of four integers representing the bounding box coordinates (as small as possible, containing all the text) of the detected text line in the format `[y_min, x_min, y_max, x_max]`.
        *   `"text_content"`: A string containing the exact text transcribed from the bounding box. Preserve case, spacing, and all characters precisely as detected.
        *   `"region"`: An integer representing the logical block or paragraph number this text line belongs to. Text lines visually grouped together (like in a paragraph or a single table cell's content if multi-line) should share the same region number. Start numbering regions from 1.Try to find meaningful paragraph/regions.
        *   `"type"`: One of the following contextual roles or styles of the line: "heading", "header", "paragraph", "table-header-{Nr.}", "table-column-{Nr.}", "page-number", "marginalia", "footnote", "drop-capital", "toc", "music, "chem", "advert", "map", "maths", "graphic", "image"
        *   `"style"`: (Optional) Select if it apply to the style of the font in the line: "handwriting", "bold", "italic"
    **Granularity:** Operate at the highest possible granularity. If a single character or symbol exists independently in a location (like a hyphen in an otherwise empty table cell), it MUST be detected and reported as its own text object (or as part of the cell's content if appropriate for the region grouping).
    **Strictness:** Adhere strictly to the specified JSON structure and content requirements. Do not add extra keys, omit required keys, or deviate from the requested format. Report everything detected.""")
    user_prompt = ("<|input|>\n")
    images_paths = []
    for image_path in map(Path, inputs):
        print(image_path)
        if image_path.is_file():
            images_paths.append(image_path)
        else:
            images_paths.extend(image_path.glob(f'*{image_extension}'))

    if not images_paths:
        raise FileNotFoundError('No image files found in input directory')
    all_usage = []
    count = 0
    xml_files_for_reocr = []
    print(f"Processing {len(images_paths)} images with {llm_api.model}")
    with ThreadPoolExecutor(max_workers=jobs) as executor:
        future_to_image = {
            executor.submit(
                ocr_single_image,
                image_path,
                outputdir,
                system_prompt,
                user_prompt,
                calls_per_minute,
                create_page,
                dry_run,
                overwrite=overwrite,
                thinking_budget=thinking_budget
            ): image_path for image_path in images_paths
        }

        for future in as_completed(future_to_image):
            image_path = future_to_image[future]
            path, success, error, usage, xml_output_path = future.result()
            all_usage.append(usage)
            count += 1
            if success:
                print(f"[green]Successfully processed: {path}[/green]")
                if xml_output_path:
                    xml_files_for_reocr.append(str(xml_output_path))
            else:
                print(f"[red]Failed processing {path}: {error}[/red]")
            print("Total tokens: ", getattr(usage, 'total_token_count', 0))
            print(f"Current count: {count}/{len(images_paths)}")
    return all_usage


def extract_text_from_xml(xml_path: Path) -> str:
    """Extract text content from a PAGE XML file."""
    try:
        import xml.etree.ElementTree as ET
        tree = ET.parse(xml_path)
        root = tree.getroot()

        # Extract text from TextLine elements
        text_lines = []
        for textline in root.findall(
                './/{http://schema.primaresearch.org/PAGE/gts/pagecontent/2013-07-15}TextLine'):
            text = textline.find(
                './/{http://schema.primaresearch.org/PAGE/gts/pagecontent/2013-07-15}TextEquiv/{http://schema.primaresearch.org/PAGE/gts/pagecontent/2013-07-15}Unicode')
            if text is not None and text.text:
                text_lines.append(text.text.strip())

        return "\n".join(text_lines)
    except Exception as e:
        print(f"Error extracting text from XML {xml_path}: {e}")
        return ""


def reocr_single_image(
        image_path: Path,
        xml_path: Path,
        outputdir: Path,
        system_prompt: str,
        calls_per_minute: int,
        update_page: bool,
        thinking_budget: int,
        recognize_level: RecognizeLevel,
        update_elements: List[UpdateElements],
        dry_run: bool = False,
        retries: int = 1,
        overwrite: bool = True):
    """Process a single image with XML context."""
    attempt = 0
    while attempt <= retries:
        rate_limit(calls_per_minute)
        try:
            print(
                f"Processing: {image_path} with context from {xml_path} (Attempt {attempt + 1})")
            outputdir_path = Path(
                outputdir) if outputdir else image_path.parent
            output_path = outputdir_path / "json"
            output_path.mkdir(parents=True, exist_ok=True)
            output_file = output_path / image_path.with_suffix('.json').name

            if not overwrite and output_file.exists():
                print(
                    f"Skipping {image_path} because {output_file} already exists.\n")
                return image_path, True, None, None

            # Extract text from XML
            page = Page(xml_path)
            # Delete existing TextRegion text content
            page.delete_textlevel('TextRegion')
            # Get the page number from the filename# Create JSON file
            json_data = {'regions': []}

            for region in page.get_ordered_regions(
                    region_types=('TextRegion')):
                textlines = region.textlines
                if textlines is None:
                    continue
                json_data['regions'].append({
                    'id': region.get_id(),
                    'type': region.get_tag(),
                    'textlines': []
                })
                for line in textlines:
                    text = line.get_text()
                    if text != '':
                        json_data['regions'][-1]['textlines'].append({
                            'id': line.get_id(),
                            'text_content': text,
                            'type': line.get_tag(),
                        })

            if json_data['regions'] is None:
                print(f"No regions found in {xml_path}")
                return image_path, False, "No regions found in {xml_path}", None

            user_prompt = json.dumps(json_data, indent=4, ensure_ascii=False)
            image, image_format = get_image(image_path)
            file_upload = llm_api.client().files.upload(file=image_path)

            if "2.5" in llm_api.model:
                response = llm_api.client().models.generate_content(
                    model=llm_api.model,
                    contents=[
                        types.Part.from_uri(
                            file_uri=file_upload.uri,
                            mime_type=file_upload.mime_type,
                        ),
                        user_prompt,
                    ],
                    config=types.GenerateContentConfig(
                        temperature=0.000001,
                        top_p=0.000001,
                        top_k=1,
                        seed=123,
                        response_mime_type="application/json",
                        system_instruction=system_prompt,
                        thinking_config=types.ThinkingConfig(
                            include_thoughts=False if thinking_budget == 0 else True,
                            thinking_budget=thinking_budget)),
                )
            else:
                response = llm_api.client().models.generate_content(
                    model=llm_api.model,
                    contents=[
                        types.Part.from_uri(
                            file_uri=file_upload.uri,
                            mime_type=file_upload.mime_type,
                        ),
                        user_prompt,
                    ],
                    config=types.GenerateContentConfig(
                        temperature=0.000001,
                        top_p=0.000001,
                        top_k=1,
                        seed=123,
                        response_mime_type="application/json",
                        system_instruction=system_prompt,
                    ),
                )

            data = json_repair.repair_json(response.text, return_objects=True)
            usage = response.usage_metadata
            print(f'Successfully re-OCR: {image_path.name}')
            if not dry_run:
                with output_file.open("w", encoding="utf-8") as jf:
                    json.dump(data, jf, indent=4, ensure_ascii=False)
                if update_page:
                    print("Updating PAGE XML...")
                    print(data)
                    for updated_region in data['regions']:
                        region = page.get_region_by_id(updated_region['id'])
                        if region is None:
                            print(
                                f"Region {updated_region['id']} not found in {xml_path}")   
                            continue
                        # region.set_tag(tag=updated_region['type'])
                        for updated_line in updated_region['textlines']:
                            textline = region.get_textline_by_id(
                                updated_line['id'])
                            if textline is None:
                                print(
                                    f"Textline {updated_line['id']} not found in {xml_path}")
                                continue
                            if updated_line.get('text_content_content', False):
                                updated_line['text_content'] = updated_line['text_content_content'].strip(
                                )
                            elif updated_line.get('text', False):
                                updated_line['text_content'] = updated_line['text'].strip(
                                )
                            text = updated_line.get('text_content', '')
                            # Limit text to 500 characters (Loop effect)
                            if len(text) > 350:
                                print(f"Textline {updated_line['id']} is too long: {text}")
                                text = textline.get_text()
                                updated_line['type'] = 'missed'
                            if UpdateElements.TEXT in update_elements:
                                textline.update_text(text)
                            if UpdateElements.TAGS in update_elements:
                                textline.set_tag(
                                    tag=updated_line.get(
                                        'type', 'paragraph'))

                    page.save_xml(xml_path)
                    print(f"Successfully updated PAGE XML: {xml_path}")

            return image_path, True, None, usage

        except Exception as e:
            print(f"An error occurred processing {image_path}: {e}")
            attempt += 1
            if attempt <= retries and getattr(e, 'code', None) != 429:
                print("[yellow]Retrying after 60 seconds...[/yellow]")
                time.sleep(60)
            else:
                if getattr(e, 'code', None) == 429:
                    print(
                        "[red]Rate limit reached. Or this model is not supported for free quota tier.[/red]")
                return image_path, False, str(e), None
    return None


class AdditionalCheck(str, Enum):
    TYPE = "type"
    STYLE = "style"
    REGION = "region"
    READING_ORDER = "reading_order"


@app.command()
def reocr_multithread(
    xml_files: Annotated[List[str], typer.Argument(exists=True, help="Paths to the XML files containing previous OCR results.")],
    image_files: Annotated[List[str], typer.Option(help="Optional paths to the image files. If not provided, will look in image_folder.")] = None,
    image_folder: Annotated[str, typer.Option(help="Folder to look for images if image_files not provided.")] = None,
    same_names: Annotated[bool, typer.Option(help="Use XML filename to find images instead of imageFilename from PAGE XML.")] = False,
    additional_checks: Annotated[List[AdditionalCheck], typer.Option(help="Additional checks to perform: type, style, region, and/or reading_order.")] = None,
    outputdir: Annotated[str, typer.Option(help="Path to the output directory.")] = None,
    system_prompt: Annotated[str, typer.Option(help="System prompt for the OCR model.")] = None,
    update_page: Annotated[bool, typer.Option(help="Updates PAGE XML output.")] = True,
    recognize_level: Annotated[RecognizeLevel, typer.Option(
        case_sensitive=False, help="Level to recognize.")] = RecognizeLevel.TextRegion,
    update_elements: Annotated[List[UpdateElements], typer.Option(
        case_sensitive=False, help="Elements to update.")] = [UpdateElements.TEXT, UpdateElements.TAGS],
    jobs: Annotated[int, typer.Option(help="Number of parallel jobs.")] = 4,
    calls_per_minute: Annotated[int, typer.Option(help="API call rate limit per minute.")] = 150,
    thinking_budget: Annotated[int, typer.Option(help="Thinking budget in tokens.(0 = no thinking)")] = 0,
    dry_run: Annotated[bool, typer.Option(help="Perform a dry run without writing files.")] = False,
    overwrite: Annotated[bool, typer.Option(help="Overwrite existing output files.")] = True
):
    """Perform OCR on images using existing XML files as context for improved accuracy."""
    # Convert additional_checks to a set for efficient lookups
    # checks = set(additional_checks) if additional_checks else set()
    system_prompt = """**Role:** You are an advanced Optical Character Recognition (OCR) and Document Layout Analysis (DLA) engine. Your specific function is to meticulously correct errors in provided JSON data by comparing it against a corresponding visual document.
    **Primary Task:**
    Given a visual input and a JSON dictionary detailing text regions and lines extracted from a previous OCR pass, your objective is to:
    1.  **Identify Incorrect/Incomplete Lines:** For each `textline` in the input JSON, compare its `text_content` with the actual text visible in the corresponding area of the visual input. Identify all input `textlines` where the `text_content` is erroneous (e.g., misread characters, missing words, extra characters) or incomplete.
    2.  **Correct Text and Attributes:** For each identified line:
        *   **Correct `text_content`:** Transcribe the text from the visual input with extreme precision.
        *   **Update `type``:** Re-evaluate and assign the correct `type` (for both the line and its parent region) based on visual analysis of the *corrected* content and its layout.
        *   **Preserve Line `id`:** The original `id` of the modified `textline` from the input JSON *must* be preserved.
    3.  **Generate non-filtered updated JSON:** Updated JSON dictionary. Each such region in the output must *only* contain these specific modified `textlines`.
    **Correction & Transcription Directives:**
    *   **Extreme Accuracy:** Transcribe *every* visible textual element for the lines requiring correction. This includes:
        *   Single, isolated characters (alphanumeric, e.g., 'A', '1').
        *   Single, isolated symbols and punctuation (e.g., '-', '_', '.', ',', '*', '$', '%', '+', '=', '/', '\\', '©', '®', '™', and all other Unicode characters).
        *   Fragmented or partially obscured characters/symbols relevant to the line.
        *   Ensure a space separates a whole number from its following fraction (e.g., "1 1/2", not "11/2").
    *   **No Normalization:** Transcribe historical glyphs, archaic spellings, or unique character variations *precisely as they appear*. Do not modernize or standardize them. (e.g. 'ſ' ,'⸗')
    *   **Contextual Layout Awareness:** Pay critical attention to structured layouts (tables, forms, lists, diagrams). For any `textline` needing correction within such structures:
        *   Ensure content within *every distinct cell, field, or demarcated area* is accurately extracted.
        *   Do not dismiss small marks (e.g., a hyphen '-' in a table cell, a checkmark) if they represent textual information relevant to a line being corrected.
    *   **Case and Spacing:** Preserve original casing and spacing (including multiple spaces if visually significant) meticulously.
    **Output JSON Specification:**
    *   **Root:** An updated JSON object with a single key `regions`, whose value is an array `[...]`.
    *   **Region Object:**
        *   `id` (String): **MUST BE PRESERVED AND UNCHANGED. HIGH PRIORITY.**
        *   `type` (String): The visually determined `type` of the *output* region, reflecting the dominant content of the *modified lines* it contains. Update based on corrected content and visual layout. Examples: "paragraph", "heading", "table", "list", "caption", "form-field-group", "column".
        *   `textlines` (Array): An array of modified and original `textline` objects.
    *   **Textline Object (within `textlines` array):**
        *   `id` (String): **MUST BE PRESERVED AND UNCHANGED. HIGH PRIORITY.**
        *   `text_content` (String): The fully corrected text for the line, adhering to all transcription directives.
        *   `type` (String): The visually determined contextual `type` of the *line itself* ("heading", "header", "paragraph", "table-header-1", "table-cell", "list-item", "page-number", "footnote", "caption-line"). This should be updated based on the corrected content and its visual role.
    **Important:**
    *   * Check every textline for correctness. *
    *   * Output modified and unmodified textlines. Not allowed to remove any textlines. *
    """

    # Process input paths
    xml_paths = []
    for xml_path in map(Path, xml_files):
        if xml_path.is_file():
            xml_paths.append(xml_path)
        else:
            xml_paths.extend(xml_path.glob('*.xml'))

    if not xml_paths:
        raise FileNotFoundError('No XML files found in input directory')

    # Get image paths
    image_xml_paths = []
    xml_names = {xml_path.name: xml_path for xml_path in xml_paths}
    if image_files:
        # Use provided image files
        for image_path in map(Path, image_files):
            if image_path.is_file():
                if xml_names.get(
                        image_path.with_suffix('.xml').name,
                        None) is not None:
                    image_xml_paths.append(
                        (image_path, xml_names.get(
                            image_path.with_suffix('.xml').name)))
            else:
                for image_path in image_path.glob('*.*'):
                    if xml_names.get(
                            image_path.with_suffix('.xml').name,
                            None) is not None:
                        image_xml_paths.append(
                            (image_path, xml_names.get(
                                image_path.with_suffix('.xml').name)))
    else:
        # Look for images in image_folder
        if not image_folder:
            raise ValueError(
                "Either image_files or image_folder must be provided")

        image_folder = Path(image_folder)
        if not image_folder.exists():
            raise FileNotFoundError(f"Image folder not found: {image_folder}")

        # Match images to XML files
        for xml_file in xml_paths:
            # Find image (same name or image filename from page-xml file)
            page = Page(xml_file)
            imageFilename = page.imageFilename(
            ) if not same_names else xml_file.with_suffix('.jpg').name
            imageDir = xml_file
            for _ in range(0, len(image_folder.split('../'))):
                imageDir = imageDir.parent
                imageDir = imageDir.joinpath(
                    './' + image_folder.rsplit('./')[0])
            imagePath = find_image(imageFilename, imageDir)
            if not imagePath:
                continue
            image_xml_paths.append((imagePath, xml_file))
    if not image_xml_paths:
        raise FileNotFoundError('No image files found')
    all_usage = []
    count = 0
    print(f"Processing {len(image_xml_paths)} images with {llm_api.model}")
    with ThreadPoolExecutor(max_workers=jobs) as executor:
        future_to_image = {
            executor.submit(
                reocr_single_image,
                image_path=image_path,
                xml_path=xml_path,
                outputdir=Path(outputdir) if outputdir else None,
                system_prompt=system_prompt,
                calls_per_minute=calls_per_minute,
                update_page=update_page,
                thinking_budget=thinking_budget,
                recognize_level=recognize_level,
                update_elements=update_elements,
                dry_run=dry_run,
                overwrite=overwrite): (
                image_path,
                xml_path) for (
                image_path,
                xml_path) in image_xml_paths}

        for future in as_completed(future_to_image):
            image_path, xml_path = future_to_image[future]
            path, success, error, usage = future.result()
            all_usage.append(usage)
            count += 1
            if success:
                print(f"[green]Successfully processed: {path}[/green]")
            else:
                print(f"[red]Failed processing {path}: {error}[/red]")
            print("Total tokens: ", getattr(usage, 'total_token_count', 0))
            print(f"Progress state: {count}/{len(image_xml_paths)}")

    return all_usage


if __name__ == "__main__":
    app()
