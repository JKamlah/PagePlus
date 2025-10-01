import streamlit as st
import pandas as pd
from pageplus.gui.cli_bridges.guidelines import GuidelinesBridge
from pageplus.gui.views.guideline_views.profile_editor import profile_editor_view
from pageplus.gui.views.guideline_views.unicode_finder import unicode_finder_view
from pathlib import Path
from pageplus.utils.guidelines.lib.unicodecache import get_name
from collections import Counter
from collections import defaultdict


def get_glyph_name(glyph):
    if not isinstance(glyph, str) or len(glyph) != 1:
        return "N/A"
    try:
        return get_name(glyph)
    except (TypeError, ValueError):
        return "N/A (control character or invalid)"


def get_nested_val(data, keys, default=0):
    for key in keys:
        if not isinstance(data, dict):
            return default
        data = data.get(key, {})
    return data if not isinstance(data, dict) else default


def _render_summary_metrics(summary_data):
    """Renders the summary statistics using st.metric."""
    if not summary_data:
        st.write("No summary statistics available.")
        return

    total_glyphs = get_nested_val(summary_data, ['sum'])
    spacing = get_nested_val(summary_data, ['Z', 'SPACE', 'Zs', 'sum'])
    digits = get_nested_val(summary_data, ['N', 'DIGIT', 'Nd', 'sum'])
    letters = get_nested_val(summary_data, ['L', 'LATIN', 'sum'])
    lowercase = get_nested_val(summary_data, ['L', 'LATIN', 'Ll', 'sum'])
    uppercase = get_nested_val(summary_data, ['L', 'LATIN', 'Lu', 'sum'])
    punctuation = get_nested_val(summary_data, ['P', 'sum'])

    c1, c2, c3, c4, c5, c6, c7 = st.columns(7)
    c1.metric("Total Glyphs", total_glyphs)
    c2.metric("Spacing Symbols", spacing)
    c3.metric("Digits", digits)
    c4.metric("Punctuation", punctuation)
    c5.metric("Letters (Total)", letters)
    c6.metric("Lowercase", lowercase)
    c7.metric("Uppercase", uppercase)


