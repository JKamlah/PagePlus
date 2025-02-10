import csv
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import List, Optional, Pattern
import re

import typer
from rich.progress import track
from shapely import LineString
from typing_extensions import Annotated

from pageplus.io.logger import logging
from pageplus.models.page import Page
from pageplus.utils import fs
from pageplus.utils.fs import collect_xml_files, transform_inputs, open_folder_default, find_image
from pageplus.utils.image import get_image, crop_image_by_polygon

app = typer.Typer()


class ReadingOrderMode(str, Enum):
    """ Reading order modes"""
    auto = "auto"
    document = "document"
    rog = "reading-order-group"


@app.command()
def line_images(inputs: Annotated[List[str],
typer.Argument(exists=True, help="Paths to the XML files to be checked.", callback=transform_inputs)] = None,
        image_folder: Annotated[str, typer.Argument(exists=True,
                                                    help="Folder to the images relative to page-xml (default same as input)")] = '.',
        same_names: Annotated[bool, typer.Option(
            help="Use the page-xml filename to search for the image (default use imageFilename from pagexml file)")] = False,
        image_extension: Annotated[str, typer.Option(
            help="Filename extension of the images (only active with 'same_names' option)")] = '.jpg',
        transparent_background: Annotated[bool, typer.Option(help="The background outside the masked is transparent.)")] = False,
        save_text: Annotated[bool, typer.Option(help="Save also the text.)")] = False,
        text_filter: Annotated[str, typer.Option(
            help="A regular expression, if specific textlines should be filtered")] = None,
        dry_run: Annotated[bool, typer.Option(help="If True, the function will not write any files.")] = False):
    """
    Export lines and text files
    """
    # Read XML
    xml_files = collect_xml_files(map(Path, inputs))
    # Raise error if no xml files are found
    if not xml_files:
        raise FileNotFoundError('No xml files found in input directory')
    for xml_file in xml_files:
        print(xml_file)
        # Read XML content
        page = Page(xml_file)
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
        # Find Textlines
        reg_filter = re.compile(rf"{text_filter}") if text_filter is not None else '.'
        for textregion in page.regions.textregions:
            tr_id = textregion.get_id()
            text_dict[tr_id] = {}
            for line in textregion.textlines:
                text = line.get_text()
                if text_filter is not None and not re.match(reg_filter, text):
                    continue
                line_id = line.get_id()
                # Cut image
                snippet_dir = imageDir.joinpath(imageFilename.rsplit('.', 1)[0])
                snippet_name = imageFilename.rsplit('.', 1)[0]+'_'+line_id
                image_snippet, bbox = crop_image_by_polygon(image,
                                                      line.get_coordinates(returntype='mrr'),
                                                      min_image_size= (120, 60),
                                                      min_scale_size=(1, 1),
                                                      buffer = 5,
                                                      transparent_background = transparent_background,
                                                      save_snippet=not dry_run,
                                                      snippet_dir=snippet_dir,
                                                      snippet_name=snippet_name)
                line.transparent_background = transparent_background
                textline_coords = line.get_coordinates(returntype='tuple')
                textline_coords = [(x - bbox[0], y - bbox[1]) for x, y in textline_coords]
                baseline_coords = line.get_baseline_coordinates(returntype='tuple')
                baseline_coords = [(x - bbox[0], y - bbox[1]) for x, y in baseline_coords]
                # Convert image to Base64
                line.update_text('')
                if not dry_run and save_text:
                    fout = snippet_dir.joinpath(snippet_name + '.txt')
                    fout.parent.mkdir(parents=True, exist_ok=True)
                    fout.open('w').write(f'{text}')
                    fout = snippet_dir.joinpath(snippet_name + '.xml')
                    logging.info(f'Wrote modified xml file to output directory: {fout}')
                    fout.open('w').write(f"""<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<PcGts xmlns="http://schema.primaresearch.org/PAGE/gts/pagecontent/2013-07-15" xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance" xsi:schemaLocation="http://schema.primaresearch.org/PAGE/gts/pagecontent/2013-07-15 http://schema.primaresearch.org/PAGE/gts/pagecontent/2013-07-15/pagecontent.xsd">
    <Metadata>
        <Creator>PagePlus</Creator>
        <Created>{datetime.now()}</Created>
    </Metadata>
    <Page imageFilename="{imageFilename.rsplit('.', 1)[0]+'_'+line_id}.png" imageWidth="{image_snippet.width}" imageHeight="{image_snippet.height}">
        <ReadingOrder>
            <OrderedGroup id="ro_1" caption="Regions reading order">
                <RegionRefIndexed index="0" regionRef="r1"/>
            </OrderedGroup>
        </ReadingOrder>
        <TextRegion id="r1" custom="readingOrder {{index:0;}} structure {{type:default;}}">
            <Coords points="0,0 {image_snippet.width},0 {image_snippet.width},{image_snippet.height} 0,{image_snippet.height}"/>
            <TextLine id="r1l1" custom="readingOrder {{index:0;}} structure {{type:default;}}">
                <Coords points="{line.convert_coordinates_tuples_to_str(textline_coords)}"/>
                <Baseline points="{line.convert_coordinates_tuples_to_str(baseline_coords)}"/>
                <TextEquiv>
                    <Unicode>{text}</Unicode>
                </TextEquiv>
            </TextLine>
        </TextRegion>
    </Page>
</PcGts>""")



