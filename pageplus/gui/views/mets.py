import re
from pathlib import Path

import streamlit as st

from pageplus.gui.cli_bridges.mets import MetsBridge
from pageplus.gui.utils.picker import pick_directory, pick_files
from pageplus.gui.views.load_files import get_loaded_workspace_dir


def show_mets(bridge: MetsBridge) -> None:
    """Show METS view."""
    # --- STATE MANAGEMENT FOR FILE/DIR PICKERS ---
    if 'mets_dir_selected' in st.session_state:
        st.session_state[st.session_state.mets_dir_key] = st.session_state.mets_dir_selected
        del st.session_state.mets_dir_selected
        del st.session_state.mets_dir_key

    if 'mets_file_selected' in st.session_state:
        st.session_state.mets_file_show = st.session_state.mets_file_selected
        st.session_state.mets_file_download = st.session_state.mets_file_selected
        st.session_state.output_dir_download = str(Path(st.session_state.mets_file_selected).parent)
        del st.session_state.mets_file_selected

    st.title("🏛️ METS")

    st.info("""
    The Metadata Encoding and Transmission Standard (METS) is a standard for encoding descriptive, administrative, and structural metadata regarding
 objects within a digital library, expressed using XML.""")

    tab1, tab2, tab3 = st.tabs(["Show FileGrps", "Download", "Fetch"])

    with tab1:
        st.header("📂 Show FileGrps")
        show_filegrps_form(bridge)

    with tab2:
        st.header("⬇️ Download Files")
        download_form(bridge)

    with tab3:
        st.header("🌐 Fetch METS Files")

        st.text_input("Output directory", key="output_dir_fetch")
        if st.button("Select Directory", key="select_dir_fetch"):
            selected_dir = pick_directory(initial_dir=get_loaded_workspace_dir())
            if selected_dir:
                st.session_state.mets_dir_selected = selected_dir
                st.session_state.mets_dir_key = 'output_dir_fetch'
                st.rerun()

        fetch_tab1, fetch_tab2 = st.tabs(["From OAI-PMH Endpoint", "From URL"])
        with fetch_tab1:
            st.subheader("📥 From OAI-PMH Endpoint")
            oai_form(bridge)
        with fetch_tab2:
            st.subheader("🔗 From URL")
            url_form(bridge)


def show_filegrps_form(bridge: MetsBridge):
    """Show the form for inspecting fileGrps."""

    st.text_input("Path to METS XML file", key="mets_file_show")
    if st.button("Select File", key="select_mets_show"):
        selected_files = pick_files(initial_dir=get_loaded_workspace_dir(), filetypes=[("XML files", "*.xml")])
        if selected_files:
            st.session_state.mets_file_selected = selected_files[0]
            st.rerun()

    with st.form("show_filegrps_form"):
        strict_show = st.checkbox("Strict parsing", key="strict_show", help="Do not allow parsing of unknown attributes and structures.")
        verbose_show = st.checkbox("Verbose output", key="verbose_show", help="Print warnings to the terminal.")
        submitted = st.form_submit_button("Inspect FileGrps")

        if submitted:
            mets_file_show = st.session_state.get("mets_file_show")
            if not mets_file_show or not Path(mets_file_show).exists():
                st.warning("Please provide a valid METS file path.")
            else:
                with st.spinner("Inspecting file groups..."):
                    result = bridge.show_filegrps(mets_file_show, strict_show, verbose_show)
                    if result["success"]:
                        st.success("Successfully inspected file groups.")
                        if result["output"]:
                            st.dataframe(result["output"])
                        else:
                            st.info("No file groups found in the METS file.")
                    else:
                        st.error(result["output"])


