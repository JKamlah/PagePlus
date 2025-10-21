import streamlit as st
from pathlib import Path
from PIL import Image, ImageFile
import pandas as pd
import numpy as np
from skimage.draw import polygon as sk_polygon, line as sk_line
from skimage.morphology import disk, binary_dilation

from pageplus.models.page import Page
from pageplus.utils.fs import find_image
from pageplus.gui.utils.picker import pick_directory, pick_files

ImageFile.LOAD_TRUNCATED_IMAGES = True


def center_dialog():
    st.markdown(
        """
        <style>
            div[data-testid="stDialog"] > div:first-child {
                position: fixed;
                top: 50%;
                left: 50%;
                transform: translate(-50%, -50%);
            }
        </style>
        """,
        unsafe_allow_html=True,
    )


def load_page_and_image(xml_path: Path, image_path: Path):
    """Loads and caches the Page and Image objects from file paths."""
    page = Page(xml_path)
    image = load_images(image_path)
    return page, image


@st.cache_resource
def load_images(image_path: Path):
    """Loads and caches the Image object from file path."""
    image = Image.open(image_path)
    image.load()  # Eagerly load image data
    return image


@st.dialog("Line Details", width="large")
def line_detail_dialog(all_lines: list, image: Image.Image, start_index: int, page: Page, xml_path: Path):
    """A dialog to show line details, allow editing and navigation."""
    center_dialog()
    page = st.session_state.page if 'page' in st.session_state and st.session_state.page else page
    if 'lines' not in st.session_state or st.session_state.lines is None:
        st.session_state.lines = all_lines
    all_lines = st.session_state.lines

    if 'current_line_index' not in st.session_state or st.session_state.get('start_index') != start_index:
        st.session_state.current_line_index = start_index
        st.session_state.start_index = start_index

    idx = st.session_state.current_line_index
    line = all_lines[idx]

    st.header(f"Line: {line.get_id()}")

    # Create a mapping from line ID to index for quick lookups
    line_id_to_idx = {l.get_id(): i for i, l in enumerate(all_lines)}
    line_ids = list(line_id_to_idx.keys())

    # Dropdown to jump to a specific line
    selected_line_id = st.selectbox(
        "Jump to Line",
        options=line_ids,
        index=idx,
        format_func=lambda line_id: f"({line_id_to_idx[line_id] + 1}/{len(all_lines)}) {line_id}",
        key=f"line_jumper_{idx}"
    )

    # If the selection changed, update the index in session state and rerun
    selected_idx = line_id_to_idx[selected_line_id]
    if selected_idx != st.session_state.current_line_index:
        st.session_state.current_line_index = selected_idx
        st.rerun()

    # Image cutout
    polygon = line.get_coordinates(returntype="array")
    if polygon is not None and len(polygon) > 0:
        with st.spinner("Cutting out line image..."):
            img_rgba = image.convert('RGBA') if image.mode != 'RGBA' else image.copy()
            img_array = np.array(img_rgba)

            # Get polygon bounding box to expand it later
            x_coords = polygon[:, 0]
            y_coords = polygon[:, 1]
            x, y, w, h = min(x_coords), min(y_coords), max(x_coords) - min(x_coords), max(y_coords) - min(y_coords)

            # Expand bounding box
            padding = 20
            left = max(0, x - padding)
            top = max(0, y - padding)
            right = min(img_array.shape[1], x + w + padding)
            bottom = min(img_array.shape[0], y + h + padding)

            # Crop image to expanded bounding box
            cropped_array = img_array[top:bottom, left:right]

            # Create semi-transparent overlay
            overlay = np.zeros_like(cropped_array)
            overlay[:, :] = (0, 0, 0, 128)

            # Translate polygon coordinates to cropped image space
            translated_polygon = polygon - np.array([left, top])

            # Create a mask for the polygon area
            rr, cc = sk_polygon(translated_polygon[:, 1], translated_polygon[:, 0], shape=overlay.shape)

            # Set the masked area to be fully transparent
            overlay[rr, cc] = (0, 0, 0, 0)

            # Alpha blending
            overlay_alpha = overlay[..., 3] / 255.0
            background_alpha = 1.0 - overlay_alpha

            blended_array = (cropped_array[..., :3] * background_alpha[..., np.newaxis] +
                             overlay[..., :3] * overlay_alpha[..., np.newaxis]).astype(np.uint8)

            display_image = Image.fromarray(blended_array)
            st.image(display_image)
    else:
        st.warning("No coordinates found for this line.")

    # Editing
    new_text = st.text_input("Text Content", line.get_text(), key=f"text_{line.get_id()}_{idx}")
    new_tag = st.text_input("Tag", line.get_tag(), key=f"tag_{line.get_id()}_{idx}")

    # Buttons
    b_col1, b_col2, b_col3, b_col4 = st.columns(4)

    def auto_save():
        if line.get_text() != new_text:
            line.update_text(new_text)
        if line.get_tag() != new_tag:
            line.set_tag(new_tag)
        st.session_state.lines[idx] = line
        st.session_state.page = page

    if b_col1.button("⬅️ Previous", disabled=idx <= 0):
        auto_save()
        st.session_state.current_line_index -= 1
        st.rerun()

    if b_col2.button("Next ➡️", disabled=idx >= len(all_lines) - 1):
        auto_save()
        st.session_state.current_line_index += 1
        st.rerun()

    if b_col3.button("Delete Line"):
        page.delete_element(line.xml_element)
        st.session_state.lines.pop(idx)
        st.session_state.page = page
        st.rerun()

    if b_col4.button("Save & Close"):
        auto_save()
        st.session_state.page.save_xml(xml_path)
        st.session_state.lines = None
        st.session_state.page = None
        st.session_state.line_editor['selection']['rows'] = []
        if 'current_line_index' in st.session_state:
            del st.session_state.current_line_index
        if 'start_index' in st.session_state:
            del st.session_state.start_index
        st.rerun()


