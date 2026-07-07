# 已知问题（A 测驱动 · 2026-06-19）

> 维护原则：前端以「玩家 / 创作者」视角，而非「系统维护者 / 技术人员」；技术 internals 进专家模式；最终呈现对标商业级成熟创作引擎或游戏界面。
>
> 本文由两条 A 测驱动更新：(1) RP 用户视角（SillyTavern / 跑团 / 角色卡背景）；(2) 写小说用户视角（项目首要目标）。原始报告见仓库 sub-agent 输出。已解决的第一/二阶段 9 条（启动/RP 文案/概览滚动/设置卡片化/素材库预览/创作任务卡/微动画）已归档至文末「已归档」。

---

## A. RP 反馈模型重构（优先级最高之一）

当前 RP 是「自然语言 → 关键词分类 → 固定模板拼接」的演示器，GM 不读输入、不判定、不主动掷骰。

### RP-A1（critical）GM「反馈」是模板复读，不做任何判定 —— ✅ 策略接口已落地（2026-06-19）
- 处理：新增 `app/rp_modes.py`，把 response 构建抽成可插拔 `RpMode` 策略（`narrate(event, state, ctx, next_scene_id) -> RpResponse`）；状态推进与叙述解耦（state reducer 仍先跑，mode 只 narrate）；GM runner 钩子保留（mock 默认，`gm.runner=llm` 显式抛 `NotImplementedError`）。
- 默认路径零行为变化：无 `rp.yaml` → immersive → 与原 `build_layered_turn_response` 同形状，既有 rp-turn 测试全绿。

### RP-A2（critical）无「沉浸 / 跑团」模式概念 —— ✅ 已落地（2026-06-19）
- 处理：内置 `ImmersiveMode`（叙述推进，= 原 mock）与 `TrpgMode`（判定→掷骰→GM 指令）；`build_rp_mode_registry()` 静态策略表，未知 mode 降级 immersive。

### RP-A3（high）掷骰仅被动触发，无 GM 主动判定 / 无 GM 掷 vs 玩家掷 —— ✅ GM 侧已落地，前端掷骰按钮待补（2026-06-19）
- 处理：TrpgMode 在 `event.intent ∈ rp.dice.prompt_on` 时判定；`source=gm` 同回合内调 `DiceRollSkill`（确定性 seed）掷骰，把「你过个 1d20 看是否命中。（GM 掷 1d20 => N：命中/未命中）」折进叙述；`source=player` 不掷，只要求玩家掷并返回 `pending`。
- 验证：curl trpg（seed=42）→ 叙述含「GM 掷 1d20 => 4：未命中」+ `skill_invocations`；player 源 → 叙述「请玩家掷 1d20」+ `pending={kind:player_dice, status:awaiting_roll}`。
- 后续：前端掷骰按钮（消费 `pending` 发回 `resolve`）= RP-A7 前端部分。

### RP-A4（high）中间态默认泄露，无开关 —— ✅ 前端层已修复（2026-06-19）
- 处理：RpView 新增「专家」开关；玩家气泡的 intent/target chip **默认隐藏**，开启专家模式才显示（GM 旁白 / 角色反应 / 骰子徽章仍正常渲染）。
- 验证：Playwright 发送「我一剑刺向王弘，掷出 1d20…」→ 默认 0 chip；开启「专家」后 chip 出现（行动）；console 零错误。测试后已还原 state/player_visible 并清理 work 瞬态文件。
- 后端响应分层（player/debug 两层 + 请求 `?debug=true`）与 `player_visible` 的 `## Hidden Information` 投影剥离为后续追加，当前先以「默认不向玩家暴露技术分类标签」止血。

### RP-A5（high）RP 配置全局共享，无法按项目差异化 —— ✅ 已落地（2026-06-19）
- 处理：新增 per-workspace `workspaces/<story>/rp.yaml`（mode / dice.source / dice.prompt_on / dice.notation / dice.seed / gm.persona / gm.runner / visibility.debug_default）；`load_story_config` 读入 `ConfigBundle.rp`（新增字段，类比 `recall`）；全局 `agents.yaml` 的 `gm.skills` 仍作 fallback；示例见 `workspaces/rp.yaml.example`。非法字段一律降级到默认，不中断回合。

