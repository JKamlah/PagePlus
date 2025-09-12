from importlib import util

from pageplus.gui.cli_bridges.base import CLIBridge

# Conditionally import dinglehopper components
if util.find_spec('pageplus.utils.dinglehopper.edit_distance'):
    from pageplus.cli.dinglehopper import process as process_dinglehopper
    from pageplus.cli.dinglehopper import compare_metrics as compare_metrics_dinglehopper
    DINGLEHOPPER_INSTALLED = True
else:
    from pageplus.cli.dinglehopper import install as install_dinglehopper
    DINGLEHOPPER_INSTALLED = False


class DinglehopperBridge(CLIBridge):
    """Bridge for Dinglehopper CLI operations."""

    def is_installed(self) -> bool:
        """Check if dinglehopper is installed."""
        return DINGLEHOPPER_INSTALLED

    def install(self) -> dict:
        """Install dinglehopper."""
        if DINGLEHOPPER_INSTALLED:
            return {"success": True, "output": "Dinglehopper is already installed."}
        try:
            output = install_dinglehopper()
            return {"success": True, "output": output}
        except Exception as e:
            return {"success": False, "output": str(e)}

    def process(
            self,
            gt: str,
            ocr: str,
            report_prefix: str = "report",
            reports_folder: str = ".",
            metrics: bool = True,
            differences: bool = False,
            textequiv_level: str = "line",
    ) -> dict:
        """Compare GT and OCR files."""
        if not DINGLEHOPPER_INSTALLED:
            return {"success": False, "output": "Dinglehopper is not installed."}
        try:
            output = process_dinglehopper(
                gt=gt,
                ocr=ocr,
                report_prefix=report_prefix,
                reports_folder=reports_folder,
                metrics=metrics,
                differences=differences,
                textequiv_level=textequiv_level
            )
            return {"success": True, "output": output}
        except Exception as e:
            return {"success": False, "output": str(e)}
    
    def compare_metrics(self, gt: str, ocr: str) -> dict:
        """Get the metrics for the GT and OCR files."""
        if not DINGLEHOPPER_INSTALLED:
            return {"success": False, "output": "Dinglehopper is not installed."}
        try:
            output = compare_metrics_dinglehopper(gt, ocr)
            return {"success": True, "output": output}
        except Exception as e:
            return {"success": False, "output": str(e)}
    
