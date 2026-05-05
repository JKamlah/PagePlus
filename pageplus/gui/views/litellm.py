"""Streamlit view for the LiteLLM-backed OCR pipeline.

This mirrors the layout of :mod:`pageplus.gui.views.gemini` (⚙️ Settings, 📁 I/O,
🔬 Process) so users can move between **Gemini** and **LiteLLM** with the same
I/O and execution habits:

* **Settings** — provider presets, credentials, and token cost settings
  (for the usage report / estimates).
* **I/O** — the same image queue as Gemini (``st.session_state.modification_input``)
  and the same ``modification_dir`` output override; load PAGE-XML on the main
  **Input** page for ReOCR.
* **Process** — OCR vs ReOCR, five PAGE-XML-aware task modes, model and run
  parameters, threaded terminal, token report, and download of console output.

Terminal streaming helpers are reused from :mod:`pageplus.gui.views.gemini` so
the two pages feel consistent.
"""
from __future__ import annotations

import queue
import sys
import threading
import time
from io import StringIO
from pathlib import Path
from typing import List, Optional

import pandas as pd
import streamlit as st

from pageplus.gui.cli_bridges.litellm import LiteLLMBridge
from pageplus.gui.utils.picker import pick_directory, pick_files
from pageplus.gui.utils.settings import Settings
from pageplus.gui.views.gemini import (
    QueueOutput,
    calculate_token_costs,
    process_result,
    update_terminal_display,
)
from pageplus.gui.views.load_files import get_loaded_workspace_dir
from pageplus.utils.fs import shuffle


IMAGE_EXT_OPTIONS = [".jpg", ".jpeg", ".png", ".bmp", ".tiff", ".tif"]

TASK_MODE_LABELS = {
    "layout_only": "Layout only (regions + coords)",
    "layout_and_text": "Layout + text (recommended OCR default)",
    "layout_correction": "Layout correction (refine coords)",
    "text_only": "Text only (coords preserved)",
    "text_correction": "Text correction (refine existing text)",
}

IMAGE_ONLY_MODES = {"layout_only", "layout_and_text"}
CORRECTION_MODES = {
    "layout_correction",
    "text_only",
    "text_correction",
}


# ---------------------------------------------------------------------------
# Preset resolution
# ---------------------------------------------------------------------------


def _resolve_selected_preset(bridge: LiteLLMBridge) -> Optional[dict]:
    """Load preset list and ensure ``litellm_selected_preset`` is valid."""
    res = bridge.list_presets(only_configured=False)
    presets: List[dict] = res.get("presets", [])
    if not presets:
        return None
    ids = [p["id"] for p in presets]
    preset_by_id = {p["id"]: p for p in presets}
    if "litellm_selected_preset" not in st.session_state:
        default_idx = next((i for i, p in enumerate(presets) if p["configured"]), 0)
        st.session_state.litellm_selected_preset = presets[default_idx]["id"]
    if st.session_state.litellm_selected_preset not in preset_by_id:
        st.session_state.litellm_selected_preset = ids[0]
    return preset_by_id[st.session_state.litellm_selected_preset]


# ---------------------------------------------------------------------------
# Settings tab: presets + token costs
# ---------------------------------------------------------------------------


