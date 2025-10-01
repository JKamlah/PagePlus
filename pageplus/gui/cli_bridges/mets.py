from pathlib import Path
from typing import List

from pageplus.cli.mets import (
    repair,
    show_filegrps,
    download,
    get_oai,
    get_url
)
from pageplus.gui.cli_bridges.base import CLIBridge


class MetsBridge(CLIBridge):
    """Bridge for METS CLI operations."""

    def repair(self, mets: str) -> dict:
        """Repair namespace issues in a METS file."""
        try:
            output = repair(mets)
            return {"success": True, "output": output}
        except Exception as e:
            return {"success": False, "output": str(e)}

    def show_filegrps(self, mets: str, strict: bool, verbose: bool) -> dict:
        """Inspect <fileGrp> entries in a METS XML file."""
        try:
            df = show_filegrps(mets=mets, strict=strict, verbose=verbose)
            return {"success": True, "output": df}
        except Exception as e:
            return {"success": False, "output": str(e)}

    def download(self, mets: str, strict: bool, verbose: bool, tag: str, nametag: str, selection: List[int], outputdir: Path) -> dict:
        """Download files referenced in a METS XML document."""
        try:
            output = download(mets, strict, verbose, tag, nametag, selection, outputdir)
            return {"success": True, "output": output}
        except Exception as e:
            return {"success": False, "output": str(e)}

    def get_oai(self, base_url: str, identifier: str, output_dir: Path, metadata_prefix: str) -> dict:
        """Download METS XML from an OAI endpoint."""
        try:
            output = get_oai(base_url, identifier, output_dir, metadata_prefix)
            return {"success": True, "output": output}
        except Exception as e:
            return {"success": False, "output": str(e)}

    def get_url(self, url: str, output_dir: Path) -> dict:
        """Download a METS XML file from a URL."""
        try:
            output = get_url(url, output_dir)
            return {"success": True, "output": output}
        except Exception as e:
            return {"success": False, "output": str(e)}
