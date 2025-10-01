import re
from pathlib import Path

import streamlit as st
import pandas as pd

from pageplus.gui.cli_bridges.mets import MetsBridge
from pageplus.gui.utils.picker import pick_directory, pick_files
from pageplus.gui.views.load_files import get_loaded_workspace_dir


def show_mets(bridge: MetsBridge) -> None:
    """Show METS view."""
    st.title("📚 METS")

    # --- SHOW PERSISTENT SUCCESS MESSAGE ---
    if 'mets_success_message' in st.session_state:
        st.success(st.session_state.mets_success_message)
        del st.session_state.mets_success_message

    # --- STATE MANAGEMENT FOR FILE/DIR PICKERS ---
    if 'mets_dir_selected' in st.session_state:
        st.session_state[st.session_state.mets_dir_key] = st.session_state.mets_dir_selected
        del st.session_state.mets_dir_selected
        del st.session_state.mets_dir_key

    if 'mets_file_selected' in st.session_state:
        selected_path = st.session_state.mets_file_selected
        # When a file is selected in one tab, populate the path in all relevant tabs
        st.session_state.mets_file_show = selected_path
        st.session_state.mets_file_download = selected_path
        st.session_state.mets_file_repair = selected_path

        # Also auto-populate the output directory in the download tab
        st.session_state.output_dir_download = str(Path(selected_path).parent)

        del st.session_state.mets_file_selected

    # --- UI TABS ---
    tab_names = ["From URL", "From OAI", "Inspect File", "Download Files", "Repair File"]
    tabs = st.tabs(tab_names)

    # --- TAB 1: Get from URL ---
    with tabs[0]:
        st.subheader("Download METS from URL")
        url = st.text_input("URL to METS XML file", key="mets_url_input")
        output_dir_url = st.text_input("Output directory", key="mets_output_dir_url")

        if st.button("Select Directory", key="select_dir_url"):
            selected_dir = pick_directory(initial_dir=get_loaded_workspace_dir())
            if selected_dir:
                st.session_state.mets_dir_selected = selected_dir
                st.session_state.mets_dir_key = "mets_output_dir_url"
                st.rerun()

        if st.button("Download", key="download_url_button"):
            if url and output_dir_url:
                with st.spinner("Downloading from URL...", show_time=True):
                    result = bridge.get_url(url, Path(output_dir_url))
                if result["success"]:
                    st.session_state.mets_success_message = "METS XML downloaded successfully."

                    # --- AUTO-POPULATE OTHER TABS ---
                    match = re.search(r"Downloaded METS XML to: (.+)", result["output"])
                    if match:
                        new_mets_path = match.group(1).strip()
                        st.session_state.mets_file_show = new_mets_path
                        st.session_state.mets_file_download = new_mets_path
                        st.session_state.mets_file_repair = new_mets_path
                    st.rerun()
                else:
                    st.error(result["output"])
            else:
                st.warning("Please provide a URL and an output directory.")

    # --- TAB 2: Get from OAI ---
    with tabs[1]:
        st.subheader("Download METS from OAI Endpoint")
        base_url = st.text_input("Base OAI URL (e.g., https://www.example.de/oai)")
        identifier = st.text_input("OAI identifier (e.g., 12311123)")
        metadata_prefix = st.text_input("Metadata prefix", value="mets")
        output_dir_oai = st.text_input("Output directory", key="mets_output_dir_oai")

        if st.button("Select Directory", key="select_dir_oai"):
            selected_dir = pick_directory(initial_dir=get_loaded_workspace_dir())
            if selected_dir:
                st.session_state.mets_dir_selected = selected_dir
                st.session_state.mets_dir_key = "mets_output_dir_oai"
                st.rerun()

        if st.button("Download", key="download_oai_button"):
            if base_url and identifier and output_dir_oai:
                with st.spinner("Downloading from OAI...", show_time=True):
                    result = bridge.get_oai(base_url, identifier, Path(output_dir_oai), metadata_prefix)
                if result["success"]:
                    st.session_state.mets_success_message = "METS XML downloaded successfully."

                    # --- AUTO-POPULATE OTHER TABS ---
                    match = re.search(r"Saved METS XML to: (.+)", result["output"])
                    if match:
                        new_mets_path = match.group(1).strip()
                        st.session_state.mets_file_show = new_mets_path
                        st.session_state.mets_file_download = new_mets_path
                        st.session_state.mets_file_repair = new_mets_path
                    st.rerun()
                else:
                    st.error(result["output"])
            else:
                st.warning("Please provide all required OAI parameters.")

    # --- TAB 3: Inspect File ---
    with tabs[2]:
        st.subheader("Inspect fileGrp")

        if 'mets_df' not in st.session_state:
            st.session_state.mets_df = pd.DataFrame()

        mets_file_show = st.text_input("Path to METS XML file", key="mets_file_show")

        if st.button("Select File", key="select_mets_show"):
            selected_file = pick_files(initial_dir=get_loaded_workspace_dir(), filetypes=[("XML files", "*.xml")])[0]
            if selected_file:
                st.session_state.mets_file_selected = selected_file
                st.session_state.mets_df = pd.DataFrame()  # Reset dataframe on new file
                st.rerun()

        strict_show = st.checkbox("Strict parsing", key="strict_show", help="Do not allow parsing of unknown attributes and structures.")
        verbose_show = st.checkbox("Verbose output", key="verbose_show", help="Print warnings to the terminal.")

        if st.button("Inspect", key="inspect_button"):
            if mets_file_show and Path(mets_file_show).exists():
                with st.spinner("Inspecting file groups...", show_time=True):
                    result = bridge.show_filegrps(mets_file_show, strict_show, verbose_show)
                if result["success"]:
                    st.success("Successfully inspected file groups.")
                    st.session_state.mets_df = result["output"]
                else:
                    st.error(result["output"])
            else:
                st.warning("Please provide a valid METS file path.")

        if not st.session_state.mets_df.empty:
            st.dataframe(
                st.session_state.mets_df,
                on_select="rerun",
                selection_mode="multi-row",
                key="mets_filegrp_selection"
            )
            # --- HANDLE SELECTION ---
            selection = st.session_state.get("mets_filegrp_selection", {}).get("selection", {}).get("rows", [])
            if selection:
                selected_rows = st.session_state.mets_df.iloc[selection]
                tags = []
                for _, row in selected_rows.iterrows():
                    if row["USE"]:
                        tags.append(row["USE"])
                    if row["ID"]:
                        tags.append(row["ID"])

                # Join unique tags
                unique_tags = sorted(list(set(tags)))
                st.session_state.mets_download_tag = ", ".join(unique_tags)
                st.info(f"Selected tags for download: `{st.session_state.mets_download_tag}`")

    # --- TAB 4: Download Files ---
    with tabs[3]:
        st.subheader("Download Files Referenced in a METS File")
        mets_file_download = st.text_input("Path to METS XML file", key="mets_file_download")
        if st.button("Select File", key="select_mets_download"):
            selected_file = pick_files(initial_dir=get_loaded_workspace_dir(), filetypes=[("XML files", "*.xml")])[0]
            if selected_file:
                st.session_state.mets_file_selected = selected_file
                st.rerun()

        output_dir_download = st.text_input("Output directory", key="output_dir_download")
        if st.button("Select Directory", key="select_dir_download"):
            selected_dir = pick_directory(initial_dir=get_loaded_workspace_dir())
            if selected_dir:
                st.session_state.mets_dir_selected = selected_dir
                st.session_state.mets_dir_key = "output_dir_download"
                st.rerun()

        st.markdown("##### Filters")
        tag = st.text_input("Filter by USE or ID tag (optional)", key="mets_download_tag")
        nametag = st.text_input("Filename tag (optional, default: href)", help="Use the original filename or the USE or ID tag for filename.")
        selection_str = st.text_input("Filter by document number (e.g., 1, 2, 4)")

        st.markdown("##### Options")
        strict_download = st.checkbox("Strict parsing", key="strict_download")
        verbose_download = st.checkbox("Verbose output", key="verbose_download")

        if st.button("Download", key="download_files_button"):
            if mets_file_download and Path(mets_file_download).exists() and output_dir_download:
                try:
                    selection = [int(s.strip()) for s in selection_str.split(',')] if selection_str else None
                    tags = [t.strip() for t in tag.split(',')] if tag else [tag.strip()]
                    for idx, tag in enumerate(tags):
                        with st.spinner(f"Downloading files for tag: {tag} ({idx + 1}/{len(tags)})...", show_time=True):
                            result = bridge.download(
                                mets=mets_file_download,
                                strict=strict_download,
                                verbose=verbose_download,
                                tag=tag,
                                nametag=nametag,
                                selection=selection,
                                outputdir=Path(output_dir_download)
                            )
                    if result["success"]:
                        st.success("Files downloaded successfully.")
                    else:
                        st.error(result["output"])
                except ValueError:
                    st.error("Invalid format for 'Filter by document number'. Please use comma-separated numbers (e.g., 1, 2, 4).")
            else:
                st.warning("Please provide a valid METS file path and an output directory.")

    # --- TAB 5: Repair File ---
    with tabs[4]:
        st.subheader("Repair METS File Namespace")
        mets_file_repair = st.text_input("Path to METS XML file to repair", key="mets_file_repair")
        if st.button("Select File", key="select_mets_repair"):
            selected_file = pick_files(initial_dir=get_loaded_workspace_dir(), filetypes=[("XML files", "*.xml")])[0]
            if selected_file:
                st.session_state.mets_file_selected = selected_file
                st.rerun()

        st.warning("This will overwrite the file in place.")
        if st.button("Repair", key="repair_button"):
            if mets_file_repair and Path(mets_file_repair).exists():
                with st.spinner("Repairing METS file...", show_time=True):
                    result = bridge.repair(mets_file_repair)
                if result["success"]:
                    st.success("METS file repaired successfully.")
                else:
                    st.error(result["output"])
            else:
                st.warning("Please provide a valid METS file path.")
