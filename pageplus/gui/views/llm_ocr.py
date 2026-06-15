"""Streamlit view for the unified **🤖 LLM-OCR** tab.

A single place to configure and run OCR through any provider — local / SSH
(OpenAI-compatible), OpenAI-compatible APIs, Gemini-compatible APIs, or the
scaffolded local ``transformers`` backend — driven by **rich presets** that
bundle provider + model + processing step + prompt + output mapping + task mode
+ task level + tag filters.

Tabs:
    * **⚙️ Settings** — provider presets + credentials, custom endpoints + SSH
      controls, and token-cost settings for the usage report.
    * **🧬 Presets** — define/edit the rich LLM-OCR presets.
    * **📁 I/O** — the same image queue as the Gemini/LiteLLM pages.
    * **🔬 Process** — pick a provider + preset, set task level and "Process only
      Tags", then run OCR (fresh) or ReOCR (correction) with a live terminal and
      token report.
"""
from __future__ import annotations

import os
import queue
import sys
import threading
import time
from io import StringIO
from pathlib import Path
from typing import List, Optional

import pandas as pd
import streamlit as st

from pageplus.gui.cli_bridges.llm_ocr import LLMOcrBridge
from pageplus.gui.utils.picker import pick_directory, pick_files
from pageplus.gui.utils.settings import Settings
from pageplus.gui.utils.terminal_stream import (
    QueueOutput,
    calculate_token_costs,
    process_result,
    update_terminal_display,
)
from pageplus.gui.views.load_files import get_loaded_workspace_dir
from pageplus.utils.fs import shuffle
from pageplus.utils.llm.ocr_presets import (
    MAPPING_CHOICES,
    STEP_DEFINITIONS,
    STEP_NAMES,
    TASK_LEVELS,
    step_family,
)
from pageplus.utils.llm.pipeline_store import EXECUTION_MODES

IMAGE_EXT_OPTIONS = [".jpg", ".jpeg", ".png", ".bmp", ".tiff", ".tif"]

TASK_MODE_OPTIONS = [
    "layout_only", "layout_and_text", "layout_correction", "text_only", "text_correction",
]


# ---------------------------------------------------------------------------
# Provider resolution
# ---------------------------------------------------------------------------

def _resolve_selected_provider(bridge: LLMOcrBridge) -> Optional[dict]:
    res = bridge.list_providers(only_configured=False)
    providers: List[dict] = res.get("providers", [])
    if not providers:
        return None
    by_id = {p["id"]: p for p in providers}
    if "llmocr_selected_provider" not in st.session_state:
        default = next((p["id"] for p in providers if p["configured"]), providers[0]["id"])
        st.session_state.llmocr_selected_provider = default
    if st.session_state.llmocr_selected_provider not in by_id:
        st.session_state.llmocr_selected_provider = providers[0]["id"]
    return by_id[st.session_state.llmocr_selected_provider]


# ---------------------------------------------------------------------------
# Settings tab
# ---------------------------------------------------------------------------

def _token_settings(settings: Settings) -> None:
    with st.expander("💰 Token costs (for usage report & estimates)", expanded=False):
        new_in = st.text_input(
            "Input token cost (per 1M tokens)",
            value=settings.get("INPUT_TOKEN_COSTS", ""),
            placeholder="e.g., 0.5",
            key="llmocr_input_token_cost",
        )
        if st.button("Set input token cost", key="llmocr_set_input_cost"):
            settings.set("INPUT_TOKEN_COSTS", new_in.strip())
            st.success("Updated.")
        new_out = st.text_input(
            "Output token cost (per 1M tokens)",
            value=settings.get("OUTPUT_TOKEN_COSTS", ""),
            placeholder="e.g., 1.5",
            key="llmocr_output_token_cost",
        )
        if st.button("Set output token cost", key="llmocr_set_output_cost"):
            settings.set("OUTPUT_TOKEN_COSTS", new_out.strip())
            st.success("Updated.")


