# 参考项目分析报告

> 本报告分析 [`参考项目.md`](参考项目.md) 列出的 5 个项目，提炼各自工作流、提示词/上下文结构、优劣势，并归纳 NovelAgent 应吸收的结构模式。
> 配套：事实归档见 [`project_archive_timeline.md`](project_archive_timeline.md)；落地计划见 [`next_step_optimization_plan.md`](next_step_optimization_plan.md)。

调研基准日期：2026-06-11。结论用于指导 NovelAgent 的解耦、隔离、可配置与前端友好优化。

---

## 1. AIRP-MCP-Server

来源：https://github.com/GhostXia/AIRP-MCP-Server

### 项目定位
纯 MCP 协议的角色扮演数据管理服务器。本身不调用 AI、不做 Agent runtime，所有推理与叙事由 MCP Client（Claude Code / Cursor / Pi / Codex）完成。本质是“文件后端 RP 记忆/状态中枢”。

### 核心工作流
1. 导入/维护角色卡与 preset。
2. 创建会话，自动装配 preset + lorebook + state。
3. 追加消息、拉取近期上下文。
4. 按关键词匹配 lorebook。
5. 随剧情更新实时 state。
6. 封卷归档记忆以降 token。
7. 通过 `export_context_bundle` 把富上下文交接给隔离 subagent。

### Prompt / Context / Tool 结构
- **三分法**：Tools（写操作）/ Resources（只读 URI）/ Prompts（工作流辅助，不强制逻辑）。
- 上下文交接以 **bundle 导出** 为核心：`context.md` + 原始 sidecar 数据，未知内容透传不解释。
- 记忆分层：current summary / volume index / archived volumes。
- 状态与对话历史分离，另有 state history 与 gating/checkpoint。

### 优势
- 数据层 / 推理层 / UI 层清晰分离。
- token 管理成熟（归档、摘要、分页、封卷）。
- 上下文 bundle 天然适配多 Agent / subagent 交接。
- 插件命名空间存储，无强 schema，易扩展。

### 劣势 / 风险
- 强依赖 client agent 自律，服务器不强制工作流。
- 无内置 runtime，质量随 client 与 prompt 使用方式波动。
- 文件约定多，规模上去后复杂度上升。

### 对 NovelAgent 的启发
- 把“数据/状态”与“推理”更彻底分离；向 subagent 交接用 **context bundle**，而非把所有上下文硬拼进一个 prompt。
- 记忆三层（summary / index / archived）与现有 `memory/` 高度一致，可据此强化封卷策略。

---

## 2. pi-stage (PI RP Engine)

来源：https://github.com/SDRTIO-bit/pi-stage

### 项目定位
LLM 无关的 RP 运行时，自身不调 LLM，在调用前装配最优上下文。支持 pi.dev 扩展模式与独立 HTTP/WebSocket 模式。

### 核心工作流（单回合）
1. 输入到达。
2. 装配上下文、注入 system prompt。
3. 把 worldbook 编译出的 Skills 注入到 agent 启动前。
4. LLM 用增强后的 prompt 响应。
5. 回合结束更新并持久化 state，重编译 worldbook 材料。

### Prompt / Context 结构（最值得借鉴）
- **5 阶段上下文流水线**：Collect → Prioritize → Schedule → Render → Trace。
- **双预算调度**：不同 prompt 类别各有 token 预算。
- collector 分层：survival-critical / stable / enhanced(retrieved)。
- 降级策略内置：drop / summarize / truncate / compress。
- **worldbook → Skill 编译**：把常驻设定编译成 Skill 文件供模型原生消费。
- 检索：TF-IDF bigram + 关键词兜底（含中文兜底）。

### 优势
- 关注点分离清晰；prompt 预算纪律强。
- prompt 快照带来可观测性。
- card / session 隔离明确（一会话一卡，各自 history/variables/skills）。
- 双部署模式（扩展 / HTTP·WS）。

### 劣势 / 风险
- 自定义流水线机器多，复杂度高。
- TF-IDF + 关键词检索语义弱于 embedding。
- worldbook→Skill 编译在源设定频繁变动时可能脆。
- prompt 装配高度面向 RP，通用性受限。

### 对 NovelAgent 的启发
- 把当前 `ContextBuilder` 升级为 **Collect→Prioritize→Schedule→Render→Trace** 的可配置流水线，引入 token 预算与降级策略。
- 引入 prompt 快照可观测性（每步保存最终 prompt），便于调试与省 token。
- 强化“一故事一运行时”的隔离。

---

