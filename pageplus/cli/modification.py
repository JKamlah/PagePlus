from collections import Counter
from datetime import datetime
from difflib import SequenceMatcher
from pathlib import Path
from typing import List, Optional
from importlib import util
import subprocess
import sys
import re

from rich import print
from rich.progress import track
from rich.table import Table
import typer
from typing_extensions import Annotated

from pageplus.io.logger import logging
from pageplus.utils.fs import collect_xml_files, determine_output_path, transform_inputs, transform_output
from pageplus.models.page import Page
from pageplus.utils.converter import strings_to_enum
from pageplus.utils.constants import TextLevel, PcGtsVersion

app = typer.Typer()


if (spec := util.find_spec('spellchecker')) is None:
    @app.command()
    def install_spellchecker() -> None:
        """
        Before spellchecking via dictionary can be used, please use this install command
        to install Pure python spell checker based on work by Peter Norvig & Tyler Barrus       !
        """
        subprocess.check_call(
            [sys.executable, "-m", "pip", "install", "-I", "pyspellchecker"])

else:
    from pageplus.utils.spellchecker.lib import SpellCheckerPP
    from pageplus.utils.constants import Languages

    @app.command()
    def spellchecking(inputs: Annotated[List[str], typer.Argument(exists=True,
                                                                  help="Direct input of directories containing XML files.", callback=transform_inputs)] = None,
                      outputdir: Annotated[Optional[str], typer.Option(
                          help="Filename of the output directory. If not specified, input files will be overwritten.",
                          callback=transform_output)] = None,
                      language: Annotated[strings_to_enum('Languages', SpellCheckerPP().languages()),
                                          typer.Option(help=f"Language of the dictionary: {SpellCheckerPP().languages()}")] = None,
                      distance: Annotated[int, typer.Option(help="Levensthein-distance.")] = 1,
                      ignore_leading_trailing: Annotated[str, typer.Option(help="Ignore these leading and trailing unicode characters.")]
                      = None,
                      ignore_last_character: Annotated[bool,
                                                       typer.Option(help="If True, changes in the last characters gets ignored.")] = False,
                      user_words: Annotated[list[str], typer.Option(help="List of words added to the dictionary")] = None,
                      workspace_dictionary: Annotated[bool,
                                                      typer.Option(help="Create a dictionary of all the text in the existing workspace")] = False,
                      workspace_word_length: Annotated[int,
                                                       typer.Option(help="Minimum character of words to use in the workspace dictionary.")] = 8,
                      workspace_word_frequency: Annotated[int,
                                                          typer.Option(help="Minimum word frequency to use in the workspace dictionary.")] = 50,
                      report: Annotated[bool,
                                        typer.Option(help="If True, print report for all replacements.")] = False,
                      dry_run: Annotated[bool, typer.Option(help="If True, the function will not write any files.")] = False) -> None:
        """
        Spellcheck via dictionary by Peter Norvig & Tyler Barrus!
        """
        xml_files = collect_xml_files(map(Path, inputs))
        if not xml_files:
            raise FileNotFoundError('No xml files found in input directory')

        def _parse_words(text: str) -> list[str]:
            return [text]
        ignore_leading_trailing = "„!\"%&'()*+,-./:;<=>?@[\\]^_`{|}~⸗" if None else ignore_leading_trailing
        language = language.value if language else None
        spell = SpellCheckerPP(
            language=language,
            distance=distance,
            tokenizer=_parse_words)
        spell._case_sensitive = True
        spell.ignore_last_character = ignore_last_character
        spell.leading_trailing_filter = ignore_leading_trailing
        user_text = ' '.join([Page(xml_file).extract_fulltext()
                             for xml_file in xml_files]) if workspace_dictionary else ''
        spell.extend_dictionary(
            user_words,
            user_text,
            workspace_word_length,
            workspace_word_frequency)
        replacements = Counter()
        # loop through all xml files
        for xml_file in xml_files:
            # get filename
            filename = xml_file.name
            page = Page(xml_file)
            logging.info('Spellchecking file: ' + filename)
            replacements.update(spell.check_page(page))
            if not dry_run:
                fout = xml_file if outputdir is None else determine_output_path(
                    xml_file, outputdir, filename)
                logging.info(
                    f'Wrote modified xml file to output directory: {fout}')
                page.save_xml(fout)
        if report:
            table = Table(title="[green]Replacements Overview[/green]")
            table.add_column("Count", justify="right")
            table.add_column("Inline Comparison")
            table.add_column(
                "[green]Original[/green]",
                justify="right",
                style="green",
                no_wrap=True)
            table.add_column(
                "[cyan]Replacement[/cyan]",
                justify="right",
                style="cyan",
                no_wrap=True)

            def inline_diff(orig, repl):
                seqdiff = SequenceMatcher(None, orig, repl)
                diff = []
                for opcode, a0, a1, b0, b1 in seqdiff.get_opcodes():
                    if opcode == 'equal':
                        diff.append(seqdiff.a[a0:a1])
                    elif opcode == 'insert':
                        diff.append("[green]" + seqdiff.b[b0:b1] + "[/green]")
                    elif opcode == 'delete':
                        diff.append("[red]" + seqdiff.a[a0:a1] + "[/red]")
                    elif opcode == 'replace':
                        diff.append("[green]" + seqdiff.b[b0:b1] + "[/green]")
                        diff.append("[red]" + seqdiff.a[a0:a1] + "[/red]")
                    else:
                        raise RuntimeError("unexpected opcode")
                return ''.join(diff)

            [table.add_row(f"{key}",
                           inline_diff(var.split(' -> ')[0],
                                       var.split(' -> ')[1]),
                           f"[green]{var.split(' -> ')[0]}[/green]",
                           f"[cyan]{var.split(' -> ')[1]}[/cyan]") for (var,
                                                                        key) in dict(replacements.most_common()).items()]
            print(table)


@app.command()
def reassign_ids(
        inputs: Annotated[List[str], typer.Argument(exists=True,
                                                    help="Direct input of directories containing XML files.",
                                                    callback=transform_inputs)] = None,
        outputdir: Annotated[Optional[str], typer.Option(
            help="Filename of the output directory. If not specified, input files will be overwritten.",
            callback=transform_output)] = None,
        reading_order_mode='auto',
        dry_run: Annotated[bool, typer.Option(help="If True, the function will not write any files.")] = False):
    """
    Reassign IDs from Regions and Textlines
    Args:
        inputs: A list of paths to the PAGE XML files to be processed.
        dry_run: If True, the function will not write any files.
        reading_order_mode: Mode how to find the reading order.
        outputdir: The directory where the repaired XML files will be saved.
    """
    xml_files = collect_xml_files(map(Path, inputs))

    if not xml_files:
        raise FileNotFoundError('No xml files found in input directory')

    for xml_file in track(sorted(xml_files), "Reassigning IDs.."):
        filename = xml_file.name
        logging.info(f'Reassign IDs in file: {filename}')
        page = Page(xml_file)
        page.reassign_ids(reading_order_mode)
        if not dry_run:
            fout = xml_file if outputdir is None else determine_output_path(
                xml_file, outputdir, filename)
            logging.info(
                f'Wrote modified xml file to output directory: {fout}')
            page.save_xml(fout)


