from dataclasses import dataclass, field
from typing import Optional, List
from datetime import datetime


@dataclass
class Metadata:
    """Represents metadata for a PAGE XML document."""
    creator: str
    created: datetime
    last_change: datetime
    comments: Optional[str] = None
    user_defined: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        """Convert metadata to dictionary."""
        return {
            "creator": self.creator,
            "created": self.created.isoformat(),
            "last_change": self.last_change.isoformat(),
            "comments": self.comments,
            "user_defined": self.user_defined
        }

    @classmethod
    def from_dict(cls, data: dict) -> 'Metadata':
        """Create metadata from dictionary."""
        return cls(
            creator=data["creator"],
            created=datetime.fromisoformat(data["created"]),
            last_change=datetime.fromisoformat(data["last_change"]),
            comments=data.get("comments"),
            user_defined=data.get("user_defined", {})
        ) 