# NovelAgent 全面审计报告

> 审计日期: 2026-07-27
> 审计范围: `app/`（70 个 Python 文件，约 9,900 行）+ `web/src/`（views/stores/components/api/schemas）+ 全部文档 + 三条核心链路端到端静态追踪
> 审计依据: `docs/refactor_guide.md`（权威设计蓝图）
> 审计方法: 逐文件源码阅读 + import 关系验证 + 链路 trace + 测试/lint 实测
> 历史审计: 2026-07-10 层级架构审计已归档至 `docs/archive/audit_report_2026-07-10.md`（其 5 个确认违规均已修复）

---

## 一、总体结论

**分层重构是真实且高质量的；系统的短板不再是"层放错了"，而是创作主链路在"最后一公里"处断裂。**

- 上一轮审计的 5 个层级违规全部修复；层间 import 关系干净（data 层零对上依赖，runtime 不依赖 api，agents 不依赖 runtime/api），唯一残留反向依赖是 agents→canvas（用户层）一处。
- 测试健康度高：后端 pytest **667 通过 / 3 跳过**，ruff 与 mypy（70 文件）全绿；前端 vitest **110 通过**。
- 但 `npm run build` 红灯（zod v4 `z.record` 签名，3 处），且三条核心链路（一轮创作 / chat / 导入+RP）各有致命断点——多数断点代码内有自认注释（"not wired" / "known limitation"），属**未完成的集成**而非错误设计。

### 分级评价

| 维度 | 评级 | 一句话 |
| --- | --- | --- |
| 架构分层实现 | ★★★★☆ | 四层边界基本落实，工厂/权限面/预算/git 版本化骨架真实 |
| 代码质量 | ★★★★☆ | 类型严格、文档密度高、防御性好；但有 1 个安全漏洞 + 若干真实 bug |
| 设计目标达成 | ★★☆☆☆ | 核心创作循环无法产出可留存的正文与版本；递归召回不可用 |
| 前端对齐设计 | ★★☆☆☆ | 结构干净的骨架；画布持久化/RP 动态前端/导入 UI 是占位或假实现 |
| 文档与代码一致性 | ★★★☆☆ | 设计文档清晰；README 架构树偏差集中（本轮已修） |

---

## 二、致命断点（阻断设计目标，最高优先级）

| ID | 问题 | 证据 |
| --- | --- | --- |
| **F-1** | **正文（章节）无落盘通道**：8 类资源中没有"正文/轮次记忆"类型，writer 的 write 权限只有 `[notes]`，全仓库无任何代码写入 `novels/`——一轮创作的正文只存在于 director 的 feedback 字符串里，随 round 结束蒸发；小说查看器永远为空；"每轮正文归档 + summary 多级索引召回"（设计核心）无从谈起 | `resource_types.py:122-131`、`builtin/writer.yaml`、`project_init.py:106` |
| **F-2** | **workflow 轮不产生 git commit，AtomicTurn 零接入**："每轮=1 commit"与"事务原子性"在主创作路径双双缺席；round 写入以脏工作区残留，被下一次 chat 提交裹挟或使回滚 checkout 报 500 | `workflow.py:26-31`（自认）、`transaction.py:19`（无生产调用方） |
| **F-3** | **assistant 消息不保留 tool_calls**：`Message` 无 tool_calls 字段、encoder 不输出，而 tool 消息却带 `tool_call_id`——OpenAI 协议要求 tool 消息必须跟在携带对应 tool_calls 的 assistant 消息之后，真实端点第二次 director 迭代必 400。MockRunner 从不返回 tool_calls，现有测试测不到此路径 | `prompt_builder.py:39-55`、`providers/openai_chat.py:77-93`、`round_executor.py:322,391-399` |
| **F-4** | **filename 路径穿越绕过 permission 隔离**：`store.read/write/read_lines` 与 API `PUT /resources` 均不校验 filename，传 `../../config.yaml` 或绝对路径可读写项目外任意文件——LLM 工具面上的真实越权通道（对照：`novel.py` 有 `_TRAVERSAL_RE` 防护，标准不一致） | `store.py:88,100-104,189`、`resources.py:190-191` |
| **F-5** | **chat 轮 director tool_calls 不被 dispatch**：`_execute_chat_round` 只计预算不执行——RP 回合推进（复用 /api/chat）完全无状态更新；若真实 LLM 选择调工具，text 为空 → 前端显示 "[director unavailable]"。`chat.py:131` docstring 与实现矛盾 | `round_executor.py:415-461` |
| **F-6** | **MockRunner 永不产生 tool_calls**：默认配置（`runner: mock`）下"一轮"= director 单响应即结束——不调度子 agent、零写入、零 commit，且误报 `all_nodes_done`。mock 作为工程验证工具无法覆盖调度/工具/commit 路径 | `mock_runner.py:31`、`round_executor.py:341-342` |
| **F-7** | **model tier 名直发 API**：agent.model 的 "premium" 被原样当模型名发送，真实 LLM 路径开箱即 400；本应承接映射的 `ModelsConfig.agent_models` 无人使用 | `direct_runner.py:110-113`、`config_loader.py:61` |
| **F-8** | **前端 build 失败**：zod v4 移除 `z.record(valueSchema)` 单参重载，3 处 TS2554 | `canvasGraph.ts:7`、`ConfigView.tsx:65-66` |

