import shapely.errors as ShapelyErrors

class PageXMLError(Exception):
    pass

class InputsDoNotExistException(Exception):
    """Exception raised when the input folder does not exist."""
    def __init__(self, inputs, message="Input workspaces and/or folder do not exist"):
        self.folder_path = inputs
        self.message = f"{message}: {inputs}"
        super().__init__(self.message)

class NotValidMetsException(Exception):
    """Exception raised when the input no volid mets file is."""
    def __init__(self, input, message="The input is no valid mets file"):
        self.message = f"{message}: {input}"
        super().__init__(self.message)

class MetsError(Exception):
    """General exception for METS structure errors."""
    pass