def _providers_block(bridge: LLMOcrBridge) -> None:
    st.subheader("Providers")
    st.caption(
        "Local/SSH (OpenAI-compatible), OpenAI-compatible, Gemini-compatible "
        "(via LiteLLM), and the scaffolded local `transformers` backend. "
        "Credentials live in your PagePlus `.env`."
    )
    only_configured = st.checkbox("Show only configured", value=False, key="llmocr_only_configured")
    if st.button("🔄 Refresh", key="llmocr_refresh_providers"):
        st.rerun()

    result = bridge.list_providers(only_configured=only_configured)
    providers: List[dict] = result.get("providers", [])
    if not providers:
        st.info("No providers available.")
        return

    st.dataframe(pd.DataFrame([
        {
            "id": p["id"], "Name": p["display_name"], "Prefix": p["litellm_prefix"],
            "Default model": p["default_model"] or "-",
            "Configured?": "✅" if p["configured"] else "❌",
        }
        for p in providers
    ]), width="stretch")

    ids = [p["id"] for p in providers]
    by_id = {p["id"]: p for p in providers}
    _resolve_selected_provider(bridge)
    labels = [f"{p['display_name']} ({p['id']})" + ("  ✅" if p["configured"] else "  ❌") for p in providers]
    current = ids.index(st.session_state.llmocr_selected_provider) \
        if st.session_state.llmocr_selected_provider in ids else 0
    chosen = st.selectbox("Selected provider", options=list(range(len(ids))),
                          format_func=lambda i: labels[i], index=current, key="llmocr_provider_select")
    st.session_state.llmocr_selected_provider = ids[chosen]
    provider = by_id[ids[chosen]]

    with st.expander("🔐 Credentials", expanded=not provider["configured"]):
        col_key, col_base = st.columns(2)
        with col_key:
            if provider["env_api_key"]:
                new_key = st.text_input(f"API key (env: {provider['env_api_key']})", value="",
                                        type="password", key=f"llmocr_key_{provider['id']}")
                if st.button("Save API key", key=f"llmocr_save_key_{provider['id']}"):
                    res = bridge.save_api_key(provider["id"], new_key)
                    (st.success if res["success"] else st.error)(res["output"])
                    st.rerun()
            else:
                st.caption("No API-key env var for this provider.")
        with col_base:
            if provider["env_api_base"] is not None:
                new_base = st.text_input(f"API base URL (env: {provider['env_api_base']})", value="",
                                         placeholder=provider["api_base_hint"] or "https://...",
                                         key=f"llmocr_base_{provider['id']}")
                if st.button("Save base URL", key=f"llmocr_save_base_{provider['id']}"):
                    res = bridge.save_api_base(provider["id"], new_base)
                    (st.success if res["success"] else st.error)(res["output"])
                    st.rerun()
            else:
                st.caption("No custom base URL for this provider.")