@app.command()
def repair(inputs: Annotated[List[str],
                             typer.Argument(exists=True,
                                            help="Direct input of directories containing XML files.",
                                            callback=transform_inputs)] = None,
           outputdir: Annotated[Optional[str],
                                typer.Option(help="Filename of the output directory. If not specified, input files will be overwritten.",
                                             callback=transform_output)] = None,
           dry_run: Annotated[bool,
                              typer.Option(help="If True, the function will not write any files.")] = False,
           ):
    """
    Repairs PAGE XML files, attempting to fix issues in text regions and lines.

    Args:
        inputs: A list of paths to the PAGE XML files to be processed.
        dry_run: If True, the function will not write any files.
        outputdir: The directory where the repaired XML files will be saved.
    """
    xml_files = collect_xml_files(map(Path, inputs))

    if not xml_files:
        raise FileNotFoundError('No xml files found in input directory')

    def repair_region(region):
        """
        Attempts to repair a given region.
        """
        for line in region.textlines:
            try:
                line.remove_repeated_points(tolerance=1)
                if not line.validate_region():
                    points = line.xml_element.find(
                        f"{{{line.ns}}}Coords").attrib['points']
                    if points:
                        coords = line.convert_coordinates_str_to_tuples(points)
                        from shapely.geometry import Polygon
                        new_coords = Polygon(coords).buffer(distance=1)
                        if new_coords:
                            line.update_coordinates(new_coords, 'polygon')

                if not line.validate_baseline(update=True):
                    line.update_baseline_coordinates(
                        line._compute_baseline(position='bottom'))

            except Exception as e:
                logging.error(f"{line.get_id()}: Error during repair - {e}")
                region.xml_element.remove(line.xml_element)

        if region.counter(level='textlines') == 0:
            logging.info(f"{region.get_id()}: Region contains no text.")

    def repair_page(page):
        """
        Attempts to repair a given Page object.
        """
        for textregion in page.regions.textregions:
            repair_region(textregion)

        for tableregion in page.regions.tableregions:
            for tablecell in tableregion.tablecells:
                repair_region(tablecell)

    for xml_file in track(sorted(xml_files), "Repairing files.."):
        filename = xml_file.name
        logging.info(f'Repairing file: {filename}')

        page = Page(xml_file)
        repair_page(page)

        if not dry_run:
            fout = xml_file if outputdir is None else determine_output_path(
                xml_file, outputdir, filename)
            logging.info(
                f'Wrote modified xml file to output directory: {fout}')
            page.save_xml(fout)


@app.command()
def delete_text(
        inputs: Annotated[List[str], typer.Argument(exists=True,
                                                    help="Paths or workspace to the PAGE XML files to be processed.",
                                                    callback=transform_inputs)] = None,
        outputdir: Annotated[Optional[str], typer.Option(
            help="Filename of the output directory. If not specified, input files will be overwritten.",
            callback=transform_output)] = None,
        levels: Annotated[List[TextLevel], typer.Option(
            help="Granularity levels to process: 'TextRegion', 'TableRegion', 'Textline', "
                 " (default: TextRegion, TableRegion).")] = ("TextRegion", "TableRegion"),
):
    """
    Deletes text elements at the specified level in PAGE XML files.

    Args:
        inputs: Paths to the PAGE XML files to be processed.
        levels: The level at which text elements will be deleted ('region', 'word', or 'line').
        outputdir: The directory where the modified XML files will be saved.
    """
    xml_files = collect_xml_files(map(Path, inputs))

    if not xml_files:
        raise FileNotFoundError('No XML files found in the input paths.')

    for xml_file in track(xml_files, description="Deleting text content.."):
        filename = xml_file.name
        logging.info(f'Processing file: {filename}')

        page = Page(xml_file)
        for level in levels:
            page.delete_textlevel(level)

        fout = xml_file if outputdir is None else determine_output_path(
            xml_file, outputdir, filename)
        logging.info(f'Wrote modified xml file to output directory: {fout}')
        page.save_xml(fout)


@app.command()
def delete_textlines(
        inputs: Annotated[List[str], typer.Argument(exists=True,
                                                    help="Paths or workspace to the PAGE XML files to be processed.",
                                                    callback=transform_inputs)] = None,
        outputdir: Annotated[Optional[str], typer.Option(
            help="Filename of the output directory. If not specified, input files will be overwritten.",
            callback=transform_output)] = None,):
    """
    Deletes text lines from PAGE XML files and saves the modified files.

    Args:
        inputs: Paths to the PAGE XML files to be processed.
        outputdir: The directory where the modified XML files will be saved.
    """
    xml_files = collect_xml_files(map(Path, inputs))

    if not xml_files:
        raise FileNotFoundError('No XML files found in the input paths.')

    for xml_file in track(xml_files, description="Delete Textlines.."):
        filename = xml_file.name
        logging.info(f'Processing file: {filename}')

        page = Page(xml_file)

        # Delete textline elements
        for textregion in page.regions.textregions:
            count = 1
            for line in textregion.textlines:
                if (len(line.get_text()) < 4 and
                        not (len(line.get_text()) == 1 and line.get_text().isalpha()) and
                        not line.get_text().isdigit()):
                    if len(textregion.textlines) == count:
                        page.delete_element(textregion.xml_element)
                        logging.info(
                                f'Delete region: {textregion.get_id()} containing only textline {line.get_id()} with text {line.get_text()}')
                    else:
                        page.delete_element(line.xml_element)
                        logging.info(
                            f'Delete textline: {line.get_id()} in region {textregion.get_id()} with text {line.get_text()}')
                        count += 1

        # Determine output file path and write the modified XML file
        fout = xml_file if outputdir is None else determine_output_path(
            xml_file, outputdir, filename)
        logging.info(f'Wrote modified xml file to output directory: {fout}')
        page.save_xml(fout)


@app.command()
def translate_lines(inputs: Annotated[List[str], typer.Argument(exists=True,
                                                                help="Paths or workspace to the PAGE XML files to be processed.",
                                                                callback=transform_inputs)] = None,
                    outputdir: Annotated[Optional[str], typer.Option(
                        help="Filename of the output directory. If not specified, input files will be overwritten.",
                        callback=transform_output)] = None,
                    xoff: Annotated[int, typer.Option(help="X Offset")] = 0,
                    yoff: Annotated[int, typer.Option(help="Y Offset.")] = 0,
                    dry_run: Annotated[bool, typer.Option(help="Perform a dry run without writing any files.")] = False
                    ):
    xml_files = collect_xml_files(map(Path, inputs))
    # raise error if no xml files are found
    if not xml_files:
        raise FileNotFoundError('No xml files found in input directory')

    # loop through all xml files
    for xml_file in xml_files:
        # get filename
        filename = xml_file.name
        page = Page(xml_file)
        logging.info('Processing file: ' + filename)

        # Place textlinepolygons over their baseline, extend the baseline and
        # fit the textlinepolygon into the textregion
        for textregion in page.regions.textregions:
            if len(textregion.textlines) == 0:
                continue
            for line in textregion.textlines:
                line.place_textlinepolygon_over_baseline()
                line.translate(xoff=xoff, yoff=yoff)
                line.fit_into_parent()

        if not dry_run:
            fout = xml_file if outputdir is None else determine_output_path(
                xml_file, outputdir, filename)
            logging.info(
                f'Wrote modified xml file to output directory: {fout}')
            page.save_xml(fout)


@app.command()
def extend_lines(
        inputs: Annotated[List[str], typer.Argument(exists=True,
                                                    help="Paths or workspace to the PAGE XML files to be processed.",
                                                    callback=transform_inputs)] = None,
        outputdir: Annotated[Optional[str], typer.Option(
            help="Filename of the output directory. If not specified, input files will be overwritten.",
            callback=transform_output)] = None,
        distance: Annotated[int, typer.Option(help="Distance (in pixel) of extension.")] = 8,
        dim: Annotated[str, typer.Option(help="Dimension in which the buffer is performed")] = "all",
        rectangularize: Annotated[bool, typer.Option(help="Rectangularize the polygons")] = True,
        cut_overlaps: Annotated[bool, typer.Option(help="Fit the extended target into the parent region.")] = True,
        dry_run: Annotated[bool, typer.Option(help="Perform a dry run without writing any files.")] = False
):
    """
    Extends the text lines and baselines in PAGE XML files.

    Args:
        inputs: Paths to the PAGE XML files to be processed.
        outputdir: The directory where the modified XML files will be saved.
        cut_overlaps: Fit the extended target into the parent region.
        dry_run: If set, no files will be written.
    """
    xml_files = collect_xml_files(map(Path, inputs))

    def process_overlapping_lines(textregion, idx, line):
        """
        Processes overlapping lines in a text region.
        """
        predecessor_line = textregion.textlines[idx - 1]
        predecessor_line_coords, line_coords = line.split_overlapping_linearrings(
            predecessor_line.get_coordinates('linearring'),
            line.get_coordinates('linearring'))
        line.update_coordinates(line_coords)
        predecessor_line.update_coordinates(predecessor_line_coords)
        if not xml_files:
            raise FileNotFoundError('No XML files found in the input paths.')

    for xml_file in track(xml_files, description="Extending Textlines.."):
        filename = xml_file.name
        logging.info(f'Processing file: {filename}')

        page = Page(xml_file)
        for textregion in page.regions.textregions:
            for idx, line in enumerate(textregion.textlines):
                try:
                    line.buffer(
                        distance=distance,
                        direction=dim,
                        rectangle=rectangularize)
                    line.fit_into_parent(
                        parent_coords=page.page_coords(
                            returntype='linearring'))
                    if cut_overlaps and idx > 0:
                        process_overlapping_lines(textregion, idx, line)
                except Exception as e:
                    logging.error(
                        f"Error processing line {line.get_id()}: {e}")
        if not dry_run:
            fout = xml_file if outputdir is None else determine_output_path(
                xml_file, outputdir, filename)
            logging.info(
                f'Wrote modified xml file to output directory: {fout}')
            page.save_xml(fout)


