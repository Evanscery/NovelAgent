"""ResourceStore: CRUD resources, read/write file content, file I/O tools.

The data layer provides storage, access, and file I/O utilities for project
resources. It owns no recall, maintenance, or permission logic — those
concerns live in the Agent and Runtime layers.
"""

from __future__ import annotations

import fnmatch
import re
from pathlib import Path

from .manifest import ResourceManifest, write_manifest
from .properties import serialize_properties_md
from .resource import Resource
from .resource_types import get_resource_type

_SKIP_FILES: frozenset[str] = frozenset({"properties.md", "manifest.json"})


def resolve_content_path(res_dir: Path, filename: str) -> Path:
    """Resolve *filename* inside *res_dir*, rejecting any path escape.

    Nested relative paths (subdirectories) are allowed; absolute paths,
    drive-qualified paths, and ``..`` traversal are rejected so that a
    tool-driven agent can never reach outside its resource directory.
    """
    candidate = Path(filename)
    if (
        not filename.strip()
        or candidate.is_absolute()
        or bool(candidate.drive)
        or filename.startswith(("/", "\\"))
        or ".." in candidate.parts
    ):
        raise ValueError(
            f"invalid filename {filename!r}: must be a relative path "
            "inside the resource directory"
        )
    resolved = (res_dir / candidate).resolve()
    if not resolved.is_relative_to(res_dir.resolve()):
        raise ValueError(
            f"invalid filename {filename!r}: escapes the resource directory"
        )
    return resolved


class ResourceStore:
    """File-based CRUD and access layer for project resources.

    Operates within one project's ``resources/`` directory.
    Provides storage, access, and file I/O utilities — no recall or
    maintenance logic.
    """

    def __init__(self, project_root: Path) -> None:
        self._root = project_root.resolve()
        self._resources_dir = self._root / "resources"

    # -- Public API ---------------------------------------------------------

    def create_resource(self, resource_type: str, resource_id: str) -> Resource:
        """Scaffold a new resource directory and return a ``Resource`` instance.

        The directory is created at ``resources/<resource_type>/`` even if it
        already exists (idempotent).  Writes default ``properties.md`` (from
        the type's default) and ``manifest.json``.
        """
        type_cls = get_resource_type(resource_type)
        res_dir = self._resources_dir / resource_type
        res_dir.mkdir(parents=True, exist_ok=True)

        # Write properties.md from the type's default (don't overwrite if exists)
        props = type_cls.default_properties()
        props_path = res_dir / "properties.md"
        if not props_path.exists():
            props_path.write_text(serialize_properties_md(props), encoding="utf-8")

        # Write manifest.json (don't overwrite if exists)
        manifest = ResourceManifest(
            type=resource_type,
            properties_ref="properties.md",
            recent_commit=None,
            current_branch="main",
        )
        manifest_path = res_dir / "manifest.json"
        if not manifest_path.exists():
            write_manifest(manifest_path, manifest)

        return type_cls(
            id=resource_id,
            type=resource_type,
            path=res_dir,
            properties=props,
            manifest=manifest,
        )

    def read(
        self,
        resource: Resource,
        filename: str | None = None,
    ) -> str:
        """Read content from a resource.

        If *filename* is ``None``, returns **all** content files concatenated
        (excluding metadata files ``properties.md`` / ``manifest.json``).
        Files are separated by a ``--- <name> ---`` marker.

        If *filename* is given, reads that specific file relative to the
        resource directory.
        """
        res_dir = resource.path
        if filename is not None:
            file_path = resolve_content_path(res_dir, filename)
            if not file_path.is_file():
                raise FileNotFoundError(
                    f"file {filename!r} not found in resource '{resource.type}'; "
                    "use list_files to see available files"
                )
            return file_path.read_text(encoding="utf-8")

        # Concatenate all content files
        parts: list[str] = []
        for child in sorted(res_dir.iterdir()):
            if not child.is_file() or child.name in _SKIP_FILES:
                continue
            parts.append(
                f"--- {child.name} ---\n{child.read_text(encoding='utf-8')}"
            )
        return "\n\n".join(parts)

    def write(self, resource: Resource, filename: str, content: str) -> None:
        """Write a file into the resource directory."""
        file_path = resolve_content_path(resource.path, filename)
        file_path.parent.mkdir(parents=True, exist_ok=True)
        file_path.write_text(content, encoding="utf-8")

    def list_files(self, resource: Resource) -> list[str]:
        """Return all content file names in the resource directory, sorted.

        Excludes metadata files (``properties.md`` / ``manifest.json``).
        """
        res_dir = resource.path
        names: list[str] = []
        for child in sorted(res_dir.iterdir()):
            if not child.is_file() or child.name in _SKIP_FILES:
                continue
            names.append(child.name)
        return names

    def glob_files(self, resource: Resource, pattern: str) -> list[str]:
        """Return content file names matching *pattern* (fnmatch-style).

        Excludes metadata files.
        """
        return [
            name
            for name in self.list_files(resource)
            if fnmatch.fnmatch(name, pattern)
        ]

    def grep_lines(
        self,
        resource: Resource,
        pattern: str,
        filename: str | None = None,
    ) -> list[tuple[str, int, str]]:
        """Regex search across the resource's content files.

        Args:
            resource: The resource to search within.
            pattern: A regular expression pattern to match.
            filename: If given, only search that specific file; otherwise
                search all content files.

        Returns:
            A list of ``(filename, line_number, line_text)`` tuples where
            ``line_number`` is 1-based and ``line_text`` is the matching line
            (without trailing newline). No context window is built.
        """
        regex = re.compile(pattern)
        res_dir = resource.path
        hits: list[tuple[str, int, str]] = []

        if filename is not None:
            targets = [resolve_content_path(res_dir, filename)]
        else:
            targets = [
                child
                for child in sorted(res_dir.iterdir())
                if child.is_file() and child.name not in _SKIP_FILES
            ]

        for path in targets:
            if not path.exists():
                continue
            lines = path.read_text(encoding="utf-8").split("\n")
            for i, line_text in enumerate(lines, start=1):
                if regex.search(line_text):
                    hits.append((path.name, i, line_text))
        return hits

    def read_lines(
        self,
        resource: Resource,
        filename: str,
        start: int,
        end: int,
    ) -> str:
        """Read a 1-based line range [start, end] from *filename*.

        Args:
            resource: The resource containing the file.
            filename: The file name within the resource directory.
            start: 1-based first line number (inclusive).
            end: 1-based last line number (inclusive).

        Returns:
            The text of lines *start* through *end*, joined with ``\n``.
        """
        file_path = resolve_content_path(resource.path, filename)
        if not file_path.is_file():
            raise FileNotFoundError(
                f"file {filename!r} not found in resource '{resource.type}'; "
                "use list_files to see available files"
            )
        lines = file_path.read_text(encoding="utf-8").split("\n")
        # 1-based to 0-based: start-1 .. end (slice end is exclusive)
        clamped_start = max(0, start - 1)
        clamped_end = min(len(lines), end)
        return "\n".join(lines[clamped_start:clamped_end])