## 三、设计符合性裁决（对照 refactor_guide.md 逐条）

| 设计条目 | 裁决 | 要点 |
| --- | --- | --- |
| 统一工具 read/search/write，不滥发 | 部分实现 | read/write + 4 个读变体（grep/glob/list/read_lines），schema 单一来源；`search` 拆分为 grep 族**合理**。**缺 `edit` 类工具**——write 只有整文件覆盖，"长数据增量维护、read→edit 策略"不存在 |
| permission 越权 reject | 已实现* | 定义在 agent 层、执行在 runtime 层（PermissionDenied 硬异常）；*但被 F-4 穿越绕过 |
| director 调度（call_agent/await/finalize，接线只定优先级可绕过） | 已实现 | LLM tool-call 循环真实；但 `await` 形同虚设（call_agent 同步完成，`run_concurrent/await_all/await_any` 零调用方），"并发执行、等待 Future"未兑现 |
| 每轮 = 1 git commit | 部分实现 | chat 交换有 commit；**workflow 轮没有**（F-2）——版本历史的主语搞反了（聊天有版本、创作没版本） |
| 回滚 = 新 branch（branch/delete 双接口） | 已实现 | `VersionManager.rollback` 正确；但重复回滚同一 turn 静默失效（Q-4）、删除 director 消息是 no-op（Q-5）；无独立回滚 API/前端入口，唯一路径是 chat 删除 |
| 事务原子性 | 未接入 | AtomicTurn 实现完整、测试通过、生产路径零调用（F-2） |
| 数据召回 5 种方式 | 2.5/5 | ①多级索引（正文）**未实现**（无正文资源，F-1）②单级召回 ✓ ③默认注入**未实现**（PromptBuilder 不注入任何资源内容，writer 看不到细纲/状态）④按需读入 ✓ ⑤只维护不召回 ✓（约定式） |
| recaller 递归召回（决策回 director） | 不可用 | 子 agent 单发（single-shot）、工具结果不回喂子 agent（代码自认 known limitation）——"读 summary→发现→再读"不可能发生 |
| maintainer 每资源唯一 | 未实现 | 单个 maintainer 统管 5 资源（1:N 简化）；maintainer/recaller 不共 prompt ✓ |
| budget/finalize/超时结束条件 | 已实现 | 三条件齐备，预算按 director 轮与子 agent 调用消费；瑕疵：`all_nodes_done` 误报语义、`Budget.remaining()` 字段语义反转 |
| 配置四层 global<profile<project<run | 部分实现 | global+project 深合并 ✓；**profile 是空 stub**；run override 仅 max_iterations 一个字段；`maximal_recursive_calling_depth` 是死配置（被 schema 默认值遮蔽） |
| agent 11 属性、配置静态/prompt 动态 | 基本实现 | 10 属性齐备 frozen + id 只读；`skills` 属性被有意删除（"a skill IS an agent"）——**但预设→文风链路断头**：`PromptFragment` 无消费方挂到 head/tail；head/tail "继承全局"未实现 |
| system agents（"帮我加节点"类） | 未实现 | 仅 director 一个 system agent |
| 项目隔离/系统控制 id/独立 git 仓 | 已实现 | 防穿越校验、独立 .git、Turn 0 scaffold 一致 |
| ST 解耦（字样仅在 compat） | 已实现 | grep 验证通过 |
| 角色卡导入 → 8 资源 + front/ | 后端已实现 | **前端无导入 UI**（postImport 无调用方且丢弃响应） |
| 变量只显示不发 AI | 约定式实现 | 靠 permission 配置约定 + API `_READ_ONLY_TYPES`，非机制保证 |
| 用户只与 director 交流；聊天增删改/重发同步回滚 | 基本实现 | 缺"改"；retry 前端状态 bug（Q-6）；chat 30s axios 超时 vs 同步等待真实 LLM 的隐患 |
| mode 切换 novel/rp | 后端已实现 | 前端 mode 零影响：不按 mode 切默认 tab，两种项目界面完全一样 |

