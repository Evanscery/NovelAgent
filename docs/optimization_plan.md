# NovelAgent 优化计划

> 日期: 2026-07-27
> 输入: `docs/audit_report.md`（问题编号 F-1~F-8 / Q-1~Q-10 / W-1~W-7 均指向该报告）
> 范围优先级: 后端架构收尾 > 运行链路可用性 > 前端对齐设计
> 验证约束: pytest + mock runner + ruff/mypy + vitest/build 为主；允许少量真实 LLM smoke（key/配额失败即 fallback mock）
> 实施方式: 自迭代，每波次至少一个 commit；基线恢复点为 commit `498ddb8`
> 状态: **全部波次已于 2026-07-27 完成**（结果见 docs/stage_report.md 修复波次结果 与 docs/audit_report.md 修复后记）

## 波次总览

| 波次 | 主题 | 覆盖问题 | 验收标准 |
| --- | --- | --- | --- |
| W0 ✅ | 门禁恢复 + 安全 | F-8, F-4 | `npm run build` 绿；新增路径穿越单测全过 |
| W1 ✅ | LLM 协议正确性 | F-3, F-7, F-6 | assistant 消息携带 tool_calls 的消息序列单测；tier→模型名解析单测；MockRunner 可产出脚本化 tool_calls |
| W2 ✅ | 创作主链路打通 | F-1, F-2, F-5, Q-1 | mock 端到端一轮：项目仓库出现新 Turn commit、`novels/` 出现章节文件、state/summary 更新；chat 轮工具真实执行 |
| W3 ✅ | 架构收尾 | Q-2~Q-7, 召回方式③默认注入, agents→canvas 依赖 | pytest/ruff/mypy 全绿；死代码清零 |
| W4 ✅ | 前端对齐设计 | W-1~W-6, mode 默认 tab | vitest + build 绿；画布读写真实 workflow；导入有 UI |
| W5 ✅ | 真实 LLM smoke | 最终验收 | 1 轮 chat + 1 轮 workflow 用真实模型走通（失败 fallback 记录） |

## 各波次明细

### W0 门禁恢复 + 安全

1. **F-8**：3 处 `z.record(v)` → `z.record(z.string(), v)`（`canvasGraph.ts:7`、`ConfigView.tsx:65-66`）。
2. **F-4**：数据层统一 filename 防护——`store.py` 新增校验（拒绝空、绝对路径、盘符、`..` 段、路径解析出资源目录外），`read/write/read_lines` 与 API `PUT /resources` 全部走同一校验；补越权单测（相对穿越/绝对路径/盘符三类）。

### W1 LLM 协议正确性（真实 LLM 的前置）

1. **F-3**：`Message` 增加 `tool_calls` 字段；round executor 把 director 响应的 tool_calls 存进 assistant 消息；`OpenAIChatEncoder` 输出 `assistant.tool_calls`（id/type/function 结构），使 tool 消息的 `tool_call_id` 有合法前驱。
2. **F-7**：模型解析走 `config/models.yaml`——tier 名（premium/standard/cheap）在 runner 构造处解析为真实模型名（含 per-agent 覆写 `agent_models`），未知 tier 报清晰错误而不是发给端点。
3. **F-6**：MockRunner 支持脚本化行为：按注入的 flow_sequence 依次产出 `call_agent`（每个节点）→ 子 agent mock 输出 → `finalize(final_text=...)`，保持确定性（fingerprint 哈希），使 mock 覆盖调度/工具/commit 全路径。

### W2 创作主链路打通（核心）

1. **F-1 正文落盘**：`finalize` 工具 schema 增加 `final_text` / `summary` 可选参数；round 收尾把 `final_text` 写入 `novels/chapter_<turn>.md`（小说查看器即刻可读），`summary` 写入新增資源类型 `turn_summary`（承接设计"每轮维护一个 summary，将正文归档"的多级索引第一级；完整多级召回本期不做，只落地"summary 可被 recaller 全量读"）。
2. **F-2 每轮 commit + 事务**：round 执行包在 `AtomicTurn` 内——成功则 `commit_turn("Round <turn>")`（与 chat 的 Turn 序号同源），失败则 restore 快照；workflow 轮从此不再残留脏工作区。commit/回滚属 Runtime 职责（设计文档 Runtime 层清单明列 Commit/回滚），接入点在 round session 收尾，API 路由不碰 git。
3. **F-5 chat 轮 dispatch**：`_execute_chat_round` 改为带上限的小型 tool-loop（复用 workflow 循环的 dispatch 路径与 budget），使 RP 行动能真实触发 read/write/call_agent。
4. **Q-1 子 agent tool-loop**：子 agent 工具结果回喂自身、有限迭代（config 上限），使 recaller 递归召回与 maintainer read→edit 成为可能。

### W3 架构收尾

- 召回方式③默认注入：sub-agent prompt 组装时，把 `state` / `short_goal` 内容直接注入 permission.read 覆盖它们的 agent（writer/critic），兑现"parser 直接注入、避免 recaller 错误传递"。
- **Q-3** `maximal_recursive_calling_depth` schema 默认改 None（config 值生效）；**Q-6** `Budget.remaining()` 语义修正；**Q-4** 重复回滚重置分支；**Q-5** 删除 director 消息的回滚目标修正；**Q-2** PUT agent 支持改名（id 定位）。
- agents→canvas 反向依赖：将画布→树的编译入口归位用户层（canvas 层 import agents 是合法向下依赖），agent 层不再 import `app.canvas`。
- **Q-7** 死代码清理（`run_concurrent/await_all/await_any` 等：并发调度短期不实现，删除并在设计偏差记录中注明）；`store` 的 FileNotFoundError 转为对 LLM 友好的 tool_error 文案。

### W4 前端对齐设计

- **W-1** NovelView 引入 DOMPurify（ChatView 一并统一）；**W-2** retry 成功后重新拉取消息列表；**W-5** 统一 axios 错误提取 `response.data.detail`。
- **W-3** 画布接真数据：load 读 `GET /api/workflow/{id}/export`，保存走 `POST /import`；前端 schema 对齐后端便携格式。
- **W-4** 导入 UI：概览页上传 `.json` 卡片 → `card` 内联 POST → 展示 ImportResponse 并跳转新项目。
- mode 决定默认 tab（novel→作品/资源，rp→RP 视图），8 tab 仍全部可手动打开；全局专家模式开关统一（WorkflowCanvasView 局部 expert state 合并到 configStore）。
- 顺带：PUT resource 空内容前端拦截；HistoryPanel 接 onSelect + 后端 content-at-sha 端点（若时间允许）。

### W5 真实 LLM smoke（最终验收，少量额度）

- 用 `.env` 已配置模型：1 轮 chat（问答+一次工具调用）+ 1 轮最小 workflow（director→writer→finalize→commit）。
- 任何 key/配额/网络失败：记录失败原因到阶段报告，fallback 到 mock 验证，不重试烧额度。

## 明确不做（本期外，记录以防误解为遗漏）

- maintainer 1:1 每资源唯一（保持 1:N 简化，待设计确认再拆）。
- 配置 profile 层（保持 stub）。
- system agents（"帮我加节点"类）、并发 await/Future 调度、完整多级索引召回（只落 summary 第一级）、write 的增量 edit 工具（先靠子 agent tool-loop 的 read→全文重写过渡）。
- RP 动态前端渲染（card_front 渲染器已存在，暴露 API + 前端消费量大，列入下期）。
