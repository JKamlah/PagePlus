import subprocess
from pathlib import Path
from typing import Optional
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
    ) -> dict:
        """Download a IIIF manifest."""
        try:
            cmd = ["pageplus", "iiif", "download", manifest_url]
            if output_dir:
                cmd.extend(["--output-dir", str(output_dir)])
            if prefix:
                cmd.extend(["--prefix", prefix])
            if leading_zeros != 4:
                cmd.extend(["--leading-zeros", str(leading_zeros)])
            if page_range:
                cmd.extend(["--page-range", page_range])
            if filename_strategy != "label":
                cmd.extend(["--filename-strategy", filename_strategy])
            if not keep_original_size:
                cmd.append("--no-keep-original-size")
            if max_dim is not None:
                cmd.extend(["--max-dim", str(max_dim)])
            if min_dim is not None:
                cmd.extend(["--min-dim", str(min_dim)])

            result = subprocess.run(cmd, check=True, capture_output=True, text=True)
            return {"success": True, "output": result.stdout}
        except subprocess.CalledProcessError as e:
            return {"success": False, "output": e.stderr or e.stdout}

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