@app.command()
def pseudolinepolygon(
        inputs: Annotated[List[str], typer.Argument(exists=True,
                                                    help="Paths or workspace to the PAGE XML files to be processed.",
                                                    callback=transform_inputs)] = None,
        outputdir: Annotated[Optional[str], typer.Option(
            help="Filename of the output directory. If not specified, input files will be overwritten.",
            callback=transform_output)] = None):
    """
    Processes PAGE XML files to compute pseudo text line polygons.

    Args:
        inputs: Paths to the PAGE XML files to be processed.
        outputdir: The directory where the modified XML files will be saved.
    """
    xml_files = collect_xml_files(map(Path, inputs))

    if not xml_files:
        raise FileNotFoundError('No XML files found in the input paths.')

    for xml_file in track(
            xml_files,
            description="Calculating Textline polygons.."):
        filename = xml_file.name
        logging.info(f'Processing file: {filename}')

        page = Page(xml_file)
        for textregion in page.regions.textregions:
            textregion.sort_lines()
            for line in textregion.textlines:
                try:
                    line.compute_pseudotextlinepolygon(buffersize=16)
                    line.translate_baseline(yoff=10)
                    line.fit_into_parent()
                    line.extend_baseline()
                except Exception as e:
                    logging.error(
                        f"Error processing line {line.get_id()}: {e}")

        fout = xml_file if outputdir is None else determine_output_path(
            xml_file, outputdir, filename)
        logging.info(f'Wrote modified xml file to output directory: {fout}')
        page.save_xml(fout)


@app.command()
def sort(
        inputs: Annotated[List[str], typer.Argument(exists=True,
                                                    help="Paths or workspace to the PAGE XML files to be processed.",
                                                    callback=transform_inputs)] = None,
        outputdir: Annotated[Optional[str], typer.Option(
            help="Filename of the output directory. If not specified, input files will be overwritten.",
            callback=transform_output)] = None):
    """
    Sorts text lines in PAGE XML files.

    Args:
        inputs: Paths to the PAGE XML files to be processed.
        outputdir: The directory where the modified XML files will be saved.
    """
    outputdir = Path(outputdir) if outputdir else None
    xml_files = collect_xml_files(map(Path, inputs))

    if not xml_files:
        raise FileNotFoundError('No XML files found in the input paths.')

    def process_page_for_sorting(page):
        # Sorts and merges text lines in a single Page object.
        for textregion in page.regions.textregions:
            textregion.sort_lines()

    for xml_file in track(xml_files, description="Sort and merge Textlines.."):
        filename = xml_file.name
        logging.info(f'Processing file: {filename}')

        page = Page(xml_file)
        process_page_for_sorting(page)
        fout = xml_file if outputdir is None else determine_output_path(
            xml_file, outputdir, filename)
        logging.info(f'Wrote modified xml file to output directory: {fout}')
        page.save_xml(fout)


@app.command()
def sort_and_merge(
        inputs: Annotated[List[str], typer.Argument(exists=True,
                                                    help="Paths or workspace to the PAGE XML files to be processed.",
                                                    callback=transform_inputs)] = None,
        outputdir: Annotated[Optional[str], typer.Option(
            help="Filename of the output directory. If not specified, input files will be overwritten.",
            callback=transform_output)] = None,
        merge_lines_gap_x: Annotated[int, typer.Option(
            help="Merges two textlines if the gap between them is less than the provided value in the x-coordinate.",
            min=0)] = 64,
        merge_lines_gap_y: Annotated[int, typer.Option(
            help="Merges two textlines if the gap between them is less than the provided value in the y-coordinate.",
            min=0)] = 10):
    """
    Sorts and merges text lines in PAGE XML files based on specified gap thresholds.

    Args:
        inputs: Paths to the PAGE XML files to be processed.
        merge_lines_gap_x: The maximum horizontal gap in pixels to consider for merging lines.
        merge_lines_gap_y: The maximum vertical gap in pixels to consider for merging lines.
        outputdir: The directory where the modified XML files will be saved.
    """
    outputdir = Path(outputdir) if outputdir else None
    xml_files = collect_xml_files(map(Path, inputs))

    if not xml_files:
        raise FileNotFoundError('No XML files found in the input paths.')

    def process_page_for_sorting_and_merging(
            page, merge_lines_gap_x, merge_lines_gap_y):
        # Sorts and merges text lines in a single Page object.
        for textregion in page.regions.textregions:
            textregion.sort_lines()
            textregion.merge_split_up_lines(
                merge_lines_gap_x, merge_lines_gap_y)

    for xml_file in track(xml_files, description="Sort and merge Textlines.."):
        filename = xml_file.name
        logging.info(f'Processing file: {filename}')

        page = Page(xml_file)
        process_page_for_sorting_and_merging(
            page, merge_lines_gap_x, merge_lines_gap_y)

        fout = xml_file if outputdir is None else determine_output_path(
            xml_file, outputdir, filename)
        logging.info(f'Wrote modified xml file to output directory: {fout}')
        page.save_xml(fout)


@app.command()
def remove_empty(
        inputs: Annotated[List[str], typer.Argument(exists=True,
                                                    help="Paths or workspace to the files to be validated.",
                                                    callback=transform_inputs)] = None,
        outputdir: Annotated[Optional[str], typer.Option(
            help="Filename of the output directory. Default is creating an output directory, "
                 "called PagePlusOutput, in the input directory.", callback=transform_output)] = None,
        level: Annotated[List[TextLevel], typer.Option(
            help="Granularity levels to process: 'TextRegion', 'TableRegion', 'Textline', "
            " (default: TextRegion, Textline).")] = ("TextRegion", "Textline"),
        region_tagfilter: Annotated[List[str], typer.Option(
            help="A regular expression, if only specific region should be processed")] = None,
        textline_tagfilter: Annotated[List[str], typer.Option(
            help="A regular expression, if only specific textlines should be processed")] = None,
        skip_tag: Annotated[List[str], typer.Option(
            help="Tags that should be skipped.")] = None,
        dry_run: Annotated[bool, typer.Option(help="Perform a dry run without writing any files.")] = False):
    """
    Removes empty textlines and empty regions
    """
    xml_files = collect_xml_files(map(Path, inputs))
    if not xml_files:
        raise FileNotFoundError('No xml files found in input directory')

    for xml_file in track(
            sorted(xml_files),
            description="Remove empty levels in files..."):
        filename = xml_file.name
        print('[green]Checking file:[/green] ' + filename)

        page = Page(xml_file)

        # Merge cells into textregions
        textregion_number = len(page.regions.textregions)
        if 'TableRegion' in level:
            for tableregion in page.regions.tableregions:
                for cell in tableregion.tablecells:
                    if (region_tagfilter is not None and tableregion.get_tag() not in region_tagfilter) \
                            or (skip_tag is not None and tableregion.get_tag() in skip_tag):
                        print(
                            f"[orange3]Skip: {tableregion.get_tag()} - {tableregion.get_id()}[/orange3]")
                        continue
                    page.regions.textregions.append(cell)
        for ridx, region in enumerate(list(page.regions.textregions)):
            del_count = 0
            if (region_tagfilter is not None and region.get_tag() not in region_tagfilter) \
                    or (skip_tag is not None and region.get_tag() in skip_tag):
                print(
                    f"[orange3]Skip: {region.get_tag()} - {region.get_id()}[/orange3]")
                continue
            for line in region.textlines:
                if (textline_tagfilter is not None and line.get_tag() not in textline_tagfilter) \
                        or (skip_tag is not None and line.get_tag() in skip_tag):
                    print(
                        f"[orange3]Skip: {line.get_tag()} - {line.get_id()}[/orange3]")
                    continue
                if 'Textline' in level and not line.validate_text():
                    print(f"[red]Textline removed: {line.get_id()}.[/red]")
                    page.delete_element(line.xml_element)
                    del_count += 1
            if ('TextRegion' in level or 'TableRegion' in level) and del_count == len(
                    region.textlines):
                regiontype = 'TextRegion' if textregion_number > ridx else 'TableCell'
                print(f"[red]{regiontype} removed: {region.get_id()}.[/red]")
                page.delete_element(region.xml_element)
        page.load_regions()

        if 'TableRegion' in level:
            for tableregion in page.regions.tableregions:
                if (region_tagfilter is not None and tableregion.get_tag() not in region_tagfilter) \
                        or (skip_tag is not None and tableregion.get_tag() in skip_tag):
                    continue
                if not tableregion.tablecells:
                    print(f"[red]Table removed: {tableregion.get_id()}.[/red]")
                    page.delete_element(tableregion.xml_element)
            page.load_regions()

        if not dry_run:
            fout = xml_file if outputdir is None else determine_output_path(
                xml_file, outputdir, filename)
            logging.info(
                f'Wrote modified xml file to output directory: {fout}')
            page.save_xml(fout)


