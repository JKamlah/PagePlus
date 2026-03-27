import json
import streamlit as st
from pageplus.gui.utils.pipeline_manager import PipelineManager
from pageplus.gui.views.gemini_views.utils import get_available_models

# Try to import streamlit-flow-component
try:
    from streamlit_flow import streamlit_flow
    from streamlit_flow.elements import StreamlitFlowNode, StreamlitFlowEdge
    from streamlit_flow.state import StreamlitFlowState
    from streamlit_flow.layouts import TreeLayout
    STREAMLIT_FLOW_AVAILABLE = True
except ImportError:
    STREAMLIT_FLOW_AVAILABLE = False
    # Create placeholder objects for type hints
    StreamlitFlowNode = None
    StreamlitFlowEdge = None
    StreamlitFlowState = None
    TreeLayout = None
    streamlit_flow = None


# Stage type icons and colors
STAGE_TYPES = {
    "All-in-One": {"icon": "🎯", "color": "#4CAF50", "desc": "Complete OCR in a single step"},
    "Segmentation": {"icon": "✂️", "color": "#FF9800", "desc": "Layout detection only"},
    "Field-Tagging": {"icon": "🏷️", "color": "#2196F3", "desc": "Classify regions and lines"},
    "Text Recognition": {"icon": "📝", "color": "#9C27B0", "desc": "Extract text from layout"},
    "Table Recognition": {"icon": "📊", "color": "#00BCD4", "desc": "Table-specific processing"}
}

CATEGORY_COLORS = {
    "OCR": "#4CAF50",
    "ReOCR": "#FF5722"
}


def get_stage_icon_and_color(stage_type: str):
    """Get icon and color for a stage type."""
    return STAGE_TYPES.get(stage_type, {"icon": "📄", "color": "#9E9E9E"})


def create_stage_node(stage_id: str, stage: dict, collection_name: str, position: tuple = (0, 0)):
    """Create a StreamlitFlowNode from a stage."""
    stage_info = get_stage_icon_and_color(stage.get('type', 'All-in-One'))
    category_color = CATEGORY_COLORS.get(stage.get('category', 'OCR'), "#9E9E9E")

    # Create node label with icon and stage info
    label = f"{stage_info['icon']} {stage.get('name', 'Unnamed')}"

    node = StreamlitFlowNode(
        id=stage_id,
        pos=position,
        data={
            'content': label,
            'stage_name': stage.get('name', 'Unnamed'),
            'stage_type': stage.get('type', 'Unknown'),
            'collection': collection_name,
            'stage_id': stage.get('id'),
            'category': stage.get('category', 'OCR'),
            'system_prompt': stage.get('system_prompt', ''),
            'icon': stage_info['icon']
        },
        node_type='default',
        source_position='right',
        target_position='left',
        style={
            'background': stage_info['color'],
            'color': 'white',
            'border': f"2px solid {category_color}",
            'borderRadius': '8px',
            'padding': '10px',
            'fontSize': '14px',
            'fontWeight': 'bold'
        },
        draggable=True
    )
    return node


