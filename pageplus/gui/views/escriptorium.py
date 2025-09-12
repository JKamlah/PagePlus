
import json
import re
from pathlib import Path
from importlib import util

import streamlit as st

from pageplus.cli.escriptorium import DataFilter
from pageplus.gui.cli_bridges.escriptorium import EscriptoriumBridge
from pageplus.gui.utils.picker import pick_directory, pick_files
from pageplus.gui.utils.settings import Settings


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
                            "project": {"name": "", "pk": None},
                            "document": {"name": name, "pk": values.get("document")},
                            "transcription": {"name": "", "pk": values.get("transcription")}
                        }
                    data["pks"] = migrated_pks
                    del data["pk"]
                    save_escriptorium_pks(data)
                
                # Migration to add project structure if missing
                if "pks" in data:
                    for name, pk_data in data["pks"].items():
                        if "project" not in pk_data:
                            pk_data["project"] = {"name": "", "pk": None}
                        if "name" not in pk_data.get("project", {}):
                            pk_data["project"]["name"] = ""
                        if "pk" not in pk_data.get("project", {}):
                            pk_data["project"]["pk"] = None
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
            with st.spinner("Installing...", show_time=True):
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
    tab_names = ["Settings", "Find Documents", "Download Document", "Update Document", "Create Project/Document", "Upload new Images/Transcriptions"]
    tabs = st.tabs(tab_names)

    with tabs[0]:  # Settings
        st.subheader("Settings")

        with st.expander("API Settings", expanded=True):
            base_url = st.text_input(
                "Base URL",
                value=settings.get("ESCRIPTORIUM_BASE_URL", "https://escriptorium.fr"),
            )
            if st.button("Set Base URL", key="set_base_url_button"):
                with st.spinner("Setting Base URL...", show_time=True):
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
                with st.spinner("Setting API Base URL...", show_time=True):
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
                with st.spinner("Setting instance name...", show_time=True):
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
                with st.spinner("Setting credentials...", show_time=True):
                    result = bridge.set_credentials(username, password)
                if result["success"]:
                    st.success(result["output"])
                else:
                    st.error(result["output"])

        if st.button("Show Current Settings"):
            with st.spinner("Fetching settings...", show_time=True):
                result = bridge.show_settings()
            if result["success"]:
                st.text_area("Settings", result["output"], height=200)
            else:
                st.error(result["output"])

    with tabs[1]:  # Find Documents
        st.subheader("Find Documents")

        if 'escriptorium_filters' not in st.session_state:
            st.session_state.escriptorium_filters = [{"filter_by": DataFilter.PROJECT.value, "search_term": "."}]

        if 'selected_document_row_index' not in st.session_state:
            st.session_state.selected_document_row_index = None

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

            with st.spinner("Finding documents...", show_time=True):
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
            current_selection_index = selection[0] if selection else None

            if current_selection_index != st.session_state.get('selected_document_row_index'):
                st.session_state.selected_document_row_index = current_selection_index

                if current_selection_index is not None:
                    selected_row = df.iloc[current_selection_index]
                    doc_pk_str = selected_row['Document (PK)']
                    doc_pk_match = re.search(r'\((\d+)\)', doc_pk_str)

                    st.session_state.escript_doc_pk_input = int(doc_pk_match.group(1)) if doc_pk_match else None
                    st.session_state.escript_doc_name_input = doc_pk_str.split(' (')[0] if doc_pk_match else doc_pk_str
                    st.session_state.escript_project_name_input = selected_row['Project']  # Extract project name from search results
                    st.session_state.transcription_options = selected_row['Transcription (PK)']
                    st.session_state.saved_pk_selector = ""  # Clear saved PK selection
                else:
                    st.session_state.transcription_options = []
                    st.session_state.escript_doc_pk_input = None
                    st.session_state.escript_doc_name_input = ""
                    st.session_state.escript_project_name_input = ""

        # --- SET PK UI ---
        with st.expander("Set Document/Transcription PK Manually", expanded=True):
            if "escript_doc_name_input" not in st.session_state:
                st.session_state.escript_doc_name_input = ""
            if "escript_project_name_input" not in st.session_state:
                st.session_state.escript_project_name_input = ""
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
                project_info = selected_data.get("project", {})
                doc_info = selected_data.get("document", {})
                trans_info = selected_data.get("transcription", {})

                st.session_state.escript_doc_name_input = doc_info.get("name", selected_saved_pk)
                st.session_state.escript_project_name_input = project_info.get("name", "")
                st.session_state.escript_doc_pk_input = doc_info.get("pk")
                st.session_state.transcription_options = []  # Can't know options, so use number input
                st.session_state.escript_trans_pk_input = trans_info.get("pk")
                st.rerun()

            col1, col2, col3, col4 = st.columns(4)
            with col1:
                st.text_input("Name", key="escript_doc_name_input")
            with col2:
                st.text_input("Project Name", key="escript_project_name_input")
            with col3:
                st.number_input("Document PK", min_value=1, step=1, key="escript_doc_pk_input")
            with col4:
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
                project_name = st.session_state.escript_project_name_input
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
                        "project": {"name": project_name if project_name else "", "pk": None},  # Project PK not available in manual setting
                        "document": {"name": entry_name, "pk": doc_pk},
                        "transcription": {"name": trans_name, "pk": trans_pk}
                    }
                    save_escriptorium_pks(pks_data)
                    st.success(f"Saved configuration '{entry_name}'.")
                    st.session_state.last_saved_pk = None  # Allows re-selection
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

    with tabs[2]:  # Download Document
        st.subheader("Download Document")

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
            project_info = selected_data.get("project", {})
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
            st.text_input(
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

            with st.spinner("Downloading document...", show_time=True):
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
            project_info = selected_data.get("project", {})
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

            with st.spinner("Updating document...", show_time=True):
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

    with tabs[4]:  # Create Project/Document
        st.subheader("Create Project/Document")

        col1, col2 = st.columns(2)
        with col1:
            project_name = st.text_input("New project name or existing PK", help="Enter project name to create new project, or existing project PK")
        with col2:
            document_name = st.text_input("Document name", help="Name of the document to create")

        col3, col4 = st.columns(2)
        with col3:
            st.subheader("Images")
            if st.button("Select Image Files", key="select_create_images"):
                image_files = pick_files(filetypes=[("Image files", "*.jpg *.jpeg *.png *.tiff *.tif"), ("All ocrocr-files", "*.*")])
                if image_files:
                    st.session_state.create_image_files = image_files
                    st.success(f"Selected {len(image_files)} image file(s)")
            
            if 'create_image_files' in st.session_state:
                st.write(f"Selected images: {len(st.session_state.create_image_files)} files")
                for i, file_path in enumerate(st.session_state.create_image_files[:5]):  # Show first 5
                    st.write(f"- {Path(file_path).name}")
                if len(st.session_state.create_image_files) > 5:
                    st.write(f"... and {len(st.session_state.create_image_files) - 5} more")
        with col4:
            st.subheader("XML Files")
            if st.button("Select XML Files", key="select_create_xmls"):
                xml_files = pick_files(filetypes=[("XML files", "*.xml"), ("All files", "*.*")])
                if xml_files:
                    st.session_state.create_xml_files = xml_files
                    st.success(f"Selected {len(xml_files)} XML file(s)")
            
            if 'create_xml_files' in st.session_state:
                st.write(f"Selected XML files: {len(st.session_state.create_xml_files)} files")
                for i, file_path in enumerate(st.session_state.create_xml_files[:5]):  # Show first 5
                    st.write(f"- {Path(file_path).name}")
                if len(st.session_state.create_xml_files) > 5:
                    st.write(f"... and {len(st.session_state.create_xml_files) - 5} more")

        transcription_name = st.text_input("Transcription Name (optional)", help="Name for the transcription")
        workspace_name = st.text_input("Workspace Name (optional)", help="Name for the workspace to store project info")

        if st.button("Create Project/Document"):
            if not project_name or not document_name:
                st.error("Please provide both project name/PK and document name.")
            else:
                # Get selected file paths
                image_paths = st.session_state.get('create_image_files', [])
                xml_paths = st.session_state.get('create_xml_files', [])

                with st.spinner("Creating project/document..."):
                    result = bridge.create_project_document(
                        project_name=project_name,
                        document_name=document_name,
                        images=image_paths if image_paths else None,
                        xml_files=xml_paths if xml_paths else None,
                        transcription_name=transcription_name if transcription_name else None,
                        workspace=workspace_name if workspace_name else None
                    )

                if result["success"]:
                    st.success("Project/Document created successfully.")
                    st.text_area("Output", result["output"], height=300)
                else:
                    st.error(result["output"])

    with tabs[5]:  # Add Parts
        st.subheader("Add Parts to existing document")

        # --- Selector for Saved PKs ---
        pks_data_add = load_escriptorium_pks()
        saved_pks_add = list(pks_data_add.get("pks", {}).keys())
        selected_pk_to_add = st.selectbox(
            "Load from Saved PKs",
            options=[""] + saved_pks_add,
            key="add_pk_selector"
        )

        if selected_pk_to_add and ('last_add_pk' not in st.session_state or st.session_state.last_add_pk != selected_pk_to_add):
            st.session_state.last_add_pk = selected_pk_to_add
            selected_data = pks_data_add["pks"][selected_pk_to_add]
            project_info = selected_data.get("project", {})
            doc_info = selected_data.get("document", {})
            trans_info = selected_data.get("transcription", {})

            # Load project PK and name if available, otherwise leave as None
            st.session_state.add_project_name = project_info.get("name", "")
            st.session_state.add_project_pk = project_info.get("pk") if project_info.get("pk") else None
            st.session_state.add_document_pk = doc_info.get("pk")
            st.session_state.add_transcription_name = trans_info.get("name")
            st.rerun()

        # Initialize session state for widgets if not present
        if "add_project_name" not in st.session_state:
            st.session_state.add_project_name = ""
        if "add_project_pk" not in st.session_state:
            st.session_state.add_project_pk = None
        if "add_document_pk" not in st.session_state:
            st.session_state.add_document_pk = None

        col1, col2, col3 = st.columns(3)
        with col1:
            project_name = st.text_input("Project Name", value=st.session_state.get("add_project_name", ""), help="Name of the project", key="add_project_name_input")
        with col2:
            project_pk = st.number_input(
                "Project PK (optional)", 
                min_value=0, 
                step=1, 
                value=st.session_state.get("add_project_pk") or 0, 
                help="Primary key of the project (use if project name fails)", 
                key="add_project_pk_input"
            )
            # Convert 0 to None for easier checking
            if project_pk == 0:
                project_pk = None
        with col3:
            document_pk = st.number_input("Document PK", min_value=1, step=1, value=st.session_state.get("add_document_pk"), help="Primary key of the existing document")

        col4, col5 = st.columns(2)
        with col4:
            st.subheader("Images")
            if st.button("Select Image Files", key="select_add_images"):
                image_files = pick_files(filetypes=[("Image files", "*.jpg *.jpeg *.png *.tiff *.tif"), ("All files", "*.*")])
                if image_files:
                    st.session_state.add_image_files = image_files
                    st.success(f"Selected {len(image_files)} image file(s)")
            
            if 'add_image_files' in st.session_state:
                st.write(f"Selected images: {len(st.session_state.add_image_files)} files")
                for i, file_path in enumerate(st.session_state.add_image_files[:5]):  # Show first 5
                    st.write(f"- {Path(file_path).name}")
                if len(st.session_state.add_image_files) > 5:
                    st.write(f"... and {len(st.session_state.add_image_files) - 5} more")
        with col5:
            st.subheader("XML Files")
            if st.button("Select XML Files", key="select_add_xmls"):
                xml_files = pick_files(filetypes=[("XML files", "*.xml"), ("All files", "*.*")])
                if xml_files:
                    st.session_state.add_xml_files = xml_files
                    st.success(f"Selected {len(xml_files)} XML file(s)")
            
            if 'add_xml_files' in st.session_state:
                st.write(f"Selected XML files: {len(st.session_state.add_xml_files)} files")
                for i, file_path in enumerate(st.session_state.add_xml_files[:5]):  # Show first 5
                    st.write(f"- {Path(file_path).name}")
                if len(st.session_state.add_xml_files) > 5:
                    st.write(f"... and {len(st.session_state.add_xml_files) - 5} more")

        transcription_name_add = st.text_input("Transcription Name (optional)", value=st.session_state.get("add_transcription_name", ""), help="Name for the transcription", key="add_transcription")

        # Manual PK setting section
        with st.expander("Set Document/Transcription PK Manually", expanded=False):
            col_manual1, col_manual2, col_manual3, col_manual4 = st.columns(4)
            with col_manual1:
                manual_doc_name = st.text_input("Name", key="add_manual_doc_name")
            with col_manual2:
                manual_project_name = st.text_input("Project Name", key="add_manual_project_name")
            with col_manual3:
                manual_doc_pk = st.number_input("Document PK", min_value=1, step=1, key="add_manual_doc_pk")
            with col_manual4:
                manual_trans_pk = st.number_input("Transcription PK", min_value=1, step=1, key="add_manual_trans_pk")

            if st.button("Set PKs", key="set_add_pks_button"):
                if manual_doc_name and manual_doc_name.strip():
                    pks_data = load_escriptorium_pks()
                    if 'pks' not in pks_data:
                        pks_data['pks'] = {}
                    
                    pks_data['pks'][manual_doc_name] = {
                        "project": {"name": manual_project_name if manual_project_name else "", "pk": None},  # Project PK not available in manual setting
                        "document": {"name": manual_doc_name, "pk": manual_doc_pk},
                        "transcription": {"name": "", "pk": manual_trans_pk}
                    }
                    save_escriptorium_pks(pks_data)
                    st.success(f"Saved configuration '{manual_doc_name}'.")
                    st.rerun()
                else:
                    if manual_doc_pk:
                        st.session_state.add_document_pk = manual_doc_pk
                    if manual_trans_pk:
                        st.session_state.add_transcription_name = f"Transcription_{manual_trans_pk}"
                    st.success("PKs set for current session.")

        if st.button("Add Parts"):
            if not document_pk:
                st.error("Please provide document PK.")
            elif not project_name.strip() and not project_pk:
                st.error("Please provide either project name or project PK.")
            else:
                # Get selected file paths
                image_paths = st.session_state.get('add_image_files', [])
                xml_paths = st.session_state.get('add_xml_files', [])

                if not image_paths and not xml_paths:
                    st.error("Please select at least one image or XML file.")
                else:
                    with st.spinner("Adding parts to document..."):
                        # Debug information
                        st.write(f"Debug: project_name='{project_name}', project_pk={project_pk}, document_pk={document_pk}")
                        
                        # Use project PK if available, otherwise use project name
                        if project_pk:
                            result = bridge.add_parts_by_pk(
                                project_pk=project_pk,
                                document_pk=document_pk,
                                images=image_paths if image_paths else None,
                                xml_files=xml_paths if xml_paths else None,
                                transcription_name=transcription_name_add if transcription_name_add else None
                            )
                        elif project_name.strip():
                            result = bridge.add_parts(
                                project_name=project_name.strip(),
                                document_pk=document_pk,
                                images=image_paths if image_paths else None,
                                xml_files=xml_paths if xml_paths else None,
                                transcription_name=transcription_name_add if transcription_name_add else None
                            )
                        else:
                            st.error("Please provide either a valid project name or project PK.")
                            return

                    if result["success"]:
                        st.success("Parts added successfully.")
                        st.text_area("Output", result["output"], height=300)
                    else:
                        st.error(result["output"])