def _litellm_token_settings(settings: Settings) -> None:
    with st.expander("💰 Token costs (for usage report & estimates)", expanded=False):
        st.caption(
            "Set per-1M token prices the same way as on the Gemini page; "
            "they apply globally to the cost report below."
        )
        new_in = st.text_input(
            "Input token cost (per 1M tokens)",
            value=settings.get("INPUT_TOKEN_COSTS", ""),
            placeholder="e.g., 0.5 (leave empty if not set)",
            key="litellm_input_token_cost_input",
        )
        if st.button("Set input token cost", key="litellm_set_input_token_cost"):
            if not new_in.strip():
                settings.set("INPUT_TOKEN_COSTS", "")
                st.success("Input token cost cleared.")
            else:
                try:
                    float(new_in)
                except ValueError:
                    st.error("Please enter a number (e.g., 0.5) or leave empty.")
                else:
                    settings.set("INPUT_TOKEN_COSTS", new_in)
                    st.success(f"Input token cost (per 1M) set to: {new_in}")

        new_out = st.text_input(
            "Output token cost (per 1M tokens)",
            value=settings.get("OUTPUT_TOKEN_COSTS", ""),
            placeholder="e.g., 1.5 (leave empty if not set)",
            key="litellm_output_token_cost_input",
        )
        if st.button("Set output token cost", key="litellm_set_output_token_cost"):
            if not new_out.strip():
                settings.set("OUTPUT_TOKEN_COSTS", "")
                st.success("Output token cost cleared.")
            else:
                try:
                    float(new_out)
                except ValueError:
                    st.error("Please enter a number (e.g., 1.5) or leave empty.")
                else:
                    settings.set("OUTPUT_TOKEN_COSTS", new_out)
                    st.success(f"Output token cost (per 1M) set to: {new_out}")


def _litellm_providers_block(bridge: LiteLLMBridge) -> None:
    st.subheader("Provider presets")
    st.caption(
        "Presets are LiteLLM-routable providers. "
        "Credentials are stored in your PagePlus ``.env``; refresh re-checks "
        "which presets are ready on this machine."
    )
    only_configured = st.checkbox(
        "Show only configured presets",
        value=False,
        key="litellm_only_configured",
    )
    if st.button("🔄 Refresh presets", key="litellm_refresh_presets"):
        st.rerun()

    result = bridge.list_presets(only_configured=only_configured)
    presets: List[dict] = result.get("presets", [])
    if not presets:
        st.info("No presets match the current filter (or the registry is empty).")
        return

    table_df = pd.DataFrame(
        [
            {
                "id": p["id"],
                "Name": p["display_name"],
                "Prefix": p["litellm_prefix"],
                "Default model": p["default_model"] or "-",
                "Configured?": "✅" if p["configured"] else "❌",
                "Task modes": ", ".join(p["task_modes"]),
            }
            for p in presets
        ]
    )
    st.dataframe(table_df, width="stretch")

    preset_labels = [
        f"{p['display_name']}  ({p['id']})" + ("  ✅" if p["configured"] else "  ❌")
        for p in presets
    ]
    _resolve_selected_preset(bridge)
    ids = [p["id"] for p in presets]
    preset_by_id = {p["id"]: p for p in presets}
    current_idx = (
        ids.index(st.session_state.litellm_selected_preset)
        if st.session_state.litellm_selected_preset in ids
        else 0
    )
    chosen_idx = st.selectbox(
        "Selected preset",
        options=list(range(len(ids))),
        format_func=lambda i: preset_labels[i],
        index=current_idx,
        key="litellm_preset_select",
    )
    st.session_state.litellm_selected_preset = ids[chosen_idx]
    preset = preset_by_id[ids[chosen_idx]]

    with st.expander("🔐 Credentials", expanded=not preset["configured"]):
        col_key, col_base = st.columns(2)
        with col_key:
            if preset["env_api_key"]:
                masked = "••••••" if preset["configured"] else "(not set)"
                st.text_input(
                    f"API key (env: {preset['env_api_key']})",
                    value=masked,
                    disabled=True,
                    key=f"litellm_key_display_{preset['id']}",
                )
                new_key = st.text_input(
                    "New API key",
                    value="",
                    type="password",
                    key=f"litellm_key_input_{preset['id']}",
                )
                if st.button("Save API key", key=f"litellm_save_key_{preset['id']}"):
                    if not new_key:
                        st.warning("Please enter a key before saving.")
                    else:
                        res = bridge.save_api_key(preset["id"], new_key)
                        (st.success if res["success"] else st.error)(res["output"])
                        st.rerun()
            else:
                st.caption("This preset does not require an API-key env var.")
        with col_base:
            if preset["env_api_base"] is not None:
                info = bridge.preset_info(preset["id"]).get("preset", {})
                current_url = info.get("api_base_url", "") or ""
                st.text_input(
                    f"API base URL (env: {preset['env_api_base']})",
                    value=current_url or (preset["api_base_hint"] or ""),
                    disabled=True,
                    key=f"litellm_base_display_{preset['id']}",
                )
                new_base = st.text_input(
                    "New base URL",
                    value="",
                    placeholder=preset["api_base_hint"] or "https://...",
                    key=f"litellm_base_input_{preset['id']}",
                )
                if st.button("Save base URL", key=f"litellm_save_base_{preset['id']}"):
                    if not new_base:
                        st.warning("Please enter a URL before saving.")
                    else:
                        res = bridge.save_api_base(preset["id"], new_base)
                        (st.success if res["success"] else st.error)(res["output"])
                        st.rerun()
            elif preset["requires_base_url"]:
                st.warning("This preset requires a base URL but has no env var declared.")
            else:
                st.caption("This preset does not use a custom base URL.")

    st.markdown("#### Preset details")
    info_df = pd.DataFrame(
        [
            {"Field": "ID", "Value": preset["id"]},
            {"Field": "Display name", "Value": preset["display_name"]},
            {"Field": "LiteLLM prefix", "Value": preset["litellm_prefix"]},
            {"Field": "Default model", "Value": preset["default_model"] or "-"},
            {
                "Field": "Vision capable",
                "Value": "yes" if preset["vision_capable"] else "no",
            },
            {
                "Field": "JSON schema",
                "Value": (
                    "yes"
                    if preset["supports_json_schema"]
                    else "no (fallback: json_object)"
                ),
            },
            {
                "Field": "Requires base URL",
                "Value": "yes" if preset["requires_base_url"] else "no",
            },
            {
                "Field": "Supported task modes",
                "Value": ", ".join(preset["task_modes"]),
            },
        ]
    )
    st.dataframe(info_df, width="stretch", hide_index=True)