## 3. tavern2agent

来源：https://github.com/Xerxes-2/tavern2agent

### 项目定位
把 SillyTavern 角色卡迁移成 pi coding agent 可运行的文字游戏。不是 ST runtime 克隆，而是迁移管线。

### 核心工作流
1. 摄入 ST v1/v2/v3 资源（PNG/WEBP/JPEG/JSON）。
2. 解包并审计卡内容。
3. 构建 **Card Semantic IR**。
4. 推导 **Runtime Plan**。
5. 选择 event packs / state schema / reducers / tools / subagent 角色。
6. 生成 pi 项目并实测验证。

### 关键范式（最值得借鉴）
- **prompt 描述世界，domain event 改变世界**。
- 状态更新必须经 domain event + reducer。
- 卡被当作“结构化游戏设计”，而非 prompt 包：提取设定、规则、触发、隐藏信息、多 NPC、经济、战斗、骰子、任务、时间。
- 默认剥离 ST 表现/运行时补丁：HTML 状态栏、宏补丁、COT 标签、JSON Patch 风格。
- 纯静态卡可坍缩为 prompt-only；任何可变即默认 evented runtime。

### 产物结构
`agents/preset.json`、`agents/gm-*.md`、`data/card-ir.json`、`data/runtime-plan.json`、`engine/*`、`tools/registry.ts`、`skills/start-game/SKILL.md`。难卡上要求先展示 runtime plan / state schema / event catalog / tool list / subagent boundaries 再编码。

### 优势
- 叙事 prompt 与状态变更彻底分离。
- 复杂卡机制可审计、可重跑、可迁移。
- 支持秘密 / 阵营 / 多 NPC 而不泄露状态。
- 静态场景可退回 prompt-only，弹性好。

### 劣势 / 风险
- 比直接 prompt 转换复杂得多。
- 依赖语义提取与规划质量。
- event packs / reducers / tooling 需要额外工程。
- 刻意不保真 ST 行为。

### 对 NovelAgent 的启发
- NovelAgent 的 `card_ir` / `runtime_plan` 直接对标本项目，应补全“分档（prompt-only / evented）”与“event+reducer”范式。
- 引入 `event catalog` + `state schema` + `reducer` 作为 RP 模式正式契约，替换当前固定模板响应。
- 迁移产物结构（`data/card_ir.json` / `data/runtime_plan.json`）已对齐，可继续向 event pack 扩展。

---

## 4. neuro-book（重点参考，近似同构）

来源：https://github.com/notnotype/neuro-book

### 项目定位
面向长篇小说创作的本地 AI 工作台：文件化 workspace、Markdown Studio、剧情结构管理、多 Agent 写作流程，也支持 ST 卡迁移。

### Workspace 模型
- 文件式 Project Workspace 为核心。
- 关键目录：`lorebook/`、`manuscript/`、`simulation/`、`reference/` 加项目配置。
- markdown 优先、人类可读，设定/正文/状态/外部参考并列。

### 写作工作流
- 分阶段而非单聊天循环：检索、研究、写作、模拟、leader 角色分离。
- sidecar 运行处理检索/反思/记忆维护/状态清理，只把有用产出合并回主线。
- RP 迁移用 inspect → unpack → import 路径，保留原卡同时把稳定内容搬入 lorebook。

### Prompt / 多 Agent 结构
- harness 支持多供应商、工具调用、append-only session tree、HITL、runtime profile、上下文压缩、摘要、生命周期 hook。
- 角色专门化：leader / writer / retrieval / researcher / simulator leader / actor / rp.writer。
- profile 定义工具权限、schema、system prompt、动态上下文、压缩/摘要、hooks。
- TSX Profiles 提供结构化上下文模板层（system / history / dynamic context / reminders / imports / skills）。

### 优势
- canon / 草稿 / 模拟状态强分离。
- markdown 文件化利于审阅、版本化、增量世界构建。
- 角色专门化减少“一个模型干所有事”的失败模式。
- sidecar 处理让主线上下文更干净。

### 劣势 / 风险
- 体系较复杂：workspace 约定、profile、hook、多角色，配置开销大。
- 长篇质量依赖良好项目结构与 profile 设计。
- 偏向高级用户与本地部署。
- 章节结构工具更多隐含在 workspace 文件里，而非独立 plot 引擎。

