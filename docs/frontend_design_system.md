# NovelAgent 前端设计规范（Frontend Design System）

> 本文档是 NovelAgent 前端的**唯一设计基准**。任何前端改动（新组件、新页面、样式调整）都必须先对照本文档；冲突时以本文档为准，或先更新本文档再实现。
>
> 基准日期：2026-06-15。配套实现：`web/`（Vite + Vue 3 + TS）、`web/src/styles/tokens.css`（令牌唯一真相源）。

---

## 0. 为什么需要它

旧前端是 `app/main.py` 内联的一段 HTML：story 名按钮 + 一个 textarea + 一堆只读 `<pre>`。它只能看、不能操作，没有统一视觉与交互语言。本规范确立一套克制、现代、可扩展的设计语言，让后续所有界面在同一套令牌与组件契约下生长，避免再次退化成「比 cmd 还难用」的拼凑页。

---

## 1. 设计语言定位

- **参考但不照搬 SillyTavern**：吸收其「信息密度高、可玩性强、面板可拼装」的优点；但摒弃其臃肿、主题杂乱、chrome 过重的问题。
- **NovelAgent 自有风格**：
  - **克制（Restraint）**：界面服务内容，装饰最小化。无渐变滥用、无强阴影堆叠。
  - **现代（Modern）**：扁平 + 柔和层次，圆角统一，留白充足，动效短而有意义。
  - **暗色优先（Dark-first）**：创作/RP 长时间使用，默认暗色护眼；提供亮色主题。
  - **内容为王**：中央工作区永远是视觉重心，导航与检查面板为辅，可折叠让位内容。
- **三条不可违背的产品原则**（与项目五原则对齐）：
  1. 前端**不持有 canonical state**：所有真相源是后端文件，前端改动一律经 API 写回。
  2. 每个 workspace **自包含、相互隔离**：切换项目即切换全部上下文。
  3. 组件**可插拔**：视图（概览/角色卡/RP/Prompt/配置/文件/运行）彼此解耦，经窄契约（store + api client）通信。

---

## 2. 设计令牌（Design Tokens）

令牌是样式的**唯一真相源**，落在 `web/src/styles/tokens.css` 为 CSS 变量。组件**不得**硬编码颜色/间距/字号，一律引用变量。主题切换 = 切换 `:root` / `[data-theme="light"]` 变量集。

### 2.1 颜色（暗色为默认）

语义化命名，不用具体色名：

| 令牌 | 暗色 | 亮色 | 用途 |
|------|------|------|------|
| `--bg` | `#0f1115` | `#f7f8fa` | 应用底色 |
| `--surface` | `#161922` | `#ffffff` | 卡片/面板表面 |
| `--surface-2` | `#1d2230` | `#eef1f5` | 次级表面（hover/嵌套） |
| `--border` | `#2a3040` | `#dce0e8` | 分隔线/描边 |
| `--text` | `#e6e9ef` | `#1a1d23` | 主文本 |
| `--text-muted` | `#9aa3b2` | `#5b6472` | 次要文本 |
| `--primary` | `#6c8cff` | `#3b5bdb` | 主操作/强调 |
| `--primary-contrast` | `#ffffff` | `#ffffff` | 主操作前景 |
| `--success` | `#4caf78` | `#2e9e63` | 成功/已保存 |
| `--warning` | `#e0a13c` | `#c47f1a` | 警告/脏标记 |
| `--danger` | `#e5615e` | `#d63a37` | 危险/删除 |
| `--accent-rp` | `#b58bff` | `#8b5cf6` | RP/角色语义点缀 |

### 2.2 字号阶梯（type scale）

```
--font-sans: "Inter", "Segoe UI", "PingFang SC", "Microsoft YaHei", system-ui, sans-serif;
--font-mono: "JetBrains Mono", "Cascadia Code", Consolas, monospace;
--fs-xs: 12px;  --fs-sm: 13px;  --fs-md: 14px;  (基准)
--fs-lg: 16px;  --fs-xl: 20px;  --fs-2xl: 26px;
--lh-tight: 1.3; --lh-normal: 1.6;
```
正文基准 `--fs-md` 14px；编辑器/代码用 `--font-mono`。

### 2.3 间距阶梯（8px 基线，含 4px 半档）

```
--sp-1: 4px; --sp-2: 8px; --sp-3: 12px; --sp-4: 16px;
--sp-5: 24px; --sp-6: 32px; --sp-8: 48px;
```
组件内边距、间隙一律取自此阶梯，不用任意值。

