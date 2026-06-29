from pathlib import Path
from typing import Annotated, Optional
import typer
import asyncio
import json
from rich import print
import pandas as pd

from pageplus.utils.iiif.manifest import IIIFManifest

app = typer.Typer()

"""
Thanks to Segolene Albouy for the iiif-download tool.
https://github.com/Segolene-Albouy/iiif-download/

MIT License

Copyright (c) 2024 Segolene-Albouy

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
"""


@app.command()
def download(
    manifest_url: Annotated[str, typer.Argument(help="IIIF manifest URL to download")],
    output_dir: Annotated[Optional[Path], typer.Option("--output-dir", "-o", help="Directory to save the images.")] = None,
    prefix: Annotated[str, typer.Option(help="Prefix for the downloaded image filenames.")] = "",
    leading_zeros: Annotated[int, typer.Option(help="Number of leading zeros for the downloaded image filenames.")] = 4,
    page_range: Annotated[Optional[str], typer.Option("--page-range", "-r", help="Page range to download, e.g., '1-5,7,9-12'.")] = None,
    filename_strategy: Annotated[str, typer.Option(help="Filename strategy: 'label', 'id', or 'index'.")] = "label",
    keep_original_size: Annotated[bool, typer.Option("--keep-original-size/--no-keep-original-size", help="Keep original image size (full resolution).")] = True,
    max_dim: Annotated[Optional[int], typer.Option("--max-dim", help="Maximum dimension for resized images.")] = None,
    min_dim: Annotated[Optional[int], typer.Option("--min-dim", help="Minimum dimension for resized images.")] = None,
    batch_size: Annotated[int, typer.Option("--batch-size", help="Number of images to download in parallel.")] = 25,
    overwrite: Annotated[bool, typer.Option("--overwrite/--no-overwrite", help="Overwrite existing image files.")] = False,
):
    """
    Download all images from a IIIF manifest.
    """
    manifest = IIIFManifest(
        url=manifest_url,
        save_dir=output_dir,
        prefix=prefix,
        leading_zeros=leading_zeros,
        page_range=page_range,
        filename_strategy=filename_strategy,
        keep_original_size=keep_original_size,
        max_dim=max_dim,
        min_dim=min_dim,
        batch_size=batch_size,
        overwrite=overwrite,
    )
    manifest.download()


@app.command(name="get-resources")
def get_resources(
    manifest_url: Annotated[str, typer.Argument(help="IIIF manifest URL to inspect")],
    output_json: Annotated[bool, typer.Option("--json", help="Output as JSON.")] = False,
):
    """
    Inspect a IIIF manifest and show image resources.
    """
    manifest = IIIFManifest(url=manifest_url)

    async def _load_manifest():
        await manifest.load()

    asyncio.run(_load_manifest())

    resources = manifest.get_resources()

    if not resources:
        print("No resources found.")
        return

    data = []
    for i, resource in enumerate(resources):
        service = manifest.get_img_service(resource)
        data.append({
            "index": i + 1,
            "label": resource.get("label", ""),
            "id": service,
            "type": resource.get("@type", resource.get("type")),
            "format": resource.get("format"),
            "height": resource.get("height"),
            "width": resource.get("width"),
        })

    if output_json:
        print(json.dumps(data, indent=4))
    else:
        df = pd.DataFrame(data)
        print("--- Image Resources ---")
        print(df)