def _custom_endpoints_block(bridge: LLMOcrBridge) -> None:
    st.subheader("🔌 Custom endpoints (local / SSH / OpenAI-compatible)")
    try:
        from pageplus.utils.llm.provider_registry import register_custom_endpoints
        register_custom_endpoints()
    except Exception:
        pass

    endpoints = bridge.list_custom_endpoints().get("endpoints", [])
    if endpoints:
        st.dataframe(pd.DataFrame([
            {
                "Name": ep["name"], "Provider": ep.get("provider", "openai"),
                "Base URL": ep["base_url"], "Model": ep["default_model"] or "—",
                "SSH": "🔒" if ep["ssh_enabled"] else "—",
            }
            for ep in endpoints
        ]), width="stretch", hide_index=True)
        provider_opts = ["openai", "gemini", "ollama", "ollama_chat", "curl"]
        for ep in endpoints:
            with st.expander(f"⚙️ {ep['name']}", expanded=False):
                # --- Discover models from the server (exact installed names) ---
                mk = f"llmocr_eps_models_{ep['name']}"
                if st.button("🔍 List models from server", key=f"llmocr_listmodels_{ep['name']}",
                             help="Query the endpoint (Ollama /api/tags or OpenAI /v1/models) "
                                  "so you can save the exact installed name (incl. tag)."):
                    r = bridge.list_endpoint_models(ep["name"])
                    st.session_state[mk] = r.get("models", [])
                    (st.success if r["success"] else st.error)(r["output"])
                fetched = st.session_state.get(mk)
                if fetched:
                    only_vision = st.checkbox("Vision-capable only", value=True,
                                              key=f"llmocr_visonly_{ep['name']}")
                    names = [m["name"] for m in fetched if (m.get("vision") or not only_vision)]
                    if not names:
                        st.info("No matching models (try unchecking 'Vision-capable only').")
                    else:
                        pick_default = st.selectbox(
                            "Set default model", names, key=f"llmocr_pickdef_{ep['name']}",
                            index=names.index(ep.get("default_model")) if ep.get("default_model") in names else 0)
                        pick_alts = st.multiselect(
                            "Models to keep (binding options)", names,
                            default=[n for n in (ep.get("alt_models") or []) if n in names] or names,
                            key=f"llmocr_pickalts_{ep['name']}")
                        if st.button("💾 Save selected models", key=f"llmocr_savemodels_{ep['name']}"):
                            res = bridge.save_custom_endpoint(
                                name=ep["name"], base_url=ep["base_url"],
                                api_key=ep.get("api_key", "EMPTY"), default_model=pick_default,
                                alt_models=pick_alts, ssh_enabled=ep.get("ssh_enabled", False),
                                ssh_command=ep.get("ssh_command", ""),
                                provider=ep.get("provider", "openai"),
                                image_key=ep.get("image_key", "image") or "image",
                                prompt_key=ep.get("prompt_key", "prompt") or "prompt",
                            )
                            (st.success if res["success"] else st.error)(res["output"])
                            if res["success"]:
                                st.rerun()
                    st.markdown("---")

                with st.form(f"llmocr_edit_ep_{ep['name']}"):
                    st.caption("Edit this endpoint (name is fixed; saving overwrites it).")
                    ec1, ec2 = st.columns(2)
                    with ec1:
                        e_key = st.text_input("API Key", value=ep.get("api_key", "EMPTY"),
                                              key=f"llmocr_ed_key_{ep['name']}")
                        e_provider = st.selectbox(
                            "Provider", provider_opts,
                            index=provider_opts.index(ep.get("provider", "openai"))
                            if ep.get("provider", "openai") in provider_opts else 0,
                            key=f"llmocr_ed_prov_{ep['name']}")
                        e_model = st.text_input("Default model", value=ep.get("default_model", "") or "",
                                                key=f"llmocr_ed_model_{ep['name']}")
                        e_image_key = st.text_input("Image JSON Key (Curl only)", value=ep.get("image_key", "image") or "image",
                                                    key=f"llmocr_ed_imgkey_{ep['name']}")
                    with ec2:
                        e_url = st.text_input("Base URL (or full POST URL for Curl)", value=ep.get("base_url", ""),
                                              key=f"llmocr_ed_url_{ep['name']}")
                        e_alt = st.text_input("Alt models (comma-separated)",
                                              value=", ".join(ep.get("alt_models", []) or []),
                                              key=f"llmocr_ed_alt_{ep['name']}")
                        e_ssh = st.text_input("SSH command (optional)",
                                              value=ep.get("ssh_command", "") or "",
                                              key=f"llmocr_ed_ssh_{ep['name']}")
                        e_prompt_key = st.text_input("Prompt JSON Key (Curl only)", value=ep.get("prompt_key", "prompt") or "prompt",
                                                     key=f"llmocr_ed_prkey_{ep['name']}")
                    e_save = st.form_submit_button("💾 Update endpoint", use_container_width=True)
                if e_save:
                    if not e_url.strip():
                        st.error("Base URL is required.")
                    else:
                        u = e_url.strip()
                        if not u.startswith("http"):
                            u = f"http://{u}"
                        if e_provider == "openai" and not u.rstrip("/").endswith("/v1"):
                            u = u.rstrip("/") + "/v1"
                        res = bridge.save_custom_endpoint(
                            name=ep["name"], base_url=u, api_key=e_key.strip() or "EMPTY",
                            default_model=e_model.strip(),
                            alt_models=[m.strip() for m in e_alt.split(",") if m.strip()],
                            ssh_enabled=bool(e_ssh.strip()), ssh_command=e_ssh.strip(),
                            provider=e_provider,
                            image_key=e_image_key.strip() or "image",
                            prompt_key=e_prompt_key.strip() or "prompt",
                        )
                        (st.success if res["success"] else st.error)(res["output"])
                        if res["success"]:
                            st.rerun()

                if ep["ssh_enabled"]:
                    status = bridge.tunnel_status(ep["name"]).get("status", "error")
                    if status == "running":
                        st.success("🟢 Tunnel running")
                        if st.button("⏹ Stop tunnel", key=f"llmocr_stoptun_{ep['name']}"):
                            res = bridge.stop_ssh_tunnel(ep["name"])
                            (st.success if res["success"] else st.error)(res["output"])
                            st.rerun()
                    else:
                        if st.button("▶ Start tunnel", key=f"llmocr_starttun_{ep['name']}"):
                            with st.spinner("Starting SSH tunnel…"):
                                res = bridge.start_ssh_tunnel(ep["name"])
                            (st.success if res["success"] else st.error)(res["output"])
                            st.rerun()
                if st.button("🗑 Delete", key=f"llmocr_delep_{ep['name']}"):
                    res = bridge.delete_custom_endpoint(ep["name"])
                    (st.success if res["success"] else st.error)(res["output"])
                    st.rerun()
    else:
        st.info("No custom endpoints saved yet.")

    with st.expander("➕ Add / update endpoint", expanded=not endpoints):
        with st.form("llmocr_add_endpoint", clear_on_submit=True):
            c1, c2 = st.columns(2)
            with c1:
                name = st.text_input("Name", placeholder="e.g. spark")
                key = st.text_input("API Key", value="EMPTY")
                provider = st.selectbox("Provider", ["openai", "gemini", "ollama", "ollama_chat", "curl"], index=0,
                                        help="openai = OpenAI-compatible (needs /v1). ollama_chat uses "
                                             "Ollama's /api/chat. curl = Custom HTTP POST REST.")
                image_key = st.text_input("Image JSON Key (Curl only)", value="image")
            with c2:
                url = st.text_input("Base URL (or full POST URL for Curl)", placeholder="localhost:8000")
                model = st.text_input("Default model", value="")
                ssh_cmd = st.text_input("SSH command (optional)",
                                        placeholder="ssh -N -L 8000:localhost:8000 host")
                prompt_key = st.text_input("Prompt JSON Key (Curl only)", value="prompt")
            submitted = st.form_submit_button("💾 Save endpoint", use_container_width=True)
        if submitted:
            if not name.strip() or not url.strip():
                st.error("Name and base URL are required.")
            else:
                u = url.strip()
                if not u.startswith("http"):
                    u = f"http://{u}"
                if provider == "openai" and not u.rstrip("/").endswith("/v1"):
                    u = u.rstrip("/") + "/v1"
                res = bridge.save_custom_endpoint(
                    name=name.strip(), base_url=u, api_key=key.strip() or "EMPTY",
                    default_model=model.strip(), ssh_enabled=bool(ssh_cmd.strip()),
                    ssh_command=ssh_cmd.strip(), provider=provider,
                    image_key=image_key.strip() or "image",
                    prompt_key=prompt_key.strip() or "prompt",
                )
                (st.success if res["success"] else st.error)(res["output"])
                if res["success"]:
                    st.rerun()