## 四、设计模糊区的实现选择评价

| 选择 | 评价 |
| --- | --- |
| `search` 拆为 grep/glob/list/read_lines 工具族 | **合理**——与"grep/symbol search + 索引"维护策略一致，仍是通用动词 |
| name vs id 双索引（LLM/前端用 name，身份用 id，导入树 definition_id 钉住防碰撞劫持） | **合理**——解决可移植工作流的真实问题 |
| director_depth=0、call_agent 目标一律 depth 1 | **欠佳**——深度门控退化为死逻辑，"cross-stage recursive call rejected" 不可达 |
| 子 agent 单发（无自己的 tool-loop） | **欠佳**——当前架构最大能力短板，直接导致递归召回不可用、writer 无法"先读再写" |
| chat=Turn、workflow 轮不 commit 的双轨制 | **欠佳**——见 F-2 |
| 进程级 `_default_tools_cache` 全局 + 启动时注入 | 欠佳但可辩护——改 agents.yaml 需重启生效，对零技术用户是隐形坑 |
| agents→canvas 反向依赖（canvas_parser/workflow/workflow_loader import canvas_model） | **欠佳**——四层结构中唯一反向依赖；宜将画布 schema 下沉为中立模块或由用户层编译后交树 |
| `ScopedTools._resolve` 每次工具调用走 `create_resource`（读操作可能触发 scaffold 写盘） | 欠佳（轻）——幂等但打破"读无写副作用" |
| RoundState：session.state 裸 str + wire 层 Literal + cast | 欠佳（风格）——仍是两处约定，非"一处定义" |

## 五、代码质量问题清单（除致命项外）

后端（按严重度）：

| ID | 问题 | 证据 |
| --- | --- | --- |
| Q-1 | 子 agent 单发限制：工具调用执行一次、结果只给 director（同 F-5 同源的架构限制） | `round_executor.py:624-649` |
| Q-2 | PUT agent 无法改名：body.name 必须等于 path.name 且按现名查找——设计说 name"可随时更改" | `config.py:234-246` |
| Q-3 | `maximal_recursive_calling_depth` 死配置：schema 默认 1 遮蔽 config 值 | `schemas.py:105-107`、`session.py:173-176` |
| Q-4 | 重复回滚同一 turn 失效：`rollback/turn-X` 分支已存在时 checkout 现有分支 tip 而不重置 | `versioning.py:82-88` |
| Q-5 | 删除 director 消息是 no-op：`_turn_id_before` 返回消息自身所在 turn，回滚后消息原样存在 | `chat.py:155-182,237-265` |
| Q-6 | `Budget.remaining()` 把剩余量塞进 `used_*` 字段返回，语义反转 | `budget.py:133-145` |
| Q-7 | 死代码：`runtime.run_concurrent/await_all/await_any/RuntimeResult`、`permission.enforce()`、`PromptBuilder.reminders`、`ModelsConfig.agent_models`、`runtime.py:110-113` 不可达 else | grep 验证 |
| Q-8 | `RoundRegistry` 只增不减；round_id 用 monotonic+id() 理论可碰撞 | `workflow.py:100-131`、`session.py:211` |
| Q-9 | `store.read/read_lines` 裸 FileNotFoundError 喂给 LLM；feedback 硬编码中文文案；`RejectedCallRecord.reason` 机器码/人类短语混用 | `store.py:88,189`、`round_executor.py` 多处 |
| Q-10 | GET export 间接 mutate 内存 tree（embed_definitions 副作用）；`tree_model.from_dict` lazy import workflow_loader 私有函数 | `tree_model.py:250-251,274-281` |

