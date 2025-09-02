# SPDX-FileCopyrightText: 2023 James R. Barlow
# SPDX-License-Identifier: MPL-2.0
# Edited: 2025, Jan Kamlah

import re
import io
import tempfile
import os
from importlib import util
from math import pi
from typing import Optional, Tuple

from PIL import Image
from rich import print

from pageplus.models.page import Page
from pageplus.models.text_elements import TextRegion, Textline

if (spec := util.find_spec('pikepdf')) is not None:
    from pikepdf import Matrix, Name
    from pikepdf.canvas import (
        BLUE,
        CYAN,
        MAGENTA,
        Canvas,
        Text,
        TextDirection,
        Color
    )
    from pikepdf import (
        Name,
    )
    from pageplus.utils.pdf.font import GlyphlessFont


def get_image_dpi(image: Image.Image) -> Tuple[int, int]:
    """
    Get the DPI of an image, with fallback to common scan DPI values.
    
    Args:
        image: PIL Image object
        
    Returns:
        Tuple of (x_dpi, y_dpi) - typically both are the same for scanned documents
    """
    # Try to get DPI from image info
    if hasattr(image, 'info') and 'dpi' in image.info:
        dpi_x, dpi_y = image.info['dpi']
        if dpi_x > 0 and dpi_y > 0:
            return int(dpi_x), int(dpi_y)
    
    # Common scan DPI values - try to infer from image size
    # Most document scans are 200, 300, 400, or 600 DPI
    width, height = image.size
    
    # For typical document sizes (A4 = 8.27" x 11.69")
    # Check if dimensions match common DPI values
    common_dpis = [200, 300, 400, 600]
    
    for dpi in common_dpis:
        # A4 dimensions in inches
        a4_width_inches = 8.27
        a4_height_inches = 11.69
        
        expected_width = int(a4_width_inches * dpi)
        expected_height = int(a4_height_inches * dpi)
        
        # Allow some tolerance (±5%)
        tolerance = 0.05
        if (abs(width - expected_width) / expected_width < tolerance and
            abs(height - expected_height) / expected_height < tolerance):
            return dpi, dpi
    
    # Default to 300 DPI if we can't determine
    return 300, 300


def optimize_image_for_pdf(image: Image.Image, target_format: str = 'JPEG', 
                          quality: int = 85, max_resolution: int = None) -> str:
    """
    Optimize image for PDF embedding and save to temporary file.
    
    Args:
        image: PIL Image object
        target_format: Target format ('JPEG' for photos/scans, 'PNG' for graphics)
        quality: JPEG quality (1-100, higher = better quality, larger file)
        max_resolution: Maximum resolution (DPI) to resize to (e.g., 300 for 300 DPI)
        
    Returns:
        Path to temporary optimized image file
    """
    # Resize image if max_resolution is specified
    if max_resolution is not None:
        # Calculate target dimensions based on max_resolution
        # Assuming A4 page size (8.27" x 11.69")
        a4_width_inches = 8.27
        a4_height_inches = 11.69
        
        target_width = int(a4_width_inches * max_resolution)
        target_height = int(a4_height_inches * max_resolution)
        
        # Resize image if it's larger than target
        if image.size[0] > target_width or image.size[1] > target_height:
            # Calculate scaling factor to fit within target dimensions
            scale_x = target_width / image.size[0]
            scale_y = target_height / image.size[1]
            scale = min(scale_x, scale_y)
            
            new_width = int(image.size[0] * scale)
            new_height = int(image.size[1] * scale)
            
            print(f"Resizing image from {image.size} to ({new_width}, {new_height}) "
                  f"for {max_resolution} DPI")
            
            # Use high-quality resizing for downscaling
            image = image.resize((new_width, new_height), Image.Resampling.LANCZOS)
    
    # Convert to RGB if needed (JPEG doesn't support alpha)
    if target_format == 'JPEG' and image.mode in ('RGBA', 'LA', 'P'):
        # Create white background for transparent images
        if image.mode == 'RGBA':
            background = Image.new('RGB', image.size, (255, 255, 255))
            background.paste(image, mask=image.split()[-1])  # Use alpha channel as mask
            image = background
        else:
            image = image.convert('RGB')
    
    # For scanned documents, JPEG is usually more efficient than PNG
    # PNG is better for graphics with sharp edges or limited colors
    if target_format == 'JPEG':
        # Convert to RGB if not already
        if image.mode != 'RGB':
            image = image.convert('RGB')
    
    # Create temporary file with appropriate extension
    suffix = '.jpg' if target_format == 'JPEG' else '.png'
    temp_file = tempfile.NamedTemporaryFile(suffix=suffix, delete=False)
    temp_path = temp_file.name
    temp_file.close()
    
    # Save optimized image to temporary file
    if target_format == 'JPEG':
        image.save(temp_path, 'JPEG', quality=quality, optimize=True)
    else:
        image.save(temp_path, 'PNG', optimize=True)
    
    return temp_path


