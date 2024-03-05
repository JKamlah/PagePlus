import os
import shutil
import subprocess
import sys
from collections import Counter
from importlib import util
from pathlib import Path
from typing import List, Annotated
import webbrowser
from datetime import datetime

import requests
import typer
from rich import print

app = typer.Typer()


def _install() -> None:
    """
    Before dinglehopper can be used, please use this install command
    to install dinglehopper by Mike Gerber and the qurator team!
    """
    for fname in ['align.py', 'edit_distance.py', 'word_error_rate.py', 'character_error_rate.py', 'extracted_text.py',
                  'ocr_files.py', 'config.py', 'templates/report.html.j2', 'templates/report.html.js',
                  'templates/report.json.j2', 'templates/summary.html.j2', 'templates/summary.json.j2']:
        url = 'https://raw.githubusercontent.com/qurator-spk/dinglehopper/master/src/dinglehopper/'+fname
        output_filename = Path(__file__).resolve().parent.parent.joinpath('utils/dinglehopper/'+fname)
        output_filename.parent.mkdir(exist_ok=True)
        response = requests.get(url)
        if response.status_code == 200:
            with open(output_filename, 'wb') as file:
                file.write(response.content)
            print(f"[green]File downloaded successfully: {output_filename}[/green]")
            if fname == 'extracted_text.py':
                shutil.copy(output_filename, output_filename.with_suffix('.old'))
                with open(output_filename, 'w') as f:
                    for line in output_filename.with_suffix('.old').open('r').readlines():
                        line = line.replace('from ocrd_utils import getLogger',
                                            'from pageplus.io.logger import logging as log')
                        if 'getLogger' in line:
                            continue
                        f.write(line)

        else:
            print(f"[red]Failed to download file. Status code: {response.status_code}[/red]")


if (spec := util.find_spec('pageplus.utils.dinglehopper.edit_distance')) is None:

    @app.command()
    def install() -> None:
        """
        Before dinglehopper can be used, please use this install command
        to install dinglehopper by Mike Gerber and the qurator team!
        """
        _install()
        for req in ["jinja2", "uniseg", "MarkupSafe", "attrs", "multimethod", "rapidfuzz", "chardet"]:
            subprocess.check_call([sys.executable, "-m", "pip", "install", "-I", req])

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

    ### PACKAGE ###
    @app.command(rich_help_panel="Package")
    def update_package() -> None:
        """
        Updates dinglehopper by Mike Gerber and the qurator team!
        """
        _install()


    ### DOCUMENTS ###
    def gen_diff_report(
        gt_in, ocr_in, css_prefix, joiner, none, *, differences=False, score_hint=None
    ):
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

        for k, (g, o) in enumerate(seq_align(gt_things, ocr_things, score_hint)):
            css_classes = None
            gt_id = None
            ocr_id = None
            if g != o:
                css_classes = "{css_prefix}diff{k} diff".format(css_prefix=css_prefix, k=k)
                if isinstance(gt_in, ExtractedText):
                    gt_id = gt_in.segment_id_for_pos(g_pos) if g is not None else None
                    ocr_id = ocr_in.segment_id_for_pos(o_pos) if o is not None else None
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
        gt: str,
        ocr: str,
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

            out_fn = os.path.join(reports_folder, report_prefix + report_suffix)

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
        gt, ocr, report_prefix, reports_folder, metrics, differences, textequiv_level
    ):
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
            reports_folder_prefix: Annotated[str, typer.Option(help="Prefix for the report folder.")] = "",
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
                typer.echo("OCR must be a directory if GT is a directory", err=True)
                raise typer.Exit(code=1)
            else:

                reports_folder = reports_folder if reports_folder != '.' else str(Path(ocr).joinpath('Dinglehopper')
                    .joinpath('_'.join([reports_folder_prefix, datetime.now().strftime('%Y-%m-%d_%H-%M')])).absolute())
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
            reports_folder = reports_folder if reports_folder != '.' else str(Path(ocr).parent.joinpath('Dinglehopper')
                    .joinpath('_'.join([reports_folder_prefix, datetime.now().strftime('%Y-%m-%d_%H-%M')])).absolute())
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
            print(f"Opened workspace [bold green]Dinglehopper result folder[/bold green]: {reports_folder}")

if __name__ == "__main__":
    app()
