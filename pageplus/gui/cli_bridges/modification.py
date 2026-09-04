from importlib import util
from typing import Any, Dict, List, Optional

from pageplus.cli.modification import (delete_fill_characters, delete_text, delete_textlines,
                                       extend_lines, fit_into_parent,
                                       match_textlines_to_region, match_textlines_to_smallest_region,
                                       merge_columnaligned_regions,
                                       merge_overlapping_textregions,
                                       pseudolinepolygon, pseudobaseline, reassign_ids,
                                       recalculate_textregion_polygon,
                                       rectangularize, remove_empty,
                                       remove_tag, repair, repair_dummy_region,
                                       replace_tag, reduce_polygon_points, simplify_polygon, set_page_version,
                                       sort, sort_and_merge,
                                       sort_regions, sort_two_column, text_mapping, top_tier_textregion,
                                       translate_lines, update_reading_order_index)
from pageplus.gui.cli_bridges.base import CLIBridge
from pageplus.gui.utils.undo import UndoManager


class ModificationBridge(CLIBridge):
    """Bridge for modification operations."""

    def text_mapping(
        self,
        files: List[str],
        mapping_profile: str = "GT4Hist",
        textnormalization: str = "NFC",
        mode: str = "deterministic",
        report: bool = False,
        dry_run: bool = False,
        outputdir: Optional[str] = None
    ) -> Dict[str, Any]:
        """Apply guideline-based text mapping to files."""
        try:
            if not dry_run:
                UndoManager.add_undo_state("Text Mapping")
            text_mapping(
                inputs=files,
                mapping_profile=mapping_profile,
                textnormalization=textnormalization,
                mode=mode,
                report=report,
                dry_run=dry_run,
                outputdir=outputdir
            )
            return {
                "success": True,
                "output": "Text mapping completed successfully"
            }
        except Exception as e:
            return {"success": False, "output": str(e)}

    @staticmethod
    def get_mapping_profiles() -> List[str]:
        """Returns a list of available mapping profiles."""
        from pageplus.gui.utils.guideline_editor_utils import GuidelineManager
        manager = GuidelineManager(profile_type="mappings", filename="mappings.json")
        return manager.get_profile_names()


    if (spec := util.find_spec('spellchecker')) is not None:
        from pageplus.cli.modification import \
            spellchecking as spellchecking_cli

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
                if not dry_run:
                    UndoManager.add_undo_state("Spellchecking")
                spellchecking_cli(
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

    def delete_fill_characters(
        self,
        files: List[str],
        levels: List[str] = ["TableRegion"],
        fill_character: str = ".",
        min_count: int = 2,
        outputdir: Optional[str] = None
    ) -> Dict[str, Any]:
        """Delete trailing fill characters from textlines."""
        try:
            UndoManager.add_undo_state("Delete Fill Characters")
            delete_fill_characters(
                inputs=files,
                levels=levels,
                fill_character=fill_character,
                min_count=min_count,
                outputdir=outputdir
            )
            return {
                "success": True,
                "output": "Fill characters deletion completed successfully"
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
            UndoManager.add_undo_state("Delete Text")
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
            UndoManager.add_undo_state("Delete Textlines")
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
            if not dry_run:
                UndoManager.add_undo_state("Remove Empty Elements")
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
            if not dry_run:
                UndoManager.add_undo_state("Reassign IDs")
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
            if not dry_run:
                UndoManager.add_undo_state("Repair")
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
            if not dry_run:
                UndoManager.add_undo_state("Translate Lines")
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
        """Extend lines in files (dim: 'all', 'x', 'y', 'left', 'right')."""
        try:
            if not dry_run:
                UndoManager.add_undo_state("Extend Lines")
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
            UndoManager.add_undo_state("Compute Pseudo Line Polygons")
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

    def pseudobaseline(
        self,
        files: List[str],
        position: str = "bottom",
        cut_to_polygon: bool = True,
        outputdir: Optional[str] = None,
        dry_run: bool = False
    ) -> Dict[str, Any]:
        """Compute pseudo baselines for files."""
        try:
            if not dry_run:
                UndoManager.add_undo_state("Compute Pseudo Baselines")
            pseudobaseline(
                inputs=files,
                position=position,
                cut_to_polygon=cut_to_polygon,
                outputdir=outputdir,
                dry_run=dry_run
            )
            return {
                "success": True,
                "output": "Pseudo baseline computation completed successfully"
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
            UndoManager.add_undo_state("Sort Elements")
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
            UndoManager.add_undo_state("Sort and Merge Elements")
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
            if not dry_run:
                UndoManager.add_undo_state("Split Big Regions Vertically")
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

    def set_metadata(self, files: List[str], creator: Optional[str], created: Optional[str], last_change: Optional[str], comments: Optional[str],
                     new: bool, default: bool, dry_run: bool):
        """Sets the PAGE XML metadata of the input files."""
        try:
            if not dry_run:
                UndoManager.add_undo_state("Set Metadata")
            from pageplus.cli.modification import set_metadata as set_metadata_cli
            set_metadata_cli(inputs=files, creator=creator, created=created, last_change=last_change, comments=comments, new=new, default=default, dry_run=dry_run)
            return {
                "success": True,
                "output": "Metadata set successfully"
            }
        except Exception as e:
            return {"success": False, "output": str(e)}

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
            if not dry_run:
                UndoManager.add_undo_state("Replace Tags")
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
            if not dry_run:
                UndoManager.add_undo_state("Remove Elements by Tag")
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
            if not dry_run:
                UndoManager.add_undo_state("Rectangularize Coordinates")
            rectangularize(
                inputs=files,
                level=level,
                outputdir=outputdir,
                dry_run=dry_run
            )
            return {
                "success": True,
                "output": "Coordinate rectangularization completed successfully"}
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
            if not dry_run:
                UndoManager.add_undo_state("Repair Dummy Regions")
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
            if not dry_run:
                UndoManager.add_undo_state("Fit Elements into Parent")
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
            if not dry_run:
                UndoManager.add_undo_state("Create Top-Tier Text Regions")
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
        only_sort: bool = False,
        tag_filter: Optional[List[str]] = None,
        outputdir: Optional[str] = None,
        dry_run: bool = False
    ) -> Dict[str, Any]:
        """Merge column-aligned text regions based on distance thresholds."""
        try:
            if not dry_run:
                UndoManager.add_undo_state("Merge Column-Aligned Regions")
            merge_columnaligned_regions(
                inputs=files,
                tolerance=tolerance,
                based_on_baselines=based_on_baselines,
                convex_hull_method=convex_hull_method,
                max_height_distance=max_height_distance,
                mid_tolerance=mid_tolerance,
                only_sort=only_sort,
                tag_filter=tag_filter,
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
        nested_regions: bool = False,
        outputdir: Optional[str] = None,
        dry_run: bool = False
    ) -> Dict[str, Any]:
        """Sort text regions based on a simple reading order."""
        try:
            if not dry_run:
                UndoManager.add_undo_state("Sort Regions")
            sort_regions(
                inputs=files,
                based_on_baselines=based_on_baselines,
                overlap_pct=overlap_pct,
                nested_regions=nested_regions,
                outputdir=outputdir,
                dry_run=dry_run
            )
            return {
                "success": True,
                "output": "Regions sorted successfully"
            }
        except Exception as e:
            return {"success": False, "output": str(e)}

    def sort_two_column(
        self,
        files: List[str],
        based_on_baselines: bool = False,
        gap_threshold: Optional[float] = None,
        center_tolerance: float = 0.15,
        span_width_ratio: float = 0.6,
        sort_lines: bool = True,
        update_reading_order: bool = True,
        outputdir: Optional[str] = None,
        dry_run: bool = False
    ) -> Dict[str, Any]:
        """Apply Two-Column Sorting Algorithm for newspapers and periodicals."""
        try:
            if not dry_run:
                UndoManager.add_undo_state("Two-Column Sorting")
            sort_two_column(
                inputs=files,
                based_on_baselines=based_on_baselines,
                gap_threshold=gap_threshold,
                center_tolerance=center_tolerance,
                span_width_ratio=span_width_ratio,
                sort_lines=sort_lines,
                update_reading_order=update_reading_order,
                outputdir=outputdir,
                dry_run=dry_run
            )
            return {
                "success": True,
                "output": "Two-column sorting completed successfully"
            }
        except Exception as e:
            return {"success": False, "output": str(e)}

    def update_reading_order_index(
        self,
        files: List[str],
        reorder_dom: bool = True,
        sort_lines: bool = False,
        outputdir: Optional[str] = None,
        dry_run: bool = False
    ) -> Dict[str, Any]:
        """Update region custom reading order attributes according to the ReadingOrder element."""
        try:
            if not dry_run:
                UndoManager.add_undo_state("Update Reading Order Indices")
            update_reading_order_index(
                inputs=files,
                reorder_dom=reorder_dom,
                sort_lines=sort_lines,
                outputdir=outputdir,
                dry_run=dry_run
            )
            return {
                "success": True,
                "output": "Reading order indices updated successfully"
            }
        except Exception as e:
            return {"success": False, "output": str(e)}

    def set_page_version(
        self,
        files: List[str],
        version: str,
        outputdir: Optional[str] = None,
        dry_run: bool = False,
        validate: bool = True
    ) -> Dict[str, Any]:
        """Update PAGE XML version (xmlns and schemaLocation) of input files."""
        try:
            if not dry_run:
                UndoManager.add_undo_state("Set PAGE Version")
            from pageplus.utils.constants import PcGtsVersion

            # Convert string to enum
            version_enum = None
            for v in PcGtsVersion:
                if v.value == version:
                    version_enum = v
                    break

            if version_enum is None:
                return {
                    "success": False,
                    "output": f"Invalid version: {version}. Valid versions: {[v.value for v in PcGtsVersion]}"
                }

            set_page_version(
                inputs=files,
                version=version_enum,
                outputdir=outputdir,
                dry_run=dry_run,
                validate=validate
            )
            return {
                "success": True,
                "output": f"PAGE XML version updated to {version} successfully"
            }
        except Exception as e:
            return {"success": False, "output": str(e)}

    def reduce_polygon_points(
        self,
        files: List[str],
        level: List[str] = ["TextRegion", "Textline"],
        tolerance: int = 2,
        outputdir: Optional[str] = None,
        dry_run: bool = False
    ) -> Dict[str, Any]:
        """Reduces the number of points in the polygon by a specified tolerance."""
        try:
            if not dry_run:
                UndoManager.add_undo_state("Reduce Polygon Points")
            reduce_polygon_points(
                inputs=files,
                level=level,
                tolerance=tolerance,
                outputdir=outputdir,
                dry_run=dry_run
            )
            return {
                "success": True,
                "output": "Polygon points reduced successfully"
            }
        except Exception as e:
            return {"success": False, "output": str(e)}

    def simplify_polygon(
        self,
        files: List[str],
        level: List[str] = ["TextRegion", "Textline"],
        tolerance: int = 2,
        outputdir: Optional[str] = None,
        dry_run: bool = False
    ) -> Dict[str, Any]:
        """Simplifies the polygon by a specified tolerance."""
        try:
            if not dry_run:
                UndoManager.add_undo_state("Simplify Polygon")
            simplify_polygon(
                inputs=files,
                level=level,
                tolerance=tolerance,
                outputdir=outputdir,
                dry_run=dry_run
            )
            return {
                "success": True,
                "output": "Polygon simplified successfully"
            }
        except Exception as e:
            return {"success": False, "output": str(e)}

    def match_textlines_to_region(
        self,
        files: List[str],
        outputdir: Optional[str] = None,
        slice_spanning: bool = False,
        slice_min_overlap: float = 0.1,
        dry_run: bool = False
    ) -> Dict[str, Any]:
        """Match textlines to regions in files.

        If ``slice_spanning`` is True, textlines that span multiple regions are
        split into separate textlines per region using the polygon
        intersection. ``slice_min_overlap`` controls the minimum
        intersection-over-line-area ratio for a region to receive a slice.
        """
        try:
            if not dry_run:
                UndoManager.add_undo_state("Match Textlines to Regions")
            match_textlines_to_region(
                inputs=files,
                outputdir=outputdir,
                slice_spanning=slice_spanning,
                slice_min_overlap=slice_min_overlap,
                dry_run=dry_run
            )
            return {
                "success": True,
                "output": "Textlines matched to regions successfully"
            }
        except Exception as e:
            return {"success": False, "output": str(e)}

    def match_textlines_to_smallest_region(
        self,
        files: List[str],
        outputdir: Optional[str] = None,
        min_overlap: float = 0.90,
        dry_run: bool = False
    ) -> Dict[str, Any]:
        """Match textlines to the smallest region."""
        try:
            if not dry_run:
                UndoManager.add_undo_state("Match Textlines to Smallest Region")
            match_textlines_to_smallest_region(
                inputs=files,
                outputdir=outputdir,
                min_overlap=min_overlap,
                dry_run=dry_run
            )
            return {
                "success": True,
                "output": "Textlines matched to smallest regions successfully"
            }
        except Exception as e:
            return {"success": False, "output": str(e)}

    def recalculate_textregion_polygon(
        self,
        files: List[str],
        rectangular: bool = False,
        min_textlines: int = 1,
        outputdir: Optional[str] = None,
        dry_run: bool = False
    ) -> Dict[str, Any]:
        """Recalculate TextRegion polygon from textlines."""
        try:
            if not dry_run:
                UndoManager.add_undo_state("Recalculate TextRegion Polygon")
            recalculate_textregion_polygon(
                inputs=files,
                rectangle=rectangular,
                min_textlines=min_textlines,
                outputdir=outputdir,
                dry_run=dry_run
            )
            return {
                "success": True,
                "output": "TextRegion polygon recalculated successfully"
            }
        except Exception as e:
            return {"success": False, "output": str(e)}

    def merge_overlapping_textregions(
        self,
        files: List[str],
        min_overlap_percentage: float = 50.0,
        recalculate_convex_hull: bool = False,
        tag_filter: Optional[List[str]] = None,
        outputdir: Optional[str] = None,
        dry_run: bool = False
    ) -> Dict[str, Any]:
        """Merge overlapping text regions."""
        try:
            if not dry_run:
                UndoManager.add_undo_state("Merge Overlapping TextRegions")
            merge_overlapping_textregions(
                inputs=files,
                min_overlap_percentage=min_overlap_percentage,
                recalculate_convex_hull=recalculate_convex_hull,
                tag_filter=tag_filter,
                outputdir=outputdir,
                dry_run=dry_run
            )
            return {
                "success": True,
                "output": "Overlapping text regions merged successfully"
            }
        except Exception as e:
            return {"success": False, "output": str(e)}

    def merge_table_rowspan_cells(
        self,
        files: List[str],
        outputdir: Optional[str] = None,
        dry_run: bool = False
    ) -> Dict[str, Any]:
        """Merge implicit rowspan cells in table regions."""
        try:
            if not dry_run:
                UndoManager.add_undo_state("Merge Table Rowspan Cells")
            from pageplus.cli.modification import merge_table_rowspan_cells
            modified_count = merge_table_rowspan_cells(
                inputs=files,
                outputdir=outputdir,
                dry_run=dry_run
            )
            if dry_run:
                msg = f"[DRY RUN] Completed check. Would modify {modified_count} file(s)."
            elif modified_count > 0:
                dest = "in-place (overwritten)" if outputdir is None else f"to '{outputdir}'"
                msg = f"Successfully modified and saved {modified_count} file(s) {dest}."
            else:
                msg = "No files needed modification (no tables met the rowspan merge criteria)."
            return {
                "success": True,
                "output": msg
            }
        except Exception as e:
            return {"success": False, "output": str(e)}

