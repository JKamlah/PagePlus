import asyncio
import os
from pathlib import Path
from typing import List, Tuple

import aiofiles
import aiohttp
from rich.progress import Progress, SpinnerColumn, BarColumn, TextColumn, TimeRemainingColumn, TimeElapsedColumn

from pageplus.utils.constants import MIME_IMAGE_EXTENSIONS
from pageplus.utils.mets_mods import File, FLocat, get_files_from_flocat
from pageplus.utils.logger import logging

logger = logging.getLogger(__name__)


async def download_file_from_flocat_async(
        session: aiohttp.ClientSession,
        file: File,
        output_folder: Path,
        nametag: str = None,
        overwrite: bool = False,
        semaphore: asyncio.Semaphore = None
) -> Tuple[str, str]:
    """
    Asynchronously download a file from an FLocat element.
    """
    href, filename = get_files_from_flocat(file, nametag)

    if not href:
        return "", "no_href"

    target_path = output_folder / filename

    if target_path.exists() and not overwrite:
        return href, "exists"

    user_agent = os.getenv("PAGEPLUS_USER_AGENT",
                           "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")
    headers = {"User-Agent": user_agent}

    async with semaphore:
        try:
            async with session.get(href, headers=headers, timeout=20) as response:
                response.raise_for_status()
                async with aiofiles.open(target_path, "wb") as f:
                    await f.write(await response.read())
                return href, "downloaded"
        except Exception as e:
            return href, f"failed: {e}"


async def download_files_async(download_tasks: List[Tuple[File, Path, str]], batch_size: int):
    progress_columns = [
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        BarColumn(),
        TextColumn("[progress.percentage]{task.percentage:>3.0f}%"),
        TimeRemainingColumn(),
        TimeElapsedColumn(),
    ]

    semaphore = asyncio.Semaphore(batch_size)
    async with aiohttp.ClientSession() as session:
        with Progress(*progress_columns, transient=False) as progress:
            task = progress.add_task("[cyan]Downloading...", total=len(download_tasks))
            async_tasks = [
                download_file_from_flocat_async(
                    session,
                    file,
                    folder,
                    nametag,
                    overwrite=True,
                    semaphore=semaphore) for file,
                folder,
                nametag in download_tasks]
            for future in asyncio.as_completed(async_tasks):
                result = await future
                progress.update(task, advance=1)


async def download_iiif_images_async(images: List, batch_size: int, re_download: bool = False):
    progress_columns = [
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        BarColumn(),
        TextColumn("[progress.percentage]{task.percentage:>3.0f}%"),
        TimeRemainingColumn(),
        TimeElapsedColumn(),
    ]

    async with aiohttp.ClientSession() as session:
        with Progress(*progress_columns, transient=False) as progress:
            task = progress.add_task("[cyan]Downloading IIIF Images...", total=len(images))
            semaphore = asyncio.Semaphore(batch_size)
            num_batches = (len(images) + batch_size - 1) // batch_size

            for i in range(num_batches):
                start_index = i * batch_size
                end_index = start_index + batch_size
                batch_images = images[start_index:end_index]

                logger.info(f"Downloading batch {i + 1}/{num_batches} ({len(batch_images)} images)...")

                async def download_with_semaphore(image):
                    async with semaphore:
                        await image.save(re_download=re_download, session=session)
                        logger.info(f"Downloaded image {image.idx}")
                        progress.update(task, advance=1)

                download_tasks = [download_with_semaphore(image) for image in batch_images]
                await asyncio.gather(*download_tasks)
