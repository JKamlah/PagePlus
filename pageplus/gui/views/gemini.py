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
from pageplus.utils.fs import shuffle


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
    loaded_files = [str(files.absolute())
                    for files in st.session_state.loaded_files] if st.session_state.loaded_files else []
    # Initialize settings
    settings = Settings()

    # Operation tabs
    tab_names = ["⚙️ Settings", "🏗️ Pipeline Editor", "📁 I/O"]
    if 'modification_input' in st.session_state:
        tab_names.append("🔬 Process")
    tabs = st.tabs(tab_names)

    selected_files_for_ocr = []
    if 'modification_input' in st.session_state:
        selected_files_for_ocr = st.session_state.modification_input["files"]

    with tabs[0]:  # Settings
        st.subheader("Settings")

        # Current Settings Summary
        st.info(f"""
        **📋 Current Default Settings**

        🤖 **Model:** `{settings.get("GEMINI_MODEL", "Not set")}`  
        ⚡ **Service Tier:** `{settings.get("GEMINI_SERVICE_TIER", "auto")}` *(Flex Inference)*  
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

        # Service Tier (Flex Inference)
        with st.expander("⚡ Service Tier (Flex Inference)", expanded=False):
            st.markdown(
                "Configure Gemini API Service Tier for standard requests. "
                "[Learn more about Flex Inference](https://ai.google.dev/gemini-api/docs/flex-inference)"
            )
            stier_options = {
                "auto": "Auto / Standard (Default latency & availability)",
                "flex": "Flex (Flex Inference - Lower cost, flexible throughput/latency)",
                "priority": "Priority (Standard / High Priority processing)",
            }
            cur_stier = settings.get("GEMINI_SERVICE_TIER", "auto")
            if cur_stier not in stier_options:
                cur_stier = "auto"

            selected_stier = st.selectbox(
                "Service Tier Option",
                options=list(stier_options.keys()),
                index=list(stier_options.keys()).index(cur_stier),
                format_func=lambda k: stier_options[k],
                key="gemini_service_tier_select"
            )
            if st.button("Set Service Tier", key="set_service_tier_button"):
                settings.set("GEMINI_SERVICE_TIER", selected_stier)
                st.success(f"Gemini Service Tier set to: {selected_stier}")
                st.rerun()

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
            col1, col2, col3 = st.columns([2, 1, 1])
            with col1:
                st.subheader("Selected Files")
            
            with col2:
                if st.button("🔀 Shuffle", key="gemini_shuffle_files", use_container_width=True):
                    st.session_state.modification_input["files"] = shuffle(st.session_state.modification_input["files"])
                    st.rerun()
            
            with col3:
                if st.button("🔁 Sort", key="gemini_sort_files_btn", use_container_width=True):
                    st.session_state.modification_input["files"] = sorted(st.session_state.modification_input["files"], key=lambda x: Path(x).name)
                    st.rerun()

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

        if "🔬 Process" in tab_names:
            with tabs[tab_names.index("🔬 Process")]:  # Process Tab
                st.subheader("Processing")

                # Initialize pipeline manager
                pipeline_manager = PipelineManager()

                # Pipeline Configuration
                st.markdown("### ⚙️ Pipeline Configuration")

                config_mode = st.radio(
                    "Configuration Mode",
                    ["🎯 Quick Mode (Single Stage)", "⚙️ Pipeline Mode"],
                    key="process_config_mode",
                    horizontal=True
                )

                selected_stages = []
                process_type = "OCR"  # Default process type

                if config_mode == "🎯 Quick Mode (Single Stage)":
                    st.markdown("#### 🎯 Quick Mode Settings")
                    
                    # 1. Mode Selection (OCR vs ReOCR)
                    mode_options = ["OCR"]
                    if any(f.suffix == ".xml" for f in st.session_state.get('loaded_files', [])):
                        mode_options.append("ReOCR")
                    
                    operation_mode = st.radio(
                        "Operation Mode",
                        mode_options,
                        horizontal=True,
                        key="quick_mode_operation_mode"
                    )

                    # 2. Process Selection
                    # Use keys that match STAGE_TYPES in pipeline_editor.py
                    process_options = ["All-in-One", "Table Recognition", "Segmentation", "Field-Tagging"]
                    process_selection = st.selectbox(
                        "Select Process",
                        process_options,
                        key="quick_mode_process_selection"
                    )

                    # 3. Stage Selection
                    # Logic: 
                    # - Category = operation_mode (OCR or ReOCR)
                    # - Type = process_selection
                    
                    target_category = operation_mode
                    stages = pipeline_manager.get_stages_by_category(target_category)
                    
                    if process_selection == "All-in-One":
                         # Allow "Text Recognition" as strictly equivalent/legacy for ReOCR or just general text extraction
                         stages = [s for s in stages if s.get('type') in ["All-in-One", "Text Recognition"]]
                    else:
                         stages = [s for s in stages if s.get('type') == process_selection]

                    if not stages:
                        st.warning(f"⚠️ No stages found for Type '{process_selection}' in Category '{operation_mode}'. Please create one in the Pipeline Editor.")
                    else:
                        stage_options = {f"{s.get('name')} ({s.get('collection')})": s for s in stages}
                        selected_stage_name = st.selectbox(
                            f"Select {process_selection} Stage",
                            list(stage_options.keys()),
                            key=f"quick_mode_stage_select_{operation_mode}_{process_selection.replace(' ', '_')}"
                        )
                        selected_stages = [stage_options[selected_stage_name]] if selected_stage_name else []

                        if selected_stages:
                            with st.expander("📋 Stage Details", expanded=True):
                                stage = selected_stages[0]
                                st.write(f"**Type:** {stage.get('type')}")
                                st.write(f"**Collection:** {stage.get('collection')}")

                                # Recognize Level Logic
                                recognize_level_options = ["Page", "TextRegion", "Textline"]
                                default_index = 0
                                disabled = False
                                
                                if process_selection == "Table Recognition":
                                    if operation_mode == "OCR":
                                        recognize_level_options = ["Page"]
                                        default_index = 0
                                        disabled = True # Force Page
                                        st.info("ℹ️ Table Recognition in OCR mode requires 'Page' level.")
                                    elif operation_mode == "ReOCR":
                                        recognize_level_options = ["TableRegion"] 
                                        default_index = 0
                                        disabled = True
                                        st.info("ℹ️ Table Recognition in ReOCR mode requires 'TableRegion' level.")
                                
                                # General default if not Table Rec
                                elif operation_mode == "ReOCR" and not disabled:
                                    # Default to TextRegion for ReOCR usually?
                                    if "TextRegion" in recognize_level_options:
                                         default_index = recognize_level_options.index("TextRegion")

                                recognize_level = st.selectbox(
                                    "Recognize Level",
                                    options=recognize_level_options,
                                    index=default_index,
                                    disabled=disabled,
                                    key=f"quick_recognize_level_{operation_mode}_{process_selection.replace(' ', '_')}"
                                )
                                # Store for execution
                                st.session_state['selected_recognize_level'] = recognize_level

                                if operation_mode == "ReOCR":
                                    st.multiselect(
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
                                    key=f"quick_prompt_display_{operation_mode}_{process_selection.replace(' ', '_')}_{selected_stage_name}"
                                )
                else:  # Pipeline Mode
                    st.info("Pipeline mode selected. Currently only OCR pipelines are supported in this view.")
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
                            pipeline_stages_refs = pipeline_data.get('stages', [])
                            if pipeline_stages_refs:
                                st.write(f"**Pipeline: {len(pipeline_stages_refs)} stage(s)**")
                                for i, stage_ref in enumerate(pipeline_stages_refs):
                                    collection_name = stage_ref.get('collection')
                                    stage_id = stage_ref.get('stage_id')
                                    stage = pipeline_manager.get_stage_by_id(collection_name, stage_id)
                                    if stage:
                                        selected_stages.append({**stage, 'collection': collection_name, 'override_attributes': stage_ref.get('attributes', {}), 'override_filters': stage_ref.get('filters', {})})
                                        st.write(f"{i + 1}. {stage.get('name')} ({stage.get('type')})")

                with st.expander("Execution Settings", expanded=True):
                    jobs_multi = st.number_input("Number of Jobs", min_value=1, value=4, key="processing_jobs")
                    calls_per_minute_multi = st.number_input("Calls per Minute", min_value=1, value=150, key="processing_calls_per_minute")
                    dry_run_multi = st.checkbox("Dry run", key="processing_dry_run")
                    overwrite_multi = st.checkbox("Overwrite", key="processing_overwrite", value=True)
                    # Expose the PAGE-XML-aware task modes served by the unified OCR pipeline.
                    _task_mode_labels = {
                        "layout_only": "Layout only (regions + coords)",
                        "layout_and_text": "Layout + text (current default)",
                        "layout_correction": "Layout correction (refine coords)",
                        "text_only": "Text only (coords preserved)",
                        "text_correction": "Text correction (refine existing text)",
                    }
                    _default_mode = "text_correction" if operation_mode == "ReOCR" else "layout_and_text"
                    task_mode_multi = st.selectbox(
                        "Task Mode",
                        options=list(_task_mode_labels.keys()),
                        index=list(_task_mode_labels.keys()).index(_default_mode),
                        format_func=lambda k: _task_mode_labels[k],
                        key="processing_task_mode",
                    )

                    use_gemini_batch = st.checkbox(
                        "⚡ Run in Batch Mode (Non-blocking, background status monitoring)",
                        value=False,
                        key="gemini_batch_mode",
                        help="Submits Gemini task as a background batch job. Monitor progress and results in 📊 Batches tab."
                    )

                    if config_mode == "🎯 Quick Mode (Single Stage)":
                        # Use our new variables
                        current_mode = operation_mode
                        current_process = process_selection
                        recognize_level = st.session_state.get('selected_recognize_level', 'TextRegion')
                    else:
                         # Pipeline mode defaults
                         current_mode = "OCR" # Pipeline mode currently only OCR
                         current_process = "Pipeline"
                         recognize_level = "TextRegion" # Default might need adjustment for pipeline

                    update_elements = ["Text", "Tags"]  # Default
                    if current_mode == "ReOCR":
                        update_elements = st.session_state.get('reocr_quick_update_elements', ["Text", "Tags"])

                    terminal_container = st.empty()
                    terminal_text = terminal_container.text_area("Process Terminal", value="", height=200, disabled=True, key="terminal_output_display_initial_process")
                    
                    # Update button text to reflect what we are doing
                    run_label = f"Run {current_mode} ({current_process}){' [BATCH]' if use_gemini_batch else ''}"

                    if st.button(run_label, key=f"run_multithreaded_button"):
                        if not selected_stages:
                            st.error("No stages selected. Please configure pipeline/stage first.")
                        elif use_gemini_batch:
                            batch_bridge = st.session_state.bridges.get('batch')
                            input_files_batch = selected_files_for_ocr if current_mode == "OCR" else loaded_files
                            output_dir_batch = st.session_state.get("modification_dir") or None

                            formatted_tasks = []
                            for stg in selected_stages:
                                formatted_tasks.append({
                                    "step": stg.get("type", "All-in-One"),
                                    "task_mode": task_mode_multi,
                                    "task_level": recognize_level,
                                    "provider_id": "gemini",
                                    "model": settings.get("GEMINI_MODEL", "gemini-2.5-flash"),
                                    "preset_id": stg.get("id", "gemini-stage"),
                                })

                            b_res = batch_bridge.submit_batch(
                                name=f"Gemini {current_mode} ({current_process})",
                                provider="gemini",
                                model=settings.get("GEMINI_MODEL", "gemini-2.5-flash"),
                                tasks=formatted_tasks,
                                input_files=input_files_batch or [],
                                output_dir=output_dir_batch,
                                execution_mode="stepwise",
                                options={
                                    "jobs": int(jobs_multi),
                                    "calls_per_minute": int(calls_per_minute_multi),
                                    "overwrite": bool(overwrite_multi),
                                    "dry_run": bool(dry_run_multi),
                                },
                            )
                            if b_res.get("success"):
                                job = b_res.get("batch", {})
                                st.success(f"✅ Gemini Batch job `{job.get('batch_id')}` submitted successfully!")
                                st.info(f"Status: 🟡 `{job.get('status')}` — {job.get('status_message')}")
                                if st.button("📊 View Running Batches", key="gemini_goto_batches_confirm"):
                                    st.session_state.main_page_selection = "📊 Batches"
                                    st.rerun()
                            else:
                                st.error(b_res.get("output", "Failed to submit Gemini batch job."))
                        else:

                            first_stage = selected_stages[0]
                            system_prompt_selected = first_stage.get('system_prompt', '')
                            stage_attributes = {**first_stage.get('attributes', {}), **first_stage.get('override_attributes', {})}
                            thinking_budget_val = int(settings.get("THINKING_BUDGET", "0"))
                            thinking_budget = stage_attributes.get('thinking_budget', thinking_budget_val)

                            current_model_output = bridge.show_model().get('output', 'N/A')
                            terminal_container.text_area("Process Terminal", value=f"Starting {current_mode} process with {current_model_output}...", height=200, disabled=True, key="terminal_output_clear_process")

                            output_queue = queue.Queue()
                            output_buffer = StringIO()

                            with st.spinner(f"Running {current_mode}...", show_time=True):
                                result_container = {"result": None}

                                def run_process():
                                    old_stdout = sys.stdout
                                    sys.stdout = QueueOutput(output_queue, output_buffer)
                                    aggregated_usage = {"prompt_tokens": 0, "candidates_tokens": 0, "total_tokens": 0}
                                    overall_success = True
                                    main_output_message = ""

                                    try:
                                        if current_mode == "OCR":
                                            result_data = bridge.ocr_multithread(
                                                files=selected_files_for_ocr,
                                                outputdir=st.session_state.get('modification_dir'),
                                                jobs=jobs_multi,
                                                calls_per_minute=calls_per_minute_multi,
                                                dry_run=dry_run_multi,
                                                system_prompt=system_prompt_selected,
                                                overwrite=overwrite_multi,
                                                recognize_level=recognize_level,
                                                multi_stage=(config_mode != "🎯 Quick Mode (Single Stage)"),
                                                thinking_budget=thinking_budget,
                                                task_mode=task_mode_multi,
                                            )
                                        elif current_mode == "ReOCR":
                                            stage_filters = {**first_stage.get('filters', {}), **first_stage.get('override_filters', {})}
                                            update_elements_stage = stage_filters.get('update_elements', update_elements)
                                            result_data = bridge.reocr_multithread(
                                                xml_files=loaded_files,
                                                image_files=selected_files_for_ocr,
                                                image_folder=None,
                                                same_names=True,
                                                additional_checks=None,
                                                outputdir=st.session_state.get('modification_dir'),
                                                system_prompt=system_prompt_selected,
                                                update_page=True,
                                                recognize_level=recognize_level,
                                                update_elements=update_elements_stage,
                                                jobs=jobs_multi,
                                                calls_per_minute=calls_per_minute_multi,
                                                thinking_budget=thinking_budget,
                                                dry_run=dry_run_multi,
                                                overwrite=overwrite_multi,
                                                task_mode=task_mode_multi,
                                            )
                                        # Eliminated independent TableRecognition block essentially, 
                                        # as we are now treating it as OCR/ReOCR with a specific prompt
                                        # But if we really need to support the old single-thread standalone way 
                                        # (which had TableRecStage), we could check current_process logic.
                                        # However, user request implies unification or at least UI integration.
                                        # The Implementation Plan assumed using ocr_multithread.
                                        # If the prompt is passed to ocr_multithread, it acts as TableRec if the prompt is designed for it.
                                        pass

                                        if isinstance(result_data, dict) and "usage" in result_data:
                                            overall_success = result_data.get("success", True)
                                            main_output_message = result_data.get("output", "Multithreaded process completed.")
                                            usage_data_list = result_data.get('usage')
                                            if usage_data_list and isinstance(usage_data_list, list):
                                                def _usage_field(meta, name):
                                                    # Support both raw google-genai usage_metadata objects
                                                    # (attribute access) and the normalized dicts emitted
                                                    # by the unified OCR pipeline (OCRResult.usage).
                                                    if meta is None:
                                                        return 0
                                                    if isinstance(meta, dict):
                                                        return meta.get(name, 0) or 0
                                                    return getattr(meta, name, 0) or 0

                                                for usage_meta in usage_data_list:
                                                    aggregated_usage["prompt_tokens"] += _usage_field(usage_meta, "prompt_token_count")
                                                    aggregated_usage["candidates_tokens"] += _usage_field(usage_meta, "candidates_token_count")
                                                    aggregated_usage["total_tokens"] += _usage_field(usage_meta, "total_token_count")
                                        else:
                                            main_output_message = f"Multithreaded {process_type} process returned an unexpected data type."
                                            overall_success = False

                                    except Exception as e:
                                        main_output_message = f"Error during {current_mode} ({current_process}) processing: {str(e)}"
                                        print(main_output_message)
                                        overall_success = False
                                    finally:
                                        sys.stdout.flush()
                                        sys.stdout = old_stdout
                                        result_container["result"] = {"success": overall_success, "output": main_output_message, "aggregated_usage": aggregated_usage}

                                process_thread = threading.Thread(target=run_process)
                                process_thread.start()

                                while process_thread.is_alive():
                                    update_terminal_display(output_queue, output_buffer, terminal_container)
                                    time.sleep(0.1)

                                process_thread.join()
                                result = result_container["result"]

                                process_result(result, output_buffer, terminal_container, "", settings, process_type=process_type)

                            download_button_key = f"download_{process_type.lower()}_output"
                            st.download_button(
                                label="Download Terminal Output",
                                data=output_buffer.getvalue(),
                                file_name=f"{process_type.lower()}_terminal_output.txt",
                                mime="text/plain",
                                key=download_button_key
                            )
