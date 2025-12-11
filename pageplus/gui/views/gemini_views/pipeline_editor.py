import json
import streamlit as st
from pageplus.gui.utils.pipeline_manager import PipelineManager
from pageplus.gui.views.gemini_views.pipeline_flow_editor import pipeline_flow_editor_view
from pageplus.gui.views.gemini_views.utils import get_available_models


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


def render_stage_card(stage, collection_name, on_edit=None, on_delete=None, on_select=None, compact=False):
    """Render a visual stage card."""
    stage_info = get_stage_icon_and_color(stage.get('type', 'All-in-One'))
    category_color = CATEGORY_COLORS.get(stage.get('category', 'OCR'), "#9E9E9E")

    if compact:
        # Compact version for pipeline builder
        with st.container():
            col1, col2, col3 = st.columns([0.5, 3, 0.5])
            with col1:
                st.markdown(f"<div style='font-size: 2em;'>{stage_info['icon']}</div>", unsafe_allow_html=True)
            with col2:
                st.markdown(f"**{stage.get('name', 'Unnamed')}**")
                st.caption(f"{stage.get('type', 'Unknown')} · {collection_name}")
            with col3:
                if on_select and st.button("➕", key=f"select_{stage.get('id')}"):
                    on_select(stage, collection_name)
    else:
        # Full card version - more compact
        with st.container():
            st.markdown(f"""
                <div style='
                    border: 2px solid {stage_info['color']};
                    border-radius: 8px;
                    padding: 10px;
                    margin: 8px 0;
                    background: linear-gradient(135deg, {stage_info['color']}12 0%, {stage_info['color']}03 100%);
                '>
                    <div style='display: flex; align-items: center; margin-bottom: 8px;'>
                        <span style='font-size: 2em; margin-right: 12px;'>{stage_info['icon']}</span>
                        <div style='flex: 1;'>
                            <h4 style='margin: 0; color: #333;'>{stage.get('name', 'Unnamed')}</h4>
                            <p style='margin: 3px 0 0 0; color: #666; font-size: 0.85em;'>
                                <span style='background: {category_color}; color: white; padding: 2px 6px; border-radius: 3px; margin-right: 5px; font-size: 0.85em;'>
                                    {stage.get('category', 'OCR')}
                                </span>
                                {stage.get('type', 'Unknown')} · {collection_name}
                            </p>
                        </div>
                    </div>
                </div>
            """, unsafe_allow_html=True)

            # Action buttons (use collection_name in key to ensure uniqueness)
            col1, col2, col3 = st.columns(3)
            with col1:
                if on_edit and st.button("✏️ Edit", key=f"edit_{collection_name}_{stage.get('id')}", use_container_width=True):
                    on_edit(stage, collection_name)
            with col2:
                if on_delete and st.button("🗑️ Delete", key=f"delete_{collection_name}_{stage.get('id')}", use_container_width=True):
                    on_delete(stage)
            with col3:
                if on_select and st.button("➕ Add to Pipeline", key=f"add_{collection_name}_{stage.get('id')}", use_container_width=True):
                    on_select(stage, collection_name)


def pipeline_editor_view():
    """Main view for the Gemini pipeline editor with improved UX."""
    st.header("✨ Gemini Pipeline Builder")

    # Initialize pipeline manager
    manager = PipelineManager()

    # Create tabs
    tab1, tab2 = st.tabs(["📋 Stages", "⚙️ Pipelines"])

    with tab1:
        _stages_tab(manager)

    with tab2:
        # Use the new flow-based pipeline editor
        pipeline_flow_editor_view()


