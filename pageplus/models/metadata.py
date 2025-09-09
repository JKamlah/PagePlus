from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional

import lxml.etree as ET


@dataclass
class Metadata:
    """Represents metadata for a PAGE XML document."""
    creator: str
    created: datetime
    last_change: datetime
    comments: Optional[str] = None
    user_defined: dict = field(default_factory=dict)

    @classmethod
    def from_xml(cls, metadata_element: Optional[ET.Element], ns: str) -> 'Metadata':
        """Create metadata from an XML element by reading its child elements."""
        if metadata_element is None:
            return cls(
                creator="PagePlus",
                created=datetime.now(),
                last_change=datetime.now(),
                comments="",
            )

        def get_text_from_child(tag):
            child = metadata_element.find(f"{{{ns}}}{tag}")
            return child.text if child is not None and child.text else None

        creator = get_text_from_child("Creator") or "Unknown"
        created_text = get_text_from_child("Created")
        last_change_text = get_text_from_child("LastChange")
        comments = get_text_from_child("Comments") or ""

        try:
            created = datetime.fromisoformat(created_text.replace("Z", "+00:00"))
        except (ValueError, TypeError, AttributeError):
            created = datetime.now()

        try:
            last_change = datetime.fromisoformat(last_change_text.replace("Z", "+00:00"))
        except (ValueError, TypeError, AttributeError):
            last_change = datetime.now()

        return cls(
            creator=creator,
            created=created,
            last_change=last_change,
            comments=comments,
            user_defined={}
        )

    def update_xml_element(self, metadata_element: ET.Element, ns: str, new: bool = False):
        """
        Updates the XML element with the metadata values as child elements.
        """
        if new:
            metadata_element.attrib.clear()
            for child in list(metadata_element):
                metadata_element.remove(child)

        def _set_child_element(parent, tag, text):
            element = parent.find(f"{{{ns}}}{tag}")
            if element is None:
                element = ET.SubElement(parent, ET.QName(ns, tag))
            element.text = text

        _set_child_element(metadata_element, "Creator", self.creator)
        _set_child_element(metadata_element, "Created", self.created.strftime("%Y-%m-%d %H:%M:%S") if isinstance(self.created, datetime) else self.created)
        _set_child_element(metadata_element, "LastChange", self.last_change.strftime("%Y-%m-%d %H:%M:%S") if isinstance(self.last_change, datetime) else self.last_change)
        _set_child_element(metadata_element, "Comments", self.comments)