### 2.4 圆角 / 阴影 / 动效

```
--radius-sm: 6px; --radius-md: 10px; --radius-lg: 14px; --radius-pill: 999px;
--shadow-sm: 0 1px 2px rgba(0,0,0,.25);
--shadow-md: 0 4px 16px rgba(0,0,0,.30);
--shadow-pop: 0 8px 32px rgba(0,0,0,.40);   (模态/弹层)
--ease: cubic-bezier(.4,0,.2,1);
--dur-fast: 120ms; --dur-mid: 200ms; --dur-slow: 320ms;
```
动效仅用于状态转移（展开/弹出/拖拽落位），**不做装饰性常驻动画**。尊重 `prefers-reduced-motion`。

### 2.5 层级（z-index）

```
--z-base: 0; --z-sticky: 100; --z-drawer: 200; --z-modal: 300; --z-toast: 400; --z-drag: 500;
```

---

## 3. 布局骨架

```
┌────────────────────────────────────────────────────────────┐
│ TopBar: [Logo] [项目选择器▾] [+新建] ……… [运行▾][主题][设置]  │  sticky, 48px
├──────────┬───────────────────────────────────┬─────────────┤
│ NavRail   │  TabBar: [概览][角色卡×][RP×][…+]   │ Inspector    │
│ (可折叠)  ├───────────────────────────────────┤ (右栏,可折叠) │
│ 概览       │                                   │ 上下文/检查   │
│ 角色卡     │        中央工作区（当前标签内容）      │ 详情/trace    │
│ RP 对话    │                                   │              │
│ Prompt     │                                   │              │
│ 配置       │                                   │              │
│ 文件       │                                   │              │
│ 运行       │                                   │              │
└──────────┴───────────────────────────────────┴─────────────┘
        ↑ 左右栏宽度均可拖拽调整（drag handle），并记忆到 localStorage
```

- **TopBar**：项目切换（核心入口）、全局动作（新建项目、运行、主题、设置）。始终可见。
- **NavRail**：视图导航；可折叠为图标条；窄屏自动收起为抽屉。
- **TabBar + 中央区**：多标签工作台，是应用主体（见 §4 标签）。
- **Inspector（右栏）**：随当前视图给上下文（如 RP 时显示状态/掷骰记录；Prompt 时显示模块挂载顺序；运行时显示 job 日志）。可折叠。
- **断点**：`>=1200px` 三栏；`768–1199px` 两栏（右栏转抽屉）；`<768px` 单栏（导航与右栏皆为抽屉）。

---

## 4. 核心组件清单与状态

所有组件状态必须完整定义：`default / hover / active / focus-visible / disabled / loading`。

### 4.1 按钮 Button
- 变体：`primary`（主操作）、`secondary`（次）、`ghost`（弱/工具栏）、`danger`（删除等）。
- 尺寸：`sm / md`。图标按钮为正方形。
- `focus-visible` 必须有 2px `--primary` 描边轮廓（键盘可达）。
- `loading` 时显示内联 spinner 并禁用。

### 4.2 表单：Input / Textarea / Select
- 统一高度（md=32px）、统一描边/圆角；focus 时 `--primary` 描边。
- 错误态：`--danger` 描边 + 下方错误文字。
- Textarea 用于长文本，可纵向 resize。

### 4.3 标签页 Tabs（工作台核心）
- 每个标签：图标 + 标题 + 关闭按钮（×）+ **脏标记圆点**（未保存时显示 `--warning` 点）。
- **可拖拽重排**（SortableJS / `@vueuse useSortable`）；拖拽时半透明 + 落位指示线。
- 溢出时横向滚动 + 「更多」下拉。
- `+` 新建标签下拉选择视图类型。
- 关闭含脏标记的标签弹确认框。

### 4.4 文件树 FileTree
- 文件夹可展开/折叠；文件点击在标签中打开。
- 选中高亮；右键/悬浮操作（重命名/新建，删除走确认）。
- 缩进用 `--sp-3` 阶梯；图标区分目录/md/yaml/json。

### 4.5 编辑器 Editor
- Markdown / 代码用 CodeMirror（`--font-mono`），YAML/JSON 语法高亮。
- 顶部工具条：保存（Ctrl/Cmd+S）、还原、字数；脏标记联动标签。
- Markdown 视图支持「编辑 / 预览」切换（`marked` 渲染）。

