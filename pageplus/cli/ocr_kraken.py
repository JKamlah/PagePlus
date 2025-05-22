import re
import site
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
    Before llm can be used, please use this install command
    to install kraken by Benjamin Kiessling!
    """
    current_package_path = Path(site.getsitepackages()[0])
    for package_globname in ['torch*', 'nvidia*', 'triton', 'skimage', 'scipy', 'kraken']:
        for package in env_path.glob(package_globname):
            if package.exists():
                current_package = current_package_path.joinpath(package.name)
                if not current_package.exists():
                    current_package.symlink_to(package)
    subprocess.check_call([sys.executable, "-m", "pip", "install", "-I", "kraken"])


if spec := util.find_spec('kraken') is None:

    @app.command()
    def install() -> None:
        """
        Before kraken can be used, please use this install command
        to install kraken by Benjamin Kiessling!
        """
        _install()


    @app.command()
    def install_with_link_to_env(env_path: Path) -> None:
        """
        To reduce ressource consumption, link the bigger kraken (by Benjamin Kiessling)
        package (nvidia, torch, triton) from an exisiting environment!
        (not recommended, own risk that package can be unwilling be upgraded or if other env is delete,
        this will not work anymore)
        """
        if env_path.is_dir() and env_path.joinpath('torch').exists():
            _install(env_path)
        else:
            print(f"Error: {env_path} is not a valid directory!")


else:

    from kraken.lib import models
    from kraken import rpred
    from kraken.containers import BaselineLine, Segmentation
    from pageplus.cli.llm import ImageExtension

    @app.command()
    @profile('kraken-ocr')
    def ocr(inputs: Annotated[List[str],
    typer.Argument(exists=True, help="Paths to the XML files to be checked.", callback=transform_inputs)] = None,
            image_folder: Annotated[str, typer.Option(exists=True,
                                                        help="Folder to the images relative to page-xml (default same as input)")] = '.',
            model_name: Annotated[str, typer.Option(help="Name of the model (should exist in Model-Directory)")] = None,
            model_dir: Annotated[Path, typer.Option(help="Directory of the model")] = None,
            same_names: Annotated[bool, typer.Option(
                help="Use the page-xml filename to search for the image (default use imageFilename from pagexml file)")] = False,
            image_extensions: Annotated[List[ImageExtension], typer.Option(
                help="Image file extensions to try (only active with 'same_names')", case_sensitive=False
            )] = ['.png', '.jpg', '.jpeg', '.tif', '.tiff'],
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
        model_name = model_name if model_name.endswith('.mlmodel') else model_name+'.mlmodel'
        model_path = model_dir.joinpath(model_name)
        if 'params' in profilelevel:
            ocr.profile.params = {'model': model_path.with_suffix('').name,
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
            if not same_names:
                imageFilename = page.imageFilename()
                imagePath = find_image(imageFilename, xml_file.parent / image_folder)
            else:
                imagePath = None
                for ext in image_extensions:
                    candidate = xml_file.with_suffix(ext.value).name
                    candidate_path = find_image(candidate, xml_file.parent / image_folder)
                    if candidate_path:
                        imagePath = candidate_path
                        break
                imageFilename = imagePath.name if imagePath else xml_file.with_suffix(image_extensions[0].value).name
            if not imagePath:
                print(f"Warning: Image {imageFilename} not found in {image_folder}")
                continue
            imageDir = Path(xml_file).parent
            image, image_format = get_image(imagePath)
            text_dict = {}
            page_diff = Counter()
            page_metrics = []

            # single model recognition
            _model = models.load_any(model_path)

            # Find Textlines
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
                    pad = 16
                    image_snippet, bbox = crop_image_by_polygon(image,
                                                                line.get_coordinates(returntype='mrr'),
                                                                patch_size=2,
                                                                buffer=pad,
                                                                save_snippet=save_snippets,
                                                                transparent_background=False,
                                                                square_canvas=False,
                                                                snippet_dir=imageDir.joinpath(
                                                                    imageFilename.rsplit('.', 1)[0]),
                                                                snippet_name='snippet_' + line_id)

                    textline_coords = line.get_coordinates(returntype='tuple')
                    textline_coords = [(x - bbox[0], y - bbox[1]) for x, y in textline_coords]
                    baseline_coords = line.get_baseline_coordinates(returntype='tuple')
                    baseline_coords = [(x - bbox[0], y - bbox[1]) for x, y in baseline_coords]

                    bll = BaselineLine(id='foo',
                                       baseline=baseline_coords,
                                       boundary=textline_coords)
                    seg = Segmentation(type='baselines',
                                       imagename='/dummy.png',
                                       text_direction='horizontal-lr',
                                       script_detection=False,
                                       lines=[bll])
                    it = rpred.rpred(
                        _model,
                        image_snippet,
                        bounds=seg,
                        pad=pad,
                        bidi_reordering=True,
                    )
                    for pred in it:
                        ocr_text = pred.prediction
                        #TODO: Is there a need to impelement poly and confidence?
                        #graphs = [{
                        #    'c': letter,
                        #    'poly': poly,
                        #    'confidence': float(confidence)
                        #} for letter, poly, confidence in zip(
                        #    pred.prediction, pred.cuts, pred.confidences)]

                        print(f'{line_id} -> [green]{ocr_text}[green]')
                        line.update_text(ocr_text)
                        text_dict[tr_id][line_id]['ocr'] = ocr_text
                        if 'analytics' in profilelevel:
                            page_metrics.append(get_metrics(text, ocr_text))
            if 'results' in profilelevel:
                ocr.profile.results.append({xml_file.name: text_dict})
            ocr.profile.stats['pages'] += any([1 for region in text_dict.values() if len(region.values()) > 0])
            ocr.profile.stats['lines'] += sum([len(region.values()) for region in text_dict.values()])
            if 'analytics' in profilelevel:
                metrics = summarize_metrics(page_metrics) if len(page_metrics) > 0 else {}
                all_metrics.extend(page_metrics)
                ocr.profile.analytics.append({xml_file.name: metrics})
                all_diff.update(page_diff)
            if not dry_run:
                fout = xml_file if overwrite else xml_file.parent.joinpath(
                    model_path.with_suffix('').name.replace('.', '_').replace(':', '-')).joinpath(xml_file.name)
                fout.parent.mkdir(parents=True, exist_ok=True)
                logging.info(f'Wrote modified xml file to output directory: {fout}')
                page.save_xml(fout)
        if 'summary' in profilelevel:
            if 'analytics' in profilelevel:
                metrics = summarize_metrics(all_metrics)
                ocr.profile.summary['analytics'] = metrics

if __name__ == "__main__":
    app()
