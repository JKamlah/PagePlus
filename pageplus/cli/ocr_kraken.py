import json
import re
import subprocess
import tempfile
from collections import Counter
from pathlib import Path
from typing import List, Annotated, Optional
import pickle
import base64

import typer
from rich import print
from dotenv import dotenv_values, set_key
import asyncio

from pageplus.io.logger import logging
from pageplus.models.page import Page
from pageplus.utils.constants import ProfileLevel, ImageExtension
from pageplus.utils.fs import collect_xml_files, find_image, transform_output
from pageplus.utils.fs import transform_inputs
from pageplus.utils.image import get_image, crop_image_by_polygon
from pageplus.utils.profile import profile, ProfileFnRet
from pageplus.utils.envs import get_env_path
import pageplus

app = typer.Typer(
    no_args_is_help=True,
)


def get_kraken_template_path() -> Path:
    """Returns the path to the default pageplus kraken template."""
    return Path(pageplus.__file__).parent / "utils" / "kraken" / "template" / "pageplus"


async def run_async_subprocess(cmd: List[str], timeout: int) -> tuple[int, str, str]:
    """Run a subprocess asynchronously."""
    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE
    )

    try:
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout)
        return proc.returncode, stdout.decode(errors='ignore'), stderr.decode(errors='ignore')
    except asyncio.TimeoutError:
        try:
            proc.kill()
        except OSError:
            pass  # process already terminated
        await proc.wait()
        return -1, "", f"Process timed out after {timeout} seconds."


async def run_kraken_segment_batch_external_async(
    python_path: Path,
    regions_data: dict,
    seg_model_path: Path,
    rec_model_path: Optional[Path] = None,
    device: str = 'cpu',
    text_direction: str = 'horizontal-lr',
) -> dict:
    """
    Run Kraken segmentation on a batch of regions using an external Python environment.
    Optionally, run recognition on the found lines.

    Args:
        python_path (Path): Path to the Python executable in the Kraken environment.
        regions_data (dict): Dictionary with region IDs as keys and image paths as values.
        seg_model_path (Path): Path to the segmentation model.
        rec_model_path (Optional[Path], optional): Path to the recognition model. Defaults to None.
        device (str, optional): Device to run on. Defaults to 'cpu'.
        text_direction (str, optional): Text direction. Defaults to 'horizontal-lr'.

    Returns:
        dict: A dictionary containing the segmentation and OCR results for each region.
    """
    script_content = '''
import sys
import json
import pickle
import base64
from pathlib import Path
from PIL import Image
from kraken.lib import models
from kraken import blla, rpred
from kraken.containers import BaselineLine, Segmentation

results = {}
try:
    # Load data from stdin
    input_data = pickle.loads(base64.b64decode(sys.stdin.read()))
    regions_data = input_data['regions_data']
    seg_model_path = Path(input_data['seg_model_path'])
    rec_model_path = Path(input_data['rec_model_path']) if input_data['rec_model_path'] else None
    device = input_data['device']
    text_direction = input_data['text_direction']

    # Load models once
    from kraken.lib.vgsl import TorchVGSLModel
    seg_model = TorchVGSLModel.load_model(seg_model_path)
    rec_model = None
    if rec_model_path and rec_model_path.exists():
        rec_model = models.load_any(rec_model_path, device=device)

    for region_id, region_info in regions_data.items():
        image_path = Path(region_info['image_path'])
        image = Image.open(image_path)

        # Segmentation
        segmentation_container = blla.segment(image, model=seg_model, text_direction=text_direction, device=device)

        region_results = {'lines': []}

        if rec_model:
            # Recognition
            it = rpred.rpred(rec_model, image, segmentation_container, device=device)
            for pred in it:
                region_results['lines'].append({
                    'boundary': pred.boundary,
                    'baseline': pred.baseline,
                    'text': pred.prediction
                })
        else:
            # Just segmentation
            for line in segmentation_container.lines:
                region_results['lines'].append({
                    'boundary': line.boundary,
                    'baseline': line.baseline,
                    'text': ''
                })

        results[region_id] = region_results
except Exception as e:
    print(f"Error in Kraken script: {e}", file=sys.stderr)
    sys.exit(1)

print(json.dumps(results))
'''
    input_data = {
        'regions_data': {k: {'image_path': str(v['image_path'])} for k, v in regions_data.items()},
        'seg_model_path': str(seg_model_path),
        'rec_model_path': str(rec_model_path) if rec_model_path else None,
        'device': device,
        'text_direction': text_direction,
    }
    encoded_data = base64.b64encode(pickle.dumps(input_data))

    try:
        proc = await asyncio.create_subprocess_exec(
            str(python_path), "-c", script_content,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )
        stdout, stderr = await asyncio.wait_for(proc.communicate(input=encoded_data), timeout=600)

        if proc.returncode == 0 and stdout:
            return json.loads(stdout.decode('utf-8'))
        else:
            error_msg = stderr.decode('utf-8')
            logging.error(f"Kraken segment batch failed with return code {proc.returncode}: {error_msg}")
            raise Exception(f"Kraken script failed: {error_msg}")
    except asyncio.TimeoutError:
        logging.error("Kraken segment batch process timed out.")
        raise
    except Exception as e:
        logging.error(f"Error running Kraken segment batch: {e}")
        raise


