#!/usr/bin/env python3
import unicodedata
from collections import defaultdict, OrderedDict, Counter
from pathlib import Path
from typing import List, Optional
from typing_extensions import Annotated

import typer
from rich.progress import Progress, SpinnerColumn, TextColumn, BarColumn, TimeRemainingColumn

from pageplus.utils.fs import transform_inputs
from pageplus.utils.fs import collect_xml_files
from pageplus.models.page import Page
from pageplus.utils.guidelines.lib.evaluation import validate_with_guidelines, categorize, missing_unicode
from pageplus.utils.guidelines.lib.functools import get_defaultdict
from pageplus.utils.guidelines.lib.io import create_json, set_output
from pageplus.utils.guidelines.lib.processhandler import Mappinghandler, Evaluatehandler
from pageplus.utils.guidelines.lib.profile_export import export_profile_to_csv
from pageplus.utils.guidelines.lib.report import summarize, create_report, ReportCollector, write_structured_report
from pageplus.utils.guidelines.lib.text_analyzer import FileAnalysis


app = typer.Typer(
    help="GTReval: A tool for evaluating ground truth text against OCR-D guidelines.",
    rich_help_panel="Tools"
)


# Command line arguments.
@app.command()
def evaluate_text(
    inputs: Annotated[List[str], typer.Argument(exists=True,
                                                help="Paths or workspace to the PAGE XML files to be processed.",
                                                callback=transform_inputs)] = None,
    output: Annotated[Optional[Path], typer.Option("-o", "--output", help="Filename of the output report, if none is given the result is printed to stdout.")] = None,
    json: Annotated[bool, typer.Option("-j", "--json", help="Will also output the all results as json file (including the guideline_violations).")] = False,
    custom_categories: Annotated[List[str], typer.Option("-c", "--custom-categories", help="Customized unicodedata categories.")] = [""],
    statistical_categories: Annotated[List[str], typer.Option("-s", "--statistical-categories", help='Customized unicodedata categories. "all" prints information about all unicode glyphs ordered by occurence. The other options ar "L" for Letter, "Z" for Separator, "P" for Punctuation, "M" for Mark,"N" for Number, "S" for Symbol,i "C" for Other')] = ["all"],
    missing_unicodes: Annotated[Optional[List[str]], typer.Option("-m", "--missing-unicodes", help="Print missing unicodes in the dataset by either a profile from profiles/rules/missing_unicode.json, a unicode rang e.g. , '0x0000-0x007F, 0x0100-0x017F'")] = None,
    addinfo: Annotated[List[str], typer.Option("-a", "--addinfo", help="Add information, such as unicode name and/or code to output")] = ["name"],
    guideline: Annotated[Optional[str], typer.Option("-g", "--guideline", help="Guidelines for the automatic revaluation")] = None,
    textnormalization: Annotated[str, typer.Option("-t", "--textnormalization", help="Unicode text normalization")] = "NFC",
    report_data: Annotated[Optional[Path], typer.Option("--report-data", help="Write structured report entries to this path (JSON or CSV). Format defaults to JSON or is inferred from the filename suffix.")] = None,
    report_data_format: Annotated[Optional[str], typer.Option("--report-data-format", help="Explicit format for structured report data; overrides filename suffix.")] = None,
    from_gui: bool = typer.Option(False, help="Internal flag for GUI usage.", hidden=True)
):
    """
    Reads text files, evaluate the unicode character and creates a report
    :return:
    """
    xml_files = collect_xml_files(map(Path, inputs))
    valid_norm = {'NFC', 'NFKC', 'NFD', 'NFKD'}
    if textnormalization not in valid_norm:
        raise typer.BadParameter('Expected one of NFC/NFKC/NFD/NFKD')

    if report_data_format and not report_data:
        raise typer.BadParameter('--report-data-format requires --report-data', param_hint='--report-data-format')
    report_data_path = Path(report_data) if report_data else None

    evalu = Evaluatehandler(xml_files, output, json, custom_categories, statistical_categories,
                            addinfo, guideline, textnormalization,
                            report_data=report_data_path, report_data_format=report_data_format)

    results = defaultdict(OrderedDict)

    # Initialize data structures
    get_defaultdict(results, 'single')
    get_defaultdict(results, 'combined')
    get_defaultdict(results['combined'], 'all')
    results['combined']['all']['glyph'] = Counter()
    results['combined']['all']['codepoints'] = defaultdict(int)
    results['combined']['all']['combined glyph'] = Counter()

    all_analyses = [FileAnalysis(fname, evalu.textnormalization) for fname in evalu.files]

    for i, analysis in enumerate(all_analyses):
        # Store path index
        results['path_indexes'][i] = analysis.path.absolute()

        # Per-file results
        file_data = results['single'][i]
        file_data['all'] = {
            'glyph': analysis.total_glyphs,
            'codepoints': analysis.total_codepoints,
            'combined glyph': analysis.combined_glyphs
        }
        file_data['details'] = {
            'text': analysis.texts,
            'glyphs_per_line': analysis.glyphs_per_line,
            'codepoints_per_line': analysis.codepoints_per_line
        }

        # Aggregate results into 'combined'
        results['combined']['all']['glyph'].update(analysis.total_glyphs)
        for code, count in analysis.total_codepoints.items():
            results['combined']['all']['codepoints'][code] += count
        results['combined']['all']['combined glyph'].update(analysis.combined_glyphs)

    # Process combined results
    categorize(results, category='combined')
    for custom_cat in evalu.custom_categories:
        if custom_cat:
            categorize(results, category=custom_cat)

    # Process per-file results
    for i in results['single']:
        # Create a temporary structure for categorize function
        temp_results = defaultdict(OrderedDict)
        temp_results['combined']['all'] = results['single'][i]['all']
        categorize(temp_results, category='combined')
        # Merge categorized data back
        if 'cat' in temp_results['combined']:
            results['single'][i]['cat'] = temp_results['combined']['cat']

        for custom_cat in evalu.custom_categories:
            if custom_cat:
                categorize(temp_results, category=custom_cat)
        if 'usr' in temp_results['combined']:
            results['single'][i]['usr'] = temp_results['combined']['usr']

    # Find missing unicode glyphs in the combined results
    if missing_unicodes:
        for missing_unicode_profile in missing_unicodes:
            missing_unicode(results, evalu, profile=missing_unicode_profile)

    # Validate the text against the guidelines
    if guideline:
        validate_with_guidelines(results, evalu)

        # Aggregate guideline violations
        results['combined']['guideline_violations_summary'] = Counter()
        for i in results['single']:
            if 'guideline_violations_summary' in results['single'][i]:
                results['combined']['guideline_violations_summary'].update(results['single'][i]['guideline_violations_summary'])
        import logging
        logging.info(results['combined']['guideline_violations_summary'])

    # Summarize category data for combined results
    for section in ['cat', 'usr']:
        if section in results['combined'].keys():
            for key in set(results['combined'][section].keys()):
                summarize(results['combined'][section], key)

    # Summarize for per-file results
    for i in results['single']:
        for section in ['cat', 'usr']:
            if section in results['single'][i].keys():
                for key in set(results['single'][i][section].keys()):
                    summarize(results['single'][i][section], key)

    # Don't need codepoints information anymore
    if 'codepoints' in results['combined']['all']:
        del results['combined']['all']['codepoints']
    for i in results['single']:
        if 'codepoints' in results['single'][i]['all']:
            del results['single'][i]['all']['codepoints']

    if from_gui:
        return results

    # Result output
    set_output(evalu)
    collector = ReportCollector() if evalu.report_data else None
    create_report(results, evalu, collector=collector)
    if evalu.report_data and collector is not None:
        write_structured_report(collector.as_records(), evalu.report_data, evalu.report_data_format)
    if evalu.json:
        create_json(results, evalu.output)
    return results


