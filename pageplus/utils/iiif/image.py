import gc
import os
import re
import time
from pathlib import Path
from typing import Any, Dict, Optional

from PIL import Image as PILgrimage

from pageplus.utils.iiif.utils import async_request, get_size, sanitize_url, write_chunks
from pageplus.utils.logger import logging

logger = logging.getLogger(__name__)

MIMETYPE_TO_EXTENSION = {
    "image/jpeg": ".jpg",
    "image/png": ".png",
    "image/tiff": ".tif",
    "image/jp2": ".jp2",
}


class IIIFImage:
    """Represents a single IIIF image with its properties and download capabilities."""

    def __init__(
        self,
        idx: int,
        img_id: str,
        resource: Dict[str, Any],
        save_dir: Path,
        prefix: str = "",
        leading_zeros: int = 4,
        max_dim: Optional[int] = None,
        min_dim: Optional[int] = None,
        filename_strategy: str = "label",
        keep_original_size: bool = True,
    ):
        self.idx = idx
        self.url = sanitize_url(img_id.replace("full/full/0/default.jpg", ""))

        self.resource = resource

        mimetype = self.resource.get("format")
        extension = MIMETYPE_TO_EXTENSION.get(mimetype, ".jpg")

        if filename_strategy == "label" and self.resource.get("label"):
            label = self.resource["label"]
            sanitized_label = re.sub(r'[\\/*?:"<>|]', "", label)
            self.img_name = f"{sanitized_label}{extension}"
        elif filename_strategy == "id":
            image_id = self.url.rstrip('/').split('/')[-1]
            sanitized_id = re.sub(r'[\\/*?:"<>|]', "", image_id)
            self.img_name = f"{sanitized_id}{extension}"
        else:
            self.img_name = f"{prefix}{format(self.idx, f'0{leading_zeros}d')}.jpg"

        self.save_dir = save_dir
        self.keep_original_size = keep_original_size
        self.max_dim = max_dim or 2500
        self.min_dim = min_dim or 1000
        self.size = None
        self.height = self.get_height()
        self.width = self.get_width()
        self.sleep = self.get_sleep_time(self.url)

    @property
    def img_path(self) -> Path:
        return self.save_dir / self.img_name

    def get_height(self) -> Optional[int]:
        return get_size(self.resource, "height")

    def get_width(self) -> Optional[int]:
        return get_size(self.resource, "width")

    def get_sleep_time(self, url: Optional[str] = None) -> float:
        """Get sleep time for a specific URL."""
        if url and "gallica" in url:
            return 12
        return 0.05

    def sized_url(self) -> str:
        return f"{self.url}/full/{self.size}/0/default.jpg"

    async def save(self, re_download: bool = False) -> bool:
        """Download and save the image."""
        if not self.size:
            self.size = "full" if self.keep_original_size else self.get_max_size()

        # Check if already downloaded
        try:
            if not re_download and self.check():
                return True

            return await self.download()
        except Exception as e:
            logger.error(f"Failed to save image {self.sized_url()}", exc_info=e)
            return False

    async def download(self, url=None) -> bool:
        """Download and save the image using configured settings."""
        url = url or self.sized_url()
        time.sleep(self.sleep)

        try:
            async with async_request(url, allow_insecure=True) as res:
                if not res.ok:
                    if res.status == 404 and url != self.url:
                        # try one last time without coord/size/rot/default.jpg
                        # if institution does not implement Image API and only serves static images
                        return await self.download(self.url)
                    self.download_fail(f"⛔️ Failed to download {url}: status {res.status}")
                    return False
                return await self.process_response(res)

        except Exception as e:
            self.download_fail(f"⛔️ Failed to download {url}", exc=e)
            return False

    async def process_response(self, response) -> bool:
        """Process and save the image response using chunked downloading."""
        content_type = response.headers.get("Content-Type", "")
        if "image" not in content_type:
            await write_chunks(self.save_dir / f"{self.img_name}.txt", response)
            self.download_fail(f"⛔️ Incorrect MIME type ({content_type}) for {self.sized_url()}")
            return False

        try:
            await write_chunks(self.img_path, response)
            return True
        except Exception as e:
            if self.size in ["full", f"{self.max_dim},", f",{self.max_dim}"]:
                self.size = self.get_min_size()
                return await self.download()
            self.download_fail(f"⛔️ Failed to process image response {self.sized_url()}", e)
            return False

    def get_max_size(self) -> str:
        if self.max_dim is None:
            return "full"

        if self.height is None or self.width is None:
            return f"{self.max_dim},"

        if self.height > self.width:
            h = self.max_dim if self.height > self.max_dim else self.height
            return f",{h}"
        w = self.max_dim if self.width > self.max_dim else self.width
        return f"{w},"

    def get_min_size(self):
        if not (self.min_dim or self.height or self.width):
            return "full"

        if self.min_dim and not (self.height or self.width):
            return f"{self.min_dim},"

        if not self.min_dim:
            if self.height and self.width:
                larger = max(self.height, self.width, default=0)
                return f"{larger // 2}," if self.width >= self.height else f",{larger // 2}"
            return f"{self.width // 2}," if self.width else f",{self.height // 2}"

        h = self.height
        w = self.width
        min_dim = self.min_dim

        if h > w:
            h = h // 2 if h > min_dim * 2 else (h if h < min_dim else min_dim)
            return f",{h}"

        w = w // 2 if w > min_dim * 2 else (w if w < min_dim else min_dim)
        return f"{w},"

    def check(self) -> bool:
        """
        Check if the image is already downloaded and has the correct dimensions.
        Returns:
            True if the image exists and has the correct dimensions, False otherwise
        """
        if not os.path.exists(self.img_path):
            return False

        img = PILgrimage.open(self.img_path)
        img_height, img_width = img.height, img.width

        if self.max_dim is None:
            return (self.height is None or img_height == self.height) and (
                self.width is None or img_width == self.width
            )

        if max(img_height, img_width) > self.max_dim:
            return False

        return self.min_dim is None or min(img_height, img_width) >= self.min_dim

    def download_fail(self, msg: Optional[str] = None, exc: Optional[Exception] = None) -> None:
        if not msg:
            msg = f"⛔️ Failed to download {self.idx} {self.sized_url()}"

        # TODO harmonize with json format
        with open(self.save_dir / "info.txt", "a") as f:
            f.write(f"\n{msg}\n")
            if exc:
                f.write(f"\n{exc}\n\n\n")

        # Log to console the error
        logger.error(msg, exc_info=exc)

    def cleanup(self) -> None:
        self.resource = None
        gc.collect()
