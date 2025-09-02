from pathlib import Path
from typing import Dict, Any, List, Optional, Union
import logging

from pageplus.gui.cli_bridges import CLIBridge
from pageplus.utils.constants import TextLevel
from pageplus.cli.analytics import tags, confidences, statistics

logger = logging.getLogger(__name__)


class AnalysisBridge(CLIBridge):
    """Bridge for analysis functionality."""

    def analyse_statistics(self,
                       files: List[Path],
                       **kwargs) -> Dict[str, Any]:
        """Analyze text statistics."""
        try:
            results = statistics(files)
            return results
        except Exception as e:
            logger.error(f"Error analyzing files: {str(e)}")
            return {}

    def analyse_confidences(self,
                        files: List[Path],
                        **kwargs) -> Dict[str, Any]:
        """Analyze confidences."""
        try:
            results = confidences(files)
            return results
        except Exception as e:
            logger.error(f"Error analyzing files: {str(e)}")
            return {}

    def analyse_tags(self,
                        files: List[Path],
                        **kwargs) -> Dict[str, Any]:
        """Analyze tags."""
        try:
            from pageplus.cli.analytics import tags
            results = tags(files)
            return results
        except Exception as e:
            logger.error(f"Error analyzing files: {str(e)}")
            return {}