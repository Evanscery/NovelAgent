# NovelAgent

> 文件驱动、可审查、可归档、可扩展到 RP 的多 Agent 小说创作 / 互动系统。
> Python 编排流程 · 文件系统作唯一真相源 · SQLite 管召回 · 可选真实 LLM 管生成与审查 · 前端只做操作/展示/调试。

NovelAgent 用一条串行多 Agent 流水线把「设定 → 大纲 → 写作 → 审查 → 修订 → 状态维护 → 归档」做成可审计的闭环，并在同一套文件结构上扩展出**玩家可互动的 RP 模式**与**酒馆卡 / 通用剧本迁移**。设计总原则只有一条：**最大程度利用 agent 能力完成任务，而不是为了"看起来高级"去引入无意义复杂度**——只有某项设计确有必要、确能稳定提升效果/效率/可维护性/可迁移性/可运维性时，才进入实现。

- Python ≥ 3.11，依赖仅 `pydantic` + `PyYAML`
- 真实 LLM 是**最终验收工具，不是调试器**：工程问题先用 mock / deterministic / schema 校验解决，最后才接真实模型
- 前端 Vite + Vue 3 + TypeScript + Pinia，构建产物由 Python 同进程托管

---

## 能力总览（截至 2026-06-24）

| 能力域 | 状态 | 说明 |
|--------|------|------|
| 文件驱动多 Agent 创作闭环 | ✅ | 13 步串行流水线，可审查、可归档 |
| 审查-修订-再审查闭环 | ✅ | 修订后自动重跑 character/continuity/style 审查 |
| workspace 隔离 + 纯净初始化 | ✅ | 每个故事自包含，互不污染 |
| 结构化状态推进 + 结构化记忆 | ✅ | state 推进校验、summary/index 幂等、`memory/scenes.json` 结构化主存 |
| 恢复 / 降级 / 缓存 / journal / resume | ✅ | runtime 配置化、checkpoint、prompt cache、失败改道 |
| RP 基础设施 | ✅ | 玩家输入解析、事件驱动状态、player_visible/hidden 分层 |
| RP 反馈模型重构 | ✅ | 可插拔 `RpMode`（immersive/trpg）+ per-workspace 配置 + GM/玩家掷骰协议 |
| 卡片迁移（Card IR / Runtime Plan） | ✅ | 酒馆卡专用管线 + 通用导入管线（可降级） |
| 一键启动 + 前端工作台 | ✅ | `serve` + `start.bat`/`start.sh`，多标签可拖拽工作台 |
| 角色卡展示前端（ST 正则渲染） | ✅ | findRegex→$1..$N→HTML 组件引擎 |
| Agent 技能系统 | ✅ | 内置 `dice_roll`（确定性，零 LLM），MCP 预留 |
| 小说阅读闭环 | ✅ | 作品阅读页 + 只读 `/api/novel*` + 章↔场景组装 |
| 真实 LLM 最小 smoke | ✅ | generate / critic / evaluate 三步打通外部模型 |

**测试现状**：Python 套件 **72 passed**（deterministic，不接真实 LLM）；前端 `vue-tsc` 通过、`vite build` 成功、Vitest store 单测通过；HTTP 端到端 smoke 与 Playwright 浏览器验证均绿、console 零错误。

---

## 快速开始

### 0. 一次性准备

```bash
pip install -e .                 # 安装依赖（首次）
python -m app.main init-db        # 初始化 Recall 数据库（全局一次）
```

要写真实正文，先配模型：把 `.env.example` 复制为 `.env` 填入供应商/密钥，编辑 `config/models.yaml` 与 `config/agents.yaml` 把各 agent 的 `runner` 指向可用模型。

### 1. 创建独立项目（工作区）

每个故事是一个自包含工作区，放在 `workspaces/<项目名>/`，互不干扰。

```bash
python -m app.main init-story \
  --story-root workspaces/my_first_novel \
  --theme "现代都市，一名程序员意外获得回到过去24小时的能力" \
  --runner direct
```

先用 `--runner mock` 干跑一遍验证工程结构（不花额度），确认无误再换 `--runner direct` 正式生成设定/人物/大纲/初始状态。

### 2. 写正文

```bash
python -m app.main write-book \
  --story-root workspaces/my_first_novel \
  --chapters 5 --min-words 3000 --runner direct
```

每章依次执行：冻结输入 → 召回 → 规划 → 多重审查 → 写作 → 修订（后自动重审）→ 状态维护 → 归档，成稿导出为 `novels/chapter_01.txt …`。支持中断后再次运行接着写。