def render_evaluation_results(results):
    """Renders the evaluation results dictionary in an interactive way."""
    if not results:
        st.warning("No results to display.")
        return

    # Combined Results Section
    st.subheader("Combined Results")
    combined = results.get('combined', {})
    if combined:
        st.write("**Statistics Summary**")
        summary_data = combined.get('cat', {}).get('sum', {})
        _render_summary_metrics(summary_data)

        if 'guideline_violations_summary' in combined and combined['guideline_violations_summary']:
            st.error(f"Total Guideline Violations: {sum(combined['guideline_violations_summary'].values())}")
            st.write(combined['guideline_violations_summary'])

        with st.expander("Glyph Statistics", expanded=True):
            glyphs = combined.get('all', {}).get('glyph', {})
            if glyphs:
                df = pd.DataFrame(glyphs.items(), columns=['Glyph', 'Count']).sort_values(by='Count', ascending=False)
                df['Name'] = df['Glyph'].apply(get_glyph_name)
                st.dataframe(df)
            else:
                st.write("No glyph data.")
    else:
        st.write("No combined results available.")

    # Guideline Violations
    guideline_violations = combined.get('guideline_violations_summary', {})
    if guideline_violations:
        st.subheader("Guideline Violations")
        total_violations = sum(guideline_violations.values())
        st.error(f"Total Guideline Violations: {total_violations}")
        df = pd.DataFrame(guideline_violations.items(), columns=['Rule', 'Violations']).sort_values(by='Violations', ascending=False)
        st.dataframe(df)

    # Custom Category Results Section
    custom_categories_results = combined.get('usr', {})
    if custom_categories_results:
        st.subheader("Custom Category Results")
        for category, subcategories in custom_categories_results.items():
            with st.expander(f"Category: {category}"):
                for subcat, glyphs in subcategories.items():
                    st.write(f"**{subcat}**")
                    if glyphs:
                        df = pd.DataFrame(glyphs.items(), columns=['Glyph', 'Count']).sort_values(by='Count', ascending=False)
                        df['Name'] = df['Glyph'].apply(get_glyph_name)
                        st.dataframe(df)
                    else:
                        st.write("No glyphs found for this subcategory.")

    # Missing Unicode Results Section
    missing_unicode_results = combined.get('missing', {})
    if missing_unicode_results:
        st.subheader("Missing Unicode Results")
        for profile, conditions in missing_unicode_results.items():
            with st.expander(f"Profile: {profile}", expanded=True):
                for condition, missing_items in conditions.items():
                    if missing_items:
                        st.write(f"**Missing based on {condition}:**")
                        df_data = []
                        for item in missing_items:
                            if isinstance(item, int):
                                char = chr(item)
                                name = get_glyph_name(char)
                                df_data.append({'Glyph': char, 'Name': name})
                            else:
                                df_data.append({'Glyph': str(item), 'Name': "N/A"})

                        if df_data:
                            df = pd.DataFrame(df_data)
                            st.dataframe(df)
                    else:
                        st.success(f"No items missing for condition: {condition}")

    # Per-File Results Section
    st.subheader("Per-File Results")
    single_results = results.get('single', {})
    if single_results:
        for i, file_data in single_results.items():
            file_path = results.get('path_indexes', {}).get(i, f"File {i}")
            with st.expander(f"File: {Path(file_path).name}"):
                st.write("**Statistics Summary**")
                summary_data = file_data.get('cat', {}).get('sum', {})
                _render_summary_metrics(summary_data)

                # Per-file Guideline Violations
                file_violations = file_data.get('guideline_violations_summary', {})
                if file_violations:
                    st.subheader("Guideline Violations")
                    total_file_violations = sum(file_violations.values())
                    st.error(f"Total Violations in this file: {total_file_violations}")
                    df_violations = pd.DataFrame(file_violations.items(), columns=['Rule', 'Violations']).sort_values(by='Violations', ascending=False)
                    st.dataframe(df_violations)

                # Detailed Guideline Violations
                file_violation_details = file_data.get('guideline_violations_details', [])
                if file_violation_details:
                    with st.expander("Violation Details"):
                        for detail in file_violation_details:
                            st.markdown(f"**Line:** `{detail['line_id']}`")
                            st.markdown(f"**Rule:** `{detail['rule']}`")
                            st.markdown("**Content:**")
                            st.text(detail['content'])
                            if 'match' in detail:
                                st.markdown(f"**Match:** `{detail['match']}`")
                            if 'violation' in detail:
                                st.markdown(f"**Violation:** `{detail['violation']}`")
                            st.markdown("---")

                st.write("**Glyph Statistics**")
                glyphs = file_data.get('all', {}).get('glyph', {})
                if glyphs:
                    df = pd.DataFrame(glyphs.items(), columns=['Glyph', 'Count']).sort_values(by='Count', ascending=False)
                    df['Name'] = df['Glyph'].apply(get_glyph_name)
                    st.dataframe(df)
                else:
                    st.write("No glyph data for this file.")

                # Per-file custom categories and missing unicodes could be added here if needed
    else:
        st.write("No per-file results available.")


