# NovelAgent UI API Contract

> 最小操作前端 `serve-ui` 的 HTTP 契约文档。
> 目标：让前端只通过稳定 API 与后端交互，不直接接触内部实现。

基准版本：2026-06-11。

---

## 设计原则

1. 前端只做操作 / 展示 / 调试，不成为 canonical state 真相源。
2. API 返回的是 **聚合后的故事视图**，而不是要求前端自行拼接文件。
3. 错误优先返回清晰的 HTTP 状态码与简短错误描述。
4. 后续新增字段时，尽量追加，不破坏已有字段。

---

## GET `/api/stories`

返回可用 story/workspace 列表。

### Response 200

```json
[
  {
    "name": "mygo_harem_comedy",
    "path": "workspaces/mygo_harem_comedy"
  }
]
```

### 字段
- `name`: workspace 名称
- `path`: 相对项目根路径，后续调用 `/api/story` 与 `/api/rp-turn` 使用

---

## GET `/api/story?path=<workspace-relative-path>`

返回单个 story 的聚合视图。

### Query
- `path`：例如 `workspaces/mygo_harem_comedy`

### Response 200

```json
{
  "project": "...",
  "state": "...",
  "player_visible": "...",
  "summaries": "...",
  "index": "...",
  "chapters": ["chapter_01.txt"],
  "archives": ["C01S01"],
  "evaluation": "...",
  "journal": "...",
  "last_response": "...",
  "card_ir": "...",
  "runtime_plan": "..."
}
```

### Response 404
- `story not found`

### 字段说明
- `project`: `PROJECT.md`
- `state`: 后台真实状态 `state/state.md`
- `player_visible`: 玩家可见状态 `state/player_visible.md`
- `summaries`: `memory/summaries.md`
- `index`: `memory/index.md`
- `chapters`: `novels/` 下章节文件名列表
- `archives`: `archive/` 下场景归档目录列表
- `evaluation`: `evaluation/final_report.md`
- `journal`: `work/run_journal/latest.json`
- `last_response`: `work/last_response.json`
- `card_ir`: `data/card_ir.json`
- `runtime_plan`: `data/runtime_plan.json`

---

## GET `/api/card?path=<workspace-relative-path>`

返回单个 story 的「角色卡」聚合视图（G1）。前端逻辑对齐酒馆角色卡：`front/` 目录下的正则脚本用 `findRegex` 抓变量、`replaceString`(HTML+JS) 渲染组件。

### Query
- `path`：例如 `workspaces/mygo_harem_comedy`

### Response 200

```json
{
  "card_view": {
    "name": "...",
    "persona": "...",
    "opening": "...",
    "alternate_greetings": ["..."],
    "world_rules": ["..."]
  },
  "card_html": "<div class=\"card-view\">...</div>",
  "widgets": {
    "html": "<details>...</details>",
    "scripts": [{"name": "...", "disabled": false, "matched": 1}],
    "total_matches": 1,
    "source_chars": 1234
  },
  "front_script_count": 1
}
```

### 字段说明
- `card_view`: 从 `data/card_ir.json` 提炼的基础卡片字段。
- `card_html`: 基础卡片 HTML（`card_ir` 字段已 HTML 转义，安全展示）。
- `widgets`: 对 `state/player_visible.md` + `work/last_response.json` 应用 `front/*.json` 正则脚本后的渲染结果。
- `front_script_count`: 该 workspace `front/` 目录下加载到的脚本数。

### 正则脚本格式（`front/*.json`）
对齐 SillyTavern Regex 扩展，最少需要：
- `findRegex`: 字符串正则（支持裸正则或 `/pattern/flags`）。
- `replaceString`: HTML+JS 模板，使用 `$1..$N` 引用捕获组（`$0` 为整段匹配）。
- 可选：`scriptName`、`disabled`。

### Response 404
- `story not found`

---

## POST `/api/rp-turn`

提交一次 RP 回合。

### Request body

```json
{
  "story_path": "workspaces/mygo_harem_comedy",
  "text": "target: 爱音\n\n对爱音说：\"先听我解释。\""
}
```

### 约束
- `story_path` 必须为非空字符串，且对应存在的 workspace。
- `text` 必须为非空字符串。
- body 必须是 JSON object。

### Response 200

