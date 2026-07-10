# Director 层级越界事故修复报告

> 日期: 2026-07-10
> 严重级别: **P0 Critical — 架构层级越界**
> 事故状态: **已识别，待修复**

---

## 一、事故描述

### 核心问题

`Director` 类（`app/agents/director.py`）在设计上应是一个 **agent 层的智能体**——通过 LLM 调用产出决策，使用 `call_agent`/`await` 工具调度其他 agent。

实际实现中，`Director.run_round()` 是一个 **runtime 层的硬编码调度器**：

```python
# director.py:174 — 当前实现
ordered_nodes = sorted(tree.all_nodes.values(), key=lambda n: (n.depth, n.id))
for node in ordered_nodes:                    # ← 硬编码遍历，非 LLM 决策
    target_agent = self._resolve_node_agent(node)
    response = await runtime.send_request(target_agent, runner, node_prompt)  # ← 直接调度
```

Director 没有做任何"决策"——它机械地按 BFS 遍历树节点，逐个发 LLM 请求。这不是 agent 行为，这是 runtime 行为。

### 层级越界分析

| 层 | 职责 (refactor_guide) | 应归属 | 当前实际 |
|---|---|---|---|
| **Agent 层** | Director 是一个 agent，用 `call_agent`/`await` 工具决策调度 | Director 应只有 Agent 属性 + prompt，通过工具调用表达决策 | ❌ `Director` 类包含 `run_round` 调度循环、预算消费、递归检查——全是 runtime 职责 |
| **Runtime 层** | 发送请求、并发执行、等待 Future、超时、重试、提交、回滚、解析工具调用并调度 | 编排循环（调 director LLM → 解析工具调用 → 调度 call_agent → 回传结果 → 循环）应在此层 | ❌ Runtime 仅做 `send_request`，编排逻辑泄露到了 agent 层的 Director |
| **数据层** | 存储、索引、访问、权限校验 | 不变 | ✅ 正常 |

### 后果链

1. **Director 不是 agent** — 它没有"先思考再决策"的环节，不会根据上下文决定绕过节点、调整顺序、或递归召回
2. **`call_agent`/`await` 工具是死代码** — `DirectorToolRegistry`（刚创建）定义了工具但没接入运行时调度
3. **工作流树失去了"可绕过"语义** — guide:87 明确说"不保证每个节点均有数据流过（可被绕过），由主agent决策"，但 `run_round` 遍历所有节点
4. **递归召回不可能实现** — guide:240-255 说 recaller 可以建议"need lore"→director 决策→递归召回，但当前没有 director LLM 决策环节，无法响应建议

### 与 refactor_guide 的冲突

| guide 条目 | 设计意图 | 当前实现 | 冲突 |
|---|---|---|---|
| guide:87 | "接线只决定优先级...由主agent决策" | `run_round` 硬编码 BFS 遍历 | ❌ director 不决策 |
| guide:92-95 | "director：决策，任务分配。主要工具：call_agent, await" | `call_agent` 方法存在但 `run_round` 不调用它 | ❌ 工具未接入 |
| guide:103-109 | "所有流程完成，主动调用 Finalize" | 没有 Finalize 工具调用机制 | ❌ director 无法主动结束 |
| guide:126-138 | Runtime "解析agent的工具调用请求并实际调取工具" | Runtime 只做 send_request，工具调度在 Director | ❌ 职责错位 |

---

## 二、审计-修复过程为何未发现

### 根因

1. **审计报告将此归类为"部分实现"而非"架构事故"** — audit_report §3.2 列出了 "director call_agent/await 未接入工具系统" 和 "数据召回的递归机制部分实现"，但标记为 P1，未升级为 P0 架构层级越界
2. **修复计划将其降级** — 我们将其拆为两个 P1 todo（Todo 7: DirectorToolRegistry 数据结构 + Todo 8: suggestions 数据管道），定义为"结构性基础，运行时集成是 future work"，但没有质疑为什么 future work 会阻断 director 作为 agent 的核心功能
3. **验证只检查了"是否通过测试"** — 所有测试都基于 `run_round` 的硬编码遍历行为编写，测试通过 ≠ 设计正确
4. **没有做层级归属检查** — 修复前没有问"这个方法属于哪一层"，直接在 agent 层的 Director 类里修修补补

### 教训

- **测试通过不能替代设计审查** — 当实现本身偏离设计时，基于错误实现写的测试会"验证"错误行为
- **层级归属是第一检查项** — 任何方法/类实现前，先确认它属于用户/runtime/agent/数据哪一层
- **设计模糊时必须提问** — 不允许智能体自作主张选择实现路径

---

## 三、修复方向（待确认后实施）

### 目标架构

```
Runtime 层 (app/runtime/)
  └─ RoundExecutor (新)
       ├─ 1. 构造 director 的 prompt（注入 flow_sequence + context）
       ├─ 2. 调 director 的 LLM → 获取响应
       ├─ 3. 解析响应中的 tool_calls
       ├─ 4. 如果是 call_agent → 从 registry 解析 agent → send_request → 回传结果
       ├─ 5. 如果是 await → 等待已调度的 task
       ├─ 6. 如果是 Finalize → 结束
       ├─ 7. 否则回传结果给 director → 回到步骤 2
       └─ 预算/递归控制在此层强制执行

Agent 层 (app/agents/)
  └─ Director = 一个普通 Agent 实例
       ├─ 属性: id/name/task/input/output/permission/model/tools=[call_agent,await]/...
       ├─ 无 run_round 方法
       └─ 无调度逻辑

数据层 (app/data/)
  └─ 不变
```

### 待确认的设计问题

见下方"四、设计问题"。

---

## 四、设计问题（需用户确认）

在实现前，以下设计模糊点必须由用户确认：

### Q1: Director 决策循环模型

guide:95 说 director 的主要工具是 `call_agent, await`。这暗示 director 的决策是**多轮对话式**的：

```
director 思考 → call_agent("writer", "写第一场") → 等待结果
→ director 思考 → call_agent("critic", "审查这段") → 等待结果  
→ director 思考 → Finalize
```

但也可能是**一次性规划**：

```
director 思考 → 输出 [call_agent("recaller"), call_agent("writer"), call_agent("maintainer")]
→ runtime 并行/顺序执行全部
```

**问题：director 的决策是逐步的（think → act → observe → think）还是一次性规划？**

### Q2: 工作流树的角色

guide:87 说"接线只决定优先级并保证无环，不严格表示执行顺序...由主agent决策"。

**问题：工作流树是纯信息性上下文（注入到 director prompt 中供参考），还是 runtime 会强制执行某些结构约束（如"不能在 recaller 之前调用 writer"）？**

### Q3: 预算和递归控制归属

当前 `BudgetTracker` 和 `check_recursion_allowed` 在 `app/runtime/`。

**问题：预算耗尽和递归限制由 runtime 层硬性强制（director 无法越过），director 在此限制内自由决策——这个理解对吗？**

### Q4: Director 类的存废

**问题：修复后，`Director` 类是否应该被移除？Director 变成只是一个从 yaml 加载的 `Agent` 实例（像 writer/recaller 一样），还是保留某些特殊方法？**

### Q5: 现有 run_round 的测试如何处理

当前 32 个测试基于 `run_round` 的硬编码遍历行为。

**问题：这些测试需要全部重写为基于新的 RoundExecutor 行为，还是保留 run_round 作为"兼容模式"直到新机制稳定？**