可选评估：`python -m app.main evaluate-book --story-root workspaces/my_first_novel --runner direct`，报告写到 `evaluation/final_report.md`。

### 3. 图形界面（推荐）

```bash
python -m app.main serve          # 一键启动后端 API + 前端 Web
```

- Windows 直接双击根目录 `start.bat`，macOS/Linux 运行 `./start.sh`（首次自动构建前端）。
- 浏览器打开提示地址（默认 `http://127.0.0.1:8766`，见 `config/server.yaml`，可覆盖）。
- 工作台含：概览、角色卡、RP 对话、Prompt 编辑（可拖拽重排）、配置编辑、文件浏览、运行面板、作品阅读页。

### 4. 扩展：RP 互动模式

RP 是可选玩法：你输入"玩家行动"，系统按事件驱动推进一回合，并维护**后台真实状态**与**玩家可见状态**的信息差。同一工作区即可开始，无需新建项目。

```bash
python -m app.main rp-turn \
  --story-root workspaces/my_first_novel \
  --text "对酒馆老板说：我想打听最近镇上的怪事。"
```

进阶：行动里写骰子表达式（如 `1d20`、`1d100`），若 GM 已声明 `skills:[dice_roll]`，结果作为可审计的技能调用挂在响应里；支持 `immersive`（沉浸叙事）/ `trpg`（跑团判定）两种可切换模式，per-workspace `rp.yaml` 差异化配置。RP 回合默认不调用大模型，适合先把互动跑顺。

> CLI 速查见文末「命令一览」；从零写 5 章的完整教程见 [`docs/how_to_start.md`](docs/how_to_start.md)。

---

## 核心架构与分工

```text
Python 编排器 (app/)     读配置 → 装配上下文 → 调用运行器 → 写产物 → 归档
  ├─ runners/            mock / direct(OpenAI兼容,策略驱动重试降级) / pi_rpc(可选)
  ├─ context_builder.py  上下文装配流水线：Collect→Prioritize→Schedule→Render→Trace
  │                      + token 预算 + section 级 keep/truncate/drop/compress
  ├─ pipeline.py         13 步串行流水线 + resume/checkpoint/cache 接入
  ├─ prompt_modules.py   模块化 prompt 组装
  ├─ recall.py           SQLite FTS5 召回（多故事隔离）
  ├─ player_input.py     RP 玩家输入结构化解析
  ├─ event_*.py          RP 事件目录 / 归约器 / 分层响应构造器（registry 化）
  ├─ rp_modes.py         可插拔 RpMode（immersive/trpg）+ per-workspace 配置
  ├─ skills.py           Agent 技能 registry（内置 dice_roll；MCP 预留）
  ├─ card_migration.py   酒馆卡 → Card IR → Runtime Plan → materialize
  ├─ card_front.py       ST 风格正则 → HTML 前端渲染引擎
  ├─ importers.py        通用导入分发器（专用管线优先，可降级到通用）
  ├─ server_config.py    一键启动配置（host/port/CORS/IP 白名单）
  └─ web/                HTTP 服务层（routes/paths/api_workspace/api_files/
                          api_config/api_run/api_novel/static）

SQLite Recall (data/recall.db)   索引历史摘要/索引/正文全文
文件系统                         唯一真相源：workspaces/<story>/{lore,state,memory,
                                 work,archive,novels,data,front,...} 自包含
Git                              保存每轮变化，提供回滚与差异审计
```

### 主创作流水线（13 步）

```text
run_snapshotter      → recaller        → scene_planner
→ outline_worldbook_guard → outline_knowledge_guard → outline_integrator
→ prose_writer        → character_guard → continuity_guard → style_detail_guard
→ prose_reviser       → state_manifest_keeper → memory_archivist
```

bootstrap 系列（`theme_bootstrapper` / `cast_designer` / `worldbook_builder` / `arc_planner` / `state_initializer`）用于 `init-story`，`book_evaluator` 用于 `evaluate-book`。

### Prompt 组装顺序

1. Agent 任务 prompt → 2. preset 全局模块 → 3. preset 文风模块 → 4. 该 Agent 专属模块 → 5. `agents.yaml` 额外挂载模块 → 6. 输出 artifact 约束 → 7. 输入文件上下文 → 8. 本轮步骤元数据。

任务职责与通用规则分离、文风/模式可替换、输出格式统一复用、上下文文件靠后便于后续缓存。

---

## 目录结构

