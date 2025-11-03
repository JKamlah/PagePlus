import json
import queue
import re
import sys
import threading
import time
from io import StringIO
from pathlib import Path

import pandas as pd
import streamlit as st

from pageplus.gui.cli_bridges.gemini import GeminiBridge
from pageplus.gui.utils.output_transform import rich_table_to_dataframe
from pageplus.gui.utils.picker import pick_files, pick_directory
from pageplus.gui.utils.settings import Settings
from pageplus.gui.utils.pipeline_manager import PipelineManager
from pageplus.utils.constants import GUI_STORAGE_DIR
from pageplus.gui.views.load_files import get_loaded_workspace_dir
from pageplus.gui.views.gemini_views.pipeline_editor import pipeline_editor_view


def strip_ansi_codes(text_to_clean):
    """Strip ANSI color codes from text."""
    ansi_escape = re.compile(r'\x1B(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])')
    return ansi_escape.sub('', text_to_clean)


class QueueOutput:
    """Custom stdout that puts output in a queue and buffer."""

    def __init__(self, q, buf):
        self.queue = q
        self.buffer = buf
        self._current_line_buffer = StringIO()  # Buffer for the current line

    def write(self, text_to_write):
        # Write to the current line buffer
        self._current_line_buffer.write(text_to_write)
        # If there's a newline, flush the line to the main buffer and queue
        if '\n' in text_to_write:
            self.flush_line()

    def flush(self):
        # This flush is called by Python's print or explicitly.
        # Ensure any remaining content in _current_line_buffer is processed.
        self.flush_line()

    def flush_line(self):
        # Get the content of the current line, clean it, and reset the line
        # buffer
        line_content = self._current_line_buffer.getvalue()
        if line_content:  # Only process if there's something
            cleaned_text = strip_ansi_codes(line_content)
            # Append to the main persistent buffer
            self.buffer.write(cleaned_text)
            # Put the cleaned chunk onto the queue
            self.queue.put(cleaned_text)
            self._current_line_buffer = StringIO()  # Reset for the next line/chunk


def update_terminal_display(output_queue, output_buffer, terminal_container):
    """Update the terminal display with new output from the queue."""
    # Process all available messages in the queue for this update cycle
    updated_once_in_cycle = False
    while not output_queue.empty():
        try:
            # We don't strictly need the item from queue if buffer is source of truth
            # but getting it clears the queue, signaling an update was
            # processed.
            output_queue.get_nowait()
            updated_once_in_cycle = True
        except queue.Empty:
            break  # Should not happen if not output_queue.empty() but good practice

    # Only update the text_area if there was new output processed
    if updated_once_in_cycle:

        current_output_for_display = output_buffer.getvalue()
        if current_output_for_display.startswith("Last item processed:"):
            _, current_output_for_display = current_output_for_display.lsplit(
                '\n')
        if 'Progress state: ' in current_output_for_display:
            _, counter = current_output_for_display.rsplit(
                'Progress state: ', 1)
            if counter:
                current_output_for_display = "Last item processed: " + \
                    counter.split(' ', 1)[0] + "\n" + current_output_for_display

        # ANSI codes should have been stripped before adding to buffer
        key = f"terminal_output_progress_{time.time()}"
        terminal_container.text_area(
            "Process Terminal",
            value=current_output_for_display,
            height=300,  # Keep increased height
            disabled=True,
            key=key
        )


def calculate_token_costs(aggregated_usage_data, settings):
    """Calculate token costs and generate a cost report."""
    cost_report_lines = ["\n--- Token Usage & Cost ---"]

    if not aggregated_usage_data:
        cost_report_lines.append("Token usage data not available.")
        return "\n".join(cost_report_lines)

    prompt_tokens = aggregated_usage_data.get("prompt_tokens", 0)
    candidate_tokens = aggregated_usage_data.get("candidates_tokens", 0)
    total_tokens = aggregated_usage_data.get("total_tokens", 0)

    cost_report_lines.append(f"Total Prompt Tokens: {prompt_tokens}")
    cost_report_lines.append(f"Total Candidates Tokens: {candidate_tokens}")
    cost_report_lines.append(
        f"Overall Total Tokens (from API): {total_tokens}")

    input_token_cost_str = settings.get("INPUT_TOKEN_COSTS", "")
    output_token_cost_str = settings.get("OUTPUT_TOKEN_COSTS", "")

    input_cost_per_million = None
    output_cost_per_million = None
    costs_calculable = True

    if input_token_cost_str and input_token_cost_str.strip():
        try:
            input_cost_per_million = float(input_token_cost_str)
        except ValueError:
            cost_report_lines.append(
                "Input Token Cost: Invalid setting, cannot calculate.")
            costs_calculable = False
    else:
        cost_report_lines.append("Input Token Cost: Not set.")
        costs_calculable = False

    if output_token_cost_str and output_token_cost_str.strip():
        try:
            output_cost_per_million = float(output_token_cost_str)
        except ValueError:
            cost_report_lines.append(
                "Output Token Cost: Invalid setting, cannot calculate.")
            costs_calculable = False
    else:
        cost_report_lines.append("Output Token Cost: Not set.")
        costs_calculable = False

    if costs_calculable and input_cost_per_million is not None and output_cost_per_million is not None:
        prompt_cost = (prompt_tokens / 1_000_000) * input_cost_per_million
        candidate_cost = (candidate_tokens / 1_000_000) * \
            output_cost_per_million
        total_calculated_cost = prompt_cost + candidate_cost

        cost_report_lines.append(
            f"Estimated Cost for Prompt Tokens: ${prompt_cost:.6f}")
        cost_report_lines.append(
            f"Estimated Cost for Candidates Tokens: ${candidate_cost:.6f}")
        cost_report_lines.append(
            f"Estimated Combined Total Cost: ${total_calculated_cost:.6f}")
    elif costs_calculable:  # Should not happen if logic is correct, but as a fallback
        cost_report_lines.append(
            "One or both token costs are missing/invalid, detailed costs not calculated."
        )

    return "\n".join(cost_report_lines)


