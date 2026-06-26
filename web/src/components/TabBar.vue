<script setup lang="ts">
import { ref } from 'vue'
import { useWorkspaceStore, type TabKind } from '@/stores/workspace'
import { useConfirmStore } from '@/stores/confirm'

const ws = useWorkspaceStore()
const confirm = useConfirmStore()
const addOpen = ref(false)

const ADDABLE: TabKind[] = ['overview', 'card', 'rp', 'files', 'config', 'run']

async function close(id: string, dirty: boolean) {
  if (dirty) {
    const ok = await confirm.ask({
      title: '关闭未保存的标签',
      message: '该标签有未保存的修改，确定关闭吗？',
      confirmText: '关闭',
      danger: true,
    })
    if (!ok) return
  }
  ws.closeTab(id)
}

function addTab(kind: TabKind) {
  ws.openTab(kind)
  addOpen.value = false
}

// 拖拽重排：HTML5 原生拖放（轻量，无需额外依赖体积进入热路径）。
const dragId = ref('')
function onDragStart(id: string) {
  dragId.value = id
}
function onDrop(targetId: string) {
  if (dragId.value && dragId.value !== targetId) {
    ws.reorderTabs(dragId.value, targetId)
  }
  dragId.value = ''
}
</script>

<template>
  <div class="tabbar">
    <div class="tabbar__tabs">
      <div
        v-for="t in ws.tabs"
        :key="t.id"
        :class="['tab', { active: t.id === ws.activeTabId, dragging: t.id === dragId }]"
        draggable="true"
        @click="ws.activateTab(t.id)"
        @dragstart="onDragStart(t.id)"
        @dragover.prevent
        @drop="onDrop(t.id)"
      >
        <span class="tab__icon">{{ ws.tabMeta[t.kind].icon }}</span>
        <span class="tab__title">{{ t.title }}</span>
        <span v-if="t.dirty" class="tab__dirty" title="未保存">●</span>
        <button class="tab__x" aria-label="关闭标签" @click.stop="close(t.id, t.dirty)">×</button>
      </div>
    </div>

    <div class="tabbar__add">
      <button class="add-btn" aria-label="新建标签" @click="addOpen = !addOpen">＋</button>
      <div v-if="addOpen" class="add-menu" @mouseleave="addOpen = false">
        <button v-for="k in ADDABLE" :key="k" class="add-item" @click="addTab(k)">
          <span>{{ ws.tabMeta[k].icon }}</span> {{ ws.tabMeta[k].title }}
        </button>
      </div>
    </div>
  </div>
</template>

<style scoped>
.tabbar {
  display: flex;
  align-items: center;
  background: var(--bg);
  border-bottom: 1px solid var(--border);
  height: 38px;
  flex: none;
}
.tabbar__tabs {
  display: flex;
  overflow-x: auto;
  flex: 1 1 auto;
  height: 100%;
}
.tab {
  display: flex;
  align-items: center;
  gap: var(--sp-2);
  padding: 0 var(--sp-2) 0 var(--sp-3);
  height: 100%;
  border-right: 1px solid var(--border);
  cursor: pointer;
  white-space: nowrap;
  font-size: var(--fs-sm);
  color: var(--text-muted);
  background: var(--surface);
  transition: background var(--dur-fast) var(--ease);
}
.tab:hover {
  background: var(--surface-2);
}
.tab.active {
  background: var(--bg);
  color: var(--text);
  box-shadow: inset 0 -2px 0 var(--primary);
}
.tab.dragging {
  opacity: 0.5;
}
.tab__dirty {
  color: var(--warning);
  font-size: 10px;
}
.tab__x {
  background: none;
  border: none;
  color: var(--text-faint);
  font-size: 16px;
  line-height: 1;
  cursor: pointer;
  border-radius: var(--radius-sm);
  padding: 0 4px;
}
.tab__x:hover {
  background: var(--surface-3);
  color: var(--text);
}
.tabbar__add {
  position: relative;
  flex: none;
}
.add-btn {
  width: 38px;
  height: 38px;
  background: none;
  border: none;
  color: var(--text-muted);
  font-size: 18px;
  cursor: pointer;
}
.add-btn:hover {
  background: var(--surface-2);
  color: var(--text);
}
.add-menu {
  position: absolute;
  top: 38px;
  left: 0;
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: var(--radius-md);
  box-shadow: var(--shadow-md);
  padding: var(--sp-1);
  z-index: var(--z-drawer);
  min-width: 140px;
}
.add-item {
  display: flex;
  align-items: center;
  gap: var(--sp-2);
  width: 100%;
  padding: var(--sp-2);
  background: none;
  border: none;
  border-radius: var(--radius-sm);
  cursor: pointer;
  color: var(--text);
  font-size: var(--fs-sm);
  text-align: left;
}
.add-item:hover {
  background: var(--surface-2);
}
</style>
