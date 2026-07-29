import asyncio
import os
from pathlib import Path
from typing import List, Tuple

import aiofiles
import aiohttp
from rich.progress import Progress, SpinnerColumn, BarColumn, TextColumn, TimeRemainingColumn, TimeElapsedColumn

from pageplus.utils.mets_mods import File, get_files_from_flocat
from pageplus.utils.logger import logging
from pageplus.utils.download_helpers import DownloadStats, create_download_info_file, print_download_summary, ProgressTracker

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


async def download_files_async(download_tasks: List[Tuple[File, Path, str]], batch_size: int, output_dir: Path = None, skip_existing: bool = True):
    """Download METS files asynchronously with progress tracking (CLI version)."""
    progress_columns = [
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        BarColumn(),
        TextColumn("[progress.percentage]{task.percentage:>3.0f}%"),
        TimeRemainingColumn(),
        TimeElapsedColumn(),
    ]

    stats = DownloadStats(total=len(download_tasks))
    semaphore = asyncio.Semaphore(batch_size)

    async with aiohttp.ClientSession() as session:
        with Progress(*progress_columns, transient=False) as progress:
            task = progress.add_task(f"[cyan]Downloading (batch size: {batch_size})...", total=len(download_tasks))
            async_tasks = [
                download_file_from_flocat_async(
                    session,
                    file,
                    folder,
                    nametag,
                    overwrite=not skip_existing,
                    semaphore=semaphore) for file,
                folder,
                nametag in download_tasks]

            for future in asyncio.as_completed(async_tasks):
                href, status = await future
                progress.update(task, advance=1)

                if status == "downloaded":
                    stats.update_success()
                elif status == "exists":
                    stats.update_exists()
                elif status.startswith("failed"):
                    stats.update_failed(f"Failed: {href} - {status}")
                elif status == "no_href":
                    stats.update_failed("Failed: No href found")

    # Create info.txt with statistics
    if output_dir:
        info_path = create_download_info_file(output_dir, stats, "METS Download Statistics")
        logger.info(f"Download statistics saved to {info_path}")

    # Print summary
    print_download_summary(stats)

    return stats.to_dict()


async def download_files_async_with_progress(download_tasks: List[Tuple[File, Path, str]], batch_size: int, output_dir: Path = None, skip_existing: bool = True, progress_callback=None):
    """
    Download METS files asynchronously with progress callback support for GUI.
    """
    tracker = ProgressTracker(total=len(download_tasks), callback=progress_callback)
    tracker.initialize()

    semaphore = asyncio.Semaphore(batch_size)

    async with aiohttp.ClientSession() as session:
        async def download_with_callback(file, folder, nametag):
            href, status = await download_file_from_flocat_async(
                session, file, folder, nametag, overwrite=not skip_existing, semaphore=semaphore
            )

            if status == "downloaded":
                tracker.report_success()
            elif status == "exists":
                tracker.report_exists()
            elif status.startswith("failed"):
                tracker.report_failed(f"Failed: {href} - {status}")
            elif status == "no_href":
                tracker.report_failed("Failed: No href found")

            return href, status

        async_tasks = [
            download_with_callback(file, folder, nametag)
            for file, folder, nametag in download_tasks
        ]

        await asyncio.gather(*async_tasks)

    # Create info.txt with statistics
    if output_dir:
        stats = tracker.get_stats()
        info_path = create_download_info_file(output_dir, stats, "METS Download Statistics")
        logger.info(f"Download statistics saved to {info_path}")

    return tracker.get_stats().to_dict()


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
