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
        strict: bool,
        verbose: bool,
        tag: str,
        nametag: str,
        selection: List[int],
        outputdir: Path,
        batch_size: int = 25,
        progress_callback: Optional[Callable] = None
    ) -> dict:
        """Download files referenced in a METS XML document."""
        try:
            from pageplus.utils.mets_mods import (
                parse_mets_xml_multiple_roots,
                FileGrp,
                File
            )
            from pageplus.utils.download import download_files_async_with_progress

            if mets.startswith("http"):
                output_path = get_url(mets, outputdir.joinpath('mets.xml'))
                if output_path:
                    mets = str(output_path)
                else:
                    return {"success": False, "output": "Failed to download METS from URL"}

            mets_files = parse_mets_xml_multiple_roots(mets, loose=not strict, verbose=verbose)
            base_output = Path(mets).parent if outputdir is None else Path(outputdir)

            # Collect download tasks
            download_tasks = []
            for idx, doc in enumerate(mets_files):
                if selection and idx + 1 not in selection:
                    continue
                output_dir = base_output if len(mets_files) == 1 else base_output / f"{(idx + 1):03}"
                output_dir.mkdir(parents=True, exist_ok=True)

                for file_grp in doc.recursive_find(doc, "fileGrp"):
                    use = file_grp.attributes.get("USE")
                    grp_id = file_grp.attributes.get("ID")

                    if tag and tag not in {use, grp_id}:
                        continue

                    grp_folder = output_dir / (use or grp_id or "unknown")
                    grp_folder.mkdir(parents=True, exist_ok=True)

                    for child in file_grp.children:
                        if isinstance(child, FileGrp):
                            nested_use = child.attributes.get("USE")
                            nested_id = child.attributes.get("ID")
                            nested_folder = grp_folder / (nested_use or nested_id or "nested")
                            nested_folder.mkdir(parents=True, exist_ok=True)

                            for file in child.children:
                                if isinstance(file, File):
                                    download_tasks.append((file, nested_folder, nametag))
                        elif isinstance(child, File):
                            download_tasks.append((child, grp_folder, nametag))

            if download_tasks:
                stats = asyncio.run(download_files_async_with_progress(download_tasks, batch_size, base_output, progress_callback))
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
