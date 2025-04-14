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
            help="Filename of the output directory. Default is creating an modified directory.",
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
        overwrite: Annotated[bool,
                          typer.Option(help="If True, ignores outputdir and overwrites input data.")] = False,
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
                fout = xml_file if overwrite else determine_output_path(xml_file, outputdir, filename)
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
            help="Filename of the output directory. Default is creating an modified directory.",
                                                      callback=transform_output)] = None,
        reading_order_mode='auto',
        overwrite: Annotated[bool, typer.Option(help="If True, ignores outputdir and overwrites input data.")] = False,
        dry_run: Annotated[bool, typer.Option(help="If True, the function will not write any files.")] = False):
    """
    Reassign IDs from Regions and Textlines
    Args:
        inputs: A list of paths to the PAGE XML files to be processed.
        dry_run: If True, the function will not write any files.
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
            fout = xml_file if overwrite else determine_output_path(xml_file, outputdir, filename)
            logging.info(f'Wrote modified xml file to output directory: {fout}')
            page.save_xml(fout)

@app.command()
def repair(inputs: Annotated[List[str], typer.Argument(exists=True, help="Direct input of directories containing XML files.",
                                                      callback=transform_inputs)] = None,
        outputdir: Annotated[Optional[str], typer.Option(
            help="Filename of the output directory. Default is creating an modified directory.",
                                                      callback=transform_output)] = None,
        overwrite: Annotated[bool, typer.Option(help="If True, ignores outputdir and overwrites input data.")] = False,
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
            fout = xml_file if overwrite else determine_output_path(xml_file, outputdir, filename)
            logging.info(f'Wrote modified xml file to output directory: {fout}')
            page.save_xml(fout)


@app.command()
def delete_text(
        inputs: Annotated[List[str], typer.Argument(exists=True,
                                                    help="Paths or workspace to the PAGE XML files to be processed.",
                                                    callback=transform_inputs)] = None,
        outputdir: Annotated[Optional[str], typer.Option(
                                    help="Filename of the output directory. Default is creating an output directory, "
                                 "called PagePlusOutput, in the input directory.", callback=transform_output)] = None,
        overwrite: Annotated[bool, typer.Option(help="If True, ignores outputdir and overwrites input data.")] = False,
        level: Annotated[
            str, typer.Option(help="Deletion level: region, word, or line.", case_sensitive=False)] = 'region',
):
    """
    Deletes text elements at the specified level in PAGE XML files.

    Args:
        inputs: Paths to the PAGE XML files to be processed.
        level: The level at which text elements will be deleted ('region', 'word', or 'line').
        outputdir: The directory where the modified XML files will be saved.
    """
    xml_files = collect_xml_files(map(Path, inputs))

    if not xml_files:
        raise FileNotFoundError('No XML files found in the input paths.')

    for xml_file in track(xml_files, description="Deleting text content.."):
        filename = xml_file.name
        logging.info(f'Processing file: {filename}')

        page = Page(xml_file)
        page.delete_textlevel(level)

        fout = xml_file if overwrite else determine_output_path(xml_file, outputdir, filename)
        logging.info(f'Wrote modified xml file to output directory: {fout}')
        page.save_xml(fout)


@app.command()
def delete_textlines(
        inputs: Annotated[List[str], typer.Argument(exists=True,
                                                    help="Paths or workspace to the PAGE XML files to be processed.",
                                                    callback=transform_inputs)] = None,
        outputdir: Annotated[Optional[str], typer.Option(
            help="Filename of the output directory. Default is creating an output directory, called PagePlusOutput, in the input directory.")] = None,
        overwrite: Annotated[bool, typer.Option(help="If True, ignores outputdir and overwrites input data.")] = False,
):
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
        fout = xml_file if overwrite else determine_output_path(xml_file, outputdir, filename)
        logging.info(f'Wrote modified xml file to output directory: {fout}')
        page.save_xml(fout)


@app.command()
def translate_lines(inputs: Annotated[List[str], typer.Argument(exists=True,
                                                    help="Paths or workspace to the PAGE XML files to be processed.",
                                                    callback=transform_inputs)] = None,
                    outputdir: Annotated[Optional[str], typer.Option(
                        help="Filename of the output directory. Default is creating an output directory, "
                        "called PagePlusOutput, in the input directory.", callback=transform_output)] = None,
                    xoff: Annotated[int, typer.Option(help="X Offset")] = 0,
                    yoff: Annotated[int, typer.Option(help="Y Offset.")] = 0,
                    overwrite: Annotated[bool,
                    typer.Option(help="If True, ignores outputdir and overwrites input data.")] = False,
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
            fout = xml_file if overwrite else determine_output_path(xml_file, outputdir, filename)
            logging.info(f'Wrote modified xml file to output directory: {fout}')
            page.save_xml(fout)


@app.command()
def extend_lines(
        inputs: Annotated[List[str], typer.Argument(exists=True,
                                                    help="Paths or workspace to the PAGE XML files to be processed.",
                                                    callback=transform_inputs)] = None,
        outputdir: Annotated[Optional[str], typer.Option(
            help="Filename of the output directory. Default is creating an output directory, "
                 "called PagePlusOutput, in the input directory.", callback=transform_output)] = None,
        distance: Annotated[int, typer.Option(help="Distance (in pixel) of extension.")] = 8,
        dim: Annotated[str, typer.Option(help="Dimension in which the buffer is performed")] = "all",
        rectify: Annotated[bool, typer.Option(help="Rectify the polygons")] = True,
        overwrite: Annotated[bool, typer.Option(help="If True, ignores outputdir and overwrites input data.")] = False,
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
            fout = xml_file if overwrite else determine_output_path(xml_file, outputdir, filename)
            logging.info(f'Wrote modified xml file to output directory: {fout}')
            page.save_xml(fout)


@app.command()
def pseudolinepolygon(
        inputs: Annotated[List[str], typer.Argument(exists=True,
                                                    help="Paths or workspace to the PAGE XML files to be processed.",
                                                    callback=transform_inputs)] = None,
        outputdir: Annotated[Optional[str], typer.Option(
            help="Filename of the output directory. Default is creating an output directory, called PagePlusOutput, "
                 "in the input directory.", callback=transform_output)] = None,
        overwrite: Annotated[bool, typer.Option(help="If True, ignores outputdir and overwrites input data.")] = False):
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

        fout = xml_file if overwrite else determine_output_path(xml_file, outputdir, filename)
        logging.info(f'Wrote modified xml file to output directory: {fout}')
        page.save_xml(fout)


@app.command()
def sort_and_merge(
        inputs: Annotated[List[str], typer.Argument(exists=True,
                                                    help="Paths or workspace to the PAGE XML files to be processed.",
                                                    callback=transform_inputs)] = None,
        outputdir: Annotated[Optional[str], typer.Option(
            help="Filename of the output directory. Default is creating an output directory, "
                 "called PagePlusOutput, in the input directory.", callback=transform_output)] = None,
        overwrite: Annotated[bool, typer.Option(help="If True, ignores outputdir and overwrites input data.")] = False,
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

        fout = xml_file if overwrite else determine_output_path(xml_file, outputdir, filename)
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
        level: Annotated[List[str], typer.Option(
                help="Granularity levels to process: 'region', 'textline', or both.",
                case_sensitive=False)] = ["region", "textline"],
        overwrite: Annotated[bool, typer.Option(help="If True, ignores outputdir and overwrites input data.")] = False,
        dry_run: Annotated[bool, typer.Option(help="Perform a dry run without writing any files.")] = False):
    """
    Removes empty textlines and empty regions
    """
    xml_files = collect_xml_files(map(Path, inputs))

    if not xml_files:
        raise FileNotFoundError('No xml files found in input directory')

    for xml_file in track(sorted(xml_files), description="Validating files..."):
        filename = xml_file.name
        print('[green]Checking file:[/green] ' + filename)

        page = Page(xml_file)

        # Merge cells into textregions
        for tableregion in page.regions.tableregions:
            for cell in tableregion.tablecells:
                page.regions.textregions.append(cell)

        for region in list(page.regions.textregions):
            del_count = 0
            for line in region.textlines:
                if 'textline' in level and not line.validate_text():
                    print(f"[red]{line.get_id()} removed.[/red]")
                    page.delete_element(line.xml_element)
                    del_count += 1
            if 'region' in level and del_count == len(region.textlines):
                print(f"[red]{region.get_id()} removed.[/red]")
                page.delete_element(region.xml_element)
        page.load_regions()

        if 'region' in level and page.regions.tableregions:
            for tableregion in page.regions.tableregions:
                if not tableregion.tablecells:
                    print(f"[red]{tableregion.get_id()} removed.[/red]")
                    page.delete_element(tableregion.xml_element)
            page.load_regions()

        if not dry_run:
            fout = xml_file if overwrite else determine_output_path(xml_file, outputdir, filename)
            logging.info(f'Wrote modified xml file to output directory: {fout}')
            page.save_xml(fout)

if __name__ == "__main__":
    app()