def page_to_pdf(page: Page,
                image: Image = None,
                fontname: Name = Name("/f-0-0"),
                font: GlyphlessFont = GlyphlessFont(),
                invisible_text: bool = True,
                draw: list = None,
                dpi: int = None,
                substitutions: list = None,
                image_quality: int = 85,
                optimize_compression: bool = True,
                max_resolution: int = None) -> Canvas:

    # Determine actual image DPI (do this once and reuse)
    detected_dpi_x, detected_dpi_y = None, None
    if image is not None:
        detected_dpi_x, detected_dpi_y = get_image_dpi(image)
        print(f"Detected image DPI: {detected_dpi_x}x{detected_dpi_y}")
    
    # Use provided DPI or detected DPI or default
    if dpi is None:
        dpi = detected_dpi_x if detected_dpi_x else 300
        print(f"Using DPI: {dpi} for scaling")
    
    # Calculate proper scaling based on actual DPI
    INCH = 72.0
    SCALING = INCH / dpi
    
    # Optimize image if provided
    temp_image_path = None
    if image is not None and optimize_compression:
        # Determine best format based on image characteristics
        if image.mode in ('RGB', 'RGBA') and image.size[0] * image.size[1] > 1000000:
            # Large color image - use JPEG
            target_format = 'JPEG'
        else:
            # Small image or grayscale - use PNG for better compression
            target_format = 'PNG'
        
        # If no max_resolution specified, use native resolution
        if max_resolution is None:
            max_resolution = detected_dpi_x if detected_dpi_x else 300
            print(f"Using native resolution: {max_resolution} DPI")
        
        temp_image_path = optimize_image_for_pdf(
            image, target_format, quality=image_quality, max_resolution=max_resolution
        )
        print(f"Optimized image saved to: {temp_image_path}")

    def _add_textregion(canvas: Canvas,
                        region: TextRegion):
        if draw and 'region' in draw:
            with canvas.do.save_state():
                # draw box around paragraph
                canvas.do.stroke_color(CYAN).line_width(0.2)
                region_bbx = region.get_coordinates(returntype='mrr').bounds
                canvas.do.rect(int(region_bbx[0]*SCALING),
                               int(region_bbx[1]*SCALING),
                               int((region_bbx[2] - region_bbx[0])*SCALING),
                               int((region_bbx[3] - region_bbx[1])*SCALING),
                               fill=False)
        for line in region.textlines:
            direction = line.get_reading_direction()
            direction = TextDirection(1) if direction is None or direction != 'left-to-right' else TextDirection(2)
            _add_line(canvas,
                      line,
                      direction)

    def _add_line(canvas: Canvas,
        line: Textline | None,
        text_direction: TextDirection = TextDirection(1)):
        """
        Render the textline with optimized font usage
        """
        line_mrr = line.get_coordinates(returntype='mrr')
        line_bbox = [x*SCALING for x in line_mrr.bounds]
        height = abs(line_bbox[3] - line_bbox[1])
        width = abs(line_bbox[2] - line_bbox[0])
        if not line_bbox:
            return

        line_text = line.get_text()
        if substitutions:
            for (pattern, replacement) in substitutions:
                re.sub(rf'{pattern}', rf'{replacement}', line_text)

        if (line_bbox[0], line_bbox[1]) == (line_bbox[2], line_bbox[3]):
            print("line box is invalid so we cannot render it: box=%s text=%s",
                line_bbox,
                line_text)
            return

        if draw and 'line' in draw:
            with canvas.do.save_state():
                canvas.do.stroke_color(BLUE).line_width(0.15).rect(
                    line_bbox[0], line_bbox[1], width, height, fill=False
                )
        if draw and 'baseline' in draw:
            baseline_tuple = line.get_baseline_coordinates(returntype='tuple')
            baseline_points = [int(baseline_tuple[0][0]*SCALING),
                               int(baseline_tuple[0][1]*SCALING),
                               int(baseline_tuple[-1][0]*SCALING),
                               int(baseline_tuple[-1][1]*SCALING)]
            canvas.do.stroke_color(MAGENTA).line_width(0.25).line(*baseline_points)

        angle = 0 #line.angle()
        line_matrix = (
            Matrix()
            .translated(line_bbox[0], line_bbox[3])
            .scaled(1, -1)
            .rotated(angle / pi * 180)
        )
        with canvas.do.save_state(cm=line_matrix):
            text = Text(direction=text_direction)
            fontsize = font.calculate_fontsize(line_text, width)
            text.font(fontname, fontsize)
            text.render_mode(0 if draw is None or not draw else 1)
            text._cs.show_text(line_text.encode("utf-16be"))
            
            if draw is None or not draw or 'word' in draw:
                # Use transparent color for invisible text
                canvas.do.fill_color(Color(1, 1, 1, 0)).draw_text(text)

    # MAIN Function
    # Get page size and create canvas with proper dimensions
    if page is not None:
        width, height = page.page_size()
        canvas = Canvas(page_size=(width * SCALING, height * SCALING))
    else:
        # If no page provided, use A4 size
        width, height = 595, 842  # A4 size in points
        canvas = Canvas(page_size=(width, height))
        SCALING = 1.0  # No scaling needed for A4
    
    # Add font only once to avoid duplication
    canvas.add_font(fontname, font)

    if page is not None:
        page_matrix = (
            Matrix()
            .translated(0, height*SCALING)
            .scaled(1, -1)
        )
    else:
        page_matrix = (
            Matrix()
            .translated(0, height)
            .scaled(1, -1)
        )

    # Draw image in background if debug mode is on
    if image is not None and (draw is not None and draw):
        if temp_image_path and optimize_compression:
            # Use optimized image file
            canvas.do.draw_image(temp_image_path, 0, 0, width=width * SCALING, height=height * SCALING)
        else:
            # Use original image
            canvas.do.draw_image(image, 0, 0, width=width * SCALING, height=height * SCALING)
    
    # Add text content
    if page is not None:
        with canvas.do.save_state(cm=page_matrix):
            for region in page.get_ordered_regions():
                region_tag = region.get_localname()
                if region_tag in ['TextRegion', 'TableRegion']:
                    _add_textregion(canvas, region)
    
    # Draw image in foreground (normal mode)
    if image is not None and (draw is None or not draw):
        if temp_image_path and optimize_compression:
            # Use optimized image file
            canvas.do.draw_image(temp_image_path, 0, 0, width=width * SCALING, height=height * SCALING)
        else:
            # Use original image
            canvas.do.draw_image(image, 0, 0, width=width * SCALING, height=height * SCALING)

    # Clean up temporary file
    if temp_image_path and os.path.exists(temp_image_path):
        try:
            os.unlink(temp_image_path)
        except:
            pass  # Ignore cleanup errors

    return canvas


