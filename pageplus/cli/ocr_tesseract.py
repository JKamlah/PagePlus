import os
import re
import subprocess
import sys
import unicodedata
from collections import Counter
from importlib import util
from pathlib import Path
from typing import List, Annotated, Optional, Dict, Any
from multiprocessing import Pool, cpu_count
from xml.sax.saxutils import escape

import typer
from rich import print
from dotenv import dotenv_values, set_key
from PIL import Image

from pageplus.io.logger import logging
from pageplus.models.page import Page
from pageplus.utils.constants import ProfileLevel, ImageExtension
from pageplus.utils.fs import collect_xml_files, find_image
from pageplus.utils.fs import transform_inputs, transform_output
from pageplus.utils.image import get_image, crop_image_by_polygon
from pageplus.utils.profile import profile, ProfileFnRet
from pageplus.utils.envs import get_env_path
from pageplus.cli.modification import delete_text
from pageplus.utils.constants import TextLevel

app = typer.Typer(
    no_args_is_help=True,
)


def _install(env_path: Path = None) -> None:
    """
    Before tesseract can be used, please use this install command
    to install tesserocr by sirfz!
    """
    subprocess.check_call([sys.executable, "-m", "pip",
                          "install", "-I", "tesserocr"])


if spec := util.find_spec('tesserocr') is None:

    @app.command()
    def install() -> None:
        """
        Before Tesseract can be used, please use this install command
        to install tesserocr by sirfz!
        """
        _install()

elif dotenv_values(get_env_path()).get('PAGEPLUS_OCR_TESSERACT', 'False') == 'False':

    @app.command()
    def activate() -> None:
        """
        Activate before Tesseract can be used!
        """
        set_key(get_env_path(), 'PAGEPLUS_OCR_TESSERACT', 'True')
        print("[green]Tesseract OCR is now activated![/green]")

