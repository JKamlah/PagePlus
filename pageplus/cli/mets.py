from pathlib import Path
from typing import Annotated, List, Optional
import asyncio
import os
import requests
import urllib.parse
from lxml import etree

import typer
from rich import print
from rich.table import Table

from pageplus.utils.download import download_files_async
from pageplus.utils.mets_mods import (
    parse_mets_xml_multiple_roots,
    FileGrp,
    File,
    repair_namespace,
    validate_mets,
    collect_mets_download_tasks,
)

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
def show_filegrps(
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
    data_rows = []
    for idx, doc in enumerate(
            parse_mets_xml_multiple_roots(
            mets, loose=not strict, verbose=verbose)):
        file_grps = doc.recursive_find(doc, "fileGrp")

        for file_grp in file_grps:
            attrs = file_grp.attributes.copy()
            row = {
                "Document": str(idx + 1),
                "ID": attrs.get("ID", ""),
                "USE": attrs.get("USE", ""),
                "Type": "",
                "MIMETYPE": ""
            }

            if file_grp.children:
                first_child = file_grp.children[0]
                mime = first_child.attributes.get("MIMETYPE")
                if mime:
                    row["MIMETYPE"] = mime

                if isinstance(first_child, FileGrp):
                    row["Type"] = "Group of Groups"
                else:
                    row["Type"] = "Group of Files"
            else:
                row["Type"] = "Empty Group"
            data_rows.append(row)

    if not data_rows:
        print("No file groups found.")
        return data_rows

    # Print table for CLI, return data for GUI
    import sys
    if __name__ == "__main__" or "typer" in str(sys.modules.get("typer")):
        table = Table(title="File Groups Summary")
        headers = list(data_rows[0].keys())
        for header in headers:
            table.add_column(header)

        for row in data_rows:
            table.add_row(*row.values())

        print(table)

    return data_rows


@app.command()
def download(
        mets: Annotated[str,
                        typer.Argument(
                            help="Path to METS XML file or URL.",
                            callback=validate_mets,)],
        strict: Annotated[bool, typer.Option(help="Do not allow parsing of unknown attributes and structures.")] = False,
        verbose: Annotated[bool, typer.Option(help="Print warnings to the terminal.")] = False,
        tag: Annotated[str, typer.Option(help="Filter FileGrp by USE or ID tag.")] = "",
        nametag: Annotated[str, typer.Option(help="Use the original filename or the USE or ID tag for filename. (default: all)")] = None,
        selection: Annotated[List[int], typer.Option(help="The documents that should be downloaded, e.g 0,1,3 .")] = None,
        page_range: Annotated[Optional[str], typer.Option("--page-range", "-r", help="Page range to download, e.g., '1-5,7,9-12'.")] = None,
        output_dir: Annotated[Optional[Path], typer.Option("--output-dir", "-o", help="Directory to save the files. If not specified, files will be saved in the same directory as the METS file.")] = None,
        batch_size: Annotated[int, typer.Option("--batch-size", help="Number of files to download in parallel.")] = 25,
        skip_existing: Annotated[bool, typer.Option("--skip-existing/--no-skip-existing", help="Skip images/files if they already exist on disk.")] = True):
    """
    Download files referenced in a METS XML document by <fileGrp>.
    """
    if mets.startswith(("http://", "https://")):
        base_output = Path(output_dir) if output_dir is not None else Path(".")
        base_output.mkdir(parents=True, exist_ok=True)
        target_mets = base_output / "mets.xml"
        if target_mets.exists():
            print(f"ℹ️ METS XML already exists at: {target_mets}")
            mets = str(target_mets)
        else:
            output_path = get_url(mets, target_mets)
            if output_path and Path(output_path).exists():
                mets = str(output_path)
            else:
                raise typer.Exit(1)
    else:
        base_output = Path(mets).parent if output_dir is None else Path(output_dir)

    mets_files = parse_mets_xml_multiple_roots(mets, loose=not strict, verbose=verbose)

    download_tasks = collect_mets_download_tasks(
        mets_files=mets_files,
        base_output=base_output,
        tag=tag,
        nametag=nametag,
        selection=selection,
        page_range=page_range,
    )

    if download_tasks:
        stats = asyncio.run(download_files_async(download_tasks, batch_size, base_output, skip_existing=skip_existing))
        print("\n📊 Download Summary:")
        print(f"   Total: {stats['total']}")
        print(f"   ✅ Downloaded: {stats['successful']}")
        print(f"   📁 Already exists: {stats['exists']}")
        print(f"   ❌ Failed: {stats['failed']}")
        if base_output:
            print(f"   📄 Details saved to: {base_output / 'info.txt'}")
    else:
        print("No files to download matching the criteria.")


@app.command()
def get_oai(
    base_url: Annotated[str, typer.Argument(help="Base OAI URL, e.g. https://www.example.de/oai")],
    identifier: Annotated[str, typer.Argument(help="OAI identifier, e.g. 12311123")],
    output_dir: Annotated[Path, typer.Option("--output-dir", "-o", help="Directory to save the METS XML file.")] = Path("."),
    metadata_prefix: Annotated[str, typer.Option(help="Metadata prefix, typically 'mets'.")] = "mets",
    token: Annotated[Optional[str], typer.Option(help="Bearer token for OAI endpoint authorization. Can also be set via OAI_TOKEN environment variable.")] = None
):
    """
    Download METS XML from an OAI endpoint using identifier and save as {identifier}.xml.
    """
    if token is None:
        token = os.getenv("OAI_TOKEN")

    params = {
        "verb": "GetRecord",
        "identifier": identifier,
        "metadataPrefix": metadata_prefix,
    }
    full_url = f"{base_url}?{urllib.parse.urlencode(params)}"

    headers = {
        "User-Agent": os.getenv("PAGEPLUS_USER_AGENT", "PagePlus (https://github.com/berd-nfdi/PagePlus)")
    }
    if token:
        headers["Authorization"] = f"Bearer {token}"

    try:
        print(f"🔗 Fetching: {full_url}")
        response = requests.get(full_url, timeout=20, headers=headers)
        response.raise_for_status()

        # Check for OAI-PMH errors in the XML response
        xml_content = response.content
        tree = etree.fromstring(xml_content)
        ns = {'oai': 'http://www.openarchives.org/OAI/2.0/'}
        error_element = tree.find('oai:error', ns)
        if error_element is not None:
            error_code = error_element.get('code', 'unknown')
            error_message = error_element.text or "No error message provided."
            print(f"[red]❌ OAI-PMH Error (code: {error_code}): {error_message.strip()}[/red]")
            return None

        output_dir.mkdir(parents=True, exist_ok=True)
        output_path = output_dir / f"{identifier}.xml"
        output_path.write_bytes(xml_content)

        print(f"✅ Saved METS XML to: {output_path}")
        return output_path
    except requests.exceptions.HTTPError as e:
        print(f"[red]❌ HTTP Error: {e.response.status_code} {e.response.reason}[/red]")
        return None
    except requests.exceptions.RequestException as e:
        print(f"[red]❌ Failed to download METS XML from OAI: {e}[/red]")
        return None
    except etree.XMLSyntaxError as e:
        print(f"[red]❌ Failed to parse XML response: {e}[/red]")
        return None
    except Exception as e:
        print(f"[red]❌ An unexpected error occurred: {e}[/red]")
        return None


@app.command()
def get_url(url: Annotated[str, typer.Argument(help="URL to the METS XML file.")],
            output_path: Annotated[Path, typer.Option("--output-dir", "-o",
                                                      help="Directory or file path to save the METS XML file.")] = Path("."),
            ):
    """
    Download a METS XML file directly from a URL and save to disk.
    """
    headers = {
        "User-Agent": os.getenv("PAGEPLUS_USER_AGENT", "PagePlus (https://github.com/berd-nfdi/PagePlus)")
    }
    try:
        response = requests.get(url, timeout=20, headers=headers)
        response.raise_for_status()

        if output_path.is_dir() or str(output_path).endswith(("/", "\\")) or output_path.suffix != ".xml":
            output_path.mkdir(parents=True, exist_ok=True)
            target_file = output_path / "mets.xml"
        else:
            output_path.parent.mkdir(parents=True, exist_ok=True)
            target_file = output_path

        target_file.write_text(response.text, encoding="utf-8")
        print(f"✅ Downloaded METS XML to: {target_file}")
        return target_file
    except Exception as e:
        print(f"[red]❌ Failed to download METS XML: {e}[/red]")
        return None
