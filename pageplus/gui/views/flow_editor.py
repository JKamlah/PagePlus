"""
Flow Editor - A node-based workflow editor for building complex document processing pipelines.

This module provides a visual workflow editor that allows users to:
1. Start with XML and Image files as input nodes
2. Add modification tool nodes from the Modification bridge
3. Add Gemini/OCR processing nodes (Gemini, Kraken, Tesseract)
4. Add LLM nodes (extensible for future providers like Google, OpenAI, etc.)
5. Connect nodes to build complex workflows
6. Execute workflows end-to-end

The node system is designed to be extensible - new node types can be added by:
1. Defining the node type in get_available_node_types() or registering it
2. Adding a handler in execute_node()
3. Adding configuration UI in render_node_config()
"""

import json
import re
import time
import uuid
import importlib
from pathlib import Path
from typing import Any, Dict, List, Optional, Callable
import queue
import sys
from io import StringIO
from dataclasses import dataclass, field

import streamlit as st
from pageplus.gui.utils.settings import Settings
from pageplus.gui.utils.pipeline_manager import PipelineManager
from pageplus.gui.views.gemini_views.utils import get_available_models
from pageplus.gui.views.load_files import get_loaded_workspace_dir
from pageplus.gui.utils.picker import pick_files, pick_directory
from pageplus.utils.fs import shuffle
from pageplus.utils.constants import GUI_STORAGE_DIR

# Try to import streamlit-flow-component
try:
    from streamlit_flow import streamlit_flow
    from streamlit_flow.elements import StreamlitFlowNode, StreamlitFlowEdge
    from streamlit_flow.state import StreamlitFlowState
    from streamlit_flow.layouts import TreeLayout, LayeredLayout
    STREAMLIT_FLOW_AVAILABLE = True
except ImportError:
    STREAMLIT_FLOW_AVAILABLE = False
    StreamlitFlowNode = None
    StreamlitFlowEdge = None
    StreamlitFlowState = None
    TreeLayout = None
    LayeredLayout = None
    streamlit_flow = None


# Workflow storage
WORKFLOW_STORAGE_DIR = GUI_STORAGE_DIR / "workflows"
WORKFLOW_STORAGE_DIR.mkdir(parents=True, exist_ok=True)


@dataclass
class NodeType:
    """Defines a node type that can be used in workflows."""
    id: str
    label: str
    icon: str
    color: str
    category: str  # input, modification, processing, output
    description: str
    enabled: bool = True  # Can be disabled if dependencies not met
    enabled_check: Optional[Callable[[], bool]] = None
    params_schema: Dict = field(default_factory=dict)
    sub_category: Optional[str] = None  # Sub-category for grouping (e.g., within modification)


# Registry for node types - allows dynamic registration
NODE_REGISTRY: Dict[str, NodeType] = {}


def register_node_type(node_type: NodeType) -> None:
    """Register a new node type dynamically."""
    NODE_REGISTRY[node_type.id] = node_type


def get_available_node_types() -> Dict[str, NodeType]:
    """Get all available node types, checking enabled status."""
    available = {}
    for node_id, node_type in NODE_REGISTRY.items():
        if node_type.enabled_check is None:
            available[node_id] = node_type
        elif node_type.enabled_check():
            node_type.enabled = True
            available[node_id] = node_type
        else:
            node_type.enabled = False
            available[node_id] = node_type
    return available


def _check_tesseract_available() -> bool:
    """Check if Tesseract OCR is available."""
    try:
        from pageplus.gui.cli_bridges.tesseract import TesseractBridge
        settings = Settings()
        return settings.get("PAGEPLUS_OCR_TESSERACT", "False") == "True"
    except ImportError:
        return False


def _check_kraken_available() -> bool:
    """Check if Kraken OCR is available."""
    try:
        from pageplus.cli.ocr_kraken import get_kraken_python_path
        return get_kraken_python_path() is not None
    except ImportError:
        return False


def _check_gemini_available() -> bool:
    """Check if Gemini is configured."""
    try:
        settings = Settings()
        return bool(settings.get("GEMINI_API_KEY"))
    except:
        return False


# Initialize default node types
def _initialize_node_types():
    """Initialize all default node types."""

    # Input nodes
    register_node_type(NodeType(
        id="input_xml",
        label="XML Input",
        icon="📄",
        color="#4CAF50",
        category="input",
        description="Load PAGE-XML files"
    ))

    register_node_type(NodeType(
        id="input_image",
        label="Image Input",
        icon="🖼️",
        color="#2196F3",
        category="input",
        description="Load image files"
    ))

    register_node_type(NodeType(
        id="input_directory",
        label="Directory Input",
        icon="📁",
        color="#FF9800",
        category="input",
        description="Load files from directory"
    ))

    # Modification nodes with subcategories
    # Format & Metadata (from modification view Tab 1)
    mod_format_metadata = [
        ("mod_set_page_version", "📄", "Set PAGE Version", "Update PAGE XML version"),
        ("mod_set_metadata", "📝", "Set Metadata", "Update file metadata"),
        ("mod_reassign_ids", "🔄", "Reassign IDs", "Reassign element IDs"),
    ]
    for node_id, icon, label, desc in mod_format_metadata:
        register_node_type(NodeType(
            id=node_id,
            label=label,
            icon=icon,
            color="#9C27B0",
            category="modification",
            description=desc,
            sub_category="format_metadata"
        ))
    # Text-Attributes (from modification view Tab 2)
    mod_text_attributes = [
        ("mod_replace_tags", "🏷️", "Replace Tags", "Replace element tags"),
        ("mod_remove_tags", "🚫", "Remove Tags", "Remove element tags"),
    ]
    for node_id, icon, label, desc in mod_text_attributes:
        register_node_type(NodeType(
            id=node_id,
            label=label,
            icon=icon,
            color="#9C27B0",
            category="modification",
            description=desc,
            sub_category="text_attributes"
        ))
    
    # Text-Content (from modification view Tab 3)
    mod_text_content = [
        ("mod_delete_text", "🗑️", "Delete Text", "Delete text content only"),
    ]
    for node_id, icon, label, desc in mod_text_content:
        register_node_type(NodeType(
            id=node_id,
            label=label,
            icon=icon,
            color="#9C27B0",
            category="modification",
            description=desc,
            sub_category="text_content"
        ))
    

    # Text-Layout (from modification view Tab 2)
    mod_text_layout = [
        ("mod_remove_empty", "🧹", "Remove Empty", "Remove empty text levels"),
        ("mod_delete_textlines", "🗑️", "Delete Textlines", "Delete textlines with content"),
        ("mod_translate_lines", "↔️", "Translate Lines", "Translate line coordinates"),
        ("mod_extend_lines", "↔️", "Extend Lines", "Extend line boundaries"),
        ("mod_rectangularize", "⬜", "Rectangularize", "Make regions rectangular"),
        ("mod_reduce_points", "📉", "Reduce Points", "Simplify polygon boundaries"),
        ("mod_simplify_polygon", "📉", "Simplify Polygon", "Simplify polygon"),
        ("mod_pseudoline_polygon", "📐", "Pseudoline Polygon", "Generate pseudo-line polygons"),
        ("mod_recalculate_polygon", "♻️", "Recalculate Polygon", "Recalculate TextRegion polygon"),
        ("mod_fit_into_parent", "📐", "Fit Into Parent", "Fit elements into parent boundaries"),
        ("mod_match_textlines", "🔗", "Match Textlines", "Match textlines to regions"),
    ]
    for node_id, icon, label, desc in mod_text_layout:
        register_node_type(NodeType(
            id=node_id,
            label=label,
            icon=icon,
            color="#9C27B0",
            category="modification",
            description=desc,
            sub_category="text_layout"
        ))

    # Merging & Splitting (from modification view Tab 2 continued)
    mod_merging_splitting = [
        ("mod_top_tier_region", "🏔️", "Top Tier Region", "Create top-tier region"),
        ("mod_merge_column_aligned", "📊", "Merge Column-Aligned", "Merge column-aligned regions"),
        ("mod_split_big_regions", "✂️", "Split Big Regions", "Split large regions"),
        ("mod_merge_regions", "🔗", "Merge Regions", "Merge overlapping regions"),
    ]
    for node_id, icon, label, desc in mod_merging_splitting:
        register_node_type(NodeType(
            id=node_id,
            label=label,
            icon=icon,
            color="#9C27B0",
            category="modification",
            description=desc,
            sub_category="merging_splitting"
        ))

    # Sorting (from modification view Tab 2 continued)
    mod_sorting = [
        ("mod_sort", "🔢", "Sort", "Sort textlines per region"),
        ("mod_sort_and_merge", "🔢", "Sort and Merge", "Sort and merge textlines"),
        ("mod_sort_regions", "🔢", "Sort Regions", "Sort regions in reading order"),
    ]
    for node_id, icon, label, desc in mod_sorting:
        register_node_type(NodeType(
            id=node_id,
            label=label,
            icon=icon,
            color="#9C27B0",
            category="modification",
            description=desc,
            sub_category="sorting"
        ))

    # Structure Repair (from modification view Tab 5)
    mod_structure_repair = [
        ("mod_repair", "🔧", "Repair", "Repair PAGE-XML structure"),
        ("mod_repair_dummy", "🔧", "Repair Dummy", "Repair dummy regions"),
    ]
    for node_id, icon, label, desc in mod_structure_repair:
        register_node_type(NodeType(
            id=node_id,
            label=label,
            icon=icon,
            color="#9C27B0",
            category="modification",
            description=desc,
            sub_category="structure_repair"
        ))

    # Gemini processing nodes - only quick mode (All-in-One) and ReOCR available
    # For other process types (Segmentation, Field-Tagging, Table Recognition), use pipelines
    gemini_nodes = [
        ("gemini_ocr", "✨", "Gemini OCR", "Quick mode: All-in-One processing"),
        ("gemini_reocr", "🔄", "Gemini ReOCR", "Re-process XML with Gemini"),
    ]

    for node_id, icon, label, desc in gemini_nodes:
        register_node_type(NodeType(
            id=node_id,
            label=label,
            icon=icon,
            color="#FF5722",
            category="processing",
            description=desc,
            enabled_check=_check_gemini_available
        ))

    # Tesseract nodes
    tesseract_nodes = [
        ("tesseract_ocr", "🔤", "Tesseract OCR", "OCR with Tesseract"),
    ]

    for node_id, icon, label, desc in tesseract_nodes:
        register_node_type(NodeType(
            id=node_id,
            label=label,
            icon=icon,
            color="#4CAF50",
            category="processing",
            description=desc,
            enabled_check=_check_tesseract_available
        ))

    # Kraken nodes
    kraken_nodes = [
        ("kraken_ocr", "🐙", "Kraken OCR", "OCR with Kraken"),
    ]

    for node_id, icon, label, desc in kraken_nodes:
        register_node_type(NodeType(
            id=node_id,
            label=label,
            icon=icon,
            color="#2196F3",
            category="processing",
            description=desc,
            enabled_check=_check_kraken_available
        ))

    # Future LLM nodes (extensible)
    llm_nodes = [
        ("llm_generic", "🤖", "Generic LLM", "Use any LLM provider"),
        ("llm_openai", "🧠", "OpenAI", "Use OpenAI GPT models"),
        ("llm_anthropic", "🟣", "Anthropic", "Use Anthropic Claude models"),
        ("llm_google", "🔵", "Google AI", "Use Google AI models"),
    ]

    for node_id, icon, label, desc in llm_nodes:
        register_node_type(NodeType(
            id=node_id,
            label=label,
            icon=icon,
            color="#7E57C2",
            category="processing",
            description=desc,
            enabled=False  # Disabled by default, can be enabled when implemented
        ))

    # Output nodes (excluding Save Output which goes to input_modification)
    output_nodes = [
        ("output_export", "📤", "Export", "Export to different format"),
        ("output_alto", "📋", "Export ALTO", "Export to ALTO format"),
        ("output_pdf", "📕", "Export PDF", "Export to PDF format"),
        ("output_text", "📄", "Export Text", "Export to plain text"),
    ]

    for node_id, icon, label, desc in output_nodes:
        register_node_type(NodeType(
            id=node_id,
            label=label,
            icon=icon,
            color="#00BCD4",
            category="output",
            description=desc
        ))

    # Input modification nodes (Save Output - used to copy files to output dir)
    input_mod_nodes = [
        ("output_save", "💾", "Save Output", "Copy files to output directory for workflow"),
    ]

    for node_id, icon, label, desc in input_mod_nodes:
        register_node_type(NodeType(
            id=node_id,
            label=label,
            icon=icon,
            color="#FF9800",
            category="input_modification",
            description=desc
        ))


# Initialize node types on module load
_initialize_node_types()


def get_nodes_by_category(category: str) -> List[NodeType]:
    """Get all nodes of a specific category."""
    all_types = get_available_node_types()
    return [nt for nt in all_types.values() if nt.category == category]


CATEGORY_COLORS = {
    "input": "#4CAF50",
    "modification": "#9C27B0",
    "processing": "#FF5722",
    "output": "#00BCD4",
    "input_modification": "#FF9800",
}

CATEGORY_LABELS = {
    "input": "📥 Input Nodes",
    "modification": "🛠️ Modification Tools",
    "processing": "✨ Processing / OCR",
    "output": "📤 Output Nodes",
    "input_modification": "💾 Input Modification",
}

# Subcategory labels for modification nodes (matching modification view tabs)
MOD_SUBCATEGORY_LABELS = {
    "format_metadata": "🧾 Format & Metadata",
    "text_attributes": "🏷️ Text-Attributes",
    "text_layout": "📐 Text-Layout",
    "merging_splitting": "🔗 Merging & Splitting",
    "sorting": "🔢 Sorting",
    "text_content": "📝 Text-Content",
    "structure_repair": "🔧 Structure Repair",
}


def strip_ansi_codes(text_to_clean):
    """Strip ANSI color codes from text."""
    ansi_escape = re.compile(r'\x1B(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])')
    return ansi_escape.sub('', text_to_clean)


class QueueOutput:
    """Custom stdout that puts output in a queue and buffer."""

    def __init__(self, q, buf):
        self.queue = q
        self.buffer = buf
        self._current_line_buffer = StringIO()

    def write(self, text_to_write):
        self._current_line_buffer.write(text_to_write)
        if '\n' in text_to_write:
            self.flush_line()

    def flush(self):
        self.flush_line()

    def flush_line(self):
        line_content = self._current_line_buffer.getvalue()
        if line_content:
            cleaned_text = strip_ansi_codes(line_content)
            self.buffer.write(cleaned_text)
            self.queue.put(cleaned_text)
            self._current_line_buffer = StringIO()


def update_terminal_display(output_queue, output_buffer, terminal_container):
    """Update the terminal display with new output from the queue."""
    updated_once_in_cycle = False
    while not output_queue.empty():
        try:
            output_queue.get_nowait()
            updated_once_in_cycle = True
        except queue.Empty:
            break

    if updated_once_in_cycle:
        current_output_for_display = output_buffer.getvalue()
        key = f"flow_terminal_output_{time.time()}"
        terminal_container.text_area(
            "Execution Log",
            value=current_output_for_display,
            height=200,
            disabled=True,
            key=key
        )


