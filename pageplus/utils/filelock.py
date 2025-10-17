"""
File locking utilities for atomic operations.

This module provides atomic file locking mechanisms to prevent race conditions
in multi-process environments.
"""

import os
import fcntl
from pathlib import Path
from typing import Optional


class AtomicFileLock:
    """
    Atomic file lock using fcntl to prevent race conditions.

    This ensures only one process can acquire the lock at a time by using
    OS-level file locking mechanisms. The lock is automatically released
    when the context manager exits.

    Example:
        >>> with AtomicFileLock(Path("/tmp/my.lock")):
        ...     # Critical section - only one process can be here
        ...     do_critical_work()
    """

    def __init__(self, lock_file_path: Path):
        """
        Initialize the atomic file lock.

        Args:
            lock_file_path: Path to the lock file to use for synchronization
        """
        self.lock_file_path = lock_file_path
        self.lock_file: Optional[object] = None
        self.acquired = False

    def __enter__(self):
        """
        Acquire the lock atomically.

        Returns:
            self: The lock instance for use in context manager

        Raises:
            OSError: If the lock cannot be acquired (already held by another process)
            IOError: If there's an I/O error during lock acquisition
        """
        try:
            # Open the lock file in write mode, create if it doesn't exist
            self.lock_file = open(self.lock_file_path, 'w')

            # Try to acquire an exclusive, non-blocking lock
            fcntl.flock(self.lock_file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)

            # Write the current process ID to the lock file
            self.lock_file.write(str(os.getpid()))
            self.lock_file.flush()

            self.acquired = True
            return self

        except (OSError, IOError):
            # Lock is already held by another process
            if self.lock_file:
                self.lock_file.close()
                self.lock_file = None
            raise

    def __exit__(self, exc_type, exc_val, exc_tb):
        """
        Release the lock and clean up.

        Args:
            exc_type: Exception type if an exception occurred
            exc_val: Exception value if an exception occurred
            exc_tb: Exception traceback if an exception occurred
        """
        if self.acquired and self.lock_file:
            try:
                fcntl.flock(self.lock_file.fileno(), fcntl.LOCK_UN)
                self.lock_file.close()
                self.lock_file_path.unlink(missing_ok=True)
            except (OSError, IOError):
                # Ignore errors during cleanup
                pass
            finally:
                self.acquired = False
                self.lock_file = None

    def is_acquired(self) -> bool:
        """
        Check if the lock is currently acquired.

        Returns:
            bool: True if the lock is acquired, False otherwise
        """
        return self.acquired

    def acquire_persistent(self):
        """
        Acquire the lock and keep it until explicitly released.
        This is useful for long-running processes that need to hold the lock
        for their entire lifetime.
        
        Returns:
            bool: True if lock was acquired, False if already held by another process
            
        Raises:
            OSError: If there's an I/O error during lock acquisition
        """
        try:
            # Open the lock file in write mode, create if it doesn't exist
            self.lock_file = open(self.lock_file_path, 'w')

            # Try to acquire an exclusive, non-blocking lock
            fcntl.flock(self.lock_file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)

            # Write the current process ID to the lock file
            self.lock_file.write(str(os.getpid()))
            self.lock_file.flush()

            self.acquired = True
            return True

        except (OSError, IOError):
            # Lock is already held by another process
            if self.lock_file:
                self.lock_file.close()
                self.lock_file = None
            return False

    def release_persistent(self):
        """
        Release the persistent lock and clean up.
        """
        if self.acquired and self.lock_file:
            try:
                fcntl.flock(self.lock_file.fileno(), fcntl.LOCK_UN)
                self.lock_file.close()
                self.lock_file_path.unlink(missing_ok=True)
            except (OSError, IOError):
                # Ignore errors during cleanup
                pass
            finally:
                self.acquired = False
                self.lock_file = None
