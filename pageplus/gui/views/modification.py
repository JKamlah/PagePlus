from importlib import util
from datetime import datetime
import json
from typing import Any
import inspect

import streamlit as st

from pageplus.gui.cli_bridges import ModificationBridge
from pageplus.gui.utils.picker import pick_directory
from pageplus.models.page import Page
from pageplus.utils.constants import TextLevel
from pathlib import Path


def show_modification(bridge: ModificationBridge) -> None:
    """Show modification view."""
    if not st.session_state.loaded_files:
        st.warning("Please load files first in the 'Input' page.")
        return

    st.title("🛠️ Modification")

    if 'modification_batch' not in st.session_state:
        st.session_state.modification_batch = []

    def record_operation(op_name: str, **kwargs: Any) -> None:
        """Record a modification operation."""
        record_kwargs = {}
        for key, value in kwargs.items():
            if hasattr(value, 'name'):
                record_kwargs[key] = value.name
            elif isinstance(value, list) and value and hasattr(value[0], 'name'):
                record_kwargs[key] = [item.name for item in value]
            elif isinstance(value, list) and value and isinstance(value[0], Path):
                record_kwargs[key] = [str(item) for item in value]
            else:
                record_kwargs[key] = value

        if "files" in record_kwargs:
            del record_kwargs["files"]

        st.session_state.modification_batch.append({
            "operation": op_name,
            "parameters": record_kwargs
        })

    main_tabs = st.tabs(["Interactive", "Batch"])

    with main_tabs[0]:
        # Get available files from session state
        selected_files = [str(f) for f in st.session_state.loaded_files]

        # Select output directory
        st.write("Output directory: The default is to overwrite the input files (recommended with backup strategy).")
        if st.button("Select Output Directory"):
            selected_paths = pick_directory(initial_dir=Path.home())
            if selected_paths:
                st.session_state.modification_dir = selected_paths
            elif selected_paths is not None:
                st.info("Directory selection cancelled.")

        if 'modification_dir' in st.session_state:
            st.text_input(
                "Selected Output Directory",
                value=st.session_state.modification_dir,
                disabled=True,
                label_visibility="visible"
            )
            if st.button("Clear Output Directory"):
                del st.session_state.modification_dir
                st.rerun()

        # Operation tabs
        tab_names = ["🧾 Format & Metadata",
                     "📐 Text-Layout",
                     "✨ Text-Attributes",
                     "📝 Text-Content",
                     "🔧 Repair"]
        tabs = st.tabs(tab_names)

        with tabs[0]:  # Format&Metadata
            st.subheader("Format & Metadata Operations")
            with st.expander("Set PAGE Version"):
                st.write("Updates the PAGE XML version (xmlns and schemaLocation) of the input files.")

                from pageplus.utils.constants import PcGtsVersion

                version_options = [v.value for v in PcGtsVersion]
                selected_version = st.selectbox(
                    "Target PAGE XML Version",
                    options=version_options,
                    index=len(version_options) - 1,  # Default to latest version
                    help="Select the target PAGE XML version for conversion.",
                    key="set_page_version_version"
                )

                col1, col2 = st.columns(2)
                with col1:
                    dry_run = st.checkbox("Dry run", key="set_page_version_dry_run")
                with col2:
                    validate = st.checkbox("Validate compatibility", value=True, key="set_page_version_validate",
                                           help="Check for compatibility issues before conversion")

                if st.button("Set PAGE Version"):
                    params = {
                        "version": selected_version,
                        "dry_run": dry_run,
                        "validate": validate,
                        "outputdir": st.session_state.get('modification_dir')
                    }
                    record_operation("set_page_version", **params)
                    with st.spinner("Updating PAGE XML version...", show_time=True):
                        result = bridge.set_page_version(files=selected_files, **params)
                    if result["success"]:
                        st.success(result["output"])
                    else:
                        st.error(result["output"])

            with st.expander("Set Metadata", expanded=False):
                st.write("Update the metadata for the loaded PAGE XML files.")

                metadata_options = ["Creator", "Comments", "Created", "Last Change"]
                selected_options = st.multiselect(
                    "Fields to update",
                    options=metadata_options,
                    default=["Creator", "Last Change"],
                    key="metadata_fields_to_update"
                )

                creator = st.text_input("Creator", key="metadata_creator", value="PagePlus", disabled="Creator" not in selected_options)
                comments = st.text_area("Comments", key="metadata_comments", disabled="Comments" not in selected_options)

                col1, col2 = st.columns(2)
                with col1:
                    created_date = st.date_input("Created Date", value=datetime.now(), key="metadata_created_date", disabled="Created" not in selected_options)
                    created_time = st.time_input("Created Time", value=datetime.now().time(), key="metadata_created_time", disabled="Created" not in selected_options)
                with col2:
                    last_change_date = st.date_input("Last Change Date", value=datetime.now(), key="metadata_last_change_date", disabled="Last Change" not in selected_options)
                    last_change_time = st.time_input("Last Change Time", value=datetime.now().time(), key="metadata_last_change_time", disabled="Last Change" not in selected_options)

                # created_datetime = datetime.combine(created_date, created_time).strftime("%Y-%m-%d %H:%M:%S")
                # last_change_datetime = datetime.combine(last_change_date, last_change_time).strftime("%Y-%m-%d %H:%M:%S")

                col_opts1, col_opts2, col_opts3 = st.columns(3)
                with col_opts1:
                    default_metadata = st.checkbox("Use Default Metadata", key="metadata_default")
                with col_opts2:
                    new_metadata = st.checkbox("Overwrite Existing (new)", key="metadata_new")
                with col_opts3:
                    dry_run_metadata = st.checkbox("Dry Run", key="metadata_dry_run")

                if st.button("Set Metadata", key="set_metadata_button"):
                    if not st.session_state.loaded_files:
                        st.warning("Please load files first.")
                    else:
                        params = {
                            "creator": creator if "Creator" in selected_options else None,
                            "created": datetime.combine(created_date, created_time).strftime("%Y-%m-%d %H:%M:%S") if "Created" in selected_options else None,
                            "last_change": datetime.combine(last_change_date, last_change_time).strftime("%Y-%m-%d %H:%M:%S") if "Last Change" in selected_options else None,
                            "comments": comments if "Comments" in selected_options else None,
                            "new": new_metadata,
                            "default": default_metadata,
                            "dry_run": dry_run_metadata
                        }
                        record_operation("set_metadata", **params)
                        with st.spinner("Setting metadata...", show_time=True):
                            result = bridge.set_metadata(files=selected_files, **params)
                        if result["success"]:
                            st.success(result["output"])
                        else:
                            st.error(result["output"])

        with tabs[1]:  # Text Operations
            st.subheader("Text-Layout Operations")
            # Remove Empty
            with st.expander("Remove Empty Text Levels"):
                level = st.multiselect(
                    "Level",
                    [TextLevel.TextRegion.name, TextLevel.Textline.name, TextLevel.TableRegion.name],
                    default=[TextLevel.TextRegion.name, TextLevel.Textline.name],
                    key="remove_empty_level"
                )
                dry_run = st.checkbox("Dry run", key="remove_empty_dry_run")
                if st.button("Remove Empty"):
                    params = {
                        "level": [TextLevel[name] for name in level],
                        "dry_run": dry_run,
                        "outputdir": st.session_state.get('modification_dir')
                    }
                    record_operation("remove_empty", **params)
                    with st.spinner("Removing empty elements...", show_time=True):
                        result = bridge.remove_empty(files=selected_files, **params)
                    if result["success"]:
                        st.success(result["output"])
                    else:
                        st.error(result["output"])

            # Delete Textlines
            with st.expander("Delete Textlines (with content)"):
                if st.button("Delete Textlines"):
                    params = {"outputdir": st.session_state.get('modification_dir')}
                    record_operation("delete_textlines", **params)
                    with st.spinner("Deleting textlines...", show_time=True):
                        result = bridge.delete_textlines(files=selected_files, **params)
                    if result["success"]:
                        st.success(result["output"])
                    else:
                        st.error(result["output"])

            st.subheader("Modify Polygon Operations")
            # Translate Lines
            with st.expander("Translate Lines"):
                xoff = st.number_input(
                    "X offset",
                    value=0,
                    key="translate_lines_xoff"
                )
                yoff = st.number_input(
                    "Y offset",
                    value=0,
                    key="translate_lines_yoff"
                )
                dry_run = st.checkbox("Dry run", key="translate_lines_dry_run")
                if st.button("Translate Lines"):
                    params = {
                        "xoff": xoff,
                        "yoff": yoff,
                        "dry_run": dry_run,
                        "outputdir": st.session_state.get('modification_dir')
                    }
                    record_operation("translate_lines", **params)
                    with st.spinner("Translating lines...", show_time=True):
                        result = bridge.translate_lines(files=selected_files, **params)
                    if result["success"]:
                        st.success(result["output"])
                    else:
                        st.error(result["output"])

            # Extend Lines
            with st.expander("Extend Lines"):
                distance = st.number_input(
                    "Distance",
                    min_value=1,
                    value=8,
                    key="extend_lines_distance"
                )
                dim = st.selectbox(
                    "Dimension",
                    ["all", "x", "y", "left", "right"],
                    key="extend_lines_dim"
                )
                rectangularize = st.checkbox(
                    "Rectangularize", key="extend_lines_rectify")
                cut_overlaps = st.checkbox(
                    "Cut overlaps",
                    key="extend_lines_cut_overlaps"
                )
                dry_run = st.checkbox("Dry run", key="extend_lines_dry_run")
                if st.button("Extend Lines"):
                    params = {
                        "distance": distance,
                        "dim": dim,
                        "rectangularize": rectangularize,
                        "cut_overlaps": cut_overlaps,
                        "dry_run": dry_run,
                        "outputdir": st.session_state.get('modification_dir')
                    }
                    record_operation("extend_lines", **params)
                    with st.spinner("Extending lines...", show_time=True):
                        result = bridge.extend_lines(files=selected_files, **params)
                    if result["success"]:
                        st.success(result["output"])
                    else:
                        st.error(result["output"])

            st.subheader("Recalculate Polygon Operations")
            # Rectangularize Coordinates
            with st.expander("Rectangularize"):
                st.write(
                    """Rectangularizes the coordinates of textlines and regions.""")

                levels = st.multiselect(
                    "Level",
                    [TextLevel.TextRegion.name, TextLevel.Textline.name, TextLevel.TableRegion.name],
                    default=[TextLevel.TextRegion.name, TextLevel.Textline.name],
                    key="rectangularize_level"
                )
                dry_run = st.checkbox("Dry run", key="rectangularize_dry_run")

                if st.button("Rectangularize Coordinates"):
                    params = {
                        "level": [TextLevel[name] for name in levels],
                        "dry_run": dry_run,
                        "outputdir": st.session_state.get('modification_dir')
                    }
                    record_operation("rectangularize", **params)
                    with st.spinner("Rectangularizing coordinates...", show_time=True):
                        result = bridge.rectangularize(files=selected_files, **params)
                    if result["success"]:
                        st.success(result["output"])
                    else:
                        st.error(result["output"])

            # Reduce Polygon Points
            with st.expander("Reduce Polygon Points"):
                st.write(
                    """Reduces the number of points in the polygon by a specified tolerance.""")
                levels = st.multiselect(
                    "Level",
                    [TextLevel.TextRegion.name, TextLevel.Textline.name, TextLevel.TableRegion.name],
                    default=[TextLevel.TextRegion.name, TextLevel.Textline.name],
                    key="reduce_polygon_points_level"
                )
                tolerance = st.number_input(
                    "Tolerance",
                    min_value=0,
                    value=2,
                    key="reduce_polygon_points_tolerance"
                )
                dry_run = st.checkbox("Dry run", key="reduce_polygon_points_dry_run")
                if st.button("Reduce Polygon Points"):
                    params = {
                        "level": [TextLevel[name] for name in levels],
                        "tolerance": tolerance,
                        "dry_run": dry_run,
                        "outputdir": st.session_state.get('modification_dir')
                    }
                    record_operation("reduce_polygon_points", **params)
                    with st.spinner("Reducing polygon points...", show_time=True):
                        result = bridge.reduce_polygon_points(
                            files=selected_files, **params)
                    if result["success"]:
                        st.success(result["output"])
                    else:
                        st.error(result["output"])

            # Simplify Polygon
            with st.expander("Simplify Polygon"):
                st.write(
                    """Simplifies the polygon by a specified tolerance.""")
                levels = st.multiselect(
                    "Level",
                    [TextLevel.TextRegion.name, TextLevel.Textline.name, TextLevel.TableRegion.name],
                    default=[TextLevel.TextRegion.name, TextLevel.Textline.name],
                    key="simplify_polygon_level"
                )
                tolerance = st.number_input(
                    "Tolerance",
                    min_value=0,
                    value=2,
                    key="simplify_polygon_tolerance"
                )
                dry_run = st.checkbox("Dry run", key="simplify_polygon_dry_run")
                if st.button("Simplify Polygon"):
                    params = {
                        "level": [TextLevel[name] for name in levels],
                        "tolerance": tolerance,
                        "dry_run": dry_run,
                        "outputdir": st.session_state.get('modification_dir')
                    }
                    record_operation("simplify_polygon", **params)
                    with st.spinner("Simplifying polygon...", show_time=True):
                        result = bridge.simplify_polygon(
                            files=selected_files, **params)
                    if result["success"]:
                        st.success(result["output"])
                    else:
                        st.error(result["output"])

            # Pseudoline Polygon
            with st.expander("Pseudoline Polygon"):
                if st.button("Pseudoline Polygon"):
                    params = {"outputdir": st.session_state.get('modification_dir')}
                    record_operation("pseudolinepolygon", **params)
                    with st.spinner("Generating pseudo-line polygons...", show_time=True):
                        result = bridge.pseudolinepolygon(files=selected_files, **params)
                    if result["success"]:
                        st.success(result["output"])
                    else:
                        st.error(result["output"])

            # Pseudobaseline
            with st.expander("Pseudobaseline"):
                st.write("Calculates pseudo-baselines from textline polygons, optionally mapped/clipped inside the polygon.")
                position = st.selectbox(
                    "Position",
                    ["bottom", "mid", "top"],
                    index=0,
                    key="pseudobaseline_position"
                )
                cut_to_polygon = st.checkbox(
                    "Cut / map baseline to existing polygon",
                    value=True,
                    key="pseudobaseline_cut_to_polygon"
                )
                dry_run = st.checkbox("Dry run", key="pseudobaseline_dry_run")
                if st.button("Calculate Pseudo-Baselines"):
                    params = {
                        "position": position,
                        "cut_to_polygon": cut_to_polygon,
                        "dry_run": dry_run,
                        "outputdir": st.session_state.get('modification_dir')
                    }
                    record_operation("pseudobaseline", **params)
                    with st.spinner("Calculating pseudo-baselines...", show_time=True):
                        result = bridge.pseudobaseline(files=selected_files, **params)
                    if result["success"]:
                        st.success(result["output"])
                    else:
                        st.error(result["output"])

            # Recalculate TextRegion Polygon
            with st.expander("Recalculate TextRegion Polygon"):
                st.write(
                    """Recalculates the polygon of a TextRegion, either from its textlines (convex hull) or by its minimal bounding box (rectangular)."""
                )
                rectangular = st.checkbox(
                    "Rectangular",
                    key="recalculate_textregion_polygon_rectangular"
                )
                min_textlines = st.number_input(
                    "Minimum Textlines",
                    min_value=0,
                    value=0,
                    key="recalculate_textregion_polygon_min_textlines"
                )
                dry_run = st.checkbox(
                    "Dry run",
                    key="recalculate_textregion_polygon_dry_run"
                )
                if st.button("Recalculate TextRegion Polygon"):
                    params = {
                        "rectangular": rectangular,
                        "min_textlines": min_textlines,
                        "dry_run": dry_run,
                        "outputdir": st.session_state.get('modification_dir')
                    }
                    record_operation("recalculate_textregion_polygon", **params)
                    with st.spinner("Recalculating TextRegion polygon...", show_time=True):
                        result = bridge.recalculate_textregion_polygon(
                            files=selected_files, **params
                        )
                    if result["success"]:
                        st.success(result["output"])
                    else:
                        st.error(result["output"])

            # Fit into Parent
            with st.expander("Fit into Parent"):
                st.write("""
                Fits TextRegions, TableRegions, and Textlines into their parent boundaries.
                This ensures that no element extends beyond its parent's boundaries.
                """)

                levels = st.multiselect(
                    "Level",
                    [TextLevel.TextRegion.name, TextLevel.Textline.name, TextLevel.TableRegion.name],
                    default=[TextLevel.TextRegion.name, TextLevel.Textline.name],
                    key="fit_into_parent_level"
                )
                dry_run = st.checkbox("Dry run", key="fit_into_parent_dry_run")

                if st.button("Fit into Parent"):
                    params = {
                        "level": [TextLevel[name] for name in levels],
                        "dry_run": dry_run,
                        "outputdir": st.session_state.get('modification_dir')
                    }
                    record_operation("fit_into_parent", **params)
                    with st.spinner("Fitting elements into parent boundaries...", show_time=True):
                        result = bridge.fit_into_parent(files=selected_files, **params)
                    if result["success"]:
                        st.success(result["output"])
                    else:
                        st.error(result["output"])

            st.subheader("Merging/Splitting Regions Operations")

            # Top Tier TextRegion
            with st.expander("Top Tier TextRegion"):
                st.write("""
                Creates a convex hull for all textlines and deletes single text regions.
                This merges multiple TextRegions into one top-tier region with a convex hull boundary.
                """)

                dry_run = st.checkbox("Dry run", key="top_tier_textregion_dry_run")

                if st.button("Create Top Tier TextRegion"):
                    params = {
                        "dry_run": dry_run,
                        "outputdir": st.session_state.get('modification_dir')
                    }
                    record_operation("top_tier_textregion", **params)
                    with st.spinner("Creating top-tier text regions...", show_time=True):
                        result = bridge.top_tier_textregion(files=selected_files, **params)
                    if result["success"]:
                        st.success(result["output"])
                    else:
                        st.error(result["output"])

            # Merge Column-Aligned Regions
            with st.expander("Merge Column-Aligned Regions"):
                st.write("""
                Merges column-aligned text regions based on distance thresholds.
                Groups regions whose centroids are within the width variance tolerance and merges them into a single region with a convex hull boundary.
                """)

                based_on_baselines = st.checkbox(
                    "Based on Baselines",
                    value=False,
                    help="If checked, merge regions based on their mean textline baseline centroid. If unchecked, use the geometric centroid of the region's polygon.",
                    key="merge_columnaligned_baselines")

                convex_hull_method = st.selectbox(
                    "Convex Hull Method",
                    options=[
                        'region',
                        'textlines'],
                    index=0,
                    help="Method to use for convex hull calculation. 'region' uses regions coordinates. 'textlines' uses the coordinates of all textlines within the merged regions.",
                    key="merge_columnaligned_hull_method")

                max_height_distance = st.slider(
                    "Max Height Distance (%)",
                    min_value=0.0,
                    max_value=1.0,
                    value=0.75,
                    step=0.01,
                    help="Maximum vertical distance between region centroids for merging, as a percentage of page height.",
                    key="merge_columnaligned_max_height")

                mid_tolerance = st.slider(
                    "Mid Tolerance (%)",
                    min_value=0.0,
                    max_value=1.0,
                    value=0.0,
                    step=0.01,
                    help="A tolerance (percentage of page width) to ignore centroids too close to the middle of the page.",
                    key="merge_columnaligned_mid_tolerance")

                tolerance = st.slider(
                    "Tolerance",
                    min_value=0.01,
                    max_value=1.0,
                    value=0.1,
                    step=0.01,
                    help="Tolerance for merging regions (0.01 = 1%, 1.0 = 100%)",
                    key="merge_columnaligned_tolerance"
                )

                # Tag filtering
                if "merge_columnaligned_tag_options" not in st.session_state:
                    st.session_state.merge_columnaligned_tag_options = []
                if "merge_columnaligned_tags" not in st.session_state:
                    st.session_state.merge_columnaligned_tags = []

                if st.button("Update tags", key="merge_columnaligned_update_tags_btn"):
                    st.session_state.merge_columnaligned_tag_options = sorted(set(tag for tags in [Page(Path(f)).get_tags([TextLevel.TextRegion]) for f in selected_files] for tag in tags))
                    st.session_state.merge_columnaligned_tags = []

                selected_tags = st.multiselect(
                    "Filter by tags",
                    st.session_state.merge_columnaligned_tag_options,
                    key="merge_columnaligned_tags",
                    help="Only merge regions that have one of the selected tags. If empty, all regions are processed."
                )

                only_sort = st.checkbox("Only Sort", value=False, help="Only sort the column-aligned regions without merging them.", key="merge_columnaligned_only_sort")
                dry_run = st.checkbox("Dry run", key="merge_columnaligned_dry_run")

                if st.button("Merge Column-Aligned Regions"):
                    params = {
                        "tolerance": tolerance,
                        "based_on_baselines": based_on_baselines,
                        "convex_hull_method": convex_hull_method,
                        "max_height_distance": max_height_distance,
                        "mid_tolerance": mid_tolerance,
                        "only_sort": only_sort,
                        "tag_filter": selected_tags if selected_tags else None,
                        "dry_run": dry_run,
                        "outputdir": st.session_state.get('modification_dir')
                    }
                    record_operation("merge_columnaligned_regions", **params)
                    with st.spinner("Merging column-aligned regions...", show_time=True):
                         result = bridge.merge_columnaligned_regions(files=selected_files, **params)
                    if result["success"]:
                        st.success(result["output"])
                    else:
                        st.error(result["output"])

            # Split Big Regions
            with st.expander("Split Big Regions"):
                split_min_area = st.number_input(
                    "Minimum Area for Splitting",
                    min_value=0,
                    value=4500000,
                    key="split_min_area"
                )
                scale_min_area = st.number_input(
                    "Scale Area by Max Lines",
                    min_value=0,
                    value=140,
                    key="scale_min_area"
                )
                dry_run = st.checkbox("Dry run", key="split_regions_dry_run")
                if st.button("Split Big Regions"):
                    params = {
                        "split_min_area": split_min_area,
                        "scale_min_area_by_maxlines": scale_min_area,
                        "dry_run": dry_run,
                        "outputdir": st.session_state.get('modification_dir')
                    }
                    record_operation("split_big_regions_vertical", **params)
                    with st.spinner("Splitting large regions...", show_time=True):
                        result = bridge.split_big_regions_vertical(files=selected_files, **params)
                    if result["success"]:
                        st.success(result["output"])
                    else:
                        st.error(result["output"])

            # Merge Overlapping TextRegions
            with st.expander("Merge Overlapping TextRegions"):
                st.write(
                    """Merges overlapping TextRegions based on a minimum overlap percentage."""
                )
                min_overlap_percentage = st.slider(
                    "Minimum Overlap Percentage",
                    min_value=0.0,
                    max_value=100.0,
                    value=50.0,
                    step=1.0,
                    key="merge_overlap_percentage"
                )
                recalculate_convex_hull = st.checkbox(
                    "Recalculate convex hull from textlines",
                    key="merge_recalculate_hull"
                )

                # Tag filtering
                if "merge_overlapping_tag_options" not in st.session_state:
                    st.session_state.merge_overlapping_tag_options = []
                if "merge_overlapping_tags" not in st.session_state:
                    st.session_state.merge_overlapping_tags = []

                if st.button("Update tags", key="merge_overlapping_update_tags_btn"):
                    st.session_state.merge_overlapping_tag_options = sorted(set(tag for tags in [Page(Path(f)).get_tags([TextLevel.TextRegion]) for f in selected_files] for tag in tags))
                    st.session_state.merge_overlapping_tags = []

                selected_tags = st.multiselect(
                    "Filter by tags",
                    st.session_state.merge_overlapping_tag_options,
                    key="merge_overlapping_tags",
                    help="Only merge regions that have one of the selected tags. If empty, all regions are processed."
                )

                dry_run = st.checkbox("Dry run", key="merge_overlap_dry_run")
                if st.button("Merge Overlapping TextRegions"):
                    params = {
                        "min_overlap_percentage": min_overlap_percentage,
                        "recalculate_convex_hull": recalculate_convex_hull,
                        "tag_filter": selected_tags if selected_tags else None,
                        "dry_run": dry_run,
                        "outputdir": st.session_state.get('modification_dir')
                    }
                    record_operation("merge_overlapping_textregions", **params)
                    with st.spinner("Merging overlapping regions...", show_time=True):
                        result = bridge.merge_overlapping_textregions(
                            files=selected_files, **params)
                    if result["success"]:
                        st.success(result["output"])
                    else:
                        st.error(result["output"])

            st.subheader("Sorting Operations")
            # Sort
            with st.expander("Sort (textlines per region)"):
                if st.button("Sort"):
                    params = {"outputdir": st.session_state.get('modification_dir')}
                    record_operation("sort", **params)
                    with st.spinner("Sorting elements...", show_time=True):
                        result = bridge.sort(files=selected_files, **params)
                    if result["success"]:
                        st.success(result["output"])
                    else:
                        st.error(result["output"])

            # Sort and Merge
            with st.expander("Sort (textlines per region) and merge (textlines with same height)"):
                merge_lines_gap_x = st.number_input(
                    "Merge lines gap X",
                    min_value=0,
                    value=64,
                    key="sort_and_merge_gap_x"
                )
                merge_lines_gap_y = st.number_input(
                    "Merge lines gap Y",
                    min_value=0,
                    value=10,
                    key="sort_and_merge_gap_y"
                )
                if st.button("Sort and Merge"):
                    params = {
                        "merge_lines_gap_x": merge_lines_gap_x,
                        "merge_lines_gap_y": merge_lines_gap_y,
                        "outputdir": st.session_state.get('modification_dir')
                    }
                    record_operation("sort_and_merge", **params)
                    with st.spinner("Sorting and merging elements...", show_time=True):
                        result = bridge.sort_and_merge(files=selected_files, **params)
                    if result["success"]:
                        st.success(result["output"])
                    else:
                        st.error(result["output"])

            # Sort Regions
            with st.expander("Sort regions and textlines"):
                st.write(
                    "Sorts text regions based on a simple reading order using overlap analysis.")

                based_on_baselines = st.checkbox(
                    "Use mean baseline centroid",
                    value=False,
                    help="If checked, sorting will be based on the mean centroid of textline baselines instead of the region's geometric centroid.",
                    key="sort_regions_baselines")

                overlap_pct = st.slider(
                    "Overlap Percentage",
                    min_value=0.0,
                    max_value=100.0,
                    value=60.0,
                    step=1.0,
                    help="Threshold in percent for Y- and X-overlap, based on the smaller width/height of the two regions being compared.",
                    key="sort_regions_overlap_pct")

                nested_regions = st.checkbox(
                    "Nested Regions",
                    value=False,
                    help="If checked, the system will identify if a region totally contains another and categorize it as the parent, treating it before its children.",
                    key="sort_regions_nested"
                )

                dry_run = st.checkbox("Dry run", key="sort_regions_dry_run")

                if st.button("Sort Regions"):
                    params = {
                        "based_on_baselines": based_on_baselines,
                        "overlap_pct": overlap_pct,
                        "nested_regions": nested_regions,
                        "dry_run": dry_run,
                        "outputdir": st.session_state.get('modification_dir')
                    }
                    record_operation("sort_regions", **params)
                    with st.spinner("Sorting regions...", show_time=True):
                        result = bridge.sort_regions(files=selected_files, **params)
                    if result["success"]:
                        st.success(result["output"])
                    else:
                        st.error(result["output"])

            # Match Textlines to Region
            with st.expander("Match Textlines to Region"):
                st.write(
                    "Matches textlines to the text region with the highest overlap (>50%) "
                    "and then sorts the textlines in each region."
                )
                slice_spanning = st.checkbox(
                    "Slice textlines spanning multiple regions",
                    value=False,
                    help=(
                        "If enabled, textlines that overlap multiple regions are split into "
                        "separate textlines per region using the polygon intersection. The "
                        "baseline is clipped accordingly. The original text is kept on the "
                        "slice with the largest overlap; other slices are created empty."
                    ),
                    key="match_textlines_slice"
                )
                slice_min_overlap = st.number_input(
                    "Slice min overlap (intersection / line area)",
                    min_value=0.0,
                    max_value=1.0,
                    value=0.1,
                    step=0.05,
                    help=(
                        "Minimum intersection-over-line-area ratio for a region to receive a "
                        "slice of a spanning textline. Only applied when slicing is enabled."
                    ),
                    key="match_textlines_slice_min_overlap",
                    disabled=not slice_spanning
                )
                dry_run = st.checkbox("Dry run", key="match_textlines_dry_run")
                if st.button("Match Textlines to Region"):
                    params = {
                        "outputdir": st.session_state.get('modification_dir'),
                        "slice_spanning": slice_spanning,
                        "slice_min_overlap": slice_min_overlap,
                        "dry_run": dry_run
                    }
                    record_operation("match_textlines_to_region", **params)
                    with st.spinner("Matching textlines to regions...", show_time=True):
                        result = bridge.match_textlines_to_region(files=selected_files, **params)
                    if result["success"]:
                        st.success(result["output"])
                    else:
                        st.error(result["output"])

            # Match Textlines to Smallest Region
            with st.expander("Match Textlines to Smallest Region"):
                st.write(
                    "Matches textlines to the smallest text region that has an overlap greater than the minimum threshold."
                )
                min_overlap = st.number_input(
                    "Minimum Overlap Ratio",
                    min_value=0.0,
                    max_value=1.0,
                    value=0.90,
                    step=0.05,
                    help="Minimum intersection-over-line-area ratio for a region to receive a textline.",
                    key="match_textlines_smallest_min_overlap"
                )
                dry_run = st.checkbox("Dry run", key="match_textlines_smallest_dry_run")
                if st.button("Match Textlines to Smallest Region"):
                    params = {
                        "outputdir": st.session_state.get('modification_dir'),
                        "min_overlap": min_overlap,
                        "dry_run": dry_run
                    }
                    record_operation("match_textlines_to_smallest_region", **params)
                    with st.spinner("Matching textlines to smallest region...", show_time=True):
                        result = bridge.match_textlines_to_smallest_region(files=selected_files, **params)
                    if result["success"]:
                        st.success(result["output"])
                    else:
                        st.error(result["output"])

        with tabs[2]:  # Text-Attributes Operations
            st.subheader("Text-Attributes Operations")

            # Reassign IDs
            with st.expander("Reassign IDs"):
                mode = st.selectbox(
                    "Reading Order Mode",
                    ["auto", "left-to-right", "right-to-left", "top-to-bottom"],
                    key="reassign_ids_mode"
                )
                dry_run = st.checkbox("Dry run", key="reassign_ids_dry_run")
                if st.button("Reassign IDs"):
                    params = {
                        "reading_order_mode": mode,
                        "dry_run": dry_run,
                        "outputdir": st.session_state.get('modification_dir')
                    }
                    record_operation("reassign_ids", **params)
                    with st.spinner("Reassigning IDs...", show_time=True):
                        result = bridge.reassign_ids(files=selected_files, **params)
                    if result["success"]:
                        st.success(result["output"])
                    else:
                        st.error(result["output"])

            # Replace Tags
            with st.expander("Replace Tags"):
                # Initialize session state on first run
                if "replace_tag_options" not in st.session_state:
                    st.session_state.replace_tag_options = []
                if "replace_tag_old" not in st.session_state:
                    st.session_state.replace_tag_old = []
                # Button to update options
                if st.button("Update old tags"):
                    st.session_state.replace_tag_options = sorted(set(tag for tags in [Page(Path(f)).get_tags([TextLevel(
                        level) for level in st.session_state.get("replace_tag_level", [])]) for f in selected_files] for tag in tags))
                    st.session_state.replace_tag_old = []  # Reset selection safely

                # Show the multiselect without using `default=`
                old_tags = st.multiselect(
                    "Old Tag",
                    st.session_state.replace_tag_options,
                    key="replace_tag_old"
                )
                new_tag = st.text_input("New Tag", key="replace_tag_new")
                levels = st.multiselect(
                    "Level",
                    [TextLevel.TextRegion.name, TextLevel.Textline.name, TextLevel.TableRegion.name],
                    default=[TextLevel.TextRegion.name, TextLevel.Textline.name],
                    key="replace_tag_level"
                )
                textfilter = st.text_input(
                    "Text Filter (Regex)",
                    help="Optional regex pattern to match text content. If provided, only elements containing matching text will be processed.",
                    key="replace_tag_textfilter")
                skip_textfilter = st.checkbox(
                    "Skip Matching Text",
                    help="If checked, skip elements matching the text filter. If unchecked, only process elements matching the text filter.",
                    key="replace_tag_skip_textfilter")
                dry_run = st.checkbox("Dry run", key="replace_tag_dry_run")

                if st.button("Replace Tags"):
                    old_tags_list = old_tags if old_tags else [None]
                    for old_tag_item in old_tags_list:
                        params = {
                            "old_tag": old_tag_item,
                            "new_tag": new_tag,
                            "level": [TextLevel[level] for level in levels],
                            "textfilter": textfilter if textfilter else None,
                            "skip_textfilter": skip_textfilter,
                            "dry_run": dry_run,
                            "outputdir": st.session_state.get('modification_dir')
                        }
                        record_operation("replace_tag", **params)
                        with st.spinner(f"Replacing tag '{old_tag_item}' with '{new_tag}'..."):
                            result = bridge.replace_tag(files=selected_files, **params)
                        if result["success"]:
                            st.success(
                                result["output"] +
                                f': {old_tag_item} -> {new_tag}')
                        else:
                            st.error(result["output"])

            # Remove Tags
            with st.expander("Remove Tags"):
                # Initialize session state on first run
                if "remove_tag_options" not in st.session_state:
                    st.session_state.remove_tag_options = []
                if "remove_tag_to_remove" not in st.session_state:
                    st.session_state.remove_tag_to_remove = []

                # Button to update options
                if st.button("Update tags to remove"):
                    st.session_state.remove_tag_options = sorted(set(tag for tags in [Page(Path(f)).get_tags([TextLevel(
                        level) for level in st.session_state.get("remove_tag_level", [])]) for f in selected_files] for tag in tags))
                    st.session_state.remove_tag_to_remove = []  # Reset selection safely

                # Show the multiselect
                tags_to_remove = st.multiselect(
                    "Tags to Remove",
                    st.session_state.remove_tag_options,
                    key="remove_tag_to_remove"
                )
                levels = st.multiselect(
                    "Level",
                    [TextLevel.TextRegion.name, TextLevel.Textline.name, TextLevel.TableRegion.name],
                    default=[TextLevel.TextRegion.name, TextLevel.Textline.name],
                    key="remove_tag_level"
                )
                textfilter = st.text_input(
                    "Text Filter (Regex)",
                    help="Optional regex pattern to match text content. If provided, only elements containing matching text will be processed.",
                    key="remove_tag_textfilter")
                skip_textfilter = st.checkbox(
                    "Skip Matching Text",
                    help="If checked, skip elements matching the text filter. If unchecked, only process elements matching the text filter.",
                    key="remove_tag_skip_textfilter")
                dry_run = st.checkbox("Dry run", key="remove_tag_dry_run")

                if st.button("Remove Tags"):
                    tags_to_remove_list = tags_to_remove if tags_to_remove else [None]
                    for tag_to_remove_item in tags_to_remove_list:
                        params = {
                            "tag_to_remove": tag_to_remove_item,
                            "level": [TextLevel[level] for level in levels],
                            "textfilter": textfilter if textfilter else None,
                            "skip_textfilter": skip_textfilter,
                            "dry_run": dry_run,
                            "outputdir": st.session_state.get('modification_dir')
                        }
                        record_operation("remove_tag", **params)
                        with st.spinner(f"Removing tag '{tag_to_remove_item}'..."):
                            result = bridge.remove_tag(files=selected_files, **params)
                        if result["success"]:
                            st.success(
                                result["output"] +
                                f': Removed elements with tag "{tag_to_remove_item}"')
                        else:
                            st.error(result["output"])

        with tabs[3]:  # Text Operations
            st.subheader("Text-Content Operations")

            # Spellchecking
            with st.expander("Spellchecking"):
                if util.find_spec('spellchecker') is not None:
                    language = st.selectbox(
                        "Language",
                        ["en", "de", "fr"],
                        key="spellcheck_language"
                    )
                    distance = st.number_input(
                        "Distance",
                        min_value=1,
                        max_value=3,
                        value=1,
                        key="spellcheck_distance"
                    )
                    ignore_last = st.checkbox(
                        "Ignore last character",
                        key="spellcheck_ignore_last"
                    )
                    workspace_dict = st.checkbox(
                        "Use workspace dictionary",
                        key="spellcheck_workspace_dict"
                    )
                    if workspace_dict:
                        word_length = st.number_input(
                            "Word length",
                            min_value=1,
                            value=8,
                            key="spellcheck_word_length"
                        )
                        word_freq = st.number_input(
                            "Word frequency",
                            min_value=1,
                            value=50,
                            key="spellcheck_word_freq"
                        )
                    report = st.checkbox(
                        "Generate report", key="spellcheck_report")
                    dry_run = st.checkbox("Dry run", key="spellcheck_dry_run")

                    if st.button("Run Spellchecking"):
                        params = {
                            "language": language,
                            "distance": distance,
                            "ignore_last_character": ignore_last,
                            "workspace_dictionary": workspace_dict,
                            "workspace_word_length": word_length if workspace_dict else 8,
                            "workspace_word_frequency": word_freq if workspace_dict else 50,
                            "report": report,
                            "dry_run": dry_run,
                            "outputdir": st.session_state.get('modification_dir')
                        }
                        record_operation("spellchecking", **params)
                        with st.spinner("Running spellchecking...", show_time=True):
                            result = bridge.spellchecking(files=selected_files, **params)
                        if result["success"]:
                            st.success(result["output"])
                        else:
                            st.error(result["output"])

            # Delete Text
            with st.expander("Delete Text (content only)"):
                levels = st.multiselect(
                    "Level",
                    [TextLevel.TextRegion.name, TextLevel.Textline.name, TextLevel.TableRegion.name],
                    default=[TextLevel.TextRegion.name, TextLevel.TableRegion.name],
                    key="remove_text"
                )
                if st.button("Delete Text (content only)"):
                    params = {
                        "levels": [TextLevel[level] for level in levels],
                        "outputdir": st.session_state.get('modification_dir')
                    }
                    record_operation("delete_text", **params)
                    with st.spinner("Deleting text content...", show_time=True):
                        result = bridge.delete_text(files=selected_files, **params)
                    if result["success"]:
                        st.success(result["output"])
                    else:
                        st.error(result["output"])

        with tabs[4]:
            st.subheader("Repair Operations")

            # Repair
            with st.expander("Repair"):
                dry_run = st.checkbox("Dry run", key="repair_dry_run")
                if st.button("Repair"):
                    params = {
                        "dry_run": dry_run,
                        "outputdir": st.session_state.get('modification_dir')
                    }
                    record_operation("repair", **params)
                    with st.spinner("Repairing files...", show_time=True):
                        result = bridge.repair(files=selected_files, **params)
                    if result["success"]:
                        st.success(result["output"])
                    else:
                        st.error(result["output"])

            # Repair Dummy Regions
            with st.expander("Repair Dummy Regions"):
                st.write("""
                Repairs TextRegions with invalid coordinates by either:
                1. Calculating a new convex hull from textlines if the region has textlines
                2. Deleting the region if it has no textlines
                """)

                dry_run = st.checkbox("Dry run", key="repair_dummy_dry_run")

                if st.button("Repair Dummy Regions"):
                    params = {
                        "dry_run": dry_run,
                        "outputdir": st.session_state.get('modification_dir')
                    }
                    record_operation("repair_dummy_region", **params)
                    with st.spinner("Repairing dummy regions...", show_time=True):
                        result = bridge.repair_dummy_region(files=selected_files, **params)
                    if result["success"]:
                        st.success(result["output"])
                    else:
                        st.error(result["output"])

    with main_tabs[1]:
        st.subheader("Batch Processing")

        batch_text = json.dumps(st.session_state.modification_batch, indent=2)
        st.text_area("Batch Operations", value=batch_text, height=400, key="batch_text_area")

        col1, col2, col3, col4 = st.columns(4)

        with col1:
            if st.button("Load from Text"):
                try:
                    loaded_batch = json.loads(st.session_state.batch_text_area)
                    if isinstance(loaded_batch, list):
                        st.session_state.modification_batch = loaded_batch
                        st.success("Batch loaded successfully from text area.")
                    else:
                        st.error("Invalid format. Batch should be a list of operations.")
                except json.JSONDecodeError:
                    st.error("Invalid JSON format in text area.")

        with col2:
            st.download_button(
                label="Save to File",
                data=json.dumps(st.session_state.modification_batch, indent=2),
                file_name="modification_batch.json",
                mime="application/json"
            )

        with col3:
            if st.button("Run Batch"):
                if not st.session_state.loaded_files:
                    st.warning("Please load files first.")
                else:
                    selected_files = [str(f) for f in st.session_state.loaded_files]
                    progress_bar = st.progress(0)
                    for i, op in enumerate(st.session_state.modification_batch):
                        op_name = op["operation"]
                        op_params = op["parameters"].copy()
                        bridge_method = getattr(bridge, op_name, None)
                        if bridge_method and callable(bridge_method):
                            with st.spinner(f"Running batch operation {i+1}/{len(st.session_state.modification_batch)}: {op_name}"):
                                sig = inspect.signature(bridge_method)
                                op_params["files"] = selected_files
                                if "outputdir" in sig.parameters and ("outputdir" not in op_params or op_params["outputdir"] is None):
                                    op_params["outputdir"] = st.session_state.get('modification_dir')
                                if 'level' in op_params and isinstance(op_params['level'], list):
                                    op_params['level'] = [TextLevel[name] for name in op_params['level']]
                                result = bridge_method(**op_params)
                                if result["success"]:
                                    st.info(f"Step {i+1}: {result['output']}")
                                else:
                                    st.error(f"Step {i+1} failed: {result['output']}")
                                    break
                        progress_bar.progress((i + 1) / len(st.session_state.modification_batch))
                    st.success("Batch processing complete.")

        with col4:
            if st.button("Clear Batch"):
                st.session_state.modification_batch = []
                st.success("Batch cleared.")
                st.rerun()