def create_node_from_type(node_type: NodeType, node_id: str, position: tuple = (0, 0), data: Optional[Dict] = None) -> StreamlitFlowNode:
    """Create a StreamlitFlowNode from a NodeType."""
    category_color = CATEGORY_COLORS.get(node_type.category, "#9E9E9E")

    label = f"{node_type.icon} {node_type.label}"
    if data and data.get('name'):
        label = f"{node_type.icon} {data['name']}"

    node_data = {
        'node_type': node_type.id,
        'label': node_type.label,
        'icon': node_type.icon,
        'category': node_type.category,
    }
    if data:
        node_data.update(data)

    # Set node type based on category for proper LayeredLayout rendering
    # Note: source_position and target_position must always be valid values (not None)
    if node_type.category == 'input':
        flow_node_type = 'input'
        source_position = 'right'
        target_position = 'right'  # Input nodes output to the right
    elif node_type.category == 'output':
        flow_node_type = 'output'
        source_position = 'left'   # Output nodes receive from left
        target_position = 'left'
    else:
        # input_modification, processing, modification all use default node type
        flow_node_type = 'default'
        source_position = 'right'
        target_position = 'left'

    node = StreamlitFlowNode(
        id=node_id,
        pos=position,
        data=node_data,
        node_type=flow_node_type,
        source_position=source_position,
        target_position=target_position,
        style={
            'background': node_type.color if node_type.enabled else '#BDBDBD',
            'color': 'white',
            'border': f"2px solid {category_color}",
            'borderRadius': '8px',
            'padding': '10px',
            'fontSize': '14px',
            'fontWeight': 'bold',
            'opacity': '1' if node_type.enabled else '0.6'
        },
        draggable=True
    )
    return node


def get_available_workflows() -> List[str]:
    """Get list of saved workflows."""
    if not WORKFLOW_STORAGE_DIR.exists():
        return []
    return [
        f.stem for f in WORKFLOW_STORAGE_DIR.glob("*.json")
        if f.stem != "autosave"
    ]


def save_workflow(name: str, nodes: List[Dict], edges: List[Dict], metadata: Optional[Dict] = None) -> bool:
    """Save a workflow to storage."""
    try:
        workflow_data = {
            "name": name,
            "version": "1.0",
            "nodes": nodes,
            "edges": edges,
            "metadata": metadata or {},
            "created_at": time.time()
        }
        workflow_path = WORKFLOW_STORAGE_DIR / f"{name}.json"
        with open(workflow_path, 'w', encoding='utf-8') as f:
            json.dump(workflow_data, f, indent=2, ensure_ascii=False)
        return True
    except Exception as e:
        st.error(f"Failed to save workflow: {e}")
        return False


