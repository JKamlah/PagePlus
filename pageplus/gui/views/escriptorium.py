
import json
import re
from pathlib import Path
from importlib import util

import pandas as pd
import streamlit as st

from pageplus.cli.escriptorium import DataFilter
from pageplus.gui.cli_bridges.escriptorium import EscriptoriumBridge
from pageplus.gui.utils.picker import pick_directory
from pageplus.gui.utils.settings import Settings
from pageplus.utils.converter import parse_page_ranges


def load_escriptorium_pks() -> dict:
    """Load eScriptorium PKs from storage."""
    storage_file = Path(__file__).parent.parent / "storage" / "escriptorium.json"
    if storage_file.exists():
        with open(storage_file, 'r') as f:
            try:
                data = json.load(f)
                # Basic migration from old format
                if "pk" in data and "pks" not in data:
                    migrated_pks = {}
                    for name, values in data["pk"].items():
                        migrated_pks[name] = {
                            "document": {"name": name, "pk": values.get("document")},
                            "transcription": {"name": "", "pk": values.get("transcription")}
                        }
                    data["pks"] = migrated_pks
                    del data["pk"]
                    save_escriptorium_pks(data)
                return data
            except json.JSONDecodeError:
                return {"pks": {}}
    return {"pks": {}}


def save_escriptorium_pks(pks: dict) -> None:
    """Save eScriptorium PKs to storage."""
    storage_file = Path(__file__).parent.parent / "storage" / "escriptorium.json"
    storage_file.parent.mkdir(parents=True, exist_ok=True)
    with open(storage_file, 'w') as f:
        json.dump(pks, f, indent=4)


