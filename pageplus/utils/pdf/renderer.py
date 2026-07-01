# SPDX-FileCopyrightText: 2023 James R. Barlow
# SPDX-License-Identifier: MPL-2.0
# Edited: 2025, Jan Kamlah
# Improved for performance and file size optimization

import io
import re
from math import pi
from typing import List, Tuple, Optional

from PIL import Image
from rich import print

# Assuming these are your project's internal models
from pageplus.models.page import Page
from pageplus.models.text_elements import TextRegion, Textline

# pikepdf imports
try:
    from pikepdf import Matrix, Name, Pdf, ObjectStreamMode, Dictionary, Stream
    from pikepdf.canvas import (
        BLUE,
        CYAN,
        MAGENTA,
        GREEN,
        # Import the low-level building blocks
        ContentStreamBuilder,
        _CanvasAccessor,
        LoadedImage,
        Text,
        TextDirection,
        Color,
    )
    from pageplus.utils.pdf.font import GlyphlessFont
except ImportError:
    print("[bold red]Error: pikepdf or pageplus is not installed.[/bold red]")
    # Define dummy classes to allow the script to be parsed without pikepdf
    class Canvas: pass
    class GlyphlessFont: pass
    class Page: pass
    class TextRegion: pass
    class Textline: pass
    # etc.

# --- Constants ---
POINTS_PER_INCH = 72.0


def _get_image_dpi(image: Image.Image) -> Tuple[int, int]:
    """
    Get the DPI of an image from its metadata, with a fallback to 300 DPI.
    """
    try:
        if 'dpi' in image.info:
            dpi = image.info['dpi']
            if isinstance(dpi, (tuple, list)) and len(dpi) == 2:
                xdpi = int(dpi[0])
                ydpi = int(dpi[1])
                if xdpi > 75 and ydpi > 75:
                    return xdpi, ydpi
    except Exception:
        pass
    return 300, 300



def _optimize_image(
    image: Image.Image,
    page_width_pt: float,
    page_height_pt: float,
    target_dpi: Optional[int] = 300,
    jpeg_quality: int = 85,
) -> tuple[io.BytesIO, str]:
    """
    Optimize and resize an image for PDF embedding, returning it as an in-memory BytesIO object.

    Args:
        image: The source PIL Image.
        page_width_pt: The width of the target PDF page in points.
        page_height_pt: The height of the target PDF page in points.
        target_dpi: The desired maximum resolution of the image on the page.
        jpeg_quality: The quality setting for JPEG compression (1-95).

    Returns:
        A tuple containing the io.BytesIO buffer and the final image mode ('L' or 'RGB').
    """
    if target_dpi is None:
        image_dpi = _get_image_dpi(image)[0]
        target_dpi = image_dpi

    # 1. Resize image if its resolution is higher than target_dpi on the page
    target_width_px = int(page_width_pt * target_dpi / POINTS_PER_INCH)
    target_height_px = int(page_height_pt * target_dpi / POINTS_PER_INCH)

    if image.width > target_width_px or image.height > target_height_px:
        print(
            f"Image resolution ({image.width}x{image.height}) is higher than target "
            f"({target_width_px}x{target_height_px} for {target_dpi} DPI). Resizing."
        )
        image.thumbnail((target_width_px, target_height_px), Image.Resampling.LANCZOS)

    # 2. Optimize image format and color mode for size
    output_format = 'JPEG'

    # For scanned documents, grayscale is common and saves a lot of space.
    if image.mode == 'L':
        # Already grayscale, perfect for JPEG
        pass
    # Handle transparency by pasting on a white background for JPEG
    elif image.mode in ('RGBA', 'LA'):
        background = Image.new('RGB', image.size, (255, 255, 255))
        background.paste(image, mask=image.split()[-1])
        image = background
    # Convert palette images or others to RGB
    elif image.mode != 'RGB':
        image = image.convert('RGB')

    # For bi-tonal (black and white) scans, CCITTFaxDecode would be even better,
    # but that requires more complex handling. JPEG on a 'L' mode image is a great compromise.

    # 3. Save to an in-memory buffer
    buffer = io.BytesIO()
    image.save(
        buffer,
        format=output_format,
        quality=jpeg_quality,
        dpi=(POINTS_PER_INCH, POINTS_PER_INCH),  # Embed standard PDF DPI
        optimize=True,
    )
    buffer.seek(0)
    return buffer, image.mode