### 4.6 卡片 Card / 抽屉 Drawer / 模态 Modal
- Card：`--surface` + `--radius-md` + `--shadow-sm`；标题区 + 内容区。
- Drawer：右/左滑入，`--z-drawer`，遮罩可点关闭。
- Modal：居中，`--z-modal` + `--shadow-pop`；用于向导、确认、危险操作二次确认。

### 4.7 反馈：Toast / 确认框 / 空态 / 加载态
- **Toast**：右下角堆叠，`success/info/warning/error` 四色，自动消失（错误更久或需手动关）。
- **确认框 Confirm**：危险/不可逆操作（删除工作区、关闭脏标签、覆盖归档）必须二次确认。
- **空态 Empty**：无项目/无文件/无消息时给图标 + 一句话 + 主行动按钮（避免「白屏即坏」）。
- **加载态 Loading**：骨架屏或居中 spinner；按钮内联 spinner。

---

## 5. 交互模式

### 5.1 拖拽（必须流畅）
统一用 `@vueuse/core` 的 `useSortable`（底层 SortableJS）：
- **标签重排**：拖拽 TabBar 内标签调整顺序。
- **Prompt 模块挂载排序**：preset 的 `modules` 列表拖拽排序 → 写回 preset yaml（顺序即组装顺序，对结果有意义）。
- **文件移动**（后续）：文件树内拖拽移动。
- 拖拽规范：抓取手柄明确、拖拽影像半透明、落点有指示线/高亮、松手有 `--dur-fast` 落位动效、可 ESC 取消。

### 5.2 键盘快捷键
- `Ctrl/Cmd+S` 保存当前编辑；`Ctrl/Cmd+Enter` 提交 RP turn；`Ctrl/Cmd+W` 关闭当前标签（脏则确认）；`Esc` 关弹层。所有快捷键在帮助面板列出。

### 5.3 保存语义（脏标记驱动）
- 编辑即置「脏」（标签显示圆点）。
- **显式保存**为主（按钮 / 快捷键），保存成功 Toast + 清脏。
- 关闭脏标签 / 切换项目时若有未保存改动 → 确认框（保存 / 放弃 / 取消）。
- 配置与 prompt 写回均经 API；写失败保留脏态并报错，绝不静默丢失。

### 5.4 错误反馈
- API 错误 → Toast（含简短原因）+ 视图内可重试。
- 表单校验 → 字段级即时反馈。
- 运行 job 失败 → 运行面板红色状态 + 日志，可复制。

---

## 6. 可访问性与响应式底线

- 颜色对比满足 WCAG AA（正文 ≥ 4.5:1）。
- 所有交互元素键盘可达，`focus-visible` 有清晰轮廓。
- 图标按钮配 `aria-label`；模态聚焦陷阱 + ESC 关闭。
- 响应式断点见 §3；窄屏不丢功能，仅改布局（栏转抽屉）。
- 尊重 `prefers-reduced-motion` 与 `prefers-color-scheme`（首次主题默认跟随系统）。

---

## 7. 遵循约定（强制）

1. **令牌唯一**：禁止硬编码颜色/间距/字号/圆角，一律用 `tokens.css` 变量。新增视觉需求先加令牌。
2. **组件复用优先**：先用 §4 既有组件；确需新组件，按本规范定义其全套状态后再实现，并回填本文档组件清单。
3. **契约通信**：视图间只经 store + api client 通信，不互相直接引用内部实现，保持可插拔。
4. **真相在后端**：任何「修改」都必须有对应写 API 并写回文件；前端不缓存为唯一真相。
5. **先文档后代码**：界面/交互的实质变更，先更新本文档相应小节，再改实现。

---

## 8. 与后端契约的对应

前端各视图对应的后端接口见 [`ui_api_contract.md`](ui_api_contract.md)：
- 项目层 → `GET /api/stories`、`POST /api/workspace`
- 概览 → `GET /api/story`
- 角色卡 → `GET /api/card`
- RP 对话 → `POST /api/rp-turn`
- 文件/ Prompt 编辑 → `GET /api/files`、`GET/PUT /api/file`
- 配置 → `GET/PUT /api/config`
- 运行 → `POST /api/run`、`GET /api/run/<job_id>`

前端是「操作 / 展示 / 调试」层，经这些窄接口访问后端聚合数据，不直接拼接文件、不持有 canonical state。
