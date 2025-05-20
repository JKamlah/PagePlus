from collections import Counter
from difflib import SequenceMatcher
from pathlib import Path
from typing import List, Optional
from importlib import util
import subprocess
import sys

from rich import print
from rich.progress import track
from rich.table import Table
import typer
from typing_extensions import Annotated

from pageplus.io.logger import logging
from pageplus.utils.fs import collect_xml_files, determine_output_path, transform_inputs, transform_output
from pageplus.models.page import Page
from pageplus.utils.converter import strings_to_enum
from pageplus.utils.constants import TextLevel

app = typer.Typer()

if (spec := util.find_spec('spellchecker')) is None:
    @app.command()
    def install_spellchecker() -> None:
        """
        Before spellchecking via dictionary can be used, please use this install command
        to install Pure python spell checker based on work by Peter Norvig & Tyler Barrus       !
        """
        subprocess.check_call([sys.executable, "-m", "pip", "install", "-I", "pyspellchecker"])

else:
    from pageplus.utils.spellchecker.lib import SpellCheckerPP

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
        spell = SpellCheckerPP(language=language, distance=distance, tokenizer=_parse_words)
        spell._case_sensitive = True
        spell.ignore_last_character = ignore_last_character
        spell.leading_trailing_filter = ignore_leading_trailing
        user_text = ' '.join([Page(xml_file).extract_fulltext() for xml_file in xml_files]) \
            if workspace_dictionary else ''
        spell.extend_dictionary(user_words, user_text, workspace_word_length, workspace_word_frequency)
        replacements = Counter()
        # loop through all xml files
        for xml_file in xml_files:
            # get filename
            filename = xml_file.name
            page = Page(xml_file)
            logging.info('Spellchecking file: ' + filename)
            replacements.update(spell.check_page(page))
            if not dry_run:
                fout = xml_file if outputdir is None else determine_output_path(xml_file, outputdir, filename)
                logging.info(f'Wrote modified xml file to output directory: {fout}')
                page.save_xml(fout)
        if report:
            table = Table(title=f"[green]Replacements Overview[/green]")
            table.add_column("Count", justify="right")
            table.add_column(f"Inline Comparison")
            table.add_column(f"[green]Original[/green]", justify="right", style="green", no_wrap=True)
            table.add_column(f"[cyan]Replacement[/cyan]", justify="right", style="cyan", no_wrap=True)
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

            [table.add_row(f"{key}", inline_diff(var.split(' -> ')[0], var.split(' -> ')[1]),
                            f"[green]{var.split(' -> ')[0]}[/green]",
                            f"[cyan]{var.split(' -> ')[1]}[/cyan]")
             for (var, key) in dict(replacements.most_common()).items()]
            print(table)

