import re
import subprocess
import sys
from collections import Counter
from importlib import util
from pathlib import Path
from typing import List, Annotated

import typer
from rich import print

from pageplus.io.logger import logging
from pageplus.models.page import Page
from pageplus.utils.constants import ProfileLevel
from pageplus.utils.fs import collect_xml_files, find_image
from pageplus.utils.fs import transform_inputs
from pageplus.utils.image import get_image, crop_image_by_polygon
from pageplus.utils.profile import profile, ProfileFnRet

app = typer.Typer()


def _install(env_path: Path = None) -> None:
    """
    Before tesseract can be used, please use this install command
    to install pytesseract by Samuel Hoffstaetter!
    """
    subprocess.check_call([sys.executable, "-m", "pip", "install", "-I", "pytesseract"])


if spec := util.find_spec('pytesseract') is None:

    @app.command()
    def install() -> None:
        """
        Before tesseract can be used, please use this install command
        to install pytesseract by Samuel Hoffstaetter!
        """
        _install()


else:
    import pytesseract


    @app.command()
    @profile('tesseract-ocr')
    def ocr(inputs: Annotated[List[str],
    typer.Argument(exists=True, help="Paths to the XML files to be checked.", callback=transform_inputs)] = None,
            image_folder: Annotated[str, typer.Argument(exists=True,
                                                        help="Folder to the images relative to page-xml (default same as input)")] = '.',
            model: Annotated[str, typer.Option(help="Modelname (should exist in Tessdata-Path)")] = None,
            tessdata_path: Annotated[str, typer.Option(help="Tessdata-Path")] = None,
            same_names: Annotated[bool, typer.Option(
                help="Use the page-xml filename to search for the image (default use imageFilename from pagexml file)")] = False,
            image_extension: Annotated[str, typer.Option(
                help="Filename extension of the images (only active with 'same_names' option)")] = '.jpg',
            save_snippets: Annotated[bool, typer.Option(help="Save snippets (debug option)")] = False,
            text_filter: Annotated[str, typer.Option(
                help="A regular expression, if specific textlines should be filtered")] = None,
            region_tagfilter: Annotated[str, typer.Option(
                help="A regular expression, if specific textlines should be filtered")] = None,
            textline_tagfilter: Annotated[str, typer.Option(
                help="A regular expression, if specific textlines should be filtered")] = None,
            profile: Annotated[
                str, typer.Option(help="Profile function with tag (default:'' no profiling active.")] = '',
            profilelevel: Annotated[List[ProfileLevel],
            typer.Option(
                help="Level of profiling. Options: 'stats' (always true), 'params', 'results', 'analytics', 'summary'")
            ] = ("stats", "params", "analytics", "summary"),
            overwrite: Annotated[
                bool, typer.Option(help="If True, ignores outputdir and overwrites input data.")] = False,
            dry_run: Annotated[bool, typer.Option(help="If True, the function will not write any files.")] = False):
        """
        OCR with the existing layout information. Existing text will be overwritten.
        """
        # API details
        # Turn profiling on
        ocr.profile = ProfileFnRet()
        ocr.profile.name = profile
        ocr.profile.dir = Path(inputs[0]).absolute() if len(inputs) > 0 else ''
        ocr.profile.stats = {'pages': 0, 'lines': 0}
        if util.find_spec('pageplus.utils.dinglehopper.edit_distance') is None:
            profilelevel.remove(ProfileLevel.analytics)
            print("[red]Warning:[/red] 'analytics' profiling level requires 'dinglehopper' package to be installed. "
                  "It will be disabled.")
        elif 'analytics' in profilelevel:
            from pageplus.cli.dinglehopper import count_diff, get_metrics, summarize_metrics

        if 'params' in profilelevel:
            ocr.profile.params = {'model': model,
                                  'text-filter': text_filter,
                                  'region-tagfilter': region_tagfilter,
                                  'textline-tagfilter': textline_tagfilter}
        # Read XML
        xml_files = collect_xml_files(map(Path, inputs))
        # Raise error if no xml files are found
        if not xml_files:
            raise FileNotFoundError('No xml files found in input directory')
        reg_filter = re.compile(rf"{text_filter}") if text_filter is not None else '.'
        all_diff = Counter()
        all_metrics = []
        for xml_file in xml_files:
            print(xml_file)
            # Read XML content
            page = Page(xml_file)
            page.delete_textlevel('region')
            # Find image (same name or image filename from page-xml file)
            imageFilename = page.imageFilename() if not same_names else xml_file.with_suffix(image_extension).name
            imageDir = xml_file
            for _ in range(0, len(image_folder.split('../'))):
                imageDir = imageDir.parent
            imageDir = imageDir.joinpath('./' + image_folder.rsplit('./')[0])
            imagePath = find_image(imageFilename, imageDir)
            if not imagePath:
                print(f"Warning: Image {imageFilename} not found in {imageDir}")
                continue
            image, image_format = get_image(imagePath)
            text_dict = {}
            page_diff = Counter()
            page_metrics = []
            # Find Textlines
            for textregion in page.regions.textregions:
                tr_id = textregion.get_id()
                if region_tagfilter is not None and region_tagfilter != textregion.get_tag():
                    continue
                text_dict[tr_id] = {}
                for line in textregion.textlines:
                    if textline_tagfilter is not None and textline_tagfilter != line.get_tag():
                        continue
                    text = line.get_text()
                    if text_filter is not None and not re.search(reg_filter, text):
                        continue
                    line_id = line.get_id()
                    text_dict[tr_id][line_id] = {'original': text} if text else {'original': ''}

                    # Cut image
                    image_snippet, bbox = crop_image_by_polygon(image,
                                                                line.get_coordinates(returntype='mrr'),
                                                                patch_size=1,
                                                                buffer=16,
                                                                save_snippet=save_snippets,
                                                                transparent_background=False,
                                                                square_canvas=False,
                                                                snippet_dir=imageDir.joinpath(
                                                                    imageFilename.rsplit('.', 1)[0]),
                                                                snippet_name='snippet_' + line_id)
                    ocr_text = pytesseract.image_to_string(image_snippet, lang=model, config='--psm 13').strip()
                    print(f'{line_id} -> [green]{ocr_text}[green]')
                    line.update_text(ocr_text)
                    text_dict[tr_id][line_id]['ocr'] = ocr_text
                    if 'analytics' in profilelevel:
                        line_diff = count_diff(text, ocr_text)
                        page_diff.update(line_diff)
                        page_metrics.append(get_metrics(text, ocr_text, line_diff))
            if 'results' in profilelevel:
                ocr.profile.results.append({xml_file.name: text_dict})
            ocr.profile.stats['pages'] += any([1 for region in text_dict.values() if len(region.values()) > 0])
            ocr.profile.stats['lines'] += sum([len(region.values()) for region in text_dict.values()])
            if 'analytics' in profilelevel:
                metrics = summarize_metrics(page_metrics) if len(page_metrics) > 0 else {}
                all_metrics.extend(page_metrics)
                ocr.profile.analytics.append({xml_file.name: {'metrics': metrics,
                                                              'confusions': dict(page_diff)}})
                all_diff.update(page_diff)
            if not dry_run:
                fout = xml_file if overwrite else xml_file.parent.joinpath(
                    Path(model).name.replace('.', '_').replace(':', '-')).joinpath(xml_file.name)
                fout.parent.mkdir(parents=True, exist_ok=True)
                logging.info(f'Wrote modified xml file to output directory: {fout}')
                page.save_xml(fout)
        if 'summary' in profilelevel:
            if 'analytics' in profilelevel:
                metrics = summarize_metrics(all_metrics)
                ocr.profile.summary['analytics'] = {'metrics': metrics,
                                                    'confusions': dict(all_diff)}

if __name__ == "__main__":
    app()