async def run_kraken_ocr_batch_external_async(
    python_path: Path,
    lines_data: dict,
    model_path: Path,
    pad: int = 16
) -> dict:
    """
    Run Kraken OCR on a batch of lines using an external Python environment asynchronously.
    The model is loaded only once.

    Args:
        python_path (Path): Path to the Python executable in the Kraken environment.
        lines_data (dict): A dictionary containing information about the lines to be processed.
                           Example: {line_id: {'image_path': Path, 'baseline_coords': list, 'textline_coords': list}}
        model_path (Path): Path to the Kraken model file.
        pad (int, optional): Padding for OCR. Defaults to 16.

    Returns:
        dict: A dictionary containing the OCR results.
              Example: {line_id: {'text': str, 'confidences': list}}
    """
    script_content = '''
import sys
import json
import pickle
import base64
from pathlib import Path
from PIL import Image
from kraken.lib import models
from kraken import rpred
from kraken.containers import BaselineLine, Segmentation

try:
    # Read parameters from stdin
    input_data = pickle.loads(base64.b64decode(sys.stdin.read()))

    lines_data = input_data['lines_data']
    model_path = Path(input_data['model_path'])
    pad = input_data['pad']

    # Load model once
    model = models.load_any(model_path)

    results = {}

    for line_id, line_info in lines_data.items():
        image_path = Path(line_info['image_path'])
        baseline_coords = line_info['baseline_coords']
        textline_coords = line_info['textline_coords']

        image = Image.open(image_path)

        bll = BaselineLine(
            id=line_id,
            baseline=baseline_coords,
            boundary=textline_coords
        )
        seg = Segmentation(
            type='baselines',
            imagename=str(image_path),
            text_direction='horizontal-lr',
            script_detection=False,
            lines=[bll]
        )

        it = rpred.rpred(
            model,
            image,
            bounds=seg,
            pad=pad,
            bidi_reordering=True,
        )

        for pred in it:
            result = {
                'text': pred.prediction,
                'confidences': [float(c) for c in pred.confidences] if hasattr(pred, 'confidences') else []
            }
            results[line_id] = result
            break

    print(json.dumps(results))
except Exception as e:
    # Log exceptions to stderr for debugging
    print(f"Error in Kraken script: {e}", file=sys.stderr)
    sys.exit(1)
'''
    input_data_serializable = {
        'lines_data': {k: {**v, 'image_path': str(v['image_path'])} for k, v in lines_data.items()},
        'model_path': str(model_path),
        'pad': pad
    }

    encoded_data = base64.b64encode(pickle.dumps(input_data_serializable))

    try:
        proc = await asyncio.create_subprocess_exec(
            str(python_path), "-c", script_content,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )
        stdout, stderr = await asyncio.wait_for(proc.communicate(input=encoded_data), timeout=300)

        if proc.returncode == 0 and stdout:
            return json.loads(stdout.decode('utf-8'))
        else:
            logging.error(f"Kraken OCR batch failed with return code {proc.returncode}: {stderr.decode('utf-8')}")
            return {}
    except asyncio.TimeoutError:
        logging.error("Kraken OCR batch process timed out.")
        return {}
    except Exception as e:
        logging.error(f"Error running Kraken OCR batch: {e}")
        return {}


def get_kraken_python_path() -> Optional[Path]:
    """
    Get the configured Kraken Python environment path from .env file.

    Returns:
        Optional[Path]: Path to Python executable in Kraken environment, or None if not configured
    """
    env_values = dotenv_values(get_env_path())
    python_path = env_values.get('PAGEPLUS_KRAKEN_PYTHON_PATH', None)
    if python_path:
        path = Path(python_path)
        if path.exists():
            return path
    return None


def verify_kraken_installation(python_path: Path) -> bool:
    """
    Verify that Kraken is installed in the specified Python environment.

    Args:
        python_path: Path to Python executable

    Returns:
        bool: True if Kraken is installed, False otherwise
    """
    try:
        result = subprocess.run(
            [str(python_path), "-c", "import importlib.metadata; importlib.metadata.version('kraken')"],
            capture_output=True,
            text=True,
            timeout=10
        )
        if result.returncode == 0:
            version = result.stdout.strip()
            print(f"[green]Kraken version {version} found in environment[/green]")
            return True
        else:
            print(f"[red]Kraken not found in environment: {result.stderr}[/red]")
            return False
    except Exception as e:
        print(f"[red]Error verifying Kraken installation: {e}[/red]")
        return False


