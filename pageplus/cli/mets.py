from pathlib import Path
from typing import Annotated, List
import requests
import urllib.parse

import typer
from rich import print
from rich.progress import track

from pageplus.utils.mets_mods import (
    parse_mets_xml_multiple_roots,
    FileGrp,
    File,
    repair_namespace,
    validate_mets,
    download_file_from_flocat,)

app = typer.Typer()

@app.command()
def repair(
    mets: Annotated[str,
        typer.Argument(
            exists=True,
            help="Path to METS XML file.",
            callback=validate_mets,),]):
    """
    Load and repair namespace issues in a METS file (overwrites in place).
    """
    repair_namespace(mets)
    print(f"🔧 Repaired: {mets}")


@app.command()
def filegrps(
    mets: Annotated[str,
        typer.Argument(
            exists=True,
            help="Path to METS XML file.",
            callback=validate_mets,),],
    strict: Annotated[bool, typer.Option(help="Do not allow parsing of unknown attributes and structures.")] = False,
    verbose: Annotated[bool, typer.Option(help="Print warnings to the terminal.")] = False,):
    """
    Inspect <fileGrp> entries in a METS XML file.
    """
    for idx, doc in enumerate(parse_mets_xml_multiple_roots(mets, loose=not strict, verbose=verbose)):
        print(f"{idx+1}. Document")
        file_grps = doc.recursive_find(doc, "fileGrp")

        for file_grp in file_grps:
            attrs = file_grp.attributes.copy()

            if file_grp.children:
                first_child = file_grp.children[0]
                mime = first_child.attributes.get("MIMETYPE")
                if mime:
                    attrs["MIMETYPE"] = mime

                if isinstance(first_child, FileGrp):
                    print(f"\tGroup of Groups: {attrs}")
                else:
                    print(f"\t\tGroup of Files: {attrs}")
            else:
                print(f"\tEmpty Group: {attrs}")


@app.command()
def download(
    mets: Annotated[str,
        typer.Argument(
            exists=True,
            help="Path to METS XML file.",
            callback=validate_mets,),],
    strict: Annotated[bool, typer.Option(help="Do not allow parsing of unknown attributes and structures.")] = False,
    verbose: Annotated[bool, typer.Option(help="Print warnings to the terminal.")] = False,
    tag: Annotated[str, typer.Option(help="Filter FileGrp by USE or ID tag.")] = "",
    nametag: Annotated[str, typer.Option(help="Use the original filename or the USE or ID tag for filename. (default: all)")] = None,
    selection: Annotated[List[int], typer.Option(help="The documents that should be downloaded, e.g 0,1,3 .")] = None,
    outputdir: Annotated[Path, typer.Option(help="Directory to save the files. If not specified, files will be saved in the same directory as the METS file.")] = None):
    """
    Download files referenced in a METS XML document by <fileGrp>.
    """
    mets_files = parse_mets_xml_multiple_roots(mets, loose=not strict, verbose=verbose)
    base_output = Path(mets).parent if outputdir is None else Path(outputdir)

    for idx, doc in enumerate(mets_files):
        # Determine output directory
        if selection and idx+1 not in selection:
            continue
        output_dir = base_output if len(mets_files) == 1 else base_output / f"{(idx + 1):03}"
        output_dir.mkdir(parents=True, exist_ok=True)

        for file_grp in doc.recursive_find(doc, "fileGrp"):
            use = file_grp.attributes.get("USE")
            grp_id = file_grp.attributes.get("ID")

            if tag and tag not in {use, grp_id}:
                continue

            # Define output subfolder
            grp_folder = output_dir / (use or grp_id or "unknown")
            grp_folder.mkdir(parents=True, exist_ok=True)

            for child in track(file_grp.children, f"{idx+1}. Document: Downloading {tag or 'all'}..."):
                if isinstance(child, FileGrp):
                    # Handle nested FileGrp
                    nested_use = child.attributes.get("USE")
                    nested_id = child.attributes.get("ID")
                    nested_folder = grp_folder / (nested_use or nested_id or "nested")
                    nested_folder.mkdir(parents=True, exist_ok=True)

                    for file in child.children:
                        if isinstance(file, File):
                            download_file_from_flocat(file, nested_folder, nametag, overwrite=True)
                elif isinstance(child, File):
                    download_file_from_flocat(child, grp_folder, nametag, overwrite=True)

@app.command()
def get_oai(
    base_url: Annotated[str, typer.Argument(help="Base OAI URL, e.g. https://www.example.de/oai")],
    identifier: Annotated[str, typer.Argument(help="OAI identifier, e.g. 12311123")],
    output_dir: Annotated[Path, typer.Option("--output-dir", "-o", help="Directory to save the METS XML file.")] = Path("."),
    metadata_prefix: Annotated[str, typer.Option(help="Metadata prefix, typically 'mets'.")] = "mets"
):
    """
    Download METS XML from an OAI endpoint using identifier and save as {identifier}.xml.
    """

    params = {
        "verb": "GetRecord",
        "identifier": identifier,
        "metadataPrefix": metadata_prefix,
    }
    full_url = f"{base_url}?{urllib.parse.urlencode(params)}"

    try:
        print(f"🔗 Fetching: {full_url}")
        response = requests.get(full_url, timeout=10)
        response.raise_for_status()

        output_dir.mkdir(parents=True, exist_ok=True)
        output_path = output_dir / f"{identifier}.xml"
        output_path.write_text(response.text, encoding="utf-8")

        print(f"✅ Saved METS XML to: {output_path}")
    except Exception as e:
        print(f"[red]❌ Failed to download METS XML from OAI: {e}[/red]")

@app.command()
def get_url(
    url: Annotated[str, typer.Argument(help="URL to the METS XML file.")],
    output_dir: Annotated[Path, typer.Option("--output-dir", "-o", help="Directory to save the METS XML file.")] = Path("."),
):
    """
    Download a METS XML file directly from a URL and save to disk.
    """
    try:
        response = requests.get(url, timeout=10)
        response.raise_for_status()
        output_dir.write_text(response.text, encoding="utf-8")
        print(f"✅ Downloaded METS XML to: {output_dir}")
    except Exception as e:
        print(f"[red]❌ Failed to download METS XML: {e}[/red]")

