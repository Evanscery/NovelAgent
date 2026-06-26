# NovelAgent 下一步实现与全方位优化计划

TODO:
1.兼容前端卡：显示角色卡的前端
2.agent的skill系统，允许MCP或统一格式（nodejs？js？需调研，不要为了增加复杂度而增加复杂度，选型需确有必要、确有优势）为agent提供skill，比如为gm提供掷骰的skill（DND，1d10,1d100，as example）
3.兼容酒馆卡=>扩展到兼容任意形式任意格式的剧本、世界观设定、小说等等。酒馆卡走特殊管线，其他走通用管线（后期可以专门化，比如COC的剧本走COC处理管线，酒馆走酒馆管线，未实现专用管线就降级到通用管线，但也能跑）

> 本计划综合：当前实现事实 [`project_archive_timeline.md`](project_archive_timeline.md)、参考项目分析 [`reference_projects_analysis.md`](reference_projects_analysis.md)、项目总指导 [`project_master_guide.md`](project_master_guide.md)。
> 基准日期：2026-06-11。

## 0. 优化总原则

所有优化必须同时服务以下五条原则：

1. **简洁工程目录**：减少散乱文件，目录语义清晰。
2. **高项目间隔离**：每个 story/workspace 自包含，互不污染。
3. **高解耦合度（模块可插拔）**：agent / runner / collector / reducer / 前端视图均可替换。
4. **高可配置度**：行为由配置/profile 驱动，而非改代码。
5. **前端交互友好**：前端只做操作/展示/调试，经窄契约访问后端。

**提示词冲突取舍**：当现有提示词与参考项目冲突时，优先采用参考项目提示词（取舍优先级见 [`reference_projects_analysis.md`](reference_projects_analysis.md) “提示词冲突取舍原则”）。

---

## 1. 短期（1-2 个迭代）：修缺口、补稳健性、立目录规范

聚焦 live 验收暴露的真实问题与低成本高收益项。

### S1. 修正 RP 输入解析脆弱性
- 问题：畸形请求体会把转义文本混进 `target`（live 验收发现）。
- 做法：`app/player_input.py` 增加输入规范化与字段边界校验；`/api/rp-turn` 增加请求体校验与错误返回。
- 原则：高解耦、前端友好。

### S2. 迁移清理旧记忆格式
- 问题：旧 `summaries.md` / `index.md` 残留 mock 混合内容。
- 做法：提供一次性迁移工具，把历史块归一到结构化格式；纳入 `import-card` / `init-story` 之外的独立 maintenance 命令。
- 原则：项目间隔离、简洁目录。

### S3. card import 字段映射加固
- 已修：JSON BOM 兼容。
- 续做：扩展 ST v2/v3 常见字段（`data.*`、`character_book`、`alternate_greetings`）映射；纯文本兜底保留。
- 原则：可迁移、可配置。

### S4. serve-ui API contract 文档化
- 做法：新增 `docs/ui_api_contract.md`，固定 `/api/stories`、`/api/story`、`/api/rp-turn` 的请求/响应 schema。
- 原则：前端友好、高解耦。

### S5. 目录规范立约
- 做法：在 `docs/architecture.md` 增补“目录规范”小节，明确 `app/` 子分层意图（runners / 未来 collectors / reducers / migration）、`config/`、`workspaces/<story>/`、`data/` 边界。
- 原则：简洁目录、项目间隔离。

### 验收
- 全部 deterministic 单测通过；live 重测 `/api/rp-turn` 畸形输入被拒；不接入真实 LLM。

---

## 2. 中期（3-5 个迭代）：把“基础版”深化为成熟系统

