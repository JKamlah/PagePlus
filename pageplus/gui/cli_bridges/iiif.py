import subprocess
from pathlib import Path
from typing import Optional, Callable
import json

from pageplus.gui.cli_bridges.base import CLIBridge


class IIIFBridge(CLIBridge):
    """Bridge for IIIF functionality."""

    def download_manifest(
        self,
        manifest_url: str,
        output_dir: Optional[Path] = None,
        prefix: str = "",
        leading_zeros: int = 4,
        page_range: Optional[str] = None,
        filename_strategy: str = "label",
        keep_original_size: bool = True,
        max_dim: Optional[int] = None,
        min_dim: Optional[int] = None,
        batch_size: int = 25,
        progress_callback: Optional[Callable] = None,
    ) -> dict:
        """Download a IIIF manifest."""
        try:
            # Use direct Python call for better progress tracking
            from pageplus.utils.iiif.manifest import IIIFManifest
            
            manifest = IIIFManifest(
                url=manifest_url,
                save_dir=output_dir,
                prefix=prefix,
                leading_zeros=leading_zeros,
                page_range=page_range,
                filename_strategy=filename_strategy,
                keep_original_size=keep_original_size,
                max_dim=max_dim,
                min_dim=min_dim,
                batch_size=batch_size,
                progress_callback=progress_callback,
            )
            result = manifest.download()
            
            if result:
                return {"success": True, "output": f"Successfully downloaded images to {output_dir}"}
            else:
                return {"success": False, "output": "Failed to download images"}
        except Exception as e:
            return {"success": False, "output": str(e)}

    def get_resources(self, manifest_url: str) -> dict:
        """Get resources from a IIIF manifest."""
        try:
            cmd = ["pageplus", "iiif", "get-resources", manifest_url, "--json"]
            result = subprocess.run(cmd, check=True, capture_output=True, text=True)
            resources = json.loads(result.stdout)
            return {"success": True, "output": resources}
        except subprocess.CalledProcessError as e:
            return {"success": False, "output": e.stderr or e.stdout}
        except json.JSONDecodeError as e:
            return {"success": False, "output": f"Failed to parse JSON output: {e}"}
