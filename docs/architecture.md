# 架构说明

本工程采用文件驱动架构，目标是让小说创作流程可审查、可归档、可回滚，并且能在不重写核心编排器的前提下扩展文风、RP 和其他模式模块。

## 核心分工

- Python 编排器：读取配置、组装上下文、调用运行器、写入产物、执行归档。
- Pi RPC 运行器：可选执行层，只负责返回文本，不直接改项目文件。
- SQLite Recall：索引历史摘要、索引和正文全文，生成召回报告。
- Git：保存每轮变化，提供回滚和差异审计。
- 文件系统：保存真实状态、设定、草稿、审查报告、模块和归档。

## 参考 TauriTavern Agent 模式后引入的概念

### 1. Preset

`novel_project/presets/default.yaml` 负责定义：

- 全局模块
- 文风模块
- 每个 Agent 的默认专属模块
- 模式挂载入口

Preset 不绑定具体模型供应商，只描述 prompt 组装策略。

### 2. Prompt Modules

模块化 prompt 存放在：

```text
novel_project/modules/
```

分为：

- `core/`：基础身份、文件驱动规则、认知边界、输出纪律
- `modes/`：小说模式、RP 模式
- `style/`：默认文风与客制化文风示例
- `optional/`：未来可选模块占位
- `output_contracts/`：统一输出格式约束

### 3. Frozen Run Input Snapshot

每次场景运行前，本地编排器会先生成：

```text
novel_project/work/run_snapshot.md
```

它冻结本轮输入事实，避免不同 Agent 在流程推进过程中看到漂移状态。

### 4. Artifact

每个 Agent 在 `config/agents.yaml` 中声明自己应该产出的 artifact，例如：

- `rough_outline`
- `final_outline`
- `draft_prose`
- `draft_logic_report`
- `state_main`

这样上下文、输出目标、校验规则都更清晰。

## Prompt Assembly 顺序

当前 `ContextBuilder` 组装顺序：

1. Agent 任务 prompt
2. preset 全局模块
3. preset 文风模块
4. preset 中该 Agent 的专属模块
5. Agent 额外挂载模块
6. artifact 约束
7. 输入文件上下文
8. 本轮步骤元数据

这个顺序的作用是：

- 任务职责与通用规则分离
- 文风与模式可替换
- 输出格式可统一复用
- 上下文文件保持在后部，便于后续优化缓存策略

## 为什么第一版仍然不做大平台

虽然引入了 preset / modules / snapshot / artifact，但第一版依然不是完整 Agent 平台。我们没有引入：

- 复杂前端
- MCP
- Pi extension
- 独立角色记忆
- 自动 profile 路由
- 可视化 PromptManager

原因是第一版的目标仍然是：

```text
稳定闭环
清晰文件结构
可审查
可归档
可扩展
```

## 目录规范（下一步优化约定）

为了满足“简洁工程目录、高项目间隔离、高解耦可插拔、高可配置、前端友好”，后续目录约定如下：

### 代码目录
- `app/`
  - `runners/`：模型/外部执行层
  - `player_input.py`、`event_runtime.py`：RP runtime 核心
  - `event_types.py`：RP 事件数据类型（`RuntimeEvent` / `EventApplicationResult`），独立出来打破循环依赖
  - `event_catalog.py`：RP 事件目录（intent → 事件条目，未知 intent 降级到 fallback）
  - `event_reducers.py`：事件状态归约器 registry（state / player_visible）
  - `event_response_builders.py`：RP 分层响应构造器 registry
  - `context_builder.py`：上下文装配流水线（collect/prioritize/schedule/render/trace + collector 分类 + budget 调度）
  - `card_migration.py`：卡片迁移核心
  - `card_front.py`：ST 风格正则前端渲染引擎（findRegex→$1..$N→HTML，G1）
  - `skills.py`：agent 技能 registry（内置 `dice_roll`；MCP 为未来外部通道，G2）
  - `server_config.py`：一键启动 server 配置（host/port/CORS/IP 白名单，G4）
  - `importers.py`：通用导入分发器（酒馆卡走专用管线，剧本/设定/小说走通用管线，可降级，G3）
  - `web/`：HTTP 服务层（前端重构时从 `main.py` 抽出，显式化路由）
    - `routes.py`：路由分发（GET/POST/PUT/DELETE + 静态托管 + CORS/IP 白名单）
    - `paths.py`：路径穿越守卫（`safe_resolve` / `resolve_workspace`）
    - `api_workspace.py`：工作区创建/列举/删除（复用 `StoryWorkspaceManager`）
    - `api_files.py`：工作区文件 CRUD（限定可编辑目录与文本类型）
    - `api_config.py`：`config/*.yaml` 读写（白名单 + 写前 YAML 校验）
    - `api_run.py`：后台 job 运行与轮询（默认 runner=mock，不接真实 LLM）
    - `api_novel.py`：小说阅读只读通道（`/api/novel*`，限定 `novels/` 与 `memory/fulltext/`，零 LLM）
    - `static.py`：托管 `web/dist` 的 SPA（缺失则回退内联页）
  - `app/rp_modes.py`：RP 反馈模型——可插拔 `RpMode` 策略（`immersive`/`trpg`）+ per-workspace `rp.yaml` 加载（`RpConfig`/`load_rp_config`）+ GM runner 钩子（mock 默认，llm 占位）。状态推进仍由 `event_reducers` 负责，mode 只 narrate。
  - 后续建议新增：
    - `collectors/`：上下文收集器（当前已在 `context_builder.py` 内以 CollectorRule 显式化，后续可外置）
    - `profiles/`：profile resolver / 权限装配
    - `skills/`：agent 技能 registry（如 GM 掷骰；MCP 作为未来可选外部通道）
    - `importers/`：通用导入管线分发器（酒馆卡走专用管线，其他走通用管线，可降级）
    - `ui_contracts/`：前端 API schema 与聚合层
- `config/`
  - pipeline / agent / model / runtime / 未来 profile / 未来 server 配置
- `web/`
  - 前端工作台（Vite + Vue 3 + TS）。`src/{styles/tokens.css, api/client.ts, stores/, components/, views/}`；构建产物 `dist/`（不入库，由 `app/web/static.py` 托管）。设计基准见 `docs/frontend_design_system.md`。
- `docs/`
  - 总指导、实现归档、参考项目分析、优化计划、API 契约、前端设计规范

### 项目数据目录
- `workspaces/<story>/`
  - `lore/`：世界与角色设定
  - `state/`：canonical state / player_visible
  - `memory/`：summary / index / fulltext
  - `work/`：临时运行产物、journal、checkpoint、last_response
  - `archive/`：场景归档
  - `data/`：card_ir / runtime_plan / 未来 schema/event catalog
  - `front/`：ST 风格正则前端脚本（`findRegex` 抓变量 + `replaceString` HTML 模板，G1），由 `/api/card` 渲染
  - 后续建议增设：`simulation/`、`reference/`、`manuscript/`

### 前端边界
- 前端只通过 API 访问聚合数据，不直接拼接文件。
- 配置页只修改配置文件，不修改 canonical state。

该约定的目标是：
- **每个 story 自包含**，便于迁移、归档与并行；
- **运行时层与展示层解耦**，便于后续替换 UI 或引入新 runner；
- **模块目录显式化**，为 collectors / reducers / profiles 的可插拔化做准备。

## 状态来源

系统真实状态只来自文件：

- `novel_project/state/state.md`
- `novel_project/state/player_visible.md`
- `novel_project/memory/`
- `novel_project/archive/`

不要把 Pi 会话、模型上下文或临时对话当作唯一状态来源。