@app.command()
def split_big_regions_vertical(
        inputs: Annotated[List[str], typer.Argument(
            exists=True,
            help="Paths or workspace to the PAGE XML files to be processed.",
            callback=transform_inputs
        )] = None,
        outputdir: Annotated[Optional[str], typer.Option(
            help="Filename of the output directory. If not specified, input files will be overwritten.",
            callback=transform_output
        )] = None,
        split_min_area: Annotated[int, typer.Option(
            help="Splits a textregion if the area exceeds the min value",
            min=0
        )] = 4500000,
        scale_min_area_by_maxlines: Annotated[int, typer.Option(
            help="Scales the min area size by max line number to split a textregion if the area exceeds the min value",
            min=0
        )] = 140,
        dry_run: Annotated[bool, typer.Option(
            help="Perform a dry run without writing any files."
        )] = False):
    """
    Splits large text regions vertically based on area thresholds.

    Args:
        inputs: Paths to the PAGE XML files to be processed.
        outputdir: The directory where the modified XML files will be saved.
        split_min_area: The minimum area threshold for splitting regions.
        scale_min_area_by_maxlines: The scaling factor for minimum area based on line count.
        dry_run: If True, perform a dry run without writing any files.
    """
    from lxml import etree as ET

    outputdir = Path(outputdir) if outputdir is not None else None
    xml_files = collect_xml_files(map(Path, inputs))

    if not xml_files:
        raise FileNotFoundError('No XML files found in the input paths.')

    for xml_file in track(xml_files, description="Splitting big regions..."):
        filename = xml_file.name
        logging.info(f'Processing file: {filename}')

        try:
            page = Page(xml_file)
        except Exception as e:
            logging.error(f'Error processing file {filename}: {str(e)}')
            continue

        # Split big region into two
        scale = 1.0
        if scale_min_area_by_maxlines > 0:
            scale = page.counter(level='textlines') / \
                scale_min_area_by_maxlines
            scale = scale if 0.1 < scale < 1.0 else 1.0

        for textregion in page.regions.textregions:
            textregion_polygon = textregion.get_coordinates('polygon')
            if textregion_polygon is None:
                continue

            if textregion_polygon.area > split_min_area * scale:
                region_element = textregion.xml_element
                new_region_element = None

                for idx, region in enumerate(
                        textregion.split_region_by_textlinecoords()):
                    new_region_element = ET.Element(
                        region_element.tag,
                        region_element.attrib,
                        region_element.nsmap
                    )
                    new_region_element.attrib['id'] += f"_{idx + 1}"
                    coords = ET.Element(
                        region_element.tag.replace('TextRegion', 'Coords'),
                        {'points': region['region_coordstr'][0]},
                        region_element.nsmap
                    )
                    new_region_element.append(coords)
                    [new_region_element.append(textlines.xml_element)
                     for textlines in region['textlines']]
                    region_element.addnext(new_region_element)

                if new_region_element is not None:
                    logging.info(
                        f"Splitting the area {textregion.get_id()} with an area of "
                        f"{int(textregion_polygon.area)} in: {filename}"
                    )
                    page.delete_element(region_element)

        if not dry_run:
            fout = xml_file if outputdir is None else determine_output_path(
                xml_file, outputdir, filename
            )
            logging.info(
                f'Wrote modified xml file to output directory: {fout}')
            page.save_xml(fout)
        else:
            logging.info(
                f'[DRY RUN] Would write modified xml file to: ' f'{xml_file if outputdir is None else determine_output_path(xml_file, outputdir, filename)}')


@app.command()
def sort_regions(
    inputs: Annotated[List[str], typer.Argument(
        exists=True,
        help="Paths/workspace to PAGE XML files.",
        callback=transform_inputs
    )] = None,
    outputdir: Annotated[Optional[str], typer.Option(
        help="Output directory (default: overwrite input).",
        callback=transform_output
    )] = None,
    based_on_baselines: Annotated[bool, typer.Option(
        help="Use mean baseline centroid instead of polygon centroid."
    )] = False,
    overlap_pct: Annotated[float, typer.Option(
        min=0.0, max=100.0,
        help="Schwelle in % für Y- und X-Überlappung (bezogen auf die kleinere Breite/Höhe)."
    )] = 60.0,
    dry_run: Annotated[bool, typer.Option(
        help="Compute and log without writing files."
    )] = False,
):
    """
    Einfache Lese-Reihenfolge:
      1) Vertical gruppieren: Y-Überlappung >= overlap_pct (über kleinere Höhe).
      2) Gruppen nach Y.
      3) In jeder Gruppe Subgruppen/Spalten per X-Überlappung >= overlap_pct,
         Subgruppen nach X, innerhalb der Subgruppen nach Y.
      4) Flatten und in PAGE-XML übernehmen (Regionen physisch umsortieren).
    """
    from dataclasses import dataclass
    from statistics import median
    from typing import List, Tuple
    from pathlib import Path

    @dataclass
    class R:
        idx: int
        id: str
        cx: float
        cy: float
        xmin: float
        ymin: float
        xmax: float
        ymax: float
        w: float
        h: float

    def _centroid(region, based_on_baselines: bool):
        return (region.get_mean_textline_centroid()
                if based_on_baselines
                else region.get_coordinates("polygon").centroid)

    def _bbox_from_coords(
            coords: List[Tuple[float, float]]) -> Tuple[float, float, float, float]:
        xs = [p[0] for p in coords]
        ys = [p[1] for p in coords]
        return min(xs), min(ys), max(xs), max(ys)

    def _safe_id(region) -> str:
        rid = region.xml_element.get("id")
        return rid if rid else f"r_{id(region)}"

    def _ioverlap_1d(a_min, a_max, b_min, b_max) -> float:
        """Intersection über min-Länge (0..1)."""
        inter = max(0.0, min(a_max, b_max) - max(a_min, b_min))
        if inter <= 0:
            return 0.0
        return inter / max(1.0, min(a_max - a_min, b_max - b_min))

    def _collect_regions(page, based_on_baselines: bool) -> List[R]:
        regs: List[R] = []
        for i, tr in enumerate(page.regions.textregions):
            c = _centroid(tr, based_on_baselines=based_on_baselines)
            coords = tr.get_coordinates(returntype="tuple")
            if not coords:
                w, h = tr.get_width_height(method="mrr")
                regs.append(R(i, _safe_id(tr),
                              cx=float(c.x), cy=float(c.y),
                              xmin=c.x - w / 2, ymin=c.y - h / 2,
                              xmax=c.x + w / 2, ymax=c.y + h / 2,
                              w=max(1.0, w), h=max(1.0, h)))
                continue
            xmin, ymin, xmax, ymax = _bbox_from_coords(coords)
            w = max(1.0, xmax - xmin)
            h = max(1.0, ymax - ymin)
            regs.append(R(i, _safe_id(tr), float(c.x), float(
                c.y), xmin, ymin, xmax, ymax, w, h))
        return regs

    def _connected_components(items: List[R], neigh) -> List[List[R]]:
        """BFS über Paar-Nachbarschafts-Test neigh(a,b)->bool."""
        n = len(items)
        seen = [False] * n
        comps: List[List[R]] = []
        for i in range(n):
            if seen[i]:
                continue
            comp_idx = [i]
            seen[i] = True
            q = [i]
            while q:
                u = q.pop()
                a = items[u]
                for j in range(n):
                    if seen[j]:
                        continue
                    b = items[j]
                    if neigh(a, b):
                        seen[j] = True
                        q.append(j)
                        comp_idx.append(j)
            comps.append([items[k] for k in comp_idx])
        return comps

    # --- Start ---
    y_thresh = overlap_pct / 100.0
    x_thresh = overlap_pct / 100.0

    xml_files = collect_xml_files(map(Path, inputs))
    if not xml_files:
        raise FileNotFoundError("No XML files found in the input paths.")

    for xml_file in track(
            xml_files,
            description="Sorting regions (simple 60% overlaps)..."):
        logging.info(f"Processing {xml_file.name}")
        try:
            page = Page(xml_file)
        except Exception as e:
            logging.error(f"Failed to open {xml_file}: {e}")
            continue

        regs = _collect_regions(page, based_on_baselines=based_on_baselines)
        if not regs:
            logging.info("No text regions; skipping.")
            continue

        # 1) HORIZONTAL Gruppen (Zeilenbänder) via Y-Überlappung ≥ Schwelle
        def same_row(a: R, b: R) -> bool:
            return _ioverlap_1d(a.ymin, a.ymax, b.ymin, b.ymax) >= y_thresh

        row_groups = _connected_components(regs, same_row)

        # 2) Zeilengruppen nach Y (Median der y-Zentren)
        row_groups.sort(key=lambda g: median([r.cy for r in g]))
        # 3) In jeder Zeilengruppe: Spalten via X-Überlappung ≥ Schwelle,
        #    Spalten nach X, innerhalb jeder Spalte nach Y
        full_order: List[R] = []
        for row in row_groups:
            def same_col(a: R, b: R) -> bool:
                return _ioverlap_1d(a.xmin, a.xmax, b.xmin, b.xmax) >= x_thresh
            cols = _connected_components(row, same_col)
            cols.sort(key=lambda col: median(
                [r.cx for r in col]))  # links→rechts
            for col in cols:
                col.sort(key=lambda r: r.cx)  # oben→unten
                full_order.extend(col)
        # 4) XML-Reorder wie gehabt …
        for r in full_order:
            region_el = page.regions.textregions[r.idx].xml_element
            parent = region_el.getparent()
            parent.remove(region_el)
            parent.append(region_el)

        preview = ", ".join(r.id for r in full_order[:20])
        more = "" if len(
            full_order) <= 20 else f"… (+{len(full_order) - 20} more)"
        logging.info(f"Order preview: [{preview}{more}]")

        if not dry_run:
            fout = xml_file if outputdir is None else determine_output_path(
                xml_file, outputdir, xml_file.name)
            page.save_xml(fout)
            logging.info(f"Wrote: {fout}")
        else:
            logging.info(f"[DRY RUN] Would write {xml_file}")


