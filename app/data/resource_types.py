"""8 concrete resource types: Outline/ShortGoal/State/Variables/Worldbook/Facts/CharacterMemory/Notes."""

from __future__ import annotations

from .properties import ResourceProperties
from .resource import Resource


class Outline(Resource):
    """大纲 — 长期目标 (low-freq, 覆盖维护)."""

    @classmethod
    def default_properties(cls) -> ResourceProperties:
        return ResourceProperties(
            存储方式="按资源类型独立文件存储",
            召回策略="按需由 Recaller Agent 主动请求",
            维护策略="低频更新，覆盖维护",
            版本策略="覆盖版本控制，每轮产生新 commit",
        )


class ShortGoal(Resource):
    """细纲 — 本回合需发生的事 (every-round, 覆盖)."""

    @classmethod
    def default_properties(cls) -> ResourceProperties:
        return ResourceProperties(
            存储方式="按资源类型独立文件存储",
            召回策略="自动注入到 Writer Agent 上下文",
            维护策略="每轮更新，覆盖维护",
            版本策略="覆盖版本控制，每轮产生新 commit",
        )


class State(Resource):
    """当前状态 — 上一轮小总结 (every-round, 覆盖)."""

    @classmethod
    def default_properties(cls) -> ResourceProperties:
        return ResourceProperties(
            存储方式="按资源类型独立文件存储",
            召回策略="自动注入到全部 Agent 上下文",
            维护策略="每轮更新，覆盖维护",
            版本策略="覆盖版本控制，每轮产生新 commit",
        )


class Variables(Resource):
    """变量 — 前端显示用，不适合让模型看到 (every-round, 覆盖, 不召回)."""

    @classmethod
    def default_properties(cls) -> ResourceProperties:
        return ResourceProperties(
            存储方式="按资源类型独立文件存储",
            召回策略="不召回，只维护",
            维护策略="每轮更新，覆盖维护",
            版本策略="覆盖版本控制，每轮产生新 commit",
        )


class Worldbook(Resource):
    """世界书 — 背景设定/人物设定/覆写常识 (low-freq, 增量)."""

    @classmethod
    def default_properties(cls) -> ResourceProperties:
        return ResourceProperties(
            存储方式="按资源类型独立文件存储",
            召回策略="按需由 Recaller Agent 主动请求",
            维护策略="低频更新，增量维护",
            版本策略="增量版本控制，每轮产生新 commit",
        )


class Facts(Resource):
    """客观事实 — 同人设定/现实真相/网搜结果 (low-freq, 增量)."""

    @classmethod
    def default_properties(cls) -> ResourceProperties:
        return ResourceProperties(
            存储方式="按资源类型独立文件存储",
            召回策略="按需由 Recaller Agent 主动请求",
            维护策略="低频更新，增量维护",
            版本策略="增量版本控制，每轮产生新 commit",
        )


class CharacterMemory(Resource):
    """人物记忆 — 角色隔离 (frequent, 增量)."""

    @classmethod
    def default_properties(cls) -> ResourceProperties:
        return ResourceProperties(
            存储方式="按资源类型独立文件存储，角色隔离",
            召回策略="按需由 Recaller Agent 按角色主动请求",
            维护策略="频繁更新，增量维护",
            版本策略="增量版本控制，每轮产生新 commit",
        )


class Notes(Resource):
    """创作笔记 — 动态发现/反馈/新约束 (low-freq, 覆盖维护).

    创作笔记 belongs to the low-freq update
    category (alongside 大纲/事实/世界观) and is
    short-length data. 短数据采用覆盖维护, and
    short+low-freq data uses 按需读入 recall. So Notes is low-freq /
    short / 覆盖维护 / 覆盖版本 — NOT frequent / 增量.
    """

    @classmethod
    def default_properties(cls) -> ResourceProperties:
        return ResourceProperties(
            存储方式="按资源类型独立文件存储",
            召回策略="按需读入，由 Agent 自行决定是否需要",
            维护策略="低频更新，覆盖维护",
            版本策略="覆盖版本控制，每轮产生新 commit",
        )


# ── Registry ──────────────────────────────────────────────────────────

RESOURCE_TYPE_REGISTRY: dict[str, type[Resource]] = {
    "outline": Outline,
    "short_goal": ShortGoal,
    "state": State,
    "variables": Variables,
    "worldbook": Worldbook,
    "facts": Facts,
    "character_memory": CharacterMemory,
    "notes": Notes,
}


def get_resource_type(type_name: str) -> type[Resource]:
    """Look up a resource type class by its string name.

    Raises ``KeyError`` if the type is not registered.
    """
    if type_name not in RESOURCE_TYPE_REGISTRY:
        valid = ", ".join(sorted(RESOURCE_TYPE_REGISTRY))
        msg = f"Unknown resource type: {type_name!r}. Valid types: {valid}"
        raise KeyError(msg)
    return RESOURCE_TYPE_REGISTRY[type_name]

