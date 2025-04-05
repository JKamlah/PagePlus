from pathlib import Path
from typing import Annotated

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
    loose: Annotated[bool, typer.Option(help="Allow parsing of unknown attributes and structures.")] = False,):
    """
    Inspect <fileGrp> entries in a METS XML file.
    """
    for idx, doc in enumerate(parse_mets_xml_multiple_roots(mets, loose=loose)):
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
    loose: Annotated[bool, typer.Option(help="Allow parsing of unknown attributes and structures.")] = True,
    tag: Annotated[str, typer.Option(help="Filter FileGrp by USE or ID.")] = "",
    nametag: Annotated[str, typer.Option(help="Use the original filename or the USE or ID tag for filename.")] = None):
    """
    Download files referenced in a METS XML document by <fileGrp>.
    """
    mets_files = parse_mets_xml_multiple_roots(mets, loose=loose)
    base_output = Path(mets).parent

    for idx, doc in enumerate(mets_files):
        # Determine output directory
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
                            download_file_from_flocat(file, nested_folder, nametag)
                elif isinstance(child, File):
                    download_file_from_flocat(child, grp_folder, nametag)

