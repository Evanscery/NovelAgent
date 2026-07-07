# NovelAgent

> 文件驱动、可审查、可归档、可扩展到 RP 的多 Agent 小说创作 / 互动系统。
> 四层架构（用户界面 / 执行基础设施 / 智能体 / 数据）· 8 类资源以纯文件 + 每项目独立 git 管版本 · FastAPI 后端 · React + TS + Vite 前端 · 角色卡兼容层单向导入。

NovelAgent 用一个**导演 Agent（director）**动态调度其他智能体（可绕过 / 可递归），在 8 类资源（大纲 / 细纲 / 当前状态 / 变量 / 世界书 / 客观事实 / 人物记忆 / 创作笔记）上做创作与维护。同一套文件结构上扩展出**玩家可互动的 RP 模式**与**角色卡兼容导入**。设计总原则只有一条：**最大程度利用 agent 能力完成任务，而不是为了"看起来高级"去引入无意义复杂度**——只有某项设计确有必要、确能稳定提升效果/效率/可维护性/可迁移性/可运维性时，才进入实现。

- Python ≥ 3.11，依赖 `pydantic` + `PyYAML` + `fastapi` + `uvicorn` + `GitPython`
- 真实 LLM 是**最终验收工具，不是调试器**：工程问题先用 mock / deterministic / schema 校验解决，最后才接真实模型
- 前端 React + TypeScript + Vite，Comfy-UI 式画布工作流配置器 + director 聊天 + 分类型数据编辑器 + 版本历史
- 纯文件 + git 存储，**无数据库**；每个项目是独立 git 仓库

---

## 架构总览

```text
用户界面 (web/)            React + TS + Vite：画布工作流配置器 / director 聊天 /
  ├─ views/                分类型数据编辑器(8类) + 版本历史 / 小说阅读器 / RP 动态前端 / 配置页 / 运行面板
  └─ stores/               Zustand 状态管理

执行基础设施 (app/runtime/) 发送 agent 请求 / 并发执行 / 等待 Future / 超时 / 重试 /
  ├─ runtime.py            提交 / 回滚 / 原子事务（与具体 agent 无关）
  ├─ transaction.py        AtomicTurn：一轮的所有维护操作要么全提交要么全取消
  ├─ permission.py         解析 agent.permission → 工具作用域 → 越权 reject
  ├─ tool_dispatcher.py    解析 agent 工具调用 → 路由到 read/search/write
  └─ budget.py             token / tool / iteration 预算 + Finalize 信号

智能体 (app/agents/)       Agent 属性模型(id/name/task/input/output/permission/
  ├─ agent.py              model/skills/tools/head/tail) + parser(配置静态→prompt动态)
  ├─ parser.py             director 必备，工具 call_agent/await，按 DAG 优先级调度
  ├─ director.py           可绕过节点 / 可递归召回 / Finalize
  ├─ workflow.py           WorkflowDAG(节点/接线/优先级，接线只定优先级+保证无环)
  ├─ tools.py              统一工具 read(resource)/search(resource)/write(resource)
  ├─ skills.py             技能 registry（内置 dice_roll + 预设技能提取；MCP 预留）
  ├─ builtin/*.yaml        5 个内置 agent 属性集（recaller/scout/writer/critic/maintainer）
  └─ default_workflow.yaml 默认 DAG

数据 (app/data/)           只做存储/索引/访问/权限校验——不主动召回、不主动维护、
  ├─ resource.py           不关心内容。所有"理解数据"交给 Agent。
  ├─ resource_types.py     8 类资源: Outline/ShortGoal/State/Variables/Worldbook/
  ├─ store.py              Facts/CharacterMemory/Notes，每类有独立 properties.md
  ├─ versioning.py         git 版本图: Turn=commit / Branch=branch / Projection=工作区
  └─ project_repo.py       每项目独立 git 仓库，主仓 .gitignore 忽略 workspaces/*/

兼容层 (app/compat/)       角色卡兼容单向导入（正则前端 / 卡→8资源 / 预设→技能）
  └─ tavern_card/          详见 docs/compat_tavern_card.md
```

### 8 类资源（对应 `docs/refactor_guide.md:167`）

| 类型 | 目录 | 更新频次 | 维护方式 | 说明 |
| --- | --- | --- | --- | --- |
| 大纲 | `resources/outline/` | 低频 | 覆盖 | 长期目标 |
| 细纲 | `resources/short_goal/` | 每轮 | 覆盖 | 本回合需发生的事 |
| 当前状态 | `resources/state/` | 每轮 | 覆盖 | 上一轮小总结 |
| 变量 | `resources/variables/` | 每轮 | 覆盖 | 前端显示用，不注入 AI |
| 世界书 | `resources/worldbook/` | 低频 | 增量 | 背景设定 / 人物设定 |
| 客观事实 | `resources/facts/` | 低频 | 增量 | 同人设定 / 现实真相 / 网搜结果 |
| 人物记忆 | `resources/character_memory/` | 频繁 | 增量 | 角色隔离，who knows what |
| 创作笔记 | `resources/notes/` | 低频 | 覆盖 | 动态发现 / 反馈 / 新约束 |

每类资源有独立的 `properties.md`（存储方式 / 召回策略 / 维护策略 / 版本策略）+ `manifest.json`。