def _settings_tab(bridge: LLMOcrBridge, settings: Settings) -> None:
    _token_settings(settings)
    st.markdown("---")
    _providers_block(bridge)
    st.markdown("---")
    _custom_endpoints_block(bridge)


# ---------------------------------------------------------------------------
# Presets tab
# ---------------------------------------------------------------------------

def preset_bindings(preset: Optional[dict]) -> List[dict]:
    """Return a preset's provider/model bindings, migrating the old single pin."""
    if not preset:
        return []
    bindings = preset.get("bindings")
    if isinstance(bindings, list) and bindings:
        return [{"provider": b.get("provider", ""), "model": b.get("model", "")}
                for b in bindings if b.get("provider")]
    pinned = (preset.get("provider_preset") or "").strip()
    if pinned:
        return [{"provider": pinned, "model": (preset.get("model") or "").strip()}]
    return []


def _binding_label(binding: dict, configured_by_id: dict) -> str:
    prov = binding.get("provider", "")
    cfg = configured_by_id.get(prov, False)
    return f"{prov} / {binding.get('model') or 'default'}" + ("" if cfg else "  ❌")


def _bindings_editor(existing: Optional[dict], providers: List[dict]) -> List[dict]:
    """Editable list of provider/model bindings stored per edited preset."""
    sel = (existing or {}).get("id", "➕ New preset")
    if st.session_state.get("llmocr_pb_for") != sel:
        st.session_state.llmocr_pb_for = sel
        st.session_state.llmocr_pb = preset_bindings(existing)

    bindings: List[dict] = st.session_state.llmocr_pb
    cfg_by_id = {p["id"]: p["configured"] for p in providers}
    prov_by_id = {p["id"]: p for p in providers}

    st.markdown("**Provider / model bindings** — the allowed provider+model "
                "combinations this preset can run on (Process tab picks among these).")
    if not bindings:
        st.info("No bindings yet. Add at least one below so this preset is usable.")
    for i, b in enumerate(list(bindings)):
        cols = st.columns([8, 1])
        with cols[0]:
            st.markdown(f"{i + 1}. {_binding_label(b, cfg_by_id)}")
        with cols[1]:
            if st.button("🗑", key=f"llmocr_pb_rm_{i}", help="Remove binding"):
                bindings.pop(i)
                st.rerun()

    ac1, ac2, ac3 = st.columns([3, 3, 1])
    with ac1:
        prov_ids = [p["id"] for p in providers]
        add_prov = st.selectbox(
            "Add provider", prov_ids,
            format_func=lambda i: f"{prov_by_id[i]['display_name']}"
            + ("" if prov_by_id[i]["configured"] else " ❌"),
            key="llmocr_pb_add_prov") if prov_ids else None
    with ac2:
        model_opts = ["(provider default)"] + (prov_by_id.get(add_prov, {}).get("alt_models", []) if add_prov else [])
        if prov_by_id.get(add_prov, {}).get("default_model"):
            dm = prov_by_id[add_prov]["default_model"]
            if dm not in model_opts:
                model_opts.insert(1, dm)
        add_model_pick = st.selectbox("Add model", model_opts, key="llmocr_pb_add_model")
        add_model_custom = st.text_input("…or custom model", value="", key="llmocr_pb_add_model_custom")
    with ac3:
        st.write("")
        st.write("")
        if st.button("➕", key="llmocr_pb_add", help="Add binding") and add_prov:
            model = add_model_custom.strip() or ("" if add_model_pick == "(provider default)" else add_model_pick)
            if not any(b["provider"] == add_prov and b.get("model", "") == model for b in bindings):
                bindings.append({"provider": add_prov, "model": model})
                st.rerun()
    return bindings