def _add_page_to_pdf(
    cs_accessor: _CanvasAccessor,
    pdf: Pdf,
    page: Pdf.pages,
    page_obj: Page,
    image: Optional[Image.Image] = None,
    fontname: Name = Name("/f-0-0"),
    font: GlyphlessFont = GlyphlessFont(),
    invisible_text: bool = True,
    draw: Optional[List[str]] = None,
    target_dpi: Optional[int] = 300,
    jpeg_quality: int = 85,
    substitutions: Optional[List[Tuple[str, str]]] = None,
    line_thickness: float = 1.5,
) -> None:
    """
    Constructs a single PDF page on the given canvas with an image and text overlays.
    """
    if draw is None:
        draw = []

    # Get page size in pixels from the Page object
    page_width_px, page_height_px = page_obj.page_size()

    # Use image DPI to calculate scaling from pixels to PDF points
    # This ensures the text overlay matches the image content's scale.
    # If no image, assume a common scan DPI for scaling.
    image_dpi = _get_image_dpi(image)[0] if image is not None else 300
    SCALING = POINTS_PER_INCH / image_dpi

    page_width_pt = page_width_px * SCALING
    page_height_pt = page_height_px * SCALING

    # Add background image
    if image is not None:
        optimized_image_buffer, final_mode = _optimize_image(
            image, page_width_pt, page_height_pt, target_dpi, jpeg_quality
        )
        # Manually create an Image XObject Stream. This is the correct low-level
        # way to embed a pre-compressed image without re-compression.
        image_xobject = Stream(pdf, optimized_image_buffer.read())
        image_xobject.Type = Name.XObject
        image_xobject.Subtype = Name.Image
        image_xobject.Width = image.width
        image_xobject.Height = image.height
        if final_mode == 'L':
            image_xobject.ColorSpace = Name.DeviceGray
        else:
            image_xobject.ColorSpace = Name.DeviceRGB
        image_xobject.BitsPerComponent = 8
        image_xobject.Filter = Name.DCTDecode

        image_name = Name(f"/Im{len(page.Resources.XObject) + 1}")
        page.Resources.XObject[image_name] = image_xobject

        # The image is drawn to fill the entire page.
        with cs_accessor.save_state(cm=Matrix(page_width_pt, 0, 0, page_height_pt, 0, 0)):
            cs_accessor._cs.draw_xobject(image_name)

    # Add text content
    # Transformation matrix to flip the Y-axis (PDF origin is bottom-left)
    page_matrix = Matrix().translated(0, page_height_pt).scaled(1, -1)

    with cs_accessor.save_state(cm=page_matrix):
        for region in page_obj.get_ordered_regions():
            if region.get_localname() in ['TextRegion', 'TableRegion']:
                _draw_text_region(cs_accessor, region, SCALING, font, fontname, invisible_text, draw, substitutions, line_thickness)


def _draw_text_region(cs_accessor: _CanvasAccessor, region: TextRegion, scaling: float, font, fontname, invisible_text, draw, substitutions, line_thickness: float = 1.5):
    """Helper to draw a single text region."""
    draw_lower = [d.lower() for d in draw] if draw else []
    if 'textregion' in draw_lower or 'region' in draw_lower:
        with cs_accessor.save_state():
            cs_accessor.stroke_color(GREEN).line_width(line_thickness * 1.33)
            bbx = region.get_coordinates(returntype='mrr').bounds
            cs_accessor.rect(
                bbx[0] * scaling, bbx[1] * scaling,
                (bbx[2] - bbx[0]) * scaling, (bbx[3] - bbx[1]) * scaling,
                fill=False
            )
    for line in region.textlines:
        _draw_text_line(cs_accessor, line, scaling, font, fontname, invisible_text, draw, substitutions, line_thickness)


def _draw_text_line(cs_accessor: _CanvasAccessor, line, scaling, font, fontname, invisible_text, draw, substitutions, line_thickness: float = 1.5):
    """Helper to draw a single text line."""
    line_mrr = line.get_coordinates(returntype='mrr')
    if not line_mrr or not line_mrr.bounds:
        return

    line_bbox_pt = [coord * scaling for coord in line_mrr.bounds]
    height_pt = abs(line_bbox_pt[3] - line_bbox_pt[1])
    width_pt = abs(line_bbox_pt[2] - line_bbox_pt[0])

    draw_lower = [d.lower() for d in draw] if draw else []

    # Draw the Textline bounding box
    if 'textline' in draw_lower or 'line' in draw_lower:
        with cs_accessor.save_state():
            cs_accessor.stroke_color(BLUE).line_width(line_thickness).rect(
                line_bbox_pt[0], line_bbox_pt[1], width_pt, height_pt, fill=False
            )

    # Draw the Baseline if coordinates are available
    if 'baseline' in draw_lower:
        baseline_tuple = line.get_baseline_coordinates(returntype='tuple')
        if baseline_tuple and len(baseline_tuple) > 0:
            baseline_points = [int(baseline_tuple[0][0]*scaling),
                               int(baseline_tuple[0][1]*scaling),
                               int(baseline_tuple[-1][0]*scaling),
                               int(baseline_tuple[-1][1]*scaling)]
            with cs_accessor.save_state():
                cs_accessor.stroke_color(BLUE).line_width(line_thickness).line(
                    baseline_points[0], baseline_points[1], baseline_points[2], baseline_points[3]
                )

    line_text = line.get_text()
    if substitutions:
        for pattern, replacement in substitutions:
            line_text = re.sub(pattern, replacement, line_text)

    if not line_text or not line_text.strip():
        return

    # Set text rendering mode: 3 for invisible, 0 for fill.
    render_mode = 3 if invisible_text and 'line' not in draw_lower and 'textline' not in draw_lower else 0

    # Re-instating the correct matrix calculation from the previous implementation.
    angle = 0  # line.angle() is not implemented
    line_matrix = (
        Matrix()
        .translated(line_bbox_pt[0], line_bbox_pt[3])  # Translate to top-left
        .scaled(1, -1)  # Flip y-axis for drawing
        .rotated(angle / 180 * pi)
    )

    with cs_accessor.save_state(cm=line_matrix):
        text = Text()
        fontsize = font.calculate_fontsize(line_text, width_pt)
        text.font(fontname, fontsize)
        text.render_mode(render_mode)
        text.show(line_text)
        cs_accessor.draw_text(text)


