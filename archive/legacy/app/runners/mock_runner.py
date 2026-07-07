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
        if step.agent == "state_initializer":
            return self._state(step)
        if step.agent == "arc_planner":
            return self._arc_outline(step)
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

    def _arc_outline(self, step: Step) -> str:
        """arc_planner 的 mock 输出：通过 ---ARTIFACT:--- 段落写出 master_outline.md
        与 current_arc.md 两个文件。路径取自 step.artifacts（已被 remap 到工作区）。

        - master_outline.md：validator 对含 "outline" 的路径要求 ``Required Beats``。
        - current_arc.md：validator 对含 "current_arc" 的路径要求 ``Required Events``。
        """
        master_path = ""
        arc_path = ""
        for artifact in step.artifacts:
            aid = artifact.get("id", "")
            p = artifact.get("path", "")
            if aid == "master_outline" or "master_outline" in p:
                master_path = p
            elif aid == "current_arc" or "current_arc" in p:
                arc_path = p
        # 兜底：若 artifacts 缺失，退回 step.output_path（current_arc.md）。
        if not arc_path:
            arc_path = step.output_path
        sections: list[str] = []
        if master_path:
            sections.append(f"---ARTIFACT: {master_path}---")
            sections.append(
                f"# Master Outline\n\n## Required Beats\n\n1. 开篇钩子：建立主角处境与核心矛盾。\n2. 第一阶段：主角觉醒并踏上旅程。\n3. 第二阶段：首次冲突升级，伏笔浮现。\n4. 第三阶段：阶段性高潮，关系推进。\n5. 长线伏笔：贯穿全书的核心悬念。\n"
            )
        if arc_path:
            sections.append(f"---ARTIFACT: {arc_path}---")
            sections.append(
                f"# Current Arc\n\n## Required Events\n\n1. 第 1 章：主角登场，展示日常与突发事件。\n2. 第 2 章：主角接触核心设定，首次抉择。\n3. 第 3 章：阶段冲突爆发，留下钩子。\n"
            )
        return "\n".join(sections) + "\n"
