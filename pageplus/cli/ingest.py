from pageplus.utils.io import gemini2d_to_page, load_gemini2d_json
from pathlib import Path

import typer
from typing_extensions import Annotated

from pageplus.utils.fs import (transform_input)

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
        help="If True, the function will not write any files.")] = False
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
    xml_content = gemini2d_to_page(data, image)

    if not dry_run:
        try:
            with open(json_file.with_suffix('.xml'), 'w', encoding='utf-8') as f_out:
                f_out.write(xml_content)
            print(
                f"Successfully wrote PAGE XML to: {json_file.with_suffix('.xml')}")
        except Exception as e:
            print(
                f"Error writing PAGE XML file '{json_file.with_suffix('.xml')}': {e}")


if __name__ == "__main__":
    app()
