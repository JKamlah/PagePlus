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

    # Show current workspaces
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

    # Backup/Restore
    st.subheader("Backup and Restore")
    backup_folder = st.text_input(
        "Backup Folder",
        value="Backup",
        label_visibility="visible"
    )
    col1, col2 = st.columns(2)
    with col1:
        if st.button("Backup XML Files"):
            try:
                cli_bridge.backup_xmlfiles(backup_folder)
                st.success("XML files backed up successfully!")
                st.rerun()
            except Exception as e:
                st.error(f"Error backing up XML files: {str(e)}")

    with col2:
        if st.button("Restore XML Files"):
            try:
                cli_bridge.restore_xmlfiles(backup_folder)
                st.success("XML files restored successfully!")
                st.rerun()
            except Exception as e:
                st.error(f"Error restoring XML files: {str(e)}")

    # Delete workspace
    st.subheader("Delete Workspace")
    if workspace_names:
        if selected_workspace:
            # Remove green dot from workspace name for processing
            selected_workspace = selected_workspace.replace("🟢 ", "")
            if st.button("Delete Selected Workspace"):
                try:
                    cli_bridge.delete_workspace(selected_workspace)
                    st.success(
                        f"Workspace '{selected_workspace}' deleted successfully!")
                    cli_bridge.update_workspaces()
                    st.rerun()
                except Exception as e:
                    st.error(f"Error deleting workspace: {str(e)}")

    # Copy workspace
    st.subheader("Copy Workspace")
    col1, col2 = st.columns(2)
    with col1:
        destination_path = st.text_input(
            "Destination Path",
            label_visibility="visible"
        )
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

    # Show success message from session state if it exists
    if 'workspace_success' in st.session_state:
        st.success(st.session_state.workspace_success)
        # Clear the success message after showing it
        del st.session_state.workspace_success
