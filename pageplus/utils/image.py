import os
import base64
from pathlib import Path
from io import BytesIO
from PIL import Image, ImageDraw
from PIL.Image import Image as ImageType
from shapely.geometry import Polygon
from typing import Tuple, Any


def get_image(image_path):
    """
        Read an image file to a pil object and return the format (image extension)

        :param file_path: Path to the image file
        :return: Base64 encoded string of the image
    """
    # Open the image
    image = Image.open(image_path)

    # Convert to RGBA to ensure transparency support (if needed)
    image = image.convert("RGBA")

    # Extract file extension and determine format
    ext = os.path.splitext(image_path)[1].lower().replace(".", "")
    format_mapping = {"jpg": "JPEG", "jpeg": "JPEG", "png": "PNG", "bmp": "BMP", "gif": "GIF", "tiff": "TIFF",
                      "webp": "WEBP"}
    image_format = format_mapping.get(ext, "PNG")  # Default to PNG if format is unknown
    return image, image_format


def crop_image_by_polygon(image: Image, polygon: Polygon,
                          patch_size: int = 14,
                          buffer: int = 5,
                          transparent_background: bool = True,
                          square_canvas: bool = True,
                          save_snippet: bool = False,
                          snippet_dir: Path = Path('.'),
                          snippet_name: str = '') -> tuple[ImageType | Any, tuple[int, ...]]:
    """
    Crop a PIL image based on a polygon. The polygon is first buffered by the given amount.
    If the buffered polygon's bounding box fits entirely within the image, it is used;
    otherwise, the original polygon is used.

    The image is cropped to the chosen polygon's bounding box, and the polygon's coordinates are adjusted
    relative to the cropped image. Finally, if the resulting snippet is smaller than the minimum size,
    it is centered on a new transparent canvas of the required dimensions.

    :param image: PIL Image to crop.
    :param polygon: Shapely Polygon (or similar) with an `exterior.coords` attribute and `bounds` property.
    :param min_image_size: Minimum size (width, height) for the final snippet.
    :param buffer: Integer value to buffer the polygon.
    :param snippet_name: Optional name for the snippet (used for saving).
    :return: A PIL Image object of the cropped (and possibly expanded) image.
    """
    # Buffer the polygon
    buffered_polygon = polygon.buffer(buffer)

    # Check if the buffered polygon's bounding box fits within the image dimensions
    buf_minx, buf_miny, buf_maxx, buf_maxy = map(int, buffered_polygon.bounds)
    if buf_minx >= 0 and buf_miny >= 0 and buf_maxx <= image.width and buf_maxy <= image.height:
        polygon = buffered_polygon

    # Calculate bounding box from the polygon
    bbox = polygon.bounds
    # Convert to integer values if your image coordinates are integer-based
    bbox = tuple(map(int, bbox))
    # Crop the image to the polygon's bounding box
    cropped_image = image.crop(bbox)

    if transparent_background:
        # Calculate the offset (minx, miny) for adjusting the polygon coordinates
        minx, miny, _, _ = bbox
        adjusted_coords = [(x - minx, y - miny) for x, y in polygon.exterior.coords]

        # Create a mask image with the same size as the cropped image
        mask = Image.new("L", cropped_image.size, 0)
        draw = ImageDraw.Draw(mask)
        draw.polygon(adjusted_coords, outline=255, fill=255)

        # Ensure the cropped image has an alpha channel
        cropped_image = cropped_image.convert("RGBA")

        # Create an output image (snippet) with a transparent background
        snippet = Image.new("RGBA", cropped_image.size, (0, 0, 0, 0))

        # Composite the cropped image using the mask so that only the polygon area is visible
        snippet = Image.composite(cropped_image, snippet, mask)

        # Determine the final canvas size:
        snippet_width, snippet_height = snippet.size
        if square_canvas:
            final_size = max(int(snippet_width+(patch_size*2)), int(snippet_height+patch_size*2))
            final_size += final_size % patch_size
            final_width, final_height = final_size, final_size
        else:
            final_width = int(snippet_width+patch_size)
            final_width += final_width % patch_size
            final_height = int(snippet_height+patch_size)
            final_height += final_height % patch_size

        if (snippet_width, snippet_height) != (final_width, final_height):
            # Create a new transparent image with the final required size
            new_snippet = Image.new("RGBA", (final_width, final_height), (0, 0, 0, 0))

            # Calculate the position to paste the original snippet (center it)
            left = (final_width - snippet_width) // 2
            top = (final_height - snippet_height) // 2

            new_snippet.paste(snippet, (left, top))
            snippet = new_snippet
    else:
        snippet = cropped_image
    if save_snippet:
        snippet_dir.mkdir(parents=True, exist_ok=True)
        snippet.save(snippet_dir.joinpath(f"{snippet_name}.png"), icc_profile=None) # Optional: save the mask to
    return (snippet, bbox)


def image_to_base64(image):
    """
        Convert an image file to a Base64-encoded string.

        :param image: Image object
        :return: Base64 encoded string of the image
    """

    # Convert to bytes and then Base64
    buffered = BytesIO()
    image.save(buffered, format='PNG')
    img_bytes = buffered.getvalue()
    img_base64 = base64.b64encode(img_bytes).decode('utf-8')  # Encode to Base64

    return img_base64