def load_workflow(name: str) -> Optional[Dict]:
    """Load a workflow from storage."""
    try:
        workflow_path = WORKFLOW_STORAGE_DIR / f"{name}.json"
        if not workflow_path.exists():
            return None
        with open(workflow_path, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception as e:
        st.error(f"Failed to load workflow: {e}")
        return None


def delete_workflow(name: str) -> bool:
    """Delete a workflow."""
    try:
        workflow_path = WORKFLOW_STORAGE_DIR / f"{name}.json"
        if workflow_path.exists():
            workflow_path.unlink()
            return True
        return False
    except Exception:
        return False


def export_workflow(name: str) -> Optional[str]:
    """Export workflow as JSON string for download."""
    workflow = load_workflow(name)
    if workflow:
        return json.dumps(workflow, indent=2, ensure_ascii=False)
    return None


def import_workflow(json_str: str, new_name: Optional[str] = None) -> bool:
    """Import workflow from JSON string."""
    try:
        workflow_data = json.loads(json_str)
        name = new_name or workflow_data.get('name', 'imported_workflow')

        # Generate new IDs for nodes and edges to avoid conflicts
        id_mapping = {}
        for node in workflow_data.get('nodes', []):
            old_id = node['id']
            new_id = f"node_{uuid.uuid4().hex[:8]}"
            id_mapping[old_id] = new_id
            node['id'] = new_id

        for edge in workflow_data.get('edges', []):
            edge['id'] = f"edge_{uuid.uuid4().hex[:8]}"
            edge['source'] = id_mapping.get(edge['source'], edge['source'])
            edge['target'] = id_mapping.get(edge['target'], edge['target'])

        workflow_data['name'] = name
        workflow_data['imported_at'] = time.time()

        return save_workflow(name, workflow_data.get('nodes', []), workflow_data.get('edges', []), workflow_data.get('metadata'))
    except Exception as e:
        st.error(f"Failed to import workflow: {e}")
        return False


def flow_editor_view():
    """Main flow editor view."""
    st.title("🔀 Flow Editor")
    st.caption("Build complex document processing workflows with a visual node editor")

    # Check if streamlit-flow is available
    if not STREAMLIT_FLOW_AVAILABLE:
        st.error("🚫 streamlit-flow-component is not installed!")
        st.info("""
        **To use the Flow Editor, please install streamlit-flow-component:**

        ```bash
        pip install streamlit-flow-component
        ```

        Or if you're using Poetry:

        ```bash
        poetry add streamlit-flow-component
        ```
        """)
        return

    # Initialize session state for workflow
    _initialize_session_state()

    # Workflow management toolbar
    _render_workflow_toolbar()

    # Show Monitor or Editor based on state
    if st.session_state.flow_active_tab == 'monitor':
        # Monitor view
        _render_monitor_tab()

        # Auto-execute next step if execution is active
        if st.session_state.flow_exec_active:
            _execute_next_step()
    else:
        # Editor view
        st.markdown("---")
        col_library, col_editor = st.columns([1, 3])

        with col_library:
            _render_node_library()

        with col_editor:
            _render_workflow_canvas()

            # Show node configuration panel when a node is selected
            if st.session_state.flow_selected_node_id:
                _render_node_config_panel()

            _render_execution_section()


def _initialize_session_state():
    """Initialize session state variables."""
    defaults = {
        'flow_nodes': [],
        'flow_edges': [],
        'flow_selected_workflow': None,
        'flow_execution_log': "",
        'flow_workflow_name': 'untitled',
        'flow_selected_node_id': None,
        'flow_autoconnect': True,
        'flow_generation': 0,  # Generation counter to force flow component reset
        # Execution monitor state
        'flow_exec_active': False,
        'flow_exec_node_states': {},  # {node_id: 'pending'|'running'|'done'|'failed'}
        'flow_exec_current_step': 0,
        'flow_exec_total_steps': 0,
        'flow_exec_log_lines': [],
        'flow_exec_plan': [],  # Flattened execution order [(node_dict, level_idx), ...]
        'flow_exec_context': {},  # Shared context: current_files, node_output_files, bridges, etc.
        'flow_active_tab': 'editor',
    }

    for key, default_value in defaults.items():
        if key not in st.session_state:
            st.session_state[key] = default_value


def _render_workflow_toolbar():
    """Render the workflow management toolbar."""
    with st.container():
        col1, col2, col3, col4, col5, col6 = st.columns([2, 1, 1, 1, 1, 1])

        with col1:
            workflows = get_available_workflows()
            workflow_name = st.selectbox(
                "Workflow",
                ["New Workflow..."] + workflows,
                key="flow_workflow_select"
            )

        with col2:
            if st.button("💾 Save", use_container_width=True, help="Save current workflow"):
                name = st.session_state.flow_workflow_name
                if workflow_name != "New Workflow...":
                    name = workflow_name
                metadata = {
                    'description': st.session_state.get('flow_description', ''),
                    'node_count': len(st.session_state.flow_nodes),
                    'edge_count': len(st.session_state.flow_edges)
                }
                if save_workflow(name, st.session_state.flow_nodes, st.session_state.flow_edges, metadata):
                    st.success(f"Workflow '{name}' saved!")

        with col3:
            if st.button("📥 Load", use_container_width=True, help="Load selected workflow"):
                if workflow_name != "New Workflow...":
                    workflow = load_workflow(workflow_name)
                    if workflow:
                        st.session_state.flow_nodes = workflow.get('nodes', [])
                        st.session_state.flow_edges = workflow.get('edges', [])
                        st.session_state.flow_selected_workflow = workflow_name
                        if 'metadata' in workflow:
                            st.session_state.flow_description = workflow['metadata'].get('description', '')
                        st.rerun()

        with col4:
            if st.button("➕ New", use_container_width=True, help="Create new workflow"):
                st.session_state.flow_nodes = []
                st.session_state.flow_edges = []
                st.session_state.flow_selected_workflow = None
                st.session_state.flow_execution_log = ""
                st.rerun()

        with col5:
            if st.button("🗑️ Delete", use_container_width=True, help="Delete selected workflow"):
                if workflow_name != "New Workflow..." and delete_workflow(workflow_name):
                    st.success(f"Workflow '{workflow_name}' deleted!")
                    st.rerun()

        with col6:
            if st.button("📤 Export", use_container_width=True, help="Export workflow as JSON"):
                if workflow_name != "New Workflow...":
                    json_data = export_workflow(workflow_name)
                    if json_data:
                        st.download_button(
                            label="Download",
                            data=json_data,
                            file_name=f"{workflow_name}.json",
                            mime="application/json",
                            key=f"download_{workflow_name}"
                        )

    # Import workflow
    with st.expander("📥 Import Workflow"):
        uploaded_file = st.file_uploader(
            "Upload workflow JSON",
            type=['json'],
            key="flow_import_uploader",
            label_visibility="collapsed"
        )
        if uploaded_file is not None:
            try:
                import_data = json.load(uploaded_file)
                new_name = st.text_input("Import as", value=uploaded_file.name.replace('.json', ''))
                col1, col2 = st.columns(2)
                with col1:
                    if st.button("Import", use_container_width=True):
                        if import_workflow(json.dumps(import_data), new_name):
                            st.success(f"Workflow '{new_name}' imported!")
                            st.rerun()
                with col2:
                    if st.button("Cancel", use_container_width=True):
                        st.rerun()
            except json.JSONDecodeError:
                st.error("Invalid JSON file!")

    # Workflow metadata
    if workflow_name == "New Workflow...":
        st.session_state.flow_workflow_name = st.text_input(
            "Workflow Name",
            value=st.session_state.flow_workflow_name,
            key="flow_workflow_name_input"
        )
        st.session_state.flow_description = st.text_input(
            "Description (optional)",
            value=st.session_state.get('flow_description', ''),
            key="flow_description_input"
        )
    else:
        workflow = load_workflow(workflow_name)
        if workflow and 'metadata' in workflow:
            desc = workflow['metadata'].get('description', '')
            if desc:
                st.caption(f"📝 {desc}")


def _render_node_library():
    """Render the node library sidebar."""
    st.subheader("📦 Node Library")

    # Check for available OCR engines
    tesseract_available = _check_tesseract_available()
    kraken_available = _check_kraken_available()
    gemini_available = _check_gemini_available()

    # Show status indicators
    st.caption("OCR Engines Status:")
    status_cols = st.columns(3)
    with status_cols[0]:
        st.caption("✨ Gemini: " + ("✅" if gemini_available else "❌"))
    with status_cols[1]:
        st.caption("🔤 Tesseract: " + ("✅" if tesseract_available else "❌"))
    with status_cols[2]:
        st.caption("🐙 Kraken: " + ("✅" if kraken_available else "❌"))
    st.markdown("---")

    # Auto-connect toggle - disabled by default
    st.session_state.flow_autoconnect = st.checkbox(
        "Auto-connect nodes",
        value=False,
        help="Automatically connect new nodes to the previous node"
    )
    st.markdown("---")

    all_types = get_available_node_types()

    # Group by category
    categories = ["input", "input_modification", "processing", "modification", "output"]

    for category in categories:
        category_nodes = [nt for nt in all_types.values() if nt.category == category]

        if not category_nodes:
            continue

        with st.expander(CATEGORY_LABELS.get(category, category.capitalize()), expanded=(category == "input")):
            # For modification category, group by subcategory
            if category == "modification":
                # Group by subcategory
                subcategory_groups = {}
                for nt in category_nodes:
                    sub_cat = nt.sub_category or "other"
                    if sub_cat not in subcategory_groups:
                        subcategory_groups[sub_cat] = []
                    subcategory_groups[sub_cat].append(nt)

                # Render each subcategory in its own expander
                for sub_cat, sub_cat_nodes in subcategory_groups.items():
                    sub_cat_label = MOD_SUBCATEGORY_LABELS.get(sub_cat, sub_cat.replace("_", " ").title())
                    with st.expander(sub_cat_label, expanded=False):
                        for node_type in sub_cat_nodes:
                            label = node_type.label
                            if not node_type.enabled:
                                label = f"{label} (disabled)"

                            if st.button(
                                f"{node_type.icon} {label}",
                                use_container_width=True,
                                key=f"add_{node_type.id}",
                                disabled=not node_type.enabled,
                                help=node_type.description
                            ):
                                _add_node(node_type.id)
            else:
                # For non-modification categories, render nodes directly
                for node_type in category_nodes:
                    # Show disabled status
                    label = node_type.label
                    if not node_type.enabled:
                        label = f"{label} (disabled)"

                    if st.button(
                        f"{node_type.icon} {label}",
                        use_container_width=True,
                        key=f"add_{node_type.id}",
                        disabled=not node_type.enabled,
                        help=node_type.description
                    ):
                        _add_node(node_type.id)

    st.markdown("---")
    st.caption(f"**Nodes:** {len(st.session_state.flow_nodes)}")
    st.caption(f"**Connections:** {len(st.session_state.flow_edges)}")


def _render_workflow_canvas():
    """Render the main workflow canvas."""
    st.subheader("🎨 Workflow Canvas")

    # Use simple stable key - just workflow name plus generation counter
    # The generation counter forces a complete flow component reset when incremented
    workflow_name = st.session_state.flow_selected_workflow or 'new'
    generation = st.session_state.get('flow_generation', 0)
    flow_key = f"flow_editor_{workflow_name}_gen{generation}"

    # Create a version string to detect changes
    version_key = f"{flow_key}_version"
    current_version = json.dumps([
        (n.get('id'), n.get('node_type'), n.get('name')) for n in st.session_state.flow_nodes
    ] + [
        (e.get('id'), e.get('source'), e.get('target')) for e in st.session_state.flow_edges
    ], sort_keys=True)
    flow_state_key = f"{flow_key}_state_object"

    # Cleanup state if empty
    if not st.session_state.flow_nodes:
        st.info("👆 Add nodes from the library to start building your workflow!")
        for key in [version_key, flow_state_key]:
            if key in st.session_state:
                del st.session_state[key]
        return

    # Only rebuild flow state object if version changed
    if version_key not in st.session_state or st.session_state[version_key] != current_version:
        st.session_state[version_key] = current_version

        # Create flow state from nodes and edges
        nodes = []
        edges = []

        # Calculate positions based on node order and category
        x_positions = {}
        y_spacing = 120
        x_positions_by_category = {
            "input": 100,
            "input_modification": 250,
            "processing": 400,
            "modification": 600,
            "output": 850
        }

        # Group nodes by category
        by_category = {
            "input": [],
            "input_modification": [],
            "processing": [],
            "modification": [],
            "output": []
        }

        for node_data in st.session_state.flow_nodes:
            category = node_data.get('category', 'input')
            by_category[category].append(node_data)

        # Assign positions
        for category, category_nodes in by_category.items():
            x_base = x_positions_by_category[category]
            for i, node_data in enumerate(category_nodes):
                x_positions[node_data['id']] = (x_base, 100 + i * y_spacing)

        # Create StreamlitFlow nodes
        all_types = get_available_node_types()
        for node_data in st.session_state.flow_nodes:
            node_id = node_data['id']
            node_type_id = node_data['node_type']
            node_type = all_types.get(node_type_id)

            if node_type:
                pos = x_positions.get(node_id, (100, 100))
                nodes.append(create_node_from_type(
                    node_type,
                    node_id,
                    position=pos,
                    data=node_data
                ))

        # Create edges
        for edge_data in st.session_state.flow_edges:
            edges.append(StreamlitFlowEdge(
                id=edge_data['id'],
                source=edge_data['source'],
                target=edge_data['target'],
                animated=True,
                style={'stroke': '#2196F3', 'strokeWidth': 2}
            ))

        # Create and store the new FlowState object
        st.session_state[flow_state_key] = StreamlitFlowState(nodes, edges)

    # Use the stored FlowState object
    flow_state = st.session_state.get(flow_state_key)

    if flow_state:
        try:
            updated_state = streamlit_flow(
                flow_key,
                flow_state,
                layout=LayeredLayout(direction='right'),  # Use LayeredLayout for better workflow visualization
                fit_view=True,
                height=500,
                enable_node_menu=True,      # Enable right-click menu on nodes
                enable_edge_menu=True,      # Enable right-click menu on edges
                enable_pane_menu=False,     # Disable canvas menu
                get_edge_on_click=True,     # Enable edge selection on click
                get_node_on_click=True,     # Enable node selection on click
                show_minimap=False,         # Disable minimap
                hide_watermark=True,
                allow_new_edges=True,
                min_zoom=0.1                # Allow deeper zoom for large workflows
            )

            # Handle edge creation (new connections)
            if hasattr(updated_state, 'edges') or isinstance(updated_state, dict):
                if isinstance(updated_state, dict):
                    new_edges = updated_state.get('edges', [])
                    selected_id = updated_state.get('selected_id')
                else:
                    new_edges = getattr(updated_state, 'edges', [])
                    selected_id = getattr(updated_state, 'selected_id', None)

                # Update edges from flow state
                if new_edges:
                    _sync_edges_from_flow(new_edges)

            # Handle node/edge selection
            selected_id = updated_state.get('selected_id') if isinstance(updated_state, dict) else getattr(updated_state, 'selected_id', None)

            if selected_id:
                # Store selection and show config panel below canvas
                st.session_state.flow_selected_node_id = selected_id

        except Exception as e:
            st.error(f"Error rendering flow: {e}")
            with st.expander("Error Details"):
                st.code(str(e))


def _sync_edges_from_flow(flow_edges):
    """Synchronize edges from the flow state."""
    current_edge_ids = {e['id'] for e in st.session_state.flow_edges}

    # Helper function to get node category
    def get_node_category(node_id: str) -> str:
        for node in st.session_state.flow_nodes:
            if node['id'] == node_id:
                return node.get('category', 'input')
        return 'unknown'

    for edge in flow_edges:
        if hasattr(edge, 'id'):
            edge_id = edge.id
            edge_source = edge.source
            edge_target = edge.target
        else:
            edge_id = edge.get('id')
            edge_source = edge.get('source')
            edge_target = edge.get('target')

        # Skip if edge already exists
        if edge_id in current_edge_ids:
            continue

        # Validate edge: prevent input-to-input connections
        source_category = get_node_category(edge_source)
        target_category = get_node_category(edge_target)

        if source_category == 'input' and target_category == 'input':
            # Skip input-to-input connections
            continue

        # Add valid edge
        st.session_state.flow_edges.append({
            'id': edge_id,
            'source': edge_source,
            'target': edge_target
        })


def _render_execution_section():
    """Render the workflow execution section."""
    st.markdown("---")
    st.subheader("▶️ Execute Workflow")

    col_run1, col_run2, col_run3, col_run4 = st.columns([2, 1, 1, 1])

    with col_run1:
        use_loaded_files = st.checkbox(
            "Use currently loaded files from Input page",
            value=True,
            help="If checked, uses files loaded in the Input page. Otherwise, specify files below."
        )

    with col_run2:
        dry_run = st.checkbox("Dry run", value=False)

    with col_run3:
        continue_on_error = st.checkbox("Continue on error", value=False)

    with col_run4:
        if st.button("▶️ Run Workflow", type="primary", use_container_width=True):
            _start_execution(dry_run, continue_on_error)

    # Show input files info
    if use_loaded_files:
        if st.session_state.get('loaded_files'):
            st.caption(f"📂 {len(st.session_state.loaded_files)} files loaded from Input page")
        else:
            st.warning("⚠️ No files loaded in Input page")

    # Execution log
    if st.session_state.flow_execution_log:
        with st.expander("📋 Execution Log", expanded=True):
            st.text_area(
                "Log",
                value=st.session_state.flow_execution_log,
                height=200,
                disabled=True
            )


def _add_node(node_type_id: str):
    """Add a node to the workflow."""
    all_types = get_available_node_types()
    node_type = all_types.get(node_type_id)

    if not node_type:
        st.error(f"Unknown node type: {node_type_id}")
        return

    node_id = f"node_{uuid.uuid4().hex[:8]}"
    node_data = {
        'id': node_id,
        'node_type': node_type_id,
        'category': node_type.category,
        'name': node_type.label,
        'params': {}
    }

    st.session_state.flow_nodes.append(node_data)

    # Auto-connect to previous node if enabled
    # Skip auto-connect for input-to-input connections
    if st.session_state.flow_autoconnect and len(st.session_state.flow_nodes) > 1:
        prev_node = st.session_state.flow_nodes[-2]
        prev_category = prev_node.get('category', 'input')

        # Don't auto-connect if both are input nodes
        if not (prev_category == 'input' and node_type.category == 'input'):
            edge_id = f"edge_{uuid.uuid4().hex[:8]}"
            st.session_state.flow_edges.append({
                'id': edge_id,
                'source': prev_node['id'],
                'target': node_id
            })

    # Note: No st.rerun() needed here - the button click will naturally trigger a rerun


def _render_node_config_panel():
    """Render configuration panel for selected node as an expander."""
    node_id = st.session_state.flow_selected_node_id
    node = next((n for n in st.session_state.flow_nodes if n['id'] == node_id), None)
    if not node:
        st.session_state.flow_selected_node_id = None
        return

    all_types = get_available_node_types()
    node_type = all_types.get(node['node_type'])

    if not node_type:
        st.session_state.flow_selected_node_id = None
        return

    # Count connections for this node
    incoming_count = sum(1 for e in st.session_state.flow_edges if e['target'] == node_id)
    outgoing_count = sum(1 for e in st.session_state.flow_edges if e['source'] == node_id)
    total_connections = incoming_count + outgoing_count

    # Display as an expander panel
    with st.expander(
        f"⚙️ {node_type.icon} {node.get('name', node_type.label)} - Node Configuration",
        expanded=True
    ):
        # Node info header
        col1, col2, col3, col4, col5 = st.columns([3, 2, 1, 1, 1])

        with col1:
            st.markdown(f"**{node_type.label}**")
            st.caption(node_type.description)

        with col2:
            st.caption(f"**Category:** {node_type.category.capitalize()}")
            if total_connections > 0:
                st.caption(f"**Connections:** ↓{outgoing_count} ↑{incoming_count}")

        with col3:
            if st.button("🔌", help="Reset connections", key=f"reset_{node_id}"):
                # Remove all edges connected to this node
                st.session_state.flow_edges = [e for e in st.session_state.flow_edges if e['source'] != node_id and e['target'] != node_id]
                # Increment generation counter to force complete flow component reset
                # This prevents the streamlit_flow component from restoring old edges from its internal state
                st.session_state.flow_generation = st.session_state.get('flow_generation', 0) + 1
                st.rerun()

        with col4:
            if st.button("🗑️", help="Remove node", key=f"delete_{node_id}"):
                st.session_state.flow_nodes = [n for n in st.session_state.flow_nodes if n['id'] != node_id]
                st.session_state.flow_edges = [e for e in st.session_state.flow_edges if e['source'] != node_id and e['target'] != node_id]
                # Increment generation counter to force complete flow component reset
                st.session_state.flow_generation = st.session_state.get('flow_generation', 0) + 1
                st.session_state.flow_selected_node_id = None
                st.rerun()

        with col5:
            if st.button("✖️", help="Close panel", key=f"close_{node_id}"):
                st.session_state.flow_selected_node_id = None
                st.rerun()

        st.markdown("---")

        # Node name
        new_name = st.text_input(
            "Node Name",
            value=node.get('name', node_type.label),
            key=f"name_{node_id}"
        )
        if new_name != node.get('name'):
            node['name'] = new_name

        # Initialize params if not exists
        if 'params' not in node:
            node['params'] = {}

        # Render node-specific configuration
        _render_node_params(node, node_type)


def _render_node_params(node: Dict, node_type: NodeType):
    """Render node-specific parameter configuration."""
    node_id = node['id']
    params = node.get('params', {})

    # Input nodes configuration
    if node_type.category == "input":
        if node_type.id == "input_directory":
            col1, col2 = st.columns([4, 1])
            with col1:
                directory = st.text_input(
                    "Directory Path",
                    value=params.get('directory', ''),
                    key=f"dir_{node_id}"
                )
            with col2:
                if st.button("📁", help="Browse directory", key=f"browse_dir_{node_id}"):
                    selected_dir = pick_directory(initial_dir=get_loaded_workspace_dir())
                    if selected_dir:
                        params['directory'] = selected_dir
                        st.rerun()

            extensions = st.text_input(
                "File Extensions (comma-separated)",
                value=params.get('extensions', '.xml,.jpg,.png'),
                key=f"ext_{node_id}"
            )
            recursive = st.checkbox(
                "Include subdirectories",
                value=params.get('recursive', False),
                key=f"rec_{node_id}"
            )
            node['params'] = {'directory': params.get('directory', directory), 'extensions': extensions, 'recursive': recursive}

        elif node_type.id == "input_image":
            # Image input node: file/directory selection with buttons
            current_source = params.get('source', 'Select files')

            col_dir, col_files = st.columns(2)
            with col_dir:
                if st.button("📁 Directory", key=f"btn_img_dir_{node_id}",
                             use_container_width=True,
                             type="primary" if current_source == "Directory" else "secondary"):
                    node['params']['source'] = 'Directory'
                    st.rerun()
            with col_files:
                if st.button("📂 Select Files", key=f"btn_img_files_{node_id}",
                             use_container_width=True,
                             type="primary" if current_source == "Select files" else "secondary"):
                    node['params']['source'] = 'Select files'
                    st.rerun()

            input_source = current_source

            if input_source == "Directory":
                col1, col2 = st.columns([4, 1])
                with col1:
                    directory = st.text_input(
                        "Directory Path",
                        value=params.get('directory', ''),
                        key=f"img_dir_{node_id}",
                        help="Path to directory containing images"
                    )
                with col2:
                    if st.button("📁", help="Browse directory", key=f"browse_img_dir_{node_id}"):
                        selected_dir = pick_directory(initial_dir=get_loaded_workspace_dir())
                        if selected_dir:
                            params['directory'] = selected_dir
                            st.rerun()

                extensions = st.text_input(
                    "Image Extensions (comma-separated)",
                    value=params.get('extensions', '.jpg,.jpeg,.png,.tif,.tiff,.webp'),
                    key=f"img_ext_{node_id}"
                )
                recursive = st.checkbox(
                    "Include subdirectories",
                    value=params.get('recursive', False),
                    key=f"img_rec_{node_id}"
                )
                node['params'] = {'source': input_source, 'directory': params.get('directory', directory), 'extensions': extensions, 'recursive': recursive}

            else:  # Select files
                # Show selected files count
                selected_files_key = f"img_selected_files_{node_id}"
                selected_files = st.session_state.get(selected_files_key, [])
                if selected_files:
                    st.info(f"📁 {len(selected_files)} file(s) selected")

                col1, col2, col3, col4 = st.columns([1, 1, 1, 1])
                with col1:
                    if st.button("📂 Browse", key=f"browse_img_files_{node_id}", use_container_width=True):
                        file_types = [
                            ("Image files", "*.jpg *.jpeg *.png *.tif *.tiff *.webp *.bmp"),
                            ("JPEG files", "*.jpg *.jpeg"),
                            ("PNG files", "*.png"),
                            ("TIFF files", "*.tif *.tiff"),
                            ("WebP files", "*.webp"),
                            ("All files", "*.*")
                        ]
                        selected_paths = pick_files(
                            initial_dir=get_loaded_workspace_dir(),
                            filetypes=file_types
                        )
                        if selected_paths:
                            st.session_state[selected_files_key] = selected_paths
                            st.success(f"Selected {len(selected_paths)} file(s)")
                            st.rerun()

                with col2:
                    if st.button("🔀 Shuffle", key=f"shuffle_img_files_{node_id}", use_container_width=True):
                        if selected_files_key in st.session_state:
                            st.session_state[selected_files_key] = shuffle(st.session_state[selected_files_key])
                            st.rerun()

                with col3:
                    if st.button("🔁 Sort", key=f"sort_img_files_{node_id}", use_container_width=True):
                        if selected_files_key in st.session_state:
                            st.session_state[selected_files_key] = sorted(st.session_state[selected_files_key], key=lambda x: Path(x).name)
                            st.rerun()

                with col4:
                    if st.button("🗑️ Clear", key=f"clear_img_files_{node_id}", use_container_width=True):
                        if selected_files_key in st.session_state:
                            del st.session_state[selected_files_key]
                        st.rerun()

                node['params'] = {'source': input_source, 'files_key': selected_files_key}

        else:  # input_xml
            st.info("This node uses files loaded from the Input page.")

    # Modification nodes configuration
    elif node_type.category == "modification":
        _render_modification_params(node, node_type)

    # Processing nodes configuration
    elif node_type.category == "processing":
        _render_processing_params(node, node_type)

    # Input modification nodes configuration (e.g., Save Output)
    elif node_type.category == "input_modification":
        _render_output_params(node, node_type)

    # Output nodes configuration
    elif node_type.category == "output":
        _render_output_params(node, node_type)


def _render_modification_params(node: Dict, node_type: NodeType):
    """Render modification node parameters."""
    node_id = node['id']
    params = node.get('params', {})

    if node_type.id == "mod_remove_empty":
        levels = st.multiselect(
            "Levels to Process",
            ["TextRegion", "Textline", "TableRegion"],
            default=params.get('levels', ["TextRegion", "Textline"]),
            key=f"levels_{node_id}"
        )
        dry_run = st.checkbox("Dry run only", value=params.get('dry_run', False), key=f"dryrun_{node_id}")
        node['params'] = {'levels': levels, 'dry_run': dry_run}

    elif node_type.id == "mod_translate_lines":
        col1, col2 = st.columns(2)
        with col1:
            xoff = st.number_input("X Offset", value=params.get('xoff', 0), key=f"xoff_{node_id}")
        with col2:
            yoff = st.number_input("Y Offset", value=params.get('yoff', 0), key=f"yoff_{node_id}")
        dry_run = st.checkbox("Dry run only", value=params.get('dry_run', False), key=f"dryrun_{node_id}")
        node['params'] = {'xoff': xoff, 'yoff': yoff, 'dry_run': dry_run}

    elif node_type.id == "mod_extend_lines":
        distance = st.number_input("Distance", min_value=1, value=params.get('distance', 8), key=f"dist_{node_id}")
        dim = st.selectbox("Dimension", ["all", "x", "y"], index=["all", "x", "y"].index(params.get('dim', 'all')), key=f"dim_{node_id}")
        rectangularize = st.checkbox("Rectangularize", value=params.get('rectangularize', False), key=f"rect_{node_id}")
        cut_overlaps = st.checkbox("Cut overlaps", value=params.get('cut_overlaps', False), key=f"cut_{node_id}")
        dry_run = st.checkbox("Dry run only", value=params.get('dry_run', False), key=f"dryrun_{node_id}")
        node['params'] = {'distance': distance, 'dim': dim, 'rectangularize': rectangularize, 'cut_overlaps': cut_overlaps, 'dry_run': dry_run}

    elif node_type.id in ["mod_rectangularize", "mod_reduce_points", "mod_simplify_polygon", "mod_fit_into_parent"]:
        levels = st.multiselect(
            "Levels to Process",
            ["TextRegion", "Textline", "TableRegion"],
            default=params.get('levels', ["TextRegion", "Textline"]),
            key=f"levels_{node_id}"
        )
        dry_run = st.checkbox("Dry run only", value=params.get('dry_run', False), key=f"dryrun_{node_id}")

        if node_type.id in ["mod_reduce_points", "mod_simplify_polygon"]:
            tolerance = st.number_input("Tolerance", min_value=0, value=params.get('tolerance', 2), key=f"tol_{node_id}")
            node['params'] = {'levels': levels, 'tolerance': tolerance, 'dry_run': dry_run}
        else:
            node['params'] = {'levels': levels, 'dry_run': dry_run}

    elif node_type.id == "mod_replace_tags":
        # Initialize session state for tag options
        tag_options_key = f'replace_tag_options_{node_id}'
        if tag_options_key not in st.session_state:
            st.session_state[tag_options_key] = []

        # Define levels first (needed for scanning)
        levels = st.multiselect(
            "Apply to Levels",
            ["TextRegion", "Textline", "TableRegion"],
            default=params.get('levels', ["TextRegion", "Textline"]),
            key=f"levels_{node_id}"
        )

        # Update tags button - scans loaded files to get available tags
        col1, col2 = st.columns([3, 1])
        with col1:
            st.caption("**Old Tag Selection**")
        with col2:
            if st.button("Update Tags", key=f"update_tags_{node_id}", help="Scan loaded files to get available tags"):
                if st.session_state.get('loaded_files'):
                    with st.spinner("Scanning files for tags..."):
                        try:
                            from pageplus.models.page import Page
                            from pageplus.utils.constants import TextLevel

                            # Get selected levels to scan
                            scan_levels = [TextLevel[level] for level in levels]
                            all_tags = sorted(set(
                                tag for tags in [
                                    Page(Path(f)).get_tags(scan_levels)
                                    for f in st.session_state.loaded_files
                                ] for tag in tags
                            ))
                            st.session_state[tag_options_key] = all_tags
                            st.success(f"Found {len(all_tags)} unique tag(s)")
                        except Exception as e:
                            st.error(f"Error scanning files: {e}")
                else:
                    st.warning("No files loaded. Please load files first.")

        # Show available tags if any were scanned
        # Use multiselect for tag selection (like in modification view)
        if st.session_state[tag_options_key]:
            old_tags_selected = st.multiselect(
                "Old Tags (from scanned files)",
                options=st.session_state[tag_options_key],
                default=params.get('old_tags_selected', []),
                key=f"old_tag_select_{node_id}",
                help="Select one or more tags to replace"
            )
        else:
            old_tags_selected = []

        # Allow manual entry for multiple tags (comma-separated)
        manual_old_tags = st.text_input(
            "Or type Old Tags manually (comma-separated)",
            value=params.get('manual_old_tags', ''),
            key=f"old_tag_manual_{node_id}",
            help="Enter tag names manually, separated by commas (e.g., tag1, tag2, tag3)"
        )

        # Combine both sources: multiselect and manual entry
        all_old_tags = list(old_tags_selected)
        if manual_old_tags:
            # Split by comma and strip whitespace
            manual_tags_list = [tag.strip() for tag in manual_old_tags.split(',') if tag.strip()]
            all_old_tags.extend(manual_tags_list)

        # Store combined list for params (empty list means scan all tags)
        final_old_tags = all_old_tags if all_old_tags else []

        new_tag = st.text_input("New Tag", value=params.get('new_tag', ''), key=f"new_tag_{node_id}")
        text_filter = st.text_input(
            "Text Filter (regex, optional)",
            value=params.get('text_filter', ''),
            key=f"tf_{node_id}",
            help="Optional regex pattern to match text content"
        )
        skip_textfilter = st.checkbox(
            "Skip Matching Text",
            value=params.get('skip_textfilter', False),
            key=f"skip_tf_{node_id}",
            help="If checked, skip elements matching the text filter. If unchecked, only process elements matching the text filter."
        )
        dry_run = st.checkbox("Dry run only", value=params.get('dry_run', False), key=f"dryrun_{node_id}")
        node['params'] = {
            'old_tags': final_old_tags,  # List of tags (empty = scan all)
            'new_tag': new_tag,
            'levels': levels,
            'text_filter': text_filter if text_filter else None,
            'skip_textfilter': skip_textfilter,
            'dry_run': dry_run,
            'old_tags_selected': old_tags_selected,
            'manual_old_tags': manual_old_tags
        }

    elif node_type.id == "mod_remove_tags":
        tag_to_remove = st.text_input("Tag to Remove", value=params.get('tag_to_remove', ''), key=f"rem_tag_{node_id}")
        levels = st.multiselect(
            "Apply to Levels",
            ["TextRegion", "Textline", "TableRegion"],
            default=params.get('levels', ["TextRegion", "Textline"]),
            key=f"levels_{node_id}"
        )
        dry_run = st.checkbox("Dry run only", value=params.get('dry_run', False), key=f"dryrun_{node_id}")
        node['params'] = {'tag_to_remove': tag_to_remove, 'levels': levels, 'dry_run': dry_run}

    elif node_type.id == "mod_sort_regions":
        based_on_baselines = st.checkbox("Use mean baseline centroid", value=params.get('based_on_baselines', False), key=f"bob_{node_id}")
        overlap_pct = st.slider("Overlap percentage", 0.0, 100.0, value=params.get('overlap_pct', 60.0), key=f"op_{node_id}")
        dry_run = st.checkbox("Dry run only", value=params.get('dry_run', False), key=f"dryrun_{node_id}")
        node['params'] = {'based_on_baselines': based_on_baselines, 'overlap_pct': overlap_pct, 'dry_run': dry_run}

    # New Format & Metadata nodes
    elif node_type.id == "mod_set_page_version":
        from pageplus.utils.constants import PcGtsVersion
        version_options = [v.value for v in PcGtsVersion]
        version = st.selectbox(
            "Target PAGE Version",
            options=version_options,
            index=len(version_options) - 1,
            key=f"version_{node_id}"
        )
        validate = st.checkbox("Validate compatibility", value=True, key=f"validate_{node_id}")
        dry_run = st.checkbox("Dry run only", value=params.get('dry_run', False), key=f"dryrun_{node_id}")
        node['params'] = {'version': version, 'validate': validate, 'dry_run': dry_run}

    elif node_type.id == "mod_set_metadata":
        creator = st.text_input("Creator", value=params.get('creator', 'PagePlus'), key=f"creator_{node_id}")
        comments = st.text_area("Comments", value=params.get('comments', ''), key=f"comments_{node_id}")
        col1, col2 = st.columns(2)
        with col1:
            use_default = st.checkbox("Use Default Metadata", value=params.get('use_default', False), key=f"default_{node_id}")
        with col2:
            new_metadata = st.checkbox("Overwrite Existing", value=params.get('new_metadata', False), key=f"new_{node_id}")
        dry_run = st.checkbox("Dry run only", value=params.get('dry_run', False), key=f"dryrun_{node_id}")
        node['params'] = {'creator': creator, 'comments': comments, 'default': use_default, 'new': new_metadata, 'dry_run': dry_run}

    elif node_type.id == "mod_reassign_ids":
        mode = st.selectbox(
            "Reading Order Mode",
            ["auto", "left-to-right", "right-to-left", "top-to-bottom"],
            index=0,
            key=f"mode_{node_id}"
        )
        dry_run = st.checkbox("Dry run only", value=params.get('dry_run', False), key=f"dryrun_{node_id}")
        node['params'] = {'reading_order_mode': mode, 'dry_run': dry_run}

    # New Text-Layout nodes
    elif node_type.id == "mod_pseudoline_polygon":
        dry_run = st.checkbox("Dry run only", value=params.get('dry_run', False), key=f"dryrun_{node_id}")
        node['params'] = {'dry_run': dry_run}

    elif node_type.id == "mod_recalculate_polygon":
        rectangular = st.checkbox("Rectangular", value=params.get('rectangular', False), key=f"rect_{node_id}")
        min_textlines = st.number_input("Minimum Textlines", min_value=0, value=params.get('min_textlines', 0), key=f"min_tl_{node_id}")
        dry_run = st.checkbox("Dry run only", value=params.get('dry_run', False), key=f"dryrun_{node_id}")
        node['params'] = {'rectangular': rectangular, 'min_textlines': min_textlines, 'dry_run': dry_run}

    elif node_type.id == "mod_match_textlines":
        slice_spanning = st.checkbox(
            "Slice textlines spanning multiple regions",
            value=params.get('slice_spanning', False),
            help=(
                "If enabled, textlines overlapping multiple regions are split into separate "
                "textlines per region using the polygon intersection."
            ),
            key=f"slice_{node_id}"
        )
        slice_min_overlap = st.number_input(
            "Slice min overlap",
            min_value=0.0,
            max_value=1.0,
            value=float(params.get('slice_min_overlap', 0.1)),
            step=0.05,
            help=(
                "Minimum intersection-over-line-area ratio for a region to receive a slice. "
                "Only applies when slicing is enabled."
            ),
            key=f"slice_min_{node_id}",
            disabled=not slice_spanning
        )
        dry_run = st.checkbox("Dry run only", value=params.get('dry_run', False), key=f"dryrun_{node_id}")
        node['params'] = {
            'slice_spanning': slice_spanning,
            'slice_min_overlap': slice_min_overlap,
            'dry_run': dry_run
        }

    # New Sorting node
    elif node_type.id == "mod_sort":
        dry_run = st.checkbox("Dry run only", value=params.get('dry_run', False), key=f"dryrun_{node_id}")
        node['params'] = {'dry_run': dry_run}

    # Updated merge column aligned with new options
    elif node_type.id == "mod_merge_column_aligned":
        based_on_baselines = st.checkbox("Based on baselines", value=params.get('based_on_baselines', False), key=f"bob_{node_id}")
        convex_hull_method = st.selectbox(
            "Convex Hull Method",
            ["region", "textlines"],
            index=0,
            key=f"hull_method_{node_id}"
        )
        max_height_distance = st.slider("Max Height Distance (%)", 0.0, 1.0, value=params.get('max_height_distance', 0.75), key=f"mhd_{node_id}")
        mid_tolerance = st.slider("Mid Tolerance (%)", 0.0, 1.0, value=params.get('mid_tolerance', 0.0), key=f"mid_tol_{node_id}")
        tolerance = st.slider("Tolerance", 0.01, 1.0, value=params.get('tolerance', 0.1), key=f"tol_{node_id}")
        dry_run = st.checkbox("Dry run only", value=params.get('dry_run', False), key=f"dryrun_{node_id}")
        node['params'] = {
            'based_on_baselines': based_on_baselines,
            'convex_hull_method': convex_hull_method,
            'max_height_distance': max_height_distance,
            'mid_tolerance': mid_tolerance,
            'tolerance': tolerance,
            'dry_run': dry_run
        }

    # Updated merge regions with new options
    elif node_type.id == "mod_merge_regions":
        min_overlap = st.slider("Min overlap (%)", 0.0, 100.0, value=params.get('min_overlap', 50.0), key=f"mo_{node_id}")
        recalculate_hull = st.checkbox("Recalculate convex hull from textlines", value=params.get('recalculate_hull', False), key=f"recalc_{node_id}")
        dry_run = st.checkbox("Dry run only", value=params.get('dry_run', False), key=f"dryrun_{node_id}")
        node['params'] = {'min_overlap': min_overlap, 'recalculate_convex_hull': recalculate_hull, 'dry_run': dry_run}

    # Updated split big regions with new options
    elif node_type.id == "mod_split_big_regions":
        split_min_area = st.number_input("Minimum Area for Splitting", min_value=0, value=params.get('split_min_area', 4500000), key=f"sma_{node_id}")
        scale_min_area = st.number_input("Scale Area by Max Lines", min_value=0, value=params.get('scale_min_area', 140), key=f"sma_scale_{node_id}")
        dry_run = st.checkbox("Dry run only", value=params.get('dry_run', False), key=f"dryrun_{node_id}")
        node['params'] = {'split_min_area': split_min_area, 'scale_min_area_by_maxlines': scale_min_area, 'dry_run': dry_run}

    # Updated sort and merge with new options
    elif node_type.id == "mod_sort_and_merge":
        merge_gap_x = st.number_input("Merge lines gap X", min_value=0, value=params.get('merge_gap_x', 64), key=f"mgx_{node_id}")
        merge_gap_y = st.number_input("Merge lines gap Y", min_value=0, value=params.get('merge_gap_y', 10), key=f"mgy_{node_id}")
        dry_run = st.checkbox("Dry run only", value=params.get('dry_run', False), key=f"dryrun_{node_id}")
        node['params'] = {'merge_lines_gap_x': merge_gap_x, 'merge_lines_gap_y': merge_gap_y, 'dry_run': dry_run}

    else:
        st.caption("No parameters for this node")


def _render_processing_params(node: Dict, node_type: NodeType):
    """Render processing node parameters (OCR/LLM nodes)."""
    node_id = node['id']
    params = node.get('params', {})

    # Get available models and stages
    manager = PipelineManager()
    available_models = get_available_models()
    settings = Settings()

    if node_type.id.startswith("gemini_"):
        # Model selection
        if available_models:
            model = st.selectbox(
                "Model",
                ["Use Default"] + available_models,
                index=0 if params.get('model') == "Use Default" or not params.get('model') else 1,
                key=f"model_{node_id}"
            )
        else:
            st.warning("No models available. Please add models in Gemini Settings.")
            model = "Use Default"

        # Execution mode selection: All-in-One (quick mode) or Pipeline
        exec_mode = st.radio(
            "Execution Mode",
            ["All-in-One", "Pipeline"],
            index=0 if params.get('exec_mode', 'All-in-One') == 'All-in-One' else 1,
            horizontal=True,
            key=f"exec_mode_{node_id}",
            help="All-in-One: Quick mode with single stage | Pipeline: Multi-stage workflow"
        )

        # Get category and available stages/pipelines
        category = "OCR" if "ocr" in node_type.id else "ReOCR"
        all_stages = manager.get_stages_by_category(category)
        all_pipelines = manager.get_pipelines_by_category(category)

        if exec_mode == "All-in-One":
            # Show All-in-One stages only
            proc_type = "All-in-One" if node_type.id == "gemini_ocr" else "Text Recognition"
            matching_stages = [s for s in all_stages if s.get('type') == proc_type]

            if matching_stages:
                stage_names = [f"{s.get('name')} ({s.get('collection')})" for s in matching_stages]
                selected_stage_index = 0
                current_stage = params.get('stage')
                if current_stage:
                    for i, name in enumerate(stage_names):
                        if current_stage in name:
                            selected_stage_index = i + 1
                            break

                selected_stage = st.selectbox(
                    "Select All-in-One Stage",
                    ["(Default)"] + stage_names,
                    index=selected_stage_index,
                    key=f"stage_{node_id}"
                )
                if selected_stage != "(Default)":
                    node['params']['stage'] = selected_stage
                else:
                    node['params'].pop('stage', None)
            else:
                st.info("No All-in-One stages available. Create stages in the Pipeline Editor.")
                node['params'].pop('stage', None)

        else:  # Pipeline mode
            # Show available pipelines
            if all_pipelines:
                pipeline_names = all_pipelines
                selected_pipeline_index = 0
                current_pipeline = params.get('pipeline')
                if current_pipeline and current_pipeline in pipeline_names:
                    selected_pipeline_index = pipeline_names.index(current_pipeline) + 1

                selected_pipeline = st.selectbox(
                    "Select Pipeline",
                    ["(None)"] + pipeline_names,
                    index=selected_pipeline_index,
                    key=f"pipeline_{node_id}"
                )
                if selected_pipeline != "(None)":
                    node['params']['pipeline'] = selected_pipeline
                    # Show pipeline details
                    pipeline_data = manager.get_pipeline(selected_pipeline)
                    with st.expander("Pipeline Details", expanded=False):
                        st.caption(f"**Description:** {pipeline_data.get('description', 'No description')}")
                        st.caption(f"**Stages:** {len(pipeline_data.get('stages', []))}")
                        for i, stage_ref in enumerate(pipeline_data.get('stages', []), 1):
                            stage = manager.get_stage_by_id(stage_ref.get('collection'), stage_ref.get('stage_id'))
                            if stage:
                                st.caption(f"{i}. {stage.get('name')} ({stage.get('type')})")
                else:
                    node['params'].pop('pipeline', None)
            else:
                st.info("No pipelines available. Create pipelines in the Pipeline Editor.")
                node['params'].pop('pipeline', None)

        # Thinking budget
        thinking_budget = st.number_input(
            "Thinking Budget",
            min_value=0,
            value=params.get('thinking_budget', int(settings.get("THINKING_BUDGET", "0"))),
            key=f"think_{node_id}"
        )

        # Recognize level (for OCR/ReOCR)
        rec_options = ["Page", "TextRegion", "Textline"]
        if node_type.id == "gemini_reocr":
            rec_options = ["Page", "TextRegion", "TableRegion"]
        recognize_level = st.selectbox(
            "Recognize Level",
            rec_options,
            index=rec_options.index(params.get('recognize_level', 'TextRegion')) if params.get('recognize_level') in rec_options else 1,
            key=f"rec_level_{node_id}"
        )

        # Update elements (for ReOCR)
        update_elements = []
        if node_type.id == "gemini_reocr":
            update_elements = st.multiselect(
                "Update Elements",
                ["Text", "Tags"],
                default=params.get('update_elements', ["Text", "Tags"]),
                key=f"upd_elem_{node_id}"
            )

        node['params'] = {
            'model': model,
            'exec_mode': exec_mode,
            'thinking_budget': thinking_budget,
            'recognize_level': recognize_level,
            'update_elements': update_elements if update_elements else []
        }
        # Preserve stage/pipeline selections (set earlier in the code)
        if 'stage' in node['params']:
            node['params']['stage'] = node['params']['stage']
        if 'pipeline' in node['params']:
            node['params']['pipeline'] = node['params']['pipeline']

    elif node_type.id.startswith("tesseract_"):
        st.info("Tesseract OCR processing")
        model = st.text_input("Model (optional)", value=params.get('model', ''), key=f"model_{node_id}")
        node['params'] = {'model': model}

    elif node_type.id.startswith("kraken_"):
        st.info("Kraken OCR processing")
        model = st.text_input("Model (optional)", value=params.get('model', ''), key=f"model_{node_id}")
        node['params'] = {'model': model}

    elif node_type.id.startswith("llm_"):
        st.info(f"{node_type.label} processing (coming soon)")
        provider = node_type.id.replace("llm_", "")
        model = st.text_input("Model", value=params.get('model', ''), key=f"model_{node_id}")
        api_key = st.text_input("API Key (optional, uses settings if empty)", type="password", value=params.get('api_key', ''), key=f"apikey_{node_id}")
        system_prompt = st.text_area("System Prompt", value=params.get('system_prompt', ''), key=f"sysprompt_{node_id}", height=100)
        node['params'] = {'provider': provider, 'model': model, 'api_key': api_key, 'system_prompt': system_prompt}


def _render_output_params(node: Dict, node_type: NodeType):
    """Render output node parameters."""
    node_id = node['id']
    params = node.get('params', {})

    # Use a key suffix that changes when directory is picked via picker
    # This forces Streamlit to create a fresh widget with the new value
    picker_key_suffix = st.session_state.get(f'picker_{node_id}', '')

    if node_type.id == "output_save":
        col1, col2 = st.columns([4, 1])
        with col1:
            output_dir = st.text_input(
                "Output Directory",
                value=params.get('output_dir', ''),
                key=f"outdir_{node_id}_{picker_key_suffix}",
                help="Leave empty to overwrite input files"
            )
        with col2:
            if st.button("📁", help="Browse directory", key=f"browse_out_dir_{node_id}"):
                selected_dir = pick_directory(initial_dir=get_loaded_workspace_dir())
                if selected_dir:
                    # Update directly in node's params to persist across reruns
                    node['params']['output_dir'] = selected_dir
                    # Change the key suffix to force widget refresh
                    st.session_state[f'picker_{node_id}'] = str(time.time())
                    st.rerun()

        create_backup = st.checkbox(
            "Create backup before overwriting",
            value=params.get('create_backup', True),
            key=f"backup_{node_id}"
        )
        # Use text input value if it was changed, otherwise keep existing
        final_output_dir = output_dir if output_dir else params.get('output_dir', '')
        node['params'] = {'output_dir': final_output_dir, 'create_backup': create_backup}

    elif node_type.id == "output_export":
        export_format = st.selectbox(
            "Export Format",
            ["ALTO", "PDF", "Text", "PAGE-XML"],
            index=["ALTO", "PDF", "Text", "PAGE-XML"].index(params.get('format', 'PAGE-XML')) if params.get('format') in ["ALTO", "PDF", "Text", "PAGE-XML"] else 3,
            key=f"fmt_{node_id}"
        )
        col1, col2 = st.columns([4, 1])
        with col1:
            output_dir = st.text_input(
                "Output Directory",
                value=params.get('output_dir', ''),
                key=f"outdir_{node_id}_{picker_key_suffix}"
            )
        with col2:
            if st.button("📁", help="Browse directory", key=f"browse_export_dir_{node_id}"):
                selected_dir = pick_directory(initial_dir=get_loaded_workspace_dir())
                if selected_dir:
                    node['params']['output_dir'] = selected_dir
                    st.session_state[f'picker_{node_id}'] = str(time.time())
                    st.rerun()

        final_output_dir = output_dir if output_dir else params.get('output_dir', '')
        node['params'] = {'format': export_format, 'output_dir': final_output_dir}

    elif node_type.id in ["output_alto", "output_pdf", "output_text"]:
        col1, col2 = st.columns([4, 1])
        with col1:
            output_dir = st.text_input(
                "Output Directory",
                value=params.get('output_dir', ''),
                key=f"outdir_{node_id}_{picker_key_suffix}"
            )
        with col2:
            if st.button("📁", help="Browse directory", key=f"browse_{node_type.id}_dir_{node_id}"):
                selected_dir = pick_directory(initial_dir=get_loaded_workspace_dir())
                if selected_dir:
                    node['params']['output_dir'] = selected_dir
                    st.session_state[f'picker_{node_id}'] = str(time.time())
                    st.rerun()

        final_output_dir = output_dir if output_dir else params.get('output_dir', '')
        node['params'] = {'output_dir': final_output_dir}


def _build_execution_graph():
    """Build a dependency graph for topological execution following edges."""
    # Build adjacency list and in-degree count
    graph = {}  # node_id -> [dependent_node_ids]
    in_degree = {}  # node_id -> number of incoming edges

    # Get set of valid node IDs
    valid_node_ids = {node['id'] for node in st.session_state.flow_nodes}

    for node in st.session_state.flow_nodes:
        node_id = node['id']
        graph[node_id] = []
        in_degree[node_id] = 0

    # Add edges (source -> target means source feeds into target)
    # Only add edges where both source and target exist (orphaned edges are skipped)
    for edge in st.session_state.flow_edges:
        source = edge['source']
        target = edge['target']
        # Only add edge if both nodes exist
        if source in graph and target in in_degree:
            graph[source].append(target)
            in_degree[target] += 1

    return graph, in_degree


def _topological_sort_with_grouping():
    """Sort nodes topologically and group them by level for execution."""
    graph, in_degree = _build_execution_graph()

    # Find all nodes (sources) with no incoming edges
    queue = [node_id for node_id, degree in in_degree.items() if degree == 0]
    levels = []  # List of lists, each inner list is a level of nodes that can execute in parallel

    node_map = {node['id']: node for node in st.session_state.flow_nodes}

    visited = set()

    while queue:
        current_level = queue[:]
        queue = []
        levels.append(current_level)

        for node_id in current_level:
            if node_id in visited:
                continue
            visited.add(node_id)

            # Decrease in-degree for neighbors
            for neighbor in graph.get(node_id, []):
                if neighbor in in_degree:  # Only process if neighbor still exists
                    in_degree[neighbor] -= 1
                    if in_degree[neighbor] == 0:
                        queue.append(neighbor)

    # Check for cycles
    if len(visited) != len(st.session_state.flow_nodes):
        # Cycle detected - fall back to stage-based execution
        return None

    # Convert node IDs to actual nodes
    result_levels = []
    for level in levels:
        result_levels.append([node_map[nid] for nid in level if nid in node_map])

    return result_levels


def _copy_files_to_output_dir(files: list, output_dir: str, log: list) -> list:
    """Copy input files to the output directory and return the copied file paths."""
    import shutil
    from pathlib import Path

    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)

    copied_files = []
    for file_path in files:
        file_path = Path(file_path)
        if file_path.exists():
            dest_path = output_path / file_path.name
            shutil.copy2(file_path, dest_path)
            copied_files.append(dest_path)
            log.append(f"   📋 Copied: {file_path.name} -> {dest_path}")

    return copied_files