def get_kraken_executable() -> Optional[Path]:
    """
    Get the path to the kraken executable from the configured Python environment.

    Returns:
        Optional[Path]: Path to kraken executable, or None if not found
    """
    python_path = get_kraken_python_path()
    if not python_path:
        return None

    # The kraken executable should be in the same bin directory as python
    kraken_path = python_path.parent / 'kraken'

    if kraken_path.exists():
        return kraken_path

    # Try with .exe extension for Windows
    kraken_exe = python_path.parent / 'kraken.exe'
    if kraken_exe.exists():
        return kraken_exe

    return None


async def kraken_segment_cli(
    image_files: List[str],
    model_path: Path,
    output_dir: Optional[Path] = None,
    device: str = 'cpu',
    text_direction: str = 'horizontal-lr',
    jobs: int = 1,
    template: str = "pageplus",
    threads: int = 1,
    progress_callback=None
) -> dict:
    """
    Run Kraken segmentation using direct CLI calls asynchronously.

    Args:
        image_files: List of image file paths
        model_path: Path to segmentation model
        output_dir: Output directory for XML files (None = same as input)
        device: Processing device ('cpu' or 'cuda:0')
        text_direction: Text direction for segment ('horizontal-lr', 'horizontal-rl', 'vertical-lr', 'vertical-rl')
        jobs: Number of parallel jobs
        progress_callback: Callback for progress updates

    Returns:
        Dictionary with success status and results
    """
    kraken_exe = get_kraken_executable()
    if not kraken_exe:
        return {
            "success": False,
            "error": "Kraken executable not found in configured Python environment"
        }

    async def worker(image_file: str, semaphore: asyncio.Semaphore) -> tuple[str, str, str]:
        async with semaphore:
            image_path = Path(image_file)

            # Determine output path
            if output_dir:
                output_path = output_dir / image_path.with_suffix('.xml').name
                output_dir.mkdir(parents=True, exist_ok=True)
            else:
                output_path = image_path.with_suffix('.xml')

            # Build kraken command
            cmd = [str(kraken_exe)]

            if template in ["pagexml", "alto"]:
                cmd.extend(['-f', template])
            else:
                template_path = get_kraken_template_path().parent / template
                if template_path.exists():
                    cmd.extend(['-t', str(template_path)])

            if device and device != 'cpu':
                cmd.extend(['--device', device])

            cmd.extend(['--threads', str(threads)])
            cmd.extend(['-x', '-i', str(image_path), str(output_path)])
            cmd.extend(['segment', '-bl', '-i', str(model_path)])
            if text_direction:
                cmd.extend(['-d', text_direction])

            # Run command
            returncode, _, stderr = await run_async_subprocess(cmd, timeout=300)

            if progress_callback:
                progress_callback()

            if returncode == 0:
                logging.info(f"Segmented: {image_path.name}")
                return image_path.name, "success", ""
            else:
                logging.error(f"Segmentation failed for {image_path.name}: {stderr}")
                return image_path.name, "failed", stderr

    try:
        semaphore = asyncio.Semaphore(jobs)
        tasks = [worker(img_file, semaphore) for img_file in image_files]
        results = await asyncio.gather(*tasks)

        processed = sum(1 for r in results if r[1] == "success")
        failed = [r[0] for r in results if r[1] == "failed"]
        error_details = {r[0]: r[2] for r in results if r[1] == "failed"}

        return {
            "success": len(failed) == 0,
            "processed_files": processed,
            "total_files": len(image_files),
            "failed_files": failed,
            "error_details": error_details,
            "error": f"{len(failed)} file(s) failed. See details below." if failed else None
        }

    except Exception as e:
        logging.error(f"Kraken segmentation error: {e}")
        return {
            "success": False,
            "error": str(e)
        }


