"""ResourceStore: CRUD resources, read/write/search file content, index maintenance, permission check."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from .manifest import ResourceManifest, read_manifest, write_manifest
from .properties import parse_properties_md, serialize_properties_md
from .resource import Resource
from .resource_types import get_resource_type


@dataclass(frozen=True)
class SearchHit:
    """A single search result hit within a resource's content files."""

    filename: str
    line_number: int
    matching_text: str
    context: str


_SKIP_FILES: frozenset[str] = frozenset({"properties.md", "manifest.json", ".index"})


class ResourceStore:
    """File-based CRUD and access layer for project resources.

    Operates within one project's ``resources/`` directory.
    Provides no recall or maintenance logic — only storage, access, indexing,
    and permission checking.
    """

    def __init__(self, project_root: Path) -> None:
        self._root = project_root.resolve()
        self._resources_dir = self._root / "resources"

    # ── Public API ────────────────────────────────────────────────────

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

        # Init empty .index
        index_path = res_dir / ".index"
        if not index_path.exists():
            index_path.write_text("", encoding="utf-8")

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
        (excluding metadata files ``properties.md``, ``manifest.json``,
        ``.index``).  Files are separated by a ``--- <name> ---`` marker.

        If *filename* is given, reads that specific file relative to the
        resource directory.
        """
        res_dir = resource.path
        if filename is not None:
            return (res_dir / filename).read_text(encoding="utf-8")

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
        """Write a file into the resource directory and update the index."""
        file_path = resource.path / filename
        file_path.parent.mkdir(parents=True, exist_ok=True)
        file_path.write_text(content, encoding="utf-8")
        self._update_index(resource)

    def search(self, resource: Resource, query: str) -> list[SearchHit]:
        """Grep-style substring search across the resource's content files.

        Performs case-insensitive substring matching.  Returns hits with
        filename, 1-based line number, the matching line text, and a context
        window (previous line → matching line → next line, with line numbers).
        """
        hits: list[SearchHit] = []
        pattern = re.compile(re.escape(query), re.IGNORECASE)
        res_dir = resource.path

        for child in sorted(res_dir.iterdir()):
            if not child.is_file() or child.name in _SKIP_FILES:
                continue
            lines = child.read_text(encoding="utf-8").split("\n")
            for i, line_text in enumerate(lines, start=1):
                if pattern.search(line_text):
                    start = max(0, i - 2)
                    end = min(len(lines), i + 1)
                    ctx = "\n".join(
                        f"{start + j + 1}: {lines[start + j]}"
                        for j in range(end - start)
                    )
                    hits.append(
                        SearchHit(
                            filename=child.name,
                            line_number=i,
                            matching_text=line_text.strip(),
                            context=ctx,
                        )
                    )
        return hits

    def list_resources(self) -> list[Resource]:
        """List all resource instances in the project.

        Scans each subdirectory of ``resources/`` for a ``manifest.json``,
        reads it and ``properties.md``, and returns a ``Resource`` instance
        for each one.
        """
        result: list[Resource] = []
        if not self._resources_dir.exists():
            return result

        for child in sorted(self._resources_dir.iterdir()):
            if not child.is_dir():
                continue
            type_name = child.name

            manifest_path = child / "manifest.json"
            props_path = child / "properties.md"
            if not manifest_path.exists():
                continue

            try:
                type_cls = get_resource_type(type_name)
            except KeyError:
                continue

            manifest = read_manifest(manifest_path)

            if props_path.exists():
                props = parse_properties_md(
                    props_path.read_text(encoding="utf-8")
                )
            else:
                props = type_cls.default_properties()

            result.append(
                type_cls(
                    id=type_name,
                    type=type_name,
                    path=child,
                    properties=props,
                    manifest=manifest,
                )
            )
        return result

    def permission_check(
        self,
        agent_permission: dict[str, list[str]],
        resource: Resource,
    ) -> bool:
        """Check whether the agent's permission covers this resource.

        *agent_permission* is a hash ``dict[str, list[str]]`` like
        ``{'read': ['state', 'memory'], 'write': ['short_goal']}``.

        Returns ``True`` if the resource's type name appears in **any** of
        the permission value lists (both read and write are checked since
        the intent is to verify general visibility).
        """
        resource_type = resource.type
        for action in ("read", "write"):
            if resource_type in agent_permission.get(action, []):
                return True
        return False

    # ── Internal helpers ──────────────────────────────────────────────

    def _update_index(self, resource: Resource) -> None:
        """Rebuild the ``.index`` file inside the resource directory.

        Scans every content file for markdown headings (``#`` … ``######``)
        and writes the result as a symbol-search-friendly listing.
        """
        res_dir = resource.path
        lines: list[str] = []
        heading_re = re.compile(r"^(#{1,6})\s+(.+)")

        for child in sorted(res_dir.iterdir()):
            if not child.is_file() or child.name in _SKIP_FILES:
                continue
            lines.append(f"# {child.name}")
            content = child.read_text(encoding="utf-8")
            for text_line in content.split("\n"):
                m = heading_re.match(text_line)
                if m:
                    lines.append(text_line)
        (res_dir / ".index").write_text("\n".join(lines) + "\n", encoding="utf-8")
