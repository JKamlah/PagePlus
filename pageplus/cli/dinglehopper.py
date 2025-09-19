import os
import re
import shutil
import string
import subprocess
import sys
import unicodedata
import webbrowser
from collections import Counter
from importlib import util
from pathlib import Path
from typing import List, Annotated, Literal

import requests
import typer
from rich import print

app = typer.Typer()


def _install() -> None:
    """
    Before dinglehopper can be used, please use this install command
    to install dinglehopper by Mike Gerber and the qurator team!
    """
    for fname in [
        'align.py',
        'edit_distance.py',
        'word_error_rate.py',
        'character_error_rate.py',
        'extracted_text.py',
        'ocr_files.py',
        'config.py',
        'templates/report.html.j2',
        'templates/report.html.js',
        'templates/report.json.j2',
        'templates/summary.html.j2',
            'templates/summary.json.j2']:
        url = 'https://raw.githubusercontent.com/qurator-spk/dinglehopper/master/src/dinglehopper/' + fname
        output_filename = Path(__file__).resolve().parent.parent.joinpath(
            'utils/dinglehopper/' + fname)
        output_filename.parent.mkdir(exist_ok=True)
        response = requests.get(url)
        if response.status_code == 200:
            with open(output_filename, 'wb') as file:
                file.write(response.content)
            print(
                f"[green]File downloaded successfully: {output_filename}[/green]")
            if fname == 'word_error_rate.py':
                shutil.copy(
                    output_filename,
                    output_filename.with_suffix('.old'))
                with open(output_filename, 'w') as f:
                    for line in output_filename.with_suffix(
                            '.old').open('r').readlines():
                        line = line.replace(
                            '            return old_word_break(c, index)',
                            '            return old_word_break(c)')
                        f.write(line)
            if fname in ['extracted_text.py', 'ocr_files.py']:
                shutil.copy(
                    output_filename,
                    output_filename.with_suffix('.old'))
                with open(output_filename, 'w') as f:
                    for line in output_filename.with_suffix(
                            '.old').open('r').readlines():
                        line = line.replace(
                            'from ocrd_utils import getLogger',
                            'from pageplus.io.logger import logging as log')
                        if 'getLogger' in line:
                            continue
                        f.write(line)
        else:
            print(
                f"[red]Failed to download file. Status code: {response.status_code}[/red]")


if (spec := util.find_spec('pageplus.utils.dinglehopper.edit_distance')) is None:

    @app.command()
    def install() -> None:
        """
        Before dinglehopper and profiling can be used, please use this install command
        to install dinglehopper by Mike Gerber and the qurator team!
        """
        _install()
        for req in [
            "jinja2",
            "uniseg",
            "MarkupSafe",
            "attrs",
            "multimethod",
            "rapidfuzz",
                "chardet"]:
            subprocess.check_call(
                [sys.executable, "-m", "pip", "install", "-I", req])