else:
    from tesserocr import PyTessBaseAPI, PSM, RIL, iterate_level

    @app.command()
    @profile('tesseract-ocr')
    def deacticvate() -> None:
        """
        Do not load Tesseract OCR for performance!
        """
        set_key(get_env_path(), 'PAGEPLUS_OCR_TESSERACT', 'False')
        print("[red]Tesseract OCR is now deactivated![/red]")

    def find_matching_image(xml_file: Path, image_files: List[str] = None,
                            image_folder: str = ".", same_names: bool = False,
                            image_extensions: List = None) -> tuple[Path, str]:
        """
        Find the matching image file for a given XML file.

        Returns:
            tuple: (image_path, image_filename) or (None, None) if not found
        """
        if image_files:
            # Use provided image files - find matching image by name
            xml_name = xml_file.stem
            for img_file in image_files:
                img_path = Path(img_file)
                if img_path.stem == xml_name:
                    return img_path, img_path.name
            return None, None
        elif image_extensions and len(image_extensions) > 0:
            # Use original logic with image_folder and image_extensions
            page = Page(xml_file)
            if not same_names:
                imageFilename = page.imageFilename()
                imagePath = find_image(imageFilename, xml_file.parent / image_folder)
                return imagePath, imageFilename
            else:
                for ext in image_extensions:
                    candidate = xml_file.with_suffix(ext.value).name
                    candidate_path = find_image(candidate, xml_file.parent / image_folder)
                    if candidate_path:
                        return candidate_path, candidate
                return None, xml_file.with_suffix(image_extensions[0].value).name
        else:
            # Fallback: try to get image from PAGE XML metadata
            page = Page(xml_file)
            imageFilename = page.imageFilename()
            imagePath = find_image(imageFilename, xml_file.parent)
            return imagePath, imageFilename

    def process_single_file(args):
        """Process a single XML file with OCR."""
        if isinstance(args, (list, tuple)):
            args_list = list(args)
            if len(args_list) < 19:
                defaults = [None, None, None, None, False, None, None, None, [], None, False, None, "Textline", None, None, True, False, False, False]
                args_list.extend(defaults[len(args_list):])
            (xml_file, image_path, image_filename, model_name, save_snippets,
             text_filter, region_tagfilter, textline_tagfilter, profilelevel,
             outputdir, dry_run, model_path, processing_level, output_formats, custom_params, create_polygon,
             create_subfolder, rename_page_xml, remove_textregion_text) = args_list[:19]
        else:
            raise ValueError(f"Expected tuple/list for args, got {type(args)}")

        if xml_file is not None:
            xml_file = Path(xml_file)
        if image_path is not None:
            image_path = Path(image_path)
            if not image_filename:
                image_filename = image_path.name

        model_name = model_name or "eng"
        processing_level = processing_level or "Textline"
        profilelevel = profilelevel or []

        reg_filter = re.compile(rf"{text_filter}") if text_filter is not None else '.'

        # Initialize variables used in all processing levels
        page_diff = Counter()
        page_metrics = []

        if processing_level == "Page":
            # Use subprocess to run tesseract directly on the image
            import subprocess
            print(f"Processing Page-level OCR for: {xml_file.name}")
            try:
                # Create output path for generated PAGE XML
                output_base = image_path.with_suffix('')
                if outputdir:
                    output_dir_path = Path(outputdir)
                    output_dir_path.mkdir(parents=True, exist_ok=True)
                    output_base = output_dir_path / output_base.name
                # generated_xml_path = output_base.with_suffix('.xml')

                # Run tesseract command
                cmd = [
                    'tesseract',
                    str(image_path),
                    str(output_base),  # tesseract adds .xml extension
                    '-l', model_name or 'eng'
                ]

                # Add output format parameters based on selected formats
                if output_formats:
                    for format_type in output_formats:
                        if format_type == "PageXML":
                            cmd.extend(['-c', 'tessedit_create_page_xml=1'])
                            # Add polygon creation parameter if enabled
                            if create_polygon:
                                cmd.extend(['-c', 'page_xml_polygon=1'])
                            else:
                                cmd.extend(['-c', 'page_xml_polygon=0'])
                        elif format_type == "ALTO":
                            cmd.extend(['-c', 'tessedit_create_alto=1'])
                        elif format_type == "TEXT":
                            cmd.extend(['-c', 'tessedit_create_txt=1'])
                        elif format_type == "HOCR":
                            cmd.extend(['-c', 'tessedit_create_hocr=1'])
                        elif format_type == "TSV":
                            cmd.extend(['-c', 'tessedit_create_tsv=1'])
                else:
                    # Default to PageXML if no formats specified
                    cmd.extend(['-c', 'tessedit_create_page_xml=1'])
                    if create_polygon:
                        cmd.extend(['-c', 'page_xml_polygon=1'])
                    else:
                        cmd.extend(['-c', 'page_xml_polygon=0'])

                # Add custom parameters
                if custom_params:
                    for param in custom_params:
                        if param.get('key') and param.get('value'):
                            cmd.extend(['-c', f"{param['key']}={param['value']}"])

                if model_path:
                    cmd.extend(['--tessdata-dir', model_path])

                print(f"Running tesseract command: {' '.join(cmd)}")
                result = subprocess.run(cmd, capture_output=True, text=True, check=True, timeout=300)  # 5 minute timeout
                print(f"Tesseract completed for {xml_file.name}, return code: {result.returncode}")
                if result.stderr:
                    print(f"Tesseract stderr: {result.stderr}")
                # Handle subfolders and renaming
                if not dry_run and (create_subfolder or rename_page_xml):
                    base_output_path = Path(outputdir) if outputdir else image_path.parent
                    print(f"Created files: {create_subfolder} {rename_page_xml}")
                    print(base_output_path)
                    subfolder_map = {
                        "PageXML": "page",
                        "ALTO": "alto",
                        "HOCR": "hocr",
                        "TEXT": "FULLTEXT",
                        "TSV": "tsv",
                    }

                    output_files = {}
                    if "PageXML" in output_formats:
                        output_files["PageXML"] = output_base.with_suffix('.page.xml')
                    if "ALTO" in output_formats:
                        output_files["ALTO"] = output_base.with_suffix('.xml')
                    if "HOCR" in output_formats:
                        output_files["HOCR"] = output_base.with_suffix('.hocr')
                    if "TEXT" in output_formats:
                        output_files["TEXT"] = output_base.with_suffix('.txt')
                    if "TSV" in output_formats:
                        output_files["TSV"] = output_base.with_suffix('.tsv')

                    if create_subfolder:
                        for format_type, file_path in output_files.items():
                            if file_path.exists():
                                subfolder_name = subfolder_map.get(format_type)
                                if subfolder_name:
                                    subfolder_path = base_output_path / subfolder_name
                                    subfolder_path.mkdir(exist_ok=True)
                                    if rename_page_xml:
                                        dest_path = subfolder_path / file_path.with_suffix('').with_suffix('.xml').name
                                    else:
                                        dest_path = subfolder_path / file_path.name
                                    file_path.rename(dest_path)
                                    output_files[format_type] = dest_path  # Update path after moving

                    elif rename_page_xml:
                        if "PageXML" in output_formats:
                            file_path = output_files["PageXML"]
                            if file_path.exists():
                                # Rename to .page.xml first, then to .xml if needed
                                page_xml_path = file_path.with_name(f"{file_path.stem}.page.xml")
                                file_path.rename(page_xml_path)

                                final_xml_path = page_xml_path.with_suffix('.xml')
                                page_xml_path.rename(final_xml_path)
                                output_files["PageXML"] = final_xml_path  # Update path after renaming

                if remove_textregion_text and "PageXML" in output_formats:
                    final_xml_path = output_files.get("PageXML")
                    if final_xml_path and final_xml_path.exists():
                        print(f"Removing TextRegion text from {final_xml_path.name}")
                        delete_text(inputs=[str(final_xml_path)], levels=[TextLevel.TextRegion])


                return {
                    'xml_file': xml_file,
                    'text_dict': {'page': {'full_text': ''}},
                    'page_diff': page_diff,
                    'page_metrics': page_metrics
                }
            except subprocess.TimeoutExpired as e:
                print(f"Tesseract timeout for {xml_file.name}: {e}")
                return {
                    'xml_file': xml_file,
                    'text_dict': {'page': {'full_text': ''}},
                    'page_diff': page_diff,
                    'page_metrics': page_metrics
                }
            except subprocess.CalledProcessError as e:
                print(f"Tesseract failed for {xml_file.name}: {e}")
                print(f"stderr: {e.stderr}")
                return {
                    'xml_file': xml_file,
                    'text_dict': {'page': {'full_text': ''}},
                    'page_diff': page_diff,
                    'page_metrics': page_metrics
                }
            except Exception as e:
                print(f"Error in Page processing for {xml_file.name}: {e}")
                return {
                    'xml_file': xml_file,
                    'text_dict': {'page': {'full_text': ''}},
                    'page_diff': page_diff,
                    'page_metrics': page_metrics
                }

        # Read XML content
        page = Page(xml_file)
        page.delete_textlevel('TextRegion')

        # Check if image was found
        if not image_path:
            print(f"Warning: No matching image found for {xml_file.name}")
            return None
        imageDir = Path(xml_file).parent
        image, image_format = get_image(image_path)
        text_dict = {}

        # Process with tesserocr (for TextRegion and Textline levels)
        resolved_datapath = model_path or get_default_datapath()
        psm_val = {'TextRegion': PSM.SINGLE_BLOCK, 'Textline': PSM.SINGLE_LINE}.get(processing_level, PSM.AUTO)
        api_kwargs = {"psm": psm_val, "lang": model_name}
        if resolved_datapath:
            api_kwargs["path"] = resolved_datapath

        with PyTessBaseAPI(**api_kwargs) as api:
            # Process based on processing level
            if processing_level == "TextRegion":
                # TextRegion-level processing - process each textregion
                for textregion in (page.regions.textregions or []):
                    tr_id = textregion.get_id()
                    if region_tagfilter is not None and region_tagfilter != textregion.get_tag():
                        print(f"Skipping region {tr_id} due to tag filter")
                        continue

                    # Get region coordinates and crop image
                    region_coords = textregion.get_coordinates(returntype='mrr')
                    if region_coords is None:
                        logging.warning(f"Could not retrieve coordinates for TextRegion {tr_id} in {xml_file.name}")
                        continue

                    try:
                        region_snippet, crop_bbox = crop_image_by_polygon(
                            image, region_coords,
                            patch_size=1, buffer=0,
                            save_snippet=save_snippets,
                            transparent_background=True,
                            square_canvas=False,
                            snippet_dir=imageDir.joinpath(
                                image_filename.rsplit('.', 1)[0]),
                            snippet_name='region_' + tr_id)
                    except Exception as e:
                        logging.error(f"Error cropping TextRegion {tr_id}: {e}")
                        continue

                    # Process region with OCR
                    if region_snippet.mode == "RGBA":
                        rgb_snippet = Image.new("RGB", region_snippet.size, (255, 255, 255))
                        rgb_snippet.paste(region_snippet, mask=region_snippet.split()[-1])
                        api.SetImage(rgb_snippet)
                    else:
                        api.SetImage(region_snippet)
                    api.Recognize()
                    ri = api.GetIterator()

                    text_dict[tr_id] = {}

                    if ri is not None:
                        # Clear existing TextLines from the region
                        if textregion.textlines:
                            indices_to_delete = list(range(len(textregion.textlines)))
                            textregion.delete_textlines(indices_to_delete)
                        xmin_crop, ymin_crop, xmax_crop, ymax_crop = crop_bbox
                        # Process each detected textline
                        for idx, r in enumerate(iterate_level(ri, RIL.TEXTLINE)):
                            try:
                                ocr_text = r.GetUTF8Text(RIL.TEXTLINE)
                            except (RuntimeError, Exception):
                                continue
                            if not ocr_text:
                                continue
                            ocr_text = unicodedata.normalize('NFC', ocr_text).strip()
                            if not ocr_text:
                                continue

                            try:
                                bbox = r.BoundingBox(RIL.TEXTLINE)
                            except (RuntimeError, Exception):
                                bbox = None
                            if not bbox:
                                continue
                            bbox = [bbox[0]+xmin_crop, bbox[1]+ymin_crop, bbox[2]+xmin_crop, bbox[3]+ymin_crop]
                            line_id = f"{tr_id}_l{idx+1}"

                            # Convert bbox to coordinates string
                            line_coords = f"{bbox[0]},{bbox[1]} {bbox[2]},{bbox[1]} {bbox[2]},{bbox[3]} {bbox[0]},{bbox[3]}"

                            # Create baseline coordinates (simplified - using bbox bottom as baseline)
                            baseline_coords = f"{bbox[0]},{bbox[3]} {bbox[2]},{bbox[3]}"

                            # Escape the text content
                            line_text = escape(ocr_text)

                            # Create new TextLine XML element
                            import lxml.etree as ET
                            textline_elem = ET.SubElement(textregion.xml_element, f"{{{textregion.ns}}}TextLine")
                            textline_elem.set("id", line_id)

                            # Add Coords element
                            coords_elem = ET.SubElement(textline_elem, f"{{{textregion.ns}}}Coords")
                            coords_elem.set("points", line_coords)

                            # Add Baseline element
                            baseline_elem = ET.SubElement(textline_elem, f"{{{textregion.ns}}}Baseline")
                            baseline_elem.set("points", baseline_coords)

                            # Add TextEquiv element
                            text_equiv_elem = ET.SubElement(textline_elem, f"{{{textregion.ns}}}TextEquiv")
                            unicode_elem = ET.SubElement(text_equiv_elem, f"{{{textregion.ns}}}Unicode")
                            unicode_elem.text = line_text

                            text_dict[tr_id][line_id] = {'ocr': ocr_text}
                            print(f'{line_id} -> [green]{line_text}[/green]')

                        # Refresh the textlines list after adding new elements
                        from pageplus.models.text_elements import Textline
                        textregion.textlines = [Textline(e, textregion.ns, parent=textregion)
                                                for e in textregion.xml_element.iter(f"{{{textregion.ns}}}TextLine")]
                    else:
                        logging.info(f"No text detected in TextRegion {tr_id}")

            else:  # Textline level (default)
                # Textline-level processing - process each textline individually
                for textregion in page.regions.textregions:
                    tr_id = textregion.get_id()
                    if region_tagfilter is not None and region_tagfilter != textregion.get_tag():
                        continue
                    text_dict[tr_id] = {}
                    for line_idx, line in enumerate(textregion.textlines):
                        if textline_tagfilter is not None and textline_tagfilter != line.get_tag():
                            continue
                        text = line.get_text()
                        if text_filter is not None and not re.search(reg_filter, text):
                            continue
                        line_id = line.get_id()
                        text_dict[tr_id][line_id] = {'original': text} if text else {'original': ''}

                        # Cut image
                        image_snippet, bbox = crop_image_by_polygon(
                            image,
                            line.get_coordinates(returntype='mrr'),
                            patch_size=1,
                            buffer=0,
                            save_snippet=save_snippets,
                            transparent_background=True,
                            square_canvas=False,
                            snippet_dir=imageDir.joinpath(
                                image_filename.rsplit('.', 1)[0]),
                            snippet_name='snippet_' + line_id)
                        # Use tesserocr for OCR
                        # Convert to RGB if the image has transparency (RGBA)
                        if image_snippet.mode == "RGBA":
                            # Create a white background for transparent images
                            rgb_snippet = Image.new("RGB", image_snippet.size, (255, 255, 255))
                            rgb_snippet.paste(image_snippet, mask=image_snippet.split()[-1])
                            api.SetImage(rgb_snippet)
                        else:
                            api.SetImage(image_snippet)
                        ocr_text = unicodedata.normalize('NFC', api.GetUTF8Text()).strip()
                        print(f'{line_id} -> [green]{ocr_text}[/green]')
                        line.update_text(ocr_text)
                        text_dict[tr_id][line_id]['ocr'] = ocr_text

                        if 'analytics' in profilelevel:
                            from pageplus.cli.dinglehopper import get_metrics
                            page_metrics.append(get_metrics(text, ocr_text))

        # Save the modified XML
        if not dry_run:
            if outputdir:
                fout = Path(outputdir) / xml_file.name
            else:
                fout = xml_file  # Overwrite original file
            fout.parent.mkdir(parents=True, exist_ok=True)
            logging.info(f'Wrote modified xml file to output directory: {fout}')
            page.save_xml(fout)

        return {
            'xml_file': xml_file,
            'text_dict': text_dict,
            'page_diff': page_diff,
            'page_metrics': page_metrics
        }

    @app.command()
    @profile('tesseract-ocr')
    def ocr(inputs: Annotated[List[str],
                              typer.Argument(exists=True,
                                             help="Paths to the XML files to be checked.",
                                             callback=transform_inputs)] = None,
            image_files: Annotated[List[str],
                                   typer.Option(help="Direct paths to image files (overrides image_folder and image_extensions)")] = None,
            image_folder: Annotated[str,
                                    typer.Option(exists=True,
                                                 help="Folder to the images relative to page-xml (default same as input)")] = '.',
            model_name: Annotated[str,
                                  typer.Option(help="Name of the model (should exist in Tessdata-Directory)")] = None,
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
            jobs: Annotated[int,
                            typer.Option(help="Number of parallel jobs to use for processing")] = cpu_count(),
            profile: Annotated[str,
                               typer.Option(help="Profile function with tag (default:'' no profiling active.")] = '',
            profilelevel: Annotated[List[ProfileLevel],
                                    typer.Option(help="Level of profiling. Options: 'stats' (always true), 'params', 'results', 'analytics', 'summary'")] = ("stats",
                                                                                                                                                             "params",
                                                                                                                                                             "analytics",
                                                                                                                                                             "summary"),
            outputdir: Annotated[Optional[str], typer.Option(
                          help="Filename of the output directory. If not specified, input files will be overwritten.",
                          callback=transform_output)] = None,
            dry_run: Annotated[bool,
                               typer.Option(help="If True, the function will not write any files.")] = False,
            create_subfolder: Annotated[bool,
                                        typer.Option(help="Create subfolders for output formats.")] = False,
            rename_page_xml: Annotated[bool,
                                       typer.Option(help="Rename PageXML from .page.xml to .xml.")] = False,
            remove_textregion_text: Annotated[bool,
                                              typer.Option(help="Remove text from TextRegion elements after OCR.")] = False,
            processing_level: Annotated[str,
                                        typer.Option(help="Processing level: 'Textline', 'TextRegion', or 'Page'.")] = "Textline"):
        """
        EXPERIMENTAL: NOT SAFE TO USE!
        OCR with the existing layout information. Existing text will be overwritten.
        Uses tesserocr for parallel processing with configurable number of jobs.
        """
        # Turn profiling on
        print("[red][bold]EXPERIMENTAL[/bold]: NOT SAFE TO USE![/red]")
        ocr.profile = ProfileFnRet()
        ocr.profile.name = profile
        ocr.profile.dir = Path(inputs[0]).absolute() if len(inputs) > 0 else ''
        ocr.profile.stats = {'pages': 0, 'lines': 0}

        if util.find_spec('pageplus.utils.dinglehopper.edit_distance') is None:
            profilelevel.remove(ProfileLevel.analytics)
            print(
                "[red]Warning:[/red] 'analytics' profiling level requires 'dinglehopper' package to be installed. "
                "It will be disabled.")
        elif 'analytics' in profilelevel:
            from pageplus.cli.dinglehopper import summarize_metrics

        if 'params' in profilelevel:
            ocr.profile.params = {'model': model_name,
                                  'text-filter': text_filter,
                                  'region-tagfilter': region_tagfilter,
                                  'textline-tagfilter': textline_tagfilter,
                                  'jobs': jobs}

        # Read XML files
        xml_files = collect_xml_files(map(Path, inputs))
        # Raise error if no xml files are found
        if not xml_files:
            raise FileNotFoundError('No xml files found in input directory')

        # Prepare arguments for parallel processing
        process_args = []
        print(f"Preparing to process {len(xml_files)} XML files:")
        for xml_file in xml_files:
            print(f"  - {xml_file.name}")
            # Find matching image for this XML file
            image_path, image_filename = find_matching_image(
                xml_file, image_files, image_folder, same_names, image_extensions
            )

            process_args.append((
                xml_file, image_path, image_filename, model_name, save_snippets,
                text_filter, region_tagfilter, textline_tagfilter, profilelevel,
                outputdir, dry_run, None, processing_level, None, None, True, create_subfolder, rename_page_xml, remove_textregion_text
            ))

        # Process files in parallel
        print(f"Processing {len(xml_files)} files with {jobs} parallel jobs...")
        all_diff = Counter()
        all_metrics = []

        with Pool(processes=jobs) as pool:
            results = pool.map(process_single_file, process_args)

        # Collect results
        for result in results:
            if result is None:
                continue

            xml_file = result['xml_file']
            text_dict = result['text_dict']
            page_diff = result['page_diff']
            page_metrics = result['page_metrics']

            print(f"Completed processing: {xml_file}")

            if 'results' in profilelevel:
                ocr.profile.results.append({xml_file.name: text_dict})
            ocr.profile.stats['pages'] += any(
                [1 for region in text_dict.values() if len(region.values()) > 0])
            ocr.profile.stats['lines'] += sum([len(region.values())
                                              for region in text_dict.values()])
            if 'analytics' in profilelevel:
                metrics = summarize_metrics(page_metrics) if len(
                    page_metrics) > 0 else {}
                all_metrics.extend(page_metrics)
                ocr.profile.analytics.append({xml_file.name: metrics})
                all_diff.update(page_diff)

        if 'summary' in profilelevel:
            if 'analytics' in profilelevel:
                metrics = summarize_metrics(all_metrics)
                ocr.profile.summary['analytics'] = metrics

    # Function that can be imported by the bridge
    def run_ocr(inputs: List[str] = None,
                image_files: List[str] = None,
                model_name: str = None,
                model_path: str = None,
                save_snippets: bool = False,
                text_filter: str = None,
                region_tagfilter: str = None,
                textline_tagfilter: str = None,
                processing_level: str = "Textline",
                jobs: int = None,
                outputdir: str = None,
                dry_run: bool = False,
                progress_callback=None,
                output_formats: List[str] = None,
                custom_params: List[Dict[str, str]] = None,
                create_polygon: bool = True,
                create_subfolder: bool = False,
                rename_page_xml: bool = False,
                remove_textregion_text: bool = False) -> Dict[str, Any]:
        """
        Run OCR processing on the given inputs.
        This function can be imported by the bridge.
        """
        if jobs is None:
            jobs = cpu_count()

        # Read XML files
        print(f"Reading {len(inputs)} XML files")
        if processing_level != "Page":
            xml_files = collect_xml_files(map(Path, inputs))
            if not xml_files:
                raise FileNotFoundError('No xml files found in input directory')
            # Prepare arguments for parallel processing
            process_args = []
            print(f"Processing {len(xml_files)} files with {jobs} parallel jobs...")
            for xml_file in xml_files:
                # Find matching image for this XML file
                image_path, image_filename = find_matching_image(
                    xml_file, image_files, ".", False, []  # Use image_files only
                )
                process_args.append((
                    xml_file, image_path, image_filename, model_name, save_snippets,
                    text_filter, region_tagfilter, textline_tagfilter, [],
                    outputdir, dry_run, model_path, processing_level,  # profilelevel is empty list
                    output_formats, custom_params, create_polygon,
                    create_subfolder, rename_page_xml, remove_textregion_text
                ))
        else:
            # For Page-level processing, we process image files directly
            process_args = []
            print(f"Processing {len(image_files)} files with {jobs} parallel jobs...")
            for image_file in image_files:
                image_file = Path(image_file)
                process_args.append((
                    image_file.with_suffix('.xml'), image_file, image_file.name, model_name, save_snippets,
                    text_filter, region_tagfilter, textline_tagfilter, [],
                    outputdir, dry_run, model_path, processing_level,  # profilelevel is empty list
                    output_formats, custom_params, create_polygon,
                    create_subfolder, rename_page_xml, remove_textregion_text
                ))

        # Process files in parallel with progress tracking
        results = []
        successful_results = []
        # Use imap for progress tracking
        print(f"Starting multiprocessing with {jobs} processes for {len(process_args)} files")
        print(f"Process args: {[str(args[0]) for args in process_args]}")
        with Pool(processes=jobs) as pool:
            # Use imap_unordered for better progress tracking
            try:
                for i, result in enumerate(pool.imap_unordered(process_single_file, process_args), 1):
                    print(f"Completed file {i}/{len(process_args)}: {result['xml_file'].name if result and 'xml_file' in result else 'None'}")
                    if result is not None:
                        successful_results.append(result)
                    results.append(result)

                    # Update progress
                    total_files = len(process_args)
                    progress_info = {
                        "current": i,
                        "total": total_files,
                        "successful": len(successful_results),
                        "percentage": (i / total_files) * 100 if total_files > 0 else 0
                    }

                    if progress_callback:
                        progress_callback(progress_info)
                    else:
                        # Fallback to console output
                        print(f"Progress: {i}/{total_files} files processed ({len(successful_results)} successful) - {progress_info['percentage']:.1f}%")
            except Exception as e:
                print(f"Error in multiprocessing: {e}")
                # Terminate the pool to prevent hanging
                pool.terminate()
                pool.join()
                raise

        return {
            "success": True,
            "processed_files": len(successful_results),
            "total_files": len(process_args)
        }

    def get_available_models(model_path: str = None) -> List[str]:
        """Get list of available Tesseract models."""
        try:
            from tesserocr import get_languages
            _, languages = get_languages(model_path)
            return languages if languages else ["eng"]  # Fallback if no models found
        except Exception:
            return ["eng"]  # Default fallback

    def get_default_datapath() -> str:
        """Get the default Tesseract data path."""
        # Fallback: Use tesseract with invalid language to get data path from error message
        try:
            tesseract_path = dotenv_values(get_env_path()).get("TESSERACT_MODEL_PATH", None)
            if tesseract_path and Path(tesseract_path).exists():
                return tesseract_path
            cmd = ["tesseract", "-l", "xxx", "xxx", "xxx"]
            result = subprocess.run(cmd, capture_output=True, text=True)
            # Parse error message to extract tessdata path
            # Error format: "Error opening data file /path/to/tessdata/xxx.traineddata"
            for line in result.stderr.split('\n'):
                if 'Error opening data file' in line and 'tessdata' in line:
                    # Extract path before 'xxx.traineddata'
                    tessdata_path = line.split('Error opening data file ')[1].split('/xxx.traineddata')[0]
                    return tessdata_path

            # If TESSDATA_PREFIX is set, use it
            if 'TESSDATA_PREFIX' in os.environ:
                return os.environ['TESSDATA_PREFIX']

        except Exception as e:
            print(e)
            pass

        # Final fallback to common paths
        import os
        common_paths = [
            "/usr/share/tesseract-ocr/4.00/tessdata",
            "/usr/share/tesseract-ocr/5/tessdata",
            "/usr/share/tesseract-ocr/tessdata",
            "/usr/local/share/tesseract-ocr/tessdata",
            "/opt/homebrew/share/tesseract-ocr/tessdata"
        ]

        for path in common_paths:
            if os.path.exists(path):
                return path

        return "/usr/share/tesseract-ocr/tessdata"  # Default fallback

    def check_tesseract_installation() -> Dict[str, Any]:
        """Check if Tesseract is properly installed."""
        try:
            # Check tesseract command
            cmd = ["tesseract", "--version"]
            result = subprocess.run(cmd, capture_output=True, text=True, check=True)

            # Check tesserocr Python package
            import importlib.util
            tesserocr_available = importlib.util.find_spec('tesserocr') is not None

            return {
                "tesseract_installed": True,
                "tesseract_version": result.stdout.strip(),
                "tesserocr_available": tesserocr_available,
                "status": "ready" if tesserocr_available else "missing_tesserocr"
            }
        except subprocess.CalledProcessError:
            return {
                "tesseract_installed": False,
                "tesseract_version": None,
                "tesserocr_available": False,
                "status": "missing_tesseract"
            }
        except FileNotFoundError:
            return {
                "tesseract_installed": False,
                "tesseract_version": None,
                "tesserocr_available": False,
                "status": "missing_tesseract"
            }


if __name__ == "__main__":
    app()
