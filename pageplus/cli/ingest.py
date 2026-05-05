from pageplus.utils.io import gemini2d_to_page, load_gemini2d_json
from pathlib import Path
from typing import Optional

import typer
from typing_extensions import Annotated

from pageplus.utils.fs import (transform_input)
from pageplus.utils.io_churro import (
    churro_page_to_page_xml,
    load_churro_json,
)

app = typer.Typer()


@app.command()
def gemini2d(
    json: Annotated[str, typer.Argument(
        exists=True,
        help="Path to the Gemini 2d JSON file containing line data (relative coords 0-1000).",
        callback=transform_input,  # Keep if you need path expansion/validation
    )],
    image: Annotated[Path, typer.Argument(
        exists=True,
        help="Path to image.",
        resolve_path=True
    )],  # Default to checking alongside JSON
    dry_run: Annotated[bool, typer.Option(
        help="If True, the function will not write any files.")] = False,
    use_bbox_fallback: Annotated[bool, typer.Option(
        help="Use previous bbox with +30px offset for entries without bbox. Default from settings.")] = None
):
    """
    Converts line data from JSON files (relative 0-1000 bboxes) to PAGE XML.
    Assumes corresponding image has the same base name as the JSON file.
    Handles multi-line text entries by splitting bounding boxes vertically.
    """
    # Use a more robust way to collect files if needed (e.g., handling
    # directories in inputs)
    json_file = Path(json)
    if not (json_file.is_file() and json_file.suffix.lower() == '.json'):
        raise FileExistsError

    print(f"--- Processing: {json_file.name} ---")
    # --- Find Corresponding Image ---
    # Fallback: check next to JSON file
    if not image.exists():
        raise FileExistsError(f"Warning: Image '{image}' not found. Skipping.")

    # Read JSON
    data = load_gemini2d_json(json_file)

    # Process JSON and Get Line Data (using updated function)
    # Pass use_bbox_fallback parameter - will use global settings if None
    xml_content = gemini2d_to_page(data, image, use_bbox_fallback=use_bbox_fallback)

    if not dry_run:
        try:
            with open(json_file.with_suffix('.xml'), 'w', encoding='utf-8') as f_out:
                f_out.write(xml_content)
            print(
                f"Successfully wrote PAGE XML to: {json_file.with_suffix('.xml')}")
        except Exception as e:
            print(
                f"Error writing PAGE XML file '{json_file.with_suffix('.xml')}': {e}")


@app.command()
def churro(
    json_path: Annotated[str, typer.Argument(
        exists=True,
        help="Path to a Churro document JSON (DocumentOCRResult, DocumentPage, or a list of pages).",
        callback=transform_input,
    )],
    image_dir: Annotated[Optional[Path], typer.Option(
        exists=True, file_okay=False,
        help="Directory to resolve image filenames against. If omitted, images are looked up next to the JSON file.",
    )] = None,
    output_dir: Annotated[Optional[Path], typer.Option(
        file_okay=False,
        help="Directory where PAGE-XML files will be written. Defaults to the JSON's parent directory.",
    )] = None,
    text_delimiter: Annotated[str, typer.Option(
        help="Line delimiter used to split the Churro page text into PAGE TextLines.",
    )] = "\n",
    dry_run: Annotated[bool, typer.Option(
        help="If True, do not write any files.",
    )] = False,
):
    """
    Ingest a Churro JSON document and emit one PAGE-XML per Churro page.

    Accepts any of the Churro output shapes:
      - ``DocumentOCRResult`` (``{source_type, metadata, pages: [...]}``)
      - a bare list of ``DocumentPage`` objects
      - a single ``DocumentPage`` object

    Per-line coordinates are approximated (Churro only emits page-level text).
    Run a layout tool on the generated PAGE-XML if you need exact geometry.
    """
    json_file = Path(json_path)
    if not json_file.is_file() or json_file.suffix.lower() != ".json":
        raise FileExistsError(f"Expected a .json file, got: {json_file}")

    document = load_churro_json(json_file)
    if not document.pages:
        print(f"No pages found in {json_file.name}, nothing to do.")
        return

    out_root = output_dir if output_dir is not None else json_file.parent
    img_root = image_dir if image_dir is not None else json_file.parent

    if not dry_run:
        out_root.mkdir(parents=True, exist_ok=True)

    for page in document.pages:
        image_hint = None
        for key in ("image_filename", "image_path", "source_path", "path"):
            value = (page.metadata or {}).get(key)
            if value:
                image_hint = Path(str(value)).name
                break
        image_path = None
        if image_hint:
            candidate = img_root / image_hint
            if candidate.exists():
                image_path = candidate

        base_name = json_file.stem
        if len(document.pages) > 1:
            base_name = f"{json_file.stem}_p{page.page_index:04d}"
        xml_path = out_root / f"{base_name}.xml"

        xml_content = churro_page_to_page_xml(
            page,
            image_path=image_path,
            text_delimiter=text_delimiter,
        )

        if dry_run:
            print(f"[dry-run] Would write {xml_path}")
            continue
        try:
            xml_path.write_text(xml_content, encoding="utf-8")
            print(f"Wrote PAGE XML: {xml_path}")
        except Exception as exc:
            print(f"Error writing PAGE XML '{xml_path}': {exc}")


if __name__ == "__main__":
    app()