def _litellm_settings_tab(bridge: LiteLLMBridge, settings: Settings) -> None:
    st.subheader("Summary")
    pr = _resolve_selected_preset(bridge)
    if pr:
        st.info(
            f"**Selected preset:** `{pr['id']}` ({pr['display_name']})  \n"
            f"**Default model:** `{pr['default_model'] or '—'}`  \n"
            f"**Input cost (per 1M):** `{settings.get('INPUT_TOKEN_COSTS', 'not set')}`  \n"
            f"**Output cost (per 1M):** `{settings.get('OUTPUT_TOKEN_COSTS', 'not set')}`"
        )
    else:
        st.warning("No provider presets are available to select.")

    _litellm_token_settings(settings)
    st.markdown("---")
    _litellm_providers_block(bridge)


# ---------------------------------------------------------------------------
# I/O tab (aligned with Gemini)
# ---------------------------------------------------------------------------


def _litellm_io_tab() -> None:
    st.caption(
        "This I/O flow matches the **✨ Gemini** page: the same *Selected Files* and "
        "*Output Directory* are used. Pick images here, then open **Process** to run "
        "via LiteLLM. For ReOCR, add PAGE-XML to the project on the main **Input** page."
    )
    input_type = st.radio(
        "Select input type",
        ["Directory", "Files"],
        horizontal=True,
        key="litellm_input_type",
    )
    selected_extensions = st.multiselect(
        "Image extensions",
        options=IMAGE_EXT_OPTIONS,
        default=[".jpg", ".jpeg", ".png", ".tiff", ".tif"],
        key="litellm_image_extensions",
    )
    if input_type == "Directory":
        st.write("Search with the chosen extensions in the selected folder.")
        if st.button("Select image directory", key="litellm_select_image_dir_button"):
            selected_dir = pick_directory(initial_dir=get_loaded_workspace_dir())
            if selected_dir and selected_extensions:
                selected_files = [
                    str(f)
                    for f in Path(selected_dir).glob("*")
                    if f.suffix.lower() in selected_extensions
                ]
                if not selected_files:
                    st.warning("No image files found in the selected directory.")
                else:
                    st.session_state.modification_input = {
                        "type": "directory",
                        "path": selected_dir,
                        "files": selected_files,
                        "extensions": selected_extensions,
                    }
                    st.success(f"Found {len(selected_files)} image file(s).")
                    st.rerun()
            elif selected_dir and not selected_extensions:
                st.warning("Select at least one image extension.")
    else:
        if st.button("Select image files", key="litellm_select_image_files_button"):
            file_types = [
                (
                    "Image files",
                    " ".join(f"*{ext}" for ext in selected_extensions),
                ),
                ("All files", "*"),
            ]
            selected_paths = pick_files(
                initial_dir=get_loaded_workspace_dir(),
                filetypes=file_types,
            )
            if selected_paths:
                st.session_state.modification_input = {
                    "type": "files",
                    "files": selected_paths,
                }
                st.success(f"Selected {len(selected_paths)} file(s).")
                st.rerun()

    if "modification_input" not in st.session_state:
        st.info("Select a directory or files to enable the **Process** tab.")
        return

    col1, col2, col3 = st.columns([2, 1, 1])
    with col1:
        st.subheader("Selected files")
    with col2:
        if st.button("🔀 Shuffle", key="litellm_shuffle_files", use_container_width=True):
            st.session_state.modification_input["files"] = shuffle(
                st.session_state.modification_input["files"]
            )
            st.rerun()
    with col3:
        if st.button("🔁 Sort", key="litellm_sort_files_btn", use_container_width=True):
            st.session_state.modification_input["files"] = sorted(
                st.session_state.modification_input["files"],
                key=lambda x: Path(x).name,
            )
            st.rerun()

    mi = st.session_state.modification_input
    if mi["type"] == "directory":
        st.write(f"**Directory:** {mi['path']}")
        st.write(f"**Extensions:** {', '.join(mi['extensions'])}")
        st.write(f"**Total files:** {len(mi['files'])}")
    files_df = pd.DataFrame(
        [
            {
                "Filename": Path(f).name,
                "Extension": Path(f).suffix,
                "Size (KB)": round(Path(f).stat().st_size / 1024, 2) if Path(f).exists() else 0,
                "Full Path": f,
            }
            for f in mi["files"]
        ]
    )
    st.dataframe(files_df, width="stretch")

    st.subheader("Output directory")
    st.write(
        "By default, results are written next to the input images. "
        "Optionally set an output base path (same behavior as on the Gemini page)."
    )
    if st.button("Select output path", key="litellm_select_output_dir_button"):
        selected_paths = pick_files(
            initial_dir=get_loaded_workspace_dir(),
            filetypes=[("All files", "*")],
        )
        if selected_paths:
            st.session_state.modification_dir = selected_paths[0]
            st.rerun()

    if "modification_dir" in st.session_state:
        st.text_input(
            "Selected output path / directory",
            value=st.session_state.modification_dir,
            disabled=True,
            key="litellm_modification_dir_display",
        )
        if st.button("Clear output path", key="litellm_clear_output_dir_button"):
            del st.session_state.modification_dir
            st.rerun()