def draw_overlays(image: Image.Image, page: Page, show_regions: bool, show_lines: bool, show_baselines: bool) -> Image.Image:
    """Draws overlays on the image using NumPy and scikit-image for performance."""
    if not any([show_regions, show_lines, show_baselines]):
        return image

    # Convert PIL image to NumPy array for drawing
    base_array = np.array(image.convert('RGBA'))
    h, w, _ = base_array.shape

    # Create a transparent overlay layer for fills and a set of masks for outlines
    overlay = np.zeros_like(base_array)
    region_outline_mask = np.zeros((h, w), dtype=bool)
    line_outline_mask = np.zeros((h, w), dtype=bool)
    baseline_mask = np.zeros((h, w), dtype=bool)

    # --- Colors (RGBA) ---
    region_fill = np.array([0, 255, 0, 64], dtype=np.uint8)
    line_fill = np.array([0, 0, 255, 64], dtype=np.uint8)
    baseline_color = np.array([128, 0, 128, 255], dtype=np.uint8)
    region_outline_color = np.array([0, 255, 0, 255], dtype=np.uint8)
    line_outline_color = np.array([0, 0, 255, 255], dtype=np.uint8)

    # --- Step 1: Draw fills and populate outline masks in a single pass ---
    for region in page.regions.textregions:
        if show_regions:
            coords = region.get_coordinates(returntype="array")
            if coords is not None and len(coords) > 2:
                rr, cc = sk_polygon(coords[:, 1], coords[:, 0], shape=base_array.shape)
                overlay[rr, cc] = region_fill

                # Populate outline mask
                coords_closed = np.vstack([coords, coords[0]])
                for i in range(len(coords_closed) - 1):
                    rr_line, cc_line = sk_line(coords_closed[i, 1], coords_closed[i, 0], coords_closed[i+1, 1], coords_closed[i+1, 0])
                    region_outline_mask[rr_line, cc_line] = True

        for line in region.textlines:
            if show_lines:
                line_coords = line.get_coordinates(returntype="array")
                if line_coords is not None and len(line_coords) > 2:
                    rr, cc = sk_polygon(line_coords[:, 1], line_coords[:, 0], shape=base_array.shape)
                    overlay[rr, cc] = line_fill

                    coords_closed = np.vstack([line_coords, line_coords[0]])
                    for i in range(len(coords_closed) - 1):
                        rr_line, cc_line = sk_line(coords_closed[i, 1], coords_closed[i, 0], coords_closed[i+1, 1], coords_closed[i+1, 0])
                        line_outline_mask[rr_line, cc_line] = True

            if show_baselines:
                baseline_coords = line.get_baseline_coordinates(returntype="array")
                if baseline_coords is not None and len(baseline_coords) > 1:
                    for i in range(len(baseline_coords) - 1):
                        rr_line, cc_line = sk_line(baseline_coords[i, 1], baseline_coords[i, 0], baseline_coords[i+1, 1], baseline_coords[i+1, 0])
                        baseline_mask[rr_line, cc_line] = True

    # --- Step 2: Dilate masks and apply outlines to the overlay ---
    if show_regions:
        overlay[binary_dilation(region_outline_mask, disk(1))] = region_outline_color

    if show_lines:
        overlay[line_outline_mask] = line_outline_color  # 1px thickness, no dilation needed

    if show_baselines:
        overlay[binary_dilation(baseline_mask, disk(1))] = baseline_color

    # --- Step 3: Alpha blend and return ---
    overlay_alpha = overlay[..., 3] / 255.0
    background_alpha = 1.0 - overlay_alpha

    blended_array = (base_array[..., :3] * background_alpha[..., np.newaxis] +
                     overlay[..., :3] * overlay_alpha[..., np.newaxis]).astype(np.uint8)

    return Image.fromarray(blended_array)


