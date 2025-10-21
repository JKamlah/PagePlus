import logging
from typing import Dict, Any, List, Optional
from importlib import util

from pageplus.gui.cli_bridges.base import CLIBridge
from pageplus.utils.envs import get_env_path
from dotenv import dotenv_values, set_key

# Conditionally import tesseract components
if util.find_spec('tesserocr') and dotenv_values(get_env_path()).get('PAGEPLUS_OCR_TESSERACT', 'False') != 'False':
    from pageplus.cli.ocr_tesseract import run_ocr, get_available_models, get_default_datapath, check_tesseract_installation
    TESSERACT_AVAILABLE = True
else:
    from pageplus.cli.ocr_tesseract import _install as install
    TESSERACT_AVAILABLE = False


class TesseractBridge(CLIBridge):
    """Bridge for Tesseract OCR functionality."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.logger = logging.getLogger(__name__)

    def is_activated(self) -> bool:
        """Check if Tesseract OCR is activated."""
        try:
            env_values = dotenv_values(get_env_path())
            return env_values.get('PAGEPLUS_OCR_TESSERACT', 'False') == 'True'
        except Exception:
            return False

    def activate(self) -> bool:
        """Activate Tesseract OCR."""
        try:
            set_key(get_env_path(), 'PAGEPLUS_OCR_TESSERACT', 'True')
            return True
        except Exception as e:
            self.logger.error(f"Failed to activate Tesseract OCR: {e}")
            return False

    def deactivate(self) -> bool:
        """Deactivate Tesseract OCR."""
        try:
            set_key(get_env_path(), 'PAGEPLUS_OCR_TESSERACT', 'False')
            return True
        except Exception as e:
            self.logger.error(f"Failed to deactivate Tesseract OCR: {e}")
            return False

    def install(self) -> bool:
        """Install Tesseract OCR dependencies."""
        if not TESSERACT_AVAILABLE:
            try:
                install()
                return True
            except Exception as e:
                self.logger.error(f"Failed to install Tesseract OCR: {e}")
                return False
        return True

    def run_ocr(self,
                inputs: List[str],
                image_files: List[str] = None,
                model_name: Optional[str] = None,
                model_path: Optional[str] = None,
                save_snippets: bool = False,
                text_filter: Optional[str] = None,
                region_tagfilter: Optional[str] = None,
                textline_tagfilter: Optional[str] = None,
                processing_level: str = "Textline",
                jobs: int = 4,
                outputdir: Optional[str] = None,
                dry_run: bool = False,
                progress_callback=None,
                output_formats: List[str] = None,
                custom_params: List[Dict[str, str]] = None,
                create_polygon: bool = True,
                create_subfolder: bool = False,
                rename_page_xml: bool = False) -> Dict[str, Any]:
        """
        Run OCR processing on the given inputs.

        Args:
            inputs: List of input file paths
            image_files: Direct paths to image files
            model_name: Tesseract model name
            model_path: Path to Tesseract models directory
            save_snippets: Save image snippets for debugging
            text_filter: Text filter regex
            region_tagfilter: Region tag filter
            textline_tagfilter: Textline tag filter
            processing_level: Level of processing (Textline, TextRegion, Page)
            jobs: Number of parallel jobs
            outputdir: Output directory (if not specified, input files will be overwritten)
            dry_run: Process without saving
            progress_callback: Optional callback function for progress updates
            output_formats: List of output formats for Page-level processing
            custom_params: List of custom parameters for Tesseract
            create_polygon: Whether to create polygon coordinates for PageXML output
            create_subfolder: Create subfolders for output formats
            rename_page_xml: Rename PageXML from .page.xml to .xml

        Returns:
            Dictionary with processing results
        """
        if not TESSERACT_AVAILABLE:
            return {
                "success": False,
                "error": "Tesseract OCR is not available. Please install tesserocr first."
            }

        try:
            # Call the OCR function directly
            import time
            start_time = time.time()
            result = run_ocr(
                inputs=inputs,
                image_files=image_files,
                model_name=model_name,
                model_path=model_path,
                save_snippets=save_snippets,
                text_filter=text_filter,
                region_tagfilter=region_tagfilter,
                textline_tagfilter=textline_tagfilter,
                processing_level=processing_level,
                jobs=jobs,
                outputdir=outputdir,
                dry_run=dry_run,
                progress_callback=progress_callback,
                output_formats=output_formats,
                custom_params=custom_params,
                create_polygon=create_polygon,
                create_subfolder=create_subfolder,
                rename_page_xml=rename_page_xml
            )
            end_time = time.time()
            result["processing_time"] = end_time - start_time
            return result
        except Exception as e:
            self.logger.error(f"Unexpected error during OCR processing: {e}")

            return {
                "success": False,
                "error": str(e)
            }

    def get_available_models(self, model_path: str = None) -> List[str]:
        """Get list of available Tesseract models."""
        if not TESSERACT_AVAILABLE:
            return ["eng"]  # Fallback if not available
        return get_available_models(model_path)

    def get_default_datapath(self) -> str:
        """Get the default Tesseract data path."""
        if not TESSERACT_AVAILABLE:
            return "/usr/share/tesseract-ocr/tessdata"  # Default fallback
        return get_default_datapath()

    def check_tesseract_installation(self) -> Dict[str, Any]:
        """Check if Tesseract is properly installed."""
        if not TESSERACT_AVAILABLE:
            return {
                "tesseract_installed": False,
                "tesseract_version": None,
                "tesserocr_available": False,
                "status": "missing_tesserocr"
            }
        return check_tesseract_installation()
