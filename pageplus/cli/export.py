import csv
import re
import sys
from datetime import datetime
from enum import Enum
from importlib import util
from pathlib import Path
from typing import List, Optional

import typer
from PIL import Image
from lxml import etree as ET
from rich.progress import track
from shapely import LineString
from typing_extensions import Annotated

from pageplus.io.logger import logging
from pageplus.models.page import Page
from pageplus.models.text_elements import Textline
from pageplus.utils import fs
from pageplus.utils.constants import DrawingsPDF, ImageExtension
from pageplus.utils.fs import (collect_xml_files,
                               transform_inputs,
                               transform_substitutions,
                               open_folder_default,
                               find_image,
                               apply_mapping_to_files)
from pageplus.utils.image import get_image, crop_image_by_polygon
from pageplus.utils.io import (setxml, set_alto_id_from_page_id,
                               REGION_PAGE_TO_ALTO,
                               HYPHEN_CHARS,
                               set_alto_xywh_from_coords,
                               set_alto_shape_from_coords,
                               set_alto_lang_from_page_lang)
from pageplus.utils.io_churro import (
    page_xml_to_churro_page,
    page_xmls_to_churro_document,
    write_churro_document,
    write_churro_page,
)

app = typer.Typer()


class ReadingOrderMode(str, Enum):
    """ Reading order modes"""
    auto = "auto"
    document = "document"
    rog = "reading-order-group"


