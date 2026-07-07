# NovelAgent 实现与验收时间轴归档

> 本文档把 NovelAgent 已实现并经过验证的能力，按“阶段 → 能力 → 关键文件 → 验收方式 → 代表产物”归档。
> 它是事实归档，不是设计文档；设计意图见 [`project_master_guide.md`](project_master_guide.md)，外部对比见 [`reference_projects_analysis.md`](reference_projects_analysis.md)，未来计划见 [`next_step_optimization_plan.md`](next_step_optimization_plan.md)。

归档基准日期：2026-06-11。阶段编号表示交付顺序，不等于自然日期。

---

## 阶段总览

| 阶段 | 主题 | 状态 | 主要验收层级 |
|------|------|------|--------------|
| Phase 0 | 文件驱动多 Agent MVP | 已完成 | mock / 结构 |
| Phase 1 | 闭环稳定化 | 已完成 | mock + deterministic |
| Phase 2 | 恢复与成本控制 | 已完成 | deterministic |
| Phase 3 | RP 基础设施 | 已完成 | deterministic |
| Phase 4 | 卡片迁移基础 | 已完成 | deterministic |
| Phase 5 | 最小操作前端 | 已完成 | live API 验收 |
| Phase 6 | 最终最小真实 LLM smoke | 已完成 | real-LLM smoke |

测试原则（贯穿全程）：非最终、非必要阶段不接入真实 LLM；先 compile/mock/deterministic，再 live，再最小真实 smoke。依据 [`project_master_guide.md`](project_master_guide.md) 第 9 节。

---

## Phase 0 — 文件驱动多 Agent MVP

**实现内容**
- 文件驱动的多 Agent 串行流水线：冻结输入 → 召回 → 规划 → 审查 → 写作 → 修订 → 状态维护 → 归档。
- 模块化 Prompt Assembly：任务 prompt + preset 全局模块 + 文风模块 + Agent 专属模块 + artifact 约束 + 上下文文件 + 步骤元数据。
- 冻结输入快照 `run_snapshot.md`，减少运行中上下文漂移。
- OpenAI 兼容直连运行器、Pi RPC 运行器、Mock 运行器三选一。
- SQLite FTS5 Recall，多故事 workspace 隔离。

**关键文件**
- `app/pipeline.py`、`app/context_builder.py`、`app/prompt_modules.py`
- `app/snapshot.py`、`app/recall.py`、`app/file_io.py`
- `config/pipeline*.yaml`、`config/agents.yaml`、`config/paths.yaml`、`config/models.yaml`
- `app/runners/mock_runner.py`、`app/runners/direct_runner.py`、`app/runners/pi_rpc_runner.py`

**验收方式**
- mock runner 跑通全链路，验证步骤顺序、artifact 路由、归档生成、workspace 隔离。

**代表产物**
- `work/run_snapshot.md`、`work/rough_outline.md`、`work/outline_final.md`、`work/draft.md`、`work/final.md`、`archive/CxxSyy/`

---

## Phase 1 — 闭环稳定化

**实现内容**
- 工作区路径兼容层：遗留 `novel_project/` 路径可映射到实际 `workspaces/*` 与 `stories/*`。
- 修订后再审查：`prose_reviser` 之后自动重跑 `character_guard` / `continuity_guard` / `style_detail_guard`，产出 final 审查报告。
- 扩写后重审：章节扩写结果写回 `work/final.md` 并触发最终审查。
- Story workspace 纯净初始化：自动检测模板根，初始化时重置 `memory/summaries.md`、`memory/index.md`、`memory/fulltext/`，避免 Recall 被旧内容污染。
- 结构化状态推进校验：解析 `state.md` 的 `## Position`，校验章节是否倒退、跳章、场景未推进。
- summary / index 结构化且幂等：同一 scene 覆盖旧块，不再无限追加重复条目。

**关键文件**
- `app/project_paths.py`、`app/story_config.py`
- `app/pipeline.py`（`rerun_final_review_guards`）
- `app/story_workspace.py`、`app/state_tools.py`、`app/archive.py`
- `app/main.py`（`run_post_final_review_sync` 调用）

**验收方式**
- mock + deterministic 单测：clean init、final 重审报告、状态推进校验、summary/index 去重、legacy 路径兼容。

**代表产物**
- `work/reports/final_character.md`、`work/reports/final_logic.md`、`work/reports/final_style_detail.md`

---

## Phase 2 — 恢复与成本控制

**实现内容**
- 运行时策略配置化：超时、重试、退避、降级/改道、resume、cache 全部进 `config/runtime.yaml`。
- run journal + checkpoint：scene 级状态与 step 级状态持久化，支持从已完成 step 续跑。
- prompt cache：基于 agent + scene + 完整上下文哈希的结果缓存。
- DirectRunner 降级/改道：writer/guard 失败后可切换 fallback tier，输出带 `DEGRADED` 标记。
- 运行时按需加载：仅在真正使用 direct runner 时才加载真实模型配置。

**关键文件**
- `config/runtime.yaml`、`app/runtime_config.py`
- `app/run_journal.py`、`app/prompt_cache.py`
- `app/pipeline.py`（resume / checkpoint / cache 接入）
- `app/runners/direct_runner.py`（policy 驱动的 retry / fallback）