def pipeline_flow_editor_view():
    """Pipeline editor using node-based flow diagram."""
    st.subheader("Pipeline Manager")

    # Check if streamlit-flow is available
    if not STREAMLIT_FLOW_AVAILABLE:
        st.error("🚫 streamlit-flow-component is not installed!")
        st.info("""
        **To use the node-based pipeline editor, please install streamlit-flow-component:**

        ```bash
        pip install streamlit-flow-component
        ```

        Or if you're using Poetry:

        ```bash
        poetry add streamlit-flow-component
        ```

        After installation, restart the application.
        """)
        st.warning("Falling back to basic pipeline view...")
        _basic_pipeline_view()
        return

    # Initialize pipeline manager
    manager = PipelineManager()

    # Pipeline selector and management
    col1, col2 = st.columns([3, 1])

    with col1:
        pipeline_names = manager.get_pipeline_names()
        selected_pipeline = st.selectbox(
            "Select Pipeline",
            ["Create New..."] + pipeline_names,
            key="selected_pipeline_flow"
        )

    with col2:
        if st.button("➕ New Pipeline", use_container_width=True, key="new_pipeline_flow_btn"):
            st.session_state.show_new_pipeline_dialog_flow = True

    # New pipeline dialog
    if st.session_state.get('show_new_pipeline_dialog_flow', False):
        with st.form("new_pipeline_form_flow"):
            st.write("**Create New Pipeline**")
            new_pipe_name = st.text_input("Pipeline Name", key="new_pipe_name_flow")
            new_pipe_desc = st.text_area("Description", key="new_pipe_desc_flow")
            new_pipe_category = st.selectbox("Category", ["OCR", "ReOCR"], key="new_pipe_cat_flow")

            col1, col2 = st.columns(2)
            with col1:
                if st.form_submit_button("Create", use_container_width=True):
                    if new_pipe_name and new_pipe_name not in pipeline_names:
                        manager.create_pipeline(new_pipe_name, new_pipe_category, new_pipe_desc)
                        manager.save_data()
                        st.success(f"Pipeline '{new_pipe_name}' created!")
                        st.session_state.show_new_pipeline_dialog_flow = False
                        st.rerun()
                    else:
                        st.error("Invalid or duplicate pipeline name!")
            with col2:
                if st.form_submit_button("Cancel", use_container_width=True):
                    st.session_state.show_new_pipeline_dialog_flow = False
                    st.rerun()

    if selected_pipeline == "Create New...":
        st.info("👆 Click 'New Pipeline' to create one!")
        return

    st.markdown("---")

    # Get pipeline data
    pipeline_data = manager.get_pipeline(selected_pipeline)

    # Pipeline info
    col1, col2 = st.columns([3, 1])
    with col1:
        pipe_desc = st.text_area(
            "Description",
            value=pipeline_data.get('description', ''),
            key="pipeline_desc_flow"
        )
        if st.button("💾 Save Description", use_container_width=True, key="save_pipe_info_flow"):
            manager.update_pipeline(selected_pipeline, description=pipe_desc)
            manager.save_data()
            st.success("Pipeline description updated!")
            st.rerun()

    with col2:
        st.text_input(
            "Category",
            value=pipeline_data.get('category', 'N/A'),
            key="pipeline_category_display",
            disabled=True,
            help="The pipeline category is determined by the first stage."
        )

    st.markdown("---")

    # Two-column layout: Stage Library | Flow Diagram
    col_library, col_flow = st.columns([1, 2])

    with col_library:
        st.write("**📚 Stage Library**")

        c1, c2 = st.columns(2)
        with c1:
            # Filter by collection
            collection_names = manager.get_collection_names()
            filter_collection = st.selectbox(
                "Collection",
                ["All"] + collection_names,
                key="flow_collection_filter"
            )
        with c2:
            # Filter by category
            filter_category = st.selectbox(
                "Category",
                ["All", "OCR", "ReOCR"],
                key="flow_category_filter"
            )

        # Get and display stages
        if filter_collection == "All":
            available_stages = []
            for coll in collection_names:
                stages = manager.get_stages_in_collection(coll)
                available_stages.extend([(s, coll) for s in stages])
        else:
            stages = manager.get_stages_in_collection(filter_collection)
            available_stages = [(s, filter_collection) for s in stages]
        
        # Apply category filter
        if filter_category != "All":
            available_stages = [
                (s, c) for s, c in available_stages if s.get('category') == filter_category
            ]

        # Display available stages as clickable buttons
        if available_stages:
            for stage, coll in available_stages:
                stage_info = get_stage_icon_and_color(stage.get('type', 'All-in-One'))
                if st.button(
                    f"{stage_info['icon']} {stage.get('name', 'Unnamed')}",
                    key=f"add_stage_{coll}_{stage.get('id')}",
                    use_container_width=True,
                    help=f"Add to pipeline: {stage.get('type')} from {coll}"
                ):
                    _add_stage_to_flow(manager, selected_pipeline, stage, coll)
                    st.rerun()

            st.caption(f"{len(available_stages)} stage(s) available")
        else:
            st.info(f"No stages found for the selected filters.")

    with col_flow:
        st.write("**⚙️ Pipeline Flow**")

        pipeline_stages = pipeline_data.get('stages', [])
        
        # Use simple key - just pipeline name
        flow_key = f"flow_{selected_pipeline}"
        
        # Create a version string to detect changes
        version_key = f"{flow_key}_version"
        current_version = json.dumps([(s.get('collection'), s.get('stage_id')) for s in pipeline_stages])
        flow_state_key = f"{flow_key}_state_object"

        if not pipeline_stages:
            st.info("Pipeline is empty. Add stages from the left!")
            # Cleanup state for this pipeline
            for key in [version_key, flow_state_key]:
                if key in st.session_state:
                    del st.session_state[key]
        
        elif pipeline_stages:
            # Only rebuild flow state object if version changed
            if version_key not in st.session_state or st.session_state[version_key] != current_version:
                st.session_state[version_key] = current_version
                
                # Create nodes and edges from pipeline stages
                nodes = []
                edges = []

                x_offset = 100
                y_offset = 100
                x_spacing = 250

                for idx, stage_ref in enumerate(pipeline_stages):
                    coll_name = stage_ref.get('collection')
                    stage_id = stage_ref.get('stage_id')
                    stage = manager.get_stage_by_id(coll_name, stage_id)

                    if stage:
                        node_id = f"stage_{idx}"
                        x_pos = x_offset + (idx * x_spacing)
                        y_pos = y_offset

                        node = create_stage_node(
                            node_id,
                            stage,
                            coll_name,
                            position=(x_pos, y_pos)
                        )
                        nodes.append(node)

                        if idx > 0:
                            edge = StreamlitFlowEdge(
                                id=f"edge_{idx-1}_{idx}",
                                source=f"stage_{idx-1}",
                                target=node_id,
                                animated=True,
                                style={'stroke': '#2196F3', 'strokeWidth': 2}
                            )
                            edges.append(edge)

                # Create and store the new FlowState object
                st.session_state[flow_state_key] = StreamlitFlowState(nodes, edges)

            # Use the stored FlowState object
            flow_state = st.session_state.get(flow_state_key)

            if flow_state:
                # Render the flow - streamlit_flow handles state internally via key
                try:
                    updated_state = streamlit_flow(
                        flow_key,
                        flow_state,
                        layout=TreeLayout(direction='right'),
                        fit_view=True,
                        height=500,
                        enable_node_menu=False,
                        enable_edge_menu=False,
                        enable_pane_menu=False,
                        get_edge_on_click=False,
                        get_node_on_click=True,
                        hide_watermark=True,
                        allow_new_edges=False,
                        min_zoom=0.5
                    )

                    # Handle node selection and interactions
                    # Access state as dictionary if it's a dict, otherwise as object
                    selected_id = updated_state.get('selected_id') if isinstance(updated_state, dict) else getattr(updated_state, 'selected_id', None)
                    
                    # Only show details if we have a valid selection
                    if selected_id and isinstance(selected_id, str):
                        st.write(f"**Selected Node:** {selected_id}")

                        # Find the selected node's index
                        selected_idx = None
                        if selected_id.startswith("stage_"):
                            try:
                                selected_idx = int(selected_id.split("_")[1])
                            except (ValueError, IndexError):
                                pass

                        if selected_idx is not None and 0 <= selected_idx < len(pipeline_stages):
                            stage_ref = pipeline_stages[selected_idx]
                            coll_name = stage_ref.get('collection')
                            stage_id = stage_ref.get('stage_id')
                            stage = manager.get_stage_by_id(coll_name, stage_id)

                            if stage:
                                # Display stage details
                                with st.expander("📋 Stage Details", expanded=True):
                                    st.write(f"**Name:** {stage.get('name')}")
                                    st.write(f"**Type:** {stage.get('type')}")
                                    st.write(f"**Collection:** {coll_name}")
                                    st.write(f"**Category:** {stage.get('category')}")
                                    
                                    # Show if there are overrides
                                    if stage_ref.get('attributes') or stage_ref.get('filters'):
                                        st.info("⚙️ This stage has active overrides.")

                                    # Action buttons
                                    c1, c2, c3, c4 = st.columns(4)

                                    with c1:
                                        if selected_idx > 0 and st.button("⬆️", help="Move Up", key="move_up_flow"):
                                            # If moving a stage to the first position, update pipeline category
                                            if selected_idx - 1 == 0:
                                                new_first_stage = manager.get_stage_by_id(stage_ref.get('collection'), stage_ref.get('stage_id'))
                                                if new_first_stage:
                                                    manager.update_pipeline(selected_pipeline, category=new_first_stage.get('category'))
                                            
                                            manager.reorder_pipeline_stages(selected_pipeline, selected_idx, selected_idx - 1)
                                            manager.save_data()
                                            st.rerun()

                                    with c2:
                                        if selected_idx < len(pipeline_stages) - 1 and st.button("⬇️", help="Move Down", key="move_down_flow"):
                                            # If moving the first stage down, update pipeline category
                                            if selected_idx == 0:
                                                next_stage_ref = pipeline_stages[selected_idx + 1]
                                                new_first_stage = manager.get_stage_by_id(next_stage_ref.get('collection'), next_stage_ref.get('stage_id'))
                                                if new_first_stage:
                                                    manager.update_pipeline(selected_pipeline, category=new_first_stage.get('category'))

                                            manager.reorder_pipeline_stages(selected_pipeline, selected_idx, selected_idx + 1)
                                            manager.save_data()
                                            st.rerun()

                                    with c3:
                                        if st.button("❌", help="Remove", key="remove_flow"):
                                            # If removing the first stage, update category from the next one
                                            if selected_idx == 0 and len(pipeline_stages) > 1:
                                                next_stage_ref = pipeline_stages[1]
                                                new_first_stage = manager.get_stage_by_id(next_stage_ref.get('collection'), next_stage_ref.get('stage_id'))
                                                if new_first_stage:
                                                    manager.update_pipeline(selected_pipeline, category=new_first_stage.get('category'))
                                            
                                            manager.remove_stage_from_pipeline(selected_pipeline, selected_idx)
                                            
                                            # If pipeline becomes empty, reset category to a default
                                            if len(pipeline_stages) == 1:
                                                 manager.update_pipeline(selected_pipeline, category="OCR")

                                            manager.save_data()
                                            st.rerun()

                                    with c4:
                                        if st.button("⚙️", help="Configure Overrides", key="config_overrides_flow"):
                                            st.session_state[f"show_overrides_{selected_idx}"] = not st.session_state.get(f"show_overrides_{selected_idx}", False)
                                            st.rerun()

                                # Override Editor Form
                                if st.session_state.get(f"show_overrides_{selected_idx}", False):
                                    _render_override_editor(manager, selected_pipeline, selected_idx, stage, stage_ref)

                                # Show system prompt
                                st.text_area(
                                    "System Prompt",
                                    value=stage.get('system_prompt', ''),
                                    height=150,
                                    disabled=True,
                                    key=f"stage_prompt_display_flow_{selected_idx}"
                                )

                except Exception as e:
                    st.error(f"Error rendering flow: {e}")
                    st.info("Try refreshing the page or recreating the pipeline.")
                    
                    # Debug information
                    with st.expander("🔍 Debug Information"):
                        st.write("**Error Type:**", type(e).__name__)
                        st.write("**Error Message:**", str(e))
                        st.write("**Pipeline Stages:**", len(pipeline_stages))
                        st.write("**Nodes Created:**", len(nodes) if 'nodes' in locals() else "N/A")
                        st.write("**Edges Created:**", len(edges) if 'edges' in locals() else "N/A")
                        if 'updated_state' in locals():
                            st.write("**State Type:**", type(updated_state))
                            if isinstance(updated_state, dict):
                                st.write("**State Keys:**", list(updated_state.keys()))
                        import traceback
                        st.code(traceback.format_exc())

    st.markdown("---")

    # Export/Import and Delete
    col1, col2, col3 = st.columns(3)

    with col1:
        if st.button("📤 Export Pipeline", use_container_width=True, key="export_pipe_flow"):
            export_data = manager.export_pipeline(selected_pipeline)
            if export_data:
                st.download_button(
                    label="📥 Download JSON",
                    data=json.dumps(export_data, indent=4, ensure_ascii=False),
                    file_name=f"{selected_pipeline}.json",
                    mime="application/json",
                    key="download_pipeline_flow_btn"
                )

    with col2:
        uploaded_file = st.file_uploader(
            "📂 Import Pipeline",
            type=['json'],
            key="import_pipeline_flow_uploader",
            label_visibility="collapsed"
        )
        if uploaded_file is not None:
            try:
                import_data = json.load(uploaded_file)
                if st.button("✅ Confirm Import", key="confirm_import_flow"):
                    success = manager.import_pipeline(import_data)
                    if success:
                        manager.save_data()
                        st.success("Pipeline imported successfully!")
                        st.rerun()
                    else:
                        st.error("Failed to import pipeline!")
            except json.JSONDecodeError:
                st.error("Invalid JSON file!")

    with col3:
        if st.button("🗑️ Delete Pipeline", use_container_width=True, type="secondary", key="delete_pipe_flow"):
            if manager.delete_pipeline(selected_pipeline):
                manager.save_data()
                st.success(f"Pipeline '{selected_pipeline}' deleted!")
                st.rerun()