### 对 NovelAgent 的启发（最高优先借鉴）
- NovelAgent 与本项目几乎同构，应直接吸收其 **workspace 目录分层**（lore / manuscript / simulation / reference）与 **角色 profile 体系**。
- 引入 sidecar 处理（检索/反思/记忆维护）以保持主线上下文干净、省 token。
- 用 profile 统一定义工具权限、system prompt、动态上下文、压缩策略，提升可配置与可插拔度。

---

## 5. TauriTavern（重点参考，成熟生态）

来源：https://github.com/Darkatse/TauriTavern

### 项目定位
把 SillyTavern 移植为 Tauri v2 + Rust 原生应用，保留上游前端体验，前端同步至 SillyTavern 1.16.0，通过模块化 Tauri 注入层集成。

### 架构
- 前端：上游 ST 风格 HTML/CSS/JS + Tauri bridge/interception。
- 后端：Rust `src-tauri`，分 presentation / application / domain / infrastructure。
- host 层：稳定平台 ABI（`window.__TAURITAVERN__`）+ trace headers。
- 模块按关注点分组：context / kernel / services / adapters / routes，组合根 bootstrap。

### Prompt / Profile / Module 结构（对前端友好最值得借鉴）
- 最可复用模式：**稳定 host 契约 / 纯 kernel 逻辑 / 带副作用 adapter** 三分。
- prompt/profile 不硬编码进 UI，而是经一个窄 ABI 路由。
- “前端 + host kernel”模型很适合 agent runtime：UI 保持 ST 风格，执行/工具/请求在窄接口之后。
- 按能力域路由：settings / resources / characters / chat / AI。

### 优势
- 保留熟悉的 ST 用户体验。
- 关注点分离使 runtime 行为易维护。
- 跨平台桌面支持；多供应商（OpenAI / Claude / Gemini / OpenAI 兼容）。
- trace headers 提供可观测性。

### 劣势 / 风险
- 多语言大栈，构建/维护复杂度高。
- 依赖自定义 bridge 与注入层，集成摩擦。
- 受上游 ST 形态约束。

### 对 NovelAgent 的启发
- 前端坚持“操作/展示/调试层”定位：UI 只改配置文件、不成为 canonical state 真相源（与总指导一致）。
- 用窄 host 契约 / routes / adapters 组织前后端交互，便于演进与替换。
- 引入 trace id 便于调试 prompt 流与工具调用。

---

## 综合提炼：NovelAgent 应吸收的结构模式

把五个项目的共性收敛为 6 条结构模式，并对照 5 条优化原则（简洁目录 / 项目间隔离 / 高解耦可插拔 / 高可配置 / 前端友好）：

1. **数据层与推理层分离**（AIRP / pi-stage / TauriTavern）
   - 文件/状态/检索是数据层；prompt 装配与模型调用是推理层；UI 是展示层。
   - 对应原则：高解耦、前端友好。

2. **prompt assembly 与 runtime state 分离**（tavern2agent / pi-stage）
   - prompt 描述世界，event + reducer 改变世界。
   - 对应原则：高解耦、可配置。

3. **Card IR + Runtime Plan 作为迁移中间层**（tavern2agent）
   - 卡片不直接转 prompt，先 IR 再 plan 再落地，可审计可重跑。
   - 对应原则：项目间隔离、可迁移。

4. **上下文装配流水线化 + 预算/降级**（pi-stage）
   - Collect→Prioritize→Schedule→Render→Trace + token 预算 + drop/summarize/truncate/compress。
   - 对应原则：可配置、省 token。

5. **角色 profile + sidecar 处理**（neuro-book）
   - 角色专门化（leader/writer/retrieval/...），sidecar 维护记忆与状态，保持主线干净。
   - 对应原则：高解耦可插拔、可配置。

6. **窄前端契约**（TauriTavern）
   - 前端经稳定 ABI/routes 与后端交互，只改配置不持有真相源。
   - 对应原则：前端友好、高解耦。

### 提示词冲突取舍原则
当 NovelAgent 现有提示词与参考项目对应提示词冲突时，**优先采用参考项目的提示词做实现**。具体优先级：
1. tavern2agent —— RP / 卡片迁移 / event 范式相关提示词。
2. neuro-book —— 长篇写作 / 角色 profile / sidecar 相关提示词（与本项目最同构）。
3. pi-stage —— 上下文装配 / worldbook-skill / 预算降级相关提示词。
4. AIRP-MCP-Server —— 记忆封卷 / context bundle 相关提示词。
5. TauriTavern —— 前端契约 / 路由组织相关约定。

落地时保留 NovelAgent 的 artifact 契约与文件路径约定，仅替换提示词内容与结构，不破坏现有 pipeline 的 I/O 边界。
