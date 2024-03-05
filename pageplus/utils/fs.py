from __future__ import annotations

from datetime import datetime
import os
from pathlib import Path
import tempfile
from typing import Tuple, Iterator, List

import lxml.etree as ET
import typer
from dotenv import load_dotenv, find_dotenv, get_key, dotenv_values

from pageplus.utils.constants import Environments, PagePlus
from pageplus.utils.exceptions import InputsDoNotExistException
from pageplus.utils.envs import str_to_env


def join_modified_path(path: Path, count: int) -> Path:
    mod_path = get_key(find_dotenv(), Environments.PAGEPLUS.as_prefix()+'MODIFIED')
    for _ in range(0, count):
        path = path.joinpath(mod_path)
    return path


def transform_input(ctx: typer.Context, param: typer.CallbackParam, value: str):
    return transform_inputs(ctx, param, [value])[0]

def transform_inputs(ctx: typer.Context, param: typer.CallbackParam, values: List[str]):
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
        print(inputpath)
        if (inputpath.is_file() and inputpath.suffix == '.xml' and inputpath.name not in exclude and
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
        print(ws_folder)
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
