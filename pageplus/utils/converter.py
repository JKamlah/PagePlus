from __future__ import annotations

import re
from enum import Enum

from typing_extensions import Type, Iterable


def strings_to_enum(name: str, strings: list[str] | Iterable[str]) -> Type[Enum]:
    # Create a dictionary with member names and their values both set to the strings from the list
    members = {string: string for string in strings}
    # Dynamically create the enum using the Enum constructor
    return Enum(name, members)


def convert_value(val):
    if val.isdigit():
        return int(val)
    return val

def custom_to_dict(s):
    pattern = r'(\w+)\s*\{([^}]*)\}'
    matches = re.findall(pattern, s)

    result = {}
    for key, values in matches:
        inner_dict = {}
        for pair in values.split(';'):
            pair = pair.strip()
            if pair:
                if ':' in pair:
                    k, v = pair.split(':', 1)
                    inner_dict[k.strip()] = convert_value(v.strip())
                else:
                    # If no key is provided, use the value as both key and value
                    inner_dict[pair] = convert_value(pair)
        result[key] = inner_dict

    return result

def dict_to_custom(d):
    result = []
    for key, values in d.items():
        inner_values = "; ".join(f"{k}:{v}" for k, v in values.items()) + ";"
        result.append(f"{key} {{{inner_values}}}")
    return " ".join(result)