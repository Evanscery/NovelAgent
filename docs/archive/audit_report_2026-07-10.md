# 层级架构一致性审计报告

> 审计日期: 2026-07-10
> 审计范围: `app/` 全部源码 (49 Python 文件) + `web/src/` 前端 (8 stores + views)
> 审计依据: 四层架构设计文档（用户/Runtime/Agent/数据）
> 审计方法: 逐文件源码阅读 + codegraph 调用链分析 + 层级职责比对

---

## 设计依据（唯一事实来源）

| 层 | 职责 | 禁止 |
|---|---|---|
| **用户层** | 前端、用户交互、工作流（画布）构建、配置、与用户相关的一切操作。完全与后端解耦。 | 后端逻辑、Runtime逻辑、Agent逻辑、数据管理 |
| **Runtime层** | 解析工具调用、找到函数、调用API、返回结果、实例化Agent、提供各种底层实现能力。收到需求后提供实现。 | 不能决定是否调用/为什么调用/下一步做什么/调用顺序/工作流控制/Agent行为。无业务决策、推理、规划、流水线控制、任务编排能力。 |
| **Agent层** | 系统核心。Agent类型、Agent实现、Agent实例、推理、决策、规划、权限、Agent约束、Agent行为、Agent之间协作、工具调用决策、数据维护策略、数据召回策略。Agent只表达意图，Runtime负责执行。 | — |
| **数据层** | 仅负责数据存储。提供读/写/更新/删除。不知道数据类型、数据语义、如何维护、如何召回、如何搜索。所有维护策略和召回策略属于Agent。数据层只是存储接口。 | 不知道数据类型/语义、不维护、不召回、不搜索（语义层面） |

---

## 已确认的审计裁决

以下裁决由用户确认，作为本次审计的判定基准：

1. **Runner（AgentRunner/DirectRunner/MockRunner）→ Runtime层**。其职责是调用API/返回结果/解析工具调用，属于Runtime的"具体实现"职责。物理上放在 `app/agents/runners/` 是层级错误。

2. **资源默认策略（resource_types.py 中的 default_properties）→ 不违反设计**。这些只是存储的默认元数据，Agent层可读取和覆盖；数据层本身不执行这些策略，只是存储它们。

3. **`app/api/` 和 `app/compat/` → 按职责映射到现有四层**。设计文档未定义这两层，但按其各自职责映射到四层中审计。

4. **API路由中的Runtime编排逻辑 → 属于Runtime越界**。API路由作为用户层后端部分，只应做HTTP接口转发。构造 Runtime/RoundExecutor/BudgetTracker 并编排后台异步执行属于Runtime层职责越界。

5. **画布数据模型（canvas_model.py）→ 属用户层**。设计文档说用户层负责"工作流（画布）构建"，画布数据模型放在 `app/agents/` 是层级错误。

---

## 审计结果

### 问题 1: Runner 物理位于 Agent 层

--------------------------------

**Component:** `app/agents/runners/` (base.py, direct_runner.py, mock_runner.py)

**Current Layer:** Agent 层（物理路径 `app/agents/runners/`）

**Expected Layer:** Runtime 层

**Observed Responsibility:**
- `AgentRunner`（base.py）：定义抽象 Runner 接口，接收 agent + prompt，返回 AgentResponse
- `DirectRunner`（direct_runner.py）：调用 OpenAI 兼容 API，解析 HTTP 响应为 AgentResponse（含 tool_calls 解析），处理超时/重试/退避
- `MockRunner`（mock_runner.py）：确定性模拟响应，无 LLM 调用
- `ToolCall`、`TokenUsage`、`AgentResponse` 数据结构定义（base.py）：这些是 LLM 调用的返回结果和工具调用解析结果

**Expected Responsibility:** 这些应属于 Runtime 层。设计文档明确 Runtime 职责包括"调用API"、"返回结果"、"解析工具调用"。Runner 的全部职责就是调用 API 并返回解析后的结果，这正是 Runtime 的"具体实现"。

**Violation Type:** Layer Placement（组件放错层）