def create_optimized_pdf(pages_and_images: list, 
                        output_path: str,
                        compress_streams: bool = True,
                        object_stream_mode: str = 'generate',
                        recompress_flate: bool = True) -> None:
    """
    Create an optimized PDF from multiple pages with compression settings.
    
    Args:
        pages_and_images: List of tuples (page, image) or (page, None)
        output_path: Path to save the PDF
        compress_streams: Enable stream compression
        object_stream_mode: Object stream mode for PDF optimization
        recompress_flate: Recompress existing Flate streams
    """
    from pikepdf import Pdf, ObjectStreamMode
    
    pdf_files = []
    
    for page, image in pages_and_images:
        try:
            canvas = page_to_pdf(page, image, optimize_compression=True)
            pdf_files.append(canvas.to_pdf())
        except Exception as e:
            print(f"Error processing page: {e}")
            continue
    
    if not pdf_files:
        raise ValueError("No valid pages to create PDF")
    
    # Create merged PDF with optimization
    merged_pdf = Pdf.new()
    
    # Add all pages
    for pdf_file in pdf_files:
        merged_pdf.pages.extend(pdf_file.pages)
    
    # Save with optimization settings
    merged_pdf.save(
        output_path,
        compress_streams=compress_streams,
        recompress_flate=recompress_flate,
        object_stream_mode=ObjectStreamMode[object_stream_mode.upper()],
        linearize=False,
        normalize_content=False,
        qdf=False
    )
