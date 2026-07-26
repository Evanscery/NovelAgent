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

## 当前健康度（2026-07-27 实测）

| 检查 | 结果 |
| --- | --- |
| 后端 pytest | 667 通过 / 3 跳过 |
| ruff / mypy（70 文件） | 全绿 |
| 前端 vitest | 110 通过 |
| 前端 `npm run build` | **失败**（zod v4 `z.record` 签名，3 处，修复中） |
| 层间依赖 | 干净（唯一残留：agents→canvas） |

## 当前阶段的真实差距

骨架（分层/工厂/权限/预算/git 版本化/回滚）真实且测试完备，但**三条核心链路在"最后一公里"断裂**：

- **创作链**：正文无落盘（无正文资源类型、writer 只能写 notes、novels/ 无生产者）；workflow 轮不 commit、AtomicTurn 未接入。
- **chat/RP 链**：chat 轮 director 工具调用不被 dispatch → RP 状态更新完全失效。
- **真实 LLM 链**：assistant 消息不带 tool_calls（协议错误必 400）+ model tier 名直发 API。
- **验证链**：MockRunner 永不产生 tool_calls，默认配置下无法覆盖调度/工具/commit 路径。
- 另有 permission 隔离可被 filename 路径穿越绕过（安全）。

前端是干净的骨架，但画布持久化、RP 动态前端、导入 UI、按 mode 切默认 tab 等设计核心项是占位或假实现。

完整问题清单（F-1~F-8 / Q-1~Q-10 / W-1~W-7）见 `docs/audit_report.md`。

## 下一阶段

按 `docs/optimization_plan.md` 分波次实施：先恢复门禁与修安全洞，再打通创作主链路（正文落盘 + 每轮 commit + 事务），再修协议与 mock 可验证性，最后前端对齐。第一版成功标准（README"连续写 3-5 场"六条）在主链路打通前不可达，打通后进入真实 LLM 验收。