**Evidence:**
- `app/agents/runners/base.py:1` — 文件开头即声明 "Abstract AgentRunner base class — the LLM-call boundary"
- `app/agents/runners/direct_runner.py:1` — "Direct runner — calls an OpenAI-compatible chat completions endpoint"
- `app/agents/runners/direct_runner.py:70-93` — `_parse_tool_calls()` 解析工具调用
- `app/agents/runners/direct_runner.py:96-103` — `_parse_usage()` 解析 token 用量
- `app/runtime/runtime.py:23` — Runtime 类导入 `from app.agents.runners.base import AgentResponse, AgentRunner, RunnerAgent`，Runtime 层依赖了 Agent 层目录下的代码

**Design Reference:**
- Runtime 层职责："调用API"、"返回结果"、"解析工具调用"
- Runtime 层："提供各种底层实现能力"

**Confidence:** 100%（用户已确认 Runner 属于 Runtime 层）

---

### 问题 2: API 路由中直接构造和编排 Runtime 组件

--------------------------------

**Component:** `app/api/routes/workflow.py` — `_execute_round()` 函数 + `run_workflow()` 端点；`app/api/routes/chat.py` — `_produce_director_reply()` 函数

**Current Layer:** 用户层（API 作为用户层后端部分）

**Expected Layer:** Runtime 层

**Observed Responsibility:**
- `workflow.py:300-313`：在 API 路由中直接构造 `Runtime`、`BudgetTracker`、`AgentRegistry`，并通过 `RUNNER_FACTORY()` 创建 Runner
- `workflow.py:236-243`：在 API 路由中直接构造 `RoundExecutor`，注入 runtime/runner/registry/budget
- `workflow.py:243-247`：在 API 路由中调用 `executor.execute_round()` 编排后台异步执行 round
- `workflow.py:320-331`：在 API 路由中创建 `asyncio.Task` 调度后台执行
- `chat.py:165-183`（`_produce_director_reply`）：同样在 API 层构造 Runtime/BudgetTracker/RoundExecutor 并执行 round

**Expected Responsibility:** API 路由作为用户层后端部分，只应做 HTTP 接口转发（接收请求、返回响应）。构造 Runtime 组件、编排 round 执行属于 Runtime 层的"任务编排"和"流水线控制"职责。Runtime 应自身暴露一个高层接口供 API 调用，而非由 API 层手动组装 Runtime 内部组件。

**Violation Type:** Responsibility Leakage（职责越界）+ Boundary Violation（层级边界破坏）

**Evidence:**
- `workflow.py:301` — `agent_registry = build_default_registry()` — API 层构建 Agent 注册表
- `workflow.py:302-308` — `runtime = Runtime({...})` — API 层构造 Runtime 实例
- `workflow.py:312` — `budget = BudgetTracker(...)` — API 层构造预算追踪器
- `workflow.py:236-243` — `executor = RoundExecutor(...)` — API 层构造执行器并注入所有 Runtime 组件
- `chat.py:167-168` — `runtime = Runtime({...})` / `budget = BudgetTracker(...)` — chat 路由重复同样的构造
- `chat.py:171-177` — `executor = RoundExecutor(...)` — chat 路由构造执行器

**Design Reference:**
- 用户层："完全与后端解耦"
- Runtime 层："提供各种底层实现能力"
- 用户已确认："API属用户层，编排逻辑是Runtime越界"

**Confidence:** 100%（用户已确认 API 属用户层，编排 Runtime 组件属于 Runtime 越界）

---

### 问题 3: 画布数据模型物理位于 Agent 层

--------------------------------

**Component:** `app/agents/canvas_model.py`（CanvasNode, CanvasWire, CanvasGraph）

**Current Layer:** Agent 层（物理路径 `app/agents/canvas_model.py`）

**Expected Layer:** 用户层

**Observed Responsibility:**
- `CanvasNode`：用户画布上的节点（id, agent_name, description, params）—— 用户可编辑的工作流节点定义
- `CanvasWire`：用户画布上的连线（from_node, to_node, repeat_count）—— 用户可编辑的接线
- `CanvasGraph`：用户可编辑的完整画布（nodes + wires），含拓扑验证逻辑
- 这些是用户在前端画布编辑器中创建和修改的数据结构

