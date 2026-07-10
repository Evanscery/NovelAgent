"""Intermediate representation TypedDicts for tavern card migration.

Holds :class:`CardIR` (the flattened card intermediate) and :class:`RuntimePlan`
(the derived runtime hints). Split out of the legacy monolithic
``card_migration.py`` so the recognition, content-builder, and materializer
modules can share these types without a circular import.
"""

from __future__ import annotations

from typing import Any, TypedDict

__all__ = ["CardIR", "RuntimePlan"]


class CardIR(TypedDict, total=False):
    """Intermediate representation of a parsed tavern card.

    Produced by :func:`app.compat.tavern_card.card_recognition.infer_card_ir`;
    consumed by :func:`infer_runtime_plan` and
    :func:`app.compat.tavern_card.materializer.materialize_project_from_card`.
    All fields are optional (a card may omit any of them).
    """

    card_name: str
    identity: dict[str, Any]
    visibility: dict[str, list[str]]
    world_rules: list[str]
    state_variables: list[dict[str, str]]
    triggers: list[str]
    relationships: list[dict[str, str]]
    prompt_hints: dict[str, Any]
    character_book: dict[str, Any]
    front_scripts: list[dict[str, Any]]


class RuntimePlan(TypedDict, total=False):
    """How a :class:`CardIR` maps onto the runtime (mode + persisted state)."""

    recommended_mode: str
    prompt_only: bool
    evented_runtime: bool
    needs_sub_agents: bool
    persist_state: list[str]
    mount_modules: list[str]
    reasoning: dict[str, Any]
