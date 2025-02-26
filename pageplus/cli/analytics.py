from pathlib import Path
from typing import List

import typer
from rich import print
from rich.table import Table
from rich.progress import track
from typing_extensions import Annotated

from pageplus.analytics.counter import PageCounter
from pageplus.io.logger import logging
from pageplus.utils.fs import collect_xml_files
from pageplus.models.page import Page
from pageplus.utils.fs import transform_inputs

app = typer.Typer()

@app.command()
def statistics(
        inputs: Annotated[List[str],
        typer.Argument(exists=True, help="Paths to the XML files to be checked.", callback=transform_inputs)] = None):
    """
    Statistics about PAGE XML files.

    This function processes each specified XML file, collects statistics about
    text regions, text lines, and table regions within those regions.

    Args:
        inputs: An iterator of Path objects pointing to the XML files to be checked.

    Raises:
        FileNotFoundError: If no XML files are found in the given input paths.
    """
    xml_files = collect_xml_files(map(Path, inputs))
    # Raise error if no xml files are found
    if not xml_files:
        raise FileNotFoundError('No xml files found in input directory')

    # Create statistics for all pages
    pagescounter = PageCounter()

    # Loop through all XML files
    for xml_file in track(xml_files, description="Collecting statistics.."):
        filename = xml_file.name
        logging.info('Processing file: ' + filename)
        # Initialize Page object and PageCounter for the current file
        page = Page(xml_file)
        page_counter = PageCounter()

        # Collect statistics for the current page
        page_counter.textregions += page.counter(level='textregions')
        page_counter.tableregions += page.counter(level='tableregions')
        page_counter.textlines += page.counter(level='textlines')
        page_counter.words += page.counter(level='words')
        page_counter.glyphs += page.counter(level='glyphs')

        # Log statistics for the current page
        page_counter.statistics(pre_text=f"Statistics for {filename}")

        # Aggregate statistics for all pages
        pagescounter += page_counter

    # Log cumulative statistics
    pagescounter.statistics(pre_text=f"Statistics for all {len(xml_files)} PAGE-XML")

@app.command()
def confidences(
        inputs: Annotated[List[str],
        typer.Argument(exists=True, help="Paths to the XML files to be checked.", callback=transform_inputs)] = None,
        output_filename: Annotated[str, typer.Option(help="Name of the output file.")] = 'output'):
    """
    Calculate the mean confidence of each page and return a list of pages which are beneath a specific threshold and/or
    just print a report of all pages
    Args:
        inputs: An iterator of Path objects pointing to the XML files to be checked.

    Raises:
        FileNotFoundError: If no XML files are found in the given input paths.
    """
    from collections import defaultdict
    from numpy import array, nanmean, nanmedian, isnan
    from openpyxl import Workbook
    from openpyxl.styles import PatternFill

    xml_files = collect_xml_files(map(Path, inputs))
    # Raise error if no xml files are found
    if not xml_files:
        raise FileNotFoundError('No xml files found in input directory')

    # Create statistics for all pages
    all_confs = defaultdict(defaultdict)

    # Loop through all XML files
    for xml_file in track(xml_files, description="Collecting confidences.."):
        filename = xml_file.name
        logging.info('Processing file: ' + filename)
        # Initialize Page object and PageCounter for the current file
        page = Page(xml_file)
        page_confs = defaultdict(float)
        # loop through all xml files
        for textregion in page.regions.textregions:
            for textline in textregion.textlines:
                conf = textline.get_confidence()
                if conf:
                    page_confs[textline.get_id()] = conf
        all_confs[str(xml_file)]['confs'] = page_confs
        all_confs[str(xml_file)]['median'] = nanmedian(array(list(page_confs.values())))
        all_confs[str(xml_file)]['mean'] = nanmean(array(list(page_confs.values())))
        all_confs[str(xml_file)]['state'] = 'inital'

    all_median = nanmedian([confs['median'] for confs in all_confs.values()])
    Q1 = nanmedian(([confs['median'] for confs in all_confs.values() if confs['median'] < all_median]))
    Q3 = nanmedian(([confs['median'] for confs in all_confs.values() if confs['median'] > all_median]))
    IQR = Q3-Q1
    for confs in all_confs.values():
        if isnan(confs['median']):
            confs['state'] = '0 (empty)'
        elif confs['median'] < Q1-(1.5*IQR):
            confs['state'] = '1 (Very low)'
        elif confs['median'] < Q1:
            confs['state'] = '2 (Low)'
        elif confs['median'] < all_median:
            confs['state'] = '3 (Moderate)'
        elif confs['median'] < Q3:
            confs['state'] = '4 (Median)'
        elif confs['median'] < Q3+(1.5*IQR):
            confs['state'] = ('5 (High)')
        else:
            confs['state'] = '6 (Very high)'

    table = Table(title=f"[green]Confidences[/green]")
    table.add_column("Filename", justify="right", no_wrap=True)
    table.add_column("Confidence", justify="right", no_wrap=True)
    table.add_column(f"Confidence level\n(Very low=<Q1-1.5*IQR\nLow=Q1–1.5*IQR-Q1\nModerate=Q1–Median\nMedian=Median–Q3\n"
                     f"High=Q3–Q3+1.5*IQR\nVery high=>Q3+1.5*IQR)", justify="left", no_wrap=True)
    from rich.style import Color

    colors = {'0': "bright_white",
              '1': "red1",
              '2': "orange_red1",
              '3': "gold3",
              '4': "chartreuse4",
              '5': "green",
              '6': "cyan"}
    [table.add_row(f"[{colors.get(confs['state'][0])}]{Path(filenames).name}[/{colors.get(confs['state'][0])}]",
                   f"[{colors.get(confs['state'][0])}]{confs['median']:.5f}[/{colors.get(confs['state'][0])}]",
                   f"[{colors.get(confs['state'][0])}]{confs['state']}[/{colors.get(confs['state'][0])}]")
     for filenames, confs in all_confs.items()]
    print(table)
    # Create a new Excel workbook and select the active worksheet
    wb = Workbook()
    ws = wb.active

    # Populate the worksheet with data
    ws.append([f"Seite", f"Band", f"Filename",
                f"Confidence"])
    for idx, (filenames, confs) in enumerate(all_confs.items()):
            ws.append([f"{idx+1}", f"1951" f"", f"{Path(filenames).name}",
                f"{confs['median']:.5f}"])
            # Create a Color object using a color name
            color = Color.parse(f"{colors.get(confs['state'][0])}")
            # Get the hexadecimal value of the color
            hex_value = color.get_truecolor().hex
            color_argbhex = f"FF{hex_value[1:].upper()}"
            if colors.get(confs['state'][0]) != 'bright_white':
                #ws.cell(row=idx+2, column=4).font = Font(color=color_argbhex)
                ws.cell(row=idx+2, column=4).fill = PatternFill(start_color=color_argbhex,
                                                                fill_type="solid")

    # Save the workbook to a file
    wb.save(f"{output_filename}.xlsx")


if __name__ == "__main__":
    app()
