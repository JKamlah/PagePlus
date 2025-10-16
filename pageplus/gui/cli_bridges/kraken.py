import logging
from typing import Dict, Any, List, Optional
from pathlib import Path
import asyncio

from pageplus.gui.cli_bridges.base import CLIBridge
from pageplus.utils.envs import get_env_path
from dotenv import set_key
from pageplus.utils.constants import ImageExtension

# Import Kraken functions
from pageplus.cli.ocr_kraken import (
    get_kraken_python_path,
    get_kraken_executable,
    verify_kraken_installation,
    kraken_segment_cli,
    kraken_recognize_cli,
    kraken_segment_and_recognize_cli,
    run_kraken_segment_batch_external_async
)


KRAKEN_AVAILABLE = get_kraken_python_path() is not None


class KrakenBridge(CLIBridge):
    """Bridge for Kraken OCR functionality."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.logger = logging.getLogger(__name__)

    def is_configured(self) -> bool:
        """Check if Kraken Python environment is configured."""
        try:
            python_path = get_kraken_python_path()
            return python_path is not None and python_path.exists()
        except Exception:
            return False

    def get_python_env_path(self) -> Optional[Path]:
        """Get the configured Kraken Python environment path."""
        return get_kraken_python_path()

    def verify_installation(self) -> Dict[str, Any]:
        """Verify that Kraken is installed in the configured environment."""
        python_path = get_kraken_python_path()
        if not python_path:
            return {
                "installed": False,
                "error": "No Python environment configured"
            }

        try:
            is_installed = verify_kraken_installation(python_path)
            kraken_exe = get_kraken_executable()

            result = {
                "installed": is_installed,
                "python_path": str(python_path),
                "kraken_executable": str(kraken_exe) if kraken_exe else None
            }

            if is_installed and not kraken_exe:
                result["warning"] = "Kraken module installed but CLI executable not found"

            return result
        except Exception as e:
            return {
                "installed": False,
                "error": str(e)
            }

    def set_python_env(self, python_path: Path) -> Dict[str, Any]:
        """
        Set the Python environment path where Kraken is installed.

        Args:
            python_path: Path to Python executable in Kraken environment

        Returns:
            Dictionary with success status and message
        """
        try:
            # Verify the path exists
            if not python_path.exists():
                return {
                    "success": False,
                    "error": f"Python executable not found at {python_path}"
                }

            # Verify Kraken is installed
            if not verify_kraken_installation(python_path):
                return {
                    "success": False,
                    "error": "Kraken is not installed in this environment",
                    "hint": f"Install with: {python_path} -m pip install kraken"
                }

            # Save to .env
            set_key(get_env_path(), 'PAGEPLUS_KRAKEN_PYTHON_PATH', str(python_path.absolute()))
            return {
                "success": True,
                "message": f"Kraken Python environment set to: {python_path.absolute()}"
            }
        except Exception as e:
            self.logger.error(f"Failed to set Kraken Python environment: {e}")
            return {
                "success": False,
                "error": str(e)
            }

    def clear_python_env(self) -> Dict[str, Any]:
        """Clear the configured Kraken Python environment path."""
        try:
            set_key(get_env_path(), 'PAGEPLUS_KRAKEN_PYTHON_PATH', '')
            return {
                "success": True,
                "message": "Kraken Python environment cleared"
            }
        except Exception as e:
            self.logger.error(f"Failed to clear Kraken Python environment: {e}")
            return {
                "success": False,
                "error": str(e)
            }

    def get_available_models(self, model_dir: Path) -> List[str]:
        """
        Get list of available Kraken models in the specified directory.

        Args:
            model_dir: Directory containing Kraken model files

        Returns:
            List of model filenames
        """
        try:
            if not model_dir or not model_dir.exists():
                return []

            # Find all .mlmodel files
            models = [f.name for f in model_dir.glob('*.mlmodel')]
            return sorted(models)
        except Exception as e:
            self.logger.error(f"Failed to get available models: {e}")
            return []

    def get_model_type(self, model_path: Path) -> str:
        """
        Detect the type of a Kraken model (segmentation or recognition).

        Args:
            model_path: Path to the Kraken model file

        Returns:
            Model type: 'segmentation', 'recognition', or 'unknown'
        """
        import re
        import json
        import json_repair

        try:
            if not model_path.exists():
                return 'unknown'

            with open(model_path, 'rb') as f:
                data = f.read()

            # Search for kraken_meta JSON block
            # Use non-greedy match to find the first complete JSON object
            match = re.search(rb'kraken_meta[^{]*(\{[^}]*\})', data)
            if not match:
                return 'unknown'

            # Extract only the matched JSON part
            json_str = match.group(1).decode('utf-8', errors='ignore')

            # Parse JSON - now only parsing the extracted part
            meta = json.loads(json_repair.repair_json(json_str))
            model_type = meta.get('model_type', 'unknown')

            return model_type
        except json.JSONDecodeError as e:
            self.logger.debug(f"JSON decode error for {model_path.name}: {e}")
            return 'unknown'
        except Exception as e:
            self.logger.debug(f"Failed to detect model type for {model_path.name}: {e}")
            return 'unknown'

    def get_models_by_type(self, model_dir: Path) -> Dict[str, List[str]]:
        """
        Get available models categorized by type.

        Args:
            model_dir: Directory containing Kraken model files

        Returns:
            Dictionary with 'segmentation', 'recognition', and 'unknown' keys
        """
        models_by_type = {
            'segmentation': [],
            'recognition': [],
            'unknown': []
        }

        try:
            all_models = self.get_available_models(model_dir)
            for model_name in all_models:
                model_path = model_dir / model_name
                model_type = self.get_model_type(model_path)
                models_by_type[model_type].append(model_name)

            return models_by_type
        except Exception as e:
            self.logger.error(f"Failed to categorize models: {e}")
            return models_by_type

    def run_segmentation(self,
                         image_files: List[str],
                         model_path: Path,
                         outputdir: Optional[str] = None,
                         device: str = 'cpu',
                         text_direction: str = 'horizontal-lr',
                         jobs: int = 1,
                         template: str = "pageplus",
                         threads: int = 1,
                         progress_callback=None) -> Dict[str, Any]:
        """
        Run Kraken segmentation on images using direct CLI commands.

        Args:
            image_files: List of image file paths
            model_path: Path to segmentation model (.mlmodel)
            outputdir: Output directory for PAGE-XML files
            device: Device to use ('cpu' or 'cuda:0')
            text_direction: Text direction ('horizontal-lr', 'horizontal-rl', 'vertical-lr', 'vertical-rl')
            jobs: Number of parallel jobs
            template: Template name for Kraken CLI
            threads: Number of threads for Kraken CLI
            progress_callback: Optional callback for progress updates

        Returns:
            Dictionary with processing results
        """
        if not self.is_configured():
            return {
                "success": False,
                "error": "Kraken Python environment is not configured."
            }

        try:
            import time
            start_time = time.time()

            # Convert outputdir to Path if provided
            output_path = Path(outputdir) if outputdir else None

            # Call the CLI function directly
            result = asyncio.run(kraken_segment_cli(
                image_files=image_files,
                model_path=model_path,
                output_dir=output_path,
                device=device,
                text_direction=text_direction,
                jobs=jobs,
                template=template,
                threads=threads,
                progress_callback=progress_callback
            ))

            end_time = time.time()

            # Add processing time to result
            if result.get("success"):
                result["processing_time"] = end_time - start_time

            return result

        except Exception as e:
            self.logger.error(f"Error during segmentation: {e}")
            return {
                "success": False,
                "error": str(e)
            }

    def run_recognition(self,
                        image_files: List[str],
                        model_path: Path,
                        outputdir: Optional[str] = None,
                        device: str = 'cpu',
                        text_direction: str = 'horizontal-tb',
                        jobs: int = 1,
                        template: str = "pageplus",
                        threads: int = 1,
                        progress_callback=None) -> Dict[str, Any]:
        """
        Run Kraken OCR recognition on pre-segmented PAGE-XML files using direct CLI commands.

        Args:
            image_files: List of image file paths (corresponding XML files must exist)
            model_path: Path to recognition model (.mlmodel)
            outputdir: Output directory for updated PAGE-XML files
            device: Device to use ('cpu' or 'cuda:0')
            text_direction: Text direction for OCR ('horizontal-tb', 'vertical-lr', 'vertical-rl')
            jobs: Number of parallel jobs
            template: Template name for Kraken CLI
            threads: Number of threads for Kraken CLI
            progress_callback: Optional callback for progress updates

        Returns:
            Dictionary with processing results
        """
        if not self.is_configured():
            return {
                "success": False,
                "error": "Kraken Python environment is not configured."
            }

        try:
            import time
            start_time = time.time()

            # Convert outputdir to Path if provided
            output_path = Path(outputdir) if outputdir else None

            # Call the CLI function directly
            result = asyncio.run(kraken_recognize_cli(
                image_files=image_files,
                model_path=model_path,
                output_dir=output_path,
                device=device,
                text_direction=text_direction,
                jobs=jobs,
                template=template,
                threads=threads,
                progress_callback=progress_callback
            ))

            end_time = time.time()

            # Add processing time to result
            if result.get("success"):
                result["processing_time"] = end_time - start_time

            return result

        except Exception as e:
            self.logger.error(f"Error during recognition: {e}")
            return {
                "success": False,
                "error": str(e)
            }

    def run_segment_and_recognize(self,
                                  image_files: List[str],
                                  seg_model_path: Path,
                                  rec_model_path: Path,
                                  outputdir: Optional[str] = None,
                                  device: str = 'cpu',
                                  seg_text_direction: str = 'horizontal-lr',
                                  rec_text_direction: str = 'horizontal-tb',
                                  jobs: int = 1,
                                  template: str = "pageplus",
                                  threads: int = 1,
                                  progress_callback=None) -> Dict[str, Any]:
        """
        Run Kraken segmentation and recognition in one pipeline using direct CLI commands.

        Args:
            image_files: List of image file paths
            seg_model_path: Path to segmentation model (.mlmodel)
            rec_model_path: Path to recognition model (.mlmodel)
            outputdir: Output directory for PAGE-XML files
            device: Device to use ('cpu' or 'cuda:0')
            seg_text_direction: Text direction for segmentation
            rec_text_direction: Text direction for recognition
            jobs: Number of parallel jobs
            template: Template name for Kraken CLI
            threads: Number of threads for Kraken CLI
            progress_callback: Optional callback for progress updates

        Returns:
            Dictionary with processing results
        """
        if not self.is_configured():
            return {
                "success": False,
                "error": "Kraken Python environment is not configured."
            }

        try:
            import time
            start_time = time.time()

            # Convert outputdir to Path if provided
            output_path = Path(outputdir) if outputdir else None

            # Call the combined CLI function
            result = asyncio.run(kraken_segment_and_recognize_cli(
                image_files=image_files,
                seg_model_path=seg_model_path,
                rec_model_path=rec_model_path,
                output_dir=output_path,
                device=device,
                seg_text_direction=seg_text_direction,
                rec_text_direction=rec_text_direction,
                jobs=jobs,
                template=template,
                threads=threads,
                progress_callback=progress_callback
            ))

            end_time = time.time()

            # Add processing time to result
            if result.get("success"):
                result["processing_time"] = end_time - start_time

            return result

        except Exception as e:
            self.logger.error(f"Error during combined segmentation and recognition: {e}")
            return {
                "success": False,
                "error": str(e)
            }

    def run_ocr(self,
                inputs: List[str],
                image_folder: str = '.',
                outputdir: Optional[str] = None,
                model_name: Optional[str] = None,
                model_dir: Optional[Path] = None,
                jobs: int = 1,
                same_names: bool = False,
                image_extensions: List[str] = None,
                save_snippets: bool = False,
                text_filter: Optional[str] = None,
                region_tagfilter: Optional[str] = None,
                textline_tagfilter: Optional[str] = None,
                dry_run: bool = False,
                progress_callback=None) -> Dict[str, Any]:
        """
        Run OCR processing on the given inputs using Kraken.

        Args:
            inputs: List of input XML file paths
            image_folder: Folder containing images relative to XML files
            outputdir: Output directory (if not specified, input files will be overwritten)
            model_name: Kraken model name (should exist in model_dir)
            model_dir: Directory containing the Kraken model
            same_names: Use XML filename to search for images
            image_extensions: List of image extensions to try
            save_snippets: Save image snippets for debugging
            text_filter: Text filter regex
            region_tagfilter: Region tag filter
            textline_tagfilter: Textline tag filter
            dry_run: Process without saving
            progress_callback: Optional callback function for progress updates

        Returns:
            Dictionary with processing results
        """
        if not self.is_configured():
            return {
                "success": False,
                "error": "Kraken Python environment is not configured. Please configure it first."
            }

        try:
            # Import the OCR function from CLI
            from pageplus.cli.ocr_kraken import ocr as cli_ocr
            from pageplus.utils.constants import ImageExtension

            # Convert image extensions to ImageExtension enum
            if image_extensions:
                img_exts = [ImageExtension(ext) for ext in image_extensions]
            else:
                img_exts = [
                    ImageExtension('.png'),
                    ImageExtension('.jpg'),
                    ImageExtension('.jpeg'),
                    ImageExtension('.tif'),
                    ImageExtension('.tiff')
                ]

            # Prepare parameters
            import time
            start_time = time.time()

            # Track progress
            processed_files = 0
            total_files = len(inputs)

            # Call the CLI function directly
            # Note: The CLI function uses the decorator @profile which returns ProfileFnRet
            # We need to call it and extract results from the profile object
            try:
                cli_ocr(
                    inputs=inputs,
                    image_folder=image_folder,
                    outputdir=outputdir,
                    model_name=model_name,
                    model_dir=model_dir,
                    jobs=jobs,
                    same_names=same_names,
                    image_extensions=img_exts,
                    save_snippets=save_snippets,
                    text_filter=text_filter,
                    region_tagfilter=region_tagfilter,
                    textline_tagfilter=textline_tagfilter,
                    profile='',  # No profiling
                    profilelevel=[],  # No profiling levels
                    dry_run=dry_run
                )

                # Get stats from the profile object if available
                if hasattr(cli_ocr, 'profile') and cli_ocr.profile:
                    processed_files = cli_ocr.profile.stats.get('pages', 0)
                else:
                    processed_files = total_files

            except Exception as e:
                self.logger.error(f"OCR processing error: {e}")
                return {
                    "success": False,
                    "error": str(e)
                }

            end_time = time.time()

            return {
                "success": True,
                "processed_files": processed_files,
                "total_files": total_files,
                "processing_time": end_time - start_time
            }

        except Exception as e:
            self.logger.error(f"Unexpected error during OCR processing: {e}")
            return {
                "success": False,
                "error": str(e)
            }

    def run_segmentation_on_regions(self,
                                      xml_files: List[str],
                                      image_folder: str,
                                      outputdir: Optional[str],
                                      seg_model_path: Path,
                                      rec_model_path: Optional[Path],
                                      device: str,
                                      text_direction: str,
                                      same_names: bool,
                                      image_extensions: List[str],
                                      region_tagfilter: Optional[str],
                                      dry_run: bool,
                                      progress_callback=None) -> Dict[str, Any]:
        """
        Run segmentation on text regions from PAGE-XML files.
        """
        if not self.is_configured():
            return {"success": False, "error": "Kraken Python environment is not configured."}

        try:
            from pageplus.cli.ocr_kraken import segment as cli_segment
            import time
            start_time = time.time()

            # The CLI command will handle the async logic
            cli_segment(
                inputs=xml_files,
                image_folder=image_folder,
                outputdir=outputdir,
                seg_model_name=seg_model_path.name,
                model_dir=seg_model_path.parent,
                rec_model_name=rec_model_path.name if rec_model_path else None,
                jobs=1,  # Let the CLI handle internal async management
                device=device,
                text_direction=text_direction,
                same_names=same_names,
                image_extensions=[ImageExtension(ext) for ext in image_extensions],
                region_tagfilter=region_tagfilter,
                dry_run=dry_run
            )

            end_time = time.time()

            # Since the CLI function is running in the same process, we can't easily get a detailed result back
            # without more significant refactoring of the CLI command.
            # For now, we assume success if no exception is thrown.
            # The progress and logs will be visible in the console where Streamlit is running.
            return {
                "success": True,
                "processing_time": end_time - start_time,
                "processed_files": len(xml_files),
                "total_files": len(xml_files),
                "message": "Region segmentation process completed. Check console for details."
            }
        except Exception as e:
            self.logger.error(f"Error during region segmentation: {e}")
            return {"success": False, "error": str(e)}

    def get_installation_instructions(self) -> str:
        """Get instructions for installing Kraken in a separate environment."""
        return """
To use Kraken OCR, you need to install it in a separate Python environment:

1. Create a new virtual environment:
   ```
   python -m venv kraken_env
   source kraken_env/bin/activate  # On Windows: kraken_env\\Scripts\\activate
   ```

2. Install Kraken:
   ```
   pip install kraken
   ```

3. Configure PagePlus to use this environment:
   - Go to Settings → OCR Engines → Kraken OCR
   - Click "Set Python Environment"
   - Select the Python executable from your Kraken environment
   - Example path: /path/to/kraken_env/bin/python
"""