**Expected Responsibility:** 画布数据模型属于用户层职责（"工作流（画布）构建"）。用户层负责画布构建，画布的数据模型应属于用户层。

**Violation Type:** Layer Placement（组件放错层）

**Evidence:**
- `canvas_model.py:3` — "The canvas is the user-editable workflow definition"
- `canvas_model.py:17` — `CanvasNode` 文档："A node on the user canvas"
- `canvas_model.py:35` — `CanvasWire` 文档："A wire on the user canvas"
- `canvas_model.py:52` — `CanvasGraph` 文档："The user-editable canvas: nodes + wires"
- 前端 `workflowStore.ts:24-43` 直接镜像了这些类型（`CanvasNodeData` / `CanvasWireData` / `CanvasGraphData`），证明它们是用户层数据模型
- 物理路径 `app/agents/canvas_model.py` 将用户层数据模型放在了 Agent 层目录下

**Design Reference:**
- 用户层职责："工作流（画布）构建"
- 用户已确认："画布数据模型属用户层"

**Confidence:** 100%（用户已确认画布模型属用户层）

---

### 问题 4: ToolCall / AgentResponse / TokenUsage 数据结构位于 Agent 层

--------------------------------

**Component:** `app/agents/runners/base.py` — `ToolCall`, `TokenUsage`, `AgentResponse`, `RunnerAgent` Protocol

**Current Layer:** Agent 层（物理路径 `app/agents/runners/base.py`）

**Expected Layer:** Runtime 层

**Observed Responsibility:**
- `ToolCall`（base.py:41-50）：从 LLM 响应中解析出的工具调用——这是"解析工具调用"的结果
- `TokenUsage`（base.py:54-58）：LLM 调用的 token 用量——这是"调用API"的返回结果
- `AgentResponse`（base.py:62-82）：LLM 调用的规范化响应——这是"返回结果"
- `RunnerAgent` Protocol（base.py:17-37）：Runner 需要的最小 Agent 视图

**Expected Responsibility:** 这些数据结构是 Runtime 层"调用API"、"返回结果"、"解析工具调用"的产物，应属于 Runtime 层。由于 Runner 已被确认属于 Runtime 层，Runner 产出的数据结构也应随 Runner 移至 Runtime 层。

**Violation Type:** Layer Placement（组件放错层）—— 与问题 1 同源

**Evidence:**
- `base.py:41` — `ToolCall` 是 "A single tool call parsed from a model response"
- `base.py:54` — `TokenUsage` 是 "Token accounting for a single model response"
- `base.py:62` — `AgentResponse` 是 "The normalized result of a single runner invocation"
- `app/runtime/runtime.py:23` — `from app.agents.runners.base import AgentResponse, AgentRunner, RunnerAgent`
- `app/runtime/round_executor.py:64-67` — `from app.agents.runners.base import AgentRunner, ToolCall`
- `app/runtime/tool_dispatcher.py:23` — `from app.agents.runners.base import ToolCall`
- 多个 Runtime 层文件依赖 Agent 层目录下的这些数据结构

**Design Reference:**
- Runtime 层职责："调用API"、"返回结果"、"解析工具调用"
- 用户已确认 Runner 属于 Runtime 层

**Confidence:** 100%（与问题 1 同源，Runner 及其全部产出物均属 Runtime 层）

---

### 问题 5: store.py（数据层）中的 permission_check 方法

--------------------------------

**Component:** `app/data/store.py:197-215` — `ResourceStore.permission_check()`

**Current Layer:** 数据层

**Expected Layer:** 不属于数据层（权限属于 Agent 层，权限执行属于 Runtime 层）

**Observed Responsibility:**
```python
def permission_check(self, agent_permission: dict[str, list[str]], resource: Resource) -> bool:
```
该方法接收一个 agent 的权限字典和一个资源，检查该资源类型是否出现在权限的 read 或 write 列表中。这是一个权限检查逻辑——判断 agent 是否有权访问某资源。

**Expected Responsibility:** 设计文档说数据层"仅负责数据存储"，提供"读/写/更新/删除"。权限属于 Agent 层（"权限"列在 Agent 层职责中），权限执行属于 Runtime 层（`ScopedTools` 中的 `_check` 方法）。数据层不应包含权限检查逻辑。

