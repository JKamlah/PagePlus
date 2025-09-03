# PagePlus

![Logo](./assets/PagePlus_Logo.png)

PagePlus is a Python-based tool for processing and analyzing PAGE XML files, which are commonly used in document layout analysis. This tool provides a variety of functions to modify and extract data from these files, providing an efficient way to handle text and region-based information in document images. It offers both a command-line interface (CLI) for batch processing and a graphical user interface (GUI) for interactive use.

## Features

PagePlus includes several commands to perform operations such as:

-   **Analytics**: Gathers detailed statistics about the contents of PAGE XML files, including counts of text regions, table regions, lines of text, words, and glyphs.
-   **Validation**: Ensures the integrity of text regions and lines in PAGE XML files, checking for and reporting any inconsistencies or errors.
-   **Modification**: A rich set of functions to repair, refactor, and modify PAGE XML files, including region manipulation, text line adjustments, and coordinate fixes.
-   **Export**: Extracts data from PAGE XML to various formats like plain text, PDF, ALTO XML, and delimiter-separated values (CSV/TSV).
-   **OCR Integration**: Tools for working with OCR engines like Kraken and Tesseract.
-   **LLM Integration / Gemnini**: Features leveraging large language models like Gemini for advanced document processing tasks.
-   **Workspace Management**: Utilities for managing project workspaces.

## Installation

To install PagePlus, you will need Python 3.11+ and [Poetry](https://python-poetry.org/) installed on your system. 

1.  Clone the repository or download the source code:
    ```sh
    git clone https://github.com/your-username/pageplus.git
    cd pageplus
    ```

2.  Install the required dependencies using Poetry (for --extras gui to enable the gui):
    ```sh
    poetry install 
    poetry install --extras gui
    ```

3.  Activate the virtual environment created by Poetry:
    ```sh
    poetry shell
    ```

## GUI Usage

PagePlus comes with a user-friendly graphical interface built with Streamlit.

### Starting the GUI

To start the GUI, run the following command from the root directory of the project:

```sh
streamlit run pageplus/gui/app.py
```

This will open the PagePlus GUI in your web browser, where you can interactively load, process, and analyze your PAGE XML files.

## CLI Usage

PagePlus can be executed from the command line for batch processing and scripting.

### General Syntax

The general syntax for using PagePlus CLI is:

```sh
pageplus [MODULE] [COMMAND] [ARGUMENTS] [OPTIONS]
```

Use the `--help` flag with any command to see all available options:

```sh
pageplus --help
pageplus modification --help
pageplus modification sort-regions --help
```

### Available Commands

Here is a list of available commands, grouped by module:

#### `analytics`
-   `statistics`: Gathers statistics about PAGE XML files.
-   `confidences`: Calculates and reports the mean confidence of pages.
-   `compare`: Compares a ground truth document with an OCR version.
-   `tags`: Analyzes and reports on the usage of tags within the XML files.

#### `dinglehopper`
-   Provides OCR evaluation metrics and comparison tools.

#### `escriptorium` / `transkribus`
-   Commands for interacting with transcription platforms.

#### `export`
-   `alto`: Converts PAGE XML to ALTO XML format.
-   `dsv`: Exports data to delimiter-separated value files (e.g., CSV).
-   `fulltext`: Extracts and saves the full text content.
-   `page-pdf`: Creates a PDF representation of the PAGE XML.
-   ... and more.

#### `gemini` / `litellm`
-   Integrations with large language models for advanced processing.

#### `ingest`
-   Commands for importing and processing various file formats.

#### `kraken` / `tesseract`
-   Commands for performing OCR with Kraken and Tesseract.

#### `mets`
-   Tools for working with METS files.

#### `modification`
-   `sort-regions`: Sorts regions based on reading order.
-   `repair`: Fixes common issues in PAGE XML files.
-   `extend-lines`: Extends text lines and baselines.
-   `reassign-ids`: Reassigns IDs to regions and text lines.
-   `delete-text`: Deletes text content at specified levels.
-   ... and many more modification functions.

#### `projects`
-   Commands for managing PagePlus projects.

#### `system`
-   System-related commands and utilities.

#### `validation`
-   `validate`: Validates the structure and content of PAGE XML files.

#### `workspace`
-   Commands for managing workspaces.

## Contributing

Contributions to PagePlus are welcome! If you find a bug or have a feature request, please open an issue on the project's GitHub repository.