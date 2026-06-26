# How to Start：从零写一本 5 章小说

本文带你从零创建一个独立小说项目，并完成前 5 章正文。**RP 互动模式**作为可选扩展，放在最后一节。

> 命令在项目根目录执行。Windows 用 PowerShell，macOS/Linux 用终端。
> 关于运行器：`--runner mock` 不调用任何大模型，只跑通流程、写占位内容，用来**先验证工程是否正常**；`--runner direct` 才会接入真实 LLM，产出真正的小说。**真实写作必须用 `direct`**。

---

## 0. 一次性准备

```bash
# 安装依赖（首次）
pip install -e .

# 初始化 Recall 数据库（全局只需一次）
python -m app.main init-db
```

如果你想用真实 LLM（写正文必须），先配置好模型：编辑 `config/models.yaml` 填入你的供应商/密钥，并确认 `config/agents.yaml` 里各 agent 的 `runner` 指向可用模型。`.env.example` 是环境变量样例。

---

## 1. 创建一个独立项目（工作区）

每个故事是一个**自包含工作区**，互不干扰，放在 `workspaces/<你的项目名>/` 下。

```bash
python -m app.main init-story ^
  --story-root workspaces/my_first_novel ^
  --theme "现代都市，一名程序员意外获得回到过去24小时的能力" ^
  --runner direct
```

（macOS/Linux 把行尾的 `^` 换成 `\`，或写成一行。）

这一步会：
- 生成完整工作区目录（`lore/` 设定、`state/` 状态、`outline/` 大纲、`memory/`、`prompts/`、`presets/`、`archive/`、`novels/` …）；
- 跑一遍 bootstrap 流程，根据你的 `--theme` 生成 premise、人物、世界观、初始大纲与初始状态。

> 想先**不花 LLM 额度**验证目录和流程能否跑通，把 `--runner direct` 换成 `--runner mock` 试一次，确认无误后再用 `direct` 正式来一遍。

创建完可以打开 `workspaces/my_first_novel/lore/premise.md`、`outline/master_outline.md` 看看生成的设定，需要的话手动修改——一切真相源都是文件。

---

## 2. 写前 5 章正文

```bash
python -m app.main write-book ^
  --story-root workspaces/my_first_novel ^
  --chapters 5 ^
  --min-words 3000 ^
  --runner direct
```

参数说明：
- `--chapters 5`：写到第 5 章（从已有章节之后续写，支持中断后再次运行接着写）。
- `--min-words 3000`：每章最少中文字符数，不足会自动触发扩写。
- `--runner direct`：用真实 LLM 写作（**必需**）。

每章会依次执行：冻结输入 → 召回历史 → 规划场景 → 多重审查（世界观/知识/连贯/人物/文风）→ 写作 → 修订 → 状态维护 → 归档，并把成稿导出为 `workspaces/my_first_novel/novels/chapter_01.txt …`。

写完后产物在：
- `novels/chapter_01.txt` … `chapter_05.txt`：可直接阅读的成稿；
- `archive/C0xS01/`：每章的完整过程归档（大纲、草稿、审查报告、最终稿）；
- `state/state.md`：当前故事状态，下一次续写从这里自然接上。

### 可选：评估这本书

```bash
python -m app.main evaluate-book --story-root workspaces/my_first_novel --runner direct
```

报告写到 `workspaces/my_first_novel/evaluation/final_report.md`。

---

## 3. 用图形界面操作（可选，更直观）

不想敲命令，可用前端工作台：

```bash
python -m app.main serve
```

Windows 也可直接双击根目录 `start.bat`，macOS/Linux 运行 `./start.sh`（首次会自动构建前端）。浏览器打开提示的地址（默认 http://127.0.0.1:8766），即可：新建项目、看概览、编辑 prompt/配置、浏览文件、在「运行」面板触发写作（默认 mock，正式写作记得选 `direct`）。

---

## 4. 扩展：RP 互动模式

RP（角色扮演）是**可选扩展玩法**：不再一次写整章，而是你输入"玩家行动"，系统按事件驱动推进一回合，并维护**后台真实状态**与**玩家可见状态**的信息差（角色不会知道不该知道的事）。

同一个工作区即可开始 RP，无需新建项目：

```bash
python -m app.main rp-turn ^
  --story-root workspaces/my_first_novel ^
  --text "对酒馆老板说：我想打听最近镇上的怪事。"
```

支持两个进阶写法：
- **指定对话目标**：在文本开头加一行 `target: 老板`。
- **掷骰技能（GM）**：行动里写骰子表达式（如 `1d20`、`1d100`），若 `config/agents.yaml` 中 GM 已声明 `skills: [dice_roll]`，结果会作为可审计的技能调用挂在响应里。

每回合的输入/事件/响应/状态都会落盘到工作区 `work/` 下（`player_input.json`、`last_event.json`、`last_response.json`），状态写回 `state/state.md` 与 `state/player_visible.md`。

也可以在前端工作台的「RP 对话」标签里图形化地一回合回合地玩。

> RP 回合默认不调用大模型（事件归约 + 确定性技能），适合先把互动跑顺；接入真实 LLM 生成更自然的叙述属于后续增强。

---

## 速查

| 目的 | 命令 |
|------|------|
| 初始化数据库（一次） | `python -m app.main init-db` |
| 新建项目 | `python -m app.main init-story --story-root workspaces/<name> --theme "..." --runner direct` |
| 写 5 章 | `python -m app.main write-book --story-root workspaces/<name> --chapters 5 --runner direct` |
| 评估 | `python -m app.main evaluate-book --story-root workspaces/<name> --runner direct` |
| 图形界面 | `python -m app.main serve`（或 `start.bat` / `./start.sh`） |
| RP 一回合 | `python -m app.main rp-turn --story-root workspaces/<name> --text "..."` |
| 干跑验证（不花额度） | 上述命令把 `--runner direct` 换成 `--runner mock` |
