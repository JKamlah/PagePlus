import json
import re
from pathlib import Path

import streamlit as st


from pageplus.gui.cli_bridges.transkribus import TranskribusBridge
from pageplus.gui.utils.picker import pick_directory, pick_files

from pageplus.gui.utils.settings import Settings
from pageplus.utils.constants import GUI_STORAGE_DIR


def load_transkribus_ids() -> dict:
    """Load Transkribus IDs from storage."""
    storage_file = GUI_STORAGE_DIR / "transkribus.json"
    if storage_file.exists():
        with open(storage_file, 'r') as f:
            try:
                data = json.load(f)
                return data
            except json.JSONDecodeError:
                return {"ids": {}}
    return {"ids": {}}


def save_transkribus_ids(ids: dict) -> None:
    """Save Transkribus IDs to storage."""
    storage_file = GUI_STORAGE_DIR / "transkribus.json"
    storage_file.parent.mkdir(parents=True, exist_ok=True)
    with open(storage_file, 'w') as f:
        json.dump(ids, f, indent=4)


def show_transkribus(bridge: TranskribusBridge):
    st.title("🐇 Transkribus")

    # Check if transkribus_utils is installed
    if not bridge.is_installed():
        st.warning("Transkribus utils are not installed.")
        if st.button("Install Transkribus Utils"):
            with st.spinner("Installing...", show_time=True):
                result = bridge.install()
                if result["success"]:
                    st.success("Installation successful! Please restart the application.")
                    st.code(result["output"])
                else:
                    st.error("Installation failed:")
                    st.code(result["output"])
        return
    else:
        from pageplus.cli.transkribus import DataFilter, PageStatus, Role

    settings = Settings()

    if 'transkribus_search_results_df' not in st.session_state:
        st.session_state.transkribus_search_results_df = None

    tab1, tab2, tab3, tab4 = st.tabs(["Settings", "Find Documents", "Download Document", "Update Document"])

    with tab1:
        st.header("Settings")
        st.subheader("Set API URL")
        url = st.text_input("Transkribus URL", value=settings.get("TRANSKRIBUS_URL", "https://transkribus.eu/TrpServer/rest"), key="transkribus_url")
        if st.button("Set URL"):
            with st.spinner("Setting URL...", show_time=True):
                result = bridge.set_url(url)
                if result["success"]:
                    st.success(result["output"])
                else:
                    st.error(result["output"])

        st.subheader("Set Credentials")
        username = st.text_input("Username", value=settings.get("TRANSKRIBUS_USERNAME", ""), key="transkribus_user")
        password = st.text_input("Password", type="password", value=settings.get("TRANSKRIBUS_PASSWORD", ""), key="transkribus_pass")
        if st.button("Set Credentials"):
            if username and password:
                with st.spinner("Setting credentials...", show_time=True):
                    result = bridge.set_credentials(username, password)
                    if result["success"]:
                        st.success(result["output"])
                    else:
                        st.error(result["output"])
            else:
                st.warning("Please provide both username and password.")

    with tab2:
        st.header("Find Documents")
        st.header("Warning: This feature can be very slow if there are a lot of documents.")
        with st.form("find_documents_form"):
            filters = {
                "Collection": st.text_input("Filter by Collection Name (regex)"),
                "Document": st.text_input("Filter by Document Name (regex)"),
                "Page": st.number_input("Filter by Minimum Page Count", min_value=0, value=None),
                "PageStatus": st.selectbox("Filter by Page Status", [None] + [status.value for status in PageStatus]),
                "Role": st.selectbox("Filter by Role", [None] + [role.value for role in Role])
            }

            case_sensitive = st.checkbox("Case Sensitive Search")
            submitted = st.form_submit_button("Search")

            if submitted:
                filter_by_list = []
                search_term_list = []
                if filters["Collection"]:
                    filter_by_list.append(DataFilter.COLLECTION)
                    search_term_list.append(filters["Collection"])
                if filters["Document"]:
                    filter_by_list.append(DataFilter.DOCUMENT)
                    search_term_list.append(filters["Document"])
                if filters["Page"] is not None and filters["Page"] > 0:
                    filter_by_list.append(DataFilter.PAGE)
                    search_term_list.append(str(filters["Page"]))
                if filters["PageStatus"]:
                    filter_by_list.append(DataFilter.PAGESTATUS)
                    search_term_list.append(filters["PageStatus"])
                if filters["Role"]:
                    filter_by_list.append(DataFilter.ROLE)
                    search_term_list.append(filters["Role"])

                if not filter_by_list:
                    filter_by_list.append(DataFilter.COLLECTION)
                    search_term_list.append('.')

                with st.spinner("Searching for documents...", show_time=True):
                    result = bridge.find_documents(filter_by_list, search_term_list, case_sensitive)
                    if result["success"]:
                        st.session_state.transkribus_search_results_df = result["output"]
                        st.success("Search complete.")
                    else:
                        st.error(f"Search failed: {result['output']}")
                        st.session_state.transkribus_search_results_df = None

        if st.session_state.transkribus_search_results_df is not None:
            df = st.session_state.transkribus_search_results_df
            st.dataframe(
                df,
                on_select="rerun",
                selection_mode="single-row",
                key="transkribus_search_results"
            )
            selection = st.session_state.get('transkribus_search_results', {}).get('selection', {}).get('rows', [])
            if selection:
                selected_row = df.iloc[selection[0]]
                col_id_str = selected_row['Collection (ID)']
                doc_id_str = selected_row['Document (ID)']

                col_id_match = re.search(r'\((\d+)\)', col_id_str)
                doc_id_match = re.search(r'\((\d+)\)', doc_id_str)

                # Update global session state
                st.session_state.transkribus_col_id = int(col_id_match.group(1)) if col_id_match else None
                st.session_state.transkribus_doc_id = int(doc_id_match.group(1)) if doc_id_match else None

                # Update manual input fields
                st.session_state.transkribus_col_name_input = col_id_str.split(' (')[0] if col_id_match else col_id_str
                st.session_state.transkribus_col_id_input = int(col_id_match.group(1)) if col_id_match else None
                st.session_state.transkribus_doc_name_input = doc_id_str.split(' (')[0] if doc_id_match else doc_id_str
                st.session_state.transkribus_doc_id_input = int(doc_id_match.group(1)) if doc_id_match else None

                # Clear saved ID selection when a new row is selected from dataframe
                st.session_state.saved_id_selector = ""

        # --- SET ID UI ---
        with st.expander("Set Collection/Document ID Manually", expanded=True):
            if "transkribus_config_name_input" not in st.session_state:
                st.session_state.transkribus_config_name_input = ""
            if "transkribus_col_name_input" not in st.session_state:
                st.session_state.transkribus_col_name_input = ""
            if "transkribus_col_id_input" not in st.session_state:
                st.session_state.transkribus_col_id_input = None
            if "transkribus_doc_name_input" not in st.session_state:
                st.session_state.transkribus_doc_name_input = ""
            if "transkribus_doc_id_input" not in st.session_state:
                st.session_state.transkribus_doc_id_input = None
            if "saved_id_selector" not in st.session_state:
                st.session_state.saved_id_selector = ""

            # Load saved configurations
            ids_data = load_transkribus_ids()
            saved_ids = list(ids_data.get("ids", {}).keys())

            col_load, col_delete = st.columns([3, 1])
            with col_load:
                selected_saved_id = st.selectbox(
                    "Load Saved ID Configuration",
                    options=[""] + saved_ids,
                    key="saved_id_selector"
                )
            with col_delete:
                st.write("")  # Spacer
                st.write("")
                if st.button("Delete", disabled=not selected_saved_id):
                    if selected_saved_id in ids_data.get("ids", {}):
                        del ids_data["ids"][selected_saved_id]
                        save_transkribus_ids(ids_data)
                        st.success(f"Deleted '{selected_saved_id}'.")
                        st.session_state.saved_id_selector = ""
                        st.rerun()

            # If a saved ID is selected, populate the fields
            if selected_saved_id and ('last_saved_id' not in st.session_state or st.session_state.last_saved_id != selected_saved_id):
                st.session_state.last_saved_id = selected_saved_id
                selected_data = ids_data["ids"][selected_saved_id]
                col_info = selected_data.get("collection", {})
                doc_info = selected_data.get("document", {})

                st.session_state.transkribus_config_name_input = selected_saved_id
                st.session_state.transkribus_col_name_input = col_info.get("name", selected_saved_id)
                st.session_state.transkribus_col_id_input = col_info.get("id")
                st.session_state.transkribus_doc_name_input = doc_info.get("name", "")
                st.session_state.transkribus_doc_id_input = doc_info.get("id")
                st.rerun()

            # Initialize session state for widgets if not present
            if "transkribus_col_id_input" not in st.session_state:
                st.session_state.transkribus_col_id_input = None
            if "transkribus_doc_id_input" not in st.session_state:
                st.session_state.transkribus_doc_id_input = None
            if "transkribus_col_name_input" not in st.session_state:
                st.session_state.transkribus_col_name_input = ""
            if "transkribus_doc_name_input" not in st.session_state:
                st.session_state.transkribus_doc_name_input = ""
            if "transkribus_config_name_input" not in st.session_state:
                st.session_state.transkribus_config_name_input = ""

            # Name field for configuration
            st.text_input("Name (for saving/loading configuration)", 
                          key="transkribus_config_name_input",
                          help="Enter a name to save this configuration for future use")
            col1, col2, col3, col4 = st.columns(4)
            with col1:
                st.text_input("Collection Name", key="transkribus_col_name_input")
            with col2:
                st.number_input("Collection ID", min_value=1, step=1, key="transkribus_col_id_input")
            with col3:
                st.text_input("Document Name", key="transkribus_doc_name_input")
            with col4:
                st.number_input("Document ID", min_value=1, step=1, key="transkribus_doc_id_input")

            if st.button("Set IDs", key="set_transkribus_ids_button"):
                col_id = st.session_state.transkribus_col_id_input
                doc_id = st.session_state.transkribus_doc_id_input
                col_name = st.session_state.transkribus_col_name_input
                doc_name = st.session_state.transkribus_doc_name_input
                config_name = st.session_state.transkribus_config_name_input
                
                if config_name and config_name.strip():
                    ids_data = load_transkribus_ids()
                    if 'ids' not in ids_data:
                        ids_data['ids'] = {}

                    ids_data['ids'][config_name] = {
                        "collection": {"name": col_name, "id": col_id},
                        "document": {"name": doc_name, "id": doc_id}
                    }
                    save_transkribus_ids(ids_data)
                    st.success(f"Saved configuration '{config_name}'.")
                    st.session_state.last_saved_id = None  # Allows re-selection
                    st.rerun()
                else:
                    if col_id:
                        st.session_state.transkribus_col_id = col_id
                        st.success(f"Collection ID set to {col_id}")
                    if doc_id:
                        st.session_state.transkribus_doc_id = doc_id
                        st.success(f"Document ID set to {doc_id}")
                    if not col_id and not doc_id:
                        st.warning("No IDs provided to set.")

                    # Update the session state for the other tabs
                    if col_name:
                        st.session_state.transkribus_col_name = col_name
                    if doc_name:
                        st.session_state.transkribus_doc_name = doc_name

    with tab3:
        st.header("Download Document")

        # Load saved configurations for download
        ids_data_download = load_transkribus_ids()
        saved_ids_download = list(ids_data_download.get("ids", {}).keys())

        if saved_ids_download:
            selected_saved_id_download = st.selectbox(
                "Load saved configuration",
                options=[""] + saved_ids_download,
                key="saved_id_selector_download"
            )
            if selected_saved_id_download and ('last_download_id' not in st.session_state or st.session_state.last_download_id != selected_saved_id_download):
                st.session_state.last_download_id = selected_saved_id_download
                selected_data = ids_data_download["ids"][selected_saved_id_download]
                col_info = selected_data.get("collection", {})
                doc_info = selected_data.get("document", {})
                st.session_state.transkribus_col_id = col_info.get("id")
                st.session_state.transkribus_doc_id = doc_info.get("id")
                st.rerun()

        collection_id = st.number_input("Collection ID", min_value=1, step=1,
                                        value=st.session_state.get("transkribus_col_id"),
                                        key="transkribus_load_col_id")
        document_id = st.number_input("Document ID", min_value=1, step=1,
                                      value=st.session_state.get("transkribus_doc_id"),
                                      key="transkribus_load_doc_id")
        pages = st.text_input("Pages (e.g., 1, 5, 10-15)", key="transkribus_load_pages",
                              help="Comma-separated list of pages or page ranges.")

        col1, col2 = st.columns(2)
        with col1:
            load_images = st.checkbox("Load Images", key="transkribus_load_images")
            overwrite_ws = st.checkbox("Overwrite existing workspace", key="transkribus_overwrite_ws")
        with col2:
            loading = st.checkbox("Load as default workspace", key="transkribus_loading", value=True)

        workspace = st.text_input("Workspace name", value="MAIN", key="transkribus_load_workspace")

        st.text_input("Folder path (optional)",
                      value=st.session_state.get("transkribus_folderpath", ""),
                      key="transkribus_folderpath_input")
        if st.button("Select Directory", key="transkribus_select_load_dir"):
            selected_dir = pick_directory()
            if selected_dir:
                st.session_state.transkribus_folderpath = selected_dir
                st.rerun()

        if st.button("Download Document"):
            if not all([collection_id, document_id]):
                st.warning("Please provide a Collection ID and a Document ID.")
            else:
                page_list = [p.strip() for p in pages.split(',')] if pages else []
                with st.spinner("Loading document...", show_time=True):
                    result = bridge.load_document(
                        collection_id=collection_id,
                        document_id=document_id,
                        pages=page_list,
                        load_images=load_images,
                        folderpath=st.session_state.get("transkribus_folderpath"),
                        workspace=workspace,
                        overwrite_ws=overwrite_ws,
                        loading=loading
                    )
                    if result["success"]:
                        st.success(result["output"])
                    else:
                        st.error(result["output"])

    with tab4:
        st.header("Update Document")

        st.info("Select the XML files you want to upload.")
        if st.button("Select XML Files", key="transkribus_select_update_files"):
            files = pick_files(filetypes=[("XML files", "*.xml"), ("All files", "*")])
            if files:
                st.session_state.transkribus_update_files = files

        if 'transkribus_update_files' in st.session_state and st.session_state.transkribus_update_files:
            st.write(f"Selected {len(st.session_state.transkribus_update_files)} files:")
            st.json([path for path in st.session_state.transkribus_update_files])

        # Load saved configurations for update
        ids_data_update = load_transkribus_ids()
        saved_ids_update = list(ids_data_update.get("ids", {}).keys())

        if saved_ids_update:
            selected_saved_id_update = st.selectbox(
                "Load Saved Configuration",
                options=[""] + saved_ids_update,
                key="saved_id_selector_update"
            )
            if selected_saved_id_update and ('last_update_id' not in st.session_state or st.session_state.last_update_id != selected_saved_id_update):
                st.session_state.last_update_id = selected_saved_id_update
                selected_data = ids_data_update["ids"][selected_saved_id_update]
                col_info = selected_data.get("collection", {})
                doc_info = selected_data.get("document", {})
                st.session_state.transkribus_col_id = col_info.get("id")
                st.session_state.transkribus_doc_id = doc_info.get("id")
                st.rerun()

        collection_id_up = st.number_input("Collection ID", min_value=1, step=1, value=st.session_state.get("transkribus_col_id"), key="transkribus_update_col_id")
        document_id_up = st.number_input("Document ID", min_value=1, step=1,
                                         value=st.session_state.get("transkribus_doc_id"),
                                         key="transkribus_update_doc_id")
        pages_up = st.text_input("Pages (optional, e.g., 1, 5, 10-15)", key="transkribus_update_pages",
                                 help="Restricts upload to specific page numbers. If empty, all selected files will be uploaded based on their filenames.")
        status_up = st.selectbox("Set Page status", [status.value for status in PageStatus],
                                 key="transkribus_update_status")
        overwrite_up = st.checkbox("Overwrite existing transcription", value=True, key="transkribus_overwrite_up")
        version_update = st.checkbox("Set XML-Version (2013-07-15) on the fly", value=False, key="transkribus_version_update")
        note_up = st.text_area("Note (optional)", key="transkribus_note_up")

        if st.button("Update Document"):
            selected_files = [str(files.absolute()) for files in st.session_state.loaded_files]
            if version_update:    
                from pageplus.models.page import Page
                tmp_folder = Path(selected_files[0]).parent.joinpath("storage/tmp")
                tmp_folder.mkdir(parents=True, exist_ok=True)
                tmp_files = []
                for file in selected_files:
                    page = Page(file)
                    page.update_pcgts_version('2013-07-15')
                    page.save_xml(tmp_folder.joinpath(file.name))
                    tmp_files.append(tmp_folder.joinpath(file.name).absolute())
                selected_files = tmp_files
            if not selected_files:
                st.warning("Please select files to update.")
            elif not all([collection_id_up, document_id_up]):
                st.warning("Please provide a Collection ID and a Document ID.")
            else:
                page_list_up = [p.strip() for p in pages_up.split(',')] if pages_up else []
                with st.spinner("Updating document...", show_time=True):
                    result = bridge.update_document(
                        inputs=selected_files,
                        collection_id=collection_id_up,
                        document_id=document_id_up,
                        pages=page_list_up,
                        overwrite=overwrite_up,
                        status=PageStatus(status_up),
                        note=note_up
                    )
                    if result["success"]:
                        if version_update:
                            import shutil
                            shutil.rmtree(tmp_folder)
                        st.success(result["output"])
                    else:
                        st.error(result["output"])