def _calculate_hull(coords: list, group_regions: list):
    """Helper function to calculate convex hull and handle different geometry types."""
    from shapely.geometry import MultiPoint, Polygon, LineString, Point

    if not coords:
        return None

    hull = MultiPoint(coords).convex_hull

    # Ensure we have a proper polygon for the region
    if isinstance(hull, Point):
        x, y = hull.x, hull.y
        buffer_size = 10
        hull = Polygon([(x -
                         buffer_size, y -
                         buffer_size), (x +
                                        buffer_size, y -
                                        buffer_size), (x +
                                                       buffer_size, y +
                                                       buffer_size), (x -
                                                                      buffer_size, y +
                                                                      buffer_size)])
    elif isinstance(hull, LineString):
        hull = hull.buffer(5)
    elif not isinstance(hull, Polygon):
        logging.warning(
            f"Unexpected hull type: {type(hull)}, using original region coordinates")
        hull = group_regions[0].get_coordinates(returntype="polygon")

    return hull


@app.command()
def merge_columnaligned_regions(
        inputs: Annotated[List[str], typer.Argument(
            exists=True,
            help="Paths or workspace to the PAGE XML files to be processed.",
            callback=transform_inputs
        )] = None,
        outputdir: Annotated[Optional[str], typer.Option(
            help="Filename of the output directory. If not specified, input files will be overwritten.",
            callback=transform_output
        )] = None,
        tolerance: Annotated[float, typer.Option(
            help="Tolerance for merging regions",
            min=0.01,
            max=1.0
        )] = 0.1,
        based_on_baselines: Annotated[bool, typer.Option(
            help="If True, the function will merge regions based on their baseline centroid.",
        )] = False,
        convex_hull_method: Annotated[str, typer.Option(
            help="Method to use for convex hull calculation. One of 'textlines' or 'region'.",
        )] = 'region',
        max_height_distance: Annotated[float, typer.Option(
            help="Maximum vertical distance between region centroids for merging, as a percentage of page height.",
            min=0.0,
            max=1.0
        )] = 0.75,
        mid_tolerance: Annotated[float, typer.Option(
            help="A tolerance (percentage of page width) to ignore centroids too close to the middle of the page.",
            min=0.0,
            max=1.0
        )] = 0.0,
        dry_run: Annotated[bool, typer.Option(
            help="Perform a dry run without writing any files."
        )] = False):
    """
    Merges column aligned regions based on distance thresholds.
    """
    xml_files = collect_xml_files(map(Path, inputs))
    if not xml_files:
        raise FileNotFoundError('No XML files found in the input paths.')

    for xml_file in track(
            xml_files,
            description="Merging column aligned regions..."):
        filename = xml_file.name
        logging.info(f'Processing file: {filename}')

        try:
            page = Page(xml_file)
        except Exception as e:
            logging.error(f'Error processing file {filename}: {str(e)}')
            continue

        #
        page_width, page_height = page.page_size()
        max_height_distance_px = max_height_distance * page_height
        page_mid_x = page_width / 2
        mid_tolerance_px = (mid_tolerance * page_width) / 2

        # Group text regions by centroid proximity
        region_groups = []
        processed_regions = set()

        for i, textregion in enumerate(page.regions.textregions):
            if i in processed_regions:
                continue

            if based_on_baselines:
                textregion_centroid = textregion.get_mean_textline_centroid()
            else:
                textregion_centroid = textregion.get_coordinates(
                    "polygon").centroid

            # Skip regions that are too close to the middle of the page
            if page_mid_x - mid_tolerance_px <= textregion_centroid.x <= page_mid_x + mid_tolerance_px:
                processed_regions.add(i)
                continue

            textregion_width = textregion.get_width_height(method='mrr')[0]
            textregion_width_variance = int(tolerance * textregion_width)

            # Find all regions that are close to this region's centroid
            current_group = [i]
            processed_regions.add(i)

            for j, other_region in enumerate(page.regions.textregions):
                if j in processed_regions:
                    continue

                if based_on_baselines:
                    other_centroid = other_region.get_mean_textline_centroid()
                else:
                    other_centroid = other_region.get_coordinates(
                        "polygon").centroid

                # Skip regions that are too close to the middle of the page
                if page_mid_x - mid_tolerance_px <= other_centroid.x <= page_mid_x + mid_tolerance_px:
                    processed_regions.add(j)
                    continue

                # Check if centroids are within the width variance and height
                # distance
                if (abs(textregion_centroid.x - other_centroid.x) <= textregion_width_variance and
                        abs(textregion_centroid.y - other_centroid.y) <= max_height_distance_px):
                    current_group.append(j)
                    processed_regions.add(j)

            if len(current_group) > 1:  # Only process groups with multiple regions
                region_groups.append(current_group)

        # Process each group: merge regions and create convex hull
        # Process groups in reverse order to avoid index issues when deleting
        # regions
        for group_indices in sorted(
                region_groups,
                key=lambda x: max(x),
                reverse=True):
            if len(group_indices) < 2:
                continue

            logging.info(
                f'Merging {len(group_indices)} column-aligned regions')

            group_regions = [page.regions.textregions[i]
                             for i in group_indices]

            try:
                base_region = group_regions[0]
                base_region_xml = base_region.xml_element

                # Move all textlines to the base region
                for region in group_regions[1:]:
                    if region.textlines:
                        base_region.textlines.extend(region.textlines)
                        region_xml = region.xml_element
                        for line in region.textlines:
                            region_xml.remove(line.xml_element)
                            base_region_xml.append(line.xml_element)
                    page.delete_element(region.xml_element)

                # Calculate convex hull
                coords_for_hull = []
                if convex_hull_method == 'region':
                    for region in group_regions:
                        region_coords = region.get_coordinates(returntype="tuple")
                        if region_coords:
                            coords_for_hull.extend(region_coords)
                else:  # 'textlines'
                    for line in base_region.textlines:
                        line_coords = line.get_coordinates(returntype="tuple")
                        if line_coords:
                            coords_for_hull.extend(line_coords)

                hull = _calculate_hull(coords_for_hull, group_regions)

                if hull:
                    base_region.update_coordinates(hull, 'polygon')
                    base_region.buffer(distance=5, direction='all')

                # base_region.sort_baselines(mode='single_col')
                logging.info(
                    f'Successfully merged {len(group_indices)} regions into one')

            except Exception as e:
                logging.error(f'Error merging regions: {str(e)}')
                continue

        if not dry_run:
            fout = xml_file if outputdir is None else determine_output_path(
                xml_file, outputdir, filename)
            logging.info(
                f'Wrote modified xml file to output directory: {fout}')
            page.save_xml(fout)
        else:
            logging.info(
                f'[DRY RUN] Would write modified xml file to: {xml_file}')


