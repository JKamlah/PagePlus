"""
Helper utilities for download operations with progress tracking.
"""
from pathlib import Path
from typing import Dict, List, Optional, Callable
from dataclasses import dataclass, field


@dataclass
class DownloadStats:
    """Statistics for download operations."""
    total: int = 0
    successful: int = 0
    failed: int = 0
    exists: int = 0
    failed_items: List[str] = field(default_factory=list)

    def update_success(self):
        """Increment successful count."""
        self.successful += 1

    def update_failed(self, item: str):
        """Increment failed count and log the item."""
        self.failed += 1
        self.failed_items.append(item)

    def update_exists(self):
        """Increment exists count."""
        self.exists += 1

    def to_dict(self) -> Dict:
        """Convert to dictionary."""
        return {
            "total": self.total,
            "successful": self.successful,
            "failed": self.failed,
            "exists": self.exists
        }

    @property
    def completed(self) -> int:
        """Get total completed downloads."""
        return self.successful + self.failed + self.exists


def create_download_info_file(
    output_dir: Path,
    stats: DownloadStats,
    title: str = "Download Statistics",
    additional_info: Optional[Dict[str, str]] = None
) -> Path:
    """
    Create an info.txt file with download statistics.
    
    Args:
        output_dir: Directory to save the info file
        stats: DownloadStats object with statistics
        title: Title for the info file
        additional_info: Additional key-value pairs to include (e.g., {"Manifest URL": "..."})
    
    Returns:
        Path to the created info file
    """
    info_path = output_dir / "info.txt"
    
    with open(info_path, "w") as f:
        f.write(f"{title}\n")
        f.write("=" * len(title) + "\n\n")
        
        # Write additional info if provided
        if additional_info:
            for key, value in additional_info.items():
                f.write(f"{key}: {value}\n")
            f.write("\n")
        
        # Write statistics
        f.write(f"Total files: {stats.total}\n")
        f.write(f"Successfully downloaded: {stats.successful}\n")
        f.write(f"Already exists: {stats.exists}\n")
        f.write(f"Failed: {stats.failed}\n\n")
        
        # Write failed items if any
        if stats.failed_items:
            f.write("Error Details:\n")
            f.write("--------------\n")
            for item in stats.failed_items:
                f.write(f"{item}\n")
    
    return info_path


def print_download_summary(stats: DownloadStats, show_exists: bool = True):
    """
    Print a formatted download summary to console.
    
    Args:
        stats: DownloadStats object with statistics
        show_exists: Whether to show "already exists" count
    """
    print(f"\n✅ Successfully downloaded: {stats.successful}")
    if show_exists:
        print(f"📁 Already exists: {stats.exists}")
    print(f"❌ Failed: {stats.failed}")
    print(f"📊 Total: {stats.total}")


class ProgressTracker:
    """
    Helper class to manage progress callbacks.
    
    This provides a consistent interface for tracking and reporting progress
    across different download operations.
    """
    
    def __init__(self, total: int, callback: Optional[Callable] = None):
        """
        Initialize progress tracker.
        
        Args:
            total: Total number of items to download
            callback: Optional callback function to call on progress updates
        """
        self.total = total
        self.callback = callback
        self.stats = DownloadStats(total=total)
    
    def update(self):
        """Update progress and call callback if provided."""
        if self.callback:
            self.callback(
                self.stats.completed,
                self.stats.total,
                self.stats.successful,
                self.stats.failed,
                self.stats.exists
            )
    
    def report_success(self):
        """Report a successful download."""
        self.stats.update_success()
        self.update()
    
    def report_failed(self, item: str):
        """Report a failed download."""
        self.stats.update_failed(item)
        self.update()
    
    def report_exists(self):
        """Report an already existing file."""
        self.stats.update_exists()
        self.update()
    
    def initialize(self):
        """Call initial progress update."""
        if self.callback:
            self.callback(0, self.total, 0, 0, 0)
    
    def get_stats(self) -> DownloadStats:
        """Get current statistics."""
        return self.stats


def format_download_status(completed: int, total: int, successful: int, failed: int, exists: int = 0) -> str:
    """
    Format download status as a string.
    
    Args:
        completed: Number of completed downloads
        total: Total number of downloads
        successful: Number of successful downloads
        failed: Number of failed downloads
        exists: Number of already existing files
    
    Returns:
        Formatted status string
    """
    percentage = (completed / total * 100) if total > 0 else 0
    return f"Progress: {completed}/{total} ({percentage:.1f}%) | ✅ {successful} | 📁 {exists} | ❌ {failed}"


