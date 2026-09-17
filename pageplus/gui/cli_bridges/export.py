import logging
from pathlib import Path
from typing import List, Optional

from pageplus.cli.export import ReadingOrderMode, alto, dsv, fulltext, markdown, tei_fsl
try:
    from pageplus.cli.export import pdf
except ImportError:
    pdf = None
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
                       dehyphenate=dehyphenate, open_folder=open_folder, **kwargs)
        except Exception as e:
            logger.error(f"Error exporting to DSV: {str(e)}")
            raise e

    def export_alto(self,
                    files: List[Path],
                    output_dir: Optional[Path] = None, **kwargs) -> List[Path]:
        """Export files to ALTO format."""
        try:
            return alto(files, output_dir, **kwargs)
        except Exception as e:
            logger.error(f"Error exporting to ALTO: {str(e)}")
            raise e

    def export_fulltext(self,
                        files: List[Path],
                        output_dir: Optional[Path] = None,
                        dehyphenate: bool = False,
                        ro: bool = False,
                        ro_mode: str = "auto",
                        single_file: bool = False,
                        single_file_name: str = "fulltext_combined.txt",
                        separator: str = "-- Page {page-number}: {page-name} --",
                        open_folder: bool = True, **kwargs) -> List[Path]:
        """Export files to fulltext format."""
        try:
            try:
                mode = ReadingOrderMode(ro_mode)
            except ValueError:
                mode = ReadingOrderMode.auto
            return fulltext(
                files,
                output_dir,
                dehyphenate=dehyphenate,
                ro=ro,
                ro_mode=mode,
                single_file=single_file,
                single_file_name=single_file_name,
                separator=separator,
                open_folder=open_folder,
                **kwargs)
        except Exception as e:
            logger.error(f"Error exporting to fulltext: {str(e)}")
            raise e

    def export_markdown(self,
                        files: List[Path],
                        output_dir: Optional[Path] = None,
                        image_folder: Optional[str] = None,
                        snippet_folder: str = "images",
                        export_table_snippets: bool = True,
                        export_image_snippets: bool = True,
                        dehyphenate: bool = False,
                        ro: bool = True,
                        ro_mode: str = "auto",
                        single_file: bool = False,
                        single_file_name: str = "document_combined.md",
                        separator: str = "-- Page {page-number}: {page-name} --",
                        open_folder: bool = True, **kwargs) -> List[Path]:
        """Export files to Markdown format."""
        try:
            try:
                mode = ReadingOrderMode(ro_mode)
            except ValueError:
                mode = ReadingOrderMode.auto
            return markdown(
                files,
                output_dir,
                image_folder=image_folder,
                snippet_folder=snippet_folder,
                export_table_snippets=export_table_snippets,
                export_image_snippets=export_image_snippets,
                dehyphenate=dehyphenate,
                ro=ro,
                ro_mode=mode,
                single_file=single_file,
                single_file_name=single_file_name,
                separator=separator,
                open_folder=open_folder,
                **kwargs)
        except Exception as e:
            logger.error(f"Error exporting to Markdown: {str(e)}")
            raise e

    def export_pdf(self,
                   files: List[Path],
                   output_dir: Optional[Path] = None,
                   images: Optional[List[str]] = None,
                   dpi: Optional[int] = 300,
                   jpeg_quality: int = 85,
                   draw: List[str] = None,
                   line_thickness: float = 1.5,
                   substitutions: Optional[dict] = None,
                   output_filename: str = "PagePlus", **kwargs) -> List[Path]:
        """Export files to PDF format."""
        try:
            if pdf is None:
                logger.error("pikepdf is not installed. PDF export is unavailable.")
                return []
            # The new `pdf` function in cli/export.py handles everything.

            # We just need to call it with the right parameters.
            pdf(inputs=files,
                images=images,
                dpi=dpi,
                jpeg_quality=jpeg_quality,
                draw=draw or [],
                line_thickness=line_thickness,
                substitutions=substitutions,
                output_filename=output_filename,
                **kwargs)  # Pass any other GUI options
            
            output_path = output_dir.joinpath(output_filename + '.pdf') if output_dir else Path(files[0]).parent.joinpath(output_filename + '.pdf')
            return [output_path] if output_path.exists() else []

        except Exception as e:
            logger.error(f"Error exporting to PDF: {str(e)}")
            return []

    def export_tei_fsl(self,
                       files: List[Path],
                       output_dir: Optional[Path] = None,
                       werkteil: str = "Grammatik",
                       editor: str = "",
                       who: str = "",
                       status: str = "work_in_progress",
                       open_folder: bool = True, **kwargs) -> List[Path]:
        """Export files to TEI FSL format."""
        try:
            return tei_fsl(files, output_dir, werkteil=werkteil, editor=editor, who=who, status=status, open_folder=open_folder, **kwargs)
        except Exception as e:
            logger.error(f"Error exporting to TEI FSL: {str(e)}")
            raise e

    def export_files(self,
                     files: List[Path],
                     format: str,
                     output_dir: Optional[Path] = None,
                     **kwargs) -> List[Path]:
        """Export processed files to the specified format."""
        if format == "DSV":
            return self.export_dsv(files, output_dir, **kwargs)
        elif format == "ALTO":
            return self.export_alto(files, output_dir, **kwargs)
        elif format == "Fulltext":
            return self.export_fulltext(files, output_dir, **kwargs)
        elif format.lower() in ("markdown", "md"):
            return self.export_markdown(files, output_dir, **kwargs)
        elif format == "PDF":
            # Map img_dir to image_folder for PDF exports
            if 'img_dir' in kwargs:
                kwargs['image_folder'] = kwargs.pop('img_dir')
            if 'max_resolution' in kwargs:
                kwargs['dpi'] = kwargs.pop('max_resolution')
            return self.export_pdf(files, output_dir, **kwargs)
        elif format == "TEI_FSL":
            return self.export_tei_fsl(files, output_dir, **kwargs)
        elif format == "TEI":
            tei_format = kwargs.pop("tei_format", "fsl")
            if tei_format == "fsl":
                return self.export_tei_fsl(files, output_dir, **kwargs)
            else:
                logger.error(f"Unknown TEI format: {tei_format}")
                return []
        else:
            logger.error(f"Unknown export format: {format}")
            return []