```text
app/                Python 编排器（见上「核心架构」）
config/             流程 / Agent / 模型 / 运行时 / 召回 / 路径 / server 配置
  ├─ agents.yaml        每个 agent 的 profile/prompt/preset/runner/artifacts/inputs
  ├─ pipeline*.yaml     多套流水线（主流程 / 章节 / 评估 / smoke / story_init）
  ├─ models.yaml        模型 tier（premium/standard/cheap）+ RPM 限速 + agent 映射
  ├─ runtime.yaml       超时/重试/退避/降级/resume/cache/section 预算策略
  └─ server.yaml        一键启动 host/port/CORS/IP 白名单/open_browser
web/                前端工作台（Vite + Vue3 + TS + Pinia）
  └─ src/{styles,api,stores,components,views}  构建产物 dist/ 不入库，由 app/web/static.py 托管
docs/               总指导 / 实现归档 / 参考分析 / 优化计划 / API 契约 / 前端设计规范 / 已知问题
workspaces/<story>/  自包含工作区
  ├─ lore/         世界与角色设定（premise/characters/worldbook/locations/style）
  ├─ outline/       大纲（master_outline/current_arc）
  ├─ state/         canonical state + player_visible
  ├─ memory/        summary/index/fulltext + scenes.json（结构化主存）
  ├─ work/          临时产物 / run_journal / checkpoints / prompt_snapshots / last_response
  ├─ archive/       每场完整过程归档
  ├─ novels/        成稿 chapter_*.txt（可直接阅读）
  ├─ evaluation/    评估报告
  ├─ data/          card_ir.json / runtime_plan.json
  ├─ front/         ST 风格正则前端脚本（由 /api/card 渲染）
  ├─ presets/ modules/ prompts/   该工作区专属 prompt 配置
  └─ rp.yaml        per-workspace RP 配置（可选）
data/               全局 SQLite（recall.db / prompt_cache）
tests/              Python deterministic 测试
```

> 遗留 `novel_project/` 路径可通过 `app/project_paths.py` 兼容层映射到实际 `workspaces/*` 与 `stories/*`。

---

## 配置体系

四层优先级：`global < profile < story < run override`（共享默认值的同时允许单个故事深度定制）。

可配置对象（全部由文件驱动，无需改核心编排代码）：prompt modules、preset、profile、agent 列表、pipeline 步骤与顺序、模型 tier 分配、重试/退避/超时、Recall 策略、扩写策略、RP 模式策略、section 级上下文预算。

新增客制化文风：在 `workspaces/<story>/modules/style/` 加一个 Markdown 模块 → 在该工作区 `presets/default.yaml` 的 `modules.style` 挂载 → 重新跑场景即可。RP 与 NSFW 模块保留扩展接口、默认不启用。

---

## 前端工作台

Vite + Vue 3 + TypeScript + Pinia 单页应用，提供多标签创作工作台：新建项目向导、概览（作品主页化）、角色卡（ST 正则 widget 渲染）、RP 对话（气泡 + 骰子徽章 + 玩家掷骰按钮）、Prompt 编辑（脏标记/保存/Markdown 预览/标签拖拽重排）、配置编辑（白名单 + YAML）、文件浏览、运行面板（job 轮询）、作品阅读页（书籍版式）。

```bash
cd web
npm install        # 首次
npm run dev        # 开发模式 (:5173，/api 代理到本地后端)
npm run build      # 构建到 web/dist，由 python -m app.main serve 托管
npm run test       # 前端 Vitest 单测
```

- `web/dist/` 不入库；`serve` 发现 dist 缺失会回退内联最小页并提示构建（`start.bat`/`start.sh` 首次自动构建）。
- 前端只经 `/api/*` 窄契约访问后端，不持有 canonical state，所有修改写回文件。
- 设计规范见 [`docs/frontend_design_system.md`](docs/frontend_design_system.md)，是后续所有前端改动的强制基准；后端写 API 契约见 [`docs/ui_api_contract.md`](docs/ui_api_contract.md)。

### 前端与后端边界

| 项目 | 后端 | 前端 |
|------|------|------|
| prompt 组装 / canonical state / event 处理 | ✅ | ❌ |
| 玩家输入采集 / 章节·归档查看 / story 管理(操作) / 卡片迁移展示确认 / 配置编辑界面 | ❌ | ✅ |

---

## 一键启动与安全

`python -m app.main serve` 读取 `config/server.yaml` 拉起后端 API + 前端 Web。安全约束：**默认仅本地监听（127.0.0.1）**；对外暴露需显式改 `host: 0.0.0.0` 并配置 `ip_whitelist`；CORS 与白名单全部 YAML 驱动。可追加参数覆盖：`serve --port 9000 --host 0.0.0.0`。