def _check_direct_xml_to_save_connection() -> bool:
    """Check if any XML Input node is connected directly to a Save Output node."""
    # Build adjacency list
    outgoing = {}  # node_id -> [target_node_ids]
    for edge in st.session_state.flow_edges:
        source = edge['source']
        target = edge['target']
        if source not in outgoing:
            outgoing[source] = []
        outgoing[source].append(target)

    # Check for direct connection from input_xml to output_save
    for node in st.session_state.flow_nodes:
        if node['node_type'] == 'input_xml':
            targets = outgoing.get(node['id'], [])
            for target_id in targets:
                target_node = next((n for n in st.session_state.flow_nodes if n['id'] == target_id), None)
                if target_node and target_node['node_type'] == 'output_save':
                    return True, node.get('name', 'XML Input'), target_node.get('name', 'Save Output')

    return False, None, None


def _render_monitor_tab():
    """Render the execution monitor tab with node status, progress bar, and terminal log."""
    node_states = st.session_state.flow_exec_node_states
    log_lines = st.session_state.flow_exec_log_lines
    current_step = st.session_state.flow_exec_current_step
    total_steps = st.session_state.flow_exec_total_steps
    is_active = st.session_state.flow_exec_active

    if not node_states and not log_lines:
        st.info("Click **▶️ Run Workflow** in the Editor tab to start execution.")
        return

    # --- Header with status ---
    if is_active:
        # Animated pulsing header for running state
        st.markdown("""
        <style>
        @keyframes pulse {
            0%, 100% { opacity: 1; }
            50% { opacity: 0.5; }
        }
        .exec-running-header {
            animation: pulse 1.5s ease-in-out infinite;
            font-size: 1.5rem;
            font-weight: 700;
            margin-bottom: 0.5rem;
        }
        @keyframes blink-dot {
            0%, 100% { opacity: 0.2; }
            50% { opacity: 1; }
        }
        .exec-dot { display: inline-block; animation: blink-dot 1.4s infinite; }
        .exec-dot:nth-child(2) { animation-delay: 0.2s; }
        .exec-dot:nth-child(3) { animation-delay: 0.4s; }
        </style>
        <div class="exec-running-header">
            ⏳ Workflow Running<span class="exec-dot">.</span><span class="exec-dot">.</span><span class="exec-dot">.</span>
        </div>
        """, unsafe_allow_html=True)

        # Show which node is currently being processed
        running_nodes = [n.get('name', n.get('node_type', '?'))
                         for n in st.session_state.flow_nodes
                         if node_states.get(n['id']) == 'running']
        if running_nodes:
            st.info(f"🔄 Processing: **{running_nodes[0]}**")
    else:
        # Check if any node failed
        has_failure = any(s == 'failed' for s in node_states.values())
        if has_failure:
            st.markdown("### ❌ Workflow Finished with Errors")
        else:
            st.markdown("### ✅ Workflow Complete")

    # --- Progress bar ---
    if total_steps > 0:
        progress = current_step / total_steps
        st.progress(progress, text=f"Step {current_step} / {total_steps}")
    else:
        st.progress(0.0, text="Preparing...")

    # --- Node status list ---
    st.markdown("#### Node Status")

    # Build a styled list of all nodes with their status
    for node in st.session_state.flow_nodes:
        node_id = node['id']
        node_name = node.get('name', node.get('node_type', 'Node'))
        state = node_states.get(node_id, 'pending')

        if state == 'done':
            icon = "🟢"
            color = "#4CAF50"
            label = "Done"
        elif state == 'failed':
            icon = "🔴"
            color = "#F44336"
            label = "Failed"
        elif state == 'running':
            icon = "🔵"
            color = "#2196F3"
            label = "Running"
        else:  # pending
            icon = "⬜"
            color = "#9E9E9E"
            label = "Pending"

        st.markdown(
            f'<div style="display:flex;align-items:center;padding:0.3rem 0.6rem;margin:0.15rem 0;'
            f'border-left:4px solid {color};background:{"rgba(33,150,243,0.12)" if state == "running" else "transparent"};'
            f'border-radius:0 0.3rem 0.3rem 0;">'
            f'<span style="font-size:1.1rem;margin-right:0.5rem;">{icon}</span>'
            f'<span style="flex:1;color:{"#fff" if state == "running" else "inherit"};'
            f'font-weight:{"700" if state == "running" else "400"};">{node_name}</span>'
            f'<span style="font-size:0.8rem;color:{color};font-weight:600;">{label}</span>'
            f'</div>',
            unsafe_allow_html=True
        )

    # --- Stop button ---
    if is_active:
        st.markdown("")
        if st.button("⏹️ Stop Execution", type="secondary", use_container_width=True):
            st.session_state.flow_exec_active = False
            st.session_state.flow_exec_log_lines.append("")
            st.session_state.flow_exec_log_lines.append("⏹️ EXECUTION STOPPED BY USER")
            st.session_state.flow_execution_log = "\n".join(st.session_state.flow_exec_log_lines)
            st.session_state.flow_active_tab = 'editor'
            st.rerun()
    else:
        # Execution finished - show back button
        if st.button("🔀 Back to Editor", type="primary", use_container_width=True):
            st.session_state.flow_active_tab = 'editor'
            st.rerun()

    # --- Terminal log ---
    st.markdown("#### Terminal Log")
    log_text = "\n".join(log_lines) if log_lines else "(no output yet)"
    st.code(log_text, language="text")