@app.command()
def fulltext(
        inputs: Annotated[List[str], typer.Argument(exists=True,
                                                    help="Iterable of paths to the PAGE XML files or workspaces.",
                                                    callback=transform_inputs)] = None,
        outputdir: Annotated[Optional[str], typer.Option(
            help="Path to the output directory where the text files will be saved. "
                 "If not specified, an output directory named Fulltext will be created "
                 "in each input file’s parent directory.")] = None,
        dehyphenate: Annotated[bool, typer.Option(help="Dehyphenate the textlines (no impact on coordinates)")] = False,
        ro: Annotated[bool, typer.Option(help="Use the region reading order (default: Textline order)")] = False,
        ro_mode: Annotated[ReadingOrderMode, typer.Option(
            help="Choose the reading order mode auto (try reading order group than document), "
                 "reading-order-group (only) or document (only)",
            case_sensitive=False)] = ReadingOrderMode.auto,
        open_folder: Annotated[bool, typer.Option(help="Opens the folder with the results after processing.")] = open_folder_default()):
    """
    Extracts full text from PAGE XML files and saves it as text files.

    Iterates over each specified PAGE XML file, extracts the text while dehyphenating it, and writes
    the resulting text to a specified or default output directory.

    Args:
        inputs: Iterable of paths to the PAGE XML files.
        outputdir: Path to the output directory where the text files will be saved.
        dehyphenate: If True, dehyphenates the text lines in the output.
        ro: If True, use the region reading order instead of the Textline document order
        ro_mode: Set mode how to calculate the region reading order
    """
    # Collect XML files from the input paths
    xml_files = collect_xml_files(map(Path, inputs))
    if not xml_files:
        raise FileNotFoundError('No XML files found in the input directory.')
    for xml_file in track(xml_files, description="Extracting fulltext.."):
        filename = xml_file.stem  # Extracts the filename without the extension
        logging.info(f'Processing file: {filename}')

        # Determine the output file path
        text_output_path = Path(f"{xml_file.parent}/Fulltext/{xml_file.with_suffix('.txt').name}") if outputdir is None\
            else Path(outputdir).joinpath(filename).with_suffix('.txt')
        text_output_path.parent.mkdir(parents=True, exist_ok=True)
        logging.info(f'Writing text file to: {text_output_path}')

        # Extract and write full text to the output file
        with open(text_output_path, 'w') as fout:
            extracted_text = Page(xml_file).extract_fulltext(reading_order=ro,
                                                             reading_order_mode=ro_mode.value,
                                                             dehyphenate=dehyphenate)
            fout.write(extracted_text)
        fs.open_folder(text_output_path.parent) if open_folder else None

