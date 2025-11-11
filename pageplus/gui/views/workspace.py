import logging
from pathlib import Path

import streamlit as st

from pageplus.gui.utils.picker import pick_directory
from pageplus.utils.constants import Environments
from pageplus.utils.envs import str_to_env
from pageplus.utils.workspace import Workspace

# Silence watchdog debug messages
logging.getLogger('watchdog.observers.inotify_buffer').setLevel(
    logging.WARNING)


def show_workspace(cli_bridge):
    """Display workspace management page."""
    st.title("🗂️ Workspace Management")

    # Initialize session state for delete confirmation
    if 'confirming_delete' not in st.session_state:
        st.session_state.confirming_delete = None

    # Get available workspaces and loaded workspace
    try:
        ws = Workspace(Environments.PAGEPLUS)
        workspace_names = ws.names()
        loaded_workspace = ws.loaded() if ws.loaded(
        ) and ws.loaded() in workspace_names else None
    except Exception as e:
        st.error(f"Error getting workspaces: {str(e)}")
        workspace_names = []
        loaded_workspace = None

    # --- UI TABS ---
    tab_names = ["🗂️ Current", "➕ Add New", "📋 Copy", "🗑️ Delete", "💾 Backup/Restore"]
    tabs = st.tabs(tab_names)

    # --- TAB 1: Current Workspaces ---
    with tabs[0]:
        st.subheader("Current Workspaces")
        if workspace_names:
            # Create dropdown with workspaces, adding green dot to loaded workspace
            workspace_options = [
                f"🟢 {name}" if name == loaded_workspace else name
                for name in workspace_names
            ]
            selected_workspace = st.selectbox(
                "Select Workspace",
                options=workspace_options,
                index=None if not loaded_workspace else workspace_names.index(loaded_workspace)
            )

            if selected_workspace:
                # Remove green dot from selected workspace name for processing
                clean_selected_workspace = selected_workspace.replace("🟢 ", "")

                # Get and display workspace path
                if clean_selected_workspace != "":
                    try:
                        current_path = cli_bridge.workspace_path(clean_selected_workspace)
                        if current_path:
                            st.text_input("Workspace path", current_path, disabled=True)
                            if st.button("Change directory", key=f"change_dir_{clean_selected_workspace}"):
                                new_path = pick_directory(initial_dir=str(current_path))
                                if new_path and new_path != str(current_path):
                                    try:
                                        cli_bridge.set_workspace_path(clean_selected_workspace, new_path)
                                        st.success(f"Path for '{clean_selected_workspace}' updated successfully!")
                                        st.rerun()
                                    except Exception as e:
                                        st.error(f"Error updating path: {str(e)}")
                    except Exception as e:
                        st.error(f"Could not retrieve workspace path: {e}")

            col1, col2, col3 = st.columns(3)
            with col1:
                if selected_workspace:
                    # Remove green dot from selected workspace name for processing
                    clean_selected_workspace = selected_workspace.replace("🟢 ", "")

                    # Load workspace button
                    if st.button("Load Selected Workspace"):
                        try:
                            cli_bridge.load_workspace(clean_selected_workspace)
                            st.success(
                                f"Workspace '{clean_selected_workspace}' loaded successfully!")
                            st.rerun()
                        except Exception as e:
                            st.error(f"Error loading workspace: {str(e)}")

            with col2:
                if selected_workspace:
                    clean_selected_workspace = selected_workspace.replace("🟢 ", "")
                    if st.button("Open Workspace Folder"):
                        try:
                            cli_bridge.open_workspace(clean_selected_workspace)
                            st.success(f"Opened folder for workspace '{clean_selected_workspace}'.")
                        except Exception as e:
                            st.error(f"Error opening workspace folder: {str(e)}")

            with col3:
                if loaded_workspace:
                    if st.button("Reset Loaded Workspace"):
                        try:
                            cli_bridge.load_workspace("")
                            st.success("Workspace reset successfully!")
                            st.rerun()
                        except Exception as e:
                            st.error(f"Error resetting workspace: {str(e)}")
        else:
            st.info("No workspaces available. Please create a workspace first.")
        # Update workspaces
        if st.button("Update Workspaces"):
            try:
                cli_bridge.update_workspaces()
                st.success("Workspaces updated successfully!")
                st.rerun()
            except Exception as e:
                st.error(f"Error updating workspaces: {str(e)}")

    # --- TAB 2: Add New Workspace ---
    with tabs[1]:
        st.subheader("Add New Workspace")

        if st.button("Select Directory"):
            initial_dir = st.session_state.get('workspace_dir', None)
            selected_paths = pick_directory(initial_dir=initial_dir)
            if selected_paths:
                st.session_state.workspace_dir = selected_paths
                # Suggest the last folder name as workspace name
                path = Path(selected_paths)
                folder_name = path.name
                if folder_name == 'page':
                    folder_name = path.parent.name
                folder_name = str_to_env(folder_name)
                st.session_state.workspace_name_suggestion = folder_name
                st.session_state.workspace_name_input = folder_name
                st.rerun()
            elif selected_paths is not None:
                st.info("Directory selection cancelled.")

        if 'workspace_dir' in st.session_state:
            st.text_input(
                "Selected Directory",
                value=st.session_state.workspace_dir,
                disabled=True,
                label_visibility="visible" if 'workspace_dir' in st.session_state else "hidden"
            )

        # Use suggested name if available, otherwise empty
        default_name = st.session_state.get('workspace_name_suggestion', '')
        workspace_name = st.text_input(
            "Workspace Name",
            value=default_name,
            placeholder="Enter workspace name",
            label_visibility="visible",
            key="workspace_name_input"
        )

        if st.button("Add Workspace"):
            if workspace_name and 'workspace_dir' in st.session_state:
                try:
                    workspace_name = str_to_env(workspace_name)
                    cli_bridge.load_local_document(
                        st.session_state.workspace_dir, workspace_name, False)
                    st.success(f"Workspace '{workspace_name}' added successfully!")
                    # Clear the suggestion after successful creation
                    if 'workspace_name_suggestion' in st.session_state:
                        del st.session_state.workspace_name_suggestion
                    if 'workspace_dir' in st.session_state:
                        del st.session_state.workspace_dir
                    st.rerun()
                except Exception as e:
                    st.error(f"Error adding workspace: {str(e)}")
            else:
                st.error("Please provide both workspace name and directory")

    # --- TAB 3: Copy Workspace ---
    with tabs[2]:
        st.subheader("Copy Workspace")

        if st.button("Select Destination Directory", key="copy_select_dir"):
            selected_paths = pick_directory()
            if selected_paths:
                st.session_state.copy_destination_dir = selected_paths
                # Suggest the last folder name as new workspace name
                path = Path(selected_paths)
                folder_name = path.name
                if folder_name == 'page':
                    folder_name = path.parent.name
                folder_name = str_to_env(folder_name)
                st.session_state.copy_workspace_name_suggestion = folder_name
                st.session_state.copy_workspace_name_input = folder_name
                st.rerun()
            elif selected_paths is not None:
                st.info("Directory selection cancelled.")

        col1, col2 = st.columns(2)
        with col1:
            destination_path = st.text_input(
                "Destination Path",
                value=st.session_state.get('copy_destination_dir', ''),
                label_visibility="visible",
                key="copy_dest_path"
            )
            # Update session state if user manually edits the path
            if destination_path:
                st.session_state.copy_destination_dir = destination_path
        with col2:
            # Use suggested name if available, otherwise empty
            default_copy_name = st.session_state.get('copy_workspace_name_suggestion', '')
            new_workspace = st.text_input(
                "New Workspace Name (optional)",
                value=default_copy_name,
                label_visibility="visible",
                key="copy_workspace_name_input"
            )

        if workspace_names:
            if selected_workspace:
                # Remove green dot from workspace name for processing
                selected_workspace = selected_workspace.replace("🟢 ", "")
                if st.button("Copy Selected Workspace"):
                    if not destination_path:
                        st.error("Please select a destination directory first")
                    else:
                        try:
                            new_workspace = str_to_env(new_workspace)
                            cli_bridge.copy_workspace(
                                destination_path,
                                selected_workspace,
                                new_workspace
                            )
                            st.success("Workspace copied successfully!")
                            # Clear the suggestion after successful copy
                            if 'copy_workspace_name_suggestion' in st.session_state:
                                del st.session_state.copy_workspace_name_suggestion
                            if 'copy_destination_dir' in st.session_state:
                                del st.session_state.copy_destination_dir
                            st.rerun()
                        except Exception as e:
                            st.error(f"Error copying workspace: {str(e)}")

    # --- TAB 4: Delete Workspace ---
    with tabs[3]:
        st.subheader("Delete Workspace")
        if workspace_names:
            if selected_workspace:
                # Remove green dot from workspace name for processing
                clean_selected_workspace = selected_workspace.replace("🟢 ", "")
                col1, col2 = st.columns(2)
                with col1:
                    if st.button("Delete Selected Workspace (keep files)"):
                        try:
                            cli_bridge.delete_workspace(clean_selected_workspace, all_files=False)
                            st.success(
                                f"Workspace '{clean_selected_workspace}' deleted successfully!")
                            cli_bridge.update_workspaces()
                            st.rerun()
                        except Exception as e:
                            st.error(f"Error deleting workspace: {str(e)}")
                with col2:
                    if st.button("Delete Workspace and all files"):
                        st.session_state.confirming_delete = clean_selected_workspace

                    if st.session_state.confirming_delete == clean_selected_workspace:
                        st.warning(f"**Are you sure you want to delete the workspace '{clean_selected_workspace}' and all its files?** This action cannot be undone.")
                        if st.button("Yes, delete everything"):
                            try:
                                cli_bridge.delete_workspace(clean_selected_workspace, all_files=True)
                                st.success(
                                    f"Workspace '{clean_selected_workspace}' and all its files deleted successfully!")
                                st.session_state.confirming_delete = None  # Reset confirmation state
                                cli_bridge.update_workspaces()
                                st.rerun()
                            except Exception as e:
                                st.error(f"Error deleting workspace: {str(e)}")
                                st.session_state.confirming_delete = None
                        if st.button("Cancel"):
                            st.session_state.confirming_delete = None
                            st.rerun()

    # --- TAB 5: Backup and Restore ---
    with tabs[4]:
        st.subheader("Backup and Restore")

        if not loaded_workspace:
            st.warning("Please load a workspace first to see backup and restore options.")
        else:
            ws = Workspace(Environments.PAGEPLUS)
            workspace_path = Path(ws.path(loaded_workspace))

            # --- Backup Section ---
            st.markdown("#### Backup")
            backup_folder_name = st.text_input(
                "Backup Folder Name",
                value="Backup",
                help="Provide a name for the backup folder or the base name for the zip file."
            )
            col1, col2 = st.columns(2)
            with col1:
                if st.button("Backup XML Files to Folder"):
                    if backup_folder_name:
                        try:
                            cli_bridge.backup_xmlfiles(backup_folder_name, as_zip=False)
                            st.success(f"XML files backed up successfully to '{backup_folder_name}'!")
                            st.rerun()
                        except Exception as e:
                            st.error(f"Error backing up XML files: {str(e)}")
                    else:
                        st.error("Backup folder name cannot be empty.")

            with col2:
                if st.button("Backup XML Files as Zip"):
                    if backup_folder_name:
                        try:
                            cli_bridge.backup_xmlfiles(backup_folder_name, as_zip=True)
                            st.success(f"XML files backed up successfully to '{backup_folder_name}.zip'!")
                            st.rerun()
                        except Exception as e:
                            st.error(f"Error backing up XML files as zip: {str(e)}")
                    else:
                        st.error("Backup file name cannot be empty.")

            st.divider()

            # --- Restore Section ---
            st.markdown("#### Restore")

            # Restore from Zip
            zip_files = sorted([f.name for f in workspace_path.glob('*.zip')], reverse=True)
            if zip_files:
                selected_zip = st.selectbox("Select a zip file to restore from", zip_files)
                if st.button("Restore from selected Zip"):
                    try:
                        # We pass the filename without the .zip extension to the bridge
                        cli_bridge.restore_xmlfiles(Path(selected_zip).stem, from_zip=True)
                        st.success(f"XML files from '{selected_zip}' restored successfully!")
                        st.rerun()
                    except Exception as e:
                        st.error(f"Error restoring from zip: {str(e)}")
            else:
                st.info("No zip backups found in the current workspace directory.")

            # Restore from Folder
            # Exclude common non-backup folders and files that look like zips
            subfolders = sorted(
                [f.name for f in workspace_path.iterdir() if f.is_dir() and not f.name.startswith('.') and f.name != "__pycache__"],
                reverse=True
            )
            if subfolders:
                selected_folder = st.selectbox("Select a folder to restore from", subfolders)
                if st.button("Restore from selected Folder"):
                    try:
                        cli_bridge.restore_xmlfiles(selected_folder, from_zip=False)
                        st.success(f"XML files from '{selected_folder}' restored successfully!")
                        st.rerun()
                    except Exception as e:
                        st.error(f"Error restoring from folder: {str(e)}")
            else:
                st.info("No backup subfolders found in the current workspace directory.")

    # Show success message from session state if it exists
    if 'workspace_success' in st.session_state:
        st.success(st.session_state.workspace_success)
        # Clear the success message after showing it
        del st.session_state.workspace_success