### M1. 上下文装配流水线化（借鉴 pi-stage）
- 把 `app/context_builder.py` 升级为 **Collect → Prioritize → Schedule → Render → Trace**。
- 引入 token 预算与降级策略（drop / summarize / truncate / compress），配置进 `config/runtime.yaml`。
- 每步保存 prompt 快照到 `work/prompt_snapshots/`，提升可观测性。
- **当前进展（2026-06-12）**：第一阶段已完成——现有 `ContextBuilder` 已显式拆成 collect/prioritize/schedule/render/trace 五阶段，并开始为每个步骤落盘 prompt snapshot + trace JSON；第二阶段已完成——加入 `default_max_chars` / `agent_max_chars` / `section_strategies` 配置，schedule 阶段开始基于 section 级策略做 keep / truncate / drop，并把预算决策写入 trace；第三阶段已完成——collector 分类显式化为 survival/retrieved/working/stable/memory/enhanced，并新增 `compress` 策略与 collectors summary trace。剩余待做：更强的 summarize/compress 质量策略、前端 trace 调试页。
- 原则：可配置、省 token、高解耦可插拔。

### M2. RP 响应升级为分层生成（借鉴 tavern2agent + neuro-book）
- 用 **event catalog + state schema + reducer** 替换当前固定模板响应。
- narrator / GM / character / hidden-state-aware 分层，hidden 状态严格不入 player_visible。
- 提示词冲突时采用 tavern2agent 的 GM / event 提示词范式。
- **当前进展（2026-06-14）**：第一阶段已完成——RP runtime 已从“单文件硬编码”拆成显式的 event catalog（`app/event_catalog.py`）+ reducer registry（`app/event_reducers.py`）+ response builder registry（`app/event_response_builders.py`），`RuntimeEvent` 抽到 `app/event_types.py` 以打破循环依赖；`build_runtime_event` 现在按 intent 解析到 catalog 条目并记录 `catalog_key`，未知 intent 降级到 `fallback_turn`。剩余待做：state schema 形式化、hidden-state-aware 分层、按 tavern2agent 范式重写 GM/character 提示词。
- 原则：高解耦、可配置、RP 互动深度。

### M3. 卡片迁移升级为完整 bootstrap（借鉴 tavern2agent）
- `card_ir` 扩展 event/state/trigger 的结构化抽取。
- `runtime_plan` 产出 event pack 选择与 reducer 草案。
- materialize 时生成 `data/event_catalog.json`、`data/state_schema.json`。
- 原则：可迁移、项目间隔离。

### M4. 角色 profile 体系（借鉴 neuro-book）
- 引入 `config/profiles/*.yaml`：定义每个 agent 的工具权限、system prompt、动态上下文、压缩策略。
- pipeline 通过 profile resolver 解析，agent/pipeline 步骤可插拔。
- 原则：高解耦可插拔、高可配置。

### M5. workspace 目录分层对齐（借鉴 neuro-book）
- 把 `workspaces/<story>/` 内部对齐为 lore / manuscript / simulation / reference / state / memory / work / archive / data。
- 提供迁移脚本平滑过渡旧结构。
- 原则：简洁目录、项目间隔离。

### M6. 前端扩展
- 新增导入确认页（展示 card_ir / runtime_plan 后再落地）、配置页（编辑 preset/profile/pipeline）、调试页（journal/prompt 快照）。
- 仍只改配置文件，不持有 canonical state。
- 原则：前端友好、高可配置。

### 验收
- 每项先 deterministic 验证；UI 经数据层纯函数测试；仅在阶段末做一次最小真实 smoke。

---

## 3. 长期（6+ 个迭代）：面向总指导最终形态

- L1. 角色独立 sub-agent（独立认知边界）。
- L2. 并行角色响应器。
- L3. 长期记忆封卷与检索升级（借鉴 AIRP 封卷 + 可选 embedding）。
- L4. 前端配置工作台：profile / preset / agent / pipeline 全可视化编辑。
- L5. 卡片迁移确认工作台。
- L6. 沙盒 / 多 NPC / faction / quest / economy 的 event pack。

原则映射：以上均需满足解耦可插拔与项目间隔离；sub-agent 与并行响应优先保证上下文隔离。

---

## 4. 优化维度矩阵