def get_loaded_workspace_dir() -> Path:
    """Get the path of the loaded workspace directory."""
    loaded_workspace = st.session_state.get("loaded_workspace")
    if loaded_workspace:
        return Path(loaded_workspace)
    return Path.cwd()


def _show_page_statistics(page: Page, image_path: Path):
    """Display statistics about the current page."""
    # Count regions and lines
    num_regions = len(page.regions.textregions)
    num_lines = sum(len(region.textlines) for region in page.regions.textregions)

    # Count total characters
    total_chars = 0
    total_words = 0
    for region in page.regions.textregions:
        for line in region.textlines:
            text = line.get_text()
            if text:
                total_chars += len(text)
                total_words += len(text.split())

    # Get image dimensions
    try:
        img = Image.open(image_path)
        img_width, img_height = img.size
        img_size_mb = image_path.stat().st_size / (1024 * 1024)
    except Exception:
        img_width = img_height = 0
        img_size_mb = 0

    # Display statistics in columns
    with st.expander("📊 Statistics", expanded=False):
        col1, col2, col3, col4, col5 = st.columns(5)
        with col1:
            st.metric("📄 Regions", num_regions)
        with col2:
            st.metric("📝 Lines", num_lines)
        with col3:
            st.metric("📊 Words", total_words)
        with col4:
            st.metric("📐 Image Size", f"{img_width}×{img_height}")
        with col5:
            st.metric("💾 File Size", f"{img_size_mb:.2f} MB")