def _stages_tab(manager: PipelineManager):
    """Enhanced Stages tab with visual cards."""
    st.subheader("Stage Library")

    # Collection selector and management
    col1, col2, col3 = st.columns([2, 2, 1])

    with col1:
        collection_names = manager.get_collection_names()
        collection_filter = st.selectbox(
            "📁 Collection",
            ["All Collections"] + collection_names,
            key="collection_filter"
        )

    with col2:
        category_filter = st.selectbox(
            "🏷️ Category",
            ["All Categories", "OCR", "ReOCR"],
            key="category_filter"
        )

    with col3:
        if st.button("➕ New Collection", use_container_width=True):
            st.session_state.show_new_collection_dialog = True

    # New collection dialog
    if st.session_state.get('show_new_collection_dialog', False):
        with st.form("new_collection_form"):
            st.write("**Create New Collection**")
            new_coll_name = st.text_input("Collection Name")
            new_coll_desc = st.text_area("Description (optional)")

            col1, col2 = st.columns(2)
            with col1:
                if st.form_submit_button("Create", use_container_width=True):
                    if new_coll_name and new_coll_name not in collection_names:
                        manager.create_collection(new_coll_name, new_coll_desc)
                        manager.save_data()
                        st.success(f"Collection '{new_coll_name}' created!")
                        st.session_state.show_new_collection_dialog = False
                        st.rerun()
                    else:
                        st.error("Invalid or duplicate collection name!")
            with col2:
                if st.form_submit_button("Cancel", use_container_width=True):
                    st.session_state.show_new_collection_dialog = False
                    st.rerun()

    st.markdown("---")

    # Get filtered stages
    all_stages = []
    if collection_filter == "All Collections":
        for coll_name in collection_names:
            stages = manager.get_stages_in_collection(coll_name)
            for stage in stages:
                all_stages.append((stage, coll_name))
    else:
        stages = manager.get_stages_in_collection(collection_filter)
        all_stages = [(stage, collection_filter) for stage in stages]

    # Apply category filter
    if category_filter != "All Categories":
        all_stages = [(s, c) for s, c in all_stages if s.get('category') == category_filter]

    # Display stages
    if all_stages:
        st.write(f"**{len(all_stages)} stage(s) found**")

        editing_stage_id = st.session_state.get('editing_stage', {}).get('id')

        for stage, coll_name in all_stages:
            # Highlight if this stage is being edited
            is_editing = stage.get('id') == editing_stage_id

            if is_editing:
                st.markdown("**✏️ Currently Editing:**")

            render_stage_card(
                stage, 
                coll_name,
                on_edit=lambda s, c: _edit_stage(manager, c, s),
                on_delete=lambda s: _delete_stage(manager, coll_name, s)
            )
    else:
        st.info("No stages found. Create one below!")

    st.markdown("---")

    # Stage creator/editor
    editing_stage = st.session_state.get('editing_stage')
    editing_collection = st.session_state.get('editing_collection')

    if editing_stage:
        st.subheader(f"✏️ Edit Stage: {editing_stage.get('name', 'Unnamed')}")
    else:
        st.subheader("✏️ Create New Stage")

    # Select collection for new stage
    if collection_names:
        # If editing, use the editing_collection as default
        default_index = 0
        if editing_collection and editing_collection in collection_names:
            default_index = collection_names.index(editing_collection)

        target_collection = st.selectbox(
            "Collection",
            collection_names,
            index=default_index,
            key="stage_target_collection"
        )

        _stage_editor_form(manager, target_collection)
    else:
        st.warning("Please create a collection first!")


