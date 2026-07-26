# NovelAgent 人工审计指南（系统简述）

> 日期: 2026-07-27
> 读者: 需要手动审计本项目的软件工程师
> 用法: 按下面的顺序读代码——每一节是一层，节内文件按审计优先级排序（先读会改变你对系统理解的文件）。约 70 个后端 Python 文件 + 前端 React SPA，全部读完约需一天；只读带 ★ 的约需 2 小时即可建立准确心智模型。

## 0. 先读的三份文档（30 分钟）

1. ★ `docs/refactor_guide.md` — 权威设计蓝图。四层架构（用户/Runtime/Agent/数据）、8+1 类资源、director 调度、统一工具、权限隔离、git 版本模型。**审计的对照基准，一切"是否符合设计"以它为准。**
2. ★ `docs/audit_report.md` — 2026-07-27 全面审计（问题编号 F/Q/W）。告诉你哪些地方曾经断裂、哪些已修、哪些是"有意为之"。
3. `docs/stage_report.md` + `docs/optimization_plan.md` — 项目走到哪了、修复按什么波次进行（git log 里的 [W0]~[W4] 标签对应这里）。

**核心运行模型（一句话版）**：用户点"开始一轮" → API 把请求交给 Runtime 工厂 → director（一个普通 Agent 配置，非代码类）在 LLM tool-call 循环里用 `call_agent` 逐个调度画布上的子 agent（每个子 agent 有自己的权限工具面和有限 tool-loop）→ director `finalize(final_text, summary)` → 正文落盘 `novels/`、摘要归档 `turn_summary` → 整轮写入作为一个 `Turn <id>:` git commit（失败则工作树回滚）。

## 1. Runtime 层 `app/runtime/`（系统心脏，最先读）

| 优先级 | 文件 | 内容 |
| --- | --- | --- |
| ★1 | `round_executor.py` | **全系统最重要的文件**（约 800 行）。director tool-call 循环：组装请求→发送→解析 tool_calls→分发（call_agent/await/finalize/数据工具）→结果作为 tool message 回喂→循环。含三道递归闸门（budget/深度/allow_recursive）、子 agent 有限 tool-loop（结果回喂子 agent 自身）、finalize 捕获 final_text/summary。chat 轮与 workflow 轮共用同一循环（chat 无 flow sequence）。 |
| ★2 | `session.py` | `create_round_session` 工厂：API 层唯一入口，组装 registry/Runtime/Budget/Executor/每 agent 权限工具面/默认注入 provider。`run_session` 把 workflow 轮包进 AtomicTurn：成功→正文/摘要落盘+一个 Turn commit；runner 失败→工作树恢复快照。 |
| ★3 | `permission.py` | `ScopedTools`：把 agent.permission 套在 ResourceStore 上，越权抛 `PermissionDenied`。上下文隔离的执行点。 |
| 4 | `prompt_builder.py` | `Message`（含 assistant tool_calls）/`RequestSpec`/`PromptBuilder`：系统提示词（来自 agent 层 parser）+ 会话历史 + 工具 schema → provider 中立请求。`fingerprint()` 供 mock 确定性。 |
| 5 | `tool_dispatcher.py` + `tool_catalog.py` | 工具调用解析与路由：catalog 实现（dice_roll 等）优先，数据工具走 ScopedTools；未知工具明确拒绝（防工具滥发）。catalog.register 是 MCP/插件缝。 |
| 6 | `runners/`（base/direct/mock） | LLM 调用边界。`DirectRunner`：OpenAI 兼容端点 + 超时/重试/退避 + tier→模型名解析。`MockRunner`：**脚本化确定性**——director 请求按 flow 顺序逐个 call_agent 再 finalize；可写子 agent 发一次 write。mock 轮因此能走完整创作链（工程验证不花额度）。 |
| 7 | `runtime.py` | 请求发送的超时/重试包装 + 并发原语（`run_concurrent/await_all/await_any`，设计能力，executor 尚未接入——当前 call_agent 是同步完成，await 是形式的）。 |
| 8 | `budget.py` / `transaction.py` / `providers/openai_chat.py` / `mcp/` | 预算计数器+FinalizeSignal；AtomicTurn 快照/提交/恢复；OpenAI 编解码（assistant.tool_calls 序列化在此）；MCP 加载缝（空实现）。 |

**审计着眼点**：round_executor 的循环终止条件是否完备；ScopedTools 是否所有工具路径都过权限；session 的事务边界（哪些写入在 AtomicTurn 内）。

## 2. Agent 层 `app/agents/`（配置即行为）

| 优先级 | 文件 | 内容 |
| --- | --- | --- |
| ★1 | `agent.py` | frozen 的 Agent 数据类（id/name/task/input/output/permission/model/tools/head/tail/allow_recursive）。id 是只读控制标识（校验规则在此），name 只是显示名。 |
| ★2 | `builtin/*.yaml`（6 个） | director/recaller/scout/writer/critic/maintainer 的属性集。**权责分割的事实来源**：director 无 write、writer 只能写 notes、maintainer 写 5 类资源。审计权限模型先看这里。 |
| 3 | `parser.py` | 属性→系统提示词的纯函数（任务/输入输出/权限段/工具段/工作流顺序段）。"配置静态、prompt 动态"的实现。 |
| 4 | `registry.py` | id 主键 + name 二级索引（重名→_AMBIGUOUS 哨兵）；`build_project_registry` = 内置 + 项目 `agents/*.yaml` 覆写。 |
| 5 | `tree_model.py` | WorkflowTree/TreeNode/NodeDefinition：画布编译产物；便携导出把 agent 定义按 id 内嵌（防重名劫持）。 |
| 6 | `tools.py` | 全部内置工具的 JSON-Schema（read/write/list/glob/grep/read_lines + call_agent/await/finalize + dice_roll）。只有 schema，无实现（实现在 runtime）。 |
| 7 | `flow_sequence.py` / `permission.py` / `workflow.py` | 执行顺序文本生成；Permission 定义（resource_type 白名单）；facade。 |

