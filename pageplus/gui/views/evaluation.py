import streamlit as st
import pandas as pd
from pageplus.gui.cli_bridges.dinglehopper import DinglehopperBridge
from pageplus.gui.components.help_button import help_button
from pageplus.gui.utils.picker import pick_directory, pick_files
from pageplus.utils.fs import collect_xml_files
from pathlib import Path
from typing import List, Tuple


def _get_matched_files(gt_path: List[Path], ocr_files: List[Path]) -> List[Tuple[Path, Path]]:
    """Finds matching files between GT and OCR lists."""
    if not gt_path or not ocr_files:
        st.warning("Please provide both GT and OCR paths.")
        return []

    gt_files = []
    if isinstance(gt_path, list):
        gt_files = gt_path
    elif Path(gt_path).is_dir():
        gt_files = collect_xml_files([Path(gt_path)])
    elif Path(gt_path).is_file():
        gt_files = [Path(gt_path)]

    if not gt_files:
        st.error("No valid GT files found.")
        return []

    ocr_files_dict = {f.name: f for f in ocr_files}

    matched_files = []
    for gt_file in gt_files:
        if gt_file.name in ocr_files_dict:
            matched_files.append((gt_file, ocr_files_dict[gt_file.name]))

    if not matched_files:
        st.warning("No files with matching names found between GT and OCR inputs.")
        return []
    return matched_files


def _get_color_for_rate(rate: float) -> str:
    """Returns a color based on the error rate."""
    rate_percent = rate * 100
    if rate_percent < 1.1:
        return "green"
    elif rate_percent < 5:
        return "yellow"
    elif rate_percent < 10:
        return "orange"
    else:
        return "red"


def _display_colored_metric(label: str, value: str, color: str):
    """Displays a metric with a specific color, mimicking st.metric."""
    st.markdown(f"""
    <div style="border: 1px solid rgba(250, 250, 250, 0.2); border-radius: 0.5rem; padding: 1rem; text-align: center;">
        <div style="font-size: 0.875rem; color: #FAFAFA; margin-bottom: 0.25rem;">{label}</div>
        <div style="font-size: 2.25rem; color: {color}; font-weight: 600;">{value}</div>
    </div>
    """, unsafe_allow_html=True)


def _display_metrics(metrics: dict):
    """Displays metrics in an interactive way."""
    st.subheader("Comparison Metrics")

    col1, col2 = st.columns(2)

    wer = metrics['error_rate']['global']['word']
    wer_color = _get_color_for_rate(wer)
    with col1:
        _display_colored_metric("Word Error Rate (WER)", f"{wer:.2%}", wer_color)

    cer = metrics['error_rate']['global']['character']
    cer_color = _get_color_for_rate(cer)
    with col2:
        _display_colored_metric("Character Error Rate (CER)", f"{cer:.2%}", cer_color)

    with st.expander("Counts"):
        st.dataframe(pd.DataFrame.from_dict(metrics['count'], orient='index', columns=['Count']))

    with st.expander("Error Counts"):
        st.dataframe(pd.DataFrame.from_dict(metrics['error_count'], orient='index', columns=['Count']))

    with st.expander("Error Rates"):
        st.dataframe(pd.DataFrame.from_dict(metrics['error_rate']['global'], orient='index', columns=['Rate']))
        if 'local' in metrics['error_rate'] and metrics['error_rate']['local']:
            st.write("Local Error Rates")
            st.dataframe(pd.DataFrame.from_dict(metrics['error_rate']['local'], orient='index', columns=['Rate']))

    with st.expander("Confusions"):
        if metrics['confusions']['word']:
            st.write("Word Confusions")
            st.dataframe(pd.DataFrame.from_dict(metrics['confusions']['word'], orient='index', columns=['Frequency']))
        if metrics['confusions']['character']:
            st.write("Character Confusions")
            st.dataframe(
                pd.DataFrame.from_dict(metrics['confusions']['character'], orient='index', columns=['Frequency']))


def show_evaluation():
    st.title("Evaluation")

    # Initialize session state variables
    if 'gt_path' not in st.session_state:
        st.session_state.gt_path = []
    if 'dinglehopper_options' not in st.session_state:
        st.session_state.dinglehopper_options = {
            "report_prefix": "report",
            "reports_folder": ".",
            "metrics": True,
            "differences": False,
            "textequiv_level": "line"
        }

    tab1, tab2, tab3 = st.tabs(["Data Selection", "Dinglehopper", "PagePlus"])

    with tab1:
        data_selection_tab()
    with tab2:
        dinglehopper_tab()
    with tab3:
        pageplus_tab()


def data_selection_tab():
    st.header("Data Selection")

    st.subheader("Ground Truth (GT) Selection")
    gt_path_selection_method = st.radio(
        "Select GT Path by:",
        ("Directory", "Files"),
        horizontal=True
    )

    if gt_path_selection_method == "Directory":
        if st.button("Select GT Directory"):
            selected_path = pick_directory()
            if selected_path:
                st.session_state.gt_path = collect_xml_files([Path(selected_path)])
    else:
        if st.button("Select GT Files"):
            selected_files = pick_files()
            if selected_files:
                st.session_state.gt_path = [Path(f) for f in selected_files]

    if st.session_state.gt_path:
        st.dataframe([{"File": f.name, "Path": str(f)} for f in st.session_state.gt_path], width='stretch')

    # OCR Path from session state
    st.subheader("OCR Selection")
    ocr_files = st.session_state.get("loaded_files", [])
    if ocr_files:
        st.write("Using loaded files as OCR input:")
        st.dataframe(
            [{"File": f.name, "Path": str(f)} for f in ocr_files],
            width='stretch'
        )
    else:
        st.warning("No OCR files loaded. Please load files on the '📂 Input' page.")