| 优化项 | 影响目标 | 参考来源 | 复杂度 | 前置依赖 |
|--------|----------|----------|--------|----------|
| S1 RP 解析加固 | 质量/RP | pi-stage | 低 | 无 |
| S2 记忆格式迁移 | 隔离/质量 | AIRP | 低 | 无 |
| S3 卡片字段加固 | 迁移 | tavern2agent | 低 | 无 |
| S4 UI contract | UI/解耦 | TauriTavern | 低 | 无 |
| S5 目录规范 | 简洁目录 | neuro-book | 低 | 无 |
| M1 上下文流水线 | 省 token/可配置 | pi-stage | 中 | S5 |
| M2 RP 分层生成 | RP 深度 | tavern2agent | 中高 | S1 |
| M3 卡片完整 bootstrap | 迁移 | tavern2agent | 中高 | S3, M2 |
| M4 角色 profile 体系 | 解耦/可配置 | neuro-book | 中 | S5 |
| M5 workspace 分层 | 简洁/隔离 | neuro-book | 中 | S5 |
| M6 前端扩展 | 前端友好/可配置 | TauriTavern | 中 | S4 |
| L1 角色 sub-agent | RP 深度/隔离 | neuro-book, pi-stage | 高 | M2, M4 |
| L2 并行角色响应 | RP 深度 | pi-stage | 高 | L1 |
| L3 记忆封卷/检索 | 省 token/质量 | AIRP | 中高 | M1 |
| L4 配置工作台 | 可配置/前端 | TauriTavern | 高 | M4, M6 |
| L5 迁移确认工作台 | 迁移/前端 | tavern2agent | 高 | M3, M6 |
| L6 沙盒/event pack | RP 深度 | tavern2agent | 高 | M2, M3 |

---

## 5. 与总指导优先级的对齐说明

总指导 [`project_master_guide.md`](project_master_guide.md) 的推荐顺序是“先闭环、再前端最小、再 RP、再卡片迁移”。当前实现已经把闭环、最小前端、RP 基础、卡片迁移基础都落地，因此本计划相对总指导做了如下**有意调整**：

- 闭环已稳，短期不再投入闭环本身，而是补 **live 验收暴露的脆弱点**（S1-S2）。
- 前端最小版已完成，故前端工作上移为 **contract 化 + 扩展页**（S4 / M6），而非从零做最小页。
- RP 与卡片迁移已有基础版，故重点从“有没有”转为“**深化为 event/reducer 与 profile 驱动**”（M2 / M3 / M4）。

调整原因：当前进度改变了边际收益分布——继续堆基础闭环收益递减，而把已实现的基础版按参考项目范式深化，收益更高，且更直接服务五条优化原则。

---

## 6. 新增目标（2026-06-14 提出）

以下四项是用户在 M2 推进期间新增的目标。它们都必须服从既有五条优化原则与“最小 LLM 调用 / 非最终非必要不接真实 LLM”的测试原则，并且**不为增加复杂度而增加复杂度**：每一项的技术选型都要求“确有必要、确有优势”。

### G1. 兼容前端卡：角色卡展示前端
- 目标：前端能直接展示一张角色卡（卡片视图），而不只是看 raw `card_ir.json` / `runtime_plan.json`。
- **关键认知（2026-06-14）**：酒馆角色卡前端的本质是「正则扩展脚本」——`findRegex` 从消息/状态文本里抓变量，`replaceString`（HTML+JS 模板）用 `$1..$N` 替换后渲染成组件（样例见 `docs/st-char-front.json`）。因此 G1 的核心不只是静态字段展示，而是一个**正则 → HTML 前端渲染引擎**。
- 做法：
  - 后端在 `/api/story` 已返回 `card_ir` / `runtime_plan` 的基础上，新增 `/api/card?path=...` 聚合视图：把 `card_ir` 规整为前端友好的字段（名称、人设、开场白、备选开场白、世界规则），并对 workspace `front/` 目录下的 ST 风格正则脚本逐个应用到 `player_visible` + `last_response`，输出渲染后的组件 HTML。
  - 前端新增「角色卡」与「前端组件（正则渲染）」两个面板。
  - 不持有 canonical state，纯展示；`card_ir` 字段一律 HTML 转义，正则脚本模板按 ST 语义保留（与酒馆一致）。
