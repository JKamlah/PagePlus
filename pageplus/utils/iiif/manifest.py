import asyncio
import gc
from pathlib import Path
from typing import Any, Dict, List, Optional, Union
from urllib.parse import unquote

from pageplus.utils.iiif.image import IIIFImage
from pageplus.utils.iiif.utils import (
    create_dir,
    get_id,
    get_json_async,
    get_license_url,
    get_meta_value,
    mono_val,
    sanitize_str,
)
from pageplus.utils.logger import logging
from pageplus.utils.download_helpers import create_download_info_file, ProgressTracker

logger = logging.getLogger(__name__)

LICENSE = [
    "license",
    "licence",
    "lizenz",
    "rights",
    "droits",
    "access",
    "copyright",
    "rechteinformationen",
    "conditions",
]


def parse_page_range(range_str: Optional[str]) -> Optional[set[int]]:
    """Parses a page range string like '1-3,5,7-9' into a set of integers."""
    if not range_str:
        return None

    pages = set()
    parts = range_str.split(',')
    for part in parts:
        part = part.strip()
        if not part:
            continue
        if '-' in part:
            try:
                start, end = part.split('-', 1)
                pages.update(range(int(start.strip()), int(end.strip()) + 1))
            except ValueError:
                # Handle invalid range format gracefully
                logger.warning(f"Invalid page range part: {part}")
        else:
            try:
                pages.add(int(part))
            except ValueError:
                logger.warning(f"Invalid page number: {part}")
    return pages


