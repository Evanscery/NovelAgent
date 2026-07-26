# NovelAgent 阶段报告

> 日期: 2026-07-27
> 性质: 阶段性状态综述（配套文档：`docs/audit_report.md` 全面审计、`docs/optimization_plan.md` 优化计划）

## 项目定位

文件驱动的多 Agent 小说创作 / RP 互动系统：director 动态调度子 agent（可绕过/可递归），在 8 类文件资源上创作与维护，每项目独立 git 仓库做版本/分支/回滚，角色卡兼容层单向导入。设计蓝图见 `docs/refactor_guide.md`（权威，只增不改）。

## 已走完的阶段

1. **旧架构（2026-06 中旬前）**：Vue3 SPA + `app/web/` 单体后端，已整体归档至 `archive/legacy/` 与 `docs/archive/`。
2. **四层重构（2026-06 底 ~ 07-10）**：React+Zustand 前端、FastAPI 后端拆为 用户/Runtime/Agent/数据 四层，8 资源 + 每项目独立 git。
3. **层级违规修复（07-10 审计 → 07-27）**：旧审计 5 个确认违规全部修复——Runner 迁 Runtime 层、画布模型迁用户层（`app/canvas/`）、ToolExecutor 删除、API 编排收敛到 `create_round_session` 工厂、数据层越界方法删除。
4. **fix3 波次（07 月下旬）**：结构化请求（PromptBuilder / RequestSpec / Message）、ToolCatalog + MCP seam、skills 抽象删除（"a skill IS an agent"）、workflow 导出/导入 API、每 agent 独立权限工具面、约 800 行死代码清理。

## 当前健康度（2026-07-27 审计时实测）

| 检查 | 审计时 | 修复波次后（同日） |
| --- | --- | --- |
| 后端 pytest | 667 通过 / 3 跳过 | **694 通过 / 3 跳过**（含新 e2e 验收） |
| ruff / mypy（70 文件） | 全绿 | 全绿 |
| 前端 vitest | 110 通过 | **126 通过** |
| 前端 `npm run build` | **失败**（zod v4） | 全绿 |
| Playwright e2e | 未跑 | 12 通过 / 3 跳过 |
| 真实 LLM smoke | 不可用（协议必 400） | **PASS**（chat + workflow 各 1 轮，见 `docs/evidence/llm_smoke_2026-07-27.txt`） |
| 层间依赖 | agents→canvas 一处残留 | 干净（画布编译已归位用户层） |

## 修复波次结果（2026-07-27，审计当日完成）

按 `docs/optimization_plan.md` 执行完 W0–W5 全部波次（git log 标签 [W0]~[W5]，基线恢复点 `498ddb8`）：

- **W0** `4edf1f9` — build 门禁恢复（zod）；filename 路径穿越封堵（F-4/F-8）。
- **W1** `446efff` — assistant 消息携带 tool_calls（F-3）；tier→模型名解析（F-7）；MockRunner 脚本化走完整轮（F-6）。
- **W2** `062b771` — 正文落盘 `novels/` + `turn_summary` 摘要归档（F-1）；workflow 轮接入 AtomicTurn、每轮一个 Turn commit、失败回滚（F-2）；chat 轮工具真实分发（F-5）；子 agent 有限 tool-loop（Q-1）。
- **W3** `d953929`+`7dc735c` — 画布编译/加载/默认画布归位 `app/canvas/`（反向依赖清零）；默认注入（召回方式③）；Q-2~Q-6 修复；死代码清理；canvas GET/PUT 契约。
- **W4** `bc0568a` — 前端：画布真数据读写、导入 UI、XSS 修复（DOMPurify）、retry 同步、错误 detail 透出、mode 默认 tab。
- **W5** — 真实 LLM smoke 一次通过：真实模型完成 chat 轮与单 writer workflow 轮（explicit_finalize + 章节落盘 + Turn commit + 零拒绝调用）。

## 审计时的真实差距（多数已在上述波次修复，保留作历史记录）

骨架（分层/工厂/权限/预算/git 版本化/回滚）真实且测试完备，但**三条核心链路在"最后一公里"断裂**：

- **创作链**：正文无落盘（无正文资源类型、writer 只能写 notes、novels/ 无生产者）；workflow 轮不 commit、AtomicTurn 未接入。
- **chat/RP 链**：chat 轮 director 工具调用不被 dispatch → RP 状态更新完全失效。
- **真实 LLM 链**：assistant 消息不带 tool_calls（协议错误必 400）+ model tier 名直发 API。
- **验证链**：MockRunner 永不产生 tool_calls，默认配置下无法覆盖调度/工具/commit 路径。
- 另有 permission 隔离可被 filename 路径穿越绕过（安全）。

前端是干净的骨架，但画布持久化、RP 动态前端、导入 UI、按 mode 切默认 tab 等设计核心项是占位或假实现。

完整问题清单（F-1~F-8 / Q-1~Q-10 / W-1~W-7）见 `docs/audit_report.md`。

## 下一阶段（W0–W5 之后仍未做的）

- **RP 动态前端**：`card_front.py` 渲染器已存在但无 API 路由与前端消费；variables 未在 RP 视图渲染。
- **预设片段挂载**：`extract_preset_fragments` 产出的 PromptFragment 无消费方（应折入 agent head/tail）。
- **多级索引召回第二级**：summary→定位→按轮次召回正文全文的工具面（目前 recaller 只能读 summary，正文在 novels/ 无 read 工具通道）。
- **版本回滚独立 API/前端入口**（当前唯一路径是 chat 删除）；资源历史"查看任意时间点内容"（需 content-at-sha 端点）。
- 并发调度接入（runtime 并发原语已有，executor 的 call_agent 仍同步）；maintainer 1:N→1:1 拆分；配置 profile 层；system agents。
- **真实 LLM 场景验收**：第一版成功标准（README"连续写 3-5 场"六条）现在链路已通，可以开始多轮真实创作验收。