def dinglehopper_tab():
    st.header("Dinglehopper Comparison")
    bridge = DinglehopperBridge()
    if not bridge.is_installed():
        st.error("Dinglehopper is not installed. Please install it to continue.")
        if st.button("Install Dinglehopper"):
            with st.spinner("Installing Dinglehopper..."):
                result = bridge.install()
            if result["success"]:
                st.success("Dinglehopper installed successfully! Please restart the application.")
            else:
                st.error("Installation failed:")
                st.code(result["output"])
        return

    options = st.session_state.dinglehopper_options
    with st.expander("Dinglehopper Options", expanded=True):
        options["report_prefix"] = st.text_input("Report Prefix", options["report_prefix"])
        options["reports_folder"] = st.text_input("Reports Folder", options["reports_folder"])
        options["metrics"] = st.checkbox("Calculate Metrics", options["metrics"])
        options["differences"] = st.checkbox("Report Differences", options["differences"])
        options["textequiv_level"] = st.selectbox(
            "TextEquiv Level",
            ["region", "line", "word", "glyph"],
            index=["region", "line", "word", "glyph"].index(options["textequiv_level"])
        )

    help_button(
        """
        **Dinglehopper Comparison**
        This tool compares a Ground Truth (GT) document/directory with an OCR document/directory.
        - **Ground Truth (GT) Path**: Path to the ground truth file or directory.
        - **OCR Path**: Path to the OCR file or directory.
        - **Report Prefix**: Prefix for the generated report files.
        - **Reports Folder**: Directory where the reports will be saved.
        - **Calculate Metrics**: If checked, CER and WER will be calculated.
        - **Report Differences**: If checked, a detailed difference report will be generated.
        - **TextEquiv Level**: The PAGE XML TextEquiv level to use for text extraction.
        """
    )

    if st.button("Create Dinglehopper Reports"):
        gt_path = st.session_state.gt_path
        ocr_files = st.session_state.get("loaded_files", [])
        matched_files = _get_matched_files(gt_path, ocr_files)

        if matched_files:
            with st.spinner("Running Dinglehopper comparison on matched files..."):
                for gt_file, ocr_file in matched_files:
                    st.write(f"Comparing `{gt_file.name}`...")

                    reports_folder = options["reports_folder"]
                    if reports_folder == '.':
                        reports_folder = str(ocr_file.parent.joinpath('Dinglehopper', 'report'))
                    Path(reports_folder).mkdir(parents=True, exist_ok=True)

                    result = bridge.process(
                        gt=str(gt_file),
                        ocr=str(ocr_file),
                        report_prefix=f"{gt_file.stem}_{options['report_prefix']}",
                        reports_folder=reports_folder,
                        metrics=options["metrics"],
                        differences=options["differences"],
                        textequiv_level=options["textequiv_level"]
                    )
                    if not result["success"]:
                        st.error(f"An error occurred during comparison for {gt_file.name}:")
                        st.code(result["output"])
                    else:
                        st.info(f"Reports saved in: {reports_folder}")
                st.success("Dinglehopper reports created for all matched files!")


def pageplus_tab():
    st.header("PagePlus Comparison")
    bridge = DinglehopperBridge()

    if st.button("Create Interactive Reports (PagePlus-Edition)", help="Create interactive reports with PagePlus-Edition - This is based on LineIDs and not on Fulltext comparison!"):
        gt_path = st.session_state.gt_path
        ocr_files = st.session_state.get("loaded_files", [])
        matched_files = _get_matched_files(gt_path, ocr_files)

        if matched_files:
            results_data = []
            with st.spinner("Running PagePlus comparison on matched files..."):
                for gt_file, ocr_file in matched_files:
                    result = bridge.compare_metrics(
                        gt=str(gt_file),
                        ocr=str(ocr_file)
                    )
                    results_data.append({
                        "gt_file": gt_file,
                        "result": result
                    })

            successful_results = [res for res in results_data if res["result"]["success"]]
            if successful_results:
                st.subheader("Error Rate Overview")
                chart_data = {
                    "File": [res["gt_file"].name for res in successful_results],
                    "WER": [res["result"]["output"]["error_rate"]["global"]["word"] for res in successful_results],
                    "CER": [res["result"]["output"]["error_rate"]["global"]["character"] for res in successful_results]
                }
                df = pd.DataFrame(chart_data).set_index("File")
                st.bar_chart(df, stack=False, horizontal=True)

            for item in results_data:
                gt_file = item["gt_file"]
                result = item["result"]
                with st.expander(f"Comparison for {gt_file.name}", expanded=True):
                    if not result["success"]:
                        st.error(f"An error occurred during comparison for {gt_file.name}:")
                        st.code(result["output"])
                    else:
                        _display_metrics(result["output"])

            st.success("PagePlus comparison reports created for all matched files!")