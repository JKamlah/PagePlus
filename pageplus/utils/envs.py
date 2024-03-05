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

def filter_envs(pattern: str) -> dict:
    """
    Filters dotenv values for a specific pattern (e.g. services, prefixes, ..)
    Returns:
        dict
    """
    load_dotenv()
    envs = dotenv_values()
    return dict(sorted([(var, key) for (var, key) in envs.items() if var.startswith(pattern)], key=lambda x: x[0]))


def str_to_env(string: str, substring=True) -> str:
    # Remove leading non-alphabetic characters
    if not substring:
        string = string.lstrip('0123456789')

    # Replace invalid characters with underscores and convert to uppercase
    valid_chars = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789_"
    string = ''.join(c if c in valid_chars else '_' for c in string).upper()

    # Ensure the string does not start with a digit (handled above) and is not empty
    if not string or string[0].isdigit():
        raise ValueError("The resulting environment variable name is invalid or empty.")

    return string


def get_env_paths(env_key) -> List[Path]:
    """
    Retrieves a list of Path objects from an environment variable.

    This function takes an environment variable key, retrieves its value,
    and splits the value by ':' to form paths. It returns a list of Path
    objects corresponding to these paths, but only includes paths that exist.

    Parameters:
    env_key (str): The key of the environment variable to retrieve paths from.

    Returns:
    List[Path]: A list of Path objects that exist, derived from the environment variable's value.
    """
    load_dotenv()
    env_val = os.getenv(env_key)
    print(env_val)
    print([Path(str_val) for str_val in env_val.split(':')])
    return [Path(str_val) for str_val in env_val.split(':') if Path(str_val).exists()] \
        if env_val is not None else []