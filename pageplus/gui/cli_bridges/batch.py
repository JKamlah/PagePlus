"""CLI bridge for Batch Processing operations."""
from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Optional

from pageplus.gui.cli_bridges.base import CLIBridge
from pageplus.utils.llm.batch_manager import BatchManager


class BatchBridge(CLIBridge):
    """Bridge for managing LLM batch processing jobs."""

    def __init__(self, output_dir: Optional[Path] = None):
        super().__init__(output_dir=output_dir)
        self.manager = BatchManager()

    def list_batches(self, filter_status: Optional[str] = None) -> Dict[str, Any]:
        """List all batch jobs, optionally filtered by status."""
        try:
            jobs = self.manager.check_all_batches()
            if filter_status and filter_status != "All":
                jobs = [j for j in jobs if j.get("status") == filter_status]
            return {"success": True, "batches": jobs}
        except Exception as exc:
            return {"success": False, "output": f"Failed to list batches: {exc}", "batches": []}

    def get_batch(self, batch_id: str) -> Dict[str, Any]:
        """Retrieve details for a single batch job."""
        try:
            job = self.manager.get_job(batch_id)
            if job:
                return {"success": True, "batch": job}
            return {"success": False, "output": f"Batch '{batch_id}' not found."}
        except Exception as exc:
            return {"success": False, "output": f"Failed to get batch: {exc}"}

    def submit_batch(
        self,
        name: str,
        provider: str,
        model: str,
        tasks: List[Dict[str, Any]],
        input_files: List[str],
        output_dir: Optional[str] = None,
        execution_mode: str = "stepwise",
        options: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Submit a new non-blocking batch processing job."""
        try:
            job = self.manager.submit_batch(
                name=name,
                provider=provider,
                model=model,
                tasks=tasks,
                input_files=input_files,
                output_dir=output_dir,
                execution_mode=execution_mode,
                options=options,
            )
            return {"success": True, "batch": job, "output": f"Batch '{job['batch_id']}' submitted successfully."}
        except Exception as exc:
            return {"success": False, "output": f"Failed to submit batch: {exc}"}

    def cancel_batch(self, batch_id: str) -> Dict[str, Any]:
        """Cancel a running batch job."""
        try:
            res = self.manager.cancel_job(batch_id)
            return res
        except Exception as exc:
            return {"success": False, "output": f"Failed to cancel batch: {exc}"}

    def delete_batch(self, batch_id: str) -> Dict[str, Any]:
        """Delete a batch job record."""
        try:
            res = self.manager.delete_job(batch_id)
            return res
        except Exception as exc:
            return {"success": False, "output": f"Failed to delete batch: {exc}"}

    def refresh_batches(self) -> Dict[str, Any]:
        """Force a status check of all active batches."""
        try:
            jobs = self.manager.check_all_batches()
            return {"success": True, "batches": jobs, "output": f"Refreshed {len(jobs)} batch job(s)."}
        except Exception as exc:
            return {"success": False, "output": f"Refresh failed: {exc}", "batches": []}
