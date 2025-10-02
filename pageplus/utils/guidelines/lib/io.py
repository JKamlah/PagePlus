import json
import sys
from pathlib import Path


def app_path():
    return Path(__file__).parent.parent


def open_stream_to(writer, fname: Path):
    """
    Opens a writer stream, if it is already open it closes it first
    :param writer: writer instance
    :param fname: output filename
    :return:
    """
    if isinstance(writer, Path):
        writer.close()
    if fname.exists():
        fname.unlink()
    fname.touch()
    return fname.open("r+")


def set_output(ctx):
    """
    Sets the output format for the report, if output is None it prints to stdout
    :return:
    """
    output = ctx.output
    if not output:
        return
    if not output.parent.exists():
        output.parent.mkdir()
    if not output.is_file():
        output = output.joinpath("result.txt")
    ctx.output = output
    return


def create_json(results: dict, output: Path) -> None:
    """
    Prints the results as json
    :param results: results instance
    :param output: output path
    :return:
    """
    if output:
        jout = output.with_suffix(".json").open("w", encoding='utf-8')
    else:
        jout = sys.stdout
    json.dump(results, jout, indent=4, ensure_ascii=False)
    jout.flush()
    jout.close()
    return


def push_on_textfile(writer, text):
    writer.seek(0, 0)
    content = writer.read()
    writer.seek(0, 0)
    writer.write(text + content)
    writer.flush()


def write_subcounter(reval):
    """
    Prints the information about the substitutions to the cmd or the log file
    :param reval: process handler
    :return:
    """
    subcountertxt = f"{'*' * 22}\nSubstitutions: " + \
                    "".join([f"\n\t{count:-{6}}: [{subs}]" for subs, count in reval.substitutiontext.calls.items()]) + \
                    f"\n{'*' * 22}\n"
    if reval.verbose:
        print(subcountertxt)
    if reval.logging:
        push_on_textfile(reval.logging, subcountertxt)
