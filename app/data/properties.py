"""properties.md parser/serializer (per-resource-type attribute table)."""

from __future__ import annotations

import re
from dataclasses import dataclass


class ValidationError(ValueError):
    """Raised when properties.md parsing fails."""

    pass


_SECTION_HEADINGS: list[str] = [
    "存储方式",
    "召回策略",
    "维护策略",
    "版本策略",
]


@dataclass(frozen=True)
class ResourceProperties:
    """Per-resource-type attribute table (properties.md).

    Mirrors the four strategy fields from refactor_guide §数据设计:
    存储方式, 召回策略, 维护策略, 版本策略.
    """

    存储方式: str = ""
    召回策略: str = ""
    维护策略: str = ""
    版本策略: str = ""


def parse_properties_md(text: str) -> ResourceProperties:
    """Parse a properties.md string into a ResourceProperties instance.

    Expected format: markdown with four ``## <heading>`` sections
    (存储方式, 召回策略, 维护策略, 版本策略), each followed by free-text body.

    Raises ``ValidationError`` if any required section is missing.
    """
    sections = re.split(r"^##\s+", text, flags=re.MULTILINE)
    # sections[0] is anything before the first heading (preamble, discarded)
    parsed: dict[str, str] = {}
    for section in sections[1:]:
        parts = section.split("\n", 1)
        heading = parts[0].strip()
        body = parts[1].strip() if len(parts) > 1 else ""
        if heading in _SECTION_HEADINGS:
            parsed[heading] = body

    for heading in _SECTION_HEADINGS:
        if heading not in parsed:
            msg = f"Missing required section: ## {heading}"
            raise ValidationError(msg)

    return ResourceProperties(**parsed)


def serialize_properties_md(props: ResourceProperties) -> str:
    """Serialize a ResourceProperties instance back to properties.md format.

    The output is round-trip stable: ``parse_properties_md(serialize_properties_md(p)) == p``.
    """
    parts: list[str] = []
    for heading in _SECTION_HEADINGS:
        value = getattr(props, heading)
        parts.append(f"## {heading}")
        if value:
            parts.append(value)
    return "\n\n".join(parts) + "\n"
