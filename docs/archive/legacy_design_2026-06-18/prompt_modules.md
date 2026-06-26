# Prompt 模块说明

当前版本的 prompt 系统参考了 TauriTavern Agent 模式中的 Preset / PromptAssembly 思路，但做了适合本项目的简化：

- 不做前端 PromptManager。
- 不做复杂 profile 路由。
- 不做 provider 绑定层。
- 只保留文件驱动、可挂载、可审计的模块化 prompt 结构。

## 目录结构

```text
novel_project/
├── presets/
│   └── default.yaml
│
├── modules/
│   ├── core/
│   ├── modes/
│   ├── style/
│   ├── optional/
│   └── output_contracts/
│
└── prompts/
```

## 各目录职责

### `presets/`

Preset 用来声明：

- 默认模式
- 全局模块
- 文风模块
- 每个 Agent 的默认专属模块

第一版默认使用：

- `presets/default.yaml`

### `modules/core/`

放所有 Agent 共用的硬规则，例如：

- Agent 身份边界
- 文件驱动规则
- 角色认知边界
- 输出纪律

### `modules/modes/`

放运行模式模块，例如：

- `novel.md`
- `rp.md`

当前默认挂载 `novel.md`。

### `modules/style/`

放文风模块，例如：

- `default.md`
- `custom_example.md`

如果你需要客制化文风，就在这里新增模块并挂载。

### `modules/optional/`

放默认不启用的可选模块。

当前只提供：

- `nsfw_placeholder.md`

它只是扩展点，不代表当前版本默认支持相关输出。

### `modules/output_contracts/`

放输出格式模块，用于统一：

- outline
- critic report
- prose
- state update
- archive notes

这样各任务 prompt 不必重复定义格式。

### `prompts/`

这里存放任务 prompt。任务 prompt 只描述“当前 Agent 要做什么”，不再重复写所有全局规则。

## 当前组装顺序

`ContextBuilder` 会按以下顺序组装 prompt：

1. Agent 任务 prompt
2. preset 全局模块
3. preset 文风模块
4. preset 中该 Agent 的专属模块
5. `agents.yaml` 中声明的额外挂载模块
6. artifact 约束
7. 输入文件上下文
8. 当前步骤元数据

这样做的好处：

- 通用规则只写一次。
- 文风与模式可替换。
- 任务 prompt 更短、更清晰。
- 未来挂载 RP 或其他模式时，不需要重写全部 prompt。

## 如何新增文风模块

### 第一步：复制示例

复制：

```text
novel_project/modules/style/custom_example.md
```

改成你自己的名字，例如：

```text
novel_project/modules/style/noir_short_sentences.md
```

### 第二步：修改内容

写入你的文风要求，例如：

- 句子更短。
- 更冷硬。
- 更少抒情。
- 更多环境噪声与动作细节。

### 第三步：挂载到 preset

编辑：

```text
novel_project/presets/default.yaml
```

在 `modules.style` 中加入该文件路径。

### 第四步：重新运行

```bash
python -m app.main run-scene C01S02 --runner mock
```

## 如何为某个 Agent 单独挂载模块

在 `config/agents.yaml` 中给某个 Agent 加 `modules:` 字段。例如只给 `prose_writer` 增加一个特殊模块：

```yaml
prose_writer:
  modules:
    - novel_project/modules/style/noir_short_sentences.md
```

这会在该 Agent 的 prompt 组装中额外挂载该模块，而不会影响其他 Agent。

## RP 模式与 NSFW 模块说明

### RP 模式

- `modules/modes/rp.md` 是 RP 模式挂载点。
- 当前默认不启用。
- 启用后应配合 `work/player_input.md` 与 `state/player_visible.md` 使用。

### NSFW 模块

- 当前只有 `modules/optional/nsfw_placeholder.md`。
- 第一版不提供具体成人向写作指令。
- 该文件只保留未来扩展接口与安全边界提醒。

## 设计原则

1. 任务 prompt 负责“做什么”。
2. 模块负责“怎么做”和“遵守什么边界”。
3. preset 负责“默认挂载哪些模块”。
4. `agents.yaml` 负责“某个 Agent 的个性化挂载与 artifact 声明”。
5. 核心编排器只负责组装与调度，不负责编码文风本身。
