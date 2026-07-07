<script setup lang="ts">
import { useUiStore } from '@/stores/ui'
import BaseModal from './BaseModal.vue'

const ui = useUiStore()

// 全部快捷键清单 —— 与 docs/frontend_design_system.md §5.2 一致。
// Ctrl+Enter 由 RpView.vue 本地绑定实现（不在此声明语义，仅登记展示）。
interface ShortcutRow {
  keys: string
  desc: string
}
const ROWS: ShortcutRow[] = [
  { keys: 'Ctrl/Cmd + S', desc: '保存当前编辑（Prompt / 配置）' },
  { keys: 'Ctrl/Cmd + Enter', desc: '提交 RP 回合' },
  { keys: 'Ctrl/Cmd + W', desc: '关闭当前标签（脏则二次确认）' },
  { keys: '?', desc: '打开 / 关闭本帮助面板' },
  { keys: 'Esc', desc: '关闭顶层模态 / 抽屉 / 帮助' },
]
</script>

<template>
  <BaseModal title="键盘快捷键" width="420px" @close="ui.closeHelp()">
    <ul class="help-list">
      <li v-for="r in ROWS" :key="r.keys" class="help-row">
        <kbd class="help-key">{{ r.keys }}</kbd>
        <span class="help-desc">{{ r.desc }}</span>
      </li>
    </ul>
    <template #footer>
      <span class="help-note">Ctrl+Enter 在 RP 对话页本地生效</span>
    </template>
  </BaseModal>
</template>

<style scoped>
.help-list {
  list-style: none;
  margin: 0;
  padding: 0;
  display: flex;
  flex-direction: column;
  gap: var(--sp-2);
}
.help-row {
  display: flex;
  align-items: center;
  gap: var(--sp-3);
}
.help-key {
  font-family: var(--font-mono);
  font-size: var(--fs-xs);
  padding: var(--sp-1) var(--sp-2);
  background: var(--surface-2);
  border: 1px solid var(--border);
  border-radius: var(--radius-sm);
  color: var(--text);
  white-space: nowrap;
  min-width: 130px;
  text-align: center;
}
.help-desc {
  color: var(--text-muted);
  font-size: var(--fs-sm);
}
.help-note {
  font-size: var(--fs-xs);
  color: var(--text-faint);
}
</style>