---

## 命令一览

| 目的 | 命令 |
|------|------|
| 初始化数据库（一次） | `python -m app.main init-db` |
| 索引记忆 | `python -m app.main index-memory` |
| 检索历史 | `python -m app.main recall "角色名 伏笔名"` |
| 新建项目 | `python -m app.main init-story --story-root workspaces/<name> --theme "..." --runner direct` |
| 写多章正文 | `python -m app.main write-book --story-root workspaces/<name> --chapters 5 --min-words 3000 --runner direct` |
| 评估 | `python -m app.main evaluate-book --story-root workspaces/<name> --runner direct` |
| 单场流程 | `python -m app.main run-scene C01S01 --runner mock` |
| 归档 | `python -m app.main archive C01S01` |
| RP 一回合 | `python -m app.main rp-turn --story-root workspaces/<name> --text "..."` |
| 导入酒馆卡 | `python -m app.main import-card --input card.json --story-root workspaces/<name>` |
| 通用导入 | `python -m app.main import --input path/to/source.md --story-root workspaces/<name>` |
| 清理/迁移记忆 | `python -m app.main normalize-memory` / `reset-work` |
| 图形界面 | `python -m app.main serve`（或 `start.bat` / `./start.sh`） |
| 干跑验证（不花额度） | 上述命令把 `--runner direct` 换成 `--runner mock` |

`mock` 运行器不调用任何模型，只验证工程结构、模块组装、配置、文件读写、归档流程是否正确。

---

## 测试原则

> 真实 LLM 不是调试器，只是最终验收工具。

测试分层：第 0 层静态/结构 → 第 1 层 mock runner → 第 2 层局部 deterministic → 第 3 层最小真实 LLM smoke → 第 4 层最终真实场景。只有前 3 层全绿才允许真实生成/RP/迁移整链测试。这避免把 contract 错位、路径错位、归档污染、状态推进错误等工程问题放到真实模型上反复烧 token。

---

## 文档索引

- [`docs/how_to_start.md`](docs/how_to_start.md) — 新手上手：从零创建项目并写完 5 章（RP 作扩展）
- [`docs/project_master_guide.md`](docs/project_master_guide.md) — 项目总指导（目标 / 现状 / 设计原则 / 演进路线）
- [`docs/architecture.md`](docs/architecture.md) — 架构说明与目录规范
- [`docs/project_archive_timeline.md`](docs/project_archive_timeline.md) — 实现与验收时间轴归档（事实归档）
- [`docs/stage_report.md`](docs/stage_report.md) — 阶段总结报告（2026-06-24 快照）
- [`docs/next_step_optimization_plan.md`](docs/next_step_optimization_plan.md) — 下一步实现与优化计划
- [`docs/reference_projects_analysis.md`](docs/reference_projects_analysis.md) — 参考项目分析报告
- [`docs/ui_api_contract.md`](docs/ui_api_contract.md) — 最小前端 API 契约
- [`docs/frontend_design_system.md`](docs/frontend_design_system.md) — 前端设计规范（强制基准）
- [`docs/ui_art_direction.md`](docs/ui_art_direction.md) — 前端美术方向
- [`docs/known_issue.md`](docs/known_issue.md) — 已知问题与待提升点
- [`docs/improvement_proposals.md`](docs/improvement_proposals.md) — 异步改进意见池（待人工审批）
- [`docs/参考项目.md`](docs/参考项目.md) — 参考项目入口清单

---

## 演进路线（简）

```text
单故事小说流水线（已完成）
→ 多故事并行隔离（已完成）
→ 玩家可互动 RP（基础已完成，真实 LLM GM 待补）
→ 卡片迁移生态（基础已完成，通用导入已落地，专用子管线待补）
→ 角色自治 / 沙盒模式（长期：sub-agent / 并行响应 / event pack）
```

下一步主线（见优化计划）：M3 卡片完整 bootstrap、M4 角色 profile 体系、M5 workspace 分层对齐、M6 前端扩展（调试页 / Inspector / 可视化模块挂载）；长期 L1 角色独立 sub-agent、L2 并行角色响应、L3 记忆封卷+检索升级、L4 配置工作台、L6 沙盒 event pack。**不为复杂度而复杂度**——每项技术选型都要求"确有必要、确有优势"。

---

## 第一版成功标准

连续写 3-5 场后：①不忘记上一场发生过什么 ②角色不会知道不该知道的信息 ③世界观规则不被破坏 ④时间/地点/物品/人物状态不矛盾 ⑤每场都有完整归档 ⑥下一场能从 `state/state.md` 自然接上。