@app.command('export-profiles')
def export_profiles(
    profiles: Annotated[List[Path], typer.Argument(help="Paths to the profile definitions.", exists=True)],
    output_dir: Annotated[Path, typer.Option("-o", "--output-dir", help="Directory to write the CSV files to.")],
    overwrite: Annotated[bool, typer.Option("--overwrite", help="Overwrite existing CSV files.")] = False
):
    """Convert GTReval profile definitions into choco-mufin compatible CSV tables."""

    if not profiles:
        raise typer.BadParameter('Provide at least one profile definition', param_hint='profiles')

    generated = []
    output_dir = Path(output_dir)
    for profile in profiles:
        paths = export_profile_to_csv(Path(profile), output_dir, overwrite=overwrite)
        generated.extend(paths)

    if not generated:
        typer.echo('No CSV files generated.')
    else:
        for path in generated:
            typer.echo(path)


@app.command()
def mapping_text(
    inputs: Annotated[List[str], typer.Argument(exists=True,
                                                help="Paths or workspace to the PAGE XML files to be processed.",
                                                callback=transform_inputs)] = None,
    guideline: Annotated[str, typer.Option("-g", "--guideline", help="Guidelines for the automatic revaluation.")] = "GT4Hist",
    textnormalization: Annotated[str, typer.Option("-t", "--textnormalization", help="Unicode text normalization.")] = "NFC",
    dry_run: Annotated[bool, typer.Option("--dry-run", help="Don't store the ground truth text changes.")] = False,
):
    """
    Mapping the glyphs of PAGE XML files based on a guideline profile.
    """
    xml_files = collect_xml_files(map(Path, inputs))
    handler = Mappinghandler(xml_files, guideline, textnormalization)
    change_log = {}

    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        BarColumn(),
        TextColumn("[progress.percentage]{task.percentage:>3.0f}%"),
        TimeRemainingColumn(),
        transient=True,
    ) as progress:
        task_files = progress.add_task("[red]Mapping text glyphs...", total=len(xml_files))
        for xml_path in xml_files:
            try:
                print("Processing file: ", xml_path.name)
                page = Page(xml_path)
                is_modified = False
                for region in page.regions.textregions:
                    for line in region.textlines:
                        original_text = line.get_text()
                        if not original_text:
                            continue
                        # Apply Unicode normalization first
                        unicode_normalized_text = unicodedata.normalize(textnormalization, original_text)

                        # Apply guideline normalization
                        guideline_normalized_text = handler.mapping_by_guideline(
                            unicode_normalized_text, line.get_id(), xml_path.name, mode='deterministic'
                        )

                        if original_text != guideline_normalized_text:
                            line.update_text(guideline_normalized_text)
                            is_modified = True
                            change_log[(xml_path.name, line.get_id())] = {
                                'original': original_text,
                                'new': guideline_normalized_text
                            }

                if is_modified and not dry_run:
                    page.save_xml(xml_path)

                progress.update(task_files, advance=1)
            except Exception as e:
                typer.secho(f"Error processing {xml_path.name}: {e}", fg=typer.colors.RED)
                progress.update(task_files, advance=1)

    # --- Summary Report ---
    typer.echo("\n--- Mapping Summary ---")
    if not handler.replacement_counts:
        typer.echo("No replacements were made.")
        return

    # 1. Total rule counts
    total_rule_counts = Counter()
    for filename, rules in handler.replacement_counts.items():
        for rule, line_counts in rules.items():
            total_rule_counts[rule] += sum(line_counts.values())

    typer.secho("\nTotal Replacements by Rule:", bold=True)
    for rule, count in total_rule_counts.items():
        typer.echo(f"  - {rule}: {count} replacements")

    # 2. Detailed changes per line
    typer.secho("\nDetailed Changes by File:", bold=True)
    # Iterate over files that had replacements
    for filename, rules in sorted(handler.replacement_counts.items()):
        typer.secho(f"\nFile: {filename}", fg=typer.colors.CYAN)

        # Collect all unique line_ids that were changed in this file
        changed_lines_in_file = set()
        for rule, line_counts in rules.items():
            for line_id in line_counts.keys():
                changed_lines_in_file.add(line_id)

        # For each changed line, print its details
        for line_id in sorted(list(changed_lines_in_file)):
            typer.echo(f"  Line: {line_id}")

            # Look up the before/after text from change_log
            log_entry = change_log.get((filename, line_id))
            if not log_entry:
                typer.echo("    (Could not find original/new text in log)")
                continue

            # Print the rules applied to this specific line
            typer.echo("    Applied Rules:")
            for rule, line_counts in rules.items():
                if line_id in line_counts:
                    count = line_counts[line_id]
                    typer.echo(f"      - {rule} ({count} replacements)")

            typer.secho("    Original: ", fg=typer.colors.RED, nl=False)
            typer.echo(log_entry['original'])
            typer.secho("    New:      ", fg=typer.colors.GREEN, nl=False)
            typer.echo(log_entry['new'])

    return {
        "replacement_counts": handler.replacement_counts,
        "change_log": change_log
    }


if __name__ == '__main__':
    app()
