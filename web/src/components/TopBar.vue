<script setup lang="ts">
import { computed } from 'vue'
import { useWorkspaceStore, type TabKind } from '@/stores/workspace'
import { useDark, useToggle } from '@vueuse/core'
import BaseButton from './BaseButton.vue'

const emit = defineEmits<{ (e: 'new-project'): void }>()
const ws = useWorkspaceStore()

const isDark = useDark({
  selector: 'html',
  attribute: 'data-theme',
  valueDark: 'dark',
  valueLight: 'light',
})
const toggleDark = useToggle(isDark)

const current = computed({
  get: () => ws.currentPath,
  set: (path: string) => {
    const story = ws.stories.find((s) => s.path === path)
    if (story) ws.openStory(story.path, story.name)
  },
})

function quick(kind: TabKind) {
  if (!ws.currentPath) return
  ws.openTab(kind)
}
</script>

<template>
  <header class="topbar">
    <div class="brand">Novel<span>Agent</span></div>

    <select v-model="current" class="proj" :disabled="!ws.stories.length">
      <option v-if="!ws.stories.length" value="">（暂无项目）</option>
      <option v-for="s in ws.stories" :key="s.path" :value="s.path">{{ s.name }}</option>
    </select>

    <BaseButton size="sm" variant="secondary" @click="emit('new-project')">＋ 新建项目</BaseButton>

    <span class="grow" />

    <div v-if="ws.currentPath" class="quick">
      <button class="quick__b" title="RP 对话" @click="quick('rp')">💬</button>
      <button class="quick__b" title="角色卡" @click="quick('card')">🪪</button>
      <button class="quick__b" title="创作" @click="quick('run')">✦</button>
    </div>

    <button class="theme" :title="isDark ? '切换亮色' : '切换暗色'" @click="toggleDark()">
      {{ isDark ? '☾' : '☀' }}
    </button>
  </header>
</template>

<style scoped>
.topbar {
  display: flex;
  align-items: center;
  gap: var(--sp-3);
  height: 48px;
  flex: none;
  padding: 0 var(--sp-3);
  background: var(--surface);
  border-bottom: 1px solid var(--border);
  z-index: var(--z-sticky);
}
.brand {
  font-weight: 700;
  font-size: var(--fs-lg);
  letter-spacing: -0.02em;
}
.brand span {
  color: var(--primary);
}
.proj {
  height: 30px;
  min-width: 180px;
  padding: 0 var(--sp-2);
  background: var(--bg);
  color: var(--text);
  border: 1px solid var(--border);
  border-radius: var(--radius-sm);
}
.quick {
  display: flex;
  gap: 2px;
}
.quick__b,
.theme {
  width: 32px;
  height: 32px;
  background: none;
  border: 1px solid transparent;
  border-radius: var(--radius-sm);
  cursor: pointer;
  font-size: 16px;
  color: var(--text-muted);
}
.quick__b:hover,
.theme:hover {
  background: var(--surface-2);
  color: var(--text);
}
</style>