async def kraken_recognize_cli(
    image_files: List[str],
    model_path: Path,
    output_dir: Optional[Path] = None,
    device: str = 'cpu',
    text_direction: str = 'horizontal-tb',
    jobs: int = 1,
    template: str = "pageplus",
    threads: int = 1,
    progress_callback=None
) -> dict:
    """
    Run Kraken recognition using direct CLI calls asynchronously.
    Requires existing PAGE-XML files for the images.

    Args:
        image_files: List of image file paths
        model_path: Path to recognition model
        output_dir: Output directory for XML files (None = same as input)
        device: Processing device ('cpu' or 'cuda:0')
        text_direction: Text direction for OCR ('horizontal-tb', 'vertical-lr', 'vertical-rl')
        jobs: Number of parallel jobs
        progress_callback: Callback for progress updates

    Returns:
        Dictionary with success status and results
    """
    kraken_exe = get_kraken_executable()
    if not kraken_exe:
        return {
            "success": False,
            "error": "Kraken executable not found in configured Python environment"
        }

    no_xml = []

    async def worker(image_file: str, semaphore: asyncio.Semaphore) -> tuple[str, str, str]:
        async with semaphore:
            image_path = Path(image_file)
            xml_path = image_path.with_suffix('.xml')

            if not xml_path.exists():
                no_xml.append(image_path.name)
                logging.warning(f"No XML found for {image_path.name}, skipping...")
                if progress_callback:
                    progress_callback()
                return image_path.name, "skipped", "No XML found"

            # Determine output path
            if output_dir:
                output_path = output_dir / xml_path.name
                output_dir.mkdir(parents=True, exist_ok=True)
            else:
                output_path = xml_path

            # Build kraken command
            cmd = [str(kraken_exe)]

            if template in ["pagexml", "alto"]:
                cmd.extend(['-f', template])
            else:
                template_path = get_kraken_template_path().parent / template
                if template_path.exists():
                    cmd.extend(['-t', str(template_path)])

            if device and device != 'cpu':
                cmd.extend(['--device', device])

            cmd.extend(['--threads', str(threads)])
            cmd.extend(['-x', '-i', str(xml_path), str(output_path)])
            cmd.extend(['ocr', '-m', str(model_path)])
            if text_direction:
                cmd.extend(['-d', text_direction])

            # Run command
            returncode, _, stderr = await run_async_subprocess(cmd, timeout=600)

            if progress_callback:
                progress_callback()

            if returncode == 0:
                logging.info(f"Recognized: {image_path.name}")
                return image_path.name, "success", ""
            else:
                logging.error(f"Recognition failed for {image_path.name}: {stderr}")
                return image_path.name, "failed", stderr

    try:
        semaphore = asyncio.Semaphore(jobs)
        tasks = [worker(img_file, semaphore) for img_file in image_files]
        results = await asyncio.gather(*tasks)

        processed = sum(1 for r in results if r[1] == "success")
        failed = [r[0] for r in results if r[1] == "failed"]
        skipped = [r[0] for r in results if r[1] == "skipped"]
        error_details = {r[0]: r[2] for r in results if r[1] == "failed"}
        error_message = ""
        if failed:
            error_message += f"{len(failed)} file(s) failed."
        if skipped:
            error_message += f" {len(skipped)} file(s) skipped (no XML)."

        return {
            "success": len(failed) == 0,
            "processed_files": processed,
            "total_files": len(image_files),
            "failed_files": failed,
            "skipped_files": skipped,
            "error_details": error_details,
            "error": error_message if (failed or skipped) else None
        }

    except Exception as e:
        logging.error(f"Kraken recognition error: {e}")
        return {
            "success": False,
            "error": str(e)
        }


async def kraken_segment_and_recognize_cli(
    image_files: List[str],
    seg_model_path: Path,
    rec_model_path: Path,
    output_dir: Optional[Path] = None,
    device: str = 'cpu',
    seg_text_direction: str = 'horizontal-lr',
    rec_text_direction: str = 'horizontal-tb',
    jobs: int = 1,
    template: str = "pageplus",
    threads: int = 1,
    progress_callback=None
) -> dict:
    """
    Run Kraken segmentation and recognition in one pipeline using direct CLI calls asynchronously.

    Args:
        image_files: List of image file paths
        seg_model_path: Path to segmentation model
        rec_model_path: Path to recognition model
        output_dir: Output directory for XML files (None = same as input)
        device: Processing device ('cpu' or 'cuda:0')
        seg_text_direction: Text direction for segment
        rec_text_direction: Text direction for recognition
        jobs: Number of parallel jobs
        progress_callback: Callback for progress updates

    Returns:
        Dictionary with success status and results
    """
    kraken_exe = get_kraken_executable()
    if not kraken_exe:
        return {
            "success": False,
            "error": "Kraken executable not found in configured Python environment"
        }

    async def worker(image_file: str, semaphore: asyncio.Semaphore) -> tuple[str, str, str]:
        async with semaphore:
            image_path = Path(image_file)

            # Determine output path
            if output_dir:
                output_path = output_dir / image_path.with_suffix('.xml').name
                output_dir.mkdir(parents=True, exist_ok=True)
            else:
                output_path = image_path.with_suffix('.xml')

            # Build kraken command
            cmd = [str(kraken_exe)]

            if template in ["page", "alto"]:
                cmd.extend(['-f', template])
            else:
                template_path = get_kraken_template_path().parent / template
                if template_path.exists():
                    cmd.extend(['-t', str(template_path)])

            if device and device != 'cpu':
                cmd.extend(['--device', device])

            cmd.extend(['--threads', str(threads)])
            cmd.extend(['-x', '-i', str(image_path), str(output_path)])
            cmd.extend(['segment', '-bl', '-i', str(seg_model_path)])
            if seg_text_direction:
                cmd.extend(['-d', seg_text_direction])
            cmd.extend(['ocr', '-m', str(rec_model_path)])
            if rec_text_direction:
                cmd.extend(['-d', rec_text_direction])

            # Run command
            returncode, _, stderr = await run_async_subprocess(cmd, timeout=900)

            if progress_callback:
                progress_callback()

            if returncode == 0:
                logging.info(f"Processed: {image_path.name}")
                return image_path.name, "success", ""
            else:
                logging.error(f"Processing failed for {image_path.name}: {stderr}")
                return image_path.name, "failed", stderr

    try:
        semaphore = asyncio.Semaphore(jobs)
        tasks = [worker(img_file, semaphore) for img_file in image_files]
        results = await asyncio.gather(*tasks)

        processed = sum(1 for r in results if r[1] == "success")
        failed = [r[0] for r in results if r[1] == "failed"]
        error_details = {r[0]: r[2] for r in results if r[1] == "failed"}

        return {
            "success": len(failed) == 0,
            "processed_files": processed,
            "total_files": len(image_files),
            "failed_files": failed,
            "error_details": error_details,
            "error": f"{len(failed)} file(s) failed. See details below." if failed else None
        }

    except Exception as e:
        logging.error(f"Kraken pipeline error: {e}")
        return {
            "success": False,
            "error": str(e)
        }


