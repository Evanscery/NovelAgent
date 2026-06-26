# NovelAgent 阶段总结报告

> 基准日期：2026-06-24。本文是事实性阶段归档，描述项目已落地并验证的能力、核心架构、配置体系、测试现状与下一步主线。
> 设计意图见 [`project_master_guide.md`](project_master_guide.md)，外部对比见 [`reference_projects_analysis.md`](reference_projects_analysis.md)，未来计划见 [`next_step_optimization_plan.md`](next_step_optimization_plan.md)，实现时间轴见 [`project_archive_timeline.md`](project_archive_timeline.md)，已知问题见 [`known_issue.md`](known_issue.md)。

---

## 一、项目定位

NovelAgent 是一套**文件驱动、可审查、可归档、可扩展**的多 Agent 小说创作 / RP 互动系统。一句话定位：

> 用 Python 编排多 Agent 流水线 + 文件系统作唯一真相源 + SQLite 做召回 + 可选真实 LLM 做生成与审查，最终演进为「自动写小说 ↔ 玩家可互动 RP ↔ 可迁移酒馆卡」的统一系统。

设计总原则只有一条——**最大程度利用 agent 能力完成任务，而非为"看起来高级"引入无意义复杂度**：只有某项设计确有必要、确能稳定提升效果/效率/可维护性/可迁移性/可运维性时，才进入实现。

八个核心目标：自动小说写作、玩家互动 RP、高效省 token、写作效果好、可迁移酒馆卡、高可配置、高可插拔、可持续演进（单故事流水线 → 多故事并行 → RP → 角色自治 → 沙盒）。

---

## 二、阶段总览（已落地并验证）

| 阶段 | 主题 | 状态 | 验收层级 |
|------|------|------|---------|
| Phase 0 | 文件驱动多 Agent MVP | ✅ | mock/结构 |
| Phase 1 | 闭环稳定化（扩写后重审、修订后再审查、纯净初始化、结构化状态/记忆） | ✅ | mock+deterministic |
| Phase 2 | 恢复与成本控制（runtime 配置化、journal/checkpoint/resume、prompt cache、降级改道） | ✅ | deterministic |
| Phase 3 | RP 基础设施（玩家输入解析、事件驱动状态、player_visible/hidden 分层、分层响应） | ✅ | deterministic |
| Phase 4 | 卡片迁移基础（Card IR、Runtime Plan、materialization、import-card） | ✅ | deterministic |
| Phase 5 | 最小操作前端（serve-ui + `/api/*`） | ✅ | live API |
| Phase 6 | 最小真实 LLM smoke（generate/critic/evaluate 三步打通外部模型） | ✅ | real-LLM |
| 前端工作台重构 | Vite+Vue3+TS 多标签工作台，端到端 Playwright 验证 | ✅ | 2026-06-17 |
| G1 角色卡展示前端 | ST 风格正则→HTML 渲染引擎（findRegex→$1..$N） | ✅ | 2026-06-14 |
| G2 Agent Skill 系统 | 内置 `dice_roll`（确定性，零 LLM），MCP 预留接口 | ✅ | 2026-06-14 |
| G3 通用导入管线 | 酒馆卡专用 + 剧本/设定/小说通用，可降级 | ✅ | 2026-06-14 |
| G4 一键启动 | `serve` + `start.bat`/`start.sh`，YAML 驱动 | ✅ | 2026-06-14 |
| RP 反馈模型重构 | 可插拔 `RpMode`（immersive/trpg）+ per-workspace `rp.yaml` + GM/玩家掷骰协议 | ✅ | 2026-06-19/23 |
| 小说阅读闭环 | 作品阅读页 + 只读 `/api/novel*` + 章↔场景组装 + 概览作品主页化 | ✅ | 2026-06-19/23 |

**测试现状**：Python 套件 **72 passed**（deterministic，不接真实 LLM）；前端 `vue-tsc` 类型检查通过、`vite build` 成功、Vitest store 单测通过；HTTP 端到端 smoke 与 Playwright 浏览器验证均绿、console 零错误。

---

## 三、核心架构与分工

- **Python 编排器** (`app/`)：读配置 → 装配上下文 → 调用运行器 → 写产物 → 归档。
- **运行器** (`app/runners/`)：`mock_runner`（不花额度干跑）/ `direct_runner`（OpenAI 兼容直连，policy 驱动重试/降级/改道）/ `pi_rpc_runner`（可选 Pi RPC）三选一。
- **SQLite Recall** (`data/recall.db`)：FTS5 索引历史摘要/索引/正文全文，生成召回报告，多故事 workspace 隔离。
- **文件系统**：唯一真相源——`workspaces/<story>/{lore,state,memory,work,archive,novels,data,front,...}` 自包含、可迁移、可并行。
- **Git**：保存每轮变化，提供回滚与差异审计。
- **上下文装配流水线** (`app/context_builder.py`)：Collect → Prioritize → Schedule → Render → Trace 五阶段，带 token 预算与 section 级 keep/truncate/drop/compress 策略，每步落盘 prompt snapshot + trace。

### 主创作流水线（13 步串行）

```text
run_snapshotter → recaller → scene_planner
→ outline_worldbook_guard → outline_knowledge_guard → outline_integrator
→ prose_writer → character_guard → continuity_guard → style_detail_guard
→ prose_reviser → state_manifest_keeper → memory_archivist
```