```json
{
  "parsed_input": {"mode": "rp", "target": "爱音"},
  "event": {"event_type": "player_turn"},
  "response": {
    "scene_id": "C01S03",
    "gm_narration": "...",
    "character_reactions": [],
    "skill_invocations": [
      {"skill": "dice_roll", "ok": true, "output": {"notation": "1d20", "rolls": [14], "modifier": 0, "total": 14}, "detail": "1d20 => [14] = 14"}
    ]
  },
  "state": "...",
  "player_visible": "..."
}
```

> `response.skill_invocations`（G2，可选）：当 GM 被授予技能（`config/agents.yaml` 的 `gm.skills`）且玩家行动文本含骰子表达式（如 `1d20`/`1d100`/`3d6+2`）时出现。掷骰为确定性纯函数，提供 seed 可复现，不调用 LLM。

### Response 400
- `invalid json body`
- `body must be a json object`
- `story_path required`
- `text required`

### Response 404
- `story not found`

---

## 写 API（前端重构新增，2026-06-15）

> 这些接口支撑「创建项目 / 编辑 prompt / 改配置 / 触发运行」。所有文件读写都经路径守卫（`app/web/paths.py:safe_resolve`）限制在 `workspaces/<story>/` 或 `config/` 内，拒绝绝对路径与 `..` 穿越。错误统一返回 `{"error": "..."}` + 对应 HTTP 状态码。

### 工作区

#### GET `/api/workspaces`
返回工作区列表（同 `/api/stories`，语义别名）。

#### POST `/api/workspace`
新建工作区。复用 `StoryWorkspaceManager.init_story`（与 CLI `init-story` 同一脚手架），项目自包含。
- Request: `{"name": "my_story", "theme": "蒸汽朋克悬疑"}`
- `name`：字母/数字/下划线/连字符/中文，1-64 字，不以连字符开头。
- 可选 `runner`（`mock|pi_rpc|direct`）：传入时，新建后立即启动 bootstrap 流程（theme_bootstrapper → cast_designer → worldbook_builder → arc_planner → state_initializer），返回 job_id 供轮询。
- Response 201（无 runner）: `{"name": "my_story", "path": "workspaces/my_story"}`
- Response 201（有 runner）: `{"name": "my_story", "path": "workspaces/my_story", "job_id": "bg_abc123"}`
- Response 400: `name required` / `工作区已存在：...` / 命名非法 / `invalid runner: ...`（非 mock/pi_rpc/direct）。

#### DELETE `/api/workspace?path=<ws>`
删除工作区（危险，前端须二次确认）。Response 200: `{"name","path","deleted":true}`。

### 文件

#### GET `/api/files?path=<ws>`
返回工作区内可编辑文件树（扁平列表）。仅暴露 `prompts/ modules/ presets/ lore/ state/ front/ data/ outline/` 下的 `.md/.yaml/.yml/.json/.txt`。
- Response 200: `{"path","files":[{"rel","dir","name","suffix","size"}],"editable_dirs":[...]}`

#### GET `/api/file?path=<ws>&rel=<relpath>`
读单文件。Response 200: `{"path","rel","content","suffix"}`（按 `utf-8-sig` 读，兼容 BOM）。

#### PUT `/api/file`
写单文件。
- Request: `{"path":"workspaces/my_story","rel":"prompts/scene_planner.md","content":"..."}`
- 仅允许写入可编辑目录、文本类型、≤2MB；统一以 `\n` 换行写回。
- Response 200: `{"path","rel","bytes","saved":true}`
- Response 400: 路径越界 / 不可写目录 / 类型不支持 / 文件过大。

#### POST `/api/file/move`
移动/重命名文件。路径守卫限制在可编辑目录内，拒绝 `..`、绝对路径、盘符穿越。
- Request: `{"path":"workspaces/my_story","src":"prompts/scene_planner.md","dst":"prompts/scene_planner_v2.md","overwrite":false}`
- `path`：工作区路径。
- `src`：源文件相对路径（相对于工作区）。
- `dst`：目标文件相对路径（相对于工作区）。
- `overwrite`：可选，默认 `false`。为 `false` 且目标已存在时返回 400。
- 约束：拒绝含 `..`、以 `/` 开头（绝对路径）、含盘符（如 `C:`）的 `src`/`dst`；拒绝目标超出 `EDITABLE_DIRS` 范围。
- Response 200: `{"path":"workspaces/my_story","src":"prompts/scene_planner.md","dst":"prompts/scene_planner_v2.md","moved":true}`
- Response 400: `invalid src path` / `invalid dst path` / `dst already exists (use overwrite=true)` / `dst outside editable dirs` / 源文件不存在。

