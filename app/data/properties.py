"""properties.md serializer (per-resource-type attribute table)."""

from __future__ import annotations

from dataclasses import dataclass

_SECTION_HEADINGS: list[str] = [
    "存储方式",
    "召回策略",
    "维护策略",
    "版本策略",
]


@dataclass(frozen=True)
class ResourceProperties:
    """Per-resource-type attribute table (properties.md).

    Mirrors the four per-type strategy fields:
    存储方式, 召回策略, 维护策略, 版本策略.
    """

    存储方式: str = ""
    召回策略: str = ""
    维护策略: str = ""
    版本策略: str = ""


def serialize_properties_md(props: ResourceProperties) -> str:
    """Serialize a ResourceProperties instance to properties.md format."""
    parts: list[str] = []
    for heading in _SECTION_HEADINGS:
        value = getattr(props, heading)
        parts.append(f"## {heading}")
        if value:
            parts.append(value)
    return "\n\n".join(parts) + "\n"