bootstrap 系列（`theme_bootstrapper`/`cast_designer`/`worldbook_builder`/`arc_planner`/`state_initializer`）用于 `init-story`，`book_evaluator` 用于 `evaluate-book`。

### Prompt 组装顺序

任务 prompt → preset 全局模块 → preset 文风模块 → 该 Agent 专属模块 → `agents.yaml` 额外挂载模块 → 输出 artifact 约束 → 输入文件上下文 → 本轮步骤元数据。任务职责与通用规则分离、文风/模式可替换、输出格式统一复用、上下文文件靠后便于缓存。

---

## 四、关键子系统现状

- **RP 系统**：从"固定模板复读"重构为可插拔策略——`ImmersiveMode`（叙述推进）与 `TrpgMode`（判定→掷骰→GM 指令）。状态推进由 `event_reducers` 负责，mode 只 narrate，二者解耦。支持 GM 侧主动判定掷骰（确定性 seed）与玩家侧掷骰 `resolve` 多步协议；per-workspace `rp.yaml` 差异化配置；默认确定性、零 LLM。真实 LLM GM（`gm.runner=llm`）为待办占位。
- **卡片迁移 / 通用导入**：`import-card`（酒馆卡专用 → Card Semantic IR → Runtime Plan → materialize）+ `import`（通用分发器，剧本/设定/小说走通用管线，未实现专用子管线时降级）。所有来源收敛到同一 `card_ir`-兼容 IR + workspace。
- **前端工作台**：Vite+Vue3+TS+Pinia 单页应用，多标签（概览/角色卡/RP/Prompt/配置/文件/运行/作品），标签可拖拽重排，暗亮主题，新建项目向导，脏标记保存，mock run job 轮询，ST 风格正则 widget 渲染，作品阅读页（书籍版式）。只经 `/api/*` 窄契约访问后端，不持有 canonical state。
- **技能系统**：内置 Python `SkillRegistry`（`dice_roll`，`NdM` 纯函数，seed 可复现，零 LLM），GM 在 `agents.yaml` 声明 `skills:[dice_roll]`。MCP 作为未来外部通道统一在同一抽象下，暂不接入（避免无谓复杂度）。
- **一键启动**：`serve` 读 `config/server.yaml`（host/port/CORS/IP 白名单/open_browser），同时托管 `/api/*` 与前端 `web/dist`；`start.bat`/`start.sh` 首次自动构建前端。默认仅本地监听（127.0.0.1），默认端口 8766。

---

## 五、配置体系

四层优先级 `global < profile < story < run override`（共享默认值的同时允许单个故事深度定制）。核心配置文件：`config/{agents,pipeline×N,models,runtime,recall,paths,server}.yaml`；每工作区自带 `presets/`、`modules/`、`prompts/`、`rp.yaml`。运行时策略（timeout/retry/backoff/降级/resume/cache/section 预算）全部配置化。

可配置对象：prompt modules、preset、profile、agent 列表、pipeline 步骤与顺序、模型 tier 分配、重试/退避/超时、Recall 策略、扩写策略、RP 模式策略、section 级上下文预算。

---

## 六、已知问题与下一步

**已知问题**（来自 live/A 测，详见 [`known_issue.md`](known_issue.md)）：
- RP 真实 LLM GM 未接入（`gm.runner=llm` 占位抛 NotImplementedError）
- RP 响应的 player/debug 双层分离与 `player_visible` 的 Hidden 投影仍待补
- 前端发起 `write-book`（真实 LLM 多章）仍延后 CLI
- 旧 `summaries.md`/`index.md` 残留待清理迁移
- 卡片字段映射较浅；PNG 卡内嵌读取、COC 专用子管线未做

**下一步主线**（详见 [`next_step_optimization_plan.md`](next_step_optimization_plan.md)）：
- 中期 M3 卡片完整 bootstrap、M4 角色 profile 体系、M5 workspace 分层对齐、M6 前端扩展（调试页 / Inspector / 可视化模块挂载）
- 长期 L1 角色独立 sub-agent、L2 并行角色响应、L3 记忆封卷+检索升级、L4 配置工作台、L6 沙盒 event pack
- 待审批 IP-005（技能选型：内置 registry 优先，MCP 预留）已采纳方向

**优先级对齐**：当前进度已让基础闭环、最小前端、RP 基础、卡片迁移基础都落地，边际收益从"有没有"转为"按参考项目范式深化"，故重点上移为 contract 化 + 扩展页（S4/M6）与 event/reducer/profile 驱动深化（M2/M3/M4）。落地顺序建议：G4 → G1 → G2 → G3。

---

## 七、一句话结论

NovelAgent 已证明「文件驱动 + 多 Agent 串行流水线 + 模块化 prompt + 章节级归档」这条路可行。要真正达到「玩家能互动 / 成本可控 / 效果稳定 / 可迁移酒馆卡 / 高可配置 / 高可插拔 / 环境隔离 / 上下文隔离 / 可恢复可暂停」，还需补齐五大能力层：闭环质量控制、事件驱动状态、前端交互承接、卡片语义迁移、配置与恢复。当前最该优先做的是把闭环补齐 → 最小前端与配置页 → RP → 酒馆卡迁移，避免在"能跑但不稳"上堆复杂度。