def show_viewer():
    """Display the viewer page."""
    st.title("🖼️ Page XML Viewer")

    if 'overlay_cache' not in st.session_state:
        st.session_state.overlay_cache = {}

    loaded_files = st.session_state.get('loaded_files', [])

    if not loaded_files:
        st.info("📭 No PAGE XML files loaded. Please load files in the 'Load Files' page first.")
        return

    xml_files = [f for f in loaded_files if f.suffix == ".xml"]
    if not xml_files:
        st.warning("⚠️ No XML files found in loaded files. Please load PAGE XML files.")
        return

    # Create a mapping from filename to full path for the selectbox
    total_files = len(xml_files)
    xml_display_options = [f"({i+1}/{total_files}) {file.name}" for i, file in enumerate(xml_files)]
    xml_file_map = {f"({i+1}/{total_files}) {file.name}": file for i, file in enumerate(xml_files)}

    # --- State management for selected file ---
    if 'viewer_selected_xml' not in st.session_state or st.session_state.viewer_selected_xml not in xml_display_options:
        st.session_state.viewer_selected_xml = None

    # Find the index of the currently selected file
    current_file_index = None
    if st.session_state.viewer_selected_xml:
        try:
            current_file_index = xml_display_options.index(st.session_state.viewer_selected_xml)
        except ValueError:
            current_file_index = None
            st.session_state.viewer_selected_xml = None

    # File navigation at the top
    col1, col2, col3 = st.columns([1, 4, 1])

    with col1:
        if st.button("⬅️ Previous", disabled=current_file_index is None or current_file_index <= 0, use_container_width=True):
            st.session_state.viewer_selected_xml = xml_display_options[current_file_index - 1]
            st.rerun()

    with col2:
        selected_xml_filename = st.selectbox(
            "Select a PAGE XML file to view",
            options=xml_display_options,
            index=current_file_index,
            placeholder="Select a file to view...",
            key="viewer_file_selector",
            label_visibility="collapsed"
        )
        # Update state if selectbox changes
        st.session_state.viewer_selected_xml = selected_xml_filename

    with col3:
        if st.button("Next ➡️", disabled=current_file_index is None or current_file_index >= len(xml_display_options) - 1, use_container_width=True):
            st.session_state.viewer_selected_xml = xml_display_options[current_file_index + 1]
            st.rerun()

    st.divider()

    # Image source configuration in expander
    with st.expander("⚙️ Image Source Configuration", expanded=False):
        image_source_option = st.radio(
            "Select how to find the image for the PAGE XML",
            ("Default (same folder as XML)", "Select Directory", "Select File"),
            key="viewer_image_source",
            horizontal=True
        )

        match_by_extension_cb = st.checkbox(
            "Match by filename and image extension (ignores filename in PAGE XML)",
            key="viewer_match_by_extension"
        )
        if match_by_extension_cb:
            image_extensions = [".jpg", ".jpeg", ".png", ".tif", ".tiff"]
            st.selectbox(
                label="Select image extension",
                options=image_extensions,
                key="viewer_image_extension_select"
            )

        if image_source_option == "Select Directory":
            if st.button("📁 Select Image Directory", use_container_width=True):
                selected_dir = pick_directory(initial_dir=str(Path(xml_files[0]).parent) if xml_files else None)
                if selected_dir:
                    st.session_state.viewer_image_folder = selected_dir
                    if 'viewer_image_path' in st.session_state:
                        del st.session_state.viewer_image_path
            if 'viewer_image_folder' in st.session_state:
                st.text_input("Selected Directory", st.session_state.viewer_image_folder, disabled=True)

        elif image_source_option == "Select File":
            if st.button("📄 Select Image File", use_container_width=True):
                selected_files = pick_files(
                    initial_dir=str(Path(xml_files[0]).parent) if xml_files else None,
                    filetypes=[("Image files", "*.jpg *.jpeg *.png *.tif *.tiff"), ("All files", "*.*")]
                )
                if selected_files:
                    st.session_state.viewer_image_path = selected_files[0]
                    if 'viewer_image_folder' in st.session_state:
                        del st.session_state.viewer_image_folder
            if 'viewer_image_path' in st.session_state:
                st.text_input("Selected File", st.session_state.viewer_image_path, disabled=True)

    if selected_xml_filename:
        with st.spinner("Processing image...", show_time=True):
            selected_xml_path = xml_file_map[selected_xml_filename]

            try:
                # --- Image Path Resolution ---
                if (image_source_option == "Select File" and 'viewer_image_path' not in st.session_state) or \
                   (image_source_option == "Select Directory" and 'viewer_image_folder' not in st.session_state):
                    st.warning("Please select an image source above to continue.")
                    st.stop()

                # 1. Determine the image filename to look for.
                if st.session_state.get("viewer_match_by_extension"):
                    image_filename = selected_xml_path.with_suffix(st.session_state.get("viewer_image_extension_select", ".jpg")).name
                else:
                    # This requires loading the page, which is inefficient but necessary for the default behavior.
                    temp_page = Page(selected_xml_path)
                    image_filename = temp_page.imageFilename()
                    del temp_page

                # 2. Determine the path or folder to search and find the image.
                image_path = None
                if image_source_option == "Select File" and 'viewer_image_path' in st.session_state:
                    selected_image_path = Path(st.session_state.viewer_image_path)
                    if selected_image_path.name == image_filename:
                        image_path = selected_image_path
                    else:
                        st.warning(f"The selected image file name '{selected_image_path.name}' does not match the expected name '{image_filename}' -> use file directory.")
                        image_path = find_image(image_filename, selected_image_path.parent)

                elif image_source_option == "Select Directory" and 'viewer_image_folder' in st.session_state:
                    image_folder = Path(st.session_state.viewer_image_folder)
                    image_path = find_image(image_filename, image_folder)

                else:  # Default case
                    image_folder = selected_xml_path.parent
                    image_path = find_image(image_filename, image_folder)

                if image_path and image_path.exists():
                    # Step 1: Load data from the resource cache
                    page, image = load_page_and_image(selected_xml_path, image_path)

                    # Display statistics
                    _show_page_statistics(page, image_path)

                    # Display and overlay options
                    with st.expander("🎨 Overlays", expanded=False):
                        show_regions = st.checkbox("Text Regions", key="show_regions")
                        show_lines = st.checkbox("Text Lines", value=True, key="show_lines")
                        show_baselines = st.checkbox("Baselines", key="show_baselines")

                    c1, c2 = st.columns([1, 4])
                    with c1:
                        if st.button("🔄 Reload View"):
                            if 'overlay_cache' in st.session_state:
                                del st.session_state.overlay_cache
                            load_images.clear()
                            st.rerun()
                    with c2:
                        show_fulltext = st.checkbox("📝 Show Fulltext Panel", value=True, key="show_fulltext")

                    # Step 2: Use dynamic session cache for drawn overlays
                    cache_key = (selected_xml_path, image_path, show_regions, show_lines, show_baselines)
                    if cache_key not in st.session_state.overlay_cache:
                        st.session_state.overlay_cache[cache_key] = draw_overlays(image.copy(), page, show_regions, show_lines, show_baselines)

                    display_image = st.session_state.overlay_cache[cache_key]

                    # Main display area
                    if show_fulltext:
                        img_col, text_col = st.columns([2, 1])
                        with img_col:
                            st.image(display_image, width='stretch')
                        with text_col:
                            st.subheader("📝 Fulltext")

                            all_lines = []
                            for region in page.regions.textregions:
                                all_lines.extend(region.textlines)

                            if all_lines:
                                # Show line count
                                st.caption(f"Total lines: {len(all_lines)}")

                                df_data = {
                                    "ID": [line.get_id() for line in all_lines],
                                    "Tag": [line.get_tag() for line in all_lines],
                                    "Text Content": [line.get_text() for line in all_lines],
                                }
                                df = pd.DataFrame(df_data)

                                st.dataframe(
                                    df,
                                    key="line_editor",
                                    on_select="rerun",
                                    selection_mode="single-row",
                                    hide_index=True,
                                    height=600
                                )

                                if "line_editor" in st.session_state and st.session_state.line_editor['selection']['rows']:
                                    selected_index = st.session_state.line_editor['selection']['rows'][0]
                                    line_detail_dialog(all_lines, image, selected_index, page, selected_xml_path)
                                    page = Page(selected_xml_path)
                            else:
                                st.info("No text content found.")

                    else:
                        st.image(display_image, width='stretch')

                else:
                    st.error(f"Could not find the image '{image_filename}'.")

            except Exception as e:
                st.error(f"An error occurred while processing '{selected_xml_filename}': {e}")
    else:
        st.info("Select a PAGE XML file from the dropdown to start viewing.")
