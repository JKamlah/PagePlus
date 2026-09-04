from pathlib import Path
from typing import List, Optional, Callable
import asyncio

from pageplus.cli.mets import (
    repair,
    show_filegrps,
    get_oai,
    get_url
)
from pageplus.gui.cli_bridges.base import CLIBridge
from pageplus.utils.mets_mods import (
    parse_mets_xml_multiple_roots,
    collect_mets_download_tasks,
)
from pageplus.utils.download import download_files_async_with_progress


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
            data = show_filegrps(mets=mets, strict=strict, verbose=verbose)
            return {"success": True, "output": data}
        except Exception as e:
            return {"success": False, "output": str(e)}

    def download(
        self,
        mets: str,
        strict: bool = False,
        verbose: bool = False,
        tag: str = "",
        nametag: Optional[str] = None,
        selection: Optional[List[int]] = None,
        outputdir: Optional[Path] = None,
        output_dir: Optional[Path] = None,
        page_range: Optional[str] = None,
        batch_size: int = 25,
        skip_existing: bool = True,
        progress_callback: Optional[Callable] = None
    ) -> dict:
        """Download files referenced in a METS XML document."""
        try:
            out_dir = output_dir if output_dir is not None else outputdir

            if mets.startswith(("http://", "https://")):
                base_output = Path(out_dir) if out_dir is not None else Path(".")
                base_output.mkdir(parents=True, exist_ok=True)
                target_mets = base_output / "mets.xml"
                if target_mets.exists():
                    mets = str(target_mets)
                else:
                    output_path = get_url(mets, target_mets)
                    if output_path and Path(output_path).exists():
                        mets = str(output_path)
                    else:
                        return {"success": False, "output": f"Failed to download METS from URL: {mets}"}
            else:
                base_output = Path(mets).parent if out_dir is None else Path(out_dir)

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
                stats = asyncio.run(download_files_async_with_progress(download_tasks, batch_size, base_output, skip_existing, progress_callback))
                return {"success": True, "output": f"Downloaded {stats['successful']} files successfully", "stats": stats}
            else:
                return {"success": True, "output": "No files to download"}
        except Exception as e:
            return {"success": False, "output": str(e)}

    def get_oai(self, base_url: str, identifier: str, output_dir: Path, metadata_prefix: str, token: Optional[str] = None) -> dict:
        """Download METS XML from an OAI endpoint."""
        try:
            output = get_oai(base_url=base_url, identifier=identifier, output_dir=output_dir, metadata_prefix=metadata_prefix, token=token)
            if output:
                return {"success": True, "output": f"✅ Saved METS XML to: {output}"}
            else:
                return {"success": False, "output": "❌ Failed to download METS XML from OAI"}
        except Exception as e:
            return {"success": False, "output": str(e)}

    def get_url(self, url: str, output_dir: Path) -> dict:
        """Download a METS XML file from a URL."""
        try:
            output = get_url(url, output_dir)
            return {"success": True, "output": output}
        except Exception as e:
            return {"success": False, "output": str(e)}