def _start_execution(dry_run: bool = False, continue_on_error: bool = False):
    """Initialize execution state and trigger step-by-step execution."""
    if not st.session_state.flow_nodes:
        st.warning("No nodes in workflow!")
        return

    # Build initial log
    log = []
    log.append("=" * 60)
    log.append("WORKFLOW EXECUTION")
    log.append("=" * 60)
    log.append(f"Nodes: {len(st.session_state.flow_nodes)}")
    log.append(f"Edges: {len(st.session_state.flow_edges)}")
    log.append(f"Dry Run: {dry_run}")
    log.append(f"Continue on Error: {continue_on_error}")
    log.append("")

    # Check for direct XML Input -> Save Output connection
    is_direct_connection, xml_node_name, save_node_name = _check_direct_xml_to_save_connection()

    # Get topological sort
    execution_levels = _topological_sort_with_grouping()
    if execution_levels is None:
        log.append("⚠️ Cycle detected in workflow, falling back to stage-based execution")
        execution_order = ["input", "processing", "modification", "output"]
        nodes_by_stage = {stage: [] for stage in execution_order}
        for node in st.session_state.flow_nodes:
            category = node.get('category', 'input')
            if category in nodes_by_stage:
                nodes_by_stage[category].append(node)
        execution_levels = [nodes_by_stage[stage] for stage in execution_order]

    # Flatten execution plan
    exec_plan = []
    for level_idx, level_nodes in enumerate(execution_levels):
        for node in level_nodes:
            exec_plan.append(node)

    # Get input files
    input_files = []
    has_input_page_files = st.session_state.get('loaded_files') is not None

    for node in st.session_state.flow_nodes:
        if node['node_type'] == 'input_directory':
            params = node.get('params', {})
            directory = params.get('directory', '')
            if directory and Path(directory).exists():
                extensions = params.get('extensions', '.xml,.jpg,.png').split(',')
                exts = [e.strip() if e.startswith('.') else f'.{e.strip()}' for e in extensions]
                for ext in exts:
                    input_files.extend([f for f in Path(directory).glob(f'*{ext}')])
                log.append(f"📁 Directory node '{directory}': {len([f for f in input_files if f.suffix in exts])} files")

        elif node['node_type'] == 'input_image':
            params = node.get('params', {})
            source = params.get('source', 'Select files')

            if source == "Directory":
                directory = params.get('directory', '')
                if directory and Path(directory).exists():
                    extensions = params.get('extensions', '.jpg,.jpeg,.png,.tif,.tiff,.webp').split(',')
                    exts = [e.strip() if e.startswith('.') else f'.{e.strip()}' for e in extensions]
                    recursive = params.get('recursive', False)
                    pattern = '**/*' if recursive else '*'
                    for ext in exts:
                        input_files.extend([f for f in Path(directory).glob(f'{pattern}{ext}')])
                    log.append(f"🖼️ Image Directory node '{directory}': {len([f for f in input_files if f.suffix in exts])} files")

            elif source == "Select files":
                files_key = params.get('files_key')
                if files_key and files_key in st.session_state:
                    selected_paths = st.session_state[files_key]
                    input_files.extend([Path(f) for f in selected_paths])
                    log.append(f"🖼️ Selected files: {len(selected_paths)} file(s)")
                else:
                    log.append(f"⚠️ Image file selection node: No files selected")

    if not input_files and has_input_page_files:
        input_files = list(st.session_state.loaded_files)
        log.append(f"📂 Input page files: {len(input_files)}")

    if not input_files:
        log.append("⚠️ WARNING: No input files available!")
        st.session_state.flow_execution_log = "\n".join(log)
        st.warning("No input files available!")
        return

    # Find output directory
    global_output_dir = None
    for node in st.session_state.flow_nodes:
        if node['node_type'] == 'output_save':
            output_dir = node.get('params', {}).get('output_dir', '')
            if output_dir:
                global_output_dir = output_dir
                log.append(f"📁 Output directory: {global_output_dir}")
                break

    # Handle direct XML -> Save connection
    copied_files_for_next_node = None
    if is_direct_connection and global_output_dir:
        log.append("")
        log.append("📋 Direct XML Input -> Save Output connection detected")
        log.append(f"   Copying input files to output directory: {global_output_dir}")
        if not dry_run:
            copied_files_for_next_node = _copy_files_to_output_dir(input_files, global_output_dir, log)
        else:
            output_path = Path(global_output_dir)
            copied_files_for_next_node = [output_path / f.name for f in input_files]
        log.append(f"   ✓ Copied {len(copied_files_for_next_node)} file(s)")

    # Build execution plan log
    log.append("")
    log.append("EXECUTION PLAN:")
    log.append("")
    for step, node in enumerate(exec_plan, 1):
        params = node.get('params', {})
        param_str = ", ".join(f"{k}={v}" for k, v in params.items() if v and v != "")
        log.append(f"{step}. {node.get('name')} ({node.get('node_type')})")
        if param_str:
            log.append(f"   Params: {param_str}")

    log.append("")
    log.append("EXECUTION:")
    log.append("")

    # Import bridges lazily
    try:
        from pageplus.gui.cli_bridges import ModificationBridge, ExportBridge
        from pageplus.gui.cli_bridges.tesseract import TesseractBridge
    except ImportError as e:
        log.append(f"❌ ERROR: Failed to import bridges: {e}")
        st.session_state.flow_execution_log = "\n".join(log)
        st.error("Failed to import required bridges.")
        return

    # Build edge lookup
    incoming_edges = {}
    for edge in st.session_state.flow_edges:
        target = edge['target']
        source = edge['source']
        if target not in incoming_edges:
            incoming_edges[target] = []
        incoming_edges[target].append(source)

    # Initialize node states: all pending
    node_states = {}
    for node in st.session_state.flow_nodes:
        node_states[node['id']] = 'pending'

    # Current files to use
    current_files = copied_files_for_next_node if copied_files_for_next_node else input_files

    # Save execution context
    st.session_state.flow_exec_context = {
        'dry_run': dry_run,
        'continue_on_error': continue_on_error,
        'current_files': current_files,
        'node_output_files': {},
        'incoming_edges': incoming_edges,
        'global_output_dir': global_output_dir,
        'copied_files_for_next_node': copied_files_for_next_node,
        'input_files': input_files,
    }

    # Set execution state
    st.session_state.flow_exec_active = True
    st.session_state.flow_exec_node_states = node_states
    st.session_state.flow_exec_current_step = 0
    st.session_state.flow_exec_total_steps = len(exec_plan)
    st.session_state.flow_exec_log_lines = log
    st.session_state.flow_exec_plan = exec_plan
    st.session_state.flow_active_tab = 'monitor'

    st.rerun()