def show_escriptorium(bridge: EscriptoriumBridge) -> None:
    """Show eScriptorium view."""
    st.title("📜 eScriptorium")

    # Check if escriptorium-connector is installed
    if util.find_spec('escriptorium_connector') is None:
        st.warning("eScriptorium connector is not installed.")
        if st.button("Install eScriptorium Connector"):
            with st.spinner("Installing..."):
                result = bridge.install()
                if result["success"]:
                    st.success("Installation successful! Please restart the application.")
                    st.code(result["output"])
                else:
                    st.error("Installation failed:")
                    st.code(result["output"])
        return

    settings = Settings()

    # Operation tabs
    tab_names = ["Settings", "Find Documents", "Download Documents", "Update Document"]
    tabs = st.tabs(tab_names)

    with tabs[0]:  # Settings
        st.subheader("Settings")

        with st.expander("API Settings", expanded=True):
            base_url = st.text_input(
                "Base URL",
                value=settings.get("ESCRIPTORIUM_BASE_URL", "https://escriptorium.fr"),
            )
            if st.button("Set Base URL", key="set_base_url_button"):
                with st.spinner("Setting Base URL..."):
                    result = bridge.set_base_url(base_url)
                if result["success"]:
                    st.success(result["output"])
                else:
                    st.error(result["output"])

            api_base_url = st.text_input(
                "API Base URL",
                value=settings.get("ESCRIPTORIUM_API_BASE", ""),
            )
            if st.button("Set API Base URL", key="set_api_base_url_button"):
                with st.spinner("Setting API Base URL..."):
                    result = bridge.set_api_base_url(api_base_url)
                if result["success"]:
                    st.success(result["output"])
                else:
                    st.error(result["output"])

            instance_name = st.text_input(
                "Instance Name",
                value=settings.get("ESCRIPTORIUM_INSTANCE_NAME", ""),
            )
            if st.button("Set Instance Name", key="set_instance_name_button"):
                with st.spinner("Setting instance name..."):
                    result = bridge.set_instance_name(instance_name)
                if result["success"]:
                    st.success(result["output"])
                else:
                    st.error(result["output"])

        with st.expander("Credentials"):
            username = st.text_input(
                "Username",
                value=settings.get("ESCRIPTORIUM_USERNAME", ""),
            )
            password = st.text_input(
                "Password",
                value=settings.get("ESCRIPTORIUM_PASSWORD", ""),
                type="password"
            )
            if st.button("Set Credentials", key="set_credentials_button"):
                with st.spinner("Setting credentials..."):
                    result = bridge.set_credentials(username, password)
                if result["success"]:
                    st.success(result["output"])
                else:
                    st.error(result["output"])

        if st.button("Show Current Settings"):
            with st.spinner("Fetching settings..."):
                result = bridge.show_settings()
            if result["success"]:
                st.text_area("Settings", result["output"], height=200)
            else:
                st.error(result["output"])

    with tabs[1]:  # Find Documents
        st.subheader("Find Documents")

        if 'escriptorium_filters' not in st.session_state:
            st.session_state.escriptorium_filters = [{"filter_by": DataFilter.PROJECT.value, "search_term": "."}]

        for i, filter_item in enumerate(st.session_state.escriptorium_filters):
            cols = st.columns([3, 3, 1])
            with cols[0]:
                st.session_state.escriptorium_filters[i]['filter_by'] = st.selectbox(
                    "Filter by",
                    options=[e.value for e in DataFilter],
                    index=[e.value for e in DataFilter].index(filter_item['filter_by']),
                    key=f"filter_by_{i}"
                )
            with cols[1]:
                st.session_state.escriptorium_filters[i]['search_term'] = st.text_input(
                    "Search term (regex)",
                    value=filter_item['search_term'],
                    key=f"search_term_{i}"
                )
            with cols[2]:
                if st.button("➖", key=f"remove_filter_{i}"):
                    st.session_state.escriptorium_filters.pop(i)
                    st.rerun()
        
        if st.button("➕ Add Filter"):
            st.session_state.escriptorium_filters.append({"filter_by": DataFilter.PROJECT.value, "search_term": ""})
            st.rerun()

        case_sensitive = st.checkbox("Case sensitive search")

        if st.button("Find Documents"):
            filters = st.session_state.escriptorium_filters
            filter_by = [item['filter_by'] for item in filters]
            search_term = [item['search_term'] for item in filters]

            with st.spinner("Finding documents..."):
                result = bridge.find_documents(filter_by, search_term, case_sensitive)

            if result["success"]:
                st.session_state.escriptorium_search_results_df = result["table"]
                if 'document_search_results' in st.session_state:
                    del st.session_state['document_search_results']
                if 'selected_transcription' in st.session_state:
                    del st.session_state['selected_transcription']
            else:
                st.session_state.pop('escriptorium_search_results_df', None)
                st.error(result["output"])

        # --- DATAFRAME DISPLAY AND SELECTION LOGIC ---
        if 'escriptorium_search_results_df' in st.session_state:
            df = st.session_state.escriptorium_search_results_df
            st.dataframe(df, on_select="rerun", selection_mode="single-row", key="document_search_results")

            selection = st.session_state.get('document_search_results', {}).get('selection', {}).get('rows', [])
            if selection:
                selected_row = df.iloc[selection[0]]
                doc_pk_str = selected_row['Document (PK)']
                doc_pk_match = re.search(r'\((\d+)\)', doc_pk_str)

                st.session_state.escript_doc_pk_input = int(doc_pk_match.group(1)) if doc_pk_match else None
                st.session_state.escript_doc_name_input = doc_pk_str.split(' (')[0] if doc_pk_match else doc_pk_str
                st.session_state.transcription_options = selected_row['Transcription (PK)']

                # Clear saved PK selection when a new row is selected from dataframe
                st.session_state.saved_pk_selector = ""
            else:
                st.session_state.transcription_options = []

        # --- SET PK UI ---
        with st.expander("Set Document/Transcription PK Manually", expanded=True):
            if "escript_doc_name_input" not in st.session_state:
                st.session_state.escript_doc_name_input = ""
            if "escript_doc_pk_input" not in st.session_state:
                st.session_state.escript_doc_pk_input = None
            if "transcription_options" not in st.session_state:
                st.session_state.transcription_options = []
            if "saved_pk_selector" not in st.session_state:
                st.session_state.saved_pk_selector = ""

            # Load saved configurations
            pks_data = load_escriptorium_pks()
            saved_pks = list(pks_data.get("pks", {}).keys())

            col_load, col_delete = st.columns([3, 1])
            with col_load:
                selected_saved_pk = st.selectbox(
                    "Load Saved PK Configuration",
                    options=[""] + saved_pks,
                    key="saved_pk_selector"
                )
            with col_delete:
                st.write("")  # Spacer
                st.write("")
                if st.button("Delete", disabled=not selected_saved_pk):
                    if selected_saved_pk in pks_data.get("pks", {}):
                        del pks_data["pks"][selected_saved_pk]
                        save_escriptorium_pks(pks_data)
                        st.success(f"Deleted '{selected_saved_pk}'.")
                        st.session_state.saved_pk_selector = ""
                        st.rerun()

            # If a saved PK is selected, populate the fields
            if selected_saved_pk and ('last_saved_pk' not in st.session_state or st.session_state.last_saved_pk != selected_saved_pk):
                st.session_state.last_saved_pk = selected_saved_pk
                selected_data = pks_data["pks"][selected_saved_pk]
                doc_info = selected_data.get("document", {})
                trans_info = selected_data.get("transcription", {})

                st.session_state.escript_doc_name_input = doc_info.get("name", selected_saved_pk)
                st.session_state.escript_doc_pk_input = doc_info.get("pk")
                st.session_state.transcription_options = []  # Can't know options, so use number input
                st.session_state.escript_trans_pk_input = trans_info.get("pk")
                st.rerun()

            col1, col2, col3 = st.columns(3)
            with col1:
                st.text_input("Name", key="escript_doc_name_input")
            with col2:
                st.number_input("Document PK", min_value=1, step=1, key="escript_doc_pk_input")
            with col3:
                if st.session_state.transcription_options:
                    # If options are available from a live search, show dropdown
                    current_trans_pk = st.session_state.get('escript_trans_pk_input')
                    current_trans_str = ""
                    if current_trans_pk:
                        for option in st.session_state.transcription_options:
                            if f"({current_trans_pk})" in option:
                                current_trans_str = option
                                break
                    
                    index = st.session_state.transcription_options.index(current_trans_str) if current_trans_str in st.session_state.transcription_options else 0

                    st.selectbox(
                        "Transcription",
                        options=st.session_state.transcription_options,
                        key="selected_transcription",
                        index=index
                    )
                else:
                    # Otherwise, show number input
                    st.number_input("Transcription PK", min_value=1, step=1, key="escript_trans_pk_input")

            if st.button("Set PKs", key="set_pks_button"):
                entry_name = st.session_state.escript_doc_name_input
                doc_pk = st.session_state.escript_doc_pk_input
                trans_pk = None
                trans_name = ""

                if st.session_state.transcription_options:
                    trans_full_str = st.session_state.selected_transcription
                    trans_pk_match = re.search(r'\((\d+)\)', trans_full_str)
                    trans_pk = int(trans_pk_match.group(1)) if trans_pk_match else None
                    trans_name = trans_full_str.split(' (')[0] if trans_pk_match else trans_full_str
                else:
                    trans_pk = st.session_state.get('escript_trans_pk_input')

                if entry_name and entry_name.strip():
                    pks_data = load_escriptorium_pks()
                    if 'pks' not in pks_data:
                        pks_data['pks'] = {}
                    
                    pks_data['pks'][entry_name] = {
                        "document": {"name": entry_name, "pk": doc_pk},
                        "transcription": {"name": trans_name, "pk": trans_pk}
                    }
                    save_escriptorium_pks(pks_data)
                    st.success(f"Saved configuration '{entry_name}'.")
                    st.session_state.last_saved_pk = None # Allows re-selection
                    st.rerun()
                else:
                    if doc_pk:
                        result_doc = bridge.set_document_pk(doc_pk)
                        if result_doc["success"]:
                            st.success(result_doc["output"])
                        else:
                            st.error(result_doc["output"])
                    if trans_pk:
                        result_trans = bridge.set_transcription_pk(trans_pk)
                        if result_trans["success"]:
                            st.success(result_trans["output"])
                        else:
                            st.error(result_trans["output"])
                    if not doc_pk and not trans_pk:
                        st.warning("No PKs provided to set.")

                st.session_state.escriptorium_name = entry_name
                st.session_state.escriptorium_doc_pk = doc_pk
                st.session_state.escriptorium_trans_pk = trans_pk

    with tabs[2]:  # Download Documents
        st.subheader("Download Documents")

        # --- Selector for Saved PKs ---
        pks_data_download = load_escriptorium_pks()
        saved_pks_download = list(pks_data_download.get("pks", {}).keys())
        selected_pk_to_load = st.selectbox(
            "Load from Saved PKs",
            options=[""] + saved_pks_download,
            key="download_pk_selector"
        )

        if selected_pk_to_load and ('last_download_pk' not in st.session_state or st.session_state.last_download_pk != selected_pk_to_load):
            st.session_state.last_download_pk = selected_pk_to_load
            selected_data = pks_data_download["pks"][selected_pk_to_load]
            doc_info = selected_data.get("document", {})
            trans_info = selected_data.get("transcription", {})

            st.session_state.escriptorium_name = doc_info.get("name", selected_pk_to_load)
            st.session_state.escriptorium_doc_pk = doc_info.get("pk")
            st.session_state.escriptorium_trans_pk = trans_info.get("pk")
            st.rerun()

        # Initialize session state for widgets if not present
        if "escriptorium_doc_pk" not in st.session_state:
            st.session_state.escriptorium_doc_pk = None
        if "escriptorium_trans_pk" not in st.session_state:
            st.session_state.escriptorium_trans_pk = None
        if "escriptorium_name" not in st.session_state:
            st.session_state.escriptorium_name = "MAIN"

        doc_pk = st.number_input("Document PK", min_value=1, step=1, value=st.session_state.get("escriptorium_doc_pk"), key="download_doc_pk")
        trans_pk = st.number_input("Transcription PK", min_value=1, step=1, value=st.session_state.get("escriptorium_trans_pk"), key="download_trans_pk")
        pages_str = st.text_input("Pages (comma-separated, optional)")
        
        cols = st.columns(2)
        with cols[0]:
            load_images = st.checkbox("Download images")
            overwrite_ws = st.checkbox("Overwrite workspace")
        with cols[1]:
            loading = st.checkbox("Load as default workspace")

        col_path, col_btn = st.columns([3, 1])
        with col_path:
            folderpath = st.text_input(
                "Folder path (optional)",
                key="download_folderpath_input",
                value=st.session_state.get("download_folderpath", "")
            )
        with col_btn:
            st.write("")  # Spacer
            st.write("")
            if st.button("Select Directory", key="select_download_dir"):
                selected_dir = pick_directory()
                if selected_dir:
                    st.session_state.download_folderpath = selected_dir
                    st.rerun()

        workspace = st.text_input("Workspace name", value=st.session_state.get("escriptorium_name", ""), key="download_workspace_name")

        if st.button("Download Document"):
            pages = [p.strip() for p in pages_str.split(',')] if pages_str else None
            
            with st.spinner("Downloading document..."):
                result = bridge.load_document(
                    document_pk=doc_pk,
                    transcription_pk=trans_pk,
                    pages=pages,
                    load_images=load_images,
                    folderpath=st.session_state.get("download_folderpath") if st.session_state.get("download_folderpath") else None,
                    workspace=workspace if workspace != "" else None,
                    overwrite_ws=overwrite_ws,
                    loading=loading
                )
            
            if result["success"]:
                st.success("Document downloaded successfully.")
                st.text_area("Output", result["output"], height=300)
            else:
                st.error(result["output"])

    with tabs[3]:  # Update Document
        st.subheader("Update Document")

        # --- Selector for Saved PKs ---
        pks_data_update = load_escriptorium_pks()
        saved_pks_update = list(pks_data_update.get("pks", {}).keys())
        selected_pk_to_update = st.selectbox(
            "Load from Saved PKs",
            options=[""] + saved_pks_update,
            key="update_pk_selector"
        )

        if selected_pk_to_update and ('last_update_pk' not in st.session_state or st.session_state.last_update_pk != selected_pk_to_update):
            st.session_state.last_update_pk = selected_pk_to_update
            selected_data = pks_data_update["pks"][selected_pk_to_update]
            doc_info = selected_data.get("document", {})
            trans_info = selected_data.get("transcription", {})

            st.session_state.escriptorium_name = doc_info.get("name", selected_pk_to_update)
            st.session_state.escriptorium_doc_pk = doc_info.get("pk")
            st.session_state.escriptorium_trans_name = trans_info.get("name")
            st.rerun()
        
        doc_pk_update = st.number_input("Document PK (optional)", min_value=1, step=1, value=st.session_state.get("escriptorium_doc_pk"), key="update_doc_pk")        
        trans_name_update = st.text_input("New transcription name (optional)", value=st.session_state.get("escriptorium_trans_name"))
        pages_update_str = st.text_input("Pages to update (comma-separated, optional)")
        overwrite_update = st.checkbox("Overwrite existing transcription", value=True)

        if st.button("Update Document"):
            pages = [p.strip() for p in pages_update_str.split(',')] if pages_update_str else None

            with st.spinner("Updating document..."):
                result = bridge.update_document(
                    inputs=[str(files.absolute()) for files in st.session_state.loaded_files],
                    document_pk=doc_pk_update,
                    pages=pages,
                    transcription_name=trans_name_update if trans_name_update else None,
                    overwrite=overwrite_update
                )

            if result["success"]:
                st.success("Document updated successfully.")
                st.text_area("Output", result["output"], height=300)
            else:
                st.error(result["output"])