def _presets_tab(bridge: LLMOcrBridge) -> None:
    st.subheader("🧬 LLM-OCR presets")
    st.caption(
        "A preset bundles step + task mode + level + prompt + output mapping + "
        "tag filters **and the provider/model bindings** it may run on. The "
        "Process tab can only pick provider/model from a preset's bindings."
    )

    presets = bridge.list_ocr_presets().get("presets", [])
    st.dataframe(pd.DataFrame([
        {
            "id": p["id"], "Name": p["name"], "Step": p.get("step", ""),
            "Task mode": p.get("task_mode", ""), "Level": p.get("task_level", ""),
            "Mapping": p.get("mapping", ""),
            "Bindings": len(preset_bindings(p)),
        }
        for p in presets
    ]), width="stretch", hide_index=True)

    options = ["➕ New preset"] + [p["id"] for p in presets]
    chosen = st.selectbox("Edit preset", options=options, key="llmocr_edit_preset_pick")
    existing = next((p for p in presets if p["id"] == chosen), None) if chosen != "➕ New preset" else None

    providers = bridge.list_providers().get("providers", [])

    # Bindings editor lives outside the form (needs its own add/remove buttons).
    bindings = _bindings_editor(existing, providers)
    st.markdown("---")

    with st.form("llmocr_preset_form"):
        c1, c2 = st.columns(2)
        with c1:
            pid = st.text_input("Preset id", value=(existing or {}).get("id", ""),
                                disabled=existing is not None,
                                placeholder="unique-id")
            name = st.text_input("Name", value=(existing or {}).get("name", ""))
            step = st.selectbox("Step", STEP_NAMES,
                                index=STEP_NAMES.index((existing or {}).get("step", "All-in-One"))
                                if (existing or {}).get("step", "All-in-One") in STEP_NAMES else 0)
            sd = STEP_DEFINITIONS[step]
            task_mode = st.selectbox(
                "Task mode", TASK_MODE_OPTIONS,
                index=TASK_MODE_OPTIONS.index((existing or {}).get("task_mode", sd["task_mode"]))
                if (existing or {}).get("task_mode", sd["task_mode"]) in TASK_MODE_OPTIONS else 0)
        with c2:
            task_level = st.selectbox(
                "Task level", TASK_LEVELS,
                index=TASK_LEVELS.index((existing or {}).get("task_level", sd["task_level"]))
                if (existing or {}).get("task_level", sd["task_level"]) in TASK_LEVELS else 0)
            mapping = st.selectbox(
                "Output mapping", MAPPING_CHOICES,
                index=MAPPING_CHOICES.index((existing or {}).get("mapping", sd["mapping"]))
                if (existing or {}).get("mapping", sd["mapping"]) in MAPPING_CHOICES else 0)

        system_prompt = st.text_area("System prompt (blank = built-in template)",
                                     value=(existing or {}).get("system_prompt", ""), height=160)
        user_prompt = st.text_area("User prompt (blank = built-in template)",
                                   value=(existing or {}).get("user_prompt", ""), height=80)
        tags_str = st.text_input("Default tags (comma-separated, optional)",
                                 value=", ".join(((existing or {}).get("filters") or {}).get("tags", [])))
        tag_regex = st.checkbox("Treat tags as regex",
                                value=bool(((existing or {}).get("filters") or {}).get("tag_regex", False)))
        save = st.form_submit_button("💾 Save preset", use_container_width=True)

    if save:
        if not pid.strip() or not name.strip():
            st.error("Preset id and name are required.")
        elif not bindings:
            st.error("Add at least one provider/model binding before saving.")
        else:
            preset = {
                "id": pid.strip(), "name": name.strip(),
                "description": (existing or {}).get("description", ""),
                "bindings": bindings,
                "step": step, "task_mode": task_mode, "task_level": task_level,
                "mapping": mapping, "system_prompt": system_prompt,
                "user_prompt": user_prompt,
                "filters": {
                    "tags": [t.strip() for t in tags_str.split(",") if t.strip()],
                    "tag_regex": bool(tag_regex),
                },
            }
            res = bridge.save_ocr_preset(preset)
            if res["success"]:
                st.session_state.pop("llmocr_pb_for", None)
            (st.success if res["success"] else st.error)(res["output"])
            if res["success"]:
                st.rerun()

    if existing is not None:
        if st.button("🗑 Delete preset", key="llmocr_delete_preset"):
            res = bridge.delete_ocr_preset(existing["id"])
            (st.success if res["success"] else st.error)(res["output"])
            if res["success"]:
                st.rerun()


# ---------------------------------------------------------------------------
# I/O tab (shared image queue)
# ---------------------------------------------------------------------------

def _io_tab() -> None:
    st.caption(
        "Same I/O flow as Gemini/LiteLLM: pick images here (used for fresh OCR), "
        "and load PAGE-XML on the main **Input** page for ReOCR (correction steps)."
    )
    input_type = st.radio("Input type", ["Directory", "Files"], horizontal=True, key="llmocr_input_type")
    exts = st.multiselect("Image extensions", IMAGE_EXT_OPTIONS,
                          default=[".jpg", ".jpeg", ".png", ".tiff", ".tif"], key="llmocr_exts")
    if input_type == "Directory":
        if st.button("Select image directory", key="llmocr_pick_dir"):
            d = pick_directory(initial_dir=get_loaded_workspace_dir())
            if d and exts:
                files = [str(f) for f in Path(d).glob("*") if f.suffix.lower() in exts]
                if files:
                    st.session_state.modification_input = {
                        "type": "directory", "path": d, "files": files, "extensions": exts,
                    }
                    st.success(f"Found {len(files)} image file(s).")
                    st.rerun()
                else:
                    st.warning("No matching images in directory.")
    else:
        if st.button("Select image files", key="llmocr_pick_files"):
            paths = pick_files(initial_dir=get_loaded_workspace_dir(),
                               filetypes=[("Image files", " ".join(f"*{e}" for e in exts)), ("All files", "*")])
            if paths:
                st.session_state.modification_input = {"type": "files", "files": paths}
                st.success(f"Selected {len(paths)} file(s).")
                st.rerun()

    if "modification_input" not in st.session_state:
        st.info("Select images to enable fresh OCR in **Process**.")
        return

    c1, c2, c3 = st.columns([2, 1, 1])
    with c1:
        st.subheader("Selected files")
    with c2:
        if st.button("🔀 Shuffle", key="llmocr_shuffle", use_container_width=True):
            st.session_state.modification_input["files"] = shuffle(st.session_state.modification_input["files"])
            st.rerun()
    with c3:
        if st.button("🔁 Sort", key="llmocr_sort", use_container_width=True):
            st.session_state.modification_input["files"] = sorted(
                st.session_state.modification_input["files"], key=lambda x: Path(x).name)
            st.rerun()

    mi = st.session_state.modification_input
    st.dataframe(pd.DataFrame([
        {"Filename": Path(f).name, "Extension": Path(f).suffix, "Full Path": f}
        for f in mi["files"]
    ]), width="stretch")

    st.subheader("Output directory (optional)")
    if st.button("Select output path", key="llmocr_pick_out"):
        paths = pick_files(initial_dir=get_loaded_workspace_dir(), filetypes=[("All files", "*")])
        if paths:
            st.session_state.modification_dir = paths[0]
            st.rerun()
    if "modification_dir" in st.session_state:
        st.text_input("Output path", value=st.session_state.modification_dir, disabled=True,
                      key="llmocr_out_display")
        if st.button("Clear output path", key="llmocr_clear_out"):
            del st.session_state.modification_dir
            st.rerun()