@app.command()
def replace_tag(
        inputs: Annotated[List[str], typer.Argument(exists=True,
                                                    help="Paths or workspace to the files to be validated.",
                                                    callback=transform_inputs)] = None,
        outputdir: Annotated[Optional[str], typer.Option(
            help="Filename of the output directory. Default is creating an output directory, "
                 "called PagePlusOutput, in the input directory.", callback=transform_output)] = None,
        old_tag: Annotated[str, typer.Option(
            help="The tag to be replaced."
        )] = None,
        new_tag: Annotated[str, typer.Option(
            help="The new tag to be used.(if set to none, the tag will be removed)"
        )] = None,
        level: Annotated[List[TextLevel], typer.Option(
            help="Granularity levels to process: 'TextRegion', 'TableRegion', 'Textline', "
            " (default: TextRegion, Textline).")] = ("TextRegion", "Textline"),
        textfilter: Annotated[Optional[str], typer.Option(
            help="Regex pattern to match text content. If provided, only elements containing matching text will be processed.")] = None,
        skip_textfilter: Annotated[bool, typer.Option(
            help="If True, skip elements matching the textfilter. If False, only process elements matching the textfilter.")] = False,
        dry_run: Annotated[bool, typer.Option(help="Perform a dry run without writing any files.")] = False):
    """
    Replaces tags in the specified levels with a new tag.
    Optionally filters elements based on their text content using regex pattern matching.
    """
    xml_files = collect_xml_files(map(Path, inputs))
    if not xml_files:
        raise FileNotFoundError('No xml files found in input directory')

    # Compile regex pattern if provided
    pattern = re.compile(textfilter) if textfilter else None
    old_tag = old_tag if old_tag is not None else ''
    new_tag = new_tag if new_tag is not None else ''

    for xml_file in track(
            sorted(xml_files),
            description="Replacing tags in files..."):
        filename = xml_file.name
        print('[green]Processing file:[/green] ' + filename)

        page = Page(xml_file)

        # Process TextRegions
        if 'TextRegion' in level:
            for region in page.regions.textregions:
                if pattern:
                    text = region.get_text()
                    matches = bool(pattern.search(text))
                    if (skip_textfilter and matches) or (
                            not skip_textfilter and not matches):
                        print(
                            f"[orange3]Skip TextRegion: {region.get_id()} - Text: {text[:50]}...[/orange3]")
                        continue
                if region.get_tag() == old_tag:
                    print(
                        f"[yellow]Replacing tag in TextRegion: {region.get_id()} with tag {new_tag}")
                    region.set_tag(new_tag)

        # Process TableRegions
        if 'TableRegion' in level:
            for tableregion in page.regions.tableregions:
                if pattern:
                    text = tableregion.get_text()
                    matches = bool(pattern.search(text))
                    if (skip_textfilter and matches) or (
                            not skip_textfilter and not matches):
                        print(
                            f"[orange3]Skip TableRegion: {tableregion.get_id()} - Text: {text[:50]}...[/orange3]")
                        continue
                if tableregion.get_tag() == old_tag:
                    print(
                        f"[yellow]Replacing tag in TableRegion: {tableregion.get_id()} with tag {new_tag}")
                    tableregion.set_tag(new_tag)

        # Process Textlines
        if 'Textline' in level:
            for region in page.regions.textregions:
                for line in region.textlines:
                    if pattern:
                        text = line.get_text()
                        matches = bool(pattern.search(text))
                        if (skip_textfilter and matches) or (
                                not skip_textfilter and not matches):
                            print(
                                f"[orange3]Skip Textline: {line.get_id()} - Text: {text[:50]}...[/orange3]")
                            continue
                    if line.get_tag() == old_tag:
                        print(
                            f"[yellow]Replacing tag in Textline: {line.get_id()} with tag {new_tag}")
                        line.set_tag(new_tag)

        if not dry_run:
            fout = xml_file if outputdir is None else determine_output_path(
                xml_file, outputdir, filename)
            logging.info(
                f'Wrote modified xml file to output directory: {fout}')
            page.save_xml(fout)


@app.command()
def remove_tag(
        inputs: Annotated[List[str], typer.Argument(exists=True,
                                                    help="Paths or workspace to the files to be validated.",
                                                    callback=transform_inputs)] = None,
        outputdir: Annotated[Optional[str], typer.Option(
            help="Filename of the output directory. Default is creating an output directory, "
                 "called PagePlusOutput, in the input directory.", callback=transform_output)] = None,
        tag_to_remove: Annotated[str, typer.Option(
            help="The tag of elements to be removed."
        )] = None,
        level: Annotated[List[TextLevel], typer.Option(
            help="Granularity levels to process: 'TextRegion', 'TableRegion', 'Textline', "
            " (default: TextRegion, Textline).")] = ("TextRegion", "Textline"),
        textfilter: Annotated[Optional[str], typer.Option(
            help="Regex pattern to match text content. If provided, only elements containing matching text will be processed.")] = None,
        skip_textfilter: Annotated[bool, typer.Option(
            help="If True, skip elements matching the textfilter. If False, only process elements matching the textfilter.")] = False,
        dry_run: Annotated[bool, typer.Option(help="Perform a dry run without writing any files.")] = False):
    """
    Removes elements with specified tags at the specified levels.
    Optionally filters elements based on their text content using regex pattern matching.
    """
    xml_files = collect_xml_files(map(Path, inputs))
    if not xml_files:
        raise FileNotFoundError('No xml files found in input directory')

    # Compile regex pattern if provided
    pattern = re.compile(textfilter) if textfilter else None
    tag_to_remove = tag_to_remove if tag_to_remove is not None else ''

    for xml_file in track(
            sorted(xml_files),
            description="Removing elements with tags from files..."):
        filename = xml_file.name
        print('[green]Processing file:[/green] ' + filename)

        page = Page(xml_file)

        # Process TextRegions
        if 'TextRegion' in level:
            for region in list(page.regions.textregions):
                if pattern:
                    text = region.get_text()
                    matches = bool(pattern.search(text))
                    if (skip_textfilter and matches) or (
                            not skip_textfilter and not matches):
                        print(
                            f"[orange3]Skip TextRegion: {region.get_id()} - Text: {text[:50]}...[/orange3]")
                        continue
                if region.get_tag() == tag_to_remove:
                    print(
                        f"[red]Removing TextRegion: {region.get_id()} with tag '{tag_to_remove}'[/red]")
                    page.delete_element(region.xml_element)

        # Process TableRegions
        if 'TableRegion' in level:
            for tableregion in list(page.regions.tableregions):
                if pattern:
                    text = tableregion.get_text()
                    matches = bool(pattern.search(text))
                    if (skip_textfilter and matches) or (
                            not skip_textfilter and not matches):
                        print(
                            f"[orange3]Skip TableRegion: {tableregion.get_id()} - Text: {text[:50]}...[/orange3]")
                        continue
                if tableregion.get_tag() == tag_to_remove:
                    print(
                        f"[red]Removing TableRegion: {tableregion.get_id()} with tag '{tag_to_remove}'[/red]")
                    page.delete_element(tableregion.xml_element)

        # Reload regions after deletions
        page.load_regions()

        # Process Textlines
        if 'Textline' in level:
            for region in page.regions.textregions:
                for line in list(region.textlines):
                    if pattern:
                        text = line.get_text()
                        matches = bool(pattern.search(text))
                        if (skip_textfilter and matches) or (
                                not skip_textfilter and not matches):
                            print(
                                f"[orange3]Skip Textline: {line.get_id()} - Text: {text[:50]}...[/orange3]")
                            continue
                    if line.get_tag() == tag_to_remove:
                        print(
                            f"[red]Removing Textline: {line.get_id()} with tag '{tag_to_remove}'[/red]")
                        page.delete_element(line.xml_element)

        if not dry_run:
            fout = xml_file if outputdir is None else determine_output_path(
                xml_file, outputdir, filename)
            logging.info(
                f'Wrote modified xml file to output directory: {fout}')
            page.save_xml(fout)


