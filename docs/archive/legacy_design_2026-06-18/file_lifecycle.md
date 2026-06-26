# 文件生命周期

## `work/`

当前场景临时工作区。一场结束后复制到 `archive/CxxSyy/`，然后清空。

保留：

- `work/.gitkeep`
- `work/reports/.gitkeep`

### 当前关键文件

- `player_input.md`：未来 RP 模式的玩家输入占位。
- `run_snapshot.md`：本轮冻结输入快照。
- `recall_report.md`：Recall 检索结果。
- `rough_outline.md`：初版场景规划。
- `outline_final.md`：最终细纲。
- `draft.md`：正文草稿。
- `final.md`：最终正文。
- `reports/`：各类审查报告。

## `state/`

长期状态目录，每场结束后更新。

- `state.md`：后台真实状态。
- `player_visible.md`：玩家或视角角色可见状态。

Statekeeper 只能根据最终正文更新状态，不得发明正文之外的新事实。

## `memory/`

长期记忆目录。

- `summaries.md`：每场客观摘要。
- `index.md`：伏笔、物品、关系、重要事实索引。
- `fulltext/`：每场最终正文全文。

## `archive/`

永久归档目录。每场一个子目录，例如：

```text
archive/C01S01/
├── player_input.md
├── run_snapshot.md
├── recall_report.md
├── rough_outline.md
├── outline_final.md
├── draft.md
├── final.md
├── reports/
├── state_after.md
└── archive_manifest.json
```

## `lore/`

稳定设定目录，低频更新。更新设定后建议提交 Git，便于追踪世界观变化。

## `presets/`

保存 prompt 组装预设。第一版默认使用：

- `presets/default.yaml`

## `modules/`

保存可挂载的 prompt 模块：

- `core/`
- `modes/`
- `style/`
- `optional/`
- `output_contracts/`

这些模块本身不是状态文件，而是 prompt 组装资源。