# ---------------------------------------------------------------------------
# Process tab — pipeline builder
# ---------------------------------------------------------------------------

def _task_summary(task: dict) -> str:
    bits = [
        f"**{task.get('step')}**",
        f"`{task.get('task_mode')}`",
        task.get("task_level", "Page"),
        f"{task.get('provider_id')}/{task.get('model') or 'default'}",
        f"preset=`{task.get('preset_id') or '—'}`",
    ]
    tags = task.get("tags") or []
    if tags:
        bits.append(f"tags={tags}{' (regex)' if task.get('tag_regex') else ''}")
    fam = step_family(task.get("step", "All-in-One"))
    bits.append("🆕 fresh" if fam == "fresh" else "✏️ correction")
    return " · ".join(bits)


def _pipeline_load_save(bridge: LLMOcrBridge) -> None:
    saved = bridge.list_pipelines().get("pipelines", [])
    c1, c2 = st.columns([3, 1])
    with c1:
        options = ["—"] + [p["id"] for p in saved]
        labels = {p["id"]: f"{p['name']} ({len(p.get('tasks', []))} tasks)" for p in saved}
        pick = st.selectbox("Load saved pipeline", options,
                            format_func=lambda i: labels.get(i, i), key="llmocr_pl_load_pick")
    with c2:
        st.write("")
        st.write("")
        if st.button("📥 Load", key="llmocr_pl_load", disabled=pick == "—", use_container_width=True):
            res = bridge.get_pipeline(pick)
            if res["success"]:
                pl = res["pipeline"]
                st.session_state.llmocr_tasks = list(pl.get("tasks", []))
                st.session_state.llmocr_exec_mode = pl.get("execution_mode", "stepwise")
                st.success(f"Loaded '{pl['name']}'.")
                st.rerun()
            else:
                st.error(res["output"])

    if st.session_state.get("llmocr_tasks"):
        with st.expander("💾 Save current pipeline", expanded=False):
            sc1, sc2 = st.columns(2)
            with sc1:
                pid = st.text_input("Pipeline id", key="llmocr_pl_save_id", placeholder="my-pipeline")
            with sc2:
                pname = st.text_input("Name", key="llmocr_pl_save_name", placeholder="My Pipeline")
            if st.button("💾 Save pipeline", key="llmocr_pl_save"):
                if not pid.strip() or not pname.strip():
                    st.error("Pipeline id and name are required.")
                else:
                    res = bridge.save_pipeline({
                        "id": pid.strip(), "name": pname.strip(), "description": "",
                        "execution_mode": st.session_state.get("llmocr_exec_mode", "stepwise"),
                        "tasks": st.session_state.llmocr_tasks,
                    })
                    (st.success if res["success"] else st.error)(res["output"])
            if pick != "—" and st.button("🗑 Delete saved pipeline", key="llmocr_pl_delete"):
                res = bridge.delete_pipeline(pick)
                (st.success if res["success"] else st.error)(res["output"])
                st.rerun()


def _task_list_editor() -> None:
    tasks: list = st.session_state.get("llmocr_tasks", [])
    if not tasks:
        st.info("No tasks yet — add one below.")
        return
    st.markdown("**Current pipeline**")
    for i, task in enumerate(tasks):
        cols = st.columns([8, 1, 1, 1])
        with cols[0]:
            st.markdown(f"{i + 1}. {_task_summary(task)}")
        with cols[1]:
            if st.button("⬆", key=f"llmocr_up_{i}", disabled=i == 0, help="Move up"):
                tasks[i - 1], tasks[i] = tasks[i], tasks[i - 1]
                st.rerun()
        with cols[2]:
            if st.button("⬇", key=f"llmocr_down_{i}", disabled=i == len(tasks) - 1, help="Move down"):
                tasks[i + 1], tasks[i] = tasks[i], tasks[i + 1]
                st.rerun()
        with cols[3]:
            if st.button("🗑", key=f"llmocr_rm_{i}", help="Remove"):
                tasks.pop(i)
                st.rerun()


