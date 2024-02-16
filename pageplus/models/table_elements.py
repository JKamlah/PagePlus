from dataclasses import dataclass, field
from typing import Optional, List

# Assuming these are your custom classes based on the import paths you provided.
from pageplus.models.basic_elements import Region
from pageplus.models.text_elements import TextRegion, Textline


@dataclass
class TableCell(TextRegion):
    """
    Represents a cell within a table region of a document page, potentially including text lines.

    Attributes:
        parent: A reference to the parent TableRegion object. Optional.
    """
    parent: Optional[Region] = field(default=None)  # Modified to directly use None as default


@dataclass
class TableRegion(Region):
    """
    Represents a table region within a document page, including its cells and text lines.

    Attributes:
        parent: A reference to the parent Page object. Optional and typically None.
        tablecells: A list of TableCell instances that belong to this table region.
        textlines: A list of Textline instances extracted from all table cells.
    """
    parent: Optional[None] = field(default=None)  # Modified to directly use None as default
    tablecells: List[TableCell] = field(default_factory=list)  # List of TableCell instances
    textlines: List[Textline] = field(default_factory=list)  # List of Textline instances

    def __post_init__(self):
        """
        Initializes the TableRegion by extracting TableCell elements and their text lines.
        """
        # Assuming `self.xml_element` and `self.ns` are defined in the `Region` base class
        self.tablecells = [TableCell(ele, self.ns, parent=self) for ele in
                           self.xml_element.iter(f"{{{self.ns}}}TableCell")]
        for tc in self.tablecells:
            self.textlines.extend(tc.textlines)  # Use extend to add elements of one list to another