def download_form(bridge: MetsBridge):
    """Show the form for downloading files."""
    st.text_input("Path to METS XML file", key="mets_file_download")
    if st.button("Select File", key="select_mets_download"):
        selected_files = pick_files(initial_dir=get_loaded_workspace_dir(), filetypes=[("XML files", "*.xml")])
        if selected_files:
            st.session_state.mets_file_selected = selected_files[0]
            st.rerun()

    st.text_input("Output directory", key="output_dir_download")
    if st.button("Select Directory", key="select_dir_download"):
        selected_dir = pick_directory(initial_dir=get_loaded_workspace_dir())
        if selected_dir:
            st.session_state.mets_dir_selected = selected_dir
            st.session_state.mets_dir_key = "output_dir_download"
            st.rerun()

    with st.form("download_form"):
        st.markdown("##### Filters")
        tag = st.text_input("Filter by USE or ID tag (optional)", key="mets_download_tag")
        nametag = st.text_input("Filename tag (optional, default: href)", help="Use the original filename or the USE or ID tag for filename.")
        selection_str = st.text_input("Filter by document number (e.g., 1, 2, 4)")

        st.markdown("##### Options")
        col_opts1, col_opts2, col_opts3, col_opts4 = st.columns(4)
        with col_opts1:
            strict_download = st.checkbox("Strict parsing", key="strict_download")
        with col_opts2:
            verbose_download = st.checkbox("Verbose output", key="verbose_download")
        with col_opts3:
            skip_existing_download = st.checkbox("Skip existing files", value=True, key="skip_existing_mets", help="Skip images/files if they already exist on disk.")
        with col_opts4:
            batch_size = st.number_input(
                "Batch Size",
                min_value=1,
                max_value=50,
                value=25,
                key="batch_size_mets",
                help="Number of files to download in parallel"
            )

        submitted = st.form_submit_button("Download")

        if submitted:
            if st.session_state.mets_file_download and Path(st.session_state.mets_file_download).exists() and st.session_state.output_dir_download:
                try:
                    selection = [int(s.strip()) for s in selection_str.split(',')] if selection_str else None
                    tags = [t.strip() for t in tag.split(',')] if tag else [tag.strip()]

                    for idx, tag_item in enumerate(tags):
                        st.write(f"**Processing tag: {tag_item} ({idx + 1}/{len(tags)})**")

                        # Create progress containers
                        progress_container = st.container()
                        with progress_container:
                            st.write("**Download Progress**")
                            progress_bar = st.progress(0)
                            status_text = st.empty()
                            stats_text = st.empty()

                        # Define progress callback
                        def update_progress(completed, total, successful, failed, exists):
                            if total > 0:
                                progress = completed / total
                                progress_bar.progress(progress)
                                status_text.text(f"Downloaded {completed} of {total} files")
                                stats_text.text(f"✅ Success: {successful} | 📁 Exists: {exists} | ❌ Failed: {failed}")

                        # Start download
                        result = bridge.download(
                            mets=st.session_state.mets_file_download,
                            strict=strict_download,
                            verbose=verbose_download,
                            tag=tag_item,
                            nametag=nametag,
                            selection=selection,
                            outputdir=Path(st.session_state.output_dir_download),
                            batch_size=batch_size,
                            skip_existing=skip_existing_download,
                            progress_callback=update_progress
                        )

                        if result["success"]:
                            progress_bar.progress(1.0)
                            stats = result.get("stats", {})
                            st.success(f"✅ {result['output']}")
                            if stats:
                                col1, col2, col3, col4 = st.columns(4)
                                with col1:
                                    st.metric("Total", stats.get('total', 0))
                                with col2:
                                    st.metric("Downloaded", stats.get('successful', 0))
                                with col3:
                                    st.metric("Already Exists", stats.get('exists', 0))
                                with col4:
                                    st.metric("Failed", stats.get('failed', 0))
                        else:
                            error_msg = result.get("output", "An error occurred")
                            st.error(f"❌ {error_msg if isinstance(error_msg, str) else str(error_msg)}")

                    st.info(f"📄 Download statistics saved to {Path(st.session_state.output_dir_download) / 'info.txt'}")

                except ValueError:
                    st.error("Invalid format for 'Filter by document number'. Please use comma-separated numbers (e.g., 1, 2, 4).")
            else:
                st.warning("Please provide a valid METS file path and an output directory.")


def oai_form(bridge: MetsBridge):
    """Show the form for fetching METS from OAI-PMH."""
    with st.form("oai_form"):
        base_url = st.text_input("OAI Base URL", placeholder="e.g. https://www.example.de/oai")
        identifier = st.text_input("Identifier", placeholder="e.g. 12311123")
        metadata_prefix = st.text_input("Metadata Prefix", value="mets")
        token = st.text_input("Bearer Token (Optional)", type="password", help="Enter a bearer token if the OAI endpoint requires authorization.")
        submitted = st.form_submit_button("Fetch METS")

        if submitted:
            if not base_url or not identifier:
                st.error("Please provide both OAI Base URL and Identifier.")
            elif not st.session_state.get("output_dir_fetch"):
                st.error("Please provide an output directory.")
            else:
                with st.spinner("Fetching METS file..."):
                    output_dir = Path(st.session_state.output_dir_fetch)
                    result = bridge.get_oai(base_url, identifier, output_dir, metadata_prefix, token)
                    if result["success"]:
                        st.success(result["output"])
                        st.session_state.last_downloaded_mets = result['output'].split(': ')[-1]
                    else:
                        st.error(result["output"])


def url_form(bridge: MetsBridge):
    """Show the form for fetching METS from URL."""
    st.text_input("URL to METS XML file", key="mets_url_input")

    with st.form("url_form"):

        submitted = st.form_submit_button("Download")

        if submitted:
            if not st.session_state.mets_url_input:
                st.error("Please provide a URL.")
            elif not st.session_state.get("output_dir_fetch"):
                st.error("Please provide an output directory.")
            else:
                with st.spinner("Downloading from URL...", show_time=True):
                    result = bridge.get_url(st.session_state.mets_url_input, Path(st.session_state.output_dir_fetch))
                if result["success"]:
                    st.session_state.mets_success_message = "METS XML downloaded successfully."

                    # --- AUTO-POPULATE OTHER TABS ---
                    if result.get("output") and isinstance(result["output"], str):
                        match = re.search(r"Downloaded METS XML to: (.+)", result["output"])
                        if match:
                            new_mets_path = match.group(1).strip()
                            st.session_state.mets_file_show = new_mets_path
                            st.session_state.mets_file_download = new_mets_path
                            st.session_state.mets_file_repair = new_mets_path
                    st.rerun()
                else:
                    error_msg = result.get("output", "An error occurred")
                    st.error(error_msg if isinstance(error_msg, str) else str(error_msg))