- **当前进展（2026-06-14）：已完成**——新增 `app/card_front.py`（`FrontScript` / `load_front_scripts` / `parse_front_script` / `apply_front_script` / `render_front_widgets` / `build_card_view` / `render_card_view_html`），支持 `$1..$N`（含两位数分组，`$12` 不被 `$1` 截断）、`/pattern/flags` 形式、`utf-8-sig`；后端新增 `load_card_view_payload` 与 `/api/card`；前端 index 增加两个面板；deterministic 测试覆盖含直接渲染 `docs/st-char-front.json` 样例。
- 依赖：S3（卡片字段加固，已完成）、S4（API contract，已完成）、M6（前端扩展）。
- 原则：前端友好、高解耦（展示层不碰真相源）。

### G2. Agent Skill 系统（为 Agent 提供可插拔技能）
- 目标：允许为某个 agent 挂载「技能」，例如为 GM 提供掷骰技能（DnD 风格：`1d10`、`1d100` 等）。
- **选型调研结论（确有必要、确有优势，避免无谓复杂度）**：
  - **第一阶段：内置 Python skill registry（确定性、零外部依赖）**——掷骰这类技能本质是纯函数（`NdM` → 结果），用 Python 实现既最小、又天然满足“最小 LLM 调用 / 可 deterministic 测试”。**不引入 Node.js/JS 运行时**，因为为一个掷骰函数引入第二套语言运行时属于“为复杂度而复杂度”，确无优势。
  - **第二阶段（仅在确有必要时）：MCP 作为外部 skill 协议**——当出现“技能需要跨进程、跨语言、可被其他客户端复用、或由第三方提供”的真实需求时，再以 MCP 接入。理由：MCP 是已被参考项目（AIRP-MCP-Server）验证的 tool/resource/prompt 标准，比自造 JS 插件协议更通用、更解耦；但在只有内置确定性技能的当下，MCP 属于过度设计，故降级为「预留接口、暂不接入」。
  - 结论：**默认走内置 skill registry；MCP 作为未来可选外部通道，统一在同一个 skill 抽象下挂载**，二者对 agent 暴露同一调用契约。
- 做法：
  - 新增 skill 抽象：`skill_name`、`invoke(args) -> result`、`describe()`。
  - 内置技能：`dice_roll`（支持 `NdM`、加值、多次掷骰，结果可复现需显式 seed，否则非确定，仅在 GM 响应时调用）。
  - 在 `config/agents.yaml` / profile 中声明每个 agent 可用的 skills（如 GM → `dice_roll`）。
  - event runtime / response builder 在需要时调用 skill，并把调用记录写入 trace / response（可审计）。
- **当前进展（2026-06-14）：第一阶段已完成**——新增 `app/skills.py`（`Skill` 协议、`SkillResult`、`DiceRollSkill`、`SkillRegistry`、`build_default_registry`、`resolve_agent_skills`、`apply_gm_skills`）；`config/agents.yaml` 新增 `gm` agent 并声明 `skills: [dice_roll]`；`run_rp_turn` 在 GM 被授予技能且玩家行动含骰子表达式（如 `1d20`/`1d100`）时执行掷骰，结果挂在 `response.skill_invocations`（可审计）。掷骰是确定性纯函数，提供 seed 即可复现，**不调用 LLM**。MCP 作为未来外部通道预留接口、暂不接入（见 IP-005）。剩余待做：更多内置技能、profile 权限装配（M4 后）、MCP 外部通道。
- 依赖：M2（event/response 已 registry 化，便于挂载）、M4（profile 体系，用于声明权限）。
- 原则：高解耦可插拔、高可配置、最小 LLM 调用（技能默认是确定性函数）。

### G3. 通用剧本/设定/小说导入（酒馆卡走专用管线，其他走通用管线）
- 目标：从“只兼容酒馆卡”扩展到“兼容任意形式、任意格式的剧本 / 世界观设定 / 小说”。
- 做法：
  - 抽象一个 **import 管线分发器**：根据来源类型选择管线。
    - 酒馆卡（ST v2/v3 JSON / PNG 卡）→ 专用酒馆管线（已存在的 `card_migration`）。
    - 其他（纯文本剧本、Markdown 设定集、小说全文、未来 COC 剧本等）→ **通用导入管线**：尽力抽取 premise / 角色 / 世界规则 / 场景，落成同一套 `card_ir`-兼容 IR + workspace。
  - 专用管线缺失时**降级到通用管线**：未实现 COC 专用管线时，COC 剧本也能走通用管线跑起来，只是抽取更粗。
  - 所有管线最终都收敛到同一 workspace 结构与 IR，保证下游一致。
