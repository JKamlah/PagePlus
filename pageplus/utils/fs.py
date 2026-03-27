from __future__ import annotations

import os
import random
import subprocess
import sys
import uuid
from pathlib import Path
from typing import Any, Iterator, List, Tuple

import lxml.etree as ET
import typer
from dotenv import dotenv_values, get_key, load_dotenv

from pageplus.utils.constants import Environments, PagePlus
from pageplus.utils.envs import str_to_env, get_env_path
from pageplus.utils.exceptions import InputsDoNotExistException
from pageplus.utils.workspace import Workspace
from rich.progress import track
from lxml import etree

ws = Workspace()


def open_folder_default() -> bool:
    """Set the directory where all workspaces by all environments get stored"""
    dotfile = get_env_path()
    return get_key(
        dotfile,
        PagePlus.SYSTEM.as_prefix() +
        'OPEN_FOLDER') == 'True'


def open_folder(fpath: Path | str):
    """
    Opens an existing folder on every os
    Args:
        fpath:

    Returns:

    """
    fpath = fpath if isinstance(fpath, str) else str(fpath.absolute())
    if fpath == '' or fpath is None or not os.path.isdir(fpath):
        print(f"{fpath} can't be opened!")
        return
    if sys.platform == "win32":
        # Windows
        os.startfile(fpath)
    elif sys.platform == "darwin":
        # macOS
        subprocess.run(["open", fpath])
    else:
        # Linux and other Unix-like OS
        subprocess.run(["xdg-open", fpath])
    fpath = Path(fpath)
    print(f"Opened [bold green]{fpath.name}[/bold green]: {fpath.absolute()}")


def join_modified_path(path: Path, count: int) -> Path:
    """
    Appends a modified path segment to a given path a specified number of times.

    This function retrieves a modified path segment from environment variables,
    specified by the 'MODIFIED' key prefixed by the current environment's prefix.
    It then appends this segment to the provided path for the specified count.

    Args:
        path (Path): The initial path to which the modified segment will be appended.
        count (int): The number of times the modified segment should be appended.

    Returns:
        Path: The updated path with the modified segment appended 'count' times.
    """
    mod_path = get_key(
        get_env_path(),
        Environments.PAGEPLUS.as_prefix() +
        'MODIFIED')
    for _ in range(0, count):
        path = path.joinpath(mod_path)
    return path


def transform_output(
        ctx: typer.Context,
        param: typer.CallbackParam,
        value: str):
    """
    Transforms the output value using the specified transformation inputs.

    This function applies a transformation to the given value if it is not None,
    using the `transform_inputs` function. The transformation context and parameters
    are specified by `ctx` and `param`.

    Args:
        ctx (typer.Context): The context in which the command is executed.
        param (typer.CallbackParam): The callback parameter associated with the command.
        value (str): The value to transform.

    Returns:
        The transformed value or None if the original value is None.
    """
    return transform_inputs(ctx, param, [value])[0] if value else None


def transform_input(
        ctx: typer.Context,
        param: typer.CallbackParam,
        value: str):
    """
    Transforms a single input value based on the given context and parameters.

    This is a convenience wrapper around `transform_inputs` for transforming a single value.

    Args:
        ctx (typer.Context): The context in which the command is executed.
        param (typer.CallbackParam): The callback parameter associated with the command.
        value (str): The value to transform.

    Returns:
        The transformed value.
    """
    return transform_inputs(
        ctx, param, [value] if value is not None else None)[0]


