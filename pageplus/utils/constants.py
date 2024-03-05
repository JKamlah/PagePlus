from __future__ import annotations
from enum import Enum

class WorkState(str, Enum):
    """
    State of the current data
    """
    ORIGINAL = "original"
    MODIFIED = "modified"

class PagePlus(str, Enum):
    """
    Pageplus configuration
    """
    SYSTEM = "System"

    def as_prefix(self):
        return f"{self.name.upper()}_"

    def as_prefix_workspace_dir(self):
        return f"{self.name.upper()}_WS_DIR"

class Environments(str, Enum):
    """
    Service names are used as prefixes with _ for dotenvs variables
    """
    #USER = "User"
    PAGEPLUS = "PagePlus"
    #METS = "METS"
    #IIIF = "IIIF"
    ESCRIPTORIUM = "eScriptorium"
    TRANSKRIBUS = "Transkribus"
    #DINGLEHOPPER = "Dinglehopper"
    #OPENAI = "OpenAI"
    #H2O = "H2O"

    def as_prefix(self):
        return f"{self.name.upper()}_"

    def as_prefix_workspace(self):
        return f"{self.name.upper()}_WS_"

    def as_prefix_loaded_workspace(self):
        return f"{self.name.upper()}_LOADED_WS"

    def as_prefix_environment(self):
        return f"{self.name.upper()}_ENVIRONMENT"

    def as_prefix_workstate(self, state: WorkState):
        if state == "original":
            return f"{self.name.upper()}_ORIGINAL"
        else:
            return f"{self.name.upper()}_MODIFIED"


# Converts boolean values to on and off
Bool2OnOff = {True: "on", False: "off"}