- **当前进展（2026-06-14）：第一阶段已完成**——新增 `app/importers.py`（`detect_source_kind` / `run_import` / `build_generic_card_ir`）：酒馆卡（spec 或 `first_mes` 等特征）走 `card_migration` 专用管线；剧本（对白行/场景标记）、小说（章节标记/长段落）、设定集（Markdown/纯文本）走通用管线；COC 等专用管线未实现时降级到通用管线。新增 `import` CLI 命令（`run_import_any`），所有来源都收敛到同一 `card_ir` + workspace。deterministic 测试覆盖 tavern/screenplay/novel/setting 检测、通用 IR 抽取、两条管线 materialize；CLI smoke 通过。剩余待做：PNG 卡内嵌读取、COC/专用子管线、更强的角色/场景结构抽取。
- 依赖：S3、M3（卡片完整 bootstrap）。
- 原则：高可迁移、高解耦（管线可插拔、可降级）、简洁目录（统一 IR 出口）。

### G4. 一键启动脚本（后端 API + 前端 Web，YAML 配置驱动）
- 目标：类似酒馆，一条命令同时拉起后端 API 与前端 Web 界面，行为由 YAML 配置读取（监听地址 / 端口 / 白名单等）。
- 做法：
  - 新增 `config/server.yaml`：`host`、`port`、`allow_origins` / `ip_whitelist`、`open_browser`、`static_dir` 等。
  - 新增启动命令 `python -m app.main serve`，读取 `config/server.yaml`，按配置启动监听、设置白名单 / CORS、可选自动打开浏览器。
  - 前端 Web 由同一服务托管（内置最小前端 + 既有 `/api/*`）。
  - 严格遵守安全约束：默认仅本地监听（127.0.0.1），白名单显式配置；对外暴露需用户显式开启。
- **当前进展（2026-06-14）：已完成**——新增 `app/server_config.py`（`ServerConfig` / `load_server_config` / `parse_server_config`，含 `is_ip_allowed` / `cors_origin_for`）、`config/server.yaml`、`serve` 子命令（支持 `--config/--host/--port` 覆盖）；handler 重构为配置感知（IP 白名单 403、CORS 头、OPTIONS 预检）；**根目录新增一键启动脚本 `start.bat`（Windows 双击即用，纯 ASCII 避免 GBK 代码页乱码）与 `start.sh`（macOS/Linux）**；deterministic 测试覆盖默认值/白名单/CORS/通配；live smoke 确认 `serve` 与 `start.bat` 均可一条命令同时提供 `/api/*` 与前端页面。
- 依赖：S4（API contract）、M6（前端扩展）。
- 原则：前端友好、高可配置（全部走 YAML）、简洁工程目录（单一入口）。

### 6.1 新增目标优先级与依赖矩阵

| 目标 | 影响目标 | 参考来源 | 复杂度 | 前置依赖 |
|------|----------|----------|--------|----------|
| G4 一键启动脚本 | UI/前端友好/可配置 | TauriTavern | 低 | S4 |
| G1 角色卡展示前端 | UI/前端友好 | TauriTavern | 低-中 | S3, S4, M6 |
| G2 Agent Skill 系统 | RP 深度/解耦/可配置 | AIRP-MCP-Server | 中 | M2, M4 |
| G3 通用导入管线 | 可迁移/解耦 | tavern2agent | 中-高 | S3, M3 |

建议落地顺序：**G4 → G1 → G2 → G3**。
理由：G4 / G1 是“低成本、立刻提升可用性与前端友好度”的项；G2 / G3 依赖 M2 / M3 / M4 的深化结果，应在事件/profile/卡片 bootstrap 更成熟后再做，避免返工。

---

## 7. 前端工作台全面重构（2026-06-15）