**验收方式**
- deterministic 单测：runtime policy 加载、run journal/checkpoint、resume 跳过已完成 step。

**代表产物**
- `work/run_journal/<scene>.json`、`work/run_journal/latest.json`、`work/checkpoints/<scene>.json`、`data/prompt_cache/*.md`

---

## Phase 3 — RP 基础设施

**实现内容**
- 玩家输入结构化解析：mode / target / action / dialogue / intent / metadata。
- 事件驱动状态更新：构造 runtime event，应用到 `state.md` 与 `player_visible.md`，自动推进场景号。
- player_visible / hidden 分层更新：玩家可见侧与后台状态分别写入。
- RP 响应层：GM 旁白 + 角色即时回应，并持久化为 `last_response.json`。
- `rp-turn` CLI。

**关键文件**
- `app/player_input.py`、`app/event_runtime.py`
- `app/main.py`（`run_rp_turn` / `cmd_rp_turn`）

**验收方式**
- deterministic 单测：输入解析、event runtime、state/player_visible 更新、分层响应。

**代表产物**
- `work/player_input.json`、`work/last_event.json`、`work/last_response.json`

---

## Phase 4 — 卡片迁移基础

**实现内容**
- 角色卡载入（JSON 含 BOM 兼容 / 纯文本兜底）。
- Card Semantic IR 推断：identity、visibility（public/hidden）、world_rules、state_variables、triggers、relationships、prompt_hints。
- Runtime Plan 推断：novel vs rp / evented runtime / sub-agent 需求 / persist_state / mount_modules。
- workspace materialization：根据 IR + plan 生成 premise / characters / worldbook / state / player_visible 以及 `data/card_ir.json`、`data/runtime_plan.json`。
- `import-card` CLI。

**关键文件**
- `app/card_migration.py`
- `app/main.py`（`run_import_card` / `cmd_import_card`）

**验收方式**
- deterministic 单测：card IR 推断、runtime plan 推断、materialize、import-card workspace 落地。

**代表产物**
- `data/card_ir.json`、`data/runtime_plan.json`、`lore/premise.md`、`lore/characters.md`、`lore/worldbook.md`、`state/state.md`、`state/player_visible.md`

---

## Phase 5 — 最小操作前端

**实现内容**
- `serve-ui` 最小本地 HTTP 服务。
- API：`/api/stories`（故事列表）、`/api/story?path=`（故事详情 payload）、`/api/rp-turn`（提交 RP 回合）。
- 单页面 UI：story 列表、project/state/player_visible/summaries/index/evaluation/journal/card_ir/runtime_plan/last_response 展示，以及 RP 输入框。
- UI 数据层抽成可测试纯函数：`collect_story_summary` / `load_story_payload` / `run_rp_turn` / `run_import_card`。

**关键文件**
- `app/main.py`（`cmd_serve_ui`、`collect_story_summary`、`load_story_payload`、`_render_index`）

**验收方式**
- deterministic 单测：UI 数据层函数。
- live API 验收：实际启动服务，验证 `/api/stories`、`/api/story`、`/api/rp-turn` 真实响应。

**代表产物**
- 运行中的本地 UI；`/api/story` 返回的聚合 payload；RP 提交后的 state/player_visible 更新

---

## Phase 6 — 最终最小真实 LLM smoke 验收

**实现内容**
- 最小 smoke pipeline：`pipeline_smoke_generate.yaml`（snapshot→recall→scene_planner）与 `pipeline_smoke_critic.yaml`（单 guard）。
- 在所有 compile / mock / deterministic / live 通过后，执行最小真实生成、审查、评估三步。

**关键文件**
- `config/pipeline_smoke_generate.yaml`、`config/pipeline_smoke_critic.yaml`
- `app/runners/direct_runner.py`

**验收方式**
- real-LLM smoke：generation / critic / evaluation 三个最小步骤实际打通外部模型。

**代表产物**
- `evaluation/final_report.md`、smoke scene 归档、`run_journal` 中 `status: completed`

---

## 当前能力总览

- 文件驱动多 Agent 创作闭环：可用、可审查、可归档。
- 审查-修订-再审查闭环：可用。
- workspace 隔离与纯净初始化：可用。
- 状态推进校验、结构化记忆：可用。
- 恢复 / 降级 / 缓存 / journal / checkpoint / resume：可用。
- RP 输入解析 + 事件驱动状态 + 分层响应：基础可用。
- 卡片迁移（IR / plan / materialization / import-card）：基础可用。
- 最小操作前端：可用（live API 已验收）。
- 真实 LLM 最小 smoke：已通过。

## 已知问题与待提升点（live 验收暴露）

- RP 输入解析对畸形请求体脆弱：错误转义会污染 `target`，需要更稳健的解析。
- 旧 `summaries.md` / `index.md` 仍残留早期 mock 混合内容，需要迁移清理。
- RP 响应目前是固定模板，不是真正的多角色/隐藏状态感知生成。
- 卡片迁移字段映射较浅，仅覆盖常见 ST 字段。
- `serve-ui` 尚无正式 API contract 文档。

> 这些问题已纳入 [`next_step_optimization_plan.md`](next_step_optimization_plan.md) 的短期/中期计划。
