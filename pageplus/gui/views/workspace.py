import logging

import streamlit as st

from pageplus.gui.utils.picker import pick_directory
from pageplus.utils.constants import Environments
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

            col1, col2 = st.columns(2)
            with col1:
                if selected_workspace:
                    # Remove green dot from selected workspace name for processing
                    selected_workspace = selected_workspace.replace("🟢 ", "")

                    # Load workspace button
                    if st.button("Load Selected Workspace"):
                        try:
                            cli_bridge.load_workspace(selected_workspace)
                            st.success(
                                f"Workspace '{selected_workspace}' loaded successfully!")
                            st.rerun()
                        except Exception as e:
                            st.error(f"Error loading workspace: {str(e)}")

            with col2:
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
            selected_paths = pick_directory()
            if selected_paths:
                st.session_state.workspace_dir = selected_paths
            elif selected_paths is not None:
                st.info("Directory selection cancelled.")

        if 'workspace_dir' in st.session_state:
            st.text_input(
                "Selected Directory",
                value=st.session_state.workspace_dir,
                disabled=True,
                label_visibility="visible" if 'workspace_dir' in st.session_state else "hidden"
            )

        workspace_name = st.text_input(
            "Workspace Name",
            placeholder="Enter workspace name",
            label_visibility="visible"
        )

        if st.button("Add Workspace"):
            if workspace_name and 'workspace_dir' in st.session_state:
                try:
                    cli_bridge.load_local_document(
                        st.session_state.workspace_dir, workspace_name, False)
                    st.success(f"Workspace '{workspace_name}' added successfully!")
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
            new_workspace = st.text_input(
                "New Workspace Name (optional)",
                label_visibility="visible"
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
                            cli_bridge.copy_workspace(
                                destination_path,
                                selected_workspace,
                                new_workspace
                            )
                            st.success("Workspace copied successfully!")
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
        backup_folder = st.text_input(
            "Backup Folder",
            value="Backup",
            label_visibility="visible"
        )
        col1, col2, col3, col4 = st.columns(4)
        with col1:
            if st.button("Backup XML Files"):
                try:
                    cli_bridge.backup_xmlfiles(backup_folder)
                    st.success("XML files backed up successfully!")
                    st.rerun()
                except Exception as e:
                    st.error(f"Error backing up XML files: {str(e)}")

        with col2:
            if st.button("Backup XML Files as Zip"):
                try:
                    cli_bridge.backup_xmlfiles(backup_folder, as_zip=True)
                    st.success("XML files backed up successfully!")
                    st.rerun()
                except Exception as e:
                    st.error(f"Error backing up XML files: {str(e)}")
        with col3:
            if st.button("Restore XML Files"):
                try:
                    cli_bridge.restore_xmlfiles(backup_folder)
                    st.success("XML files restored successfully!")
                    st.rerun()
                except Exception as e:
                    st.error(f"Error restoring XML files: {str(e)}")
        with col4:
            if st.button("Restore XML Files from Zip"):
                try:
                    cli_bridge.restore_xmlfiles(backup_folder, from_zip=True)
                    st.success("XML files restored successfully!")
                    st.rerun()
                except Exception as e:
                    st.error(f"Error restoring XML files: {str(e)}")

    # Show success message from session state if it exists
    if 'workspace_success' in st.session_state:
        st.success(st.session_state.workspace_success)
        # Clear the success message after showing it
        del st.session_state.workspace_success