**Violation Type:** Responsibility Leakage（职责越界）

**Evidence:**
- `store.py:197-215` — `permission_check` 方法在数据层的 `ResourceStore` 类中
- 该方法仅被测试代码调用（`tests/unit/data/test_store.py`），生产代码中无任何调用方——实际权限执行由 `app/runtime/permission.py:ScopedTools._check()` 承担
- `app/runtime/permission.py:249-253` — `ScopedTools._check()` 是实际使用的权限检查方法
- codegraph 调用链分析确认 `permission_check` 的 5 个调用方全部在 `tests/unit/data/test_store.py` 中

**Design Reference:**
- 数据层："仅负责数据存储"、"提供读/写/更新/删除"
- Agent 层职责包括："权限"
- 设计文档未赋予数据层任何权限相关职责

**Confidence:** 100%

---

### 问题 6: RoundExecutor 中的工作流控制逻辑（待确认）

--------------------------------

**Component:** `app/runtime/round_executor.py` — `RoundExecutor._execute_workflow_round()`

**Current Layer:** Runtime 层

**Expected Layer:** 部分逻辑属于 Runtime 层（正确），部分属于 Agent 层（越界）

**Observed Responsibility:**
RoundExecutor 位于 Runtime 层（正确），但其实际承担的职责混合了两种层级的责任：

**属于 Runtime 层的职责（正确）：**
- 发送 director 请求通过 runtime（round_executor.py:285-287）
- 解析 tool_calls 并分发（round_executor.py:328-494）
- 预算消费和递归深度控制（round_executor.py:267-269, 310-318, 529-551）
- 超时和错误处理（round_executor.py:288-302）

**可能越界的职责：**
- `round_executor.py:271-281`：组装 director prompt——拼接 `parse_agent_to_prompt(director, context, flow_sequence)` + feedback_block。这调用了 Agent 层的 parser，本身是 Runtime 调用 Agent 层接口，但 prompt 组装逻辑（决定哪些信息注入 director 上下文）可能属于 Agent 行为决策
- `round_executor.py:245`：`generate_flow_sequence(tree)`——调用 Agent 层生成工作流执行顺序文本，然后注入 director prompt。工作流执行顺序的生成是否属于 Runtime 的"具体实现"还是 Agent 的"规划"职责存在歧义

**Expected Responsibility:** 设计文档说 Runtime "不能决定调用顺序"和"没有工作流控制能力"。但 RoundExecutor 驱动的 tool-call 循环（send → parse → dispatch → feedback → repeat）本质上是在控制工作流的执行流程。虽然执行顺序由 director 的 LLM 决策驱动，但循环控制、终止条件判断、结果回传编排由 Runtime 承担。

**Violation Type:** Boundary Violation（层级边界模糊）—— 需要确认循环编排是否属于 Runtime 的"提供实现"还是越界到了"工作流控制"

**Evidence:**
- `round_executor.py:265-373` — while 循环驱动 director 的多轮 tool-call，包含：预算检查 → prompt 组装 → 发送请求 → 解析响应 → 消费预算 → 分发 tool_calls → 回传结果 → 循环
- `round_executor.py:271-281` — 组装 director prompt（调用 Agent 层 parser + 自行拼接 feedback）
- `round_executor.py:245` — 调用 `generate_flow_sequence(tree)` 生成执行顺序

**Design Reference:**
- Runtime 层："不能决定调用顺序"、"没有工作流控制能力"、"没有流水线控制能力"、"没有任务编排能力"
- Runtime 层："收到需求之后提供实现"
- Agent 层："工具调用决策"

**Confidence:** 80% —— RoundExecutor 的 tool-call 循环是否构成"工作流控制"存在歧义。一方面，director 通过 LLM 决策驱动每一步（Agent 行为）；另一方面，循环结构本身由 Runtime 控制（循环、终止、回传）。设计文档说 Runtime"没有工作流控制能力"，但 RoundExecutor 的循环结构正是工作流控制。由于设计文档同时说 Runtime 负责"解析工具调用"和"返回结果"，这些操作需要一个循环来串联，因此循环本身可能是"提供实现"的合理部分。**此问题无法在不补充设计定义的情况下达到 100% 置信度。**