def _add_task_form(bridge: LLMOcrBridge, presets: List[dict]) -> None:
    configured_by_id = {p["id"]: p["configured"]
                        for p in bridge.list_providers().get("providers", [])}

    # Only presets that actually carry provider/model bindings are usable here.
    bound_presets = [p for p in presets if preset_bindings(p)]
    if not bound_presets:
        st.warning("No preset has provider/model bindings yet. Open **🧬 Presets** and "
                   "add at least one provider/model binding to a preset.")
        return

    with st.expander("➕ Add task", expanded=not st.session_state.get("llmocr_tasks")):
        # 1 · Step — and the bound presets for it constrain everything below.
        steps = [s for s in STEP_NAMES if any(p.get("step") == s for p in bound_presets)]
        step = st.selectbox("1 · Step", steps, key="llmocr_add_step")
        step_presets = [p for p in bound_presets if p.get("step") == step]

        c1, c2 = st.columns(2)
        with c1:
            # 2 · Task mode — only modes some bound preset for this step provides.
            modes = sorted({p.get("task_mode") for p in step_presets if p.get("task_mode")})
            task_mode = st.selectbox("2 · Task mode", modes, key="llmocr_add_mode")
        mode_presets = [p for p in step_presets if p.get("task_mode") == task_mode]
        with c2:
            # 3 · Level — only levels available for the chosen step + mode.
            levels = [lv for lv in TASK_LEVELS
                      if any(p.get("task_level") == lv for p in mode_presets)]
            task_level = st.selectbox("3 · Level", levels, key="llmocr_add_level")
        level_presets = [p for p in mode_presets if p.get("task_level") == task_level]

        # 4 · Preset (prompt + mapping) — those fitting step + mode + level.
        if not level_presets:
            st.warning("No preset fits this Step + mode + level. Adjust the choices.")
            return
        preset_ids = [p["id"] for p in level_presets]
        preset_by_id = {p["id"]: p for p in level_presets}
        preset_id = st.selectbox(
            "4 · Prompt + mapping (preset)", preset_ids,
            format_func=lambda i: f"{preset_by_id[i]['name']}  ·  map=`{preset_by_id[i].get('mapping')}`",
            key="llmocr_add_preset")
        chosen_preset = preset_by_id[preset_id]

        # 5 · Provider + model — ONLY the preset's declared bindings.
        only_cfg = st.checkbox("Only configured", value=True, key="llmocr_add_only_cfg")
        bindings = preset_bindings(chosen_preset)
        if only_cfg:
            bindings = [b for b in bindings if configured_by_id.get(b["provider"], False)] or bindings
        b_labels = [_binding_label(b, configured_by_id) for b in bindings]
        b_idx = st.selectbox("5 · Provider / model (from preset)", list(range(len(bindings))),
                             format_func=lambda i: b_labels[i], key="llmocr_add_binding")
        binding = bindings[b_idx]

        tags_str = st.text_input("Process only tags (optional, comma-separated)",
                                 value=", ".join((chosen_preset.get("filters") or {}).get("tags", [])),
                                 key="llmocr_add_tags")
        tag_regex = st.checkbox("Tags are regex",
                                value=bool((chosen_preset.get("filters") or {}).get("tag_regex", False)),
                                key="llmocr_add_tag_regex")

        if st.button("➕ Add task to pipeline", key="llmocr_add_btn", use_container_width=True):
            st.session_state.setdefault("llmocr_tasks", [])
            st.session_state.llmocr_tasks.append({
                "step": step, "task_mode": task_mode, "task_level": task_level,
                "provider_id": binding["provider"], "model": binding.get("model", ""),
                "preset_id": preset_id,
                "tags": [t.strip() for t in tags_str.split(",") if t.strip()],
                "tag_regex": bool(tag_regex),
            })
            st.rerun()


