"""Resource abstract base class (id/type/path/properties/manifest)."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path

from .manifest import ResourceManifest
from .properties import ResourceProperties


@dataclass(frozen=True)
class Resource(ABC):
    """Abstract base class for all resource types.

    Each concrete resource type (Outline, ShortGoal, State, …) subclasses
    this and implements ``default_properties()``.

    Fields:
        id:         Unique resource-instance identifier (within a project).
        type:       Resource type name (e.g. ``"outline"``, ``"state"``).
        path:       Filesystem path to the resource directory.
        properties: The parsed ``properties.md`` attribute table.
        manifest:   The parsed ``manifest.json`` metadata.
    """

    id: str
    type: str
    path: Path
    properties: ResourceProperties
    manifest: ResourceManifest

    @classmethod
    @abstractmethod
    def default_properties(cls) -> ResourceProperties:
        """Return the default ``ResourceProperties`` for this type.

        Every concrete subclass must override this to declare its own
        storage / recall / maintenance / version strategy defaults.
        """
        ...