### 配置

#### GET `/api/configs`
列出可读写的配置文件白名单及是否存在。

#### GET `/api/config?name=<file>`
读 `config/<file>.yaml`（仅白名单：`agents/models/paths/pipeline*/recall/runtime/server`）。Response 200: `{"name","content"}`。

#### PUT `/api/config`
写回配置。写前做 YAML 解析校验，语法错误拒绝写入（防写坏配置导致服务起不来）。
- Request: `{"name":"server","content":"server:\n  port: 8766\n"}`
- Response 200: `{"name","bytes","saved":true}`；Response 400: 非白名单 / YAML 语法错误。

### 运行（后台 job）

#### POST `/api/run`
触发后台运行，立即返回 job 概要。**默认 `runner=mock`，不接真实 LLM**；真实 runner 需显式传入。
- Request: `{"kind":"rp-turn","story_path":"workspaces/my_story","text":"..."}`
  - `kind`：
    - `run-scene`：需 `scene_id`，默认 `runner=mock`
    - `rp-turn`：需 `text`，确定性
    - `import`：需 `input`，确定性
    - `init-story`：需 `story_path` + `theme` + 可选 `runner`（默认 `mock`）。新建工作区并启动 bootstrap 流程。
    - `write-book`：需 `story_path` + 可选 `chapters`（默认 3）+ 可选 `min_words`（默认 3000）+ 可选 `runner`（默认 `mock`）。逐章写作，结果包含 `chapters_written` 列表，每章进度通过 `logs` 输出。
    - `evaluate-book`：需 `story_path` + 可选 `runner`（默认 `mock`）。评估全书，结果写入 `evaluation/final_report.md`。
  - 可选 `sync: true`（测试用，同步跑完再返回）。
- Response 202: `{"job_id","kind","status":"pending|running|done|error","result","error","logs":[]}`

#### GET `/api/run/<job_id>`
轮询 job 状态。Response 200: 同上 job 结构（`status` 终态为 `done`/`error`，`result` 为该 kind 的返回，如 rp-turn 的完整 turn payload）。Response 404: `job not found`。

### 小说阅读（只读，NOVEL-A2）

只读通道，用于前端「作品」阅读标签。可读根严格限定为 `workspaces/<story>/novels` 与 `workspaces/<story>/memory/fulltext`，复用 `safe_resolve` 防 `..`/盘符穿越，只返回 `.txt/.md`，**只读无写入、零 LLM**。`novels/`、`archive/`、`memory/` 不在 `EDITABLE_DIRS` 内，文件浏览器无法触达，由本通道专门承担阅读。

#### GET `/api/novel?path=<ws>`
列出工作区小说结构。Response 200:
```json
{
  "path": "workspaces/foo",
  "chapters": [{"number":1,"file":"chapter_01.txt","title":"第1章","char_count":4194,"size":14113}],
  "scenes": [{"scene_id":"C01S01","chapter":1,"char_count":4192,"size":12000}],
  "has_novel": true
}
```

#### GET `/api/novel/chapter?path=<ws>&chapter=<01|1|chapter_01.txt>`
读章节正文。`chapter` 接受序号（`01`/`1`）或文件名；拒绝含 `/`、`\`、盘符的输入。Response 200: `{"path","chapter","file","title","body","char_count"}`（`body` 已剥离首行标题）。Response 400: 非法标识 / 不存在。

#### GET `/api/novel/scene?path=<ws>&scene_id=<C01S01>`
读场景全文本（`memory/fulltext/<scene_id>.md`）。Response 200: `{"path","scene_id","chapter","body","char_count"}`。Response 400: 非法 scene_id / 不存在。

---

## 兼容性说明

- 当前 `text` 同时支持自然语言与带头部字段的输入；后续若采纳 `docs/improvement_proposals.md` 中的结构化输入提案，建议新增可选字段而不是破坏现有 `text`。
- `/api/story` 返回的是“便于前端渲染”的聚合内容；后续如果要增加更细粒度 API，可在保持该接口稳定的前提下新增。
- HTTP 层已从 `app/main.py` 迁出到 `app/web/` 包（`routes/api_workspace/api_files/api_config/api_run/static/paths`）；`/api/stories`、`/api/story`、`/api/card`、`/api/rp-turn` 语义不变。