def process_result(
    result,
    output_buffer,
    terminal_container,
    terminal_text,
    settings,
    process_type="Process"
):
    """Process the result and update the terminal display."""
    final_key = f"terminal_output_final_{time.time()}"
    final_output_value = output_buffer.getvalue()  # Get all captured stdout

    cost_report_str = calculate_token_costs(
        result.get("aggregated_usage") if result else None,
        settings
    )

    if result and result.get("success"):
        final_message = (
            f"{final_output_value}\n" f"{process_type} completed successfully.\n{result.get('output', '')}" f"{cost_report_str}")
        terminal_text += terminal_container.text_area(
            "Process Terminal",
            value=final_message,
            height=300,  # Increased height for more info
            disabled=True,
            key=final_key
        )
        st.success(result.get('output', f'{process_type} completed.'))
    else:
        error_detail = (
            result.get('output', 'Unknown error.') if result
            else f'{process_type} failed without a specific message.'
        )
        final_message = (
            f"{final_output_value}\n{process_type} failed.\n{error_detail}"
            f"{cost_report_str}"
        )
        terminal_text += terminal_container.text_area(
            "Process Terminal",
            value=final_message,
            height=300,  # Increased height for more info
            disabled=True,
            key=final_key
        )
        st.error(error_detail)


def load_prompt_templates() -> dict:
    """Load prompt templates from storage."""
    storage_file = GUI_STORAGE_DIR / "gemini.json"
    if storage_file.exists():
        with open(storage_file, 'r') as f:
            user_templates = json.load(f)
    else:
        user_templates = {"OCR": {"system": {}, "user": {}}, "OCR Multistage": {"system": {}, "user": {}}, "ReOCR": {"system": {}, "user": {}}}
    storage_file = Path(__file__).parent.parent / "storage" / "gemini_pp_templates.json"
    if storage_file.exists():
        with open(storage_file, 'r') as f:
            user_templates.update(json.load(f))
    return user_templates


def save_prompt_templates(templates: dict) -> None:
    """Save prompt templates to storage."""
    storage_file = GUI_STORAGE_DIR / "gemini.json"
    storage_file.parent.mkdir(parents=True, exist_ok=True)
    with open(storage_file, 'w') as f:
        json.dump(templates, f, indent=4)