前端（按严重度）：

| ID | 问题 | 证据 |
| --- | --- | --- |
| W-1 | **NovelView XSS 面**：`marked.parse` 直接 `dangerouslySetInnerHTML` 不消毒，章节内容（agent 生成或导入）的内联 HTML 原样注入 | `NovelView.tsx:79-83,169` |
| W-2 | **chatStore.retry 状态脱节**：后端已回滚删除的消息仍留在本地列表，与服务端 chat.jsonl 不一致直到手动刷新 | `chatStore.ts:87-106` |
| W-3 | **画布是假数据**：load() 不读后端 workflow 而是从 agent 列表合成线性链；后端已有的 `GET/POST /api/workflow/{id}/export` 与 `/import` 前端零调用；拉线/导入 JSON 永不落后端；且前端 CanvasGraph schema 与后端 export 便携格式不是同一 schema | `workflowStore.ts:90-123` |
| W-4 | 导入无 UI；ImportRequest 前后端字段对不上（前端多 `format`，缺 `card/display_name/mode`）；postImport 返回 void 丢弃响应 | `client.ts:196-200` vs `schemas.py:373-404` |
| W-5 | 错误处理只取 `e.message`，axios 场景下后端 `detail`（如"该项目已有运行中回合"）全部丢失 | 全部 8 个 store |
| W-6 | 历史版本只能看 commit 元数据，无法查看任意时间点内容（HistoryPanel onSelect 未接，后端也无 content-at-sha 端点） | `ResourceEditorView.tsx` |
| W-7 | 小说"编辑"是本地 draft 无保存路径；PUT resource 空内容 422 不拦截；chat 30s 超时隐患；rpStore/chatStore 双份真相；AgentEditForm 与 AgentConfigCard 约 140 行重复；若干死代码（client 5 个方法、workflowStore 5 个 action、HistoryPanel.onSelect 等） | 详见前端审计明细 |

## 六、文档一致性

- 代码内过时文本串仅 2 处（本轮已修）：`app/api/schemas.py:111` 引用已删除的 `app.agents.director`；`app/compat/tavern_card/__init__.py:12` "预设技能"→"预设片段"。
- README 架构树偏差集中（本轮已重写）：列了已删除的 `director.py/skills.py`、漏了 runtime 核心执行链（round_executor/runners/prompt_builder/session/tool_catalog/providers/mcp）、工具面描述过时（无 search 工具）、内置 agent 数量（6 非 5）、projection 已删除等。
- `docs/fix/director-layer-violation.md` 描述的问题已修复 → 归档为 `docs/archive/fix_director-layer-violation.md`。
- `samples/preset.json` 与当前提取逻辑不匹配（完整 ST 设置型预设的 `prompts` 列表不被 `_PRESET_SECTION_KEYS` 识别，实测提取结果为空）；`samples/st-char-front.json` 仍匹配。
- `docs/compat_tavern_card.md` 基本一致，模块表缺 `card_recognition/ir_definition/content_builders/materializer` 四个实际文件。

## 七、历史遗留核实（上轮"已知未做"7 条）

全部属实、未变：① `resource_types.default_properties` 维持旧裁决（不违设计）② `_READ_ONLY_TYPES/_TYPE_TITLES` 在 API 层 ③ chat 轮 tool_calls 不 dispatch（=F-5）④ round_executor 中文 feedback ⑤ `all_nodes_done` 误报语义 ⑥ AtomicTurn 未接入（=F-2）⑦ model tier 直发（=F-7）。

---

修复优先级与实施安排见 `docs/optimization_plan.md`；当前阶段综述见 `docs/stage_report.md`。