@app.command()
def line_images(inputs: Annotated[List[str],
                                  typer.Argument(exists=True, help="Paths to the XML files to be checked.", callback=transform_inputs)] = None,
                image_folder: Annotated[str, typer.Option(exists=True,
                                                          help="Folder to the images relative to page-xml (default same as input)")] = '.',
                same_names: Annotated[bool, typer.Option(
                    help="Use the page-xml filename to search for the image (default use imageFilename from pagexml file)")] = False,
                image_extensions: Annotated[List[ImageExtension], typer.Option(
                    help="Image file extensions to try (only active with 'same_names')", case_sensitive=False
                )] = ['.png', '.jpg', '.jpeg', '.tif', '.tiff'],
                transparent_background: Annotated[bool, typer.Option(help="The background outside the masked is transparent.)")] = False,
                save_text: Annotated[bool, typer.Option(help="Save also the text.)")] = False,
                text_filter: Annotated[str, typer.Option(
                    help="A regular expression, if specific textlines should be filtered")] = None,
                mapping_profile: Annotated[Optional[str], typer.Option(help="Mapping profile to apply to the text before exporting.")] = None,
                dry_run: Annotated[bool, typer.Option(help="If True, the function will not write any files.")] = False):
    """
    Export lines and text files
    """
    # Read XML
    xml_files = collect_xml_files(map(Path, inputs))
    # Raise error if no xml files are found
    if not xml_files:
        raise FileNotFoundError('No xml files found in input directory')

    files_to_process = [(f, f) for f in xml_files]
    temp_dir = None
    if mapping_profile:
        mapped_files, temp_dir = apply_mapping_to_files(xml_files, mapping_profile)
        files_to_process = mapped_files

    try:
        for xml_file, original_xml_file in files_to_process:
            print(original_xml_file)
            # Read XML content
            page = Page(xml_file)
            # Find image (same name or image filename from page-xml file)
            if not same_names:
                imageFilename = page.imageFilename()
                imagePath = find_image(
                    imageFilename, original_xml_file.parent / image_folder)
            else:
                imagePath = None
                for ext in image_extensions:
                    candidate = original_xml_file.with_suffix(ext.value).name
                    candidate_path = find_image(
                        candidate, original_xml_file.parent / image_folder)
                    if candidate_path:
                        imagePath = candidate_path
                        break
                imageFilename = imagePath.name if imagePath else original_xml_file.with_suffix(
                    image_extensions[0].value).name
            if not imagePath:
                print(
                    f"Warning: Image {imageFilename} not found in {image_folder}")
                continue
            imageDir = Path(original_xml_file).parent
            image, image_format = get_image(imagePath)
            text_dict = {}
            # Find Textlines
            reg_filter = re.compile(
                rf"{text_filter}") if text_filter is not None else '.'
            for textregion in page.regions.textregions:
                tr_id = textregion.get_id()
                text_dict[tr_id] = {}
                for line in textregion.textlines:
                    text = line.get_text()
                    if text_filter is not None and not re.match(reg_filter, text):
                        continue
                    line_id = line.get_id()
                    # Cut image
                    snippet_dir = imageDir.joinpath(
                        imageFilename.rsplit('.', 1)[0])
                    snippet_name = imageFilename.rsplit('.', 1)[0] + '_' + line_id
                    image_snippet, bbox = crop_image_by_polygon(image,
                                                                line.get_coordinates(returntype='mrr'),
                                                                square_canvas=False,
                                                                buffer=5,
                                                                transparent_background=transparent_background,
                                                                save_snippet=not dry_run,
                                                                snippet_dir=snippet_dir,
                                                                snippet_name=snippet_name)
                    line.transparent_background = transparent_background
                    textline_coords = line.get_coordinates(returntype='tuple')
                    textline_coords = [(x - bbox[0], y - bbox[1])
                                       for x, y in textline_coords]
                    baseline_coords = line.get_baseline_coordinates(
                        returntype='tuple')
                    baseline_coords = [(x - bbox[0], y - bbox[1])
                                       for x, y in baseline_coords]
                    # Convert image to Base64
                    line.update_text('')
                    if not dry_run and save_text:
                        fout = snippet_dir.joinpath(snippet_name + '.txt')
                        fout.parent.mkdir(parents=True, exist_ok=True)
                        fout.open('w').write(f'{text}')
                        fout = snippet_dir.joinpath(snippet_name + '.xml')
                        logging.info(
                            f'Wrote modified xml file to output directory: {fout}')
                        fout.open('w').write(
                            f"""<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<PcGts xmlns="http://schema.primaresearch.org/PAGE/gts/pagecontent/2013-07-15"
       xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"
       xsi:schemaLocation="http://schema.primaresearch.org/PAGE/gts/pagecontent/2013-07-15
       http://schema.primaresearch.org/PAGE/gts/pagecontent/2013-07-15/pagecontent.xsd">
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
    finally:
        if temp_dir:
            temp_dir.cleanup()


@app.command()
def fulltext(
        inputs: Annotated[List[str], typer.Argument(exists=True,
                                                    help="Iterable of paths to the PAGE XML files or workspaces.",
                                                    callback=transform_inputs)] = None,
        outputdir: Annotated[Optional[str], typer.Option(
            help="Path to the output directory where the text files will be saved. "
                 "If not specified, an output directory named Fulltext will be created "
                 "in each input file's parent directory.")] = None,
        dehyphenate: Annotated[bool, typer.Option(help="Dehyphenate the textlines (no impact on coordinates)")] = False,
        ro: Annotated[bool, typer.Option(help="Use the region reading order (default: Textline order)")] = False,
        ro_mode: Annotated[ReadingOrderMode, typer.Option(
            help="Choose the reading order mode auto (try reading order group than document), "
                 "reading-order-group (only) or document (only)",
            case_sensitive=False)] = ReadingOrderMode.auto,
        mapping_profile: Annotated[Optional[str], typer.Option(help="Mapping profile to apply to the text before exporting.")] = None,
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

    files_to_process = [(f, f) for f in xml_files]
    temp_dir = None
    if mapping_profile:
        mapped_files, temp_dir = apply_mapping_to_files(xml_files, mapping_profile)
        files_to_process = mapped_files

    try:
        text_output_path = None
        for xml_file, original_xml_file in track(files_to_process, description="Extracting fulltext.."):
            filename = original_xml_file.stem  # Extracts the filename without the extension
            logging.info(f'Processing file: {filename}')

            # Determine the output file path
            text_output_path = Path(f"{original_xml_file.parent}/Fulltext/{original_xml_file.with_suffix('.txt').name}") if outputdir is None\
                else Path(outputdir).joinpath(filename).with_suffix('.txt')
            text_output_path.parent.mkdir(parents=True, exist_ok=True)
            logging.info(f'Writing text file to: {text_output_path}')

            # Extract and write full text to the output file
            with open(text_output_path, 'w') as fout:
                extracted_text = Page(xml_file).extract_fulltext(
                    reading_order=ro, reading_order_mode=ro_mode.value, dehyphenate=dehyphenate)
                fout.write(extracted_text)
        if text_output_path:
            fs.open_folder(text_output_path.parent) if open_folder else None
    finally:
        if temp_dir:
            temp_dir.cleanup()


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
        mapping_profile: Annotated[Optional[str], typer.Option(help="Mapping profile to apply to the text before exporting.")] = None,
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

    files_to_process = [(f, f) for f in xml_files]
    temp_dir = None
    if mapping_profile:
        mapped_files, temp_dir = apply_mapping_to_files(xml_files, mapping_profile)
        files_to_process = mapped_files

    try:
        # loop through all xml files
        for xml_file, original_xml_file in track(
                files_to_process,
                description="Exporting data to a DSV file.."):
            # get filename
            filename = original_xml_file.name
            page = Page(xml_file)
            logging.info('Processing file: ' + filename)

            line_infos = {'id': [], 'text': [], 'region': [],
                          'start': [], 'mean': [], 'end': [],
                          'area': [], 'width': [], 'length': []}
            for rid, region in enumerate(page.get_ordered_regions()):
                for line in region.textlines:
                    if line.get_text is None:
                        continue
                    line_infos['id'].append(line.get_id())
                    line_infos['text'].append(line.get_text())
                    line_infos['region'].append(rid)
                    baseline_coords = line.get_baseline_coordinates(
                        returntype='linestring')
                    if baseline_coords is not None:
                        line_infos['start'].append(
                            [int(baseline_coords.bounds[0]), int(baseline_coords.bounds[1])])
                        line_infos['mean'].append(
                            [int(baseline_coords.centroid.x), int(baseline_coords.centroid.y)])
                        line_infos['end'].append(
                            [int(baseline_coords.bounds[2]), int(baseline_coords.bounds[3])])
                    else:
                        line_infos['start'].append([-1, -1])
                        line_infos['mean'].append([-1, -1])
                        line_infos['end'].append([-1, -1])
                    textline_coords = line.get_coordinates(returntype='mrr')
                    if textline_coords is not None:
                        lines = sorted([LineString([c1,
                                                    c2]) for c1,
                                        c2 in zip(textline_coords.exterior.coords[:-1],
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
            filename = original_xml_file.with_suffix(
                {'/t': '.tsv', ',': '.csv'}.get(delimiter, '.dsv')).name
            filepath = Path(
                f"{original_xml_file.parent}/DSV/{filename}") if outputdir is None else Path(outputdir) / filename
            filepath.parent.mkdir(parents=True, exist_ok=True)
            logging.info(
                'Wrote separated value file to output directory: ' +
                str(filepath))
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
    finally:
        if temp_dir:
            temp_dir.cleanup()


@app.command()
def alto(
        inputs: Annotated[List[str], typer.Argument(exists=True,
                                                    help="Iterable of paths to the PAGE XML files or workspaces.",
                                                    callback=transform_inputs)] = None,
        outputdir: Annotated[Optional[str], typer.Option(
            help="Path to the output directory where the text files will be saved. "
                 "If not specified, an output directory named Fulltext will be created "
                 "in each input file's parent directory.")] = None,
        mapping_profile: Annotated[Optional[str], typer.Option(help="Mapping profile to apply to the text before exporting.")] = None) -> None:
    """
    Converts PAGE XML files to ALTO XML files. (experimental)

    Processes each PAGE XML file, extracts text and coordinates, and writes
    them to an ALTO XML file.
    This function and subfunction are heavily influenced by https://github.com/OCR-D/page-to-alto/ (thanks)
    """
    # ToDO: Support older versions?
    alto_version = "4.2"
    xml_files = collect_xml_files(map(Path, inputs))
    # raise error if no xml files are found
    if not xml_files:
        raise FileNotFoundError('No xml files found in input directory')

    files_to_process = [(f, f) for f in xml_files]
    temp_dir = None
    if mapping_profile:
        mapped_files, temp_dir = apply_mapping_to_files(xml_files, mapping_profile)
        files_to_process = mapped_files

    try:
        # loop through all xml files
        for xml_file, original_xml_file in track(
                files_to_process,
                description="Exporting data to a ALTO XML file.."):
            # get filename
            filename = original_xml_file.name
            page = Page(xml_file)

            # ALTO namespace and schema settings.
            alto_ns = f"http://www.loc.gov/standards/alto/ns-v{alto_version.split('.')[0]}#"
            xsd_url = f"http://www.loc.gov/standards/alto/v{alto_version.split('.')[0]}/alto-{alto_version}.xsd"

            # Create ALTO root element.
            alto = ET.Element("alto", nsmap={None: alto_ns})
            alto.set(
                "{http://www.w3.org/2001/XMLSchema-instance}schemaLocation",
                f"{alto_ns} {xsd_url}")

            # Create Description element.
            description = ET.SubElement(alto, "Description")
            measurement_unit = ET.SubElement(description, "MeasurementUnit")
            measurement_unit.text = "pixel"
            source_info = ET.SubElement(description, "sourceImageInformation")
            file_name = ET.SubElement(source_info, "fileName")
            _ = ET.SubElement(alto, "Styles")
            tag_info = ET.SubElement(alto, "Tags")
            # Use the PAGE <Page> element's imageFilename attribute if available.
            file_name.text = page.imageFilename()

            # Create Layout.
            layout = ET.SubElement(alto, "Layout")
            alto_page = ET.SubElement(layout, "Page")
            setxml(alto_page, "ID", page.get_id())
            setxml(alto_page, "PHYSICAL_IMG_NR", 0)
            setxml(alto_page, "WIDTH", page.page_size()[0])
            setxml(alto_page, "HEIGHT", page.page_size()[1])

            # Create PrintSpace.
            alto_printspace = ET.SubElement(alto_page, "PrintSpace")
            print_space = page.border()
            if print_space is None:
                print_space = page.print_space()
            if print_space is not None:
                bbox = print_space.get_coordinates('mrr').bounds
                page_attr = {
                    'HPOS': bbox[0],
                    'VPOS': bbox[1],
                    'WIDTH': bbox[2] - bbox[0],
                    'HEIGHT': bbox[3] - bbox[1]}
                for attr in ["HEIGHT", "WIDTH", "HPOS", "VPOS"]:
                    setxml(alto_printspace, attr, int(page_attr.get(attr)))
                set_alto_shape_from_coords(alto_printspace, print_space)

            else:
                # Assume full page if no PrintSpace.
                for attr in ["HEIGHT", "WIDTH", "HPOS", "VPOS"]:
                    val = alto_page.get(attr)
                    if val:
                        setxml(alto_printspace, attr, val)
                    else:
                        setxml(alto_printspace, attr, 0)
                set_alto_shape_from_coords(alto_printspace, page)

            # Reading Order
            ro = page.get_region_reading_order_ids(
                'auto', set(REGION_PAGE_TO_ALTO.keys()))

            layouttags = {}
            # Process each PAGE TextRegion.
            for region in page.get_ordered_regions(
                    region_types=REGION_PAGE_TO_ALTO.keys()):
                region_tag = region.get_localname()
                alto_block_type = REGION_PAGE_TO_ALTO.get(region_tag)
                block = ET.SubElement(alto_printspace, alto_block_type)
                set_alto_id_from_page_id(block, region)
                set_alto_xywh_from_coords(block, region)
                set_alto_shape_from_coords(block, region)
                set_alto_lang_from_page_lang(block, region)
                layouttag = region.get_tag()
                layouttag = {
                    'TextRegion': 'TextRegion',
                    'TableRegion': 'ComposedBlock'}.get(
                    layouttag,
                    layouttag)
                if layouttag:
                    layouttags[layouttag] = layouttag
                    setxml(block, 'TAGREFS', layouttag)
                if region.get_id() in ro and ro.index(region.get_id()) < len(ro) - 1:
                    ro.index(region.get_id())
                    setxml(block, 'IDNEXT', ro[ro.index(region.get_id()) + 1])

                # Process TextLines within the region.
                if region_tag in ['TextRegion', 'TableRegion']:
                    for line in region.textlines:
                        tl = ET.SubElement(block, "TextLine")
                        set_alto_id_from_page_id(tl, line)
                        set_alto_xywh_from_coords(tl, line)
                        set_alto_shape_from_coords(tl, line)
                        set_alto_lang_from_page_lang(tl, line)
                        layouttag = line.get_tag()
                        if layouttag:
                            layouttags[layouttag] = layouttag
                            setxml(tl, 'TAGREFS', layouttag)
                        words = list(line.xml_element.iter(f"{{{page.ns}}}Word"))
                        if words:
                            aggregated_text = []
                            for idx, word in enumerate(words):
                                word = Textline(word, page.ns, line)
                                word_text = word.get_text() or ""
                                if idx < len(
                                        words) - 1 and word_text and word_text[-1] in HYPHEN_CHARS:
                                    # Remove trailing hyphen and add a HYP element.
                                    hyphen_char = word_text[-1]
                                    word_text = word_text[:-1]
                                    hyp = ET.SubElement(tl, "HYP")
                                    setxml(hyp, "CONTENT", hyphen_char)
                                string_el = ET.SubElement(tl, "String")
                                set_alto_id_from_page_id(string_el, word)
                                set_alto_xywh_from_coords(string_el, word)
                                set_alto_shape_from_coords(string_el, word)
                                set_alto_lang_from_page_lang(string_el, word)
                                layouttag = word.get_tag()
                                if layouttag:
                                    layouttags[layouttag] = layouttag
                                    setxml(string_el, 'TAGREFS', layouttag)
                                setxml(string_el, "CONTENT", word_text)
                                aggregated_text.append(word_text)
                                if idx < len(words) - 1:
                                    ET.SubElement(tl, "SP")
                            # te = ET.SubElement(tl, "TextEquiv")
                            # unicode_el = ET.SubElement(te, "Unicode")
                            # unicode_el.text = " ".join(aggregated_text)
                        else:
                            # Use aggregated TextEquiv if no Word elements.
                            line_text = line.get_text()
                            if line_text and line_text.strip():
                                string_el = ET.SubElement(tl, "String")
                                set_alto_id_from_page_id(string_el, line, "w0")
                                set_alto_xywh_from_coords(string_el, line)
                                # set_alto_shape_from_coords(string_el, word)
                                set_alto_lang_from_page_lang(string_el, line)
                                setxml(string_el, "CONTENT", line_text.strip())
                                set_alto_shape_from_coords(string_el, line)
            # Update Layouttags
            for idx, label in layouttags.items():
                tag = ET.SubElement(tag_info, 'LayoutTag')
                tag.attrib['ID'] = idx
                tag.attrib['LABEL'] = label
            # Write out the ALTO XML.
            filepath = Path(
                f"{original_xml_file.parent}/ALTO/{filename}") if outputdir is None else Path(outputdir) / filename
            filepath.parent.mkdir(parents=True, exist_ok=True)
            tree = ET.ElementTree(alto)
            tree.write(
                filepath,
                pretty_print=True,
                xml_declaration=True,
                encoding="UTF-8")
            print(f"Converted PAGE XML '{filename}' to ALTO XML '{filepath}'.")
    finally:
        if temp_dir:
            temp_dir.cleanup()


@app.command()
def churro(
    inputs: Annotated[List[str], typer.Argument(
        exists=True,
        help="Paths to PAGE-XML files or workspaces to export.",
        callback=transform_inputs,
    )] = None,
    output: Annotated[Optional[str], typer.Option(
        help="Output JSON path. Use '-' to write one JSON per input XML next to the source; "
             "omit for a default 'Churro/<input>.json' layout.",
    )] = None,
    bundle: Annotated[bool, typer.Option(
        help="If True, emit a single DocumentOCRResult JSON grouping every input page. "
             "If False (default), write one DocumentPage JSON per input XML.",
    )] = False,
    provider_name: Annotated[Optional[str], typer.Option(
        help="Optional provider label to attach to the Churro document (e.g. 'pageplus').",
    )] = None,
    model_name: Annotated[Optional[str], typer.Option(
        help="Optional model label to attach to the Churro document (e.g. an OCR engine id).",
    )] = None,
    reading_order: Annotated[bool, typer.Option(
        help="Use PAGE reading-order information when extracting line text (default: True).",
    )] = True,
    dehyphenate: Annotated[bool, typer.Option(
        help="Dehyphenate across line breaks before serialising.",
    )] = False,
    text_delimiter: Annotated[str, typer.Option(
        help="Delimiter used between lines in the Churro 'text' field.",
    )] = "\n",
) -> None:
    """
    Export PAGE-XML files to Churro JSON format.

    By default, each XML file becomes a standalone Churro ``DocumentPage``
    JSON. Use ``--bundle`` to emit a single Churro ``DocumentOCRResult`` JSON
    gathering every input page (useful for round-tripping into Churro tools).
    """
    xml_files = collect_xml_files(map(Path, inputs or []))
    if not xml_files:
        raise FileNotFoundError("No xml files found in input directory")

    if bundle:
        document = page_xmls_to_churro_document(
            xml_files,
            provider_name=provider_name,
            model_name=model_name,
            reading_order=reading_order,
            dehyphenate=dehyphenate,
            text_delimiter=text_delimiter,
        )
        out_path = Path(output) if output else xml_files[0].parent / "Churro" / "document.churro.json"
        write_churro_document(document, out_path)
        print(f"Wrote Churro document ({len(document.pages)} pages) to {out_path}")
        return

    for idx, xml_file in enumerate(track(xml_files, description="Exporting to Churro JSON..")):
        churro_page = page_xml_to_churro_page(
            xml_file,
            page_index=idx,
            source_index=idx,
            provider_name=provider_name,
            model_name=model_name,
            reading_order=reading_order,
            dehyphenate=dehyphenate,
            text_delimiter=text_delimiter,
        )
        if output == "-":
            out_path = xml_file.with_suffix(".churro.json")
        elif output:
            out_path = Path(output) / f"{xml_file.stem}.churro.json"
        else:
            out_path = xml_file.parent / "Churro" / f"{xml_file.stem}.churro.json"
        write_churro_page(churro_page, out_path)
    print(f"Wrote {len(xml_files)} Churro DocumentPage JSON file(s).")


if (spec := util.find_spec('pikepdf')) is None:
    @app.command()
    def pdf_install() -> None:
        """
        Before pdf export can be used, please use this install command
        to install pikepdf by J. Barlow!
        """
        import subprocess
        subprocess.check_call(
            [sys.executable, "-m", "pip", "install", "-I", "pikepdf"])

else:

    @app.command()
    def pdf(inputs: Annotated[List[str], typer.Argument(exists=True, help="Paths to the XML files to be checked.", callback=transform_inputs)] = None,
            images: Annotated[List[str], typer.Option(exists=True,
                                                      help="List of images to be used for the PDF export.")] = None,
            image_folder: Annotated[str, typer.Option(exists=True,
                                                      help="Folder to the images relative to page-xml (default same as input)")] = '.',
            same_names: Annotated[bool, typer.Option(
                help="Use the page-xml filename to search for the image (default use imageFilename from pagexml file)")] = False,
            image_extensions: Annotated[List[ImageExtension], typer.Option(
                help="Image file extensions to try (only active with 'same_names')", case_sensitive=False
            )] = ['.png', '.jpg', '.jpeg', '.tif', '.tiff'],
            dpi: Annotated[Optional[int], typer.Option(
                help="Resolution of the image (use None for auto-detection)")] = 300,
            jpeg_quality: Annotated[int, typer.Option(
                help="JPEG quality for embedded images (1-95)")] = 85,
            draw: Annotated[Optional[list[DrawingsPDF]], typer.Option(
                help="Activate drawing for region, line, baseline and words. (Debug Option)")] = None,
            line_thickness: Annotated[float, typer.Option(
                help="Line thickness (in points) for drawing layout elements.")] = 1.5,
            substitutions: Annotated[List[str], typer.Option(
                help="Regex substitutions with pattern==>replacement,...]", callback=transform_substitutions)] = None,
            mapping_profile: Annotated[Optional[str], typer.Option(help="Mapping profile to apply to the text before exporting.")] = None,
            output_filename: Annotated[str, typer.Option(help="Name of the output file.")] = 'PagePlus') -> None:
        """
        Creates a PDF file without word level
        """
        from pageplus.utils.pdf.renderer import create_pdf
        # Read XML
        xml_files = collect_xml_files(map(Path, inputs))
        # Raise error if no xml files are found
        if not xml_files:
            raise FileNotFoundError('No xml files found in input directory')

        files_to_process = [(f, f) for f in xml_files]
        temp_dir = None
        if mapping_profile:
            mapped_files, temp_dir = apply_mapping_to_files(xml_files, mapping_profile)
            files_to_process = mapped_files

        try:
            pages_and_images = []
            for xml_file, original_xml_file in track(files_to_process,
                              description="Rendering data to a PDF file.."):
                # Read XML content
                try:
                    page = Page(xml_file)
                    imagePath = None
                    if images:
                        match = [image for image in images if original_xml_file.with_suffix(
                            '').name == Path(image).with_suffix('').name]
                        if match:
                            imagePath = Path(match[0]).absolute()
                    if not imagePath:
                        if not same_names:
                            imageFilename = page.imageFilename()
                            imagePath = find_image(
                                imageFilename, original_xml_file.parent / image_folder)
                        else:
                            for ext in image_extensions:
                                candidate = original_xml_file.with_suffix(ext.value).name
                                candidate_path = find_image(
                                    candidate, original_xml_file.parent / image_folder)
                                if candidate_path:
                                    imagePath = candidate_path
                                    break
                            imageFilename = imagePath.name if imagePath else original_xml_file.with_suffix(
                                image_extensions[0].value).name
                    if not imagePath:
                        print(
                            f"Warning: Image not found for {original_xml_file.name}")
                        pages_and_images.append((page, None))
                        continue
                    image = Image.open(imagePath)
                    pages_and_images.append((page, image))
                except Exception as e:
                    print(f"Error: {e}")
                    continue

            if pages_and_images:
                output_path = xml_files[0].parent.joinpath(output_filename + '.pdf')
                print(f"Converted all PAGE XML files to pdf: '{output_path}'.")
                create_pdf(
                    pages_and_images=pages_and_images,
                    output_path=str(output_path),
                    target_dpi=dpi,
                    jpeg_quality=jpeg_quality,
                    draw=draw,
                    line_thickness=line_thickness,
                    substitutions=substitutions
                )
        finally:
            if temp_dir:
                temp_dir.cleanup()


@app.command()
def tei_fsl(
        inputs: Annotated[List[str], typer.Argument(exists=True,
                                                    help="Iterable of paths to the PAGE XML files or workspaces.",
                                                    callback=transform_inputs)] = None,
        outputdir: Annotated[Optional[str], typer.Option(
            help="Path to the output directory where the TEI files will be saved. "
                 "If not specified, an output directory named TEI_FSL will be created "
                 "in each input file's parent directory.")] = None,
        werkteil: Annotated[str, typer.Option(help="Type of the milestone (e.g. Grammatik)")] = "Grammatik",
        editor: Annotated[str, typer.Option(help="Name of the editor/transcriber")] = "",
        who: Annotated[str, typer.Option(help="Abbreviation/ID of the editor/transcriber (for who attribute)")] = "",
        status: Annotated[str, typer.Option(help="Status of the transcription (e.g. work_in_progress, done)")] = "work_in_progress",
        open_folder: Annotated[bool, typer.Option(help="Opens the folder with the results after processing.")] = open_folder_default()) -> List[Path]:
    """
    Converts PAGE XML files to TEI XML layout region format.
    """
    from pageplus.utils.export.tei.fsl import convert_pagexml_to_tei_fsl

    xml_files = collect_xml_files(map(Path, inputs))
    if not xml_files:
        raise FileNotFoundError('No XML files found in the input directory.')

    exported_paths = []
    for xml_file in track(xml_files, description="Converting to TEI FSL.."):
        filename = xml_file.stem
        logging.info(f'Processing file: {filename}')

        # Determine the output file path
        output_path = Path(f"{xml_file.parent}/TEI_FSL/{xml_file.with_suffix('.xml').name}") if outputdir is None \
            else Path(outputdir).joinpath(filename).with_suffix('.xml')
        
        output_path.parent.mkdir(parents=True, exist_ok=True)
        logging.info(f'Writing TEI XML file to: {output_path}')

        tree = convert_pagexml_to_tei_fsl(xml_file, werkteil=werkteil, editor=editor, who=who, status=status)
        tree.write(
            str(output_path),
            pretty_print=True,
            xml_declaration=True,
            encoding="UTF-8"
        )
        exported_paths.append(output_path)

    if exported_paths and open_folder:
        fs.open_folder(exported_paths[0].parent)

    return exported_paths


if __name__ == "__main__":
    app()