# ---------------------------------------------------------------------------
# Process tab
# ---------------------------------------------------------------------------


def _litellm_process_tab(bridge: LiteLLMBridge, settings: Settings) -> None:
    st.subheader("Run via LiteLLM")

    preset = _resolve_selected_preset(bridge)
    if not preset:
        st.error("No provider presets. Install LiteLLM and check the registry.")
        return

    selected_files_for_ocr = st.session_state.modification_input["files"]
    loaded_all = [str(p.absolute()) for p in (st.session_state.get("loaded_files") or [])]
    loaded_xmls = [p for p in loaded_all if Path(p).suffix.lower() == ".xml"]

    mode_options: List[str] = ["OCR"]
    if loaded_xmls:
        mode_options.append("ReOCR")
    else:
        st.caption("Load PAGE-XML on the main **Input** page to enable **ReOCR** here.")

    operation_mode = st.radio("Operation", mode_options, horizontal=True, key="litellm_op_mode")
    st.markdown("---")

    task_modes = list(preset["task_modes"])
    _default = "text_correction" if operation_mode == "ReOCR" else "layout_and_text"
    _ix = task_modes.index(_default) if _default in task_modes else 0
    task_mode = st.selectbox(
        "Task mode",
        options=task_modes,
        format_func=lambda k: TASK_MODE_LABELS.get(k, k),
        index=_ix,
        key="litellm_task_mode",
    )

    model_choices = ["(preset default)"] + list(preset["alt_models"])
    model_pick = st.selectbox(
        "Model",
        options=model_choices,
        index=0,
        key="litellm_model_pick",
    )
    custom_model = st.text_input(
        "Custom model (optional; overrides the selection above)",
        value="",
        key="litellm_custom_model",
        placeholder=preset["default_model"] or "provider-specific-model-id",
    )
    effective_model = custom_model or (None if model_pick == "(preset default)" else model_pick)

    c1, c2, c3 = st.columns(3)
    with c1:
        jobs = st.number_input("Concurrent jobs", min_value=1, value=4, key="litellm_jobs")
    with c2:
        cpm = st.number_input("Calls / minute", min_value=1, value=120, key="litellm_cpm")
    with c3:
        json_object = st.checkbox(
            "Force json_object response_format",
            value=not preset["supports_json_schema"],
            key="litellm_json_object",
        )

    c4, c5 = st.columns(2)
    with c4:
        overwrite = st.checkbox("Overwrite existing XML", value=True, key="litellm_overwrite")
    with c5:
        dry_run = st.checkbox("Dry run (no writes)", value=False, key="litellm_dry_run")

    with st.expander("ReOCR: image resolution", expanded=False):
        st.caption(
            "Images are paired from each XML’s directory (or the optional folder below) using "
            "``@imageFilename`` or ``same_names`` (basename match). The file list in **I/O** is for OCR only."
        )
        st.text_input(
            "Image folder (optional)",
            value=st.session_state.get("litellm_reocr_image_folder", ""),
            help="If set, look for page images in this directory when resolving filenames.",
            key="litellm_reocr_image_folder",
        )
        st.checkbox(
            "Match image by XML basename (same_names)",
            value=True,
            key="litellm_reocr_same_names",
        )

    # Validation
    if operation_mode == "OCR" and task_mode in IMAGE_ONLY_MODES and not selected_files_for_ocr:
        st.warning("Select image files in the I/O tab.")
    if operation_mode == "ReOCR" and task_mode in CORRECTION_MODES and not loaded_xmls:
        st.warning("ReOCR with this task mode needs PAGE-XML on the project (Input page).")
    if not preset["configured"]:
        st.error("Configure the preset (API key / base URL) in the Settings tab.")

    can_run = preset["configured"]
    if operation_mode == "OCR" and task_mode in IMAGE_ONLY_MODES:
        can_run = can_run and bool(selected_files_for_ocr)
    if operation_mode == "ReOCR" and task_mode in CORRECTION_MODES:
        can_run = can_run and bool(loaded_xmls)

    # Mixed mode: e.g. layout on OCR with ReOCR tab by mistake
    if operation_mode == "OCR" and task_mode in CORRECTION_MODES:
        st.warning("This task mode is for existing PAGE-XML. Switch operation to **ReOCR** or change task mode.")
        can_run = False
    if operation_mode == "ReOCR" and task_mode in IMAGE_ONLY_MODES:
        st.warning("This task mode is image-only. Switch operation to **OCR** or change task mode.")
        can_run = False

    terminal_container = st.empty()
    terminal_container.text_area(
        "Process terminal",
        value="",
        height=280,
        disabled=True,
        key="litellm_terminal_initial",
    )

    run_label = f"▶ Run {operation_mode} ({task_mode}) via {preset['display_name']}"
    if st.button(run_label, key="litellm_run_process", disabled=not can_run):
        output_queue: queue.Queue = queue.Queue()
        output_buffer = StringIO()
        result_container: dict = {"result": None}

        image_folder = (st.session_state.get("litellm_reocr_image_folder") or "").strip() or None
        same_names = bool(st.session_state.get("litellm_reocr_same_names", True))
        output_dir = st.session_state.get("modification_dir") or None

        def run_process() -> None:
            old_stdout = sys.stdout
            sys.stdout = QueueOutput(output_queue, output_buffer)
            try:
                if operation_mode == "OCR":
                    res = bridge.run_ocr(
                        preset_id=preset["id"],
                        task_mode=task_mode,
                        image_files=selected_files_for_ocr,
                        xml_files=None,
                        model=effective_model,
                        outputdir=output_dir,
                        image_folder=None,
                        same_names=False,
                        jobs=int(jobs),
                        calls_per_minute=int(cpm),
                        json_object=bool(json_object),
                        overwrite=bool(overwrite),
                        dry_run=bool(dry_run),
                    )
                else:
                    # Correction modes resolve images from XML + optional folder;
                    # ``image_files`` is not used by the bridge for this path.
                    res = bridge.run_ocr(
                        preset_id=preset["id"],
                        task_mode=task_mode,
                        image_files=None,
                        xml_files=loaded_xmls,
                        model=effective_model,
                        outputdir=output_dir,
                        image_folder=image_folder,
                        same_names=same_names,
                        jobs=int(jobs),
                        calls_per_minute=int(cpm),
                        json_object=bool(json_object),
                        overwrite=bool(overwrite),
                        dry_run=bool(dry_run),
                    )
            except Exception as exc:
                res = {"success": False, "output": str(exc), "usage": []}
            finally:
                sys.stdout.flush()
                sys.stdout = old_stdout
            ag = {"prompt_tokens": 0, "candidates_tokens": 0, "total_tokens": 0}
            for meta in res.get("usage", []) or []:
                if isinstance(meta, dict):
                    ag["prompt_tokens"] += int(meta.get("prompt_token_count", 0) or 0)
                    ag["candidates_tokens"] += int(meta.get("candidates_token_count", 0) or 0)
                    ag["total_tokens"] += int(meta.get("total_token_count", 0) or 0)
            result_container["result"] = {
                "success": res.get("success", False),
                "output": res.get("output", ""),
                "aggregated_usage": ag,
                "written": res.get("written", []),
            }

        with st.spinner(
            f"Running {operation_mode} via {preset['display_name']}...", show_time=True
        ):
            t = threading.Thread(target=run_process)
            t.start()
            while t.is_alive():
                update_terminal_display(output_queue, output_buffer, terminal_container)
                time.sleep(0.1)
            t.join()

        result = result_container["result"]
        ptype = f"LiteLLM {operation_mode}"
        process_result(
            result, output_buffer, terminal_container, "", settings, process_type=ptype
        )

        if result and result.get("written"):
            st.success(f"Wrote {len(result['written'])} file(s).")
            with st.expander("Written files"):
                st.write(result["written"])

        with st.expander("Token usage report", expanded=True):
            st.code(
                calculate_token_costs(
                    result.get("aggregated_usage") if result else None, settings
                ),
                language="text",
            )

        st.download_button(
            label="Download terminal output",
            data=output_buffer.getvalue(),
            file_name="litellm_terminal_output.txt",
            mime="text/plain",
            key="litellm_download_terminal",
        )


# ---------------------------------------------------------------------------
# Entry
# ---------------------------------------------------------------------------


def show_litellm(bridge: LiteLLMBridge) -> None:
    st.title("🧩 LiteLLM")
    st.write(
        "OCR and PAGE-XML task modes through any **LiteLLM**-routable provider. "
        "Use the same **I/O** pattern as the Gemini page: set files in **📁 I/O**, then run in **Process**."
    )
    settings = Settings()

    avail = bridge.is_available()
    if not avail["success"]:
        st.error(avail["output"])
        st.info("After `pip install litellm`, reload the app to enable this page.")
        return

    tab_names = ["⚙️ Settings", "📁 I/O"]
    if "modification_input" in st.session_state:
        tab_names.append("🔬 Process")
    tabs = st.tabs(tab_names)

    with tabs[0]:
        _litellm_settings_tab(bridge, settings)
    with tabs[1]:
        _litellm_io_tab()

    if "🔬 Process" in tab_names:
        with tabs[tab_names.index("🔬 Process")]:
            _litellm_process_tab(bridge, settings)