def _add_stage_to_flow(manager, pipeline_name, stage, collection_name):
    """Add a stage to the pipeline and update category if it's the first one."""
    pipeline = manager.get_pipeline(pipeline_name)
    is_first_stage = not pipeline.get('stages')

    manager.add_stage_to_pipeline(pipeline_name, collection_name, stage.get('id'))
    
    # If it's the first stage, set the pipeline's category
    if is_first_stage:
        manager.update_pipeline(pipeline_name, category=stage.get('category'))

    manager.save_data()
    st.success(f"Added '{stage.get('name')}' to pipeline!")
    st.rerun()


def _render_override_editor(manager, pipeline_name, stage_idx, stage_defaults, stage_ref):
    """Renders the form for editing stage overrides within a pipeline."""
    st.markdown("---")
    st.write(f"#### ⚙️ Overrides for `{stage_defaults.get('name')}`")
    st.caption("These settings apply only to this stage within this pipeline.")

    # Get default and overridden values
    from pageplus.gui.utils.settings import Settings
    settings = Settings()
    settings_thinking_budget = int(settings.get("THINKING_BUDGET", "0"))
    
    default_attrs = stage_defaults.get('attributes', {})
    override_attrs = stage_ref.get('attributes', {})
    
    default_filters = stage_defaults.get('filters', {})
    override_filters = stage_ref.get('filters', {})

    # --- ATTRIBUTES ---
    with st.container():
        st.write("**Advanced Attributes**")

        # Model
        available_models = get_available_models()
        model_options = ["(Use Stage Default)"] + available_models
        
        default_model = default_attrs.get('model')
        current_model_override = override_attrs.get('model')
        
        # Determine the selectbox index
        model_display = current_model_override or "(Use Stage Default)"
        model_index = 0
        if model_display in model_options:
            model_index = model_options.index(model_display)
        
        override_model = st.selectbox(
            "Model Override",
            options=model_options,
            index=model_index,
            key=f"override_model_{stage_idx}",
            help=f"Stage default: {default_model or 'Default Model'}"
        )

        # Thinking Budget
        default_thinking = default_attrs.get('thinking_budget', settings_thinking_budget)
        override_thinking = st.number_input(
            "Thinking Budget Override",
            min_value=0,
            value=override_attrs.get('thinking_budget', default_thinking),
            key=f"override_thinking_{stage_idx}",
            help=f"Stage default: {default_thinking}"
        )

    # --- FILTERS ---
    with st.container():
        st.write("**Stage Options**")
        
        # Update Elements
        default_update = default_filters.get('update_elements', [])
        override_update = st.multiselect(
            "Update Elements Override",
            options=["Text", "Tags"],
            default=override_filters.get('update_elements', default_update),
            key=f"override_update_{stage_idx}",
            help=f"Stage default: {default_update}"
        )

        # Recognize Level
        default_rec_level = default_filters.get('recognize_level', 'TextRegion')
        rec_level_options = ["(Use Stage Default)", "Page", "TextRegion", "Textline"]
        
        current_rec_level = override_filters.get('recognize_level') or "(Use Stage Default)"
        rec_level_index = 0
        if current_rec_level in rec_level_options:
            rec_level_index = rec_level_options.index(current_rec_level)
            
        override_rec_level = st.selectbox(
            "Recognize Level Override",
            options=rec_level_options,
            index=rec_level_index,
            key=f"override_rec_level_{stage_idx}",
            help=f"Stage default: {default_rec_level}"
        )

    # --- SAVE BUTTON ---
    if st.button("💾 Save Overrides", key=f"save_overrides_{stage_idx}"):
        # --- Build final overrides ---
        final_override_attrs = {}
        # Model
        if override_model != "(Use Stage Default)":
            final_override_attrs['model'] = override_model
        # Thinking Budget
        if override_thinking != default_thinking:
            final_override_attrs['thinking_budget'] = override_thinking

        final_override_filters = {}
        # Update Elements
        if set(override_update) != set(default_update):
            final_override_filters['update_elements'] = override_update
        # Recognize Level
        if override_rec_level != "(Use Stage Default)":
            final_override_filters['recognize_level'] = override_rec_level
            
        # --- Update pipeline data ---
        pipeline_data = manager.get_pipeline(pipeline_name)
        stages = pipeline_data.get('stages', [])
        if 0 <= stage_idx < len(stages):
            stages[stage_idx]['attributes'] = final_override_attrs
            stages[stage_idx]['filters'] = final_override_filters
            
            manager.update_pipeline(pipeline_name, stages=stages)
            manager.save_data()
            st.success(f"Overrides for '{stage_defaults.get('name')}' saved!")
            # Hide the form after saving
            st.session_state[f"show_overrides_{stage_idx}"] = False
            st.rerun()