def create_pdf(
    pages_and_images: List[Tuple[Page, Optional[Image.Image]]],
    output_path: str,
    font: Optional[GlyphlessFont] = None,
    invisible_text: bool = True,
    draw: Optional[List[str]] = None,
    target_dpi: Optional[int] = 300,
    jpeg_quality: int = 85,
    substitutions: Optional[List[Tuple[str, str]]] = None,
    line_thickness: float = 1.5,
) -> None:
    """
    Creates an optimized, multi-page PDF from Page objects and images.

    Args:
        pages_and_images: A list of tuples, where each tuple is a (Page, PIL.Image) pair.
        output_path: The path to save the final PDF file.
        font: The font to use for text rendering (defaults to a new GlyphlessFont).
        invisible_text: If True, text is invisible but selectable.
        draw: A list of elements to draw for debugging ('region', 'line').
        target_dpi: The maximum resolution for images in the PDF. Lower values reduce file size.
        jpeg_quality: The JPEG quality for embedded images (1-95).
        substitutions: Regex substitutions to apply to text content.
    """
    if not pages_and_images:
        raise ValueError("Input list 'pages_and_images' cannot be empty.")

    # Use a default glyphless font if none is provided
    active_font = font if font is not None else GlyphlessFont()
    fontname = Name("/Gf0")

    # 1. Create the main PDF object
    pdf = Pdf.new()

    # 2. Loop through pages, creating and adding them one by one
    for i, (page_obj, image) in enumerate(pages_and_images):
        print(f"Processing page {i + 1}/{len(pages_and_images)}...")
        try:
            # Determine page size in points
            page_width_px, page_height_px = page_obj.page_size()
            image_dpi = _get_image_dpi(image)[0] if image is not None else 300
            scaling = POINTS_PER_INCH / image_dpi
            page_size = (page_width_px * scaling, page_height_px * scaling)

            # Add a blank page to the PDF
            new_page = pdf.add_blank_page(page_size=page_size)
            new_page.Resources = Dictionary(Font={}, XObject={})

            # --- Manually create a canvas-like environment ---
            cs_builder = ContentStreamBuilder()
            accessor = _CanvasAccessor(cs_builder)
            accessor.push()  # Manually initialize the graphics state

            # Add font to the page's resources
            new_page.Resources.Font[fontname] = active_font.register(pdf)

            # Use the drawing function to add content
            _add_page_to_pdf(
                cs_accessor=accessor,
                pdf=pdf,
                page=new_page,
                page_obj=page_obj,
                image=image,
                fontname=fontname,
                font=active_font,
                invisible_text=invisible_text,
                draw=draw,
                target_dpi=target_dpi,
                jpeg_quality=jpeg_quality,
                substitutions=substitutions,
                line_thickness=line_thickness,
            )

            # Finalize the page content
            new_page.Contents = pdf.make_stream(cs_builder.build())

        except Exception as e:
            print(f"[bold red]Error processing page {i + 1}: {e}[/bold red]")
            # Optionally, you could add a blank page here to keep page numbering consistent
            # pdf.add_blank_page()
            continue

    # 3. Save the final PDF with optimization settings
    print(f"Saving optimized PDF to {output_path}...")
    pdf.save(
        output_path,
        compress_streams=True,
        recompress_flate=True,
        object_stream_mode=ObjectStreamMode.generate,
        linearize=False,  # Linearization is for web view, not smallest size
    )
    print("[bold green]PDF creation complete.[/bold green]")
