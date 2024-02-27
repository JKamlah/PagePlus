from __future__ import annotations
from enum import Enum

WORKSPACE_PREFIX = 'WS_'

class DotEnvPrefixes(str, Enum):
    """
    Prefixes for dotenvs variables
    """
    USER = "USER"
    PAGEPLUS = "PAGEPLUS"
    METS = "METS"
    IIIF = "IIIF"
    ESCRIPTORIUM = "ESCRIPTORIUM"
    TRANSKRIBUS = "TRANSKRIBUS"
    DINGLEHOPPER = "DINGLEHOPPER"
    OPENAI = "OPENAI"
    H2O = "H2O"

class WorkState(str, Enum):
    """
    State of the current data
    """
    ORIGINAL = "ORIGINAL"
    MODIFIED = "MODIFIED"


# Converts boolean values to on and off
Bool2OnOff = {True: "on", False: "off"}
