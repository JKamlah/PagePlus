"""Shared Streamlit helpers for streaming a background process's stdout to a
text area and reporting token usage / cost.

These were originally defined inside :mod:`pageplus.gui.views.gemini`; they are
extracted here so the LLM-OCR view (and any future LLM view) can reuse them
without importing the heavy Gemini view module. The Gemini and LiteLLM views
keep their own copies for now.
"""
from __future__ import annotations

import queue
import re
import time
from io import StringIO

import streamlit as st


def strip_ansi_codes(text_to_clean: str) -> str:
    """Strip ANSI color codes from text."""
    ansi_escape = re.compile(r'\x1B(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])')
    return ansi_escape.sub('', text_to_clean)


_DATA_URI_RE = re.compile(r"(data:image/[A-Za-z0-9.+-]+;base64,)[A-Za-z0-9+/=\s]+")
_LONG_B64_RE = re.compile(r"[A-Za-z0-9+/]{200,}={0,2}")


def redact_base64(text: str) -> str:
    """Replace base64 image payloads so verbose logs don't flood the terminal."""
    if not text:
        return text
    text = _DATA_URI_RE.sub(lambda m: m.group(1) + "<base64 image omitted>", text)
    return _LONG_B64_RE.sub("<base64 omitted>", text)


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
            cleaned_text = redact_base64(strip_ansi_codes(line_content))
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
        key = f"llmocr_terminal_progress_{time.time()}"
        terminal_container.text_area(
            "Process Terminal",
            value=current_output_for_display,
            height=300,
            disabled=True,
            key=key,
        )


def calculate_token_costs(aggregated_usage_data, settings) -> str:
    """Calculate token costs and generate a cost report.

    Expects ``aggregated_usage_data`` normalized to
    ``{prompt_tokens, candidates_tokens, total_tokens}``.
    """
    lines = ["\n--- Token Usage & Cost ---"]
    if not aggregated_usage_data:
        lines.append("Token usage data not available.")
        return "\n".join(lines)

    prompt_tokens = aggregated_usage_data.get("prompt_tokens", 0)
    candidate_tokens = aggregated_usage_data.get("candidates_tokens", 0)
    total_tokens = aggregated_usage_data.get("total_tokens", 0)

    lines.append(f"Total Prompt Tokens: {prompt_tokens}")
    lines.append(f"Total Completion/Candidates Tokens: {candidate_tokens}")
    lines.append(f"Overall Total Tokens (from API): {total_tokens}")

    input_cost_str = settings.get("INPUT_TOKEN_COSTS", "")
    output_cost_str = settings.get("OUTPUT_TOKEN_COSTS", "")

    input_cost = None
    output_cost = None
    if input_cost_str and input_cost_str.strip():
        try:
            input_cost = float(input_cost_str)
        except ValueError:
            lines.append("Input Token Cost: Invalid setting, cannot calculate.")
    else:
        lines.append("Input Token Cost: Not set.")
    if output_cost_str and output_cost_str.strip():
        try:
            output_cost = float(output_cost_str)
        except ValueError:
            lines.append("Output Token Cost: Invalid setting, cannot calculate.")
    else:
        lines.append("Output Token Cost: Not set.")

    if input_cost is not None and output_cost is not None:
        prompt_cost = (prompt_tokens / 1_000_000) * input_cost
        candidate_cost = (candidate_tokens / 1_000_000) * output_cost
        lines.append(f"Estimated Cost for Prompt Tokens: ${prompt_cost:.6f}")
        lines.append(f"Estimated Cost for Completion Tokens: ${candidate_cost:.6f}")
        lines.append(f"Estimated Combined Total Cost: ${prompt_cost + candidate_cost:.6f}")

    return "\n".join(lines)


def process_result(result, output_buffer, terminal_container, terminal_text,
                   settings, process_type="Process") -> None:
    """Render the final terminal output + success/error toast."""
    final_key = f"llmocr_terminal_final_{time.time()}"
    final_output_value = output_buffer.getvalue()
    cost_report_str = calculate_token_costs(
        result.get("aggregated_usage") if result else None, settings,
    )

    if result and result.get("success"):
        final_message = (
            f"{final_output_value}\n{process_type} completed successfully.\n"
            f"{result.get('output', '')}{cost_report_str}"
        )
        terminal_container.text_area("Process Terminal", value=final_message,
                                     height=300, disabled=True, key=final_key)
        st.success(result.get('output', f'{process_type} completed.'))
    else:
        error_detail = (
            result.get('output', 'Unknown error.') if result
            else f'{process_type} failed without a specific message.'
        )
        final_message = (
            f"{final_output_value}\n{process_type} failed.\n{error_detail}{cost_report_str}"
        )
        terminal_container.text_area("Process Terminal", value=final_message,
                                     height=300, disabled=True, key=final_key)
        st.error(error_detail)
