from importlib import util
from datetime import datetime

import streamlit as st

from pageplus.gui.cli_bridges import ModificationBridge
from pageplus.gui.utils.picker import select_directory
from pageplus.models.page import Page
from pageplus.utils.constants import TextLevel


def show_modification(bridge: ModificationBridge) -> None:
    """Show modification view."""
    if not st.session_state.loaded_files:
        st.warning("Please load files first in the 'Input' page.")
        return

    st.title("🛠️ Modification")

    # Get available files from session state
    selected_files = [str(f) for f in st.session_state.loaded_files]

    # Select output directory
    st.write("Output directory: The default is to overwrite the input files (recommended with backup strategy).")
    if st.button("Select Output Directory"):
        selected_paths = select_directory()
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
    tab_names = ["Format&Metadata Operations",
                 "Text-Layout Operations",
                 "Text-Attributes Operations",
                 "Text-Content Operations",
                 "Repair Operations"]
    tabs = st.tabs(tab_names)

    with tabs[0]:  # Format&Metadata
        st.subheader("Format&Metadata Operations")
        
        # Set PAGE Version
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
                with st.spinner("Updating PAGE XML version...", show_time=True):
                    result = bridge.set_page_version(
                        files=selected_files,
                        version=selected_version,
                        dry_run=dry_run,
                        validate=validate,
                        outputdir=st.session_state.get('modification_dir')
                    )
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

            created_datetime = datetime.combine(created_date, created_time).strftime("%Y-%m-%d %H:%M:%S")
            last_change_datetime = datetime.combine(last_change_date, last_change_time).strftime("%Y-%m-%d %H:%M:%S")

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
                    with st.spinner("Setting metadata...", show_time=True):
                        creator_arg = creator if "Creator" in selected_options else None
                        comments_arg = comments if "Comments" in selected_options else None
                        created_arg = created_datetime if "Created" in selected_options else None
                        last_change_arg = last_change_datetime if "Last Change" in selected_options else None

                        result = bridge.set_metadata(
                            files=selected_files,
                            creator=creator_arg,
                            created=created_arg,
                            last_change=last_change_arg,
                            comments=comments_arg,
                            new=new_metadata,
                            default=default_metadata,
                            dry_run=dry_run_metadata
                        )
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
                level = [TextLevel(level) for level in level]
                with st.spinner("Removing empty elements...", show_time=True):
                    result = bridge.remove_empty(
                        files=selected_files,
                        level=level,
                        dry_run=dry_run,
                        outputdir=st.session_state.get('modification_dir')
                    )
                if result["success"]:
                    st.success(result["output"])
                else:
                    st.error(result["output"])

        # Delete Textlines
        with st.expander("Delete Textlines (with content)"):
            if st.button("Delete Textlines"):
                with st.spinner("Deleting textlines...", show_time=True):
                    result = bridge.delete_textlines(
                        files=selected_files,
                        outputdir=st.session_state.get('modification_dir')
                    )
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
                with st.spinner("Translating lines...", show_time=True):
                    result = bridge.translate_lines(
                        files=selected_files,
                        xoff=xoff,
                        yoff=yoff,
                        dry_run=dry_run,
                        outputdir=st.session_state.get('modification_dir')
                    )
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
                ["all", "x", "y"],
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
                with st.spinner("Extending lines...", show_time=True):
                    result = bridge.extend_lines(
                        files=selected_files,
                        distance=distance,
                        dim=dim,
                        rectangularize=rectangularize,
                        cut_overlaps=cut_overlaps,
                        dry_run=dry_run,
                        outputdir=st.session_state.get('modification_dir')
                    )
                if result["success"]:
                    st.success(result["output"])
                else:
                    st.error(result["output"])

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
                with st.spinner("Rectangularizing coordinates...", show_time=True):
                    result = bridge.rectangularize(
                        files=selected_files,
                        level=[TextLevel(level) for level in levels],
                        dry_run=dry_run,
                        outputdir=st.session_state.get('modification_dir')
                    )
                    if result["success"]:
                        st.success(result["output"])
                    else:
                        st.error(result["output"])


        st.subheader("Recalculate Polygon Operations")
        # Pseudoline Polygon
        with st.expander("Pseudoline Polygon"):
            if st.button("Pseudoline Polygon"):
                with st.spinner("Generating pseudo-line polygons...", show_time=True):
                    result = bridge.pseudolinepolygon(
                        files=selected_files,
                        outputdir=st.session_state.get('modification_dir')
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
                with st.spinner("Fitting elements into parent boundaries...", show_time=True):
                    result = bridge.fit_into_parent(
                        files=selected_files,
                        level=[TextLevel(level) for level in levels],
                        dry_run=dry_run,
                        outputdir=st.session_state.get('modification_dir')
                    )
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
                with st.spinner("Creating top-tier text regions...", show_time=True):
                    result = bridge.top_tier_textregion(
                        files=selected_files,
                        dry_run=dry_run,
                        outputdir=st.session_state.get('modification_dir')
                    )
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

            dry_run = st.checkbox("Dry run", key="merge_columnaligned_dry_run")

            if st.button("Merge Column-Aligned Regions"):
                with st.spinner("Merging column-aligned regions...", show_time=True):
                    result = bridge.merge_columnaligned_regions(
                        files=selected_files,
                        tolerance=tolerance,
                        based_on_baselines=based_on_baselines,
                        convex_hull_method=convex_hull_method,
                        max_height_distance=max_height_distance,
                        mid_tolerance=mid_tolerance,
                        dry_run=dry_run,
                        outputdir=st.session_state.get('modification_dir')
                    )
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
                with st.spinner("Splitting large regions...", show_time=True):
                    result = bridge.split_big_regions_vertical(
                        files=selected_files,
                        split_min_area=split_min_area,
                        scale_min_area_by_maxlines=scale_min_area,
                        dry_run=dry_run,
                        outputdir=st.session_state.get('modification_dir')
                    )
                if result["success"]:
                    st.success(result["output"])
                else:
                    st.error(result["output"])

        st.subheader("Sorting Operations")
        # Sort
        with st.expander("Sort"):
            if st.button("Sort"):
                with st.spinner("Sorting elements...", show_time=True):
                    result = bridge.sort(
                        files=selected_files,
                        outputdir=st.session_state.get('modification_dir')
                    )
                if result["success"]:
                    st.success(result["output"])
                else:
                    st.error(result["output"])

        # Sort and Merge
        with st.expander("Sort and Merge"):
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
                with st.spinner("Sorting and merging elements...", show_time=True):
                    result = bridge.sort_and_merge(
                        files=selected_files,
                        merge_lines_gap_x=merge_lines_gap_x,
                        merge_lines_gap_y=merge_lines_gap_y,
                        outputdir=st.session_state.get('modification_dir')
                    )
                if result["success"]:
                    st.success(result["output"])
                else:
                    st.error(result["output"])

        # Sort Regions
        with st.expander("Sort Regions"):
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

            dry_run = st.checkbox("Dry run", key="sort_regions_dry_run")

            if st.button("Sort Regions"):
                with st.spinner("Sorting regions...", show_time=True):
                    result = bridge.sort_regions(
                        files=selected_files,
                        based_on_baselines=based_on_baselines,
                        overlap_pct=overlap_pct,
                        dry_run=dry_run,
                        outputdir=st.session_state.get('modification_dir')
                    )
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
                with st.spinner("Reassigning IDs...", show_time=True):
                    result = bridge.reassign_ids(
                        files=selected_files,
                        reading_order_mode=mode,
                        dry_run=dry_run,
                        outputdir=st.session_state.get('modification_dir')
                    )
                if result["success"]:
                    st.success(result["output"])
                else:
                    st.error(result["output"])

         # Replace Tags
        with st.expander("Replace Tags"):
            # old_tag = st.text_input("Old Tag", key="replace_tag_old"
            # Initialize session state on first run
            if "replace_tag_options" not in st.session_state:
                st.session_state.replace_tag_options = []
            if "replace_tag_old" not in st.session_state:
                st.session_state.replace_tag_old = []
            # Button to update options
            if st.button("Update old tags"):
                from pathlib import Path
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
                old_tags = old_tags if old_tags else [None]
                with st.spinner("Replacing tags...", show_time=True):
                    for old_tag in old_tags:
                        result = bridge.replace_tag(
                            files=selected_files,
                            old_tag=old_tag,
                            new_tag=new_tag,
                            level=[TextLevel(level) for level in levels],
                            textfilter=textfilter if textfilter else None,
                            skip_textfilter=skip_textfilter,
                            dry_run=dry_run,
                            outputdir=st.session_state.get('modification_dir')
                        )
                        if result["success"]:
                            st.success(
                                result["output"] +
                                f': {old_tag} -> {new_tag}')
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
                from pathlib import Path
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
                tags_to_remove = tags_to_remove if tags_to_remove else [None]
                with st.spinner("Removing tags...", show_time=True):
                    for tag_to_remove in tags_to_remove:
                        result = bridge.remove_tag(
                            files=selected_files,
                            tag_to_remove=tag_to_remove,
                            level=[TextLevel(level) for level in levels],
                            textfilter=textfilter if textfilter else None,
                            skip_textfilter=skip_textfilter,
                            dry_run=dry_run,
                            outputdir=st.session_state.get('modification_dir')
                        )
                        if result["success"]:
                            st.success(
                                result["output"] +
                                f': Removed elements with tag "{tag_to_remove}"')
                        else:
                            st.error(result["output"])

    with tabs[3]:  # Text Operations
        st.subheader("Text-Content Operations")

        # Spellchecking
        with st.expander("Spellchecking"):
            if (spec := util.find_spec('spellchecker')) is None:
                st.error(
                    "Spellchecker is not installed. Please install it with `pip install spellchecker`.")
                from pageplus.cli.modification import install_spellchecker
                if st.button("Install Spellchecking"):
                    result = install_spellchecker()
                    if result["success"]:
                        st.success(result["output"])
                    else:
                        st.error(result["output"])
            else:
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
                    with st.spinner("Running spellchecking...", show_time=True):
                        result = bridge.spellchecking(
                            files=selected_files,
                            language=language,
                            distance=distance,
                            ignore_last_character=ignore_last,
                            workspace_dictionary=workspace_dict,
                            workspace_word_length=word_length if workspace_dict else 8,
                            workspace_word_frequency=word_freq if workspace_dict else 50,
                            report=report,
                            dry_run=dry_run,
                            outputdir=st.session_state.get('modification_dir'))
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
                with st.spinner("Deleting text content...", show_time=True):
                    result = bridge.delete_text(
                        files=selected_files,
                        levels=[TextLevel(level) for level in levels],
                        outputdir=st.session_state.get('modification_dir')
                    )
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
                with st.spinner("Repairing files...", show_time=True):
                    result = bridge.repair(
                        files=selected_files,
                        dry_run=dry_run,
                        outputdir=st.session_state.get('modification_dir')
                    )
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
                with st.spinner("Repairing dummy regions...", show_time=True):
                    result = bridge.repair_dummy_region(
                        files=selected_files,
                        dry_run=dry_run,
                        outputdir=st.session_state.get('modification_dir')
                    )
                if result["success"]:
                    st.success(result["output"])
                else:
                    st.error(result["output"])