### RP-A6（medium）GM agent 形同空壳（无 prompt / runner） —— 部分已落地（2026-06-19）
- 处理：`rp.yaml` 的 `gm.persona`（折进叙述前缀）与 `gm.runner: mock|llm`（默认 mock，llm 占位抛错）已生效；GM 人格前缀已在 trpg 验证中确认（「【中立裁判】…」）。
- 后续：真实 LLM GM（`gm.runner=llm`）实现 = 接 `direct_runner` 通道。

### RP-A7（medium）回合单次同步，无多步跑团协议 —— ✅ 已落地（2026-06-23）
- 处理：后端 `rp-turn` 新增 `resolve` 路径（`run_rp_turn(..., resolve={scene_id,notation,total})`）→ `resolve_player_roll` 直接判定命中/未命中（阈值 >=10），不推进场景、不要求重掷；前端 RpView 在响应含 `pending` 时显示「🎲 掷 {notation}」按钮，玩家点击后客户端掷骰（解析 1d20/3d6+2）并把 `total` 回传 `resolve`。
- 验证：Playwright trpg(player) → GM「请玩家掷 1d20」+ 掷骰按钮出现 → 点击 → 玩家骰子气泡「1d20 => 8」+ GM 判定「玩家掷 1d20 => 8：未命中。」+ pending 消失；console 零错误。pytest +2（`test_rp_turn_resolve_*`）。测试后已还原 state/player_visible、移除 rp.yaml 与 work 瞬态文件。

**RP 落地顺序建议**：~~A4（止血，独立可做）~~ ✅ → ~~A1+A2+A5（策略接口 + 模式 + per-workspace 配置）~~ ✅ → ~~A3（gm-side 判定先行）~~ ✅ → A6（真实 LLM GM）→ A7（前端掷骰按钮 + resolve）。全程 rp-turn 默认确定性、mock 可用。

---

## B. 小说结果阅读（项目首要目标，优先级最高）

后端产物齐全（`novels/chapter_*.txt`、`memory/fulltext/<id>.md`），但前端「写完无处读」，连取正文的 API 都没有。

### NOVEL-A1（critical）没有「作品」阅读标签页 —— ✅ 已修复（2026-06-19）
- 处理：新增 `TabKind='novel'`（📖「作品」）+ `web/src/views/NovelView.vue`：左侧目录（章节 + 场景全本）+ 右侧书籍版式阅读窗（行距 1.9、最大宽 720px、首行缩进 2em、标题居中）；不暴露文件名，显示「第 N 章」+ 解析标题。
- 验证：Playwright 打开作品标签 → 目录列出 3 章 + 4 场景、章节/场景切换正文正确渲染（第2章 3678 字、C03S01 3238 字）、console 零错误。

### NOVEL-A2（critical）前端无法获取章节正文——API 只返回文件名 —— ✅ 已修复（2026-06-19）
- 处理：新增 `app/web/api_novel.py` + 路由 `GET /api/novel`（列章/场）、`/api/novel/chapter`、`/api/novel/scene`；可读根严格限定 `workspaces/<story>/novels` 与 `.../memory/fulltext`，复用 `safe_resolve` 防 `..`/盘符穿越，只返回 `.txt/.md`，**只读无写入、零 LLM**。
- 验证：curl 三端点返回正确（list 3 章/4 场景、chapter 1 = 第1章 4194 字、scene C03S01 = 2750 字）；路径穿越 `chapter=../../config/server.yaml` → 400；pytest +5 项 `test_novel_*` 全绿。

### NOVEL-A3（high）素材库无法到达 novels/、archive/、fulltext/ —— ✅ 已由 A1+A2 解决
- 不开放这些目录进 `EDITABLE_DIRS`（防误写 / 暴露技术结构）；专用只读阅读页承担，素材库保持现状。

