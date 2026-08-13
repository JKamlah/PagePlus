"""Streamlit view for the **📊 Batches** management tab.

Provides full visibility into running, completed, failed, and expired LLM batch jobs.
Features summary metrics, filters, status timeline, duration analytics, error cause reports,
and detailed inspection views.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Optional

import pandas as pd
import streamlit as st

from pageplus.gui.cli_bridges.batch import BatchBridge
from pageplus.utils.llm.batch_manager import (
    ALL_STATUSES,
    STATUS_CANCELLED,
    STATUS_CANCELLING,
    STATUS_COMPLETED,
    STATUS_DESCRIPTIONS,
    STATUS_EXPIRED,
    STATUS_FAILED,
    STATUS_FINALIZING,
    STATUS_IN_PROGRESS,
    STATUS_VALIDATING,
)

STATUS_ICONS = {
    STATUS_VALIDATING: "🟡",
    STATUS_IN_PROGRESS: "🔵",
    STATUS_FINALIZING: "🟣",
    STATUS_COMPLETED: "🟢",
    STATUS_FAILED: "🔴",
    STATUS_EXPIRED: "🟠",
    STATUS_CANCELLING: "🛑",
    STATUS_CANCELLED: "⚪",
}


def format_duration(seconds: Optional[float]) -> str:
    """Format duration in seconds to a human-readable string."""
    if seconds is None:
        return "—"
    if seconds < 60:
        return f"{seconds:.1f}s"
    minutes = int(seconds // 60)
    rem_sec = int(seconds % 60)
    if minutes < 60:
        return f"{minutes}m {rem_sec}s"
    hours = int(minutes // 60)
    rem_min = int(minutes % 60)
    return f"{hours}h {rem_min}m"


def show_batches(bridge: BatchBridge) -> None:
    """Display the Batches management page."""
    st.title("📊 LLM Batch Jobs")
    st.caption(
        "Monitor and manage asynchronous LLM batch processing jobs across "
        "OpenAI, Gemini, Mistral, LiteLLM, and local/SSH custom endpoints. "
        "Running batches automatically refresh and save PAGE-XML results."
    )

    # Top Toolbar
    col_ref, col_info, col_nav = st.columns([2, 5, 3])
    with col_ref:
        if st.button("🔄 Refresh All Batches", key="batches_refresh_btn", use_container_width=True):
            res = bridge.refresh_batches()
            if res.get("success"):
                st.success("Refreshed batch statuses.")
                st.rerun()
            else:
                st.error(res.get("output", "Refresh failed."))
    with col_nav:
        if st.button("🤖 Go to LLM-OCR Pipeline", key="batches_goto_llmocr", use_container_width=True):
            st.session_state.main_page_selection = "🤖 LLM-OCR"
            st.rerun()

    st.markdown("---")

    # Fetch all batches
    batch_res = bridge.list_batches()
    batches: List[Dict[str, Any]] = batch_res.get("batches", [])

    # 1. Summary Metrics Bar
    total_count = len(batches)
    in_prog_count = sum(1 for b in batches if b.get("status") in (STATUS_VALIDATING, STATUS_IN_PROGRESS, STATUS_FINALIZING))
    completed_count = sum(1 for b in batches if b.get("status") == STATUS_COMPLETED)
    failed_count = sum(1 for b in batches if b.get("status") == STATUS_FAILED)
    other_count = sum(1 for b in batches if b.get("status") in (STATUS_EXPIRED, STATUS_CANCELLING, STATUS_CANCELLED))

    m1, m2, m3, m4, m5 = st.columns(5)
    m1.metric("📊 Total Batches", total_count)
    m2.metric("🔵 In Progress / Validating", in_prog_count)
    m3.metric("🟢 Completed", completed_count)
    m4.metric("🔴 Failed", failed_count)
    m5.metric("🟠 Expired / Cancelled", other_count)

    st.markdown("---")

    # 2. Filters & Search Bar
    f1, f2, f3 = st.columns([3, 3, 4])
    with f1:
        status_filter = st.selectbox(
            "Filter by Status",
            ["All"] + ALL_STATUSES,
            format_func=lambda s: f"{STATUS_ICONS.get(s, '')} {s}" if s != "All" else "All Statuses",
            key="batches_status_filter",
        )
    with f2:
        providers = sorted({b.get("provider", "unknown") for b in batches})
        provider_filter = st.selectbox(
            "Filter by Provider",
            ["All"] + providers,
            key="batches_provider_filter",
        )
    with f3:
        search_query = st.text_input(
            "Search Batches (ID, Name, Model, Error)",
            placeholder="Search keyword...",
            key="batches_search_query",
        )

    # Filter batches
    filtered_batches = list(batches)
    if status_filter != "All":
        filtered_batches = [b for b in filtered_batches if b.get("status") == status_filter]
    if provider_filter != "All":
        filtered_batches = [b for b in filtered_batches if b.get("provider") == provider_filter]
    if search_query.strip():
        q = search_query.strip().lower()
        filtered_batches = [
            b for b in filtered_batches
            if q in b.get("batch_id", "").lower()
            or q in b.get("name", "").lower()
            or q in b.get("model", "").lower()
            or q in str(b.get("error_message", "")).lower()
        ]

    if not filtered_batches:
        st.info("No matching batch jobs found.")
        return

    # Dataframe Table View
    st.subheader("Batch Job List")
    table_data = []
    for b in filtered_batches:
        st_val = b.get("status", "")
        icon = STATUS_ICONS.get(st_val, "❓")
        duration_str = format_duration(b.get("duration_seconds"))
        num_inputs = len(b.get("input_files", []))
        num_outputs = len(b.get("output_files", []))

        table_data.append({
            "Status": f"{icon} {st_val}",
            "Batch ID": b.get("batch_id"),
            "Job Name": b.get("name"),
            "Provider": b.get("provider"),
            "Model": b.get("model") or "—",
            "Created At": b.get("created_at", "")[:19].replace("T", " "),
            "Duration": duration_str,
            "Inputs": num_inputs,
            "Outputs": num_outputs,
        })

    st.dataframe(pd.DataFrame(table_data), width="stretch", hide_index=True)

    st.markdown("---")

    # 3. Detailed Inspector View
    st.subheader("🔍 Job Details & Diagnostics")
    job_ids = [b["batch_id"] for b in filtered_batches]
    selected_id = st.selectbox(
        "Select a batch to inspect",
        job_ids,
        format_func=lambda j_id: next(
            f"{STATUS_ICONS.get(b.get('status'), '')} {b.get('name')} ({j_id})"
            for b in filtered_batches if b["batch_id"] == j_id
        ),
        key="batches_select_inspect",
    )

    selected_job = bridge.get_batch(selected_id).get("batch")
    if not selected_job:
        st.warning("Selected batch job details could not be loaded.")
        return

    # Overview Cards
    c1, c2, c3, c4 = st.columns(4)
    st_val = selected_job.get("status", "")
    icon = STATUS_ICONS.get(st_val, "")
    c1.markdown(f"**Status:** {icon} `{st_val}`")
    c2.markdown(f"**Provider:** `{selected_job.get('provider')}`")
    c3.markdown(f"**Model:** `{selected_job.get('model') or 'Default'}`")
    c4.markdown(f"**Duration:** `{format_duration(selected_job.get('duration_seconds'))}`")

    st.info(f"ℹ️ **Status Description:** {selected_job.get('status_message', STATUS_DESCRIPTIONS.get(st_val, ''))}")

    # Action Buttons for Selected Job
    b_act1, b_act2, b_act3 = st.columns([3, 3, 3])
    with b_act1:
        if st.button("🔄 Check Status Now", key=f"batches_chk_{selected_id}"):
            bridge.refresh_batches()
            st.rerun()
    with b_act2:
        is_terminal = st_val in (STATUS_COMPLETED, STATUS_FAILED, STATUS_EXPIRED, STATUS_CANCELLED)
        if st.button("⏹ Cancel Batch Job", key=f"batches_cnc_{selected_id}", disabled=is_terminal):
            res = bridge.cancel_batch(selected_id)
            if res.get("success"):
                st.success(res.get("message", "Batch cancelled."))
            else:
                st.error(res.get("output", "Cancellation failed."))
            st.rerun()
    with b_act3:
        if st.button("🗑 Delete Job Record", key=f"batches_del_{selected_id}"):
            res = bridge.delete_batch(selected_id)
            if res.get("success"):
                st.success(res.get("message", "Job deleted."))
                st.rerun()
            else:
                st.error(res.get("output", "Deletion failed."))

    # Error Cause Report (if failed, expired, or cancelled)
    if selected_job.get("error_message"):
        st.error(f"❌ **Error Cause / Reason:** {selected_job.get('error_message')}")

    # Tabs for Details
    dt1, dt2, dt3 = st.tabs(["📁 Files & Outputs", "📈 Duration Analytics", "🛠 Raw Metadata JSON"])

    with dt1:
        st.markdown("**Input Files:**")
        in_files = selected_job.get("input_files", [])
        if in_files:
            st.dataframe(pd.DataFrame([{"File Path": f, "Filename": Path(f).name} for f in in_files]), width="stretch")
        else:
            st.caption("No input files recorded.")

        st.markdown("**Output Files / PAGE-XML:**")
        out_files = selected_job.get("output_files", [])
        if out_files:
            st.dataframe(pd.DataFrame([{"Output File": f, "Filename": Path(f).name} for f in out_files]), width="stretch")
        else:
            st.caption("No output files generated yet.")

    with dt2:
        st.markdown(f"- **Created At:** `{selected_job.get('created_at')}`")
        st.markdown(f"- **Started At:** `{selected_job.get('started_at') or 'Not started'}`")
        st.markdown(f"- **Completed At:** `{selected_job.get('completed_at') or 'In progress'}`")
        dur_sec = selected_job.get("duration_seconds")
        st.markdown(f"- **Total Duration:** `{format_duration(dur_sec)}` ({dur_sec or 0} seconds)")

        details = selected_job.get("details", {})
        usage = details.get("usage", {})
        if usage:
            st.markdown("**Token Usage Summary:**")
            st.json(usage)

    with dt3:
        st.json(selected_job)
