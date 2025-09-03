from pathlib import Path
from typing import List
from importlib import util
import re
from collections import Counter

import typer
from rich import print
from rich.style import Color
from rich.table import Table
from rich.progress import track
from typing_extensions import Annotated

from pageplus.utils.counter import PageCounter
from pageplus.io.logger import logging
from pageplus.utils.fs import collect_xml_files
from pageplus.models.page import Page
from pageplus.utils.fs import transform_inputs, transform_input
from pageplus.utils.constants import ProfileLevel
from pageplus.utils.profile import profile, ProfileFnRet
from pageplus.cli.export import transform_substitutions


app = typer.Typer()


@app.command()
def statistics(inputs: Annotated[List[str],
                                 typer.Argument(exists=True,
                                                help="Paths to the XML files to be checked.",
                                                callback=transform_inputs)] = None):
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
    counters = {}
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
        counters[filename] = page_counter
        # Aggregate statistics for all pages
        pagescounter += page_counter

    # Log cumulative statistics
    pagescounter.statistics(
        pre_text=f"Statistics for all {
            len(xml_files)} PAGE-XML")
    counters[f'All {len(xml_files)} PAGE-XML'] = pagescounter
    return counters


@app.command()
def confidences(inputs: Annotated[List[str],
                                  typer.Argument(exists=True,
                                                 help="Paths to the XML files to be checked.",
                                                 callback=transform_inputs)] = None,
                output_filename: Annotated[str,
                                           typer.Option(help="Name of the output file.")] = 'output'):
    """
    Calculate the mean confidence of each page and return a list of pages which are beneath a specific threshold and/or
    just print a report of all pages
    Args:
        inputs: An iterator of Path objects pointing to the XML files to be checked.
        output_filename: Name of the output file
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
        all_confs[str(xml_file)]['median'] = nanmedian(
            array(list(page_confs.values())))
        all_confs[str(xml_file)]['mean'] = nanmean(
            array(list(page_confs.values())))
        all_confs[str(xml_file)]['state'] = 'initial'

    all_median = nanmedian([confs['median'] for confs in all_confs.values()])
    Q1 = nanmedian(([confs['median']
                   for confs in all_confs.values() if confs['median'] < all_median]))
    Q3 = nanmedian(([confs['median']
                   for confs in all_confs.values() if confs['median'] > all_median]))
    IQR = Q3 - Q1
    for confs in all_confs.values():
        if isnan(confs['median']):
            confs['state'] = '0 (empty)'
        elif confs['median'] < Q1 - (1.5 * IQR):
            confs['state'] = '1 (Very low)'
        elif confs['median'] < Q1:
            confs['state'] = '2 (Low)'
        elif confs['median'] < all_median:
            confs['state'] = '3 (Moderate)'
        elif confs['median'] < Q3:
            confs['state'] = '4 (Median)'
        elif confs['median'] < Q3 + (1.5 * IQR):
            confs['state'] = ('5 (High)')
        else:
            confs['state'] = '6 (Very high)'

    table = Table(title="[green]Confidences[/green]")
    table.add_column("Filename", justify="right", no_wrap=True)
    table.add_column("Confidence", justify="right", no_wrap=True)
    table.add_column("Confidence level\n(Very low=<Q1-1.5*IQR\nLow=Q1–1.5*IQR-Q1\nModerate=Q1–Median\nMedian=Median–Q3\n"
                     "High=Q3–Q3+1.5*IQR\nVery high=>Q3+1.5*IQR)", justify="left", no_wrap=True)

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
    ws.append(["Seite", "Band", "Filename",
               "Confidence"])
    for idx, (filenames, confs) in enumerate(all_confs.items()):
        ws.append([f"{idx + 1}", "1951" "", f"{Path(filenames).name}",
                   f"{confs['median']:.5f}"])
        # Create a Color object using a color name
        color = Color.parse(f"{colors.get(confs['state'][0])}")
        # Get the hexadecimal value of the color
        hex_value = color.get_truecolor().hex
        color_argbhex = f"FF{hex_value[1:].upper()}"
        if colors.get(confs['state'][0]) != 'bright_white':
            # ws.cell(row=idx+2, column=4).font = Font(color=color_argbhex)
            ws.cell(
                row=idx + 2,
                column=4).fill = PatternFill(
                start_color=color_argbhex,
                fill_type="solid")

    # Save the workbook to a file
    wb.save(f"{output_filename}.xlsx")

    return table


if (spec := util.find_spec('pageplus.utils.dinglehopper.edit_distance')) is not None:
    from pageplus.cli.dinglehopper import get_metrics, summarize_metrics

    @app.command()
    @profile('pageplus')
    def compare(
            gt: Annotated[str, typer.Argument(help="Ground Truth file or directory path or workspace, e.g. main.",
                                              exists=True, callback=transform_input)] = ...,
            ocr: Annotated[str, typer.Argument(help="OCR file or directory path or workspace, e.g. main:modified.",
                                               exists=True, callback=transform_input)] = ...,
            text_filter: Annotated[str, typer.Option(
                help="A regular expression, if specific textlines should be filtered")] = None,
            region_tagfilter: Annotated[str, typer.Option(
                help="A regular expression, if specific textlines should be filtered")] = None,
            textline_tagfilter: Annotated[str, typer.Option(
                help="A regular expression, if specific textlines should be filtered")] = None,
            substitutions: Annotated[List[str], typer.Option(
                help="Regex substitutions with pattern==>replacement,...]", callback=transform_substitutions)] = [''],
            profile: Annotated[str, typer.Option(
                help="Profile function with tag (default: no profiling active.")] = '',
            profilelevel: Annotated[List[ProfileLevel],
                                    typer.Option(
                help="Level of profiling. Options: 'stats' (always true), 'params', 'results', 'analytics', 'summary'")
            ] = ("stats", "params", "analytics", "summary"),
    ):
        """
        Compare the PAGE/ALTO/text document GT against the document OCR using PagePlus Profiling output.
        """
        compare.profile = ProfileFnRet()
        compare.profile.name = profile
        compare.profile.stats = {'pages': 0, 'lines': 0}
        print(f"Starting PagePlus comparison with gt={gt} ocr={ocr}")
        # Your existing logic here
        if 'params' in profilelevel:
            compare.profile.params = {'text-filter': text_filter,
                                      'region-tagfilter': region_tagfilter,
                                      'textline-tagfilter': textline_tagfilter}

        # Read XML
        gt_xml_files = collect_xml_files(map(Path, [gt]))
        # Raise error if no xml files are found
        if not gt_xml_files:
            raise FileNotFoundError('No xml files found in input directory')

        compare.profile.dir = gt_xml_files[0].parent.absolute() if len(
            ocr) > 0 else ''

        reg_filter = re.compile(
            rf"{text_filter}") if text_filter is not None else '.'
        all_diff = Counter()
        all_metrics = []
        ocr_path = Path(ocr)
        for gt_file in track(gt_xml_files, description="Comparing gt-files.."):
            ocr_file = ocr_path.joinpath(gt_file.name)
            if not ocr_file.exists():
                continue
            # Read XML content
            gt_page = Page(gt_file)
            ocr_page = Page(ocr_file)
            text_dict = {}
            page_diff = Counter()
            page_metrics = []
            # Find Textlines
            for gt_region, ocr_region in zip(
                    gt_page.get_ordered_regions(), ocr_page.get_ordered_regions()):
                if gt_region.get_id() != ocr_region.get_id():
                    continue
                tr_id = gt_region.get_id()
                if region_tagfilter is not None and region_tagfilter != gt_region.get_tag():
                    continue
                text_dict[tr_id] = {}
                for line_idx, (gt_line, ocr_line) in enumerate(
                        zip(gt_region.textlines, ocr_region.textlines)):
                    gt_text, ocr_text = gt_line.get_text(), ocr_line.get_text()
                    for (pattern, replacement) in substitutions:
                        gt_text = re.sub(
                            rf'{pattern}', rf'{replacement}', gt_text)
                        ocr_text = re.sub(
                            rf'{pattern}', rf'{replacement}', ocr_text)
                    if textline_tagfilter is not None and textline_tagfilter != gt_text:
                        continue
                    if text_filter is not None and not re.search(
                            reg_filter, gt_text):
                        continue
                    if 'analytics' in profilelevel:
                        print(gt_text + ' ==> ' + ocr_text)
                        if line_idx == len(gt_region.textlines) - 1:
                            page_metrics.append(get_metrics(gt_text, ocr_text))
                        else:
                            page_metrics.append(get_metrics(
                                gt_text + '\n', ocr_text + '\n'))

            if 'results' in profilelevel:
                compare.profile.results.append({gt_file.name: text_dict})
            compare.profile.stats['pages'] += any(
                [1 for region in text_dict.values() if len(region.values()) > 0])
            compare.profile.stats['lines'] += sum(
                [len(region.values()) for region in text_dict.values()])
            if 'analytics' in profilelevel:
                metrics = summarize_metrics(page_metrics) if len(
                    page_metrics) > 0 else {}
                all_metrics.extend(page_metrics)
                compare.profile.analytics.append({gt_file.name: metrics})
                all_diff.update(page_diff)
        if 'summary' in profilelevel:
            if 'analytics' in profilelevel:
                metrics = summarize_metrics(all_metrics)
                compare.profile.summary['analytics'] = metrics


@app.command()
def tags(
        inputs: Annotated[List[str], typer.Argument(exists=True,
                                                    help="Paths or workspace to the files to be validated.",
                                                    callback=transform_inputs)] = None,
        levels: Annotated[List[str], typer.Option(
            help="Granularity levels to process: 'TextRegion', 'TableRegion', 'Textline', "
            " (default: TextRegion, Textline).")] = ("TextRegion", "Textline", "TableRegion")):
    """
    Analyzes tags with details across all pages.
    """
    xml_files = collect_xml_files(map(Path, inputs))
    if not xml_files:
        raise FileNotFoundError('No xml files found in input directory')

    tag_analysis = {}

    for xml_file in track(sorted(xml_files),
                          description="Analyzing tags in files..."):
        filename = xml_file.name
        print('[green]Processing file:[/green] ' + filename)

        page = Page(xml_file)

        # Get tag details for the page
        tag_details = page.get_tags(levels=levels, details=True)

        # Store the analysis in the dictionary
        tag_analysis[filename] = tag_details

        # Print summary for this file
        print(f'{filename}: {tag_details}')
        # for tag, count in tag_details.get('counts', {}).items():
        #     print(f"  - {tag}: {count} occurrences")

    return tag_analysis