def _execute_next_step():
    """Execute the next node in the execution plan (one node per rerun cycle)."""
    if not st.session_state.flow_exec_active:
        return

    plan = st.session_state.flow_exec_plan
    step_idx = st.session_state.flow_exec_current_step
    log = st.session_state.flow_exec_log_lines
    ctx = st.session_state.flow_exec_context

    if step_idx >= len(plan):
        # Execution complete
        log.append("=" * 60)
        log.append("EXECUTION COMPLETE")
        log.append("")
        st.session_state.flow_exec_active = False
        st.session_state.flow_execution_log = "\n".join(log)
        st.rerun()
        return

    node = plan[step_idx]
    node_type_id = node['node_type']
    node_name = node.get('name', 'Node')
    node_id = node['id']
    params = node.get('params', {})

    all_types = get_available_node_types()
    node_type = all_types.get(node_type_id)

    # Mark as running
    st.session_state.flow_exec_node_states[node_id] = 'running'

    log.append(f"▶️ Executing: {node_name}")

    if not node_type or not node_type.enabled:
        log.append(f"   ⚠️ Skipped (node type disabled or not found)")
        st.session_state.flow_exec_node_states[node_id] = 'done'
        st.session_state.flow_exec_current_step = step_idx + 1
        log.append("")
        if not ctx['continue_on_error']:
            st.session_state.flow_exec_active = False
            st.session_state.flow_execution_log = "\n".join(log)
        st.rerun()
        return

    # Determine input files for this node
    current_files = ctx['current_files']
    node_output_files = ctx['node_output_files']
    incoming_edges = ctx['incoming_edges']
    node_input_files = current_files

    if node_id in incoming_edges:
        source_ids = incoming_edges[node_id]
        source_files = []
        for source_id in source_ids:
            if source_id in node_output_files:
                source_files.extend(node_output_files[source_id])

        if source_files:
            node_input_files = source_files
            log.append(f"   📥 Input files from {len(source_ids)} source node(s): {len(node_input_files)} file(s)")
        else:
            copied = ctx.get('copied_files_for_next_node')
            node_input_files = copied if copied else ctx['input_files']
            log.append(f"   📥 Using base input files: {len(node_input_files)} file(s)")

    dry_run = ctx['dry_run']
    continue_on_error = ctx['continue_on_error']
    global_output_dir = ctx['global_output_dir']
    copied_files_for_next_node = ctx.get('copied_files_for_next_node')
    success = True

    try:
        # Import bridges lazily for each step
        from pageplus.gui.cli_bridges import ModificationBridge, ExportBridge
        from pageplus.gui.cli_bridges.tesseract import TesseractBridge

        modification_bridge = ModificationBridge()
        export_bridge = ExportBridge()
        tesseract_bridge = TesseractBridge()

        if node_type_id.startswith('mod_'):
            result = _execute_modification_node(
                node_type_id, node_input_files, params, dry_run, log, modification_bridge, global_output_dir
            )
            if not result.get('success', True):
                log.append(f"   ❌ Failed: {result.get('error', 'Unknown error')}")
                success = False
            else:
                log.append(f"   ✓ {result.get('message', 'Completed')}")
                if global_output_dir and result.get('output_files'):
                    node_output_files[node_id] = result['output_files']
                    log.append(f"   📤 Output files: {len(result['output_files'])} file(s)")

        elif node_type_id.startswith('gemini_'):
            result = _execute_gemini_node(
                node_type_id, node_input_files, params, dry_run, log, global_output_dir
            )
            if not result.get('success', True):
                log.append(f"   ❌ Failed: {result.get('error', 'Unknown error')}")
                success = False
            else:
                log.append(f"   ✓ {result.get('message', 'Completed')}")
                if global_output_dir and result.get('output_files'):
                    node_output_files[node_id] = result['output_files']
                    log.append(f"   📤 Output files: {len(result['output_files'])} file(s)")

        elif node_type_id.startswith('tesseract_'):
            result = _execute_tesseract_node(
                node_input_files, params, dry_run, log, tesseract_bridge, global_output_dir
            )
            if not result.get('success', True):
                log.append(f"   ❌ Failed: {result.get('error', 'Unknown error')}")
                success = False
            else:
                log.append(f"   ✓ {result.get('message', 'Completed')}")
                if global_output_dir and result.get('output_files'):
                    node_output_files[node_id] = result['output_files']
                    log.append(f"   📤 Output files: {len(result['output_files'])} file(s)")

        elif node_type_id.startswith('kraken_'):
            result = _execute_kraken_node(
                node_input_files, params, dry_run, log, global_output_dir
            )
            if not result.get('success', True):
                log.append(f"   ❌ Failed: {result.get('error', 'Unknown error')}")
                success = False
            else:
                log.append(f"   ✓ {result.get('message', 'Completed')}")
                if global_output_dir and result.get('output_files'):
                    node_output_files[node_id] = result['output_files']
                    log.append(f"   📤 Output files: {len(result['output_files'])} file(s)")

        elif node_type_id.startswith('output_'):
            result = _execute_output_node(
                node_type_id, node_input_files, params, dry_run, log, export_bridge
            )
            if not result.get('success', True):
                log.append(f"   ❌ Failed: {result.get('error', 'Unknown error')}")
                success = False
            else:
                log.append(f"   ✓ {result.get('message', 'Completed')}")
                if node_type_id == 'output_save' and copied_files_for_next_node:
                    node_output_files[node_id] = copied_files_for_next_node
                    log.append(f"   📤 Output files (from Save Output): {len(copied_files_for_next_node)} file(s)")

        elif node_type_id.startswith('input_'):
            log.append(f"   ✓ Input node (files already collected)")

        else:
            log.append(f"   ⚠️ Unknown node type: {node_type_id}")

    except Exception as e:
        import traceback
        log.append(f"   ❌ Exception: {str(e)}")
        log.append(f"   Traceback: {traceback.format_exc()}")
        success = False

    log.append("")

    # Update node state
    st.session_state.flow_exec_node_states[node_id] = 'done' if success else 'failed'

    # Update context
    ctx['node_output_files'] = node_output_files
    st.session_state.flow_exec_context = ctx

    # Advance step
    st.session_state.flow_exec_current_step = step_idx + 1

    # Check if should stop
    if not success and not continue_on_error:
        st.session_state.flow_exec_active = False
        log.append("=" * 60)
        log.append("EXECUTION STOPPED (error encountered)")
        log.append("")
        st.session_state.flow_execution_log = "\n".join(log)
    elif step_idx + 1 >= len(plan):
        # All done
        st.session_state.flow_exec_active = False
        log.append("=" * 60)
        log.append("EXECUTION COMPLETE")
        log.append("")
        st.session_state.flow_execution_log = "\n".join(log)

    st.rerun()