else:
    from pageplus.utils.constants import Environments
    from pageplus.utils.fs import transform_input, open_folder_default
    from pageplus.utils.workspace import Workspace
    from jinja2 import Environment, FileSystemLoader
    from markupsafe import escape

    from pageplus.utils.dinglehopper.align import score_hint, seq_align
    from pageplus.utils.dinglehopper.character_error_rate import character_error_rate_n
    from pageplus.utils.dinglehopper.extracted_text import ExtractedText
    from pageplus.utils.dinglehopper.ocr_files import extract
    from pageplus.utils.dinglehopper.word_error_rate import word_error_rate_n, words_normalized

    dh_workspace = Workspace(Environments.DINGLEHOPPER)

    # PACKAGE #
    @app.command(rich_help_panel="Package")
    def install() -> None:
        """ Updates dinglehopper by Mike Gerber and the qurator team! """
        _install()

    # DOCUMENTS #

    def count_diff(gt_in, ocr_in, *, differences=True, score_hint=None):

        if isinstance(gt_in, ExtractedText):
            if not isinstance(ocr_in, ExtractedText):
                raise TypeError()
            gt_things = gt_in.grapheme_clusters
            ocr_things = ocr_in.grapheme_clusters
        else:
            gt_things = gt_in
            ocr_things = ocr_in

        g_pos = 0
        o_pos = 0
        found_differences = []

        for k, (g, o) in enumerate(
                seq_align(gt_things, ocr_things, score_hint)):
            if g != o:
                # if isinstance(gt_in, ExtractedText):
                # gt_id = gt_in.segment_id_for_pos(g_pos) if g is not None else None
                # ocr_id = ocr_in.segment_id_for_pos(o_pos) if o is not None else None
                # Deletions and inserts only produce one id + None, UI must
                # support this, i.e. display for the one id produced
                if differences:
                    found_differences.append(f"{g} :: {o}")

            if g is not None:
                g_pos += len(g)
            if o is not None:
                o_pos += len(o)

        counted_differences = Counter(elem for elem in found_differences)

        return counted_differences

    def gen_diff_report(
            gt_in,
            ocr_in,
            css_prefix,
            joiner,
            none,
            *,
            differences=False,
            score_hint=None):
        gtx = ""
        ocrx = ""

        def format_thing(t, css_classes=None, id_=None):
            if t is None:
                html_t = none
                css_classes += " ellipsis"
            elif t == "\n":
                html_t = "<br>"
            else:
                html_t = escape(t)

            html_custom_attrs = ""

            # Set Bootstrap tooltip to the segment id
            if id_:
                html_custom_attrs += f'data-toggle="tooltip" title="{id_}"'

            if css_classes:
                return f'<span class="{css_classes}" {html_custom_attrs}>{html_t}</span>'
            else:
                return f"{html_t}"

        if isinstance(gt_in, ExtractedText):
            if not isinstance(ocr_in, ExtractedText):
                raise TypeError()
            gt_things = gt_in.grapheme_clusters
            ocr_things = ocr_in.grapheme_clusters
        else:
            gt_things = gt_in
            ocr_things = ocr_in

        g_pos = 0
        o_pos = 0
        found_differences = []

        for k, (g, o) in enumerate(
                seq_align(gt_things, ocr_things, score_hint)):
            css_classes = None
            gt_id = None
            ocr_id = None
            if g != o:
                css_classes = "{css_prefix}diff{k} diff".format(
                    css_prefix=css_prefix, k=k)
                if isinstance(gt_in, ExtractedText):
                    gt_id = gt_in.segment_id_for_pos(
                        g_pos) if g is not None else None
                    ocr_id = ocr_in.segment_id_for_pos(
                        o_pos) if o is not None else None
                    # Deletions and inserts only produce one id + None, UI must
                    # support this, i.e. display for the one id produced

                if differences:
                    found_differences.append(f"{g} :: {o}")

            gtx += joiner + format_thing(g, css_classes, gt_id)
            ocrx += joiner + format_thing(o, css_classes, ocr_id)

            if g is not None:
                g_pos += len(g)
            if o is not None:
                o_pos += len(o)

        counted_differences = dict(Counter(elem for elem in found_differences))

        return (
            """
            <div class="row">
               <div class="col-md-6 gt">{}</div>
               <div class="col-md-6 ocr">{}</div>
            </div>
            """.format(
                gtx, ocrx
            ),
            counted_differences,
        )

    def categories():
        return {
            "insertion": 0,
            "deletion": 0,
            "substitution": 0,
            "whitespace": 0,
            "punctuation": 0,
            "digits": 0,
            "ascii_uppercase": 0,
            "ascii_lowercase": 0,
        }

    def count_categories(text: str, categories: dict) -> dict:
        for char in text:
            if char in string.whitespace:
                categories["whitespace"] += 1
            elif char in string.punctuation:
                categories["punctuation"] += 1
            elif char in string.digits:
                categories["digits"] += 1
            elif char in string.ascii_uppercase:
                categories["ascii_uppercase"] += 1
            elif char in string.ascii_lowercase:
                categories["ascii_lowercase"] += 1
        return categories

    def get_metrics(gt: str,
                    ocr: str,
                    normalization: Literal['NFC',
                                           'NFKC',
                                           'NFD',
                                           'NFKD'] = 'NFC',
                    line_breaks=True,
                    warning_msg=True) -> dict:
        """Get the accuracy metrics for gt and ocr input."""
        counts = {}
        gt = unicodedata.normalize(normalization, gt)
        ocr = unicodedata.normalize(normalization, ocr)
        if warning_msg:
            if len(gt) == 0:
                print("[red]Warning: Ground Truth is empty.[/red]")
            if len(ocr) == 0:
                print("[red]Warning: Compare text is empty.[/red]")
        # Handle edge cases: Minimum of 1 character and 1 word for gt and ocr
        # to calculate accuracy
        if line_breaks:
            gt += '\n' if not gt.endswith('\n') else gt
            ocr += '\n' if not ocr.endswith('\n') else ocr

        w_diff, counts['word'] = (count_diff(re.sub(
            r'\s+', ' ', gt).split(' '), re.sub(r'\s+', ' ', ocr).split(' ')), len(gt.split(' ')))
        wec = sum([v for k, v in w_diff.items()]) if w_diff else 0
        wer = wec / counts['word'] if w_diff else 0
        c_diff, counts['character'] = count_diff(gt, ocr), len(gt)
        cec = sum([v for k, v in c_diff.items()]) if c_diff else 0
        cer = sum([v for k, v in c_diff.items()]) / \
            counts['character'] if c_diff else 0
        counts.update(count_categories(gt, categories()))
        metrics = {
            'count': counts,
            'error_rate': {
                'global': {
                    'word': wer,
                    'character': cer},
                'local': {}},
            'error_count': {
                'word': wec,
                'character': cec}}
        gt_string = ''.join([k.split(' :: ')[0].replace(
            'None', '') * v for k, v in c_diff.items()]) if c_diff else ''
        error_counts = count_categories(gt_string, categories())
        counts['deletion'] = sum([v for k, v in c_diff.items() if re.search(
            'None', k.split(' :: ')[0])]) if c_diff else 0
        counts['insertion'] = sum([v for k, v in c_diff.items() if re.search(
            'None', k.split(' :: ')[1])]) if c_diff else 0
        counts['substitution'] = sum(
            [v for k, v in c_diff.items() if 'None' not in k]) if c_diff else 0
        for error_key, error_count in error_counts.items():
            if error_key in [
                'insertion',
                'deletion',
                'substitution',
                'character',
                    'word']:
                error_count = metrics['count'][error_key]
            else:
                metrics['error_rate']['local'][error_key] = error_count / \
                    metrics['count'][error_key] if error_count != 0 and metrics['count'][error_key] != 0 else 0
            if error_key in ['word']:
                metrics['error_rate']['global'][error_key] = error_count / metrics['count'][
                    'word'] if error_count != 0 or \
                    metrics['count']['word'] != 0 else 0
            elif error_key in ['insertion', 'deletion', 'substitution', 'character']:
                metrics['error_rate']['global'][error_key] = error_count / \
                    metrics['count']['character'] if error_count != 0 or metrics['count']['character'] != 0 else 0
            metrics['error_count'][error_key] = error_count
        metrics['confusions'] = {
            'word': dict(w_diff),
            'character': dict(c_diff)}
        return metrics

    def summarize_metrics(data: list) -> dict:
        """Summarize the accuracy metrics for each run."""
        sum_metrics = get_metrics('', '', line_breaks=False, warning_msg=False)
        for cat in sum_metrics['count']:
            sum_metrics['count'][cat] = sum(
                [metrics['count'][cat] for metrics in data])
            sum_metrics['error_count'][cat] = sum(
                [metrics['error_count'][cat] for metrics in data])
            if cat in ['word']:
                sum_metrics['error_rate']['global'][cat] = sum_metrics['error_count'][cat] / sum_metrics['count'][
                    'word'] if (sum_metrics['error_count'][cat] != 0 and sum_metrics['count']['word'] != 0) else 0
            else:
                sum_metrics['error_rate']['global'][cat] = sum_metrics['error_count'][cat] / sum_metrics['count']['character'] if (
                    sum_metrics['error_count'][cat] != 0 and sum_metrics['count']['character'] != 0) else 0
            if cat not in [
                'insertion',
                'deletion',
                'substitution',
                'word',
                    'character']:
                sum_metrics['error_rate']['local'][cat] = sum_metrics['error_count'][cat] / sum_metrics['count'][cat] if (
                    sum_metrics['error_count'][cat] != 0 and sum_metrics['count'][cat] != 0) else 0
        for cat in sum_metrics['confusions']:
            confusion = Counter()
            [confusion.update(Counter(metrics['confusions'][cat]))
             for metrics in data]
            sum_metrics['confusions'][cat] = dict(confusion)
        return sum_metrics

    def json_float(value):
        """Convert a float value to an JSON float.

        This is here so that float('inf') yields "Infinity", not "inf".
        """
        if value == float("inf"):
            return "Infinity"
        elif value == float("-inf"):
            return "-Infinity"
        else:
            return str(value)

    def process(
        gt: str | bytes,
        ocr: str | bytes,
        report_prefix: str,
        reports_folder: str = ".",
        *,
        metrics: bool = True,
        differences: bool = False,
        textequiv_level: str = "region",
    ) -> None:
        """Check OCR result against GT.

        The @click decorators change the signature of the decorated functions, so we keep
        this undecorated version and use Click on a wrapper.
        """

        gt_text = extract(gt, textequiv_level=textequiv_level)
        ocr_text = extract(ocr, textequiv_level=textequiv_level)
        gt_words: List[str] = list(words_normalized(gt_text))
        ocr_words: List[str] = list(words_normalized(ocr_text))

        assert isinstance(gt_text, ExtractedText)
        assert isinstance(ocr_text, ExtractedText)
        cer, n_characters = character_error_rate_n(gt_text, ocr_text)
        char_diff_report, diff_c = gen_diff_report(
            gt_text,
            ocr_text,
            css_prefix="c",
            joiner="",
            none="·",
            score_hint=score_hint(cer, n_characters),
            differences=differences,
        )

        # {gt,ocr}_words must not be a generator, so we don't drain it for the differences
        # report.
        assert isinstance(gt_words, list)
        assert isinstance(ocr_words, list)
        wer, n_words = word_error_rate_n(gt_words, ocr_words)
        word_diff_report, diff_w = gen_diff_report(
            gt_words,
            ocr_words,
            css_prefix="w",
            joiner=" ",
            none="⋯",
            score_hint=score_hint(wer, n_words),
            differences=differences,
        )

        env = Environment(
            loader=FileSystemLoader(
                Path(__file__).resolve().parent.parent.joinpath('utils/dinglehopper/templates')
            )
        )

        env.filters["json_float"] = json_float

        for report_suffix in (".html", ".json"):
            template_fn = "report" + report_suffix + ".j2"

            if not os.path.isdir(reports_folder):
                os.mkdir(reports_folder)

            out_fn = os.path.join(
                reports_folder,
                report_prefix +
                report_suffix)

            template = env.get_template(template_fn)
            template.stream(
                gt=gt,
                ocr=ocr,
                cer=cer,
                n_characters=n_characters,
                wer=wer,
                n_words=n_words,
                char_diff_report=char_diff_report,
                word_diff_report=word_diff_report,
                metrics=metrics,
                differences=differences,
                diff_c=diff_c,
                diff_w=diff_w,
            ).dump(out_fn)

    def process_dir(
            gt,
            ocr,
            report_prefix,
            reports_folder,
            metrics,
            differences,
            textequiv_level):
        for gt_file in Path(gt).glob('*.xml'):
            gt_file = gt_file.name
            if 'mets.xml' in [gt_file.lower()]:
                continue
            gt_file_path = os.path.join(gt, gt_file)
            ocr_file_path = os.path.join(ocr, gt_file)

            if os.path.isfile(gt_file_path) and os.path.isfile(ocr_file_path):
                process(
                    gt_file_path,
                    ocr_file_path,
                    f"{gt_file}-{report_prefix}",
                    reports_folder=reports_folder,
                    metrics=metrics,
                    differences=differences,
                    textequiv_level=textequiv_level,
                )
            # else:
            #  print("Skipping {0} and {1}".format(gt_file_path, ocr_file_path))

    @app.command()
    def compare(
            gt: Annotated[str, typer.Argument(help="Ground Truth file or directory path or workspace, e.g. main.",
                                              exists=True, callback=transform_input)] = ...,
            ocr: Annotated[str, typer.Argument(help="OCR file or directory path or workspace, e.g. main:modified.",
                                               exists=True, callback=transform_input)] = ...,
            report_prefix: Annotated[str, typer.Argument(help="Prefix for the report files.")] = "report",
            reports_folder: Annotated[str, typer.Argument(help="Directory to store the report files. "
                                                               "Default: save into a Dinglehopper/Date/ "
                                                               "folder in the ocr folder.")] = ".",
            reports_folder_prefix: Annotated[str, typer.Option(help="Prefix for the report folder.")] = "report",
            metrics: Annotated[bool, typer.Option("--metrics/--no-metrics",
                                                  help="Enable/disable metrics and green/red.")] = True,
            differences: Annotated[bool, typer.Option(help="Enable reporting character and "
                                                           "word level differences.")] = False,
            textequiv_level: Annotated[str, typer.Option(help="PAGE TextEquiv level to extract text from.",
                                                         metavar="LEVEL")] = "line",
            open_folder: Annotated[bool, typer.Option(help="Opens the folder with the results after processing.")]
            = open_folder_default(),
            show_results: Annotated[bool, typer.Option(help="Opens the html version in "
                                                            "a browser after processing.")] = True):
        """
        Compare the PAGE/ALTO/text document GT against the document OCR.

        dinglehopper detects if GT/OCR are ALTO or PAGE XML documents to extract
        their text and falls back to plain text if no ALTO or PAGE is detected.

        The files GT and OCR are usually a ground truth document and the result of
        an OCR software, but you may use dinglehopper to compare two OCR results. In
        that case, use --no-metrics to disable the then meaningless metrics and also
        change the color scheme from green/red to blue.

        The comparison report will be written to $REPORTS_FOLDER/$REPORT_PREFIX.{html,json},
        where $REPORTS_FOLDER defaults to the current working directory and
        $REPORT_PREFIX defaults to "report". The reports include the character error
        rate (CER) and the word error rate (WER).

        By default, the text of PAGE files is extracted on 'region' level. You may
        use "--textequiv-level line" to extract from the level of TextLine tags.
        """
        print(f"Starting Dinglehopper comparison with gt={gt}, ocr={ocr}, "
              f"report_prefix={report_prefix}, reports_folder={reports_folder}, reports_folder={reports_folder_prefix},"
              f"metrics={metrics}, differences={differences}, textequiv_level={textequiv_level}")
        # Your existing logic here
        if os.path.isdir(gt):
            if not os.path.isdir(ocr):
                typer.echo(
                    "OCR must be a directory if GT is a directory",
                    err=True)
                raise typer.Exit(code=1)
            else:
                reports_folder = reports_folder if reports_folder != '.' else str(
                    Path(ocr).joinpath('Dinglehopper') .joinpath(reports_folder_prefix).absolute())
                Path(reports_folder).mkdir(parents=True, exist_ok=True)
                process_dir(gt,
                            ocr,
                            report_prefix,
                            reports_folder,
                            metrics,
                            differences,
                            textequiv_level,
                            )
                pass
        else:
            reports_folder = reports_folder if reports_folder != '.' else str(Path(ocr).parent.joinpath('Dinglehopper').joinpath(reports_folder_prefix).absolute())
            Path(reports_folder).mkdir(parents=True, exist_ok=True)
            process(gt,
                    ocr,
                    report_prefix,
                    reports_folder,
                    metrics=metrics,
                    differences=differences,
                    textequiv_level=textequiv_level,
                    )
            pass

        if show_results:
            for html in Path(reports_folder).glob('*.html'):
                webbrowser.open(str(html.absolute()))
        if open_folder:
            if sys.platform == "win32":
                # Windows
                os.startfile(reports_folder)
            elif sys.platform == "darwin":
                # macOS
                subprocess.run(["open", reports_folder])
            else:
                # Linux and other Unix-like OS
                subprocess.run(["xdg-open", reports_folder])
            print(
                f"Opened workspace [bold green]Dinglehopper result folder[/bold green]: {reports_folder}")

    @app.command()
    def compare_metrics(
            gt: Annotated[str, typer.Argument(help="Ground Truth file",
                                              exists=True, callback=transform_input)] = ...,
            ocr: Annotated[str, typer.Argument(help="OCR file",
                                               exists=True, callback=transform_input)] = ...,):
        """
        Compare the metrics of the GT and OCR files.
        """
        print(f"Starting Dinglehopper comparison with gt={gt}, ocr={ocr}")
        # Your existing logic here
        from pageplus.models.page import Page
        gt_page = Page(Path(gt))
        ocr_page = Page(Path(ocr))
        line_metrics = []
        for gt_region in gt_page.regions.textregions:
            ocr_region = ocr_page.get_region_by_id(gt_region.get_id()) 
            if ocr_region is None:
                continue
            for gt_textline in gt_region.textlines:
                for ocr_textline in ocr_region.textlines:
                    if gt_textline.get_id() != ocr_textline.get_id():
                        continue
                    line_metrics.append(get_metrics(gt_textline.get_text(), ocr_textline.get_text()))
                    print(f"GT Textline: {gt_textline.get_text()}")
                    print(f"OCR Textline: {ocr_textline.get_text()}")
                    print(f"Metrics: {line_metrics[-1]}")
                    print("--------------------------------")       
        metrics = summarize_metrics(line_metrics)
        print(metrics)
        return metrics


if __name__ == "__main__":
    app()