def _stage_editor_form(manager: PipelineManager, collection_name: str):
    """Form for creating/editing a stage."""

    # Check if editing
    editing_stage = st.session_state.get('editing_stage')
    editing_stage_id = editing_stage.get('id') if editing_stage else 'new'

    # Use unique keys based on editing state to force refresh
    key_suffix = f"_edit_{editing_stage_id}" if editing_stage else "_new"

    # Get default thinking budget from settings
    from pageplus.gui.utils.settings import Settings
    settings = Settings()
    settings_thinking_budget = int(settings.get("THINKING_BUDGET", "0"))

    # Get default values
    if editing_stage:
        default_name = editing_stage.get('name', '')
        default_category = editing_stage.get('category', 'OCR')
        default_type = editing_stage.get('type', 'All-in-One')
        default_system_prompt = editing_stage.get('system_prompt', '')
        default_user_prompt = editing_stage.get('user_prompt', '<|input|>\\n')
        default_attributes = editing_stage.get('attributes', {})
        default_filters = editing_stage.get('filters', {})
        default_thinking_budget = default_attributes.get('thinking_budget', settings_thinking_budget)
        default_temperature = default_attributes.get('temperature', 0.000001)
        default_model = default_attributes.get('model') or 'Use Default Model'
        default_update_elements = default_filters.get('update_elements', ["Text", "Tags"])
        default_tag_filter = ", ".join(default_filters.get('tag_filter', []))
        default_region_types = ", ".join(default_filters.get('region_types', []))
    else:
        default_name = ''
        default_category = 'OCR'
        default_type = 'All-in-One'
        default_system_prompt = ''
        default_user_prompt = '<|input|>\\n'
        default_thinking_budget = settings_thinking_budget  # Use settings default
        default_temperature = 0.000001
        default_model = 'Use Default Model'
        default_attributes = {}
        default_filters = {}
        default_update_elements = ["Text", "Tags"]
        default_tag_filter = ''
        default_region_types = ''

    stage_name = st.text_input(
        "Stage Name",
        value=default_name,
        key=f"stage_name_input{key_suffix}"
    )

    col1, col2 = st.columns(2)
    with col1:
        category_index = 0 if default_category == "OCR" else 1
        stage_category = st.selectbox(
            "Category",
            ["OCR", "ReOCR"],
            index=category_index,
            key=f"stage_category_input{key_suffix}"
        )

    with col2:
        stage_type_options = list(STAGE_TYPES.keys())
        stage_type_index = stage_type_options.index(default_type) if default_type in stage_type_options else 0

        stage_type = st.selectbox(
            "Stage Type",
            stage_type_options,
            index=stage_type_index,
            key=f"stage_type_input{key_suffix}",
            help=STAGE_TYPES[stage_type_options[stage_type_index]]["desc"]
        )

        # Show icon and description
        type_info = STAGE_TYPES[stage_type]
        st.caption(f"{type_info['icon']} {type_info['desc']}")

    system_prompt = st.text_area(
        "System Prompt",
        value=default_system_prompt,
        height=250,
        key=f"system_prompt_input{key_suffix}",
        help="The main instruction for the AI model"
    )

    # User prompt is fixed and not editable
    user_prompt = '<|input|>\\n'
    st.text_input(
        "User Prompt",
        value=user_prompt,
        disabled=True,
        key=f"user_prompt_display{key_suffix}",
        help="Fixed user prompt template"
    )

    # Attributes and filters in expanders
    with st.expander("⚙️ Advanced Attributes", expanded=bool(editing_stage)):
        # Model selection
        # Get cached models
        available_models = get_available_models()

        # Prepare model options with "Use Default Model" at the top
        model_options = ["Use Default Model"] + available_models

        # Find index
        try:
            model_index = model_options.index(default_model)
        except ValueError:
            model_index = 0  # Default to "Use Default Model"

        selected_model = st.selectbox(
            "Model",
            options=model_options,
            index=model_index,
            key=f"model_attr{key_suffix}",
            help="Select a specific model or use the default configured model. Update models in Settings tab."
        )

        thinking_budget = st.number_input(
            "Thinking Budget (tokens)",
            min_value=0,
            value=default_thinking_budget,
            key=f"thinking_budget_attr{key_suffix}"
        )

        temperature = st.number_input(
            "Temperature",
            min_value=0.0,
            max_value=2.0,
            value=default_temperature,
            format="%.6f",
            key=f"temperature_attr{key_suffix}"
        )

    with st.expander("🔧 Stage Options", expanded=bool(editing_stage)):
        # Stage type specific options
        update_elements = []
        recognize_as = None

        if stage_type == "Segmentation":
            # Segmentation: Update elements (default: Tags only) + Recognize Level
            default_seg_update = default_filters.get('update_elements', ["Tags"])
            update_elements = st.multiselect(
                "Update Elements",
                ["Text", "Tags"],
                default=default_seg_update,
                key=f"update_elements_filter{key_suffix}"
            )

            default_recognize_level = default_filters.get('recognize_level', 'TextRegion')
            recognize_level = st.selectbox(
                "Recognize Level",
                ["Page", "TextRegion", "Textline"],
                index=["Page", "TextRegion", "Textline"].index(default_recognize_level) if default_recognize_level in ["Page", "TextRegion", "Textline"] else 1,
                key=f"recognize_level_filter{key_suffix}"
            )

        elif stage_type == "Text Recognition":
            # Text Recognition: Update elements (default: Tags + Text) + Recognize Level
            default_text_update = default_filters.get('update_elements', ["Tags", "Text"])
            update_elements = st.multiselect(
                "Update Elements",
                ["Text", "Tags"],
                default=default_text_update,
                key=f"update_elements_filter{key_suffix}"
            )

            default_recognize_level = default_filters.get('recognize_level', 'TextRegion')
            recognize_level = st.selectbox(
                "Recognize Level",
                ["Page", "TextRegion", "Textline"],
                index=["Page", "TextRegion", "Textline"].index(default_recognize_level) if default_recognize_level in ["Page", "TextRegion", "Textline"] else 1,
                key=f"recognize_level_filter{key_suffix}"
            )

        elif stage_type == "Table Recognition":
            # Table Recognition: Update elements (default: Tags + Text) + Recognize As + Recognize Level
            default_table_update = default_filters.get('update_elements', ["Tags", "Text"])
            update_elements = st.multiselect(
                "Update Elements",
                ["Text", "Tags"],
                default=default_table_update,
                key=f"update_elements_filter{key_suffix}"
            )

            default_recognize_as = default_filters.get('recognize_as', 'TextRegion')
            recognize_as = st.selectbox(
                "Recognize As",
                ["TextRegion", "TableStructure"],
                index=["TextRegion", "TableStructure"].index(default_recognize_as) if default_recognize_as in ["TextRegion", "TableStructure"] else 0,
                key=f"recognize_as_filter{key_suffix}"
            )

            default_recognize_level = default_filters.get('recognize_level', 'TextRegion')
            recognize_level = st.selectbox(
                "Recognize Level",
                ["Page", "TextRegion", "Textline"],
                index=["Page", "TextRegion", "Textline"].index(default_recognize_level) if default_recognize_level in ["Page", "TextRegion", "Textline"] else 1,
                key=f"recognize_level_filter{key_suffix}"
            )

        elif stage_type == "Field-Tagging":
            # Field-Tagging: Only Recognize Level
            default_recognize_level = default_filters.get('recognize_level', 'TextRegion')
            recognize_level = st.selectbox(
                "Recognize Level",
                ["Page", "TextRegion", "Textline"],
                index=["Page", "TextRegion", "Textline"].index(default_recognize_level) if default_recognize_level in ["Page", "TextRegion", "Textline"] else 1,
                key=f"recognize_level_filter{key_suffix}"
            )

        elif stage_category == "ReOCR":
            # ReOCR stages (backward compatibility)
            update_elements = st.multiselect(
                "Update Elements",
                ["Text", "Tags"],
                default=default_update_elements,
                key=f"update_elements_filter{key_suffix}"
            )

        # Common filters (for all types)
        st.markdown("**Additional Filters:**")

        tag_filter_text = st.text_input(
            "Tag Filter (comma-separated)",
            value=default_tag_filter,
            key=f"tag_filter_input{key_suffix}"
        )

        region_types_text = st.text_input(
            "Region Types Filter (comma-separated)",
            value=default_region_types,
            key=f"region_types_filter{key_suffix}"
        )

    # Save/Clone/Cancel buttons
    col1, col2, col3 = st.columns([2, 1, 1])

    with col1:
        button_label = "💾 Update Stage" if editing_stage else "💾 Create Stage"
        if st.button(button_label, key=f"save_stage_btn{key_suffix}", type="primary", use_container_width=True):
            if not stage_name or not system_prompt:
                st.error("Stage name and system prompt are required!")
            else:
                # Prepare attributes - only store non-default values
                final_attributes = {}

                # Only store thinking_budget if different from settings default
                if thinking_budget != settings_thinking_budget:
                    final_attributes['thinking_budget'] = thinking_budget

                # Only store temperature if different from default
                if temperature != 0.000001:
                    final_attributes['temperature'] = temperature

                # Only store model if not using default
                if selected_model != "Use Default Model":
                    final_attributes['model'] = selected_model

                final_filters = {}

                # Add stage-type specific filters
                if stage_type in ["Segmentation", "Text Recognition", "Table Recognition"]:
                    if update_elements:
                        final_filters['update_elements'] = update_elements
                    if 'recognize_level' in locals():
                        final_filters['recognize_level'] = recognize_level
                    if stage_type == "Table Recognition" and recognize_as:
                        final_filters['recognize_as'] = recognize_as

                elif stage_type == "Field-Tagging":
                    if 'recognize_level' in locals():
                        final_filters['recognize_level'] = recognize_level

                elif stage_category == "ReOCR":
                    # Backward compatibility for ReOCR category
                    if update_elements:
                        final_filters['update_elements'] = update_elements

                # Add common filters
                if tag_filter_text:
                    final_filters['tag_filter'] = [t.strip() for t in tag_filter_text.split(',') if t.strip()]
                if region_types_text:
                    final_filters['region_types'] = [r.strip() for r in region_types_text.split(',') if r.strip()]

                if editing_stage:
                    # Update existing stage
                    success = manager.update_stage(
                        collection_name=collection_name,
                        stage_id=editing_stage.get('id'),
                        name=stage_name,
                        category=stage_category,
                        stage_type=stage_type,
                        system_prompt=system_prompt,
                        user_prompt=user_prompt,
                        attributes=final_attributes,
                        filters=final_filters
                    )
                    if success:
                        manager.save_data()
                        st.success(f"Stage '{stage_name}' updated!")
                        _cancel_edit()
                else:
                    # Create new stage
                    stage_id = manager.add_stage(
                        collection_name=collection_name,
                        name=stage_name,
                        category=stage_category,
                        stage_type=stage_type,
                        system_prompt=system_prompt,
                        user_prompt=user_prompt,
                        attributes=final_attributes,
                        filters=final_filters
                    )
                    if stage_id:
                        manager.save_data()
                        st.success(f"Stage '{stage_name}' created!")
                        st.rerun()
                    else:
                        st.error("Failed to create stage!")

    with col2:
        if editing_stage and st.button("🔄 Clone", key=f"clone_stage_btn{key_suffix}", use_container_width=True):
            # Create a copy with "(Copy)" suffix
            new_name = f"{stage_name} (Copy)"

            final_filters = {}

            # Add stage-type specific filters
            if stage_type in ["Segmentation", "Text Recognition", "Table Recognition"]:
                if update_elements:
                    final_filters['update_elements'] = update_elements
                if 'recognize_level' in locals():
                    final_filters['recognize_level'] = recognize_level
                if stage_type == "Table Recognition" and recognize_as:
                    final_filters['recognize_as'] = recognize_as

            elif stage_type == "Field-Tagging":
                if 'recognize_level' in locals():
                    final_filters['recognize_level'] = recognize_level

            elif stage_category == "ReOCR":
                # Backward compatibility for ReOCR category
                if update_elements:
                    final_filters['update_elements'] = update_elements

            # Add common filters
            if tag_filter_text:
                final_filters['tag_filter'] = [t.strip() for t in tag_filter_text.split(',') if t.strip()]
            if region_types_text:
                final_filters['region_types'] = [r.strip() for r in region_types_text.split(',') if r.strip()]

            # Prepare clone attributes - only store non-default values
            clone_attributes = {}

            # Only store thinking_budget if different from settings default
            if thinking_budget != settings_thinking_budget:
                clone_attributes['thinking_budget'] = thinking_budget

            # Only store temperature if different from default
            if temperature != 0.000001:
                clone_attributes['temperature'] = temperature

            # Only store model if not using default
            if selected_model != "Use Default Model":
                clone_attributes['model'] = selected_model

            stage_id = manager.add_stage(
                collection_name=collection_name,
                name=new_name,
                category=stage_category,
                stage_type=stage_type,
                system_prompt=system_prompt,
                user_prompt=user_prompt,
                attributes=clone_attributes,
                filters=final_filters
            )
            if stage_id:
                manager.save_data()
                st.success(f"Stage cloned as '{new_name}'!")
                _cancel_edit()

    with col3:
        button_label = "❌ Cancel" if editing_stage else "🔄 Reset"
        if st.button(button_label, key=f"cancel_form_btn{key_suffix}", use_container_width=True):
            if editing_stage:
                _cancel_edit()
            else:
                # Just rerun to reset form
                st.rerun()


def _edit_stage(manager, collection_name, stage):
    """Set up stage for editing."""
    st.session_state.editing_stage = stage
    st.session_state.editing_collection = collection_name
    st.rerun()


def _delete_stage(manager, collection_name, stage):
    """Delete a stage."""
    if manager.delete_stage(collection_name, stage.get('id')):
        manager.save_data()
        st.success(f"Stage '{stage.get('name')}' deleted!")
        st.rerun()


def _cancel_edit():
    """Cancel editing and clear the form."""
    # Clear editing state - dynamic keys will handle the rest
    if 'editing_stage' in st.session_state:
        del st.session_state.editing_stage
    if 'editing_collection' in st.session_state:
        del st.session_state.editing_collection

    st.rerun()


