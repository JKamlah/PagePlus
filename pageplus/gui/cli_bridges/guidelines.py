from pathlib import Path
from typing import List, Optional
import tempfile
from pageplus.cli.guidelines import evaluate_text, mapping_text
from pageplus.gui.cli_bridges.base import CLIBridge
from pageplus.gui.utils.guideline_editor_utils import GuidelineManager


class GuidelinesBridge(CLIBridge):
    def __init__(self):
        output_dir = Path(tempfile.gettempdir()) / "pageplus" / "gui_outputs" / "guidelines"
        super().__init__(output_dir)

    def run_evaluate(
        self,
        inputs: List[Path],
        output: Optional[Path] = None,
        as_json: bool = False,
        custom_categories: Optional[List[str]] = None,
        statistical_categories: Optional[List[str]] = None,
        missing_unicodes: Optional[List[str]] = None,
        addinfo: Optional[List[str]] = None,
        guideline: Optional[str] = None,
        textnormalization: str = "NFC",
        report_data: Optional[Path] = None,
        report_data_format: Optional[str] = None,
    ):
        """Runs the 'evaluate' command from the guidelines CLI and returns structured results."""
        return evaluate_text(
            inputs=[str(p) for p in inputs],
            output=output,
            json=as_json,
            custom_categories=custom_categories or [""],
            statistical_categories=statistical_categories or ["all"],
            missing_unicodes=missing_unicodes,
            addinfo=addinfo or ["name"],
            guideline=guideline,
            textnormalization=textnormalization,
            report_data=report_data,
            report_data_format=report_data_format,
            from_gui=True
        )

    def run_mapping_text(
        self,
        inputs: List[Path],
        guideline: str = "GT4Hist",
        textnormalization: str = "NFC",
        dry_run: bool = False,
    ):
        """Runs the 'mapping_text' command from the guidelines CLI."""
        try:
            return {
                "output": mapping_text(
                    inputs=inputs,
                    guideline=guideline,
                    textnormalization=textnormalization,
                    dry_run=dry_run),
                "success": True}
        except Exception as e:
            return {"success": False, "output": str(e)}

    @staticmethod
    def get_guideline_profiles() -> List[str]:
        """Returns a list of available guideline profiles."""
        manager = GuidelineManager(profile_type="rules", filename="guidelines.json")
        return manager.get_profile_names()

    @staticmethod
    def get_missing_unicode_profiles() -> List[str]:
        """Reads and returns the profile keys from missing_unicode.json."""
        manager = GuidelineManager(profile_type="rules", filename="missing_unicode.json")
        return manager.get_profile_names()

    @staticmethod
    def get_custom_category_profiles() -> List[str]:
        """Reads and returns the category keys from categories.json."""
        manager = GuidelineManager(profile_type="rules", filename="categories.json")
        return list(manager.data.get("categories", {}).keys())