def _process_tab(bridge: LLMOcrBridge, settings: Settings) -> None:
    presets = bridge.list_ocr_presets().get("presets", [])
    if not presets:
        st.error("No presets defined. Create one in **🧬 Presets** first.")
        return

    st.caption(
        "Build a pipeline of tasks. Each task: pick **step → task mode → level**, "
        "then a matching **provider/model**, then the **preset** (prompt + mapping). "
        "Add the same step multiple times (e.g. different tags). Tasks run in order; "
        "a fresh step turns images into XML and later correction steps refine it."
    )

    _pipeline_load_save(bridge)
    st.markdown("---")
    _task_list_editor()
    _add_task_form(bridge, presets)

    tasks: list = st.session_state.get("llmocr_tasks", [])
    if not tasks:
        return

    st.markdown("---")
    st.subheader("Run")
    exec_mode = st.radio(
        "Execution mode",
        EXECUTION_MODES,
        index=EXECUTION_MODES.index(st.session_state.get("llmocr_exec_mode", "stepwise")),
        format_func=lambda m: "Run stepwise (step → all pages)" if m == "stepwise"
        else "Run pagewise (page → all steps)",
        horizontal=True, key="llmocr_exec_mode")

    c3, c4 = st.columns(2)
    with c3:
        jobs = st.number_input("Concurrent jobs / pages", min_value=1, value=4, key="llmocr_jobs")
    with c4:
        cpm = st.number_input("Calls / minute", min_value=1, value=120, key="llmocr_cpm")
    c6, c7, c8 = st.columns(3)
    with c6:
        overwrite = st.checkbox("Overwrite XML", value=True, key="llmocr_overwrite")
    with c7:
        dry_run = st.checkbox("Dry run (no writes)", value=False, key="llmocr_dry_run")
    with c8:
        rescale = st.checkbox("Rescale image", value=True, key="llmocr_rescale")
    max_size = st.number_input("Max image dimension (px)", min_value=100, max_value=10000, value=1000,
                               disabled=not rescale, key="llmocr_max_size")
    verbose = st.checkbox("🐞 Verbose LLM debug (log the exact upstream request: URL + payload)",
                          value=False, key="llmocr_verbose",
                          help="Prints LiteLLM's raw request/curl to the terminal so you can see "
                               "exactly what is called. Takes effect on the next run.")

    first_family = step_family(tasks[0].get("step", "All-in-One"))
    image_files = (st.session_state.get("modification_input") or {}).get("files")
    loaded_all = [str(p.absolute()) for p in (st.session_state.get("loaded_files") or [])]
    xml_files = [p for p in loaded_all if Path(p).suffix.lower() == ".xml"]

    image_folder = None
    same_names = True
    with st.expander("Image resolution for correction steps", expanded=False):
        image_folder = st.text_input("Image folder (optional, defaults to image/XML dir)",
                                     value="", key="llmocr_image_folder") or None
        same_names = st.checkbox("Match image by XML basename", value=True, key="llmocr_same_names")

    can_run = True
    if first_family == "fresh":
        if not image_files:
            st.warning("First step is *fresh* — select image files in **📁 I/O**.")
            can_run = False
    else:
        if not xml_files:
            st.warning("First step is *correction* — load PAGE-XML on the main **Input** page.")
            can_run = False

    terminal_container = st.empty()
    terminal_container.text_area("Process terminal", value="", height=260, disabled=True,
                                 key="llmocr_terminal_init")

    if st.button(f"▶ Run pipeline ({exec_mode}, {len(tasks)} task(s))",
                 key="llmocr_run", disabled=not can_run):
        output_queue: queue.Queue = queue.Queue()
        output_buffer = StringIO()
        result_container: dict = {"result": None}
        output_dir = st.session_state.get("modification_dir") or None
        os.environ["PAGEPLUS_LLM_DEBUG"] = "1" if verbose else "0"

        def run_process() -> None:
            old_stdout = sys.stdout
            sys.stdout = QueueOutput(output_queue, output_buffer)
            try:
                res = bridge.run_pipeline(
                    tasks=tasks,
                    execution_mode=exec_mode,
                    image_files=image_files,
                    xml_files=xml_files,
                    outputdir=output_dir,
                    image_folder=image_folder,
                    same_names=same_names,
                    jobs=int(jobs),
                    calls_per_minute=int(cpm),
                    overwrite=bool(overwrite),
                    dry_run=bool(dry_run),
                    max_image_size=int(max_size) if rescale else None,
                )
            except Exception as exc:  # pragma: no cover - defensive
                res = {"success": False, "output": str(exc), "usage": []}
            finally:
                sys.stdout.flush()
                sys.stdout = old_stdout
            result_container["result"] = {
                "success": res.get("success", False),
                "output": res.get("output", ""),
                "aggregated_usage": res.get("aggregated_usage",
                                            {"prompt_tokens": 0, "candidates_tokens": 0, "total_tokens": 0}),
                "written": res.get("written", []),
            }

        with st.spinner(f"Running pipeline ({exec_mode})…", show_time=True):
            t = threading.Thread(target=run_process)
            t.start()
            while t.is_alive():
                update_terminal_display(output_queue, output_buffer, terminal_container)
                time.sleep(0.1)
            t.join()

        result = result_container["result"]
        process_result(result, output_buffer, terminal_container, "", settings,
                       process_type="LLM-OCR pipeline")
        if result and result.get("written"):
            st.success(f"Wrote {len(result['written'])} file(s).")
            with st.expander("Written files"):
                st.write(result["written"])
        with st.expander("Token usage report", expanded=True):
            st.code(calculate_token_costs(result.get("aggregated_usage") if result else None, settings),
                    language="text")
        st.download_button("Download terminal output", data=output_buffer.getvalue(),
                           file_name="llm_ocr_terminal.txt", mime="text/plain",
                           key="llmocr_download_terminal")


# ---------------------------------------------------------------------------
# Entry
# ---------------------------------------------------------------------------

def show_llm_ocr(bridge: LLMOcrBridge) -> None:
    st.title("🤖 LLM-OCR")
    st.write(
        "Unified OCR across local/SSH, OpenAI-compatible, Gemini-compatible, and "
        "(scaffolded) local transformer models — driven by rich presets."
    )
    settings = Settings()

    avail = bridge.is_available()
    if not avail["success"]:
        st.error(avail["output"])
        return

    try:
        from pageplus.utils.llm.provider_registry import register_custom_endpoints
        register_custom_endpoints()
    except Exception:
        pass

    tab_names = ["⚙️ Settings", "🧬 Presets", "📁 I/O", "🔬 Process"]
    tabs = st.tabs(tab_names)
    with tabs[0]:
        _settings_tab(bridge, settings)
    with tabs[1]:
        _presets_tab(bridge)
    with tabs[2]:
        _io_tab()
    with tabs[3]:
        _process_tab(bridge, settings)
