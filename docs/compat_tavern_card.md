# 角色卡兼容层 (Character Card Compat Layer)

> 本文档是项目中文档里**唯一**提及 SillyTavern 的地方（见 `docs/refactor_guide.md:27-29` 与决策 D5：除兼容层代码与这一篇说明外，项目内不得出现 SillyTavern 字样）。

## 为什么存在这个兼容层

NovelAgent 的灵感来自 SillyTavern 的角色卡生态，但运行时与 SillyTavern **完全解耦**——不依赖 SillyTavern 任何功能。为了能复用社区已有的角色卡与预设，项目在 `app/compat/tavern_card/` 提供一个**单向导入**兼容层：把外部角色卡转换为 NovelAgent 自己的 8 资源模型，把外部预设里的文风/越狱片段转换为 Agent 技能。

## 模块

| 模块 | 职责 |
| --- | --- |
| `app/compat/tavern_card/card_front.py` | 角色卡绑定的正则前端脚本（findRegex → HTML 模板，`$1..$N` 占位符）→ 安全 HTML 渲染。用于 RP 模式的动态前端。 |
| `app/compat/tavern_card/card_migration.py` | 角色卡 → 8 资源项目迁移：`load_card_payload` → `infer_card_ir` → `infer_runtime_plan` → `materialize_project_from_card`。 |
| `app/compat/tavern_card/preset_extract.py` | 预设（文风 / 越狱 / system 段）→ Agent 技能。解析预设格式，再委托 `app/agents/skills.py` 的 `extract_skills_from_preset` 包成 `Skill` 对象。 |

## 导入流程

```
角色卡文件 (.json) ──┐
                     ├─ load_card_payload ──> infer_card_ir (CardIR)
内联卡 payload ──────┘                                │
                                                      ▼
                                        infer_runtime_plan (RuntimePlan)
                                                      │
                                                      ▼
                          materialize_project_from_card ──> 8 资源目录 + front/
```

### 角色卡字段 → 8 资源映射

| 资源类型 | 来源 |
| --- | --- |
| `worldbook` | `character_book` 条目 + `scenario` 规则 |
| `character_memory` | `personality` + 推断出的人际关系（角色隔离） |
| `state` | `first_mes`（初始状态） |
| `notes` | `description` + 创作备注 |
| `outline` | `scenario` 推导的剧情主线（若可用） |
| `variables` | 推断的量化变量（好感 / 任务 / 时间 / 金钱 / 关系 / 信任） |
| `facts` | （留空——客观事实由运行时网搜工具填充） |
| `short_goal` | （留空——maintainer agent 每回合填写） |

卡片的正则前端脚本写入项目的 `front/` 目录，供 RP 模式动态渲染。

## API 入口

`POST /api/import` 委托本兼容层：

- `{"source": "<卡文件路径>"}` 或 `{"card": <内联 payload>}` —— 二选一。
- 可选 `{"project_id": "<已有项目 id>"}` 导入到既有项目；否则新建一个。
- 可选 `{"display_name": "...", "mode": "novel|rp"}` 覆盖默认值（默认取卡片名 / runtime plan 推荐）。
- 成功返回 `201`，含 `project_id` / `resources_created` / `front_scripts_written`。

## 预设技能提取

`extract_preset_skills(preset)` 接受 markdown 字符串、JSON/YAML dict、或区段列表，规范化为 markdown `##` 段落后，委托 `app/agents/skills.py` 的 `extract_skills_from_preset` 产出 `Skill` 对象：

- `## 文风` / `## style` / `## 写作风格` → `style_<hash8>`
- `## jailbreak` / `## 越狱` → `jailbreak_<hash8>`

技能名按内容哈希命名，同一预设片段在多次运行中得到稳定标识符。

## 边界

- 兼容层只做**导入**（卡 → 项目 / 预设 → 技能），不承担运行时角色卡渲染之外的任何 SillyTavern 行为。
- 项目的其他代码、文档、UI 一律使用自己的术语（角色卡兼容 / 卡导入 / 预设技能），不出现 SillyTavern 字样。
- `docs/refactor_guide.md` 是权威源，其中提及 SillyTavern 是历史背景说明，不在此限。
