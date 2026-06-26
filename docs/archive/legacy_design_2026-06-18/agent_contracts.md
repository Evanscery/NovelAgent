# Agent 契约

## 通用规则

1. 每个 Agent 只处理自己的职责。
2. 信息不足时必须说明缺口，不得编造。
3. 审查类 Agent 只报告问题，不直接改正文。
4. 写作类 Agent 只写正文或细纲，不更新状态。
5. State 类型 Agent 只根据最终正文更新状态。
6. Archive 类型 Agent 只做归档、摘要和索引维护。
7. 所有 Agent 的通用规则、文风规则和输出格式优先由模块提供，不在任务 prompt 中重复堆叠。

## `run_snapshotter`

- 输入：玩家输入、状态、玩家可见状态、当前大纲、记忆索引。
- 输出：`work/run_snapshot.md`。
- 类型：本地步骤。
- 作用：冻结本轮输入事实，供后续所有 Agent 共享。

## `recaller`

- 输入：冻结快照、记忆索引、历史摘要、SQLite 检索结果。
- 输出：`work/recall_report.md`。
- 禁止：编造历史事实。

## `scene_planner`

- 输入：冻结快照、召回报告、设定、总大纲、当前弧线。
- 输出：`work/rough_outline.md`。
- 禁止：写正文。

## `outline_worldbook_guard`

- 输入：世界观、地点、冻结快照、初版场景规划。
- 输出：`work/reports/outline_worldbook.md`。
- 检查：世界观规则、设定硬伤、时间地点物理逻辑。

## `outline_knowledge_guard`

- 输入：角色设定、冻结快照、初版场景规划。
- 输出：`work/reports/outline_knowledge.md`。
- 检查：角色认知边界、后台真相泄露、信息越权。

## `outline_integrator`

- 输入：冻结快照、初版场景规划、两份细纲审查报告、核心设定。
- 输出：`work/outline_final.md`。
- 禁止：无视关键审查问题。

## `prose_writer`

- 输入：冻结快照、最终细纲、角色设定、文风设定。
- 输出：`work/draft.md`。
- 禁止：改剧情结构、更新状态、解释创作意图。

## `character_guard`

- 输入：角色设定、冻结快照、最终细纲、正文草稿。
- 输出：`work/reports/draft_character.md`。
- 检查：OOC、关系状态、人物动机、说话方式。

## `continuity_guard`

- 输入：世界观、冻结快照、记忆索引、最终细纲、正文草稿。
- 输出：`work/reports/draft_logic.md`。
- 检查：连续性、因果、时间地点、事实错误、物品状态。

## `style_detail_guard`

- 输入：文风设定、最终细纲、正文草稿。
- 输出：`work/reports/draft_style_detail.md`。
- 检查：AI 腔、泛泛表达、动作细节、手部/体位/物品连续性、文风一致性。

## `prose_reviser`

- 输入：文风设定、最终细纲、正文草稿、三份草稿审查报告。
- 输出：`work/final.md`。
- 禁止：添加新剧情。

## `state_manifest_keeper`

- 输入：旧状态、玩家可见状态、最终细纲、最终正文。
- 输出：`state/state.md` 与 `state/player_visible.md`。
- 禁止：引入正文没有发生的新事实。

## `memory_archivist`

- 输入：状态、冻结快照、最终细纲、最终正文。
- 输出：记忆摘要、全文归档、归档目录。
- 类型：本地归档步骤。
- 禁止：改正文。