def _execute_workflow(dry_run: bool = False, continue_on_error: bool = False):
    """Execute the workflow."""
    if not st.session_state.flow_nodes:
        st.warning("No nodes in workflow!")
        return

    # Start execution log
    log = []
    log.append("=" * 60)
    log.append("WORKFLOW EXECUTION")
    log.append("=" * 60)
    log.append(f"Nodes: {len(st.session_state.flow_nodes)}")
    log.append(f"Edges: {len(st.session_state.flow_edges)}")
    log.append(f"Dry Run: {dry_run}")
    log.append(f"Continue on Error: {continue_on_error}")
    log.append("")

    # Check for direct XML Input -> Save Output connection
    is_direct_connection, xml_node_name, save_node_name = _check_direct_xml_to_save_connection()

    # Try topological sort following edges, fall back to stage-based if cycle detected
    execution_levels = _topological_sort_with_grouping()

    if execution_levels is None:
        log.append("⚠️ Cycle detected in workflow, falling back to stage-based execution")
        # Fall back to original stage-based execution
        execution_order = ["input", "processing", "modification", "output"]
        nodes_by_stage = {stage: [] for stage in execution_order}
        for node in st.session_state.flow_nodes:
            category = node.get('category', 'input')
            if category in nodes_by_stage:
                nodes_by_stage[category].append(node)
        execution_levels = [nodes_by_stage[stage] for stage in execution_order]

    # Get input files
    input_files = []
    has_input_page_files = st.session_state.get('loaded_files') is not None

    # Check for specific input nodes
    for node in st.session_state.flow_nodes:
        if node['node_type'] == 'input_directory':
            params = node.get('params', {})
            directory = params.get('directory', '')
            if directory and Path(directory).exists():
                extensions = params.get('extensions', '.xml,.jpg,.png').split(',')
                exts = [e.strip() if e.startswith('.') else f'.{e.strip()}' for e in extensions]
                for ext in exts:
                    input_files.extend([f for f in Path(directory).glob(f'*{ext}')])
                log.append(f"📁 Directory node '{directory}': {len([f for f in input_files if f.suffix in exts])} files")

        elif node['node_type'] == 'input_image':
            params = node.get('params', {})
            source = params.get('source', 'Input page files')

            if source == "Directory":
                directory = params.get('directory', '')
                if directory and Path(directory).exists():
                    extensions = params.get('extensions', '.jpg,.jpeg,.png,.tif,.tiff,.webp').split(',')
                    exts = [e.strip() if e.startswith('.') else f'.{e.strip()}' for e in extensions]
                    recursive = params.get('recursive', False)

                    pattern = '**/*' if recursive else '*'
                    for ext in exts:
                        input_files.extend([f for f in Path(directory).glob(f'{pattern}{ext}')])
                    log.append(f"🖼️ Image Directory node '{directory}': {len([f for f in input_files if f.suffix in exts])} files")

            elif source == "Select files":
                files_key = params.get('files_key')
                if files_key and files_key in st.session_state:
                    selected_paths = st.session_state[files_key]
                    input_files.extend([Path(f) for f in selected_paths])
                    log.append(f"🖼️ Selected files: {len(selected_paths)} file(s)")
                else:
                    log.append(f"⚠️ Image file selection node: No files selected")

    # Also include Input page files if available and no specific input nodes found
    if not input_files and has_input_page_files:
        input_files = list(st.session_state.loaded_files)
        log.append(f"📂 Input page files: {len(input_files)}")

    if not input_files:
        log.append("⚠️ WARNING: No input files available!")
        st.session_state.flow_execution_log = "\n".join(log)
        return

    # Find output directory from Save Output node (to use for modification nodes)
    global_output_dir = None
    for node in st.session_state.flow_nodes:
        if node['node_type'] == 'output_save':
            output_dir = node.get('params', {}).get('output_dir', '')
            if output_dir:
                global_output_dir = output_dir
                log.append(f"📁 Output directory set by Save Output node: {global_output_dir}")
                break

    # If direct connection from XML Input to Save Output, copy files to output dir
    copied_files_for_next_node = None
    if is_direct_connection and global_output_dir:
        log.append("")
        log.append("📋 Direct XML Input -> Save Output connection detected")
        log.append(f"   Copying input files to output directory: {global_output_dir}")
        if not dry_run:
            copied_files_for_next_node = _copy_files_to_output_dir(input_files, global_output_dir, log)
        else:
            log.append(f"   Dry run - would copy {len(input_files)} file(s)")
            # For dry run, simulate the copied files
            output_path = Path(global_output_dir)
            copied_files_for_next_node = [output_path / f.name for f in input_files]
        log.append(f"   ✓ Copied {len(copied_files_for_next_node)} file(s)")

    # Build execution plan following edges
    log.append("")
    log.append("EXECUTION PLAN:")
    log.append("")

    step = 0
    for level_idx, level_nodes in enumerate(execution_levels):
        for node in level_nodes:
            step += 1
            params = node.get('params', {})
            param_str = ", ".join(f"{k}={v}" for k, v in params.items() if v and v != "")
            log.append(f"{step}. {node.get('name')} ({node.get('node_type')})")
            if param_str:
                log.append(f"   Params: {param_str}")

    log.append("")
    log.append("EXECUTION:")
    log.append("")

    # Execute workflow
    current_files = copied_files_for_next_node if copied_files_for_next_node else input_files
    all_types = get_available_node_types()

    # Import bridges lazily
    try:
        from pageplus.gui.cli_bridges import ModificationBridge, ExportBridge
        from pageplus.gui.cli_bridges.tesseract import TesseractBridge
    except ImportError as e:
        log.append(f"❌ ERROR: Failed to import bridges: {e}")
        st.session_state.flow_execution_log = "\n".join(log)
        st.error("Failed to import required bridges. Please check your installation.")
        return

    # Create bridge instances
    modification_bridge = ModificationBridge()
    export_bridge = ExportBridge()
    tesseract_bridge = TesseractBridge()

    # Track files output from each node for next nodes
    node_output_files = {}  # node_id -> list of output files

    # Build edge lookup for finding input sources
    incoming_edges = {}  # node_id -> [source_node_ids]
    for edge in st.session_state.flow_edges:
        target = edge['target']
        source = edge['source']
        if target not in incoming_edges:
            incoming_edges[target] = []
        incoming_edges[target].append(source)

    for level_idx, level_nodes in enumerate(execution_levels):
        for node in level_nodes:
            node_type_id = node['node_type']
            node_name = node.get('name', 'Node')
            node_id = node['id']
            node_type = all_types.get(node_type_id)
            params = node.get('params', {})

            log.append(f"▶️ Executing: {node_name}")

            if not node_type or not node_type.enabled:
                log.append(f"   ⚠️ Skipped (node type disabled or not found)")
                if not continue_on_error:
                    break
                continue

            # Determine input files for this node based on incoming edges
            node_input_files = current_files  # Default to current files

            # If this node has incoming edges, use output files from source nodes
            if node_id in incoming_edges:
                source_ids = incoming_edges[node_id]
                # Collect output files from all source nodes
                source_files = []
                for source_id in source_ids:
                    if source_id in node_output_files:
                        source_files.extend(node_output_files[source_id])

                if source_files:
                    node_input_files = source_files
                    log.append(f"   📥 Input files from {len(source_ids)} source node(s): {len(node_input_files)} file(s)")
                else:
                    # No output files from sources, use current files or input files
                    node_input_files = copied_files_for_next_node if copied_files_for_next_node else input_files
                    log.append(f"   📥 Using base input files: {len(node_input_files)} file(s)")

            try:
                # Execute based on node type
                if node_type_id.startswith('mod_'):
                    result = _execute_modification_node(
                        node_type_id, node_input_files, params, dry_run, log, modification_bridge, global_output_dir
                    )
                    if not result.get('success', True):
                        if not continue_on_error:
                            log.append(f"   ❌ Failed: {result.get('error', 'Unknown error')}")
                            break
                        log.append(f"   ⚠️ Failed (continuing): {result.get('error', 'Unknown error')}")
                    else:
                        log.append(f"   ✓ {result.get('message', 'Completed')}")
                        # Store output files for this node
                        if global_output_dir and result.get('output_files'):
                            node_output_files[node_id] = result['output_files']
                            log.append(f"   📤 Output files: {len(result['output_files'])} file(s)")

                elif node_type_id.startswith('gemini_'):
                    result = _execute_gemini_node(
                        node_type_id, node_input_files, params, dry_run, log, global_output_dir
                    )
                    if not result.get('success', True):
                        if not continue_on_error:
                            log.append(f"   ❌ Failed: {result.get('error', 'Unknown error')}")
                            break
                        log.append(f"   ⚠️ Failed (continuing): {result.get('error', 'Unknown error')}")
                    else:
                        log.append(f"   ✓ {result.get('message', 'Completed')}")
                        # Store output files for this node
                        if global_output_dir and result.get('output_files'):
                            node_output_files[node_id] = result['output_files']
                            log.append(f"   📤 Output files: {len(result['output_files'])} file(s)")

                elif node_type_id.startswith('tesseract_'):
                    result = _execute_tesseract_node(
                        node_input_files, params, dry_run, log, tesseract_bridge, global_output_dir
                    )
                    if not result.get('success', True):
                        if not continue_on_error:
                            log.append(f"   ❌ Failed: {result.get('error', 'Unknown error')}")
                            break
                        log.append(f"   ⚠️ Failed (continuing): {result.get('error', 'Unknown error')}")
                    else:
                        log.append(f"   ✓ {result.get('message', 'Completed')}")
                        # Store output files for this node
                        if global_output_dir and result.get('output_files'):
                            node_output_files[node_id] = result['output_files']
                            log.append(f"   📤 Output files: {len(result['output_files'])} file(s)")

                elif node_type_id.startswith('kraken_'):
                    result = _execute_kraken_node(
                        node_input_files, params, dry_run, log, global_output_dir
                    )
                    if not result.get('success', True):
                        if not continue_on_error:
                            log.append(f"   ❌ Failed: {result.get('error', 'Unknown error')}")
                            break
                        log.append(f"   ⚠️ Failed (continuing): {result.get('error', 'Unknown error')}")
                    else:
                        log.append(f"   ✓ {result.get('message', 'Completed')}")
                        # Store output files for this node
                        if global_output_dir and result.get('output_files'):
                            node_output_files[node_id] = result['output_files']
                            log.append(f"   📤 Output files: {len(result['output_files'])} file(s)")

                elif node_type_id.startswith('output_'):
                    result = _execute_output_node(
                        node_type_id, node_input_files, params, dry_run, log, export_bridge
                    )
                    if not result.get('success', True):
                        if not continue_on_error:
                            log.append(f"   ❌ Failed: {result.get('error', 'Unknown error')}")
                            break
                        log.append(f"   ⚠️ Failed (continuing): {result.get('error', 'Unknown error')}")
                    else:
                        log.append(f"   ✓ {result.get('message', 'Completed')}")
                        # For Save Output node, store the copied files as output
                        if node_type_id == 'output_save' and copied_files_for_next_node:
                            node_output_files[node_id] = copied_files_for_next_node
                            log.append(f"   📤 Output files (from Save Output): {len(copied_files_for_next_node)} file(s)")

                elif node_type_id.startswith('input_'):
                    log.append(f"   ✓ Input node (files already collected)")

                else:
                    log.append(f"   ⚠️ Unknown node type: {node_type_id}")

            except Exception as e:
                import traceback
                log.append(f"   ❌ Exception: {str(e)}")
                if not continue_on_error:
                    log.append(f"   Traceback: {traceback.format_exc()}")
                    break
                log.append(f"   Continuing after error...")

            log.append("")

    log.append("=" * 60)
    log.append("EXECUTION COMPLETE")
    log.append("")

    st.session_state.flow_execution_log = "\n".join(log)
    if dry_run:
        st.info("Dry run completed - no files were modified.")
    else:
        st.success("Workflow execution completed!")


def _execute_modification_node(node_type_id: str, files: list, params: dict,
                                dry_run: bool, log: list, bridge, global_output_dir: str = None) -> dict:
    """Execute a modification node."""
    from pathlib import Path

    # Map node type IDs to bridge methods
    method_map = {
        'mod_remove_empty': 'remove_empty',
        'mod_translate_lines': 'translate_lines',
        'mod_extend_lines': 'extend_lines',
        'mod_rectangularize': 'rectangularize',
        'mod_reduce_points': 'reduce_polygon_points',
        'mod_simplify_polygon': 'simplify_polygon',
        'mod_merge_regions': 'merge_overlapping_textregions',
        'mod_merge_column_aligned': 'merge_columnaligned_regions',
        'mod_sort_regions': 'sort_regions',
        'mod_sort': 'sort',
        'mod_sort_and_merge': 'sort_and_merge',
        'mod_replace_tags': 'replace_tag',
        'mod_remove_tags': 'remove_tag',
        'mod_delete_text': 'delete_text',
        'mod_delete_textlines': 'delete_textlines',
        'mod_repair': 'repair',
        'mod_repair_dummy': 'repair_dummy_region',
        'mod_fit_into_parent': 'fit_into_parent',
        'mod_top_tier_region': 'top_tier_textregion',
        'mod_split_big_regions': 'split_big_regions_vertical',
        # New Format & Metadata nodes
        'mod_set_page_version': 'set_page_version',
        'mod_set_metadata': 'set_metadata',
        'mod_reassign_ids': 'reassign_ids',
        # New Text-Layout nodes
        'mod_pseudoline_polygon': 'pseudolinepolygon',
        'mod_recalculate_polygon': 'recalculate_textregion_polygon',
        'mod_match_textlines': 'match_textlines_to_region',
    }

    method_name = method_map.get(node_type_id)
    if not method_name:
        return {'success': False, 'error': f'Unknown modification node: {node_type_id}'}

    # Get the method from the bridge
    method = getattr(bridge, method_name, None)
    if not method:
        return {'success': False, 'error': f'Method not found: {method_name}'}

    # Build kwargs for the method
    kwargs = {'files': [str(f) for f in files]}

    # Add output directory if provided globally (from Save Output node)
    # and the method supports it
    if global_output_dir and _method_supports_outputdir(method_name):
        kwargs['outputdir'] = global_output_dir
        log.append(f"   - outputdir: {global_output_dir} (from Save Output node)")

    # Map parameters based on method
    if node_type_id == 'mod_remove_empty':
        kwargs['level'] = params.get('levels', ['TextRegion', 'Textline'])
        kwargs['dry_run'] = params.get('dry_run', dry_run)
        if not dry_run:
            kwargs['dry_run'] = False

    elif node_type_id == 'mod_translate_lines':
        kwargs['xoff'] = params.get('xoff', 0)
        kwargs['yoff'] = params.get('yoff', 0)
        kwargs['dry_run'] = params.get('dry_run', dry_run)

    elif node_type_id == 'mod_extend_lines':
        kwargs['distance'] = params.get('distance', 8)
        kwargs['dim'] = params.get('dim', 'all')
        kwargs['rectangularize'] = params.get('rectangularize', False)
        kwargs['cut_overlaps'] = params.get('cut_overlaps', False)
        kwargs['dry_run'] = params.get('dry_run', dry_run)

    elif node_type_id in ['mod_rectangularize', 'mod_fit_into_parent']:
        kwargs['level'] = params.get('levels', ['TextRegion', 'Textline'])
        kwargs['dry_run'] = params.get('dry_run', dry_run)

    elif node_type_id in ['mod_reduce_points', 'mod_simplify_polygon']:
        kwargs['level'] = params.get('levels', ['TextRegion', 'Textline'])
        kwargs['tolerance'] = params.get('tolerance', 2)

    elif node_type_id == 'mod_replace_tags':
        # old_tags can be a list or None (empty list means scan all tags)
        old_tags = params.get('old_tags', [])
        # If empty list or None, the bridge will handle scanning all tags
        if old_tags:
            # Use first tag for old_tag (bridge handles single tag)
            kwargs['old_tag'] = old_tags[0] if len(old_tags) == 1 else None
        else:
            kwargs['old_tag'] = None
        kwargs['new_tag'] = params.get('new_tag', '')
        kwargs['level'] = params.get('levels', ['TextRegion', 'Textline'])
        text_filter = params.get('text_filter', '')
        if text_filter:
            kwargs['textfilter'] = text_filter
            kwargs['skip_textfilter'] = params.get('skip_textfilter', False)

    elif node_type_id == 'mod_remove_tags':
        kwargs['tag'] = params.get('tag_to_remove', '')
        kwargs['level'] = params.get('levels', ['TextRegion', 'Textline'])
        kwargs['dry_run'] = params.get('dry_run', dry_run)

    elif node_type_id == 'mod_merge_regions':
        kwargs['min_overlap_percentage'] = params.get('min_overlap', 50.0)
        kwargs['recalculate_convex_hull'] = params.get('recalculate_hull', False)

    elif node_type_id == 'mod_merge_column_aligned':
        kwargs['based_on_baselines'] = params.get('based_on_baselines', False)
        kwargs['convex_hull_method'] = params.get('convex_hull_method', 'region')
        kwargs['max_height_distance'] = params.get('max_height_distance', 0.75)
        kwargs['mid_tolerance'] = params.get('mid_tolerance', 0.0)
        kwargs['tolerance'] = params.get('tolerance', 0.1)

    elif node_type_id == 'mod_sort_regions':
        kwargs['based_on_baselines'] = params.get('based_on_baselines', False)
        kwargs['overlap_pct'] = params.get('overlap_pct', 60.0)
        kwargs['dry_run'] = params.get('dry_run', dry_run)

    elif node_type_id == 'mod_sort':
        # No special parameters
        pass

    elif node_type_id == 'mod_sort_and_merge':
        kwargs['merge_lines_gap_x'] = params.get('merge_lines_gap_x', 64)
        kwargs['merge_lines_gap_y'] = params.get('merge_lines_gap_y', 10)

    elif node_type_id == 'mod_split_big_regions':
        kwargs['split_min_area'] = params.get('split_min_area', 4500000)
        kwargs['scale_min_area_by_maxlines'] = params.get('scale_min_area', 140)

    # New Format & Metadata nodes
    elif node_type_id == 'mod_set_page_version':
        kwargs['version'] = params.get('version', '2019-07-15')
        kwargs['validate'] = params.get('validate', True)
        kwargs['dry_run'] = params.get('dry_run', dry_run)

    elif node_type_id == 'mod_set_metadata':
        kwargs['creator'] = params.get('creator', 'PagePlus')
        kwargs['comments'] = params.get('comments', '')
        kwargs['default'] = params.get('default', False)
        kwargs['new'] = params.get('new_metadata', False)
        kwargs['dry_run'] = params.get('dry_run', dry_run)

    elif node_type_id == 'mod_reassign_ids':
        kwargs['reading_order_mode'] = params.get('reading_order_mode', 'auto')
        kwargs['dry_run'] = params.get('dry_run', dry_run)

    # New Text-Layout nodes
    elif node_type_id == 'mod_pseudoline_polygon':
        # No special parameters
        pass

    elif node_type_id == 'mod_recalculate_polygon':
        kwargs['rectangular'] = params.get('rectangular', False)
        kwargs['min_textlines'] = params.get('min_textlines', 0)

    elif node_type_id == 'mod_match_textlines':
        kwargs['slice_spanning'] = params.get('slice_spanning', False)
        kwargs['slice_min_overlap'] = params.get('slice_min_overlap', 0.1)

    # Call the method
    for key, value in list(kwargs.items()):
        if value is None or value == '' or (isinstance(value, list) and len(value) == 0):
            del kwargs[key]
        elif key != 'files' and key != 'outputdir':
            log.append(f"   - {key}: {value}")

    if dry_run:
        return {'success': True, 'message': f'Dry run - would process {len(files)} file(s)'}

    result = method(**kwargs)
    if result.get('success'):
        response = {'success': True, 'message': result.get('output', 'Completed')}
        # If output directory was used, find and return the output files
        if global_output_dir and _method_supports_outputdir(method_name):
            output_files = _get_output_files(files, global_output_dir)
            if output_files:
                response['output_files'] = output_files
        return response
    else:
        return {'success': False, 'error': result.get('output', 'Unknown error')}