def transform_inputs(
        ctx: typer.Context,
        param: typer.CallbackParam,
        values: List[str]):
    """
    Transforms a list of input values based on the specified context and parameters.

    This function loads environment variables and determines the current environment.
    Based on the loaded environment, it applies a transformation to each input value
    in the list provided.

    Args:
        ctx (typer.Context): The context in which the command is executed.
        param (typer.CallbackParam): The callback parameter associated with the command.
        values (List[str]): The list of values to transform.

    Returns:
        A list of transformed values.
    """
    load_dotenv()
    envs = dotenv_values()
    loaded_env = Environments[envs.get(
        Environments.PAGEPLUS.as_prefix_environment(), 'PAGEPLUS')]
    ret_values = []
    if not values or (
            len(values) == 1 and ''.join(
            values[0].split(':modified')) == ''):
        ws_folder = Path(
            envs.get(
                envs.get(
                    loaded_env.as_prefix_loaded_workspace())))
        count = 0 if not values else len(values[0].split(':modified')) - 1
        ws_folder = join_modified_path(ws_folder, count)
        if ws_folder.exists():
            ret_values.append(ws_folder)
    elif not values or (len(values) == 1 and ':' in values[0]):
        ws_folder = Path(
            envs.get(
                envs.get(
                    loaded_env.as_prefix_loaded_workspace())))
        ws_folder = ws_folder.joinpath(values[0].split(':')[1])
        if ws_folder.exists():
            ret_values.append(ws_folder)
    else:
        for value in values:
            if Path(value).exists():
                ret_values.append(value)
                continue
            ws_name = str_to_env(value.split(':')[0])
            ws_folder = envs.get(
                ws_name,
                None) if envs.get(
                ws_name,
                None) else (
                envs.get(
                    loaded_env.as_prefix_workspace() +
                    ws_name,
                    None))
            if ws_folder:
                count = len(value.split(':modified')) - 1
                ws_folder = join_modified_path(Path(ws_folder), count)
                if ws_folder.exists():
                    ret_values.append(ws_folder)
    if not ret_values:
        raise InputsDoNotExistException(values)
    return ret_values


def transform_substitutions(
        ctx: typer.Context,
        param: typer.CallbackParam,
        values):
    """Transform substitutions into valid (pattern, replacement) tuples."""
    if values is None or not values:
        return []
    return [tuple(value.split("==>", 1)) for value in values if "==>" in value]


def find_image(imageFilename: str, imageFolder: Path):
    """
    Finds the image file in the specified folder.

    Args:
    - imageFilename: The filename of the image file to find.
    - imageFolder: The directory where the image file resides.

    Returns:
    - The full path to the image file if found, or None if not found.
    """
    image_path = imageFolder.joinpath(imageFilename)
    if image_path.is_file():
        return image_path
    return None


def collect_xml_files_by_mets(mets: Path) -> List[Path]:
    """
    Read METS and return the existing xml-files in correct order
    """
    from lxml import etree

    def get_namespace_alias(root, ns_uri):
        """
        Given the root element and a namespace URI, return the alias (prefix) used in the document.
        If no alias is found, return a default alias 'mets'.
        """
        for prefix, uri in root.nsmap.items():
            if uri == ns_uri:
                return prefix if prefix is not None else 'mets'
        return "mets"

    # Parse the METS XML file using lxml.
    tree = etree.parse(mets)
    root = tree.getroot()

    # Get the namespace URI of the root element.
    ns_uri = tree.xpath('namespace-uri(.)')
    # Determine the alias used for that namespace in the document.
    alias = get_namespace_alias(root, ns_uri)

    # Build the namespace mapping dictionary for XPath queries.
    ns = {alias: ns_uri, 'xlink': 'http://www.w3.org/1999/xlink'}

    struct_map = root.find(f".//{alias}:structMap", ns)
    if struct_map is None:
        raise ValueError("No structMap element found in the METS file.")

    xml_files = []

    # Iterate through all fptr elements in the structMap, preserving order.
    for fptr in struct_map.findall(f".//{alias}:fptr", ns):
        # Try to get the FILEID directly from fptr.
        file_id = fptr.get("FILEID")
        # If not present, look for an area element within fptr.
        if not file_id:
            area = fptr.find(f".//{alias}:area", ns)
            if area is not None:
                file_id = area.get("FILEID")
        if not file_id:
            continue

        # Find the corresponding <file> element in fileSec by matching the FILE
        # ID.
        file_elem = root.find(f".//{alias}:file[@ID='{file_id}']", ns)
        if file_elem is None:
            continue

        # Retrieve the FLocat element which holds the file reference.
        flocat = file_elem.find(f"{alias}:FLocat", ns)
        if flocat is None:
            continue

        # Extract the file path from the xlink:href attribute.
        href = flocat.get("{http://www.w3.org/1999/xlink}href")
        if href and href.lower().endswith('.xml') and mets.parent.joinpath(
                href.split('/')[-1]).is_file():
            xml_files.append(mets.parent.joinpath(href.split('/')[-1]))
    return xml_files


