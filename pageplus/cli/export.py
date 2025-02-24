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
from pageplus.models.basic_elements import Region
from pageplus.models.text_elements import TextRegion, Textline
from pageplus.models.table_elements import TableRegion

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
                                                      square_canvas=False,
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


@app.command()
def page_to_alto(
        inputs: Annotated[List[str], typer.Argument(exists=True,
                                                    help="Iterable of paths to the PAGE XML files or workspaces.",
                                                    callback=transform_inputs)] = None,
        outputdir: Annotated[Optional[str], typer.Option(
            help="Path to the output directory where the text files will be saved. "
                 "If not specified, an output directory named Fulltext will be created "
                 "in each input file’s parent directory.")] = None) -> None:

    """
    Converts PAGE XML files to ALTO XML files. (experimental)

    Processes each PAGE XML file, extracts text and coordinates, and writes
    them to an ALTO XML file.
    This function and subfunction are heavily influenced by https://github.com/OCR-D/page-to-alto/ (thanks)
    """
    from lxml import etree as ET
    from pageplus.utils.io import (setxml, set_alto_id_from_page_id ,
                                   REGION_PAGE_TO_ALTO,
                                   HYPHEN_CHARS,
                                   set_alto_xywh_from_coords,
                                   set_alto_shape_from_coords,
                                   set_alto_lang_from_page_lang)

    # ToDO: Support older versions?
    alto_version = "4.2"
    xml_files = collect_xml_files(map(Path, inputs))
    # raise error if no xml files are found
    if not xml_files:
        raise FileNotFoundError('No xml files found in input directory')

    # loop through all xml files
    for xml_file in track(xml_files, description="Exporting data to a ALTO XML file.."):
        # get filename
        filename = xml_file.name
        page = Page(xml_file)

        # ALTO namespace and schema settings.
        alto_ns = f"http://www.loc.gov/standards/alto/ns-v{alto_version.split('.')[0]}#"
        xsd_url = f"http://www.loc.gov/standards/alto/v{alto_version.split('.')[0]}/alto-{alto_version}.xsd"

        # Create ALTO root element.
        alto = ET.Element("alto", nsmap={None: alto_ns})
        alto.set("{http://www.w3.org/2001/XMLSchema-instance}schemaLocation", f"{alto_ns} {xsd_url}")

        # Create Description element.
        description = ET.SubElement(alto, "Description")
        measurement_unit = ET.SubElement(description, "MeasurementUnit")
        measurement_unit.text = "pixel"
        source_info = ET.SubElement(description, "sourceImageInformation")
        file_name = ET.SubElement(source_info, "fileName")
        style_info = ET.SubElement(alto, "Styles")
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
            page_attr = {'HPOS': bbox[0],'VPOS':bbox[1], 'WIDTH':bbox[2]-bbox[0], 'HEIGHT':bbox[3]-bbox[1]}
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
        ro = page.get_region_reading_order_ids('auto', set(REGION_PAGE_TO_ALTO.keys()))

        layouttags = {}
        # Process each PAGE TextRegion.
        for region in page.root.findall(f".//{{{page.ns}}}*"):
            region_tag = ET.QName(region.tag).localname
            if region_tag not in REGION_PAGE_TO_ALTO.keys():
                continue
            region = {'Region': Region,
                      'TextRegion': TextRegion,
                      'TableRegion': TableRegion}.get(region_tag, Region)(region, page.ns, region.getparent())
            alto_block_type = REGION_PAGE_TO_ALTO.get(region_tag)
            block = ET.SubElement(alto_printspace, alto_block_type)
            set_alto_id_from_page_id(block, region)
            set_alto_xywh_from_coords(block, region)
            set_alto_shape_from_coords(block, region)
            set_alto_lang_from_page_lang(block, region)
            layouttag = region.get_tag()
            layouttag = 'paragraph' if 'TextRegion' == region_tag and not layouttag else layouttag
            if layouttag:
                layouttags[layouttag] = layouttag
                setxml(block, 'TAGREFS', layouttag)
            if region.get_id() in ro and ro.index(region.get_id()) < len(ro)-1:
                ro.index(region.get_id())
                setxml(block, 'IDNEXT', ro[ro.index(region.get_id())+1])


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
                    words =  list(line.xml_element.iter(f"{{{page.ns}}}Word"))
                    if words:
                        aggregated_text = []
                        for idx, word in enumerate(words):
                            word = Textline(word, page.ns, line)
                            word_text = word.get_text()
                            if idx < len(words) - 1 and word_text and word_text[-1] in HYPHEN_CHARS:
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
                        #te = ET.SubElement(tl, "TextEquiv")
                        #unicode_el = ET.SubElement(te, "Unicode")
                        #unicode_el.text = " ".join(aggregated_text)
                    else:
                        # Use aggregated TextEquiv if no Word elements.
                        line_text = line.get_text()
                        if line_text.strip():
                            string_el = ET.SubElement(tl, "String")
                            set_alto_id_from_page_id(string_el, line, "w0")
                            set_alto_xywh_from_coords(string_el, line)
                            #set_alto_shape_from_coords(string_el, word)
                            set_alto_lang_from_page_lang(string_el, line)
                            setxml(string_el, "CONTENT", line_text.strip())
                            set_alto_shape_from_coords(string_el, line)
        # Update Layouttags
        for id,label in layouttags.items():
            tag = ET.SubElement(tag_info, 'LayoutTag')
            tag.attrib['ID'] = id
            tag.attrib['LABEL'] = label
        # Write out the ALTO XML.
        filepath = Path(f"{xml_file.parent}/ALTO/{filename}") if outputdir is None else outputdir / filename
        filepath.parent.mkdir(parents=True, exist_ok=True)
        tree = ET.ElementTree(alto)
        tree.write(filepath, pretty_print=True, xml_declaration=True, encoding="UTF-8")
        print(f"Converted PAGE XML '{filename}' to ALTO XML '{filepath}'.")

if __name__ == "__main__":
    app()