@app.command()
def set_python_env(
    python_path: Annotated[Path, typer.Argument(
        help="Path to Python executable in Kraken environment (e.g., /path/to/venv/bin/python)"
    )]
) -> None:
    """
    Set the Python environment path where Kraken is installed.
    This allows using Kraken from a separate virtual environment without installing it in PagePlus.
    """
    # Verify the path exists
    if not python_path.exists():
        print(f"[red]Error: Python executable not found at {python_path}[/red]")
        raise typer.Exit(1)

    # Verify it's a Python executable
    try:
        result = subprocess.run(
            [str(python_path), "--version"],
            capture_output=True,
            text=True,
            timeout=5
        )
        if result.returncode != 0:
            print("[red]Error: Not a valid Python executable[/red]")
            raise typer.Exit(1)

        python_version = result.stdout.strip()
        print(f"[green]Found {python_version}[/green]")
    except Exception as e:
        print(f"[red]Error verifying Python executable: {e}[/red]")
        raise typer.Exit(1)

    # Verify Kraken is installed
    if not verify_kraken_installation(python_path):
        print("[yellow]Warning: Kraken is not installed in this environment.[/yellow]")
        print("[yellow]Please install Kraken in the environment first:[/yellow]")
        print(f"  {python_path} -m pip install kraken")

        continue_anyway = typer.confirm("Do you want to set this path anyway?")
        if not continue_anyway:
            raise typer.Exit(0)

    # Save to .env
    set_key(get_env_path(), 'PAGEPLUS_KRAKEN_PYTHON_PATH', str(python_path.absolute()))
    print(f"[green]Kraken Python environment set to: {python_path.absolute()}[/green]")


@app.command()
def show_python_env() -> None:
    """
    Show the currently configured Kraken Python environment path.
    """
    python_path = get_kraken_python_path()
    if python_path:
        print(f"[green]Kraken Python environment: {python_path}[/green]")
        verify_kraken_installation(python_path)
    else:
        print("[yellow]No Kraken Python environment configured.[/yellow]")
        print("[yellow]Use 'pageplus ocr-kraken set-python-env <path>' to configure.[/yellow]")


@app.command()
def clear_python_env() -> None:
    """
    Clear the configured Kraken Python environment path.
    """
    set_key(get_env_path(), 'PAGEPLUS_KRAKEN_PYTHON_PATH', '')
    print("[green]Kraken Python environment cleared[/green]")


# Check if Kraken Python environment is configured (but don't verify yet to avoid slow imports)
kraken_python_path = get_kraken_python_path()