def _get_output_files(input_files: list, output_dir: str) -> list:
    """Get the output files from the output directory based on input file names."""
    from pathlib import Path

    output_path = Path(output_dir)
    output_files = []

    for input_file in input_files:
        input_path = Path(input_file)
        # Output file has the same name as input file
        output_file = output_path / input_path.name
        if output_file.exists():
            output_files.append(output_file)

    return output_files


def _method_supports_outputdir(method_name: str) -> bool:
    """Check if a modification method supports outputdir parameter."""
    # Most modification methods support outputdir
    # Methods that don't: sorting, merging (some), repair (some)
    methods_without_outputdir = {
        'sort',
        'sort_and_merge',
        'sort_regions',
        'merge_overlapping_textregions',
        'merge_columnaligned_regions',
    }
    return method_name not in methods_without_outputdir


def _execute_gemini_node(node_type_id: str, files: list, params: dict,
                         dry_run: bool, log: list, global_output_dir: str = None) -> dict:
    """Execute a Gemini processing node."""
    from pageplus.gui.cli_bridges.gemini import GeminiBridge
    from pathlib import Path

    exec_mode = params.get('exec_mode', 'All-in-One')

    if dry_run:
        log.append(f"   - Execution Mode: {exec_mode}")
        if exec_mode == "All-in-One":
            stage = params.get('stage', '(Default)')
            log.append(f"   - Stage: {stage}")
        else:  # Pipeline
            pipeline = params.get('pipeline', '(None)')
            log.append(f"   - Pipeline: {pipeline}")

        # Log other params
        for key, value in params.items():
            if key not in ['exec_mode', 'stage', 'pipeline'] and value:
                if isinstance(value, list) and value:
                    log.append(f"   - {key}: {', '.join(str(v) for v in value)}")
                elif not isinstance(value, list):
                    log.append(f"   - {key}: {value}")

        return {'success': True, 'message': f'Dry run - would process {len(files)} file(s) with Gemini ({exec_mode})'}

    # Create Gemini bridge instance
    gemini_bridge = GeminiBridge()

    # Log execution mode
    log.append(f"   - Execution Mode: {exec_mode}")

    try:
        if exec_mode == "All-in-One":
            # Execute using stage configuration
            stage_name = params.get('stage', '')

            if stage_name and stage_name != '(Default)':
                # Parse stage name to extract collection and stage name
                # Format: "Stage Name (Collection)"
                if '(' in stage_name and ')' in stage_name:
                    collection = stage_name.split('(')[-1].rstrip(')')
                    stage_display = stage_name.split('(')[0].strip()
                else:
                    # Try to find matching stage from available stages
                    from pageplus.gui.utils.pipeline_manager import PipelineManager
                    manager = PipelineManager()

                    category = "OCR" if "ocr" in node_type_id else "ReOCR"
                    all_stages = manager.get_stages_by_category(category)

                    # Find matching stage by display name
                    stage_config = None
                    collection = None
                    for stage in all_stages:
                        if stage.get('name') == stage_name:
                            stage_config = stage
                            # Find collection name - iterate through collections
                            for coll_name in manager.get_collection_names():
                                stages_in_coll = manager.get_stages_in_collection(coll_name)
                                if any(s.get('id') == stage.get('id') for s in stages_in_coll):
                                    collection = coll_name
                                    break
                            if collection:
                                break
                            break

                    if not stage_config:
                        return {'success': False, 'error': f'Stage not found: {stage_name}'}

                log.append(f"   - Stage: {stage_name} (from {collection})")

                # Execute the stage
                result = gemini_bridge.execute_stage(
                    stage_config=stage_config,
                    files=[str(f) for f in files],
                    outputdir=global_output_dir,
                    dry_run=dry_run,
                    overwrite=True
                )

                if result.get('success'):
                    return {'success': True, 'message': result.get('output', 'Stage completed successfully')}
                else:
                    return {'success': False, 'error': result.get('output', 'Stage execution failed')}
            else:
                # Use default OCR/ReOCR without stage configuration
                log.append(f"   - Using default {node_type_id} processing")

                # Map files to images for OCR, XMLs for ReOCR
                if node_type_id == "gemini_ocr":
                    # For OCR, we need image files
                    image_files = []
                    for f in files:
                        f_path = Path(f)
                        if f_path.suffix.lower() in ['.jpg', '.jpeg', '.png', '.tif', '.tiff', '.webp', '.bmp']:
                            image_files.append(f)
                        elif f_path.suffix.lower() == '.xml':
                            # XML file - try to find corresponding image
                            from pageplus.utils.fs import find_image
                            from pageplus.models.page import Page
                            try:
                                page = Page(f_path)
                                image_filename = page.imageFilename()
                                image_path = find_image(image_filename, f_path.parent)
                                if image_path:
                                    image_files.append(str(image_path))
                            except:
                                pass

                    if not image_files:
                        return {'success': False, 'error': 'No image files found for OCR'}

                    result = gemini_bridge.ocr_multithread(
                        files=image_files,
                        outputdir=global_output_dir,
                        dry_run=dry_run,
                        overwrite=True,
                        recognize_level=params.get('recognize_level', 'TextRegion'),
                        thinking_budget=params.get('thinking_budget', 0)
                    )
                else:  # gemini_reocr
                    # For ReOCR, we need XML files
                    xml_files = [str(f) for f in files if Path(f).suffix.lower() == '.xml']

                    if not xml_files:
                        return {'success': False, 'error': 'No XML files found for ReOCR'}

                    result = gemini_bridge.reocr_multithread(
                        xml_files=xml_files,
                        outputdir=global_output_dir,
                        dry_run=dry_run,
                        overwrite=True,
                        recognize_level=params.get('recognize_level', 'TextRegion'),
                        update_elements=params.get('update_elements', ['Text', 'Tags']),
                        thinking_budget=params.get('thinking_budget', 0)
                    )

                if result.get('success'):
                    return {'success': True, 'message': result.get('output', 'Processing completed successfully')}
                else:
                    return {'success': False, 'error': result.get('output', 'Processing failed')}

        else:  # Pipeline mode
            pipeline_name = params.get('pipeline', '')

            if not pipeline_name or pipeline_name == '(None)':
                return {'success': False, 'error': 'No pipeline selected'}

            log.append(f"   - Pipeline: {pipeline_name}")

            # Execute the pipeline
            result = gemini_bridge.run_pipeline(
                pipeline_name=pipeline_name,
                files=[str(f) for f in files],
                outputdir=global_output_dir,
                dry_run=dry_run,
                overwrite=True
            )

            if result.get('success'):
                return {'success': True, 'message': result.get('output', 'Pipeline completed successfully')}
            else:
                return {'success': False, 'error': result.get('output', 'Pipeline execution failed')}

    except Exception as e:
        import traceback
        return {'success': False, 'error': f'Exception: {str(e)}\n{traceback.format_exc()}'}


def _execute_tesseract_node(files: list, params: dict, dry_run: bool,
                            log: list, bridge, global_output_dir: str = None) -> dict:
    """Execute a Tesseract OCR node."""
    for key, value in params.items():
        if value:
            log.append(f"   - {key}: {value}")

    if dry_run:
        return {'success': True, 'message': f'Dry run - would process {len(files)} file(s) with Tesseract'}

    # TODO: Implement actual Tesseract integration
    return {'success': False, 'error': 'Tesseract integration not yet implemented'}


def _execute_kraken_node(files: list, params: dict, dry_run: bool,
                         log: list, global_output_dir: str = None) -> dict:
    """Execute a Kraken OCR node."""
    for key, value in params.items():
        if value:
            log.append(f"   - {key}: {value}")

    if dry_run:
        return {'success': True, 'message': f'Dry run - would process {len(files)} file(s) with Kraken'}

    # TODO: Implement actual Kraken integration
    return {'success': False, 'error': 'Kraken integration not yet implemented'}


def _execute_output_node(node_type_id: str, files: list, params: dict,
                         dry_run: bool, log: list, bridge) -> dict:
    """Execute an output node."""
    from pathlib import Path

    output_dir = params.get('output_dir', '')
    if output_dir:
        log.append(f"   - Output Directory: {output_dir}")

    if node_type_id == "output_save":
        if params.get('create_backup') and not dry_run:
            log.append(f"   - Backup: Will be created")
        if dry_run:
            return {'success': True, 'message': f'Dry run - would save {len(files)} file(s)', 'output_dir': output_dir}
        # Files are already in place from modification operations
        return {'success': True, 'message': f'Files saved ({len(files)} file(s))', 'output_dir': output_dir}

    elif node_type_id == "output_export":
        export_format = params.get('format', 'PAGE-XML')
        log.append(f"   - Format: {export_format}")

        if dry_run:
            return {'success': True, 'message': f'Dry run - would export to {export_format}', 'output_dir': output_dir}

        # Map export format to bridge method
        format_map = {
            'ALTO': 'export_alto',
            'PDF': 'export_pdf',
            'Text': 'export_fulltext',
            'PAGE-XML': None  # Already in PAGE-XML format
        }

        if export_format == 'PAGE-XML':
            return {'success': True, 'message': f'Files already in PAGE-XML format ({len(files)} file(s))', 'output_dir': output_dir}

        method_name = format_map.get(export_format)
        if not method_name:
            return {'success': False, 'error': f'Unknown export format: {export_format}'}

        method = getattr(bridge, method_name, None)
        if not method:
            return {'success': False, 'error': f'Export method not found: {method_name}'}

        output_path = Path(output_dir) if output_dir else None

        try:
            result = method(files=files, output_dir=output_path, open_folder=False)
            if result:
                return {'success': True, 'message': f'Exported to {export_format} ({len(result)} file(s))', 'output_dir': output_dir}
            else:
                return {'success': False, 'error': f'Export to {export_format} returned no results'}
        except Exception as e:
            return {'success': False, 'error': str(e)}

    elif node_type_id == "output_alto":
        if dry_run:
            return {'success': True, 'message': f'Dry run - would export to ALTO', 'output_dir': output_dir}

        output_path = Path(output_dir) if output_dir else None
        try:
            result = bridge.export_alto(files=files, output_dir=output_path)
            if result:
                return {'success': True, 'message': f'Exported to ALTO ({len(result)} file(s))', 'output_dir': output_dir}
            else:
                return {'success': False, 'error': 'ALTO export returned no results'}
        except Exception as e:
            return {'success': False, 'error': str(e)}

    elif node_type_id == "output_pdf":
        if dry_run:
            return {'success': True, 'message': f'Dry run - would export to PDF', 'output_dir': output_dir}

        output_path = Path(output_dir) if output_dir else None
        try:
            result = bridge.export_pdf(files=files, output_dir=output_path, open_folder=False)
            if result:
                return {'success': True, 'message': f'Exported to PDF ({len(result)} file(s))', 'output_dir': output_dir}
            else:
                return {'success': False, 'error': 'PDF export returned no results'}
        except Exception as e:
            return {'success': False, 'error': str(e)}

    elif node_type_id == "output_text":
        if dry_run:
            return {'success': True, 'message': f'Dry run - would export to Text', 'output_dir': output_dir}

        output_path = Path(output_dir) if output_dir else None
        try:
            result = bridge.export_fulltext(files=files, output_dir=output_path, open_folder=False)
            if result:
                return {'success': True, 'message': f'Exported to Text ({len(result)} file(s))', 'output_dir': output_dir}
            else:
                return {'success': False, 'error': 'Text export returned no results'}
        except Exception as e:
            return {'success': False, 'error': str(e)}

    return {'success': False, 'error': f'Unknown output node: {node_type_id}'}