def collect_xml_files(inputpaths: Iterator[Path | str], exclude: Tuple[str, ...] = (
        'metadata.xml', 'mets.xml', 'METS.xml')) -> List[Path]:
    """
    Collects XML files from given input paths or environmental names pointing to an existing path,
    excluding specified filenames.

    Args:
    - inputpaths: An iterator of Path objects representing files, directories or environmental names
    pointing to an existing path to search.
    - exclude: A tuple of filenames to exclude from the search.

    Returns:
    - A sorted list of Path objects for the XML files found.
    """
    xml_files = []
    load_dotenv()
    envs = dotenv_values()
    loaded_env = Environments[envs.get(
        Environments.PAGEPLUS.as_prefix_environment(), 'PAGEPLUS')]
    empty = True
    for inputpath in inputpaths:
        empty = False
        if (inputpath.is_file() and inputpath.suffix ==
                '.xml' and inputpath.name.upper() == 'METS.XML'):
            xml_files = collect_xml_files_by_mets(inputpath)
            return xml_files
        elif (inputpath.is_file() and inputpath.suffix == '.xml' and inputpath.name not in exclude):
            if is_page_xml(inputpath):
                xml_files.append(inputpath)
            else:
                print(f"Debug: Skipped XML file (not PAGE XML): {inputpath.name}")
                continue
        elif inputpath.is_dir():
            xml_files.extend([xml_file for xml_file in inputpath.glob(
                '*.xml') if xml_file.name not in exclude and is_page_xml(xml_file)])
            continue
        else:
            ws_name = str_to_env(inputpath.name)
            ws_folder = envs.get(
                ws_name,
                None) if envs.get(
                ws_name,
                None) else (
                envs.get(
                    loaded_env.as_prefix_workspace() +
                    ws_name,
                    None))
            if ws_folder:
                xml_files.extend([xml_file for xml_file in Path(ws_folder).glob(
                    '*.xml') if xml_file.name not in exclude and is_page_xml(xml_file)])
    if empty:
        ws_folder = envs.get(loaded_env.as_prefix_loaded_workspace())
        if ws_folder and ws_folder in envs.keys():
            xml_files.extend([xml_file for xml_file in Path(envs.get(ws_folder)).glob(
                '*.xml') if xml_file.name not in exclude and is_page_xml(xml_file)])
    return sorted(xml_files)


def is_page_xml(file_path: Path) -> bool:
    """
    Check if file is a page xml file
    """
    print(f"Debug: Checking if {file_path.name} is PAGE XML")
    
    if not file_path.suffix.lower() == '.xml':
        print(f"Debug: {file_path.name} - Not an XML file")
        return False

    # Check if file exists and is not empty
    if not file_path.exists():
        print(f"Debug: {file_path.name} - File does not exist")
        return False
    
    if file_path.stat().st_size == 0:
        print(f"Warning: Empty XML file skipped: {file_path}")
        return False

    try:
        tree = ET.parse(file_path)
        root = tree.getroot()
        print(f"Debug: {file_path.name} - Root tag: {root.tag}")

        # Check for PAGE XML namespace or specific elements
        # Typical namespace URI for PAGE is something like: "http://schema.primaresearch.org/PAGE/gts/pagecontent/2013-07-15"
        # Adjust the namespace URI according to the version of PAGE XML you're
        # expecting
        page_namespace = "http://schema.primaresearch.org/PAGE/gts/pagecontent/"
        is_page = (root.tag.startswith(f"{{{page_namespace}") or root.tag.startswith("PcGts"))
        print(f"Debug: {file_path.name} - Is PAGE XML: {is_page}")
        return is_page

    except ET.ParseError as e:
        # Not an XML file, or XML is malformed
        print(f"Warning: Invalid XML file skipped: {file_path} - {e}")
        return False
    except Exception as e:
        # Any other error (permission, etc.)
        print(f"Warning: Error reading file {file_path}: {e}")
        return False


def is_page_version(file_path: Path) -> Any | None:
    """
    Return page xml version
    """
    if is_page_xml(file_path):
        tree = ET.parse(file_path)
        root = tree.getroot()
        return root.tag.rsplit('/', 1)[1]


def determine_output_path(xml_file, outputdir, filename):
    """
    Determines the output path for the repaired XML file.

    Args:
        xml_file: The original XML file.
        outputdir: The specified output directory.
        filename: The name of the XML file.

    Returns:
        The Path object for the output file.
    """
    load_dotenv()
    if outputdir is None:
        return xml_file.parent / \
            get_key(get_env_path(), Environments.PAGEPLUS.as_prefix() + 'MODIFIED') / filename
    else:
        return Path(outputdir) / filename


def get_prefixed_files_from_ws(prefix: str) -> List[Path]:
    files = []
    ws_path = ws.get_ws_path(
        ws.get_loaded_ws().replace(
            ws.prefix_ws, ''))
    if ws_path:
        for file in Path(ws_path).iterdir():
            if file.name.startswith(prefix):
                files.append(file)
    return files


def save_result_to_ws(result: str, filename: str, from_file: Path) -> Path:
    load_dotenv(dotenv_path=get_env_path())
    envs = dotenv_values(dotenv_path=get_env_path())

    current_ws = envs.get("PAGEPLUS_LOADED_WS", None)
    if not current_ws:
        raise ValueError("PAGEPLUS_LOADED_WS not set in environment.")

    output_dir = Path(get_key(get_env_path(), Environments.PAGEPLUS.as_prefix() + 'MODIFIED'))
    if not output_dir.exists():
        output_dir.mkdir(parents=True)

    output_path = output_dir / filename
    with open(output_path, 'w') as f:
        f.write(result)
    return output_path


def get_img_path_from_pagexml(page_path: Path) -> Path | None:
    """
    Returns the path to the image file referenced in a PAGE XML file.
    """
    load_dotenv(dotenv_path=get_env_path())
    envs = dotenv_values(dotenv_path=get_env_path())

    # Try to find the image in the current workspace first
    current_ws = envs.get("PAGEPLUS_LOADED_WS", None)
    if current_ws:
        ws_path = ws.get_ws_path(current_ws)
        if ws_path:
            for img_file in Path(ws_path).iterdir():
                if img_file.name == page_path.name:
                    return img_file
    return None


def get_project_from_pagexml(page_path: Path) -> str | None:
    load_dotenv(dotenv_path=get_env_path())

    tree = etree.parse(page_path)
    # Define the namespace map
    ns = {
        'page': "http://schema.primaresearch.org/PAGE/gts/pagecontent/2013-07-15",
        'xlink': "http://www.w3.org/1999/xlink"
    }

    # Find the project element
    project_elem = tree.find(".//page:project", ns)
    if project_elem is not None:
        return project_elem.text
    return None


def get_modified_pagexml_path(page_path: Path) -> Path | None:
    load_dotenv(dotenv_path=get_env_path())
    filename = Path(page_path).name

    try:
        return Path(get_key(get_env_path(), Environments.PAGEPLUS.as_prefix() + 'MODIFIED') / filename)
    except TypeError:
        return None


def apply_mapping_to_files(xml_files: List[Path], mapping_profile: str, textnormalization: str = "NFC") -> Tuple[List[Tuple[Path, Path]], Any]:
    """
    Applies a mapping profile to a list of XML files and returns temporary files with their original paths.
    """
    import tempfile
    import unicodedata
    import shutil
    from pageplus.models.page import Page
    from pageplus.utils.guidelines.lib.processhandler import Mappinghandler

    temp_dir = tempfile.TemporaryDirectory()
    temp_dir_path = Path(temp_dir.name)
    temp_files_with_originals = []

    handler = Mappinghandler(fnames=[str(p) for p in xml_files], guideline=mapping_profile, textnormalization=textnormalization)

    for xml_path in xml_files:
        page = Page(xml_path)
        is_modified = False
        for region in page.regions.textregions:
            for line in region.textlines:
                original_text = line.get_text()
                if not original_text:
                    continue

                unicode_normalized_text = unicodedata.normalize(textnormalization, original_text)

                guideline_normalized_text = handler.mapping_by_guideline(
                    unicode_normalized_text, line.get_id(), xml_path.name, mode='deterministic'
                )

                if original_text != guideline_normalized_text:
                    line.update_text(guideline_normalized_text)
                    is_modified = True

        temp_file_path = temp_dir_path / xml_path.name
        if is_modified:
            page.save_xml(temp_file_path)
        else:
            shutil.copy(xml_path, temp_file_path)
        temp_files_with_originals.append((temp_file_path, xml_path))

    return temp_files_with_originals, temp_dir


def shuffle(data: list) -> list:
    """
    Randomizes the order of the input list.

    Args:
        data: The list of items to shuffle.

    Returns:
        A new list with items in randomized order.
    """
    shuffled_data = data[:]
    random.shuffle(shuffled_data)
    return shuffled_data


def get_random_name(prefix: str = "anon_", length: int = 8) -> str:
    """
    Generates a random name for use as an anonymized display name.

    Args:
        prefix: Prefix for the random name.
        length: Length of the random suffix (using uuid character hex).

    Returns:
        A string like 'anon_a1b2c3d4'.
    """
    unique_id = uuid.uuid4().hex[:length]
    return f"{prefix}{unique_id}"