---

## 快速开始

### 0. 一次性准备

```bash
pip install -e .                 # 安装依赖（首次）
```

要写真实正文，先配模型：把 `.env.example` 复制为 `.env` 填入供应商/密钥，编辑 `config/models.yaml` 与各 agent 的 model 字段。

### 1. 启动服务

```bash
python -m app.main serve          # 拉起 FastAPI 后端 + 前端 Web
```

- 浏览器打开提示地址（默认 `http://127.0.0.1:8000`，见 `config/server.yaml`）。
- 默认仅本地监听；对外暴露需显式改 `host: 0.0.0.0` 并配置 `ip_whitelist`。

### 2. 创建项目并写作

通过前端「概览」页创建项目（系统自动生成项目 id，显示名在 `config.yaml` 里），打开「运行」面板点「开始一轮」即可。Director 会按默认工作流 DAG 调度 recaller / scout / writer / critic / maintainer，每轮产出提交为一次 git commit。

### 3. 角色卡兼容导入

通过前端「导入」按钮或 `POST /api/import` 上传角色卡文件（`.json`），系统会：

1. 解析卡片 → 中间表示（CardIR）+ 运行时计划（RuntimePlan）
2. 新建项目（或导入到既有项目）
3. 把卡片字段映射到 8 类资源 + 把正则前端脚本写入 `front/`

详见 [`docs/compat_tavern_card.md`](docs/compat_tavern_card.md)。

### 4. RP 互动模式

RP 是可选玩法：切换项目 mode 为 `rp`，在 RP 视图输入"玩家行动"，系统按事件驱动推进一回合，并维护**后台真实状态**与**玩家可见状态**的信息差。行动里可写骰子表达式（如 `1d20`），若 GM agent 声明了 `skills:[dice_roll]`，结果作为可审计的技能调用挂在响应里。

---

## 配置体系

四层优先级：`global < profile < project < run override`。

- `config/models.yaml` — 模型 tier（premium/standard/cheap）+ 供应商类型（openai/openai-response/anthropic）+ per-agent 模型
- `config/runtime.yaml` — 超时 / 重试 / 退避 / 降级 / 预算 / Finalize 策略
- `config/server.yaml` — FastAPI host / port / CORS / IP 白名单
- `workspaces/<id>/config.yaml` — 项目显示名 + mode + per-project 覆写

每 agent 独立配置 Name / Task / Model / Skills / Tools / Permission / Input / Output（Workflow 保存**配置**而非 Prompt，parser 在运行时动态生成 prompt）。

---

## 前端

React + TypeScript + Vite 单页应用：

- **画布工作流配置器**（react-flow）：节点 / 接线 / DAG / JSON 导入导出，用户可交互式创建 workflow agent
- **Director 聊天**：增 / 删 / 重试消息，同步到后端 git 回滚与更新
- **分类型数据编辑器**：8 类资源各一个编辑器 + git 版本历史查看
- **小说阅读器**：查看 / 编辑 / 缩放
- **RP 动态前端**：从角色卡绑定的正则脚本渲染（regex → html+css+js）
- **集中配置页**：模型 / 供应商 / per-agent，默认傻瓜式零技术用户，专家模式解锁高级字段

```bash
cd web
npm install        # 首次
npm run dev        # 开发模式 (:5173，/api 代理到本地后端)
npm run build      # 构建到 web/dist，由 python -m app.main serve 托管
npm run test       # 前端 Vitest 单测
```

---

## 命令一览

| 目的 | 命令 |
|------|------|
| 启动服务 | `python -m app.main serve`（或 `start.bat` / `./start.sh`） |
| 干跑验证（不花额度） | 后端用 mock runner（前端运行面板切换 / 配置覆写） |

> 项目创建 / 写作 / 导入 / RP 等操作均由前端驱动（`docs/refactor_guide.md:352-353` 傻瓜式零技术用户），CLI 只保留 `serve` 子命令。

---

## 测试原则

> 真实 LLM 不是调试器，只是最终验收工具。

测试分层：第 0 层静态/结构 → 第 1 层 mock runner → 第 2 层局部 deterministic → 第 3 层最小真实 LLM smoke → 第 4 层最终真实场景。只有前 3 层全绿才允许真实生成/RP/迁移整链测试。

```bash
pytest tests/unit/ -v            # 后端单测
cd web && npm run test           # 前端单测
ruff check app/ && mypy app/     # lint + 类型检查
```

---

## 文档索引

- [`docs/refactor_guide.md`](docs/refactor_guide.md) — **权威蓝图**（四层架构 / 8 资源 / director / 运行时分离 / 统一工具 / 权限 / git 版本 / 无 DB / React / FastAPI）
- [`docs/compat_tavern_card.md`](docs/compat_tavern_card.md) — 角色卡兼容层说明（唯一提及外部角色卡生态来源的地方）
- `docs/archive/` — 旧版文档归档（仅供参考，非当前架构）

---

## 第一版成功标准

连续写 3-5 场后：①不忘记上一场发生过什么 ②角色不会知道不该知道的信息 ③世界观规则不被破坏 ④时间/地点/物品/人物状态不矛盾 ⑤每场都有完整归档 ⑥下一场能从 `resources/state/` 自然接上。
