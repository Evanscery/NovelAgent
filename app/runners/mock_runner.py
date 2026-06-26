from __future__ import annotations

from app.runners.base import AgentRunner, Step


class MockRunner(AgentRunner):
    """用于验证流程的假运行器，不调用模型。"""

    async def run(self, step: Step, context: str) -> str:
        if step.agent.endswith("_guard"):
            return self._critic_report(step)
        if step.agent == "scene_planner":
            return self._rough_outline(step)
        if step.agent == "outline_integrator":
            return self._final_outline(step)
        if step.agent == "prose_writer":
            return f"# Draft\n\n这是 {step.scene_id} 的 mock 草稿。角色按照细纲行动，场景保持连续，文风模块已参与组装。\n"
        if step.agent == "prose_reviser":
            return f"# Final\n\n这是 {step.scene_id} 的 mock 最终正文。审查报告中的问题已被视为修复，模块化 prompt 组装已生效。\n"
        if step.agent == "state_manifest_keeper":
            return self._state(step)
        return f"# {step.agent}\n\nMock output for {step.scene_id}.\n"

    def _critic_report(self, step: Step) -> str:
        target = "final" if step.raw.get("final_mode") else "draft"
        return f"""# Critic Report

## Verdict
PASS

## Issues

暂无关键问题。

## Notes

Mock 审查通过：{step.agent} / {step.scene_id} / target={target}。
"""

    def _rough_outline(self, step: Step) -> str:
        return f"""# Rough Outline of This Round

## Metadata
- Chapter: 1
- Scene: {step.scene_id}
- POV: 待填写
- Time: 待填写
- Location: 待填写

## Scene Goal

跑通 {step.scene_id} 的初版场景规划。

## Required Beats
1. 承接冻结输入快照中的当前状态。
2. 推进一个明确场景事件。
3. 留下可接续的结尾。

## Character Knowledge Boundaries

角色只能知道 run_snapshot 与 characters 中允许的信息。

## Logic Constraints

不得违反 worldbook。

## Expected Ending State

状态可以自然进入下一场。

## Uncertainties

- 当前为 mock 输出。
"""

    def _final_outline(self, step: Step) -> str:
        return f"""# Final Outline of This Round

## Metadata
- Chapter: 1
- Scene: {step.scene_id}
- POV: 待填写
- Time: 待填写
- Location: 待填写

## Scene Goal

完成 {step.scene_id} 的最终细纲。

## Required Beats
1. 承接上一场状态。
2. 推进一个明确事件。
3. 更新人物或伏笔状态。

## Character Knowledge Boundaries

不得让角色知道未获得的信息。

## Logic Constraints

保持时间、地点、物品连续。

## Expected Ending State

下一场能从 state.md 接续。

## Uncertainties

- 当前为 mock 修订结果。
"""

    def _state(self, step: Step) -> str:
        scene_no = int(step.scene_id[1:3]) if step.scene_id.startswith("C") else 1
        return f"""# Current State

## Position

- Chapter: {scene_no}
- Scene: {step.scene_id}
- Time: mock 时间之后
- Location: mock 地点
- POV: 待填写

## Current Situation

{step.scene_id} 已完成 mock 最终正文。

## Active Characters

- Character A: 状态稳定。

## Character Knowledge

### Character A

Knows:
- 已经历 {step.scene_id} 的公开事件。

Does Not Know:
- 未公开的后台真相。

## Open Threads

- T001: 继续保持 open。

## Constraints

- 下一场必须承接 {step.scene_id} 的结果。

## Last Scene Result

- {step.scene_id} 已完成并可归档。

---PLAYER_VISIBLE_STATE---
# Player Visible State

## What the Player / POV Character Knows

- 已经历 {step.scene_id} 的可见事件。

## Available Leads

- T001

## Hidden Information

此文件不应包含后台真相。
"""
