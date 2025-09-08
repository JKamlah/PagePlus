import json
from pathlib import Path

import streamlit as st

from pageplus.gui.cli_bridges.mets import MetsBridge
from pageplus.gui.utils.picker import pick_directory, pick_file


def show_mets(bridge: MetsBridge) -> None:
    """Show METS view."""
    st.title("📚 METS")

    # Operation tabs
    tab_names = ["Get URL", "Get OAI", "Show FileGrps", "Repair", "Download"]
    tabs = st.tabs(tab_names)

    with tabs[0]:  # Get URL
        st.subheader("Download METS from URL")
        url = st.text_input("URL to METS XML file")
        
        output_dir_url = st.text_input("Output directory", key="output_dir_url")
        if st.button("Select Directory", key="select_dir_url"):
            selected_dir = pick_directory()
            if selected_dir:
                st.session_state.output_dir_url = selected_dir
                st.rerun()

        if st.button("Download from URL", key="url_button"):
            if url and output_dir_url:
                with st.spinner("Downloading from URL..."):
                    result = bridge.get_url(url, Path(output_dir_url))
                if result["success"]:
                    st.success("METS XML downloaded successfully from URL.")
                    st.text_area("Output", result["output"], height=200)
                else:
                    st.error(result["output"])
            else:
                st.warning("Please provide a URL and an output directory.")

    with tabs[1]:  # Get OAI
        st.subheader("Download METS from OAI Endpoint")
        base_url = st.text_input("Base OAI URL")
        identifier = st.text_input("OAI identifier")
        metadata_prefix = st.text_input("Metadata prefix", value="mets")
        
        output_dir_oai = st.text_input("Output directory", key="output_dir_oai")
        if st.button("Select Directory", key="select_dir_oai"):
            selected_dir = pick_directory()
            if selected_dir:
                st.session_state.output_dir_oai = selected_dir
                st.rerun()

        if st.button("Download from OAI", key="oai_button"):
            if base_url and identifier and output_dir_oai:
                with st.spinner("Downloading from OAI..."):
                    result = bridge.get_oai(base_url, identifier, Path(output_dir_oai), metadata_prefix)
                if result["success"]:
                    st.success("METS XML downloaded successfully from OAI.")
                    st.text_area("Output", result["output"], height=200)
                else:
                    st.error(result["output"])
            else:
                st.warning("Please provide all required OAI parameters.")

    with tabs[2]:  # Show FileGrps
        st.subheader("Show File Groups")
        mets_file_show = st.text_input("METS file path", key="mets_file_show")
        if st.button("Select File", key="select_mets_show"):
            selected_file = pick_file()
            if selected_file:
                st.session_state.mets_file_show = selected_file
                st.rerun()

        strict_show = st.checkbox("Strict parsing", key="strict_show")
        verbose_show = st.checkbox("Verbose output", key="verbose_show")

        if st.button("Show", key="show_button"):
            if mets_file_show and Path(mets_file_show).exists():
                with st.spinner("Inspecting file groups..."):
                    result = bridge.show_filegrps(mets_file_show, strict_show, verbose_show)
                if result["success"]:
                    st.text_area("File Groups", result["output"], height=400)
                else:
                    st.error(result["output"])
            else:
                st.warning("Please provide a valid METS file path.")

    with tabs[3]:  # Repair
        st.subheader("Repair METS File")
        mets_file_repair = st.text_input("METS file path", key="mets_file_repair")
        if st.button("Select File", key="select_mets_repair"):
            selected_file = pick_file()
            if selected_file:
                st.session_state.mets_file_repair = selected_file
                st.rerun()

        if st.button("Repair", key="repair_button"):
            if mets_file_repair and Path(mets_file_repair).exists():
                with st.spinner("Repairing METS file..."):
                    result = bridge.repair(mets_file_repair)
                if result["success"]:
                    st.success("METS file repaired successfully.")
                    st.text_area("Output", result["output"], height=200)
                else:
                    st.error(result["output"])
            else:
                st.warning("Please provide a valid METS file path.")

    with tabs[4]:  # Download
        st.subheader("Download Files from METS")
        mets_file_download = st.text_input("METS file path", key="mets_file_download")
        if st.button("Select File", key="select_mets_download"):
            selected_file = pick_file()
            if selected_file:
                st.session_state.mets_file_download = selected_file
                st.rerun()
        
        output_dir_download = st.text_input("Output directory", key="output_dir_download")
        if st.button("Select Directory", key="select_dir_download"):
            selected_dir = pick_directory()
            if selected_dir:
                st.session_state.output_dir_download = selected_dir
                st.rerun()

        tag = st.text_input("Filter by USE or ID tag (optional)")
        nametag = st.text_input("Filename tag (optional)")
        selection_str = st.text_input("Document selection (e.g., 1,2,4, optional)")
        
        strict_download = st.checkbox("Strict parsing", key="strict_download")
        verbose_download = st.checkbox("Verbose output", key="verbose_download")

        if st.button("Download", key="download_button"):
            if mets_file_download and Path(mets_file_download).exists() and output_dir_download:
                selection = [int(s.strip()) for s in selection_str.split(',')] if selection_str else None
                with st.spinner("Downloading files..."):
                    result = bridge.download(
                        mets_file_download,
                        strict_download,
                        verbose_download,
                        tag,
                        nametag,
                        selection,
                        Path(output_dir_download)
                    )
                if result["success"]:
                    st.success("Files downloaded successfully.")
                    st.text_area("Output", result["output"], height=300)
                else:
                    st.error(result["output"])
            else:
                st.warning("Please provide valid METS file path and output directory.")
