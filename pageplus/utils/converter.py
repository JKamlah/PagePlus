from __future__ import annotations

from enum import Enum
import json
from typing_extensions import Type, Iterable

from pageplus.models.page import Page

def strings_to_enum(name: str, strings: list[str] | Iterable[str]) -> Type[Enum]:
    # Create a dictionary with member names and their values both set to the strings from the list
    members = {string: string for string in strings}
    # Dynamically create the enum using the Enum constructor
    return Enum(name, members)


def convert_page_to_json(page: Page, ) -> dict:
    # TODO: Implement this function..
    return json