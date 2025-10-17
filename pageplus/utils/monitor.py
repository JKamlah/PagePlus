"""
Session monitoring utilities for Streamlit applications.

This module provides functionality to monitor active Streamlit sessions
and automatically shut down the server when no sessions are active.
"""

import os
import signal
import time
from pageplus.utils.logger import setup_logger

logger = setup_logger()


def monitor_sessions(lock_file_path=None):
    """
    Monitors active Streamlit sessions and shuts down the server if no sessions
    are active for a specified duration.

    NOTE: This uses an undocumented, internal Streamlit API, which may break
    in future versions. This is not a recommended production practice.
    
    Args:
        lock_file_path: Path to the lock file to hold during monitoring
    """
    from pageplus.utils.filelock import AtomicFileLock
    
    # Hold the lock for the entire duration of monitoring
    if lock_file_path:
        lock = AtomicFileLock(lock_file_path)
        if not lock.acquire_persistent():
            logger.debug("Could not acquire lock for monitoring, another monitor is running")
            return
        
        try:
            _monitor_loop()
        finally:
            lock.release_persistent()
    else:
        _monitor_loop()


def _monitor_loop():
    """The actual monitoring loop."""
    # Grace period to allow for initial connections
    time.sleep(10)

    inactivity_period = 30  # seconds
    check_interval = 5      # seconds
    max_inactive_checks = inactivity_period // check_interval
    inactive_checks = 0
    pid = os.getpid()

    while True:
        try:
            # Import streamlit here to avoid import issues during module loading
            import streamlit as st

            # THIS IS AN UNDOCUMENTED, INTERNAL STREAMLIT API.
            active_sessions = st.runtime.get_instance()._session_mgr.list_active_sessions()

            if not active_sessions:
                inactive_checks += 1
            else:
                inactive_checks = 0  # Reset on activity

            if inactive_checks >= max_inactive_checks:
                if pid == os.getpid():
                    logger.info(f"No active sessions for {inactivity_period} seconds. Shutting down server.")
                    os.kill(os.getpid(), signal.SIGTERM)
                break

        except Exception as e:
            logger.error(f"Failed to check for active Streamlit sessions: {e}. Stopping monitor.")
            break

        time.sleep(check_interval)
