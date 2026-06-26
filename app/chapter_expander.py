from __future__ import annotations

import asyncio

from app.config_loader import ConfigBundle
from app.runners.base import Step
from app.runners.direct_runner import DirectRunner
from app.runtime_config import load_runtime_config


async def expand_chapter(
    config: ConfigBundle,
    scene_id: str,
    chapter_markdown: str,
    outline_text: str,
    snapshot_text: str,
    characters_text: str,
    style_text: str,
    min_chars: int,
    pass_index: int,
) -> str:
    runtime = load_runtime_config(config.root)
    runner = DirectRunner(runtime, config.models)
    step = Step(
        id=f"expand_chapter_pass_{pass_index}",
        agent="chapter_expander",
        scene_id=scene_id,
        prompt_path="",
        output_path=f"{scene_id}_expanded.md",
        inputs=[],
        runner="direct",
        raw={},
        profile="writer.expander",
    )
    context = f"""# Chapter Expander

你的任务：
- 把当前章节扩写到至少 {min_chars} 个中文字符。
- 输出完整章节正文，不要只输出补丁，不要只输出续写片段。
- 必须保留现有章节标题与已发生的核心事件。
- 不允许新增会改变后续 state 的重大新事实。
- 你只能通过补充环境、动作、对话、心理博弈、节奏回合、余波和收尾钩子来扩写。
- 保持网文可读性和章节完整度。
- 优先扩充已有场景，不要无意义跳剧情。

## 当前章节

{chapter_markdown}

## 最终细纲

{outline_text}

## 冻结快照

{snapshot_text}

## 角色设定

{characters_text}

## 文风模块

{style_text}
"""
    return await runner.run(step, context)


async def iterative_expand_chapter(
    config: ConfigBundle,
    scene_id: str,
    chapter_markdown: str,
    outline_text: str,
    snapshot_text: str,
    characters_text: str,
    style_text: str,
    min_chars: int,
    counter,
    max_passes: int = 3,
):
    current = chapter_markdown
    for index in range(1, max_passes + 1):
        expanded = await expand_chapter(
            config=config,
            scene_id=scene_id,
            chapter_markdown=current,
            outline_text=outline_text,
            snapshot_text=snapshot_text,
            characters_text=characters_text,
            style_text=style_text,
            min_chars=min_chars,
            pass_index=index,
        )
        current = expanded
        if counter(current) >= min_chars:
            break
    return current


def expand_chapter_sync(
    config: ConfigBundle,
    scene_id: str,
    chapter_markdown: str,
    outline_text: str,
    snapshot_text: str,
    characters_text: str,
    style_text: str,
    min_chars: int,
    pass_index: int,
) -> str:
    return asyncio.run(
        expand_chapter(
            config,
            scene_id,
            chapter_markdown,
            outline_text,
            snapshot_text,
            characters_text,
            style_text,
            min_chars,
            pass_index,
        )
    )


def iterative_expand_chapter_sync(
    config: ConfigBundle,
    scene_id: str,
    chapter_markdown: str,
    outline_text: str,
    snapshot_text: str,
    characters_text: str,
    style_text: str,
    min_chars: int,
    counter,
    max_passes: int = 3,
) -> str:
    return asyncio.run(
        iterative_expand_chapter(
            config=config,
            scene_id=scene_id,
            chapter_markdown=chapter_markdown,
            outline_text=outline_text,
            snapshot_text=snapshot_text,
            characters_text=characters_text,
            style_text=style_text,
            min_chars=min_chars,
            counter=counter,
            max_passes=max_passes,
        )
    )