def render_mapping_results(mapping_data):
    """Renders the mapping results in an interactive way."""
    replacement_counts = mapping_data.get("replacement_counts", {})
    change_log = mapping_data.get("change_log", {})

    if not replacement_counts:
        st.info("No replacements were made.")
        return

    st.header("Mapping Results")

    # Overall Summary
    st.subheader("Summary of Replacements")
    total_rule_counts = Counter()
    for filename, rules in replacement_counts.items():
        for rule, line_counts in rules.items():
            total_rule_counts[rule] += sum(line_counts.values())

    for rule, count in total_rule_counts.items():
        st.metric(label=rule, value=f"{count} replacements")

    # Detailed view per file
    st.subheader("Detailed Changes")
    for filename, rules in replacement_counts.items():
        with st.expander(f"File: {filename}"):
            # Collect all changed lines in the file to group rules by line
            lines_in_file = defaultdict(list)
            for rule, line_counts in rules.items():
                for line_id, count in line_counts.items():
                    lines_in_file[line_id].append({"rule": rule, "count": count})

            for line_id, applied_rules in sorted(lines_in_file.items()):
                st.markdown(f"**Line: `{line_id}`**")

                st.markdown("Applied Rules:")
                for rule_info in applied_rules:
                    st.text(f"  - {rule_info['rule']} ({rule_info['count']} replacements)")

                # Find the corresponding change_log entry
                log_entry_key = next((key for key in change_log if key[0] == filename and key[1] == line_id), None)
                if log_entry_key and log_entry_key in change_log:
                    log_entry = change_log[log_entry_key]
                    st.markdown(f"Original: `{log_entry['original']}`")
                    st.markdown(f"New: `{log_entry['new']}`")
                st.markdown("---")


def show_guidelines():
    st.title("📄 Guidelines Tools")

    bridge = GuidelinesBridge()
    loaded_files = st.session_state.get("loaded_files", [])

    if not loaded_files:
        st.warning("No files loaded. Please load some files first in the 'Load Files' view.")
        return

    tab1, tab2, tab3, tab4 = st.tabs(["📝 Evaluate", "🔄 Mapping", "✍️ Profile Editor", "🔍 Unicode Finder"])

    with tab1:
        st.header("Evaluate Text")
        with st.form("evaluate_form"):
            files_to_process = st.multiselect(
                "Select files to evaluate",
                options=[f.name for f in loaded_files],
                default=[f.name for f in loaded_files]
            )
            guideline_profiles = bridge.get_guideline_profiles()
            selected_guideline = st.selectbox(
                "Select guideline profile",
                options=guideline_profiles
            )

            missing_unicode_profiles = bridge.get_missing_unicode_profiles()
            selected_missing_unicodes = st.multiselect(
                "Missing Unicode Profiles",
                options=missing_unicode_profiles
            )

            text_normalization = st.selectbox(
                "Text Normalization",
                options=["NFC", "NFKC", "NFD", "NFKD"],
                index=0
            )

            submitted = st.form_submit_button("Run Evaluation")

            if submitted and files_to_process:
                selected_files = [f for f in loaded_files if f.name in files_to_process]
                with st.spinner("Running evaluation..."):
                    result = bridge.run_evaluate(
                        inputs=selected_files,
                        guideline=selected_guideline,
                        missing_unicodes=selected_missing_unicodes,
                        custom_categories=None,
                        textnormalization=text_normalization,
                    )
                    render_evaluation_results(result)

    with tab2:
        st.header("Text Mapping")
        with st.form("mapping_form"):
            files_to_normalize = st.multiselect(
                "Select files to map",
                options=[f.name for f in loaded_files],
                default=[f.name for f in loaded_files]
            )
            # TODO: Add a way to dynamically get mapping profiles
            normalization_profiles = bridge.get_mapping_profiles()
            selected_normalization_guideline = st.selectbox(
                "Select mapping profile",
                options=normalization_profiles
            )
            dry_run = st.checkbox("Dry Run", value=True)

            text_mapping = st.selectbox(
                "Text Mapping",
                options=["NFC", "NFKC", "NFD", "NFKD"],
                index=0,
                key="mapping_text_mapping"
            )

            mapping_submitted = st.form_submit_button("Run Mapping")

            if mapping_submitted and files_to_normalize:
                selected_files_mapping = [f for f in loaded_files if f.name in files_to_normalize]
                with st.spinner("Running mapping..."):
                    result = bridge.run_mapping_text(
                        inputs=selected_files_mapping,
                        guideline=selected_normalization_guideline,
                        dry_run=dry_run,
                        textnormalization=text_mapping,
                    )
                    if not result.get("success", False):
                        st.error(result.get("output", ""))
                        return

                    st.success("Mapping finished successfully!")
                    render_mapping_results(result.get("output", {}))

    with tab3:
        profile_editor_view()
    with tab4:
        unicode_finder_view()