---

### 问题 7: store.py（数据层）中的 search 方法（待确认）

--------------------------------

**Component:** `app/data/store.py:118-149` — `ResourceStore.search()`

**Current Layer:** 数据层

**Expected Layer:** 设计文档说数据层"不知道如何搜索"，搜索策略属于 Agent 层

**Observed Responsibility:**
`ResourceStore.search()` 执行 grep 风格的子串搜索：遍历资源目录下所有内容文件，对每行做大小写不敏感的子串匹配，返回 `SearchHit` 列表（含文件名、行号、匹配文本、上下文窗口）。

**Expected Responsibility:** 设计文档说数据层"不知道如何搜索"，"所有召回策略属于Agent"。但这里的 `search` 方法实现了具体的搜索逻辑（子串匹配 + 上下文窗口构建）。问题在于：这是数据层提供的"搜索"基础能力（类似数据库的 LIKE 查询），还是数据层在执行本应属于 Agent 的"召回策略"？

**Violation Type:** 可能的 Responsibility Leakage（职责越界）—— 取决于 search 是"存储层基础能力"还是"召回策略实现"

**Evidence:**
- `store.py:118` — `def search(self, resource: Resource, query: str) -> list[SearchHit]:` 文档说明 "Grep-style substring search"
- `store.py:126-148` — 实现了正则编译、文件遍历、行匹配、上下文窗口构建
- `SearchHit`（store.py:16-22）包含 filename, line_number, matching_text, context —— 这已超出纯存储接口，包含了搜索结果的语义结构
- `app/runtime/permission.py:204-224` — `ScopedTools.search()` 调用 `store.search()`，说明 search 是通过权限层暴露给 agent 的工具

**Design Reference:**
- 数据层："不知道如何搜索"
- Agent 层："所有召回策略属于Agent"
- 数据层："数据层只是存储接口"

**Confidence:** 85% —— 设计文档说数据层"不知道如何搜索"，但 `search()` 方法确实在数据层实现了搜索逻辑。然而，也可以解释为：这是数据层提供的"读"操作的变体（搜索 = 定向读取），类似数据库的全文搜索索引。设计文档说数据层"提供读"，search 可被视为一种"读"。**此问题的置信度未达 100%，因为"搜索"是否属于数据层的"读"职责存在歧义。**

---

### 问题 8: store.py（数据层）中的 _update_index 方法构建搜索索引（待确认）

--------------------------------

**Component:** `app/data/store.py:219-238` — `ResourceStore._update_index()`

**Current Layer:** 数据层

**Expected Layer:** 设计文档说数据层"不知道如何搜索"

**Observed Responsibility:**
`_update_index()` 在每次写入后扫描所有内容文件的 Markdown 标题（`#` 到 `######`），构建一个 `.index` 文件作为"符号搜索友好的列表"。这是一个搜索索引构建逻辑。

**Expected Responsibility:** 如果数据层"不知道如何搜索"，那么构建搜索索引（为搜索服务的基础设施）也不应属于数据层。索引构建隐含了对数据语义的理解（知道什么是"标题"、什么是"可搜索的符号"）。

**Violation Type:** 可能的 Responsibility Leakage（职责越界）—— 与问题 7 同源

**Evidence:**
- `store.py:219` — `def _update_index(self, resource: Resource) -> None:` 文档说明 "Rebuild the `.index` file"
- `store.py:227` — `heading_re = re.compile(r"^(#{1,6})\s+(.+)")` — 解析 Markdown 标题结构
- `store.py:230-237` — 遍历文件、提取标题行、写入索引文件
- `store.py:116` — 在 `write()` 方法中调用 `self._update_index(resource)`，每次写入自动更新索引

**Design Reference:**
- 数据层："不知道如何搜索"
- 数据层："数据层只是存储接口"

**Confidence:** 85% —— 与问题 7 同源。索引构建是搜索的基础设施，但也可以被视为存储层的内部维护（类似数据库自动维护 B-tree 索引）。设计文档的"不知道如何搜索"是否涵盖"不构建搜索索引"存在歧义。

---

### 问题 9: tools.py（Agent层）中的 ToolExecutor 承担 Runtime 职责（待确认）

