"""manifest.json read/write (type/properties_ref/recent_commit/current_branch)."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path


@dataclass(frozen=True)
class ResourceManifest:
    """Metadata manifest for a resource instance.

    Stored as ``manifest.json`` inside each resource directory.
    """

    type: str
    properties_ref: str  # path to properties.md, relative to the resource dir
    recent_commit: str | None = None
    current_branch: str = "main"


def write_manifest(path: Path, manifest: ResourceManifest) -> None:
    """Write a ``ResourceManifest`` to a ``manifest.json`` file.

    Args:
        path: Path to write the ``manifest.json`` file to.
        manifest: The ``ResourceManifest`` instance to serialize.
    """
    path.write_text(
        json.dumps(asdict(manifest), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