def show_gemini(bridge: "GeminiBridge") -> None:
    """Show Gemini view."""
    st.title("✨ Gemini")

    # Initialize session state variables
    if 'gemini_available_models' not in st.session_state:
        # Load models from gemini_models.json if it exists
        models_file = GUI_STORAGE_DIR / "gemini_models.json"
        if models_file.exists():
            try:
                with open(models_file, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    st.session_state.gemini_available_models = data.get('models', [])
            except (json.JSONDecodeError, IOError):
                st.session_state.gemini_available_models = []
        else:
            st.session_state.gemini_available_models = []
    if not st.session_state.loaded_files:
        st.warning("Please load files first.")
        return

    loaded_files = [str(files.absolute())
                    for files in st.session_state.loaded_files]
    # Initialize settings
    settings = Settings()

    # Operation tabs
    tab_names = ["⚙️ Settings", "🏗️ Pipeline Editor", "📁 I/O"]
    if 'modification_input' in st.session_state:
        tab_names.extend(["🔡 OCR", "🔄 ReOCR"])
    tabs = st.tabs(tab_names)

    with tabs[0]:  # Settings
        st.subheader("Settings")

        # Current Settings Summary
        st.info(f"""
        **📋 Current Default Settings**

        🤖 **Model:** `{settings.get("GEMINI_MODEL", "Not set")}`  
        💭 **Thinking Budget:** `{settings.get("THINKING_BUDGET", "0")} tokens`  
        💰 **Input Token Cost:** `${settings.get("INPUT_TOKEN_COSTS", "Not set")} per 1M`  
        💰 **Output Token Cost:** `${settings.get("OUTPUT_TOKEN_COSTS", "Not set")} per 1M`

        *These are the default settings used when "Use Default Model" is selected in stages.*
        """)

        st.markdown("---")

        # API Key
        with st.expander("API Key", expanded=False):
            api_key = st.text_input(
                "API Key",
                value=settings.get("GEMINI_API_KEY", ""),
                type="password"
            )
            if st.button("Set API Key", key="set_api_key_button"):
                with st.spinner("Setting API key...", show_time=True):
                    result = bridge.set_api_key(api_key)
                if result["success"]:
                    st.success(result["output"])
                else:
                    st.error(result["output"])

            if st.button("Check API Key", key="check_api_key_button"):
                with st.spinner("Checking API key...", show_time=True):
                    result = bridge.check_valid_key()
                if result["success"]:
                    st.success(result["output"])
                else:
                    st.error(result["output"])

        # Models
        with st.expander("Models", expanded=False):
            settings = Settings()
            current_model = settings.get("GEMINI_MODEL", "")
            available_models = st.session_state.gemini_available_models

            if current_model and current_model not in available_models:
                available_models.insert(0, current_model)

            model_index = 0
            if current_model in available_models:
                model_index = available_models.index(current_model)

            model = st.selectbox(
                "Model Name",
                options=available_models,
                index=model_index
            )
            if st.button(
                "Show Model Details",
                    key="show_model_details_button"):
                with st.spinner(f"Fetching details for model {model}...", show_time=True):
                    result = bridge.show_modeldetails(model)
                if result["success"]:
                    st.success(result["output"])
                    if "details" in result:
                        details_dict = result["details"]
                        df = pd.DataFrame({
                            'Attribute': list(details_dict.keys()),
                            'Value': [str(v) for v in details_dict.values()]
                        })
                        st.dataframe(df, width='stretch')
                else:
                    st.error(result["output"])

            if st.button("Update Model Selection", key="update_models_button"):
                with st.spinner("Fetching available models...", show_time=True):
                    result = bridge.show_models()
                if result["success"]:
                    df = rich_table_to_dataframe(result["models"])
                    if 'Model' in df.columns:
                        model_list = df['Model'].tolist()
                        st.session_state.gemini_available_models = model_list

                        # Save to gemini_models.json
                        models_file = GUI_STORAGE_DIR / "gemini_models.json"
                        models_file.parent.mkdir(parents=True, exist_ok=True)
                        with open(models_file, 'w', encoding='utf-8') as f:
                            json.dump({"models": model_list}, f, indent=2)

                        st.success(f"{result['output']} Models saved to {models_file.name}")
                    st.rerun()
                else:
                    st.error(result["output"])

            if st.button("Set Model", key="set_model_button"):
                settings.set("GEMINI_MODEL", model)
                with st.spinner(f"Setting model to {model}...", show_time=True):
                    result = bridge.set_model(model)
                if result["success"]:
                    st.success(result["output"])
                else:
                    st.error(result["output"])

        with st.expander("Token Settings", expanded=False):
            # Thinking Budget
            thinking_budget = st.number_input(
                "Thinking Budget (tokens)",
                min_value=0,
                value=int(settings.get("THINKING_BUDGET", "0")),
                help="Set to 0 to disable thinking. Higher values allow more detailed analysis."
            )
            if st.button(
                "Set Thinking Budget",
                    key="set_thinking_budget_button"):
                settings.set("THINKING_BUDGET", thinking_budget)
                st.success(f"Thinking budget set to: {thinking_budget} tokens")

            st.markdown("---")  # Separator

            # Input Token Cost
            input_token_cost_str = settings.get("INPUT_TOKEN_COSTS", "")
            new_input_token_cost_str = st.text_input(
                "Input Token Cost (per 1M tokens)",
                value=input_token_cost_str,
                placeholder="e.g., 0.5 (leave empty if not set)",
                key="gemini_input_token_cost_input"
            )
            if st.button(
                "Set Input Token Cost",
                    key="set_input_token_cost_button"):
                if not new_input_token_cost_str.strip():
                    settings.set("INPUT_TOKEN_COSTS", "")
                    st.success("Input token cost cleared (set to None).")
                else:
                    try:
                        float(new_input_token_cost_str)  # Validate
                        settings.set(
                            "INPUT_TOKEN_COSTS",
                            new_input_token_cost_str)
                        st.success(
                            f"Input token cost (per 1M tokens) set to: {new_input_token_cost_str}")
                    except ValueError:
                        st.error(
                            "Invalid input token cost. Please enter a number "
                            "(e.g., 0.5) or leave empty."
                        )

            st.markdown("---")  # Separator

            # Output Token Cost
            output_token_cost_str = settings.get("OUTPUT_TOKEN_COSTS", "")
            new_output_token_cost_str = st.text_input(
                "Output Token Cost (per 1M tokens)",
                value=output_token_cost_str,
                placeholder="e.g., 1.5 (leave empty if not set)",
                key="gemini_output_token_cost_input"
            )
            if st.button(
                "Set Output Token Cost",
                    key="set_output_token_cost_button"):
                if not new_output_token_cost_str.strip():
                    settings.set("OUTPUT_TOKEN_COSTS", "")
                    st.success("Output token cost cleared (set to None).")
                else:
                    try:
                        float(new_output_token_cost_str)  # Validate
                        settings.set(
                            "OUTPUT_TOKEN_COSTS",
                            new_output_token_cost_str)
                        st.success(
                            f"Output token cost (per 1M tokens) set to: {new_output_token_cost_str}")
                    except ValueError:
                        st.error(
                            "Invalid output token cost. Please enter a number "
                            "(e.g., 1.5) or leave empty."
                        )

    with tabs[1]:  # Pipeline Editor
        pipeline_editor_view()

    with tabs[2]:  # I/O
        # Input selection
        input_type = st.radio(
            "Select Input Type",
            ["Directory", "Files"],
            horizontal=True
        )
        selected_extensions = st.multiselect(
                "Image Extensions",
                options=['.jpg', '.jpeg', '.png', '.bmp', '.tiff', '.tif'],
                default=['.jpg', '.jpeg', '.png', '.tiff', '.tif']
            )
        if input_type == "Directory":
            st.write("Select Image Extensions to Search")

            if st.button(
                "Select Image Directory",
                    key="select_image_dir_button"):
                selected_dir = pick_directory(initial_dir=get_loaded_workspace_dir())

                if selected_dir:
                    if selected_extensions:
                        selected_files = [
                            str(f) for f in Path(selected_dir).glob('*')
                            if f.suffix.lower() in selected_extensions
                        ]
                        if not selected_files:
                            st.warning(
                                "No image files found in selected directory."
                            )
                        else:
                            st.session_state.modification_input = {
                                "type": "directory",
                                "path": selected_dir,
                                "files": selected_files,
                                "extensions": selected_extensions
                            }
                            st.success(
                                f"Found {len(selected_files)} image files."
                            )
                            st.rerun()
                    else:
                        st.warning(
                            "Please select at least one image extension."
                        )
        else:  # Files
            if st.button(
                "Select Image Files",
                    key="select_image_files_button"):

                file_types = [
                    ("Image Files", " ".join(f"*{ext}" for ext in selected_extensions)),
                    ("All files", "*")
                ]
                selected_paths = pick_files(
                    initial_dir=get_loaded_workspace_dir(),
                    filetypes=file_types
                )
                if selected_paths:
                    st.session_state.modification_input = {
                        "type": "files",
                        "files": selected_paths
                    }
                    st.success(f"Selected {len(selected_paths)} files.")
                    st.rerun()

        if 'modification_input' in st.session_state:
            # Display selected files in a dataframe
            st.subheader("Selected Files")
            if st.session_state.modification_input["type"] == "directory":
                # For directory input, show directory path and file count
                st.write(
                    f"Directory: {st.session_state.modification_input['path']}")
                st.write(
                    f"Extensions: {', '.join(st.session_state.modification_input['extensions'])}")
                st.write(
                    f"Total files: {len(st.session_state.modification_input['files'])}")

                # Create a dataframe with file information
                files_df = pd.DataFrame([
                    {
                        'Filename': Path(f).name,
                        'Extension': Path(f).suffix,
                        'Size (KB)': round(Path(f).stat().st_size / 1024, 2),
                        'Full Path': f
                    }
                    for f in st.session_state.modification_input['files']
                ])
                st.dataframe(files_df, width='stretch')
            else:
                # For file input, show list of selected files
                files_df = pd.DataFrame([
                    {
                        'Filename': Path(f).name,
                        'Extension': Path(f).suffix,
                        'Size (KB)': round(Path(f).stat().st_size / 1024, 2),
                        'Full Path': f
                    }
                    for f in st.session_state.modification_input['files']
                ])
                st.dataframe(files_df, width='stretch')

            selected_files_for_ocr = st.session_state.modification_input["files"]

            # Select output directory
            st.subheader("Output Directory")
            st.write(
                "Output directory: The default is to overwrite the input files "
                "(recommended with backup strategy).")
            if st.button(
                "Select Output Directory",
                    key="select_output_dir_button"):
                # picker_script_path = Path(__file__).parent.parent / "utils" / "picker.py"
                # command = [sys.executable, str(picker_script_path)]
                selected_paths = pick_files(
                    initial_dir=get_loaded_workspace_dir(),
                    filetypes=[("All files", "*")]
                )
                if selected_paths:
                    st.session_state.modification_dir = selected_paths[0]
                elif selected_paths is not None:
                    st.info("Directory selection cancelled.")

            if 'modification_dir' in st.session_state:
                st.text_input(
                    "Selected Output Directory",
                    value=st.session_state.modification_dir,
                    disabled=True,
                    label_visibility="visible"
                )
                if st.button(
                    "Clear Output Directory",
                        key="clear_output_dir_button"):
                    del st.session_state.modification_dir
                    st.rerun()

        if len(tab_names) > 3:  # Only show OCR tab if it exists
            with tabs[3]:  # OCR
                st.subheader("OCR")

                # Initialize pipeline manager
                pipeline_manager = PipelineManager()

                # Pipeline Configuration
                st.markdown("### ⚙️ Pipeline Configuration")

                config_mode = st.radio(
                    "Configuration Mode",
                    ["🎯 Quick Mode (Single Stage)", "⚙️ Pipeline Mode"],
                    key="ocr_config_mode",
                    horizontal=True
                )

                selected_stages = []

                if config_mode == "🎯 Quick Mode (Single Stage)":
                    # Quick mode: select a single All-in-One stage
                    ocr_stages = pipeline_manager.get_stages_by_category("OCR")
                    all_in_one_stages = [s for s in ocr_stages if s.get('type') == 'All-in-One']

                    if not all_in_one_stages:
                        st.warning("⚠️ No All-in-One OCR stages available. Please create one in the Pipeline Editor.")
                    else:
                        stage_options = {f"{s.get('name')} ({s.get('collection')})": s for s in all_in_one_stages}
                        selected_stage_name = st.selectbox(
                            "Select OCR Stage",
                            list(stage_options.keys()),
                            key="ocr_quick_stage_select"
                        )
                        selected_stages = [stage_options[selected_stage_name]] if selected_stage_name else []

                        # Show stage details
                        if selected_stages:
                            with st.expander("📋 Stage Details", expanded=True):
                                stage = selected_stages[0]
                                st.write(f"**Type:** {stage.get('type')}")
                                st.write(f"**Collection:** {stage.get('collection')}")

                                # Recognize Level selector
                                recognize_level_quick = st.selectbox(
                                    "Recognize Level",
                                    options=["Page", "TextRegion", "Textline"],
                                    index=0,  # Default to TextRegion
                                    key="ocr_quick_recognize_level"
                                )

                                st.text_area(
                                    "System Prompt",
                                    value=stage.get('system_prompt', ''),
                                    height=100,
                                    disabled=True,
                                    key="ocr_quick_prompt_display"
                                )
                else:
                    # Pipeline mode: select a pipeline
                    ocr_pipelines = pipeline_manager.get_pipelines_by_category("OCR")

                    if not ocr_pipelines:
                        st.warning("⚠️ No OCR pipelines available. Please create one in the Pipeline Editor.")
                    else:
                        selected_pipeline_name = st.selectbox(
                            "Select Pipeline",
                            ocr_pipelines,
                            key="ocr_pipeline_select"
                        )

                        if selected_pipeline_name:
                            pipeline_data = pipeline_manager.get_pipeline(selected_pipeline_name)
                            st.info(f"ℹ️ {pipeline_data.get('description', 'No description')}")

                            # Show pipeline stages
                            pipeline_stages = pipeline_data.get('stages', [])
                            if pipeline_stages:
                                st.write(f"**Pipeline: {len(pipeline_stages)} stage(s)**")
                                for i, stage_ref in enumerate(pipeline_stages):
                                    collection_name = stage_ref.get('collection')
                                    stage_id = stage_ref.get('stage_id')
                                    stage = pipeline_manager.get_stage_by_id(collection_name, stage_id)
                                    if stage:
                                        selected_stages.append({
                                            **stage,
                                            'collection': collection_name,
                                            'override_attributes': stage_ref.get('attributes', {}),
                                            'override_filters': stage_ref.get('filters', {})
                                        })
                                        st.write(f"{i+1}. {stage.get('name')} ({stage.get('type')})")

                # OCR-Multithread Settings
                with st.expander("Execution Settings", expanded=True):

                    jobs_multi = st.number_input(
                        "Number of Jobs",
                        min_value=1,
                        value=4,
                        key="ocring_jobs"
                    )
                    calls_per_minute_multi = st.number_input(
                        "Calls per Minute",
                        min_value=1,
                        value=150,
                        key="ocring_calls_per_minute"
                    )
                    dry_run_multi = st.checkbox(
                        "Dry run", key="ocring_dry_run")
                    overwrite_multi = st.checkbox(
                        "Overwrite", key="ocring_overwrite", value=True)

                    # Get recognize_level from Quick Mode or default
                    recognize_level = st.session_state.get('ocr_quick_recognize_level', 'TextRegion')

                    # Terminal display area
                    terminal_container = st.empty()
                    terminal_text = terminal_container.text_area(
                        "Process Terminal",
                        value="",
                        height=200,
                        disabled=True,
                        key="terminal_output_display_initial"
                    )

                    if st.button(
                        "Run multithreaded OCR",
                            key="run_multithreaded_ocr_button"):

                        if not selected_stages:
                            st.error("No stages selected. Please configure pipeline first.")
                        else:
                            # Use the first stage's prompt (for single stage or first stage in pipeline)
                            first_stage = selected_stages[0]
                            system_prompt_selected = first_stage.get('system_prompt', '')

                            # Merge default attributes with overrides
                            stage_attributes = {**first_stage.get('attributes', {}), **first_stage.get('override_attributes', {})}
                            thinking_budget = stage_attributes.get('thinking_budget', thinking_budget)

                            # Clear terminal
                            current_model_output = bridge.show_model().get('output', 'N/A')
                            terminal_text += terminal_container.text_area(
                                "Process Terminal",
                                value=f"Starting OCR process with {current_model_output}...",
                                height=200,
                                disabled=True,
                                key="terminal_output_clear"
                            )

                            # Create a queue for output
                            output_queue = queue.Queue()
                            # Create a buffer to store all output
                            output_buffer = StringIO()

                            with st.spinner("Running OCR...", show_time=True):

                                # Run OCR with real-time output capture
                                def run_ocr_process():
                                    old_stdout = sys.stdout
                                    sys.stdout = QueueOutput(
                                        output_queue, output_buffer)
                                    # Since usage data per file seems unavailable from ocr_multithread,
                                    # we'll focus on capturing the string outputs.
                                    aggregated_usage = {  # Initialize but expect it to remain empty
                                        "prompt_tokens": 0,
                                        "candidates_tokens": 0,
                                        "total_tokens": 0
                                    }
                                    overall_success = True  # Assume success unless an error is caught
                                    main_output_message = ""

                                    try:
                                        # Assuming bridge.ocr_multithread now returns a
                                        # list of strings
                                        st.write(f"Overwrite: {overwrite_multi}")
                                        # Note: multi_stage is False for now (pipeline mode not fully implemented yet)
                                        individual_results_messages = bridge.ocr_multithread(
                                            files=selected_files_for_ocr,
                                            outputdir=st.session_state.get('modification_dir'),
                                            jobs=jobs_multi,
                                            calls_per_minute=calls_per_minute_multi,
                                            dry_run=dry_run_multi,
                                            system_prompt=system_prompt_selected,
                                            overwrite=overwrite_multi,
                                            recognize_level=recognize_level,
                                            multi_stage=False,
                                            thinking_budget=thinking_budget
                                        )

                                        # The bridge.ocr_multithread might return a single dictionary for the whole
                                        # batch if it can provide a summary and global
                                        # usage.
                                        if isinstance(
                                                individual_results_messages,
                                                dict) and "usage" in individual_results_messages:
                                            overall_success = individual_results_messages.get(
                                                "success", True)
                                            main_output_message = individual_results_messages.get(
                                                "output", "Multithreaded process completed.")
                                            usage_data_list = individual_results_messages.get(
                                                'usage')
                                            if usage_data_list and isinstance(
                                                    usage_data_list, list):
                                                for usage_meta in usage_data_list:
                                                    if hasattr(
                                                            usage_meta, 'prompt_token_count'):
                                                        aggregated_usage["prompt_tokens"] += getattr(
                                                            usage_meta, 'prompt_token_count', 0)
                                                        aggregated_usage["candidates_tokens"] += getattr(
                                                            usage_meta, 'candidates_token_count', 0)
                                                        aggregated_usage["total_tokens"] += getattr(
                                                            usage_meta, 'total_token_count', 0)
                                                    elif isinstance(usage_meta, dict):
                                                        aggregated_usage["prompt_tokens"] += usage_meta.get(
                                                            'prompt_token_count', 0)
                                                        aggregated_usage["candidates_tokens"] += usage_meta.get(
                                                            'candidates_token_count', 0)
                                                        aggregated_usage["total_tokens"] += usage_meta.get(
                                                            'total_token_count', 0)
                                        elif isinstance(individual_results_messages, list):
                                            main_output_message = (f"Multithreaded OCR process initiated for " f"{len(selected_files_for_ocr)} files. Output below.")
                                        else:
                                            main_output_message = (
                                                "Multithreaded OCR process returned an unexpected data type."
                                            )
                                            overall_success = False

                                        # Ensure all pending stdout is flushed before
                                        # returning from the thread
                                        sys.stdout.flush()

                                        return {
                                            "success": overall_success,
                                            "output": main_output_message,
                                            "aggregated_usage": aggregated_usage
                                        }
                                    except Exception as e:
                                        error_msg = f"Error during OCR processing: {str(e)}"
                                        # This print should go to the redirected stdout
                                        # (QueueOutput)
                                        print(error_msg)
                                        sys.stdout.flush()  # Ensure error message is flushed
                                        return {
                                            "success": False,
                                            "output": error_msg,
                                            "aggregated_usage": aggregated_usage
                                        }
                                    finally:
                                        sys.stdout = old_stdout

                                result_container = {"result": None}

                                def run_ocr_and_store_result():
                                    result_container["result"] = run_ocr_process()

                                ocr_thread = threading.Thread(
                                    target=run_ocr_and_store_result)
                                ocr_thread.start()

                                while ocr_thread.is_alive():
                                    update_terminal_display(
                                        output_queue, output_buffer, terminal_container)
                                    time.sleep(0.1)

                                ocr_thread.join()
                                result = result_container["result"]

                                process_result(
                                    result,
                                    output_buffer,
                                    terminal_container,
                                    terminal_text,
                                    settings,
                                    process_type="OCR"
                                )

                            st.download_button(
                                label="Download Terminal Output",
                                data=terminal_text,
                                file_name="ocr_terminal_output.txt",
                                mime="text/plain")

        if len(tab_names) > 4:  # Only show ReOCR tab if it exists
            with tabs[4]:  # ReOCR
                st.subheader("ReOCR")

                # Initialize pipeline manager
                reocr_pipeline_manager = PipelineManager()

                # Pipeline Configuration
                st.markdown("### ⚙️ Pipeline Configuration")

                reocr_config_mode = st.radio(
                    "Configuration Mode",
                    ["🎯 Quick Mode (Single Stage)", "⚙️ Pipeline Mode"],
                    key="reocr_config_mode",
                    horizontal=True
                )

                reocr_selected_stages = []

                if reocr_config_mode == "🎯 Quick Mode (Single Stage)":
                    # Quick mode: select a single ReOCR stage
                    reocr_stages = reocr_pipeline_manager.get_stages_by_category("ReOCR")

                    if not reocr_stages:
                        st.warning("⚠️ No ReOCR stages available. Please create one in the Pipeline Editor.")
                    else:
                        reocr_stage_options = {f"{s.get('name')} ({s.get('collection')})": s for s in reocr_stages}
                        reocr_selected_stage_name = st.selectbox(
                            "Select ReOCR Stage",
                            list(reocr_stage_options.keys()),
                            key="reocr_quick_stage_select"
                        )
                        reocr_selected_stages = [reocr_stage_options[reocr_selected_stage_name]] if reocr_selected_stage_name else []

                        # Show stage details
                        if reocr_selected_stages:
                            with st.expander("📋 Stage Details", expanded=True):
                                stage = reocr_selected_stages[0]
                                st.write(f"**Type:** {stage.get('type')}")
                                st.write(f"**Collection:** {stage.get('collection')}")

                                # Recognize Level selector
                                recognize_level_quick_reocr = st.selectbox(
                                    "Recognize Level",
                                    options=["Page", "TextRegion", "Textline"],
                                    index=0,  # Default to TextRegion
                                    key="reocr_quick_recognize_level"
                                )

                                # Update Elements selector
                                update_elements_quick = st.multiselect(
                                    "Update Elements",
                                    options=["Text", "Tags"],
                                    default=stage.get('filters', {}).get('update_elements', ["Text", "Tags"]),
                                    key="reocr_quick_update_elements"
                                )

                                st.text_area(
                                    "System Prompt",
                                    value=stage.get('system_prompt', ''),
                                    height=100,
                                    disabled=True,
                                    key="reocr_quick_prompt_display"
                                )
                else:
                    # Pipeline mode: select a pipeline
                    reocr_pipelines = reocr_pipeline_manager.get_pipelines_by_category("ReOCR")

                    if not reocr_pipelines:
                        st.warning("⚠️ No ReOCR pipelines available. Please create one in the Pipeline Editor.")
                    else:
                        reocr_selected_pipeline_name = st.selectbox(
                            "Select Pipeline",
                            reocr_pipelines,
                            key="reocr_pipeline_select"
                        )

                        if reocr_selected_pipeline_name:
                            reocr_pipeline_data = reocr_pipeline_manager.get_pipeline(reocr_selected_pipeline_name)
                            st.info(f"ℹ️ {reocr_pipeline_data.get('description', 'No description')}")

                            # Show pipeline stages
                            reocr_pipeline_stages = reocr_pipeline_data.get('stages', [])
                            if reocr_pipeline_stages:
                                st.write(f"**Pipeline: {len(reocr_pipeline_stages)} stage(s)**")
                                for i, stage_ref in enumerate(reocr_pipeline_stages):
                                    collection_name = stage_ref.get('collection')
                                    stage_id = stage_ref.get('stage_id')
                                    stage = reocr_pipeline_manager.get_stage_by_id(collection_name, stage_id)
                                    if stage:
                                        reocr_selected_stages.append({
                                            **stage,
                                            'collection': collection_name,
                                            'override_attributes': stage_ref.get('attributes', {}),
                                            'override_filters': stage_ref.get('filters', {})
                                        })
                                        st.write(f"{i+1}. {stage.get('name')} ({stage.get('type')})")

                # ReOCR-Multithread Settings
                with st.expander("Execution Settings", expanded=True):

                    jobs_multi = st.number_input(
                        "Number of Jobs",
                        min_value=1,
                        value=4,
                        key="reocring_jobs"
                    )
                    calls_per_minute_multi = st.number_input(
                        "Calls per Minute",
                        min_value=1,
                        value=150,
                        key="reocring_calls_per_minute"
                    )
                    dry_run_multi = st.checkbox(
                        "Dry run", key="reocring_dry_run")
                    overwrite_multi = st.checkbox(
                        "Overwrite", key="reocring_overwrite", value=True)

                    # Get recognize_level and update_elements from Quick Mode or defaults
                    recognize_level = st.session_state.get('reocr_quick_recognize_level', 'TextRegion')
                    update_elements = st.session_state.get('reocr_quick_update_elements', ["Text", "Tags"])

                    # Additional checks
                    # additional_checks = st.multiselect(
                    #    "Additional Checks",
                    #    options=["type", "style", "region", "reading_order"],
                    #    default=["type", "style"],
                    #     key="reocr_additional_checks"
                    # )

                    # Terminal display area
                    terminal_container = st.empty()
                    terminal_text = terminal_container.text_area(
                        "Process Terminal",
                        value="",
                        height=200,
                        disabled=True,
                        key="reocr_terminal_output_display_initial"
                    )

                    if st.button(
                        "Run multithreaded ReOCR",
                            key="run_multithreaded_reocr_button"):

                        if not reocr_selected_stages:
                            st.error("No stages selected. Please configure pipeline first.")
                        else:
                            # Use the first stage's prompt (for single stage or first stage in pipeline)
                            first_stage = reocr_selected_stages[0]
                            system_prompt_multi_selected = first_stage.get('system_prompt', '')

                            # Merge default attributes/filters with overrides
                            stage_attributes = {**first_stage.get('attributes', {}), **first_stage.get('override_attributes', {})}
                            stage_filters = {**first_stage.get('filters', {}), **first_stage.get('override_filters', {})}

                            # Override thinking_budget and update_elements if specified
                            thinking_budget_reocr = stage_attributes.get('thinking_budget', thinking_budget)
                            update_elements_stage = stage_filters.get('update_elements', update_elements)

                            # Clear terminal
                            current_model_output = bridge.show_model().get('output', 'N/A')
                            terminal_text += terminal_container.text_area(
                                "Process Terminal",
                                value=f"Starting ReOCR process with {current_model_output}...",
                                height=200,
                                disabled=True,
                                key="reocr_terminal_output_clear"
                            )
                            with st.spinner("Running ReOCR...", show_time=True):
                                # Create a queue for output
                                output_queue = queue.Queue()
                                # Create a buffer to store all output
                                output_buffer = StringIO()

                                # Run ReOCR with real-time output capture
                                def run_reocr_process():
                                    old_stdout = sys.stdout
                                    sys.stdout = QueueOutput(
                                        output_queue, output_buffer)
                                    # Since usage data per file seems unavailable from reocr_multithread,
                                    # we'll focus on capturing the string outputs.
                                    aggregated_usage = {  # Initialize but expect it to remain empty
                                        "prompt_tokens": 0,
                                        "candidates_tokens": 0,
                                        "total_tokens": 0
                                    }
                                    overall_success = True  # Assume success unless an error is caught
                                    main_output_message = ""

                                    try:
                                        # Run reocr command
                                        result = bridge.reocr_multithread(
                                            xml_files=loaded_files,
                                            image_files=selected_files_for_ocr,
                                            image_folder=None,
                                            same_names=True,
                                            additional_checks=None,
                                            outputdir=st.session_state.get('modification_dir'),
                                            system_prompt=system_prompt_multi_selected,
                                            update_page=True,
                                            recognize_level=recognize_level,
                                            update_elements=update_elements_stage,
                                            jobs=jobs_multi,
                                            calls_per_minute=calls_per_minute_multi,
                                            thinking_budget=thinking_budget_reocr,
                                            dry_run=dry_run_multi,
                                            overwrite=overwrite_multi
                                        )

                                        # The bridge.reocr_multithread might return a single dictionary for the whole
                                        # batch if it can provide a summary and global
                                        # usage.
                                        if isinstance(
                                                result, dict) and "usage" in result:
                                            overall_success = result.get(
                                                "success", True)
                                            main_output_message = result.get(
                                                "output", "Multithreaded process completed."
                                            )
                                            usage_data_list = result.get('usage')
                                            if usage_data_list and isinstance(
                                                    usage_data_list, list):
                                                for usage_meta in usage_data_list:
                                                    if hasattr(
                                                            usage_meta, 'prompt_token_count'):
                                                        aggregated_usage["prompt_tokens"] += getattr(
                                                            usage_meta, 'prompt_token_count', 0)
                                                        aggregated_usage["candidates_tokens"] += getattr(
                                                            usage_meta, 'candidates_token_count', 0)
                                                        aggregated_usage["total_tokens"] += getattr(
                                                            usage_meta, 'total_token_count', 0)
                                                    elif isinstance(usage_meta, dict):
                                                        aggregated_usage["prompt_tokens"] += usage_meta.get(
                                                            'prompt_token_count', 0)
                                                        aggregated_usage["candidates_tokens"] += usage_meta.get(
                                                            'candidates_token_count', 0)
                                                        aggregated_usage["total_tokens"] += usage_meta.get(
                                                            'total_token_count', 0)
                                        else:
                                            main_output_message = (
                                                "Multithreaded ReOCR process returned an unexpected data type."
                                            )
                                            overall_success = False

                                        # Ensure all pending stdout is flushed before
                                        # returning from the thread
                                        sys.stdout.flush()

                                        return {
                                            "success": overall_success,
                                            "output": main_output_message,
                                            "aggregated_usage": aggregated_usage
                                        }
                                    except Exception as e:
                                        error_msg = f"Error during ReOCR processing: {str(e)}"
                                        # This print should go to the redirected stdout
                                        # (QueueOutput)
                                        print(error_msg)
                                        sys.stdout.flush()  # Ensure error message is flushed
                                        return {
                                            "success": False,
                                            "output": error_msg,
                                            "aggregated_usage": aggregated_usage
                                        }
                                    finally:
                                        sys.stdout = old_stdout

                                result_container = {"result": None}

                                def run_reocr_and_store_result():
                                    result_container["result"] = run_reocr_process()

                                reocr_thread = threading.Thread(
                                    target=run_reocr_and_store_result)
                                reocr_thread.start()

                                while reocr_thread.is_alive():
                                    update_terminal_display(
                                        output_queue, output_buffer, terminal_container)
                                    time.sleep(0.1)

                                reocr_thread.join()
                                result = result_container["result"]

                                process_result(
                                    result,
                                    output_buffer,
                                    terminal_container,
                                    terminal_text,
                                    settings,
                                    process_type="ReOCR"
                                )

                            st.download_button(
                                label="Download Terminal Output",
                                data=terminal_text,
                                file_name="reocr_terminal_output.txt",
                                mime="text/plain")
