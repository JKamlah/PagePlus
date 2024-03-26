from __future__ import annotations

import os
from pathlib import Path
from typing import Tuple, Iterator, List

from dotenv import load_dotenv, find_dotenv, get_key, dotenv_values


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
    """
    Converts a given string into a format suitable for environment variable names.

    This function processes the input string to make it compliant with common
    conventions for environment variable names. It removes leading non-alphabetic characters
    if the `substring` flag is False, replaces any invalid characters (i.e., characters
    not in the set of uppercase and lowercase English letters, digits, and the underscore)
    with underscores, and converts the string to uppercase.

    The function ensures that the resulting string is not empty and does not start with
    a digit, raising a ValueError if these conditions are not met.

    Args:
        string (str): The input string to convert.
        substring (bool, optional): If True, leading non-alphabetic characters are allowed.
            If False, such characters are removed from the beginning of the string. Defaults to True.

    Returns:
        str: The transformed string suitable for use as an environment variable name.

    Raises:
        ValueError: If the resulting string is empty or starts with a digit.
    """
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