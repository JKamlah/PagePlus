import logging
from pathlib import Path
from typing import List, Optional

from pageplus.cli.export import ReadingOrderMode, alto, dsv, fulltext, pdf
from pageplus.gui.cli_bridges import CLIBridge

logger = logging.getLogger(__name__)


class ExportBridge(CLIBridge):
    """Bridge for export functionality."""

    def export_dsv(self,
                   files: List[Path],
                   output_dir: Optional[Path] = None,
                   delimiter: str = '\t',
                   dehyphenate: bool = False,
                   open_folder: bool = True, **kwargs) -> List[Path]:
        """Export files to DSV format."""
        try:
            return dsv(files, output_dir, delimiter=delimiter,
                       dehyphenate=dehyphenate, open_folder=open_folder)
        except Exception as e:
            logger.error(f"Error exporting to DSV: {str(e)}")
            return []

    def export_alto(self,
                    files: List[Path],
                    output_dir: Optional[Path] = None, **kwargs) -> List[Path]:
        """Export files to ALTO format."""
        try:
            return alto(files, output_dir)
        except Exception as e:
            logger.error(f"Error exporting to ALTO: {str(e)}")
            return []

    def export_fulltext(self,
                        files: List[Path],
                        output_dir: Optional[Path] = None,
                        dehyphenate: bool = False,
                        ro: bool = False,
                        ro_mode: str = "auto",
                        open_folder: bool = True, **kwargs) -> List[Path]:
        """Export files to fulltext format."""
        try:
            return fulltext(
                files,
                output_dir,
                dehyphenate=dehyphenate,
                ro=ro,
                ro_mode=ReadingOrderMode(ro_mode),
                open_folder=open_folder)
        except Exception as e:
            logger.error(f"Error exporting to fulltext: {str(e)}")
            return []

    def export_pdf(self,
                   files: List[Path],
                   output_dir: Optional[Path] = None,
                   images: Optional[List[str]] = None,
                   dpi: int = 400,
                   max_resolution: int = 72,
                   draw: List[str] = None,
                   substitutions: Optional[dict] = None,
                   output_filename: str = "PagePlus", **kwargs) -> List[Path]:
        """Export files to PDF format."""
        try:
            return pdf(files,
                       images=images,
                       dpi=dpi,
                       max_resolution=max_resolution,
                       draw=draw or [],
                       substitutions=substitutions,
                       output_filename=output_filename)
        except Exception as e:
            logger.error(f"Error exporting to PDF: {str(e)}")
            return []

    def export_files(self,
                     files: List[Path],
                     format: str,
                     output_dir: Optional[Path] = None,
                     **kwargs) -> List[Path]:
        """Export processed files to the specified format."""
        if format == "DSV":
            return self.export_dsv(files, output_dir, **kwargs)
        elif format == "ALTO":
            return self.export_alto(files, output_dir)
        elif format == "Fulltext":
            return self.export_fulltext(files, output_dir, **kwargs)
        elif format == "PDF":
            # Map img_dir to image_folder for PDF exports
            if 'img_dir' in kwargs:
                kwargs['image_folder'] = kwargs.pop('img_dir')
            return self.export_pdf(files, output_dir, **kwargs)
        else:
            logger.error(f"Unknown export format: {format}")
            return []
