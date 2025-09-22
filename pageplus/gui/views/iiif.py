import streamlit as st
from pathlib import Path
import pandas as pd

from pageplus.gui.utils.picker import pick_directory

def show_iiif_downloader(cli_bridge):
    """Display the IIIF downloader page."""
    st.title("📑 IIIF")

    tab_names = ["Download Images", "Inspect Resources"]
    tabs = st.tabs(tab_names)

    with tabs[0]:  # Download Images
        st.subheader("Download all images from a manifest")

        # --- STATE MANAGEMENT FOR DIR PICKER ---
        if 'iiif_dir_selected' in st.session_state:
            st.session_state.output_dir_iiif = st.session_state.iiif_dir_selected
            del st.session_state.iiif_dir_selected

        manifest_url_dl = st.text_input(
            "IIIF Manifest URL",
            placeholder="Enter the URL of the IIIF manifest",
            key="manifest_url_dl"
        )

        output_dir = st.text_input(
            "Output Directory",
            placeholder="e.g., /path/to/save/images",
            key="output_dir_iiif"
        )

        if st.button("Select Directory", key="select_dir_iiif"):
            selected_dir = pick_directory()
            if selected_dir:
                st.session_state.iiif_dir_selected = selected_dir
                st.rerun()

        page_range = st.text_input(
            "Page Range (optional)",
            placeholder="e.g., 1-5, 7, 9-12",
            key="page_range_iiif"
        )

        col1, col2 = st.columns(2)
        with col1:
            filename_strategy = st.selectbox(
                "Filename Strategy",
                options=["label", "id", "index"],
                index=0,
                key="filename_strategy_iiif",
                help="Determines how downloaded files are named. 'label' uses the manifest label, 'id' uses the last part of the image URL, and 'index' uses a sequential number."
            )
        with col2:
            keep_original_size = st.checkbox("Keep original size", value=True, key="keep_size_iiif")

        if filename_strategy == "index":
            prefix = st.text_input(
                "Filename Prefix (optional)",
                placeholder="e.g., manuscript-"
            )
            leading_zeros = st.number_input(
                "Number of Leading Zeros for Filename",
                min_value=0,
                max_value=10,
                value=4
            )
        else:
            prefix = ""
            leading_zeros = 4

        if not keep_original_size:
            max_dim = st.number_input("Max Dimension", min_value=0, value=2500, key="max_dim_iiif")
            min_dim = st.number_input("Min Dimension", min_value=0, value=1000, key="min_dim_iiif")
        else:
            max_dim = None
            min_dim = None

        if st.button("Download Images"):
            if not manifest_url_dl:
                st.warning("Please enter a manifest URL.")
            elif not output_dir:
                st.warning("Please select an output directory.")
            else:
                with st.spinner("Downloading images..."):
                    result = cli_bridge.download_manifest(
                        manifest_url_dl,
                        Path(output_dir),
                        prefix,
                        leading_zeros,
                        page_range,
                        filename_strategy,
                        keep_original_size,
                        max_dim,
                        min_dim,
                    )
                if result["success"]:
                    st.success(f"Images downloaded successfully to {output_dir}!")
                else:
                    st.error(result["output"])

    with tabs[1]:  # Inspect Resources
        st.subheader("Inspect image resources in a manifest")

        if 'iiif_resources_df' not in st.session_state:
            st.session_state.iiif_resources_df = pd.DataFrame()

        manifest_url_inspect = st.text_input(
            "IIIF Manifest URL",
            placeholder="Enter the URL of the IIIF manifest",
            key="manifest_url_inspect"
        )

        if st.button("Get Resources"):
            if not manifest_url_inspect:
                st.warning("Please enter a manifest URL.")
            else:
                with st.spinner("Fetching resources..."):
                    result = cli_bridge.get_resources(manifest_url_inspect)

                if result["success"]:
                    st.success("Successfully fetched resources.")
                    st.session_state.iiif_resources_df = pd.DataFrame(result["output"])
                else:
                    st.error(result["output"])
                    st.session_state.iiif_resources_df = pd.DataFrame()

        if not st.session_state.iiif_resources_df.empty:
            st.dataframe(st.session_state.iiif_resources_df)