if kraken_python_path:
    @app.command()
    @profile('kraken-segment')
    def segment(inputs: Annotated[List[str], typer.Argument(exists=True,
                help="Paths to the XML files to be processed.", callback=transform_inputs)] = None,
                image_folder: Annotated[str, typer.Option(exists=True, help="Folder to the images relative to page-xml (default same as input)")] = '.',
                outputdir: Annotated[Optional[str], typer.Option(
                          help="Filename of the output directory. If not specified, input files will be overwritten.",
                          callback=transform_output)] = None,
                seg_model_name: Annotated[str, typer.Option(help="Name of the segmentation model (should exist in Model-Directory)")] = None,
                model_dir: Annotated[Path,
                                     typer.Option(help="Directory of the models")] = None,
                rec_model_name: Annotated[Optional[str], typer.Option(help="Name of the recognition model (optional)")] = None,
                jobs: Annotated[int,
                                typer.Option(help="Number of parallel jobs for processing pages.")] = 1,
                device: Annotated[str, typer.Option(help="Device to run inference on, e.g., 'cpu' or 'cuda:0'")] = 'cpu',
                text_direction: Annotated[str,
                                          typer.Option(help="Text direction for segmentation")] = 'horizontal-lr',
                same_names: Annotated[bool,
                                      typer.Option(help="Use the page-xml filename to search for the image")] = False,
                image_extensions: Annotated[List[ImageExtension],
                                            typer.Option(help="Image file extensions to try (only with 'same_names')")] = ['.png', '.jpg', '.jpeg', '.tif', '.tiff'],
                region_tagfilter: Annotated[str,
                                            typer.Option(help="Regular expression to filter text regions by tag")] = None,
                dry_run: Annotated[bool,
                                   typer.Option(help="If True, the function will not write any files.")] = False):
        """
        Segment text regions into lines and optionally OCR them.
        This will DELETE all existing text lines within the targeted regions.
        """
        python_path = get_kraken_python_path()
        if not python_path:
            print("[red]Error: Kraken Python environment not configured.[/red]")
            raise typer.Exit(1)

        seg_model_path = model_dir.joinpath(seg_model_name if seg_model_name.endswith(('.mlmodel', '.pt')) else seg_model_name + '.mlmodel')
        if not seg_model_path.exists():
            print(f"[red]Error: Segmentation model not found at {seg_model_path}[/red]")
            raise typer.Exit(1)

        rec_model_path = None
        if rec_model_name:
            rec_model_path = model_dir.joinpath(rec_model_name if rec_model_name.endswith(('.mlmodel', '.pt')) else rec_model_name + '.mlmodel')
            if not rec_model_path.exists():
                print(f"[red]Warning: Recognition model not found at {rec_model_path}. Only segmentation will be performed.[/red]")
                rec_model_path = None

        xml_files = collect_xml_files(map(Path, inputs))
        if not xml_files:
            raise FileNotFoundError('No xml files found in input directory')

        temp_dir = tempfile.mkdtemp(prefix='pageplus_kraken_seg_')

        async def main():
            semaphore = asyncio.Semaphore(jobs)

            async def process_page(xml_file):
                async with semaphore:
                    print(f"Processing {xml_file.name}...")
                    page = Page(xml_file)

                    if not same_names:
                        image_filename = page.imageFilename()
                        image_path = find_image(image_filename, xml_file.parent / image_folder)
                    else:
                        image_path = next((p for ext in image_extensions if (p := find_image(xml_file.with_suffix(ext.value).name, xml_file.parent / image_folder))), None)
                        image_filename = image_path.name if image_path else xml_file.with_suffix(image_extensions[0].value).name

                    if not image_path:
                        print(f"Warning: Image for {xml_file.name} not found, skipping.")
                        return

                    image, _ = get_image(image_path)
                    regions_to_process = {}

                    for textregion in page.regions.textregions:
                        if region_tagfilter and not re.search(region_tagfilter, textregion.get_tag()):
                            continue

                        region_id = textregion.get_id()
                        region_snippet, bbox = crop_image_by_polygon(image, textregion.get_coordinates(returntype='mrr'))
                        if region_snippet is None:
                            continue

                        snippet_path = Path(temp_dir) / f"region_{region_id}.png"
                        region_snippet.save(snippet_path)

                        regions_to_process[region_id] = {
                            'image_path': snippet_path,
                            'region_object': textregion,
                            'bbox': bbox
                        }

                    if not regions_to_process:
                        print(f"No matching regions found in {xml_file.name}, skipping.")
                        return

                    try:
                        batch_data = {rid: {'image_path': rinfo['image_path']} for rid, rinfo in regions_to_process.items()}
                        segmentation_results = await run_kraken_segment_batch_external_async(
                            python_path, batch_data, seg_model_path, rec_model_path, device, text_direction
                        )
                        print(segmentation_results)

                        for region_id, region_result in segmentation_results.items():
                            region_info = regions_to_process[region_id]
                            region_obj = region_info['region_object']
                            min_x, min_y, _, _ = region_info['bbox']

                            # Delete old lines
                            region_obj.delete_textlines(list(range(len(region_obj.textlines))))

                            for i, line_data in enumerate(region_result.get('lines', [])):
                                new_line_id = f"{region_id}_l{i+1}"

                                abs_boundary = [(int(x + min_x), int(y + min_y)) for x, y in line_data['boundary']]
                                abs_baseline = [(int(x + min_x), int(y + min_y)) for x, y in line_data['baseline']]

                                region_obj.add_textline(
                                    new_line_id, abs_boundary, abs_baseline, line_data.get('text', '')
                                )
                                print(f"  Added line {new_line_id} to region {region_id}")

                        if not dry_run:
                            fout = xml_file if outputdir is None else Path(outputdir) / xml_file.name
                            fout.parent.mkdir(parents=True, exist_ok=True)
                            page.save_xml(fout)
                            logging.info(f"Saved updated file to {fout}")

                    except Exception as e:
                        print(f"[red]Error processing page {xml_file.name}: {e}[/red]")

            tasks = [process_page(xml_file) for xml_file in xml_files]
            await asyncio.gather(*tasks)

        try:
            asyncio.run(main())
        finally:
            import shutil
            shutil.rmtree(temp_dir, ignore_errors=True)

    @app.command()
    @profile('kraken-ocr')
    def ocr(inputs: Annotated[List[str],
                              typer.Argument(exists=True,
                                             help="Paths to the XML files to be checked.",
                                             callback=transform_inputs)] = None,
            image_folder: Annotated[str,
                                    typer.Option(exists=True,
                                                 help="Folder to the images relative to page-xml (default same as input)")] = '.',
            outputdir: Annotated[Optional[str], typer.Option(
                      help="Filename of the output directory. If not specified, input files will be overwritten.",
                      callback=transform_output)] = None,
            model_name: Annotated[str,
                                  typer.Option(help="Name of the model (should exist in Model-Directory)")] = None,
            model_dir: Annotated[Path,
                                 typer.Option(help="Directory of the model")] = None,
            jobs: Annotated[int,
                            typer.Option(help="Number of parallel jobs for OCR processing.")] = 1,
            same_names: Annotated[bool,
                                  typer.Option(help="Use the page-xml filename to search for the image (default use imageFilename from pagexml file)")] = False,
            image_extensions: Annotated[List[ImageExtension],
                                        typer.Option(help="Image file extensions to try (only active with 'same_names')",
                                                     case_sensitive=False)] = ['.png',
                                                                               '.jpg',
                                                                               '.jpeg',
                                                                               '.tif',
                                                                               '.tiff'],
            save_snippets: Annotated[bool,
                                     typer.Option(help="Save snippets (debug option)")] = False,
            text_filter: Annotated[str,
                                   typer.Option(help="A regular expression, if specific textlines should be filtered")] = None,
            region_tagfilter: Annotated[str,
                                        typer.Option(help="A regular expression, if specific textlines should be filtered")] = None,
            textline_tagfilter: Annotated[str,
                                          typer.Option(help="A regular expression, if specific textlines should be filtered")] = None,
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
        Uses Kraken from an external Python environment.
        """
        # Get the configured Kraken Python path
        python_path = get_kraken_python_path()
        if not python_path:
            print("[red]Error: Kraken Python environment not configured.[/red]")
            print("[yellow]Use 'pageplus ocr-kraken set-python-env <path>' to configure.[/yellow]")
            raise typer.Exit(1)

        # API details
        # Turn profiling on
        ocr.profile = ProfileFnRet()
        ocr.profile.name = profile
        ocr.profile.dir = Path(
            inputs[0]).absolute() if len(inputs) > 0 else ''
        ocr.profile.stats = {'pages': 0, 'lines': 0}

        # Check for dinglehopper for analytics
        from importlib import util
        if util.find_spec(
                'pageplus.utils.dinglehopper.edit_distance') is None:
            if ProfileLevel.analytics in profilelevel:
                profilelevel = list(profilelevel)
                profilelevel.remove(ProfileLevel.analytics)
            print(
                "[red]Warning:[/red] 'analytics' profiling level requires 'dinglehopper' package to be installed. "
                "It will be disabled.")
        elif 'analytics' in profilelevel:
            from pageplus.cli.dinglehopper import get_metrics, summarize_metrics

        model_name = model_name if model_name.endswith(
            '.mlmodel') else model_name + '.mlmodel'
        model_path = model_dir.joinpath(model_name)
        if 'params' in profilelevel:
            ocr.profile.params = {'model': model_path.with_suffix('').name,
                                  'jobs': jobs,
                                  'text-filter': text_filter,
                                  'region-tagfilter': region_tagfilter,
                                  'textline-tagfilter': textline_tagfilter}

        # Read XML
        xml_files = collect_xml_files(map(Path, inputs))
        # Raise error if no xml files are found
        if not xml_files:
            raise FileNotFoundError(
                'No xml files found in input directory')
        reg_filter = re.compile(
            rf"{text_filter}") if text_filter is not None else '.'
        all_diff = Counter()
        all_metrics = []

        # Create temporary directory for image snippets if needed
        temp_dir = tempfile.mkdtemp(prefix='pageplus_kraken_')

        async def main():
            nonlocal all_metrics, all_diff
            semaphore = asyncio.Semaphore(jobs)
            lock = asyncio.Lock()

            async def process_page(xml_file):
                async with semaphore:
                    print(xml_file)
                    page = Page(xml_file)
                    page.delete_textlevel('region')

                    # Find image
                    if not same_names:
                        imageFilename = page.imageFilename()
                        imagePath = find_image(imageFilename, xml_file.parent / image_folder)
                    else:
                        imagePath = next((p for ext in image_extensions if (p := find_image(xml_file.with_suffix(ext.value).name, xml_file.parent / image_folder))), None)
                        imageFilename = imagePath.name if imagePath else xml_file.with_suffix(image_extensions[0].value).name

                    if not imagePath:
                        print(f"Warning: Image {imageFilename} not found in {image_folder}")
                        return

                    imageDir = Path(xml_file).parent
                    image, _ = get_image(imagePath)
                    text_dict = {}
                    page_metrics = []

                    # Collect all lines to be processed for the current page
                    lines_to_process = {}
                    pad = 16

                    for textregion in page.regions.textregions:
                        if region_tagfilter is not None and region_tagfilter != textregion.get_tag():
                            continue

                        for line in textregion.textlines:
                            if textline_tagfilter is not None and textline_tagfilter != line.get_tag():
                                continue
                            text = line.get_text()
                            if text_filter is not None and not re.search(reg_filter, text):
                                continue

                            line_id = line.get_id()
                            image_snippet, bbox = crop_image_by_polygon(image,
                                                                        line.get_coordinates(returntype='mrr'),
                                                                        patch_size=2,
                                                                        buffer=pad,
                                                                        save_snippet=save_snippets,
                                                                        transparent_background=False,
                                                                        square_canvas=False,
                                                                        snippet_dir=imageDir.joinpath(
                                                                            imageFilename.rsplit('.', 1)[0]) if save_snippets else None,
                                                                        snippet_name='snippet_' + line_id)

                            snippet_path = Path(temp_dir) / f"{line_id}.png"
                            image_snippet.save(snippet_path)

                            textline_coords = [(x - bbox[0], y - bbox[1]) for x, y in line.get_coordinates(returntype='tuple')]
                            baseline_coords = [(x - bbox[0], y - bbox[1]) for x, y in line.get_baseline_coordinates(returntype='tuple')]

                            lines_to_process[line_id] = {
                                'image_path': snippet_path,
                                'baseline_coords': baseline_coords,
                                'textline_coords': textline_coords,
                                'line_object': line,
                                'tr_id': textregion.get_id(),
                                'original_text': text or ''
                            }

                    if not lines_to_process:
                        return

                    # Run OCR in a single batch for the page
                    batch_data = {
                        line_id: {k: v for k, v in line_info.items() if k not in ['line_object', 'tr_id', 'original_text']}
                        for line_id, line_info in lines_to_process.items()
                    }
                    ocr_results = await run_kraken_ocr_batch_external_async(python_path, batch_data, model_path, pad=pad)

                    # Update page object with results
                    for line_id, result in ocr_results.items():
                        if line_id in lines_to_process:
                            line_info = lines_to_process[line_id]
                            line_obj = line_info['line_object']
                            ocr_text = result.get('text', '')

                            print(f'{line_id} -> [green]{ocr_text}[/green]')
                            line_obj.update_text(ocr_text)

                            tr_id = line_info['tr_id']
                            if tr_id not in text_dict:
                                text_dict[tr_id] = {}

                            text_dict[tr_id][line_id] = {
                                'original': line_info['original_text'],
                                'ocr': ocr_text
                            }

                            if 'analytics' in profilelevel:
                                metrics = get_metrics(line_info['original_text'], ocr_text)
                                if metrics:
                                    page_metrics.append(metrics)

                    # Cleanup snippets
                    for line_data in lines_to_process.values():
                        if not save_snippets:
                            line_data['image_path'].unlink(missing_ok=True)

                    async with lock:
                        if 'results' in profilelevel:
                            ocr.profile.results.append({xml_file.name: text_dict})
                        ocr.profile.stats['pages'] += any(text_dict.values())
                        ocr.profile.stats['lines'] += sum(len(region) for region in text_dict.values())

                        if 'analytics' in profilelevel and page_metrics:
                            metrics_summary = summarize_metrics(page_metrics)
                            all_metrics.extend(page_metrics)
                            ocr.profile.analytics.append({xml_file.name: metrics_summary})

                    if not dry_run:
                        fout = xml_file if outputdir is None else Path(outputdir) / xml_file.name
                        fout.parent.mkdir(parents=True, exist_ok=True)
                        logging.info(f'Wrote modified xml file to output directory: {fout}')
                        page.save_xml(fout)

            tasks = [process_page(xml_file) for xml_file in xml_files]
            await asyncio.gather(*tasks)

        try:
            asyncio.run(main())
            if 'summary' in profilelevel:
                if 'analytics' in profilelevel and all_metrics:
                    metrics = summarize_metrics(all_metrics)
                    ocr.profile.summary['analytics'] = metrics
        finally:
            # Clean up temporary directory
            import shutil
            shutil.rmtree(temp_dir, ignore_errors=True)


else:
    @app.command()
    def set_python_env_first() -> None:
        """
        Kraken Python environment not configured.
        Use 'pageplus ocr-kraken set-python-env <path>' to configure.
        """
        print("[yellow]Kraken Python environment not configured.[/yellow]")
        print("[yellow]Use 'pageplus ocr-kraken set-python-env <path>' to configure.[/yellow]")
        print("\nExample:")
        print("  pageplus ocr-kraken set-python-env /path/to/kraken/venv/bin/python")
        print("\nTo create a new Kraken environment:")
        print("  python -m venv kraken_env")
        print("  source kraken_env/bin/activate  # On Windows: kraken_env\\Scripts\\activate")
        print("  pip install kraken")

if __name__ == "__main__":
    app()