## 3. 数据层 `app/data/`（只存储，不理解）

| 优先级 | 文件 | 内容 |
| --- | --- | --- |
| ★1 | `store.py` | ResourceStore：资源目录 CRUD + grep/glob/read_lines。`resolve_content_path` 是路径穿越防线（审计安全必读）。 |
| ★2 | `versioning.py` + `project_repo.py` | git 版本模型：Turn=commit、回滚=新 branch（重复回滚加后缀）、delete 模式需显式确认；ProjectRepo 封装 init/commit/branch/checkout/restore。 |
| 3 | `resource_types.py` | 9 类资源（8 设计类 + turn_summary 轮次摘要）及各自默认策略文本（仅存储元数据，数据层不执行策略）。 |
| 4 | `message_store.py` / `manifest.py` / `properties.py` | chat.jsonl 持久化；manifest.json / properties.md 读写。 |

## 4. 用户层后端 `app/api/` + `app/canvas/`

| 优先级 | 文件 | 内容 |
| --- | --- | --- |
| ★1 | `api/routes/workflow.py` | run/round 状态/stop + canvas GET/PUT + 便携 export/import。看它如何只做 HTTP 转发（Runtime 构造全部在 session 工厂里）。 |
| ★2 | `api/routes/chat.py` | 聊天全链路：发送→director 轮→每交换一个 Turn commit；删除/重发→git 回滚到前一 turn（含 director 消息删除=删除整个交换的语义）。 |
| 3 | `api/routes/resources.py` | 9 类资源列表/读写/历史；variables 只读（只维护不召回）。 |
| 4 | `api/routes/config.py` | 全局/项目配置 + 每 agent 配置（PUT 支持改名，identity=id）。 |
| 5 | `canvas/`（canvas_model/compile/workflow_loader/default_workflow.yaml） | 画布数据模型与校验；画布→树编译（feedback 线循环展开）；workflow.yaml 加载；默认画布。画布编译属用户层——agent 层不 import canvas。 |
| 6 | `api/routes/projects.py` / `novel.py` / `import_.py`；`api/server.py`；`api/schemas.py` | 项目 CRUD（id 系统生成）；小说只读通道（novels/chapter_*.txt）；角色卡导入；FastAPI 装配+CORS+IP 白名单；全部 wire 模型。 |
| 7 | `config_loader.py` / `project_init.py` / `project_paths.py` | 四层配置深合并（global<profile[stub]<project<run）；项目脚手架（资源目录+独立 git+Turn 0）；路径解析防穿越。 |

## 5. 兼容层 `app/compat/tavern_card/`

按 `docs/compat_tavern_card.md` 的模块表读即可：`card_migration.py`（facade）→ `card_recognition.py`（v2/v3/PNG 识别）→ `ir_definition.py`（CardIR/RuntimePlan）→ `content_builders.py`（字段→资源文本）→ `materializer.py`（落盘）→ `card_front.py`（正则前端渲染，**尚无 API 路由消费**）→ `preset_extract.py`（预设→PromptFragment，**尚无挂载消费方**）。外部生态字样只允许出现在这个包里。

## 6. 前端 `web/src/`

结构：`views/`（8 个 tab 视图）+ `stores/`（8 个 Zustand store，均可注入 ApiClient）+ `api/client.ts`（后端契约镜像）。审计顺序：

1. ★ `api/client.ts` — 前后端契约的前端侧，逐方法对照 `app/api/schemas.py`。
2. `stores/workflowStore.ts` + `views/WorkflowCanvasView.tsx` — 画布（react-flow）：读写 /canvas 端点。
3. `stores/chatStore.ts` + `views/ChatView.tsx` — 聊天与回滚同步。
4. `views/ResourceEditorView.tsx` / `NovelView.tsx` / `RpView.tsx` / `ConfigView.tsx` / `OverviewView.tsx` / `RunView.tsx` — 其余功能面。
5. `__tests__/` — vitest 单测（store 全覆盖）。

## 7. 测试与验证入口

- `tests/unit/`（按层分目录，约 700 个）：每层的行为规格；`tests/unit/runtime/test_llm_protocol.py` 是 LLM 协议正确性（W1）的规格。
- ★ `tests/integration/test_mock_round_e2e.py` — **一轮创作端到端验收**：mock 下跑一轮 → 章节文件 + 轮次摘要 + 恰好一个 Turn commit。想快速验证系统是否"活着"，跑它。
- `tests/integration/test_api.py` — 15 步全 API 流。
- 门禁命令：`python -m pytest tests/ -q`、`ruff check app/`、`mypy app/`、`cd web && npm run test -- --run && npm run build`。

## 8. 已知的有意状态（审计时不要误报）

- `runtime.py` 的并发原语无生产调用方——设计能力保留，executor 的 call_agent 目前同步完成（`await` 工具是形式的）。
- `transaction.AtomicTurn` 只包 workflow 轮；chat 轮由 chat 路由自行 commit（消息日志与资源同 commit）。
- `resource_types` 的 default_properties 只是存储的默认元数据（旧审计裁决：不违反"数据层不执行策略"）。
- maintainer 是 1:N（单 maintainer 管 5 资源），设计的"每资源唯一 maintainer"暂未拆分。
- 配置的 profile 层是空 stub；变量（variables）靠权限约定不发给模型，非机制强制。
- `card_front.py` 渲染器与 `preset_extract.py` 片段提取是"实现完成、消费未接"的两个断头（下期计划）。
