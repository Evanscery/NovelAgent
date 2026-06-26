# 流程说明

当前版本采用更明确的 Agent 阶段划分，参考了 TauriTavern Agent 模式中的 artifact 与 prompt assembly 思路。

## 主流程

```text
run_snapshotter
→ recaller
→ scene_planner
→ outline_worldbook_guard
→ outline_knowledge_guard
→ outline_integrator
→ prose_writer
→ character_guard
→ continuity_guard
→ style_detail_guard
→ prose_reviser
→ state_manifest_keeper
→ memory_archivist
```

## 阶段说明

1. `run_snapshotter`
   - 本地步骤。
   - 生成 `work/run_snapshot.md`。
   - 冻结本轮输入事实。

2. `recaller`
   - 从 SQLite Recall 中检索历史摘要、索引和全文片段。
   - 生成 `work/recall_report.md`。

3. `scene_planner`
   - 生成本轮初版场景规划。
   - 产出 `work/rough_outline.md`。

4. `outline_worldbook_guard`
   - 检查场景规划是否违反世界观、物理逻辑或设定硬规则。

5. `outline_knowledge_guard`
   - 检查角色知道/不知道什么，防止认知越界。

6. `outline_integrator`
   - 根据两份审查报告整合生成最终细纲。
   - 产出 `work/outline_final.md`。

7. `prose_writer`
   - 严格根据最终细纲写正文草稿。
   - 产出 `work/draft.md`。

8. `character_guard`
   - 审查草稿中的角色表现、动机、关系与说话方式。

9. `continuity_guard`
   - 审查连续性、因果、时间地点、物品状态与历史事实一致性。

10. `style_detail_guard`
   - 审查文风、AI 腔、动作细节和物理连续性。

11. `prose_reviser`
   - 根据三份草稿审查报告改稿，生成最终正文。
   - 产出 `work/final.md`。

12. `state_manifest_keeper`
   - 更新 `state/state.md` 与 `state/player_visible.md`。

13. `memory_archivist`
   - 更新摘要与全文归档。
   - 把 `work/` 复制到 `archive/CxxSyy/`。
   - 清空 `work/`。

## 失败策略

任一步失败时停止流程，不继续执行后续步骤，避免错误扩散到状态和记忆。

## 设计理由

新的阶段划分比早期“GM / Writer / Critic / Rewriter”更贴近实际运行结构：

- 先冻结输入，再召回。
- 规划与审查拆开。
- 写作与修订拆开。
- 状态更新与记忆归档拆开。

这样更适合后期增加：

- 文风模块挂载
- RP 模式
- profile / preset 细分
- 不同 Agent 的 artifact 约束
