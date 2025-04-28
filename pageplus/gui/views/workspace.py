import streamlit as st
from pageplus.utils.workspace import Workspace
from pageplus.utils.constants import Environments

def show_workspace(cli_bridge):
    """Display workspace management page."""
    st.title("🗂️ Workspace Management")
    
    # Get available workspaces and loaded workspace
    try:
        ws = Workspace(Environments.PAGEPLUS)
        workspace_names = ws.names()
        loaded_workspace = ws.loaded() if ws.loaded() else None
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
                        st.success(f"Workspace '{selected_workspace}' loaded successfully!")
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
    backup_folder = st.text_input("Backup Folder", value="Backup")
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
        workspace_to_delete = st.selectbox(
            "Select Workspace to Delete",
            options=workspace_options if 'workspace_options' in locals() else workspace_names,
            index=None
        )
        if workspace_to_delete:
            # Remove green dot from workspace name for processing
            workspace_to_delete = workspace_to_delete.replace("🟢 ", "")
            if st.button("Delete Selected Workspace"):
                try:
                    cli_bridge.delete_workspace(workspace_to_delete)
                    st.success(f"Workspace '{workspace_to_delete}' deleted successfully!")
                    st.rerun()
                except Exception as e:
                    st.error(f"Error deleting workspace: {str(e)}")
    
    # Copy workspace
    st.subheader("Copy Workspace")
    col1, col2 = st.columns(2)
    with col1:
        destination_path = st.text_input("Destination Path")
    with col2:
        new_workspace = st.text_input("New Workspace Name (optional)")
    
    if workspace_names:
        workspace_to_copy = st.selectbox(
            "Select Workspace to Copy",
            options=workspace_options if 'workspace_options' in locals() else workspace_names,
            index=None
        )
        if workspace_to_copy:
            # Remove green dot from workspace name for processing
            workspace_to_copy = workspace_to_copy.replace("🟢 ", "")
            if st.button("Copy Selected Workspace"):
                try:
                    cli_bridge.copy_workspace(
                        destination_path,
                        workspace_to_copy,
                        new_workspace
                    )
                    st.success("Workspace copied successfully!")
                    st.rerun()
                except Exception as e:
                    st.error(f"Error copying workspace: {str(e)}")
    
    # Load local document
    st.subheader("Load Local Document")
    col1, col2 = st.columns(2)
    with col1:
        input_dir = st.text_input("Input Directory")
    with col2:
        overwrite = st.checkbox("Overwrite Workspace")
    
    if st.button("Load Local Document"):
        try:
            cli_bridge.load_local_document(
                input_dir,
                selected_workspace if 'selected_workspace' in locals() else None,
                overwrite
            )
            st.success("Local document loaded successfully!")
            st.rerun()
        except Exception as e:
            st.error(f"Error loading local document: {str(e)}") 