--------------------------------

**Component:** `app/agents/tools.py:137-217` — `ToolExecutor` 类

**Current Layer:** Agent 层（物理路径 `app/agents/tools.py`）

**Expected Layer:** Runtime 层

**Observed Responsibility:**
`ToolExecutor` 包装 `ScopedTools`（Runtime 层的权限作用域工具），暴露 `read`/`search`/`write` 三个方法。其文档说明它是"agent-facing tool executor"——在 runtime 中为每个 agent 构造一个实例。

但 `ToolExecutor` 实际上不承担任何 Agent 层职责（不推理、不决策、不规划）。它只是 `ScopedTools` 的薄包装，将工具调用路由到数据层。这属于 Runtime 的"提供各种底层实现能力"。

**Expected Responsibility:** `ToolExecutor` 是工具执行的胶水代码，属于 Runtime 层的"找到函数"、"调用"职责。它不表达 Agent 意图，不做决策。

**Violation Type:** Layer Placement（组件放错层）

**Evidence:**
- `tools.py:137` — `class ToolExecutor:` 文档说明 "Agent-facing tool executor wrapping a ScopedTools"
- `tools.py:140-141` — "The runtime constructs one `ToolExecutor` per agent per round" —— 明确说明由 Runtime 构造
- `tools.py:159-160` — `def __init__(self, scoped_tools: ScopedTools)` —— 接收 Runtime 层的 `ScopedTools`
- `tools.py:169-217` — `read`/`search`/`write` 方法直接委托给 `self._scoped`，无任何决策逻辑
- `tools.py:36-37` — `from app.data.store import SearchHit` / `from app.runtime.permission import ScopedTools` —— Agent 层文件依赖 Runtime 层

**Design Reference:**
- Runtime 层："找到函数"、"调用"、"提供各种底层实现能力"
- Agent 层："Agent只表达意图，Runtime负责执行"

**Confidence:** 90% —— `ToolExecutor` 纯粹是执行胶水，无 Agent 层职责。但设计文档在 Agent 层下列出了"工具调用决策"——`ToolExecutor` 不做决策（决策由 director LLM 做），只做执行。不过，`tools.py` 中的 `TOOL_SCHEMAS` 和 `TOOL_REGISTRY` 定义了工具的元数据（schema），这部分可能属于 Agent 层（Agent 需要知道有哪些工具可用）。**整体文件中 `ToolExecutor` 类应属 Runtime 层，但 `TOOL_SCHEMAS`/`TOOL_REGISTRY` 的归属存在歧义。**

---

## 设计文档未定义，无法审计的组件

以下组件在设计文档中未定义其层级归属，按规则输出"设计文档未定义，无法审计"：

### A. `app/api/` 整体层级

设计文档定义的四层为用户/Runtime/Agent/数据，未定义 API/后端接口层。用户已确认"按职责映射到现有四层"。映射结果：
- `app/api/server.py`：FastAPI 应用构造、CORS、IP 白名单 → 用户层（后端接口配置）
- `app/api/routes/projects.py`：项目 CRUD → 用户层（配置管理）
- `app/api/routes/config.py`：配置读写 → 用户层（配置管理）
- `app/api/routes/resources.py`：资源读写 API → 用户层（数据访问接口，委托数据层）
- `app/api/routes/novel.py`：小说查看 → 用户层（用户交互接口）
- `app/api/routes/import_.py`：角色卡导入 → 用户层（用户交互接口）
- `app/api/routes/workflow.py`：工作流执行 → **部分越界**（见问题 2）
- `app/api/routes/chat.py`：聊天接口 → **部分越界**（见问题 2）
- `app/api/schemas.py`：Pydantic 模型 → 用户层（接口数据结构）
- `app/api/routes/_message_store.py`：JSONL 持久化 → 数据层职责（文件存储），但在 API 目录下
- `app/config_loader.py`：配置加载 → 用户层（配置管理）
- `app/project_init.py`：项目脚手架 → 用户层（配置管理）
- `app/project_paths.py`：路径解析 → 工具函数，无明确层级

### B. `app/compat/` 整体层级

设计文档未定义兼容层。用户已确认"按职责映射到现有四层"。映射结果：
- `app/compat/tavern_card/` 整体：角色卡解析 → 兼容导入逻辑，将外部格式转换为内部 8 资源结构。这属于数据格式转换，不涉及推理/决策/规划。可映射为数据层（数据格式转换 + 写入）或用户层（导入接口的后端部分）。由于它直接写入资源文件（`materializer.py` 调用 `_write_resource_file`），且不经过 Agent 层，其行为更接近数据层的"写"操作。但 compat 层的 `preset_extract.py` 调用了 `app.agents.skills.extract_skills_from_preset`（Agent 层），因此它同时涉及 Agent 层接口。

---

## 审计结论

### 确认的违规（Confidence 100%）

| # | 组件 | 违规类型 | 当前层 | 应属层 |
|---|------|---------|--------|--------|
| 1 | `app/agents/runners/` (Runner 全部) | Layer Placement | Agent | Runtime |
| 2 | `app/api/routes/workflow.py` + `chat.py` 中的 Runtime 编排 | Responsibility Leakage + Boundary Violation | 用户层(API) | Runtime |
| 3 | `app/agents/canvas_model.py` (画布数据模型) | Layer Placement | Agent | 用户 |
| 4 | `app/agents/runners/base.py` 中的数据结构 (ToolCall/AgentResponse/TokenUsage) | Layer Placement | Agent | Runtime |
| 5 | `app/data/store.py:permission_check()` | Responsibility Leakage | 数据 | 不属于数据层（权限属 Agent，执行属 Runtime） |

### 置信度不足 100% 的问题（需补充设计定义）

| # | 组件 | 违规类型 | 置信度 | 待确认歧义 |
|---|------|---------|--------|-----------|
| 6 | `RoundExecutor._execute_workflow_round()` 的循环编排 | Boundary Violation | 80% | tool-call 循环是否构成 Runtime 的"工作流控制"越界 |
| 7 | `store.py:search()` 执行搜索 | Responsibility Leakage | 85% | "搜索"是否属于数据层的"读"职责 |
| 8 | `store.py:_update_index()` 构建搜索索引 | Responsibility Leakage | 85% | 索引构建是否属于"不知道如何搜索"的禁止范围 |
| 9 | `tools.py:ToolExecutor` | Layer Placement | 90% | 工具执行胶水代码的层级归属，TOOL_SCHEMAS 与 ToolExecutor 可能需分开归属 |

### 未发现违规的组件

| 组件 | 层 | 结论 |
|------|---|------|
| `app/agents/agent.py` (Agent 数据类) | Agent | ✅ 符合设计——Agent 属性模型，含权限/工具/技能 |
| `app/agents/parser.py` (prompt 组装) | Agent | ✅ 符合设计——将 Agent 属性动态组装为 prompt |
| `app/agents/skills.py` (技能注册表) | Agent | ✅ 符合设计——技能定义和注册属于 Agent 层 |
| `app/agents/registry.py` (Agent 注册表) | Agent | ✅ 符合设计——Agent 实例管理 |
| `app/agents/builtin/*.yaml` (内置 Agent 定义) | Agent | ✅ 符合设计——Agent 属性集 |
| `app/agents/default_workflow.yaml` | Agent | ✅ 符合设计——默认工作流定义 |
| `app/agents/canvas_parser.py` (画布→树解析) | Agent | ✅ 符合设计——将用户画布编译为工作流树（Agent 调度基础结构） |
| `app/agents/tree_model.py` (工作流树模型) | Agent | ✅ 符合设计——工作流树是 Agent 调度的内部结构 |
| `app/agents/flow_sequence.py` (执行顺序生成) | Agent | ✅ 符合设计——为 director 生成执行顺序上下文 |
| `app/agents/workflow_loader.py` (工作流加载) | Agent | ✅ 符合设计——加载工作流配置 |
| `app/runtime/runtime.py` (执行基础设施) | Runtime | ✅ 符合设计——超时/重试/并发，不引用具体 Agent |
| `app/runtime/budget.py` (预算追踪) | Runtime | ✅ 符合设计——纯计数器，无业务决策 |
| `app/runtime/transaction.py` (原子事务) | Runtime | ✅ 符合设计——事务协调，数据层执行 |
| `app/runtime/permission.py` (权限执行) | Runtime | ✅ 符合设计——权限定义在 Agent 层，执行在 Runtime 层 |
| `app/runtime/tool_dispatcher.py` (工具分发) | Runtime | ✅ 符合设计——解析工具调用并路由 |
| `app/data/resource.py` (资源基类) | 数据 | ✅ 符合设计——资源抽象 |
| `app/data/resource_types.py` (8 类资源) | 数据 | ✅ 符合设计——资源类型定义（默认策略为存储元数据，不执行） |
| `app/data/store.py` (CRUD 主体) | 数据 | ✅ 基本符合——read/write/create/list_resources 属存储职责（search/permission_check/_update_index 见问题 5/7/8） |
| `app/data/properties.py` (属性解析) | 数据 | ✅ 符合设计——properties.md 读写 |
| `app/data/manifest.py` (清单读写) | 数据 | ✅ 符合设计——manifest.json 读写 |
| `app/data/versioning.py` (版本管理) | 数据 | ✅ 符合设计——git 版本操作 |
| `app/data/project_repo.py` (项目仓库) | 数据 | ✅ 符合设计——git 操作 |
| `app/data/projection.py` (工作树投影) | 数据 | ✅ 符合设计——读取当前工作树状态 |
| `web/src/stores/*.ts` (8 个 Zustand store) | 用户 | ✅ 符合设计——纯 API 封装 + UI 状态，无后端/Runtime/Agent 逻辑 |
| `web/src/` 前端整体 | 用户 | ✅ 符合设计——前端交互、画布编辑、配置 UI，无后端逻辑泄露 |