@app.command()
def reassign_ids(inputs: Annotated[List[str], typer.Argument(exists=True,
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
            fout = xml_file if outputdir is None else determine_output_path(xml_file, outputdir, filename)
            logging.info(f'Wrote modified xml file to output directory: {fout}')
            page.save_xml(fout)

@app.command()
def repair(inputs: Annotated[List[str], typer.Argument(exists=True, help="Direct input of directories containing XML files.",
                                                      callback=transform_inputs)] = None,
        outputdir: Annotated[Optional[str], typer.Option(
            help="Filename of the output directory. If not specified, input files will be overwritten.",
                                                      callback=transform_output)] = None,
        dry_run: Annotated[bool, typer.Option(help="If True, the function will not write any files.")] = False,
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
                    line.convex_hull()
                if not line.validate_baseline(update=True):
                    line.update_baseline_coordinates(line._compute_baseline(position='bottom'))

            except Exception as e:
                logging.error(f"{line.get_id()}: Error during repair - {e}")

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
            fout = xml_file if outputdir is None else determine_output_path(xml_file, outputdir, filename)
            logging.info(f'Wrote modified xml file to output directory: {fout}')
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

        fout = xml_file if outputdir is None else determine_output_path(xml_file, outputdir, filename)
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
                        logging.info(f'Delete region: {textregion.get_id()} containing only textline {line.get_id()} with text {line.get_text()}')
                    else:
                        page.delete_element(line.xml_element)
                        logging.info(f'Delete textline: {line.get_id()} in region {textregion.get_id()} with text {line.get_text()}')
                        count += 1

        # Determine output file path and write the modified XML file
        fout = xml_file if outputdir is None else determine_output_path(xml_file, outputdir, filename)
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
            fout = xml_file if outputdir is None else determine_output_path(xml_file, outputdir, filename)
            logging.info(f'Wrote modified xml file to output directory: {fout}')
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
        rectify: Annotated[bool, typer.Option(help="Rectify the polygons")] = True,
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
                    line.buffer(distance=distance, direction=dim, rectangle=rectify)
                    line.fit_into_parent(parent_coords=page.page_coords(returntype='linearring'))
                    if cut_overlaps and idx > 0:
                        process_overlapping_lines(textregion, idx, line)
                except Exception as e:
                    logging.error(f"Error processing line {line.get_id()}: {e}")
        if not dry_run:
            fout = xml_file if outputdir is None else determine_output_path(xml_file, outputdir, filename)
            logging.info(f'Wrote modified xml file to output directory: {fout}')
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

    for xml_file in track(xml_files, description="Calculating Textline polygons.."):
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
                    logging.error(f"Error processing line {line.get_id()}: {e}")

        fout = xml_file if outputdir is None else determine_output_path(xml_file, outputdir, filename)
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
        fout = xml_file if outputdir is None else determine_output_path(xml_file, outputdir, filename)
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

    def process_page_for_sorting_and_merging(page, merge_lines_gap_x, merge_lines_gap_y):
        # Sorts and merges text lines in a single Page object.
        for textregion in page.regions.textregions:
            textregion.sort_lines()
            textregion.merge_split_up_lines(merge_lines_gap_x, merge_lines_gap_y)

    for xml_file in track(xml_files, description="Sort and merge Textlines.."):
        filename = xml_file.name
        logging.info(f'Processing file: {filename}')

        page = Page(xml_file)
        process_page_for_sorting_and_merging(page, merge_lines_gap_x, merge_lines_gap_y)

        fout = xml_file if outputdir is None else determine_output_path(xml_file, outputdir, filename)
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

    for xml_file in track(sorted(xml_files), description="Remove empty levels in files..."):
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
                        print(f"[orange3]Skip: {tableregion.get_tag()} - {tableregion.get_id()}[/orange3]")
                        continue
                    page.regions.textregions.append(cell)
        for ridx, region in enumerate(list(page.regions.textregions)):
            del_count = 0
            if (region_tagfilter is not None and region.get_tag() not in region_tagfilter) \
                or (skip_tag is not None and region.get_tag() in skip_tag):
                print(f"[orange3]Skip: {region.get_tag()} - {region.get_id()}[/orange3]")
                continue
            for line in region.textlines:
                if (textline_tagfilter is not None and line.get_tag() not in textline_tagfilter) \
                        or (skip_tag is not None and line.get_tag() in skip_tag):
                    print(f"[orange3]Skip: {line.get_tag()} - {line.get_id()}[/orange3]")
                    continue
                if 'Textline' in level and not line.validate_text():
                    print(f"[red]Textline removed: {line.get_id()}.[/red]")
                    page.delete_element(line.xml_element)
                    del_count += 1
            if ('TextRegion' in level or 'TableRegion' in level) and del_count == len(region.textlines):
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
            fout = xml_file if outputdir is None else determine_output_path(xml_file, outputdir, filename)
            logging.info(f'Wrote modified xml file to output directory: {fout}')
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
            scale = page.counter(level='textlines') / scale_min_area_by_maxlines
            scale = scale if 0.1 < scale < 1.0 else 1.0

        for textregion in page.regions.textregions:
            textregion_polygon = textregion.get_coordinates('polygon')
            if textregion_polygon is None:
                continue

            if textregion_polygon.area > split_min_area * scale:
                region_element = textregion.xml_element
                new_region_element = None

                for idx, region in enumerate(textregion.split_region_by_textlinecoords()):
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
            logging.info(f'Wrote modified xml file to output directory: {fout}')
            page.save_xml(fout)
        else:
            logging.info(
                f'[DRY RUN] Would write modified xml file to: '
                f'{xml_file if outputdir is None else determine_output_path(xml_file, outputdir, filename)}'
            )


if __name__ == "__main__":
    app()