def _basic_pipeline_view():
    """Basic pipeline view without flow diagram (fallback when streamlit-flow is not available)."""
    manager = PipelineManager()

    # Pipeline selector
    pipeline_names = manager.get_pipeline_names()

    if not pipeline_names:
        st.info("No pipelines found. Create one first.")
        return

    selected_pipeline = st.selectbox(
        "Select Pipeline",
        pipeline_names,
        key="basic_pipeline_select"
    )

    if selected_pipeline:
        pipeline_data = manager.get_pipeline(selected_pipeline)
        pipeline_stages = pipeline_data.get('stages', [])

        st.write(f"**Pipeline:** {selected_pipeline}")
        st.write(f"**Description:** {pipeline_data.get('description', 'No description')}")
        st.write(f"**Category:** {pipeline_data.get('category', 'OCR')}")

        if not pipeline_stages:
            st.info("Pipeline is empty.")
        else:
            st.write(f"**Stages ({len(pipeline_stages)}):**")

            for idx, stage_ref in enumerate(pipeline_stages):
                coll_name = stage_ref.get('collection')
                stage_id = stage_ref.get('stage_id')
                stage = manager.get_stage_by_id(coll_name, stage_id)

                if stage:
                    stage_info = get_stage_icon_and_color(stage.get('type', 'All-in-One'))
                    st.markdown(f"{idx + 1}. {stage_info['icon']} **{stage.get('name')}** ({stage.get('type')}) - {coll_name}")
                else:
                    st.error(f"{idx + 1}. Broken reference: {coll_name}/{stage_id}")