---

## 违规汇总

共发现 **5 个确认违规**（Confidence 100%）和 **4 个待确认问题**（Confidence < 100%）。

确认违规的根因可分为两类：

1. **物理位置错误**（问题 1, 3, 4, 9）：组件被放在了错误的目录/层级下。Runner 及其数据结构应在 Runtime 目录下而非 Agent 目录下；画布模型应在用户层而非 Agent 层；ToolExecutor 应在 Runtime 层而非 Agent 层。

2. **职责越界**（问题 2, 5）：API 路由承担了 Runtime 编排职责；数据层承担了权限检查职责。

待确认问题的根因是设计文档的边界定义不够精确：tool-call 循环是否属于"工作流控制"、搜索是否属于数据层的"读"职责、索引构建是否属于"不知道如何搜索"的禁止范围——这些需要设计文档补充定义才能确定。

---

## 2026-07-27 复审结论

旧报告的 **5 个确认违规均已修复**：

1. Runner 及其数据结构已迁至 Runtime 层（`app/runtime/runners/`）。
2. 画布模型已迁至用户层目录 `app/canvas/`。
3. `ToolExecutor` 已删除（工具执行统一走 runtime 的 dispatcher）。
4. API 层的 Runtime 编排已收敛到 `create_round_session` 工厂（API 不再直接构造 Runtime/BudgetTracker/RoundExecutor）。
5. `store.permission_check` / `store.search` / `store._update_index` 已从数据层删除。

本轮又完成：

- **Permission 定义迁至 agent 层**（消除 agents→runtime 反向依赖）。
- **runner/预算/深度接入 config**（`models.yaml` / `runtime.yaml`）。
- **每 agent 独立权限工具面**：子 agent 的工具调用真实执行（各自的 permission 生效）。
- **双状态机合并**：`RoundState` 增加 `stopped`，round 状态一处定义。
- **chat 使用真实项目路径**（不再用临时/占位路径）。
- **director 移除必拒的 `write` 工具**。
- **message_store 迁数据层**。
- **约 800 行确认死代码删除**（projection、文本解析路径、死 facade 等）。

已知未做（有意保留）：

- `resource_types` 的 `default_properties` 维持旧裁决。
- `_READ_ONLY_TYPES` / `_TYPE_TITLES` 仍在 API 层。
- chat 轮的 director `tool_calls` 不 dispatch。
- `round_executor` 中文 feedback 文案。
- `all_nodes_done` 语义。
- `transaction.AtomicTurn` 未接入生产路径。
- model tier 名直发 API。