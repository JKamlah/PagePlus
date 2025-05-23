from __future__ import annotations

import os
from pathlib import Path
from typing import Tuple, Iterator, List, Any
import sys
import subprocess

import lxml.etree as ET
import typer
from dotenv import load_dotenv, find_dotenv, get_key, dotenv_values

from pageplus.utils.constants import Environments, PagePlus
from pageplus.utils.exceptions import InputsDoNotExistException
from pageplus.utils.envs import str_to_env


def open_folder_default() -> bool:
    """Set the directory where all workspaces by all environments get stored"""
    dotfile = find_dotenv()
    return get_key(dotfile, PagePlus.SYSTEM.as_prefix()+'OPEN_FOLDER') == 'True'

def open_folder(fpath: Path|str):
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
    mod_path = get_key(find_dotenv(), Environments.PAGEPLUS.as_prefix()+'MODIFIED')
    for _ in range(0, count):
        path = path.joinpath(mod_path)
    return path

def transform_output(ctx: typer.Context, param: typer.CallbackParam, value: str):
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

def transform_input(ctx: typer.Context, param: typer.CallbackParam, value: str):
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
    return transform_inputs(ctx, param, [value] if value is not None else None)[0]


def transform_inputs(ctx: typer.Context, param: typer.CallbackParam, values: List[str]):
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
    loaded_env = Environments[envs.get(Environments.PAGEPLUS.as_prefix_environment(), 'PAGEPLUS')]
    ret_values = []
    if not values or (len(values) == 1 and ''.join(values[0].split(':modified')) == ''):
        ws_folder = Path(envs.get(envs.get(loaded_env.as_prefix_loaded_workspace())))
        count = 0 if not values else len(values[0].split(':modified'))-1
        ws_folder = join_modified_path(ws_folder, count)
        if ws_folder.exists():
            ret_values.append(ws_folder)
    elif not values or (len(values) == 1 and ':' in values[0]):
        ws_folder = Path(envs.get(envs.get(loaded_env.as_prefix_loaded_workspace())))
        ws_folder = ws_folder.joinpath(values[0].split(':')[1])
        if ws_folder.exists():
            ret_values.append(ws_folder)
    else:
        for value in values:
            if Path(value).exists():
                ret_values.append(value)
                continue
            ws_name = str_to_env(value.split(':')[0])
            ws_folder = envs.get(ws_name, None) if envs.get(ws_name, None) else (envs.get(loaded_env.as_prefix_workspace() + ws_name, None))
            if ws_folder:
                count = len(value.split(':modified'))-1
                ws_folder = join_modified_path(Path(ws_folder), count)
                if ws_folder.exists():
                    ret_values.append(ws_folder)
    if not ret_values:
        raise InputsDoNotExistException(values)
    return ret_values

def transform_substitutions(ctx: typer.Context, param: typer.CallbackParam, values):
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
        return Path(image_path.absolute())
    return None


def collect_xml_files_by_mets(mets:Path) -> List[Path]:
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

        # Find the corresponding <file> element in fileSec by matching the FILE ID.
        file_elem = root.find(f".//{alias}:file[@ID='{file_id}']", ns)
        if file_elem is None:
            continue

        # Retrieve the FLocat element which holds the file reference.
        flocat = file_elem.find(f"{alias}:FLocat", ns)
        if flocat is None:
            continue

        # Extract the file path from the xlink:href attribute.
        href = flocat.get("{http://www.w3.org/1999/xlink}href")
        if href and href.lower().endswith('.xml') and mets.parent.joinpath(href.split('/')[-1]).is_file():
            xml_files.append(mets.parent.joinpath(href.split('/')[-1]))
    return xml_files



def collect_xml_files(inputpaths: Iterator[Path|str],
                      exclude: Tuple[str, ...] = ('metadata.xml', 'mets.xml', 'METS.xml')) -> List[Path]:
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
    loaded_env = Environments[envs.get(Environments.PAGEPLUS.as_prefix_environment(), 'PAGEPLUS')]
    empty = True
    for inputpath in inputpaths:
        empty = False
        if (inputpath.is_file() and inputpath.suffix == '.xml' and inputpath.name.upper() == 'METS.XML'):
            xml_files = collect_xml_files_by_mets(inputpath)
            return xml_files
        elif (inputpath.is_file() and inputpath.suffix == '.xml' and inputpath.name not in exclude and
                is_page_xml(inputpath)):
            xml_files.append(inputpath)
        elif inputpath.is_dir():
            xml_files.extend([xml_file for xml_file in inputpath.glob('*.xml') if
                              xml_file.name not in exclude and is_page_xml(xml_file)])
        else:
            ws_name = str_to_env(inputpath.name)
            ws_folder = envs.get(ws_name, None) if envs.get(ws_name, None) else \
                (envs.get(loaded_env.as_prefix_workspace() + ws_name, None))
            if ws_folder:
                xml_files.extend([xml_file for xml_file in Path(ws_folder).glob('*.xml') if
                          xml_file.name not in exclude and is_page_xml(xml_file)])
    if empty:
        ws_folder = envs.get(loaded_env.as_prefix_loaded_workspace())
        if ws_folder and ws_folder in envs.keys():
            xml_files.extend([xml_file for xml_file in Path(envs.get(ws_folder)).glob('*.xml') if
                          xml_file.name not in exclude and is_page_xml(xml_file)])
    return sorted(xml_files)


def is_page_xml(file_path: Path) -> bool:
    """
    Check if file is a page xml file
    """
    if not file_path.suffix.lower() == '.xml':
        return False

    try:
        tree = ET.parse(file_path)
        root = tree.getroot()

        # Check for PAGE XML namespace or specific elements
        # Typical namespace URI for PAGE is something like: "http://schema.primaresearch.org/PAGE/gts/pagecontent/2013-07-15"
        # Adjust the namespace URI according to the version of PAGE XML you're expecting
        page_namespace = "http://schema.primaresearch.org/PAGE/gts/pagecontent/"
        return root.tag.startswith(f"{{{page_namespace}")

    except ET.ParseError:
        # Not an XML file, or XML is malformed
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
        return xml_file.parent / get_key(find_dotenv(), Environments.PAGEPLUS.as_prefix()+'MODIFIED') / filename
    else:
        return Path(outputdir) / filename