@app.command()
def dsv(
        inputs: Annotated[List[str], typer.Argument(exists=True,
                                                    help="Iterable of paths to the PAGE XML files or workspaces.",
                                                    callback=transform_inputs)] = None,
        outputdir: Annotated[Optional[str], typer.Option(
            help="Filename of the output directory. Default is creating an output directory, called PagePlusOutput, "
                 "in the input directory.")] = None,
        delimiter: Annotated[str, typer.Option(help="Delimiter to use for separating values")] = '\t',
        dehyphenate: Annotated[bool, typer.Option(help="Dehyphenate the textlines (no impact on coordinates)")] = False,
        open_folder: Annotated[bool, typer.Option(help="Opens the folder with the results after processing.")] = open_folder_default):
    """
    Extracts text and coordinates from PAGE XML files and saves them as delimiter-separated values (DSV) files.

    Processes each PAGE XML file, extracts text line information including coordinates, and writes
    them to a DSV file with the specified delimiter.

    Args:
        inputs: Iterable of paths to the PAGE XML files.
        delimiter: The delimiter to use in the DSV file.
        dehyphenate: If True, dehyphenates the text lines in the output.
        outputdir: Path to the output directory where the DSV files will be saved.
    """
    xml_files = collect_xml_files(map(Path, inputs))
    # raise error if no xml files are found
    if not xml_files:
        raise FileNotFoundError('No xml files found in input directory')

    # loop through all xml files
    for xml_file in track(xml_files, description="Exporting data to a DSV file.."):
        # get filename
        filename = xml_file.name
        page = Page(xml_file)
        logging.info('Processing file: ' + filename)

        line_infos = {'id': [], 'text': [], 'region': [],
                      'start': [], 'mean': [], 'end': [],
                      'area': [], 'width': [], 'length': []}
        for rid, textregion in enumerate(page.regions.textregions):
            for line in textregion.textlines:
                if line.get_text is None: continue
                line_infos['id'].append(line.get_id())
                line_infos['text'].append(line.get_text())
                line_infos['region'].append(rid)
                baseline_coords = line.get_baseline_coordinates(returntype='linestring')
                if baseline_coords is not None:
                    line_infos['start'].append([int(baseline_coords.bounds[0]), int(baseline_coords.bounds[1])])
                    line_infos['mean'].append([int(baseline_coords.centroid.x), int(baseline_coords.centroid.y)])
                    line_infos['end'].append([int(baseline_coords.bounds[2]), int(baseline_coords.bounds[3])])
                else:
                    line_infos['start'].append([-1, -1])
                    line_infos['mean'].append([-1, -1])
                    line_infos['end'].append([-1, -1])
                textline_coords = line.get_coordinates(returntype='mrr')
                if textline_coords is not None:
                    lines = sorted([LineString([c1, c2]) for c1, c2 in zip(textline_coords.exterior.coords[:-1],
                                                                           textline_coords.exterior.coords[1:])],
                                   key=lambda x: x.length)
                    line_infos['area'].append(int(textline_coords.area))
                    line_infos['width'].append(int(lines[0].length))
                    line_infos['length'].append(int(lines[-1].length))
                else:
                    line_infos['area'].append(-1)
                    line_infos['width'].append(-1)
                    line_infos['length'].append(-1)

        if dehyphenate:
            line_infos['text'] = page.dehyphe(line_infos['text'])

        # Write to file
        filename = xml_file.with_suffix({'/t': '.tsv', ',': '.csv'}.get(delimiter, '.dsv')).name
        filepath = Path(f"{xml_file.parent}/DSV/{filename}") if outputdir is None else outputdir / filename
        filepath.parent.mkdir(parents=True, exist_ok=True)
        logging.info('Wrote separated value file to output directory: ' + str(filepath))
        with open(filepath, 'w') as dsvfile:
            # csv writer to write in tsv file
            dsv_writer = csv.writer(dsvfile, delimiter=delimiter)
            # write header in tsv file
            dsv_writer.writerow(line_infos.keys())
            # write rows
            dsv_writer.writerows(zip(*line_infos.values()))
            # close csv file
            dsvfile.close()
        fs.open_folder(filepath.parent) if open_folder else None


if __name__ == "__main__":
    app()