@app.command()
def rectangularize(
        inputs: Annotated[List[str], typer.Argument(exists=True,
                                                    help="Paths or workspace to the files to be validated.",
                                                    callback=transform_inputs)] = None,
        outputdir: Annotated[Optional[str], typer.Option(
            help="Filename of the output directory. Default is creating an output directory, "
            "called PagePlusOutput, in the input directory.", callback=transform_output)] = None,
        level: Annotated[List[TextLevel], typer.Option(
            help="Granularity levels to process: 'TextRegion', 'TableRegion', 'Textline', "
            " (default: TextRegion, Textline).")] = ("TextRegion", "Textline"),
        dry_run: Annotated[bool, typer.Option(help="Perform a dry run without writing any files.")] = False):
    """
    Rectangularizes the coordinates of textlines and regions to ensure they are properly aligned.
    """
    xml_files = collect_xml_files(map(Path, inputs))
    if not xml_files:
        raise FileNotFoundError('No xml files found in input directory')

    for xml_file in track(
            sorted(xml_files),
            description="Rectangularizing coordinates in files..."):
        filename = xml_file.name
        print('[green]Processing file:[/green] ' + filename)

        page = Page(xml_file)
        page_size = page.get_coordinates('linearring')

        # Process TextRegions
        if 'TextRegion' in level:
            for region in page.regions.textregions:
                region.buffer(distance=0, direction='all', rectangle=True)
                region.fit_into_parent(page_size)
                print(
                    f"[yellow]Rectangularizing TextRegion: {region.get_id()}[/yellow]")
        # Process TableRegions
        if 'TableRegion' in level:
            for tableregion in page.regions.tableregions:
                tableregion.buffer(distance=0, direction='all', rectangle=True)
                tableregion.fit_into_parent(page_size)
                print(
                    f"[yellow]Rectangularizing TableRegion: {tableregion.get_id()}[/yellow]")
                for cell in tableregion.tablecells:
                    cell.buffer(distance=0, direction='all', rectangle=True)
                    tableregion.fit_into_parent(
                        tableregion.get_coordinates('linearring'))
                    print(
                        f"[yellow]Rectangularizing TableCell: {cell.get_id()}[/yellow]")

        # Process Textlines
        if 'Textline' in level:
            for region in [
                *page.regions.textregions,
                    *page.regions.tableregions]:
                for line in region.textlines:
                    line.buffer(distance=0, direction='all', rectangle=True)
                    line.fit_into_parent()
                    print(
                        f"[yellow]Rectangularizing Textline: {line.get_id()}[/yellow]")

        if not dry_run:
            fout = xml_file if outputdir is None else determine_output_path(
                xml_file, outputdir, filename)
            logging.info(
                f'Wrote modified xml file to output directory: {fout}')
            page.save_xml(fout)


@app.command()
def repair_dummy_region(
        inputs: Annotated[List[str], typer.Argument(exists=True,
                                                    help="Paths or workspace to the files to be validated.",
                                                    callback=transform_inputs)] = None,
        outputdir: Annotated[Optional[str], typer.Option(
            help="Filename of the output directory. Default is creating an output directory, "
            "called PagePlusOutput, in the input directory.", callback=transform_output)] = None,
        dry_run: Annotated[bool, typer.Option(help="Perform a dry run without writing any files.")] = False):
    """
    Repairs TextRegions with invalid coordinates by either:
    1. Calculating a new convex hull from textlines if the region has textlines
    2. Deleting the region if it has no textlines
    """
    xml_files = collect_xml_files(map(Path, inputs))
    if not xml_files:
        raise FileNotFoundError('No xml files found in input directory')

    for xml_file in track(
            sorted(xml_files),
            description="Repairing dummy regions in files..."):
        filename = xml_file.name
        print('[green]Processing file:[/green] ' + filename)

        page = Page(xml_file)

        # Process TextRegions
        for region in page.regions.textregions:
            # Check if region has valid coordinates
            if region.get_coordinates(returntype="polygon") is None:
                if region.textlines:
                    print(
                        f"[yellow]Repairing TextRegion: {region.get_id()} - Calculating new convex hull[/yellow]")
                    # Calculate new convex hull from textlines
                    textline_coords = []
                    for line in region.textlines:
                        textline_coords.extend(
                            line.get_coordinates(
                                returntype="tuple"))
                    if textline_coords:
                        # Create convex hull from textline coordinates
                        from shapely.geometry import MultiPoint
                        hull = MultiPoint(textline_coords).convex_hull
                        region.update_coordinates(hull, 'polygon')
                        region.buffer(distance=5, direction='all')
                else:
                    print(
                        f"[red]Deleting TextRegion: {region.get_id()} - No textlines found[/red]")
                    page.delete_element(region.xml_element)

        if not dry_run:
            fout = xml_file if outputdir is None else determine_output_path(
                xml_file, outputdir, filename)
            logging.info(
                f'Wrote modified xml file to output directory: {fout}')
            page.save_xml(fout)


@app.command()
def top_tier_textregion(
        inputs: Annotated[List[str], typer.Argument(exists=True,
                                                    help="Paths or workspace to the files to be validated.",
                                                    callback=transform_inputs)] = None,
        outputdir: Annotated[Optional[str], typer.Option(
            help="Filename of the output directory. Default is creating an output directory, "
            "called PagePlusOutput, in the input directory.", callback=transform_output)] = None,
        dry_run: Annotated[bool, typer.Option(help="Perform a dry run without writing any files.")] = False):
    """
    Creates a convex hall for all textlines and deletes single text regions
    """
    xml_files = collect_xml_files(map(Path, inputs))
    if not xml_files:
        raise FileNotFoundError('No xml files found in input directory')

    for xml_file in track(
            sorted(xml_files),
            description="Creating top tier textregion in files..."):
        filename = xml_file.name
        print('[green]Processing file:[/green] ' + filename)

        page = Page(xml_file)

        # Process TextRegions
        if len(page.regions.textregions) > 1:
            top_tier_region = page.regions.textregions[0]
            top_tier_region.set_tag('paragraph')
            top_tier_region_xml = page.regions.textregions[0].xml_element
            for region in page.regions.textregions[1:]:
                # Check if region has valid coordinates
                if region.textlines:
                    top_tier_region.textlines.extend(region.textlines)
                    region_xml = region.xml_element
                    for line in region.textlines:
                        region_xml.remove(line.xml_element)
                        top_tier_region_xml.append(line.xml_element)
                page.delete_element(region.xml_element)
            textline_coords = []
            for line in top_tier_region.textlines:
                textline_coords.extend(
                    line.get_coordinates(returntype="tuple"))
            if textline_coords:
                # Create convex hull from textline coordinates
                from shapely.geometry import MultiPoint
                hull = MultiPoint(textline_coords).convex_hull
                top_tier_region.update_coordinates(hull, 'polygon')
                top_tier_region.buffer(distance=5, direction='all')
            top_tier_region.sort_baselines(mode='single_col')
        if not dry_run:
            fout = xml_file if outputdir is None else determine_output_path(
                xml_file, outputdir, filename)
            logging.info(
                f'Wrote modified xml file to output directory: {fout}')
            page.save_xml(fout)


