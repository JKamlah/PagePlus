from typing import List, Optional, Dict, Any
from importlib import util

from pageplus.gui.cli_bridges.base import CLIBridge
from pageplus.cli.modification import (
    delete_text,
    delete_textlines,
    remove_empty,
    reassign_ids,
    repair,
    translate_lines,
    extend_lines,
    pseudolinepolygon,
    sort,
    sort_and_merge,
    replace_tag,
    remove_tag,
    rectangularize,
    repair_dummy_region,
    fit_into_parent,
    top_tier_textregion,
    merge_columnaligned_regions,
    sort_regions
)

class ModificationBridge(CLIBridge):
    """Bridge for modification operations."""
    
    if (spec := util.find_spec('spellchecker')) is not None:
        from pageplus.cli.modification import spellchecking
        def spellchecking(
            self,
            files: List[str],
            language: str = "en",
            distance: int = 1,
            ignore_last_character: bool = False,
            workspace_dictionary: bool = False,
            workspace_word_length: int = 8,
            workspace_word_frequency: int = 50,
            report: bool = False,
            dry_run: bool = False
        ) -> Dict[str, Any]:
            """Run spellchecking on files."""
            try:
                spellchecking(
                    inputs=files,
                    language=language,
                    distance=distance,
                    ignore_last_character=ignore_last_character,
                    workspace_dictionary=workspace_dictionary,
                    workspace_word_length=workspace_word_length,
                    workspace_word_frequency=workspace_word_frequency,
                    report=report,
                    dry_run=dry_run
                )
                return {
                    "success": True,
                    "output": "Spellchecking completed successfully"
                }
            except Exception as e:
                return {"success": False, "output": str(e)}
    
    def delete_text(
        self,
        files: List[str],
        levels: List[str] = ["TextRegion", "TableRegion"],
        outputdir: Optional[str] = None
    ) -> Dict[str, Any]:
        """Delete text from files."""
        try:
            delete_text(
                inputs=files,
                levels=levels,
                outputdir=outputdir
            )
            return {
                "success": True,
                "output": "Text deletion completed successfully"
            }
        except Exception as e:
            return {"success": False, "output": str(e)}
    
    def delete_textlines(
        self,
        files: List[str],
        outputdir: Optional[str] = None
    ) -> Dict[str, Any]:
        """Delete textlines from files."""
        try:
            delete_textlines(
                inputs=files,
                outputdir=outputdir
            )
            return {
                "success": True,
                "output": "Textline deletion completed successfully"
            }
        except Exception as e:
            return {"success": False, "output": str(e)}
    
    def remove_empty(
        self,
        files: List[str],
        level: List[str] = None,
        outputdir: Optional[str] = None,
        dry_run: bool = False
    ) -> Dict[str, Any]:
        """Remove empty elements from files."""
        try:
            remove_empty(
                inputs=files,
                level=level,
                outputdir=outputdir,
                dry_run=dry_run
            )
            return {
                "success": True,
                "output": "Empty elements removal completed successfully"
            }
        except Exception as e:
            return {"success": False, "output": str(e)}
    
    def reassign_ids(
        self,
        files: List[str],
        reading_order_mode: str = "auto",
        outputdir: Optional[str] = None,
        dry_run: bool = False
    ) -> Dict[str, Any]:
        """Reassign IDs in files."""
        try:
            reassign_ids(
                inputs=files,
                reading_order_mode=reading_order_mode,
                outputdir=outputdir,
                dry_run=dry_run
            )
            return {
                "success": True,
                "output": "ID reassignment completed successfully"
            }
        except Exception as e:
            return {"success": False, "output": str(e)}
    
    def repair(
        self,
        files: List[str],
        outputdir: Optional[str] = None,
        dry_run: bool = False
    ) -> Dict[str, Any]:
        """Repair files."""
        try:
            repair(
                inputs=files,
                outputdir=outputdir,
                dry_run=dry_run
            )
            return {
                "success": True,
                "output": "Repair completed successfully"
            }
        except Exception as e:
            return {"success": False, "output": str(e)}
    
    def translate_lines(
        self,
        files: List[str],
        xoff: int = 0,
        yoff: int = 0,
        outputdir: Optional[str] = None,
        dry_run: bool = False
    ) -> Dict[str, Any]:
        """Translate lines in files."""
        try:
            translate_lines(
                inputs=files,
                xoff=xoff,
                yoff=yoff,
                outputdir=outputdir,
                dry_run=dry_run
            )
            return {
                "success": True,
                "output": "Line translation completed successfully"
            }
        except Exception as e:
            return {"success": False, "output": str(e)}
    
    def extend_lines(
        self,
        files: List[str],
        distance: int = 8,
        dim: str = "all",
        rectangularize: bool = True,
        cut_overlaps: bool = True,
        outputdir: Optional[str] = None,
        dry_run: bool = False
    ) -> Dict[str, Any]:
        """Extend lines in files."""
        try:
            extend_lines(
                inputs=files,
                distance=distance,
                dim=dim,
                rectangularize=rectangularize,
                cut_overlaps=cut_overlaps,
                outputdir=outputdir,
                dry_run=dry_run
            )
            return {
                "success": True,
                "output": "Line extension completed successfully"
            }
        except Exception as e:
            return {"success": False, "output": str(e)}
    
    def pseudolinepolygon(
        self,
        files: List[str],
        outputdir: Optional[str] = None
    ) -> Dict[str, Any]:
        """Compute pseudo line polygons for files."""
        try:
            pseudolinepolygon(
                inputs=files,
                outputdir=outputdir
            )
            return {
                "success": True,
                "output": "Pseudo line polygon computation completed"
            }
        except Exception as e:
            return {"success": False, "output": str(e)}
    
    def sort(
        self,
        files: List[str],
        outputdir: Optional[str] = None
    ) -> Dict[str, Any]:
        """Sort elements in files."""
        try:
            sort(
                inputs=files,
                outputdir=outputdir
            )
            return {
                "success": True,
                "output": "Sort completed successfully"
            }
        except Exception as e:
            return {"success": False, "output": str(e)}

    def sort_and_merge(
        self,
        files: List[str],
        merge_lines_gap_x: int = 64,
        merge_lines_gap_y: int = 10,
        outputdir: Optional[str] = None
    ) -> Dict[str, Any]:
        """Sort and merge elements in files."""
        try:
            sort_and_merge(
                inputs=files,
                merge_lines_gap_x=merge_lines_gap_x,
                merge_lines_gap_y=merge_lines_gap_y,
                outputdir=outputdir
            )
            return {
                "success": True,
                "output": "Sort and merge completed successfully"
            }
        except Exception as e:
            return {"success": False, "output": str(e)}
    
    def split_big_regions_vertical(
        self,
        files: List[str],
        split_min_area: int = 4500000,
        scale_min_area_by_maxlines: int = 140,
        outputdir: Optional[str] = None,
        dry_run: bool = False
    ) -> Dict[str, Any]:
        """Split big regions vertically in files."""
        try:
            from pageplus.cli.modification import split_big_regions_vertical
            split_big_regions_vertical(
                inputs=files,
                split_min_area=split_min_area,
                scale_min_area_by_maxlines=scale_min_area_by_maxlines,
                outputdir=outputdir,
                dry_run=dry_run
            )
            return {
                "success": True,
                "output": "Split big regions completed successfully"
            }
        except Exception as e:
            return {"success": False, "output": str(e)}
    
    # Metadata Operations
    def update_metadata(self, files: List[str], key: str, value: str) -> None:
        """Update metadata in selected files."""
        for file in files:
            # TODO: Implement metadata update using CLI functions
            pass
    
    def remove_metadata(self, files: List[str], key: str) -> None:
        """Remove metadata from selected files."""
        for file in files:
            # TODO: Implement metadata removal using CLI functions
            pass
    
    def add_metadata(self, files: List[str], key: str, value: str) -> None:
        """Add metadata to selected files."""
        for file in files:
            # TODO: Implement metadata addition using CLI functions
            pass
    
    # Batch Operations
    def batch_rename(self, files: List[str], pattern: str) -> None:
        """Rename files according to pattern."""
        for i, file in enumerate(files):
            # TODO: Implement batch renaming using CLI functions
            pass
    
    def batch_convert(self, files: List[str], target_format: str) -> None:
        """Convert files to target format."""
        for file in files:
            # TODO: Implement batch conversion using CLI functions
            pass
    
    def batch_process(self, files: List[str], process_type: str) -> None:
        """Process files according to type."""
        for file in files:
            # TODO: Implement batch processing using CLI functions
            pass

    def replace_tag(
        self,
        files: List[str],
        old_tag: str,
        new_tag: str,
        level: List[str] = ["TextRegion", "Textline"],
        textfilter: Optional[str] = None,
        skip_textfilter: bool = False,
        outputdir: Optional[str] = None,
        dry_run: bool = False
    ) -> Dict[str, Any]:
        """Replace tags in files."""
        try:
            replace_tag(
                inputs=files,
                old_tag=old_tag,
                new_tag=new_tag,
                level=level,
                textfilter=textfilter,
                skip_textfilter=skip_textfilter,
                outputdir=outputdir,
                dry_run=dry_run
            )
            return {
                "success": True,
                "output": "Tag replacement completed successfully"
            }
        except Exception as e:
            return {"success": False, "output": str(e)}

    def remove_tag(
        self,
        files: List[str],
        tag_to_remove: str,
        level: List[str] = ["TextRegion", "Textline"],
        textfilter: Optional[str] = None,
        skip_textfilter: bool = False,
        outputdir: Optional[str] = None,
        dry_run: bool = False
    ) -> Dict[str, Any]:
        """Remove elements with specified tags from files."""
        try:
            remove_tag(
                inputs=files,
                tag_to_remove=tag_to_remove,
                level=level,
                textfilter=textfilter,
                skip_textfilter=skip_textfilter,
                outputdir=outputdir,
                dry_run=dry_run
            )
            return {
                "success": True,
                "output": "Element removal by tag completed successfully"
            }
        except Exception as e:
            return {"success": False, "output": str(e)}

    def rectangularize(
        self,
        files: List[str],
        level: List[str] = ["TextRegion", "Textline"],
        outputdir: Optional[str] = None,
        dry_run: bool = False
    ) -> Dict[str, Any]:
        """Rectangularize coordinates in files."""
        try:
            rectangularize(
                inputs=files,
                level=level,
                outputdir=outputdir,
                dry_run=dry_run
            )
            return {
                "success": True,
                "output": "Coordinate rectangularization completed successfully"
            }
        except Exception as e:
            return {"success": False, "output": str(e)}

    def repair_dummy_region(
        self,
        files: List[str],
        outputdir: Optional[str] = None,
        dry_run: bool = False
    ) -> Dict[str, Any]:
        """Repair TextRegions with invalid coordinates."""
        try:
            repair_dummy_region(
                inputs=files,
                outputdir=outputdir,
                dry_run=dry_run
            )
            return {
                "success": True,
                "output": "Dummy region repair completed successfully"
            }
        except Exception as e:
            return {"success": False, "output": str(e)}

    def fit_into_parent(
        self,
        files: List[str],
        level: List[str] = ["TextRegion", "Textline"],
        outputdir: Optional[str] = None,
        dry_run: bool = False
    ) -> Dict[str, Any]:
        """Fit elements into their parent boundaries."""
        try:
            fit_into_parent(
                inputs=files,
                level=level,
                outputdir=outputdir,
                dry_run=dry_run
            )
            return {
                "success": True,
                "output": "Elements fitted into parent boundaries successfully"
            }
        except Exception as e:
            return {"success": False, "output": str(e)}

    def top_tier_textregion(
        self,
        files: List[str],
        outputdir: Optional[str] = None,
        dry_run: bool = False
    ) -> Dict[str, Any]:
        """Create top tier text regions by merging multiple regions into one."""
        try:
            top_tier_textregion(
                inputs=files,
                outputdir=outputdir,
                dry_run=dry_run
            )
            return {
                "success": True,
                "output": "Top tier text regions created successfully"
            }
        except Exception as e:
            return {"success": False, "output": str(e)}

    def merge_columnaligned_regions(
        self,
        files: List[str],
        tolerance: float = 0.1,
        based_on_baselines: bool = True,
        convex_hull_method: str = 'region',
        max_height_distance: float = 0.75,
        mid_tolerance: float = 0.0,
        outputdir: Optional[str] = None,
        dry_run: bool = False
    ) -> Dict[str, Any]:
        """Merge column-aligned text regions based on distance thresholds."""
        try:
            merge_columnaligned_regions(
                inputs=files,
                tolerance=tolerance,
                based_on_baselines=based_on_baselines,
                convex_hull_method=convex_hull_method,
                max_height_distance=max_height_distance,
                mid_tolerance=mid_tolerance,
                outputdir=outputdir,
                dry_run=dry_run
            )
            return {
                "success": True,
                "output": "Column-aligned regions merged successfully"
            }
        except Exception as e:
            return {"success": False, "output": str(e)}

    def sort_regions(
        self,
        files: List[str],
        based_on_baselines: bool = False,
        overlap_pct: float = 60.0,
        outputdir: Optional[str] = None,
        dry_run: bool = False
    ) -> Dict[str, Any]:
        """Sort text regions based on a simple reading order."""
        try:
            sort_regions(
                inputs=files,
                based_on_baselines=based_on_baselines,
                overlap_pct=overlap_pct,
                outputdir=outputdir,
                dry_run=dry_run
            )
            return {
                "success": True,
                "output": "Regions sorted successfully"
            }
        except Exception as e:
            return {"success": False, "output": str(e)}