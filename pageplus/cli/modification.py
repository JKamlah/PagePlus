from pathlib import Path
from typing import List, Optional

import typer
from rich.progress import track
from typing_extensions import Annotated

from pageplus.io.logger import logging
from pageplus.utils.fs import collect_xml_files, determine_output_path, transform_inputs
from pageplus.models.page import Page

app = typer.Typer()


@app.command()
def repair(inputs: Annotated[List[str], typer.Argument(exists=True, help="Direct input of directories containing XML files.",
                                                      callback=transform_inputs)] = None,
        outputdir: Annotated[Optional[str], typer.Option(
            help="Filename of the output directory. Default is creating an modified directory.")] = None,
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
    print(inputs)
    return
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
                line.validate_baseline()
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
        inputs: Annotated[List[str], typer.Argument(exists=True, help="Paths or workspace to the PAGE XML files to be processed.")] = None,
        outputdir: Annotated[Optional[str], typer.Option(
            help="Filename of the output directory. Default is creating an output directory, called PagePlusOutput, in the input directory.")] = None,
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
        inputs: Annotated[List[str], typer.Argument(exists=True, help="Paths or workspace to the PAGE XML files to be processed.")] = None,
        overwrite: Annotated[bool, typer.Option(help="If True, ignores outputdir and overwrites input data.")] = False,
        outputdir: Annotated[Optional[str], typer.Option(
            help="Filename of the output directory. Default is creating an output directory, called PagePlusOutput, in the input directory.")] = None
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
            for line in textregion.textlines:
                page.delete_element(line.xml_element)

        # Determine output file path and write the modified XML file
        fout = xml_file if overwrite else determine_output_path(xml_file, outputdir, filename)
        logging.info(f'Wrote modified xml file to output directory: {fout}')
        page.save_xml(fout)


@app.command()
def extend_lines(
        inputs: Annotated[List[str], typer.Argument(exists=True, help="Paths or workspace to the PAGE XML files to be processed.")] = None,
        outputdir: Annotated[Optional[str], typer.Option(
            help="Filename of the output directory. Default is creating an output directory, called PagePlusOutput, in the input directory.")] = None,
        distance: Annotated[int, typer.Option(help="Distance (in pixel) of extension.")] = 16,
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
                    line.fit_into_parent()
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
        inputs: Annotated[List[str], typer.Argument(exists=True, help="Paths or workspace to the PAGE XML files to be processed.")] = None,
        outputdir: Annotated[Optional[str], typer.Option(
            help="Filename of the output directory. Default is creating an output directory, called PagePlusOutput, in the input directory.")] = None,
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
        inputs: Annotated[List[str], typer.Argument(exists=True, help="Paths or workspace to the PAGE XML files to be processed.")] = None,
        outputdir: Annotated[Optional[str], typer.Option(
            help="Filename of the output directory. Default is creating an output directory, called PagePlusOutput, in the input directory.")] = None,
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
            textregion.merge_splitted_lines(merge_lines_gap_x, merge_lines_gap_y)

    for xml_file in track(xml_files, description="Sort and merge Textlines.."):
        filename = xml_file.name
        logging.info(f'Processing file: {filename}')

        page = Page(xml_file)
        process_page_for_sorting_and_merging(page, merge_lines_gap_x, merge_lines_gap_y)

        fout = xml_file if overwrite else determine_output_path(xml_file, outputdir, filename)
        logging.info(f'Wrote modified xml file to output directory: {fout}')
        page.save_xml(fout)


if __name__ == "__main__":
    app()