@app.command()
def fit_into_parent(
        inputs: Annotated[List[str], typer.Argument(exists=True,
                                                    help="Paths or workspace to the files to be validated.",
                                                    callback=transform_inputs)] = None,
        outputdir: Annotated[Optional[str], typer.Option(
            help="Filename of the output directory. Default is creating an output directory, "
                 "called PagePlusOutput, in the input directory.", callback=transform_output)] = None,
        level: Annotated[List[TextLevel], typer.Option(
            help="Granularity levels to process: 'TextRegion', 'TableRegion', 'Textline', "
            " (default: TextRegion, Textline).")] = ("TextRegion", "Textline"),
        dry_run: Annotated[bool, typer.Option(help="Perform a dry run without writing any files.")] = False):
    """
    Fits TextRegions, TableRegions, and Textlines into their parent boundaries.
    This ensures that no element extends beyond its parent's boundaries.
    """
    xml_files = collect_xml_files(map(Path, inputs))
    if not xml_files:
        raise FileNotFoundError('No xml files found in input directory')

    for xml_file in track(
            sorted(xml_files),
            description="Fitting elements into parent boundaries..."):
        filename = xml_file.name
        print('[green]Processing file:[/green] ' + filename)

        page = Page(xml_file)
        page_size = page.get_coordinates('linearring')

        # Process TextRegions
        if 'TextRegion' in level:
            for region in page.regions.textregions:
                region.fit_into_parent(page_size)
                print(
                    f"[yellow]Fitting TextRegion: {region.get_id()} into page[/yellow]")

        # Process TableRegions
        if 'TableRegion' in level:
            for tableregion in page.regions.tableregions:
                tableregion.fit_into_parent(page_size)
                print(
                    f"[yellow]Fitting TableRegion: {tableregion.get_id()} into page[/yellow]")
                for cell in tableregion.tablecells:
                    cell.fit_into_parent(
                        tableregion.get_coordinates('linearring'))
                    print(
                        f"[yellow]Fitting TableCell: {cell.get_id()} into table[/yellow]")

        # Process Textlines
        if 'Textline' in level:
            for region in [
                *page.regions.textregions,
                    *page.regions.tableregions]:
                for line in region.textlines:
                    line.fit_into_parent()
                    print(
                        f"[yellow]Fitting Textline: {line.get_id()} into region[/yellow]")

        if not dry_run:
            fout = xml_file if outputdir is None else determine_output_path(
                xml_file, outputdir, filename)
            logging.info(
                f'Wrote modified xml file to output directory: {fout}')
            page.save_xml(fout)


@app.command()
def set_page_version(inputs: Annotated[List[str], typer.Argument(exists=True,
                                                                  help="Direct input of directories containing XML files.", callback=transform_inputs)] = None,
                     outputdir: Annotated[Optional[str], typer.Option(
                         help="Filename of the output directory. If not specified, input files will be overwritten.",
                         callback=transform_output)] = None,
                     version: Annotated[PcGtsVersion, typer.Option(help="Target PAGE XML version")] = PcGtsVersion.V2019_07_15,
                     dry_run: Annotated[bool, typer.Option(help="If True, no files will be modified.")] = False,
                     validate: Annotated[bool, typer.Option(help="If True, validate compatibility before conversion.")] = True) -> None:
    """
    Updates the PAGE XML version (xmlns and schemaLocation) of the input files.
    """
    xml_files = collect_xml_files(map(Path, inputs))
    if not xml_files:
        print("[red]No XML files found in input directories.[/red]")
        return

    print(f"[bold green]Updating PAGE XML version to {version.value}[/bold green]")
    for xml_file in track(xml_files, description="Processing files..."):
        try:
            page = Page(xml_file)
            
            # Validate compatibility if requested
            if validate:
                validation_result = page.validate_version_compatibility(version)
                
                if validation_result["errors"]:
                    print(f"[red]ERROR: Cannot convert {xml_file.name} to {version.value}[/red]")
                    for error in validation_result["errors"]:
                        print(f"  [red]• {error}[/red]")
                    continue
                
                if validation_result["warnings"]:
                    print(f"[yellow]WARNING: {xml_file.name} has compatibility issues with {version.value}[/yellow]")
                    for warning in validation_result["warnings"]:
                        print(f"  [yellow]• {warning}[/yellow]")
                
                compatibility_score = validation_result["compatibility_score"]
                if compatibility_score < 50:
                    print(f"[red]Compatibility score: {compatibility_score}% - conversion may result in data loss[/red]")
                elif compatibility_score < 80:
                    print(f"[yellow]Compatibility score: {compatibility_score}% - some features may be affected[/yellow]")
                else:
                    print(f"[green]Compatibility score: {compatibility_score}% - conversion should be safe[/green]")
            
            if dry_run:
                print(f"[yellow]DRY RUN: Would update {xml_file.name} to version {version.value}[/yellow]")
                continue
                
            # Update the PAGE version
            page.update_pcgts_version(version)
            
            # Determine output path
            fout = xml_file if outputdir is None else determine_output_path(xml_file, outputdir)
            
            # Save the updated file
            page.save_xml(fout)
            print(f"[green]Updated {xml_file.name} to version {version.value}[/green]")
            
        except Exception as e:
            print(f"[red]Error processing {xml_file.name}: {str(e)}[/red]")
            logging.error(f"Error processing {xml_file.name}: {str(e)}")


def _parse_user_defined(value: Optional[List[str]]) -> Optional[dict]:
    """Callback to parse user-defined metadata from key=value strings."""
    if value is None:
        return None
    user_defined_dict = {}
    for item in value:
        if "=" not in item:
            raise typer.BadParameter(
                f"Invalid format for user-defined metadata: '{item}'. "
                "Expected 'key=value'."
            )
        key, val = item.split("=", 1)
        user_defined_dict[key] = val
    return user_defined_dict


@app.command()
def set_metadata(inputs: Annotated[List[str], typer.Argument(exists=True,
                                                                  help="Direct input of directories containing XML files.", callback=transform_inputs)] = None,
                     outputdir: Annotated[Optional[str], typer.Option(
                         help="Filename of the output directory. If not specified, input files will be overwritten.",
                         callback=transform_output)] = None,
                     creator: Annotated[str, typer.Option(help="Creator of the metadata")] = None,
                     created: Annotated[datetime, typer.Option(help="Created date of the metadata")] = None,
                     last_change: Annotated[datetime, typer.Option(help="Last change date of the metadata")] = None,
                     comments: Annotated[str, typer.Option(help="Comments of the metadata")] = None,
                     user_defined_raw: Annotated[Optional[List[str]], typer.Option(
                         help="User defined metadata in 'key=value' format. Can be specified multiple times."
                     )] = None,
                     new: Annotated[bool, typer.Option(help="If True, a new metadata is created (old metadata is overwritten).")] = False,
                     default: Annotated[bool, typer.Option(help="If True, a default metadata is created.")] = False,
                     dry_run: Annotated[bool, typer.Option(help="If True, no files will be modified.")] = False) -> None:
    """
    Updates the PAGE XML metadata of the input files.
    """
    xml_files = collect_xml_files(map(Path, inputs))
    if not xml_files:
        print("[red]No XML files found in input directories.[/red]")
        return

    user_defined = _parse_user_defined(user_defined_raw)

    print(f"[bold green]Updating PAGE XML metadata[/bold green]")
    print(f"Found {len(xml_files)} XML files to process.")
    print(f" New: {new}")
    for xml_file in track(xml_files, description="Processing files..."):
        try:
            page = Page(xml_file)
            if default:
                page.set_metadata(None, new)
            else:
                metadata = page.get_metadata()
                metadata.creator = creator if creator is not None else metadata.creator
                metadata.created = created if created is not None else metadata.created
                metadata.last_change = last_change if last_change is not None else metadata.last_change
                metadata.comments = comments if comments is not None else metadata.comments
                metadata.user_defined = user_defined if user_defined is not None else metadata.user_defined
                page.set_metadata(metadata, new)
            if not dry_run:
                fout = xml_file if outputdir is None else determine_output_path(xml_file, outputdir)
                page.save_xml(fout)
            print(f"[green]Updated {xml_file.name} to metadata[/green]")
        except Exception as e:
            print(f"[red]Error processing {xml_file.name}: {str(e)}[/red]")
            logging.error(f"Error processing {xml_file.name}: {str(e)}")


if __name__ == "__main__":
    app()