### 背景
旧前端是 `app/main.py` 内联的一段 HTML（story 名按钮 + 一个 textarea + 一堆只读 `<pre>`），只能看不能操作，无法创建项目、编辑 prompt/配置、无多标签、无拖拽。用户明确要求彻底重构为「精致、现代、简洁、可拖拽、富交互的多标签创作工作台」，并先形成设计规范文档后续强制遵循。

### 决策（已确认）
- 技术栈：**Vite + Vue 3 + TypeScript + Pinia**（首次引入 node 构建链，产物 `web/dist/` 由 Python 托管）。
- 验证：**Playwright MCP** 做端到端浏览器验证（点击/拖拽/填表/断言 DOM/截图）。
- 后端写范围：**全套 CRUD + 运行**（创建工作区、文件读写、config 读写、后台 run job）。
- IP 白名单语义：仅局域网/公网跨设备访问的轻量准入，非严格鉴权；默认本地不限制。

### 已完成
- **设计规范**：新增 `docs/frontend_design_system.md`（设计令牌、布局骨架、组件清单与状态、交互模式、可访问性、强制遵循约定），并落为 `web/src/styles/tokens.css` 唯一样式真相源。
- **后端写 API**：HTTP 层从 `main.py` 抽出为 `app/web/` 包（`routes/paths/api_workspace/api_files/api_config/api_run/static`）。新增工作区创建/删除、文件树/读/写、config 读写（白名单+YAML 校验）、后台 run job（默认 mock）。路径穿越守卫 + 非 UTF-8 请求体降级为 400。契约写入 `docs/ui_api_contract.md`。
- **前端工程**：`web/`（Vite+Vue3+TS）。多标签工作台：新建项目向导、概览、角色卡（正则 widget 渲染）、RP 对话气泡、Prompt 编辑（脏标记/保存/Markdown 预览）、配置编辑、文件浏览、运行面板（job 轮询）、标签拖拽重排、暗/亮主题、Toast/确认/空态。
- **验证**：后端 deterministic 测试 `tests/test_web_api.py`（10 项）+ 既有套件共 **55 passed**；前端 `vue-tsc` 类型检查通过、`vite build` 成功；Vitest 工作台 store 单测 6 项通过；HTTP 端到端 smoke（SPA 托管 + 工作区 CRUD + 文件读写 + run job + 路径穿越被拒 + 中文 UTF-8 round-trip）全绿、无 server traceback。
- **一键启动**：`start.bat`/`start.sh` 增加首次自动构建前端（缺 dist 且有 npm 时 `npm install && npm run build`）。

### 端到端浏览器验证（2026-06-17 已完成）
通过 Playwright MCP 真正打开页面，全流程已验证通过并截图存证：
- SPA 加载（标题/暗色主题/概览真实数据渲染）。
- 导航切换：概览 / 角色卡（空 card_ir 显空态）/ RP / Prompt / 配置 / 文件 / 运行 全部可达。
- RP 全链路：提交带骰子表达式的玩家行动 → 玩家/GM/角色气泡 + **dice_roll 技能结果（1d20）**渲染。
- 文件写回链路：打开 `lore/premise.md` → 编辑触发脏标记（tab ● + 工具栏 ● + 按钮启用）→ 保存 → 文件落盘确认（测试后已还原原文）。
- 配置编辑：白名单列表 + agents.yaml YAML 加载（含 G2 gm/dice_roll）。
- **标签拖拽重排**：把「配置」从末位拖到首位成功（用户强调的核心交互）。
- mock run 生命周期：error 路径（C01S01 已归档，如实报错）+ done 路径（C09S09 输出 JSON），轮询渲染正常。
- 新建项目向导：填名称/主题 → 创建 → 自动选中打开 → 磁盘自包含工作区生成；DELETE API 清理 200。
- 亮/暗主题切换正常；**console 零错误零警告**。
- 验证产生的测试残留（e2e_test_proj、C09S09 归档/journal/checkpoint、premise/state/player_visible 改写）已全部清理还原。Python 55 passed 回归通过。

### 剩余待做（增强项，非阻塞）
- 文件重命名/移动拖拽、preset 模块挂载的可视化拖拽排序写回、右侧 Inspector 上下文面板、键盘快捷键帮助面板、CodeMirror 语法高亮（当前为 textarea+mono）。