class IIIFManifest:
    """Represents a IIIF manifest with its metadata and image list."""

    def __init__(
        self,
        url: str,
        save_dir: Optional[Union[Path, str]] = None,
        prefix: str = "",
        leading_zeros: int = 4,
        page_range: Optional[str] = None,
        filename_strategy: str = "label",
        keep_original_size: bool = True,
        max_dim: Optional[int] = None,
        min_dim: Optional[int] = None,
        batch_size: int = 25,
        progress_callback=None,
        overwrite: bool = False,
        **kwargs,
    ):
        self.url = unquote(url)
        self.content: Optional[Dict[str, Any]] = None
        self._prefix = prefix
        self._leading_zeros = leading_zeros
        self._save_dir: Path = Path(save_dir) if save_dir else Path.cwd()
        self._manifest_info: Dict = {}
        self._license: Optional[str] = None
        self._resources: Optional[List] = None
        self._images: Optional[List[IIIFImage]] = None
        self.page_range: Optional[set[int]] = parse_page_range(page_range)
        self.filename_strategy = filename_strategy
        self.keep_original_size = keep_original_size
        self.max_dim = max_dim
        self.min_dim = min_dim
        self.batch_size = batch_size
        self.progress_callback = progress_callback
        self.overwrite = overwrite

    @property
    def save_dir(self) -> Path:
        """Directory where images will be saved."""
        return self._save_dir

    @save_dir.setter
    def save_dir(self, path):
        self._save_dir = Path(path) if path else Path.cwd()

    @property
    def uid(self) -> str:
        """Generate a directory name from manifest URL."""
        return sanitize_str(self.url).replace("manifest", "").replace("json", "")

    async def load(self, reload=False) -> bool:
        """Load manifest content from URL."""
        if bool(self.content) and not reload:
            return True

        try:
            self.content = await get_json_async(self.url, allow_insecure=True)
            # if self.config.save_manifest:
            #     with open(self.save_dir / "manifest.json", "w") as f:
            #         json.dump(self.content, f)
            return bool(self.content)
        except Exception as e:
            logger.error(f"Failed to load manifest from {self.url}", exc_info=e)
            return False

    def get_meta(self, label: str) -> Optional[str]:
        """Get value from manifest metadata"""
        if not self.content:
            return None

        if "metadata" not in self.content:
            return None

        for meta in self.content.get("metadata", []):
            if value := get_meta_value(meta, label):
                return value

        return None

    # TODO add a property metadata with every metadata provided

    @property
    def license(self) -> str:
        if self._license is None:
            self._license = self.get_license()
        return self._license

    def get_license(self) -> str:
        """Get license information from manifest."""
        if not self.content:
            return "No manifest loaded"

        for label in ["license", "rights"]:
            if lic := self.content.get(label):
                return get_license_url(mono_val(lic))

        if metadata := self.content.get("metadata"):
            for meta in metadata:
                if meta_label := str(meta.get("label", "")).lower():
                    if any(term in meta_label for term in LICENSE):
                        return get_license_url(meta.get("value", ""))

                for label in LICENSE:
                    if value := get_meta_value(meta, label):
                        return get_license_url(value)

        return get_license_url(mono_val(self.content.get("attribution", "")))

    @staticmethod
    def get_image_resource(image_data: Dict[str, Any], label: str = "") -> Optional[Dict[str, Any]]:
        """Extract image resource from image data."""
        try:
            resource = image_data.get("resource") or image_data.get("body")
            if label:
                resource["label"] = label
            return resource
        except KeyError:
            return None

    @property
    def resources(self) -> List:
        if self._resources is None:
            self._resources = self.get_resources()
        return self._resources

    def get_resources(self) -> List:
        """Extract all image resources from manifest."""
        resources = []
        if not self.content:
            return resources

        try:
            # Try sequences/canvases path
            sequences = self.content["sequences"]
            if len(sequences) < 1:
                return resources
            canvases = self.content["sequences"][0]["canvases"]
            for canvas in canvases:
                label = canvas.get("label", "")
                for image in canvas["images"]:
                    if resource := self.get_image_resource(image, label=label):
                        resources.append(resource)
        except KeyError:
            try:
                # Try items path
                items = self.content["items"]
                for item in items:
                    for sub_item in item["items"][0]["items"]:
                        if resource := self.get_image_resource(sub_item):
                            resources.append(resource)
            except KeyError as e:
                logger.error("Failed to extract images from manifest", exc_info=e)

        return resources

    @staticmethod
    def get_img_service(resource):
        if resource.get("service"):
            return get_id(resource["service"])
        img_id = get_id(resource)

        # look for hidden image services
        if img_id.endswith(("/full/full/0/default.jpg", "/full/max/0/default.jpg")):
            return img_id.rsplit("/", 4)[0]

        # case were only static images are provided
        return img_id

    # TODO add property canvas

    @property
    def images(self) -> List:
        if self._images is None:
            self._images = self.get_images()
        return self._images

    def get_images(self) -> List[IIIFImage]:
        """Get all images from manifest."""
        images = []
        for i, resource in enumerate(self.get_resources()):
            idx = i + 1
            if self.page_range and idx not in self.page_range:
                continue

            images.append(
                IIIFImage(
                    idx=i + 1,
                    img_id=self.get_img_service(resource),
                    resource=resource,
                    save_dir=self.save_dir,
                    prefix=self._prefix,
                    leading_zeros=self._leading_zeros,
                    filename_strategy=self.filename_strategy,
                    keep_original_size=self.keep_original_size,
                    max_dim=self.max_dim,
                    min_dim=self.min_dim,
                )
            )
        return images

    def save_log(self):
        # if self.config.is_logged:
        #     logger.add_to_json(self.save_dir / "info.json", self._manifest_info)
        pass

    def download(
        self, save_dir: Optional[Union[Path, str]] = None, cleanup=False
    ) -> Union[bool, "IIIFManifest"]:
        if save_dir:
            self.save_dir = save_dir
        if not self.save_dir.exists():
            create_dir(self.save_dir)

        async def _async_download_manifest():
            # if self.config.is_logged:
            #     self._manifest_info = {"url": self.url, "license": "", "images": {}}

            if not await self.load():
                logger.warning(f"Unable to load json content of {self.url}")
                self.save_log()
                return self

            # if self.config.is_logged:
            #     self._manifest_info["license"] = self.license

            images = self.images
            if not images:
                logger.warning(f"No images found in manifest {self.url}")
                self.save_log()
                return self

            logger.info(f"Downloading {len(images)} images from {self.url} inside {self.save_dir}")

            # Initialize progress tracker
            tracker = ProgressTracker(total=len(images), callback=self.progress_callback)
            tracker.initialize()

            # Create a semaphore to limit concurrent downloads
            semaphore = asyncio.Semaphore(self.batch_size)

            async def download_with_semaphore(image):
                async with semaphore:
                    if not self.overwrite and image.img_path.exists():
                        logger.info(f"Skipping existing image: {image.img_name}")
                        tracker.report_success()
                        return True
                    result = await image.save(re_download=self.overwrite)
                    if result:
                        tracker.report_success()
                    else:
                        tracker.report_failed(f"Image #{image.idx}: {image.sized_url()}")
                        logger.error(f"Failed to download image #{image.idx} ({image.sized_url()})")
                    # if self.config.is_logged:
                    #     self._manifest_info["images"][image.img_name] = image.sized_url()
                    return result

            # Create a list of tasks
            tasks = [download_with_semaphore(image) for image in images]

            # Run tasks concurrently with batch size limit
            await asyncio.gather(*tasks)

            # Get final statistics
            stats = tracker.get_stats()

            # Create info.txt with statistics
            additional_info = {
                "Manifest URL": self.url,
                "Batch size": str(self.batch_size)
            }
            info_path = create_download_info_file(
                self.save_dir,
                stats,
                "IIIF Download Statistics",
                additional_info
            )

            logger.info(f"Download statistics saved to {info_path}")
            print(f"\n✅ Successfully downloaded: {stats.successful}/{len(images)}")
            print(f"❌ Failed: {stats.failed}/{len(images)}")

            self.save_log()
            return self

        try:
            result = asyncio.run(_async_download_manifest())
        finally:
            if cleanup:
                self.cleanup()
        return result

    def cleanup(self):
        self.content = None
        self._resources = None
        self._manifest_info = None
        if self._images:
            for img in self._images:
                img.cleanup()
            self._images = None
        gc.collect()