### NOVEL-A4（high）概览是「技术 dump」而非作品主页 —— ✅ 已修复（2026-06-19）
- 处理：`OverviewView` 重构为作品主页——顶部「我的作品」卡（项目简介 + 章节数/总字数/归档数 + 「去阅读 →」跳作品标签）；meta-grid 改为 章节数/归档场景/总字数/角色卡；后台真相/玩家可见/Summaries/Index/Evaluation/Journal/Last Response 等技术块**默认折叠进「专家信息」**。
- 验证：Playwright 打开概览 → work-hero 显示「3 章 · 10091 字 · 3 个归档场景」，专家信息默认折叠；「去阅读 →」跳转作品标签并加载目录（7 项）。

### NOVEL-A5（high）创作跑完后无「阅读刚写的内容」入口 —— ✅ 已修复（2026-06-19）
- 处理：`RunView` 创作任务 `done` 后自动 `readScene(scene_id)` 渲染「📖 刚写完的内容」预览（书籍版式）+「在作品页完整阅读 →」按钮跳作品标签；mock 无正文时回退为读取失败提示。
- 验证：Playwright mock 跑 C03S02 → done 后预览面板渲染「这是 C03S02 的 mock 最终正文…」+ 跳阅读按钮；console 零错误。测试后已还原 state/player_visible、移除 C03S02 mock 产物与 work 瞬态文件。

### NOVEL-A6（medium）write-book 仅 CLI —— 阅读侧已就绪，触发侧仍延后
- 处理（阅读侧）：CLI 产出的多章 `novels/chapter_*.txt` 已可在作品页按序连读（A1+A2 落地即覆盖）；章↔场景组装见 NOVEL-A7。
- 延后：前端发起 `write-book`（涉及真实 LLM 多章写作，风险高）暂不开放，保持 CLI；待真实写作链路稳定后再补前端触发。

### NOVEL-A7（medium）缺章↔场景组装概念 —— ✅ 已修复（2026-06-23）
- 处理：`api_novel.list_novel` 按 scene_id 前缀（C01→第1章）把场景归到对应章节，`chapters[*].scene_ids`；`NovelView` TOC 每章下展示其组成场景（可点击进入单场阅读）；修正 `RunView.recommendNextScene` 去掉「每章固定 10 场」假设，改为基于 archive 真实列表、仅以 >=99 作安全上限。
- 验证：curl `/api/novel` → 第1章 [C01S01,C01S02]、第2章 [C02S01]、第3章 [C03S01]；Playwright 点击 C01S02 子项 → 进入场景阅读「场景全本 · 第 1 章」；console 零错误。

**项目目标对齐判定**：前端已从「写小说」首要目标 **drift 到 RP 游戏 + 创作调试台**。9 条已解决优化无一涉及小说阅读。**单一最高杠杆补强 = 作品阅读标签页 + 限定到 novels/ 与 fulltext/ 的只读 API（A1+A2）**，纯只读零 LLM，落地后作者完成「写→读」闭环，重新对齐首要目标。

---

## C. 其他

（暂无新增；后续 RP / 小说阅读落地过程中发现的新问题在此追加。）

---

## 已归档（第一/二阶段，均已验证完成）

以下 9 条已在本轮 A 测前完成并验证（前端构建 + pytest + Playwright），保留为历史记录：

1. 双击启动脚本应自动打开浏览器 → `open_browser: true` + `start.bat` 修复闪退。
2. RP 输入不应让用户键入命令（`target:`） → 纯自然语言 + chip 回填。（注：RP 文案层已优化，但 GM 反馈模型本身仍需重构，见 §A。）
3. RP 显示游戏风格化 → 游戏气泡 / 骰子徽章 / 去重 narrator。
4. 概览折叠栏压缩 → 固定高度 + 外层滚动。
5. 设置图形化 / 可拖拽 / 隐藏文件名 → 设置卡片化 + server 表单 + 专家模式。
6. 文件标签无意义 → 素材库分区 + 只读预览抽屉。
7. 项目隔离 / 切换 → 切项目重置标签 + 新建自动选中（切换确认 / 最近项目 / 安全删除仍为后续）。
8. 运行→创作 + 任务卡 + 自动推荐下一场 scene_id。
9. 富交互 / 动画 → 视图淡入 / 卡片 hover / 保存成功勾选微动画 / 素材库预览抽屉滑入。
