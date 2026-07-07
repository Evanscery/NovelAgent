<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useMediaQuery } from '@vueuse/core'
import { useWorkspaceStore, type TabKind } from '@/stores/workspace'
import { useToastStore } from '@/stores/toast'
import { useUiStore } from '@/stores/ui'
import { useShortcuts } from '@/composables/useShortcuts'
import TopBar from '@/components/TopBar.vue'
import TabBar from '@/components/TabBar.vue'
import ToastHost from '@/components/ToastHost.vue'
import ConfirmHost from '@/components/ConfirmHost.vue'
import NewProjectModal from '@/components/NewProjectModal.vue'
import InspectorHost from '@/components/InspectorHost.vue'
import HelpPanel from '@/components/HelpPanel.vue'
import EmptyState from '@/components/EmptyState.vue'
import BaseButton from '@/components/BaseButton.vue'

import OverviewView from '@/views/OverviewView.vue'
import NovelView from '@/views/NovelView.vue'
import CardView from '@/views/CardView.vue'
import RpView from '@/views/RpView.vue'
import PromptView from '@/views/PromptView.vue'
import ConfigView from '@/views/ConfigView.vue'
import FilesView from '@/views/FilesView.vue'
import RunView from '@/views/RunView.vue'

const ws = useWorkspaceStore()
const toast = useToastStore()
const ui = useUiStore()
const showNew = ref(false)

const VIEW_MAP: Record<TabKind, any> = {
  overview: OverviewView,
  novel: NovelView,
  card: CardView,
  rp: RpView,
  prompt: PromptView,
  config: ConfigView,
  files: FilesView,
  run: RunView,
}

// 响应式断点（docs/frontend_design_system.md §3）。
const is3col = useMediaQuery('(min-width: 1200px)')
const isDesktop = useMediaQuery('(min-width: 768px)')
const layout = computed(() => (is3col.value ? '3col' : isDesktop.value ? 'inspector-drawer' : 'mobile'))

// 内联 Inspector 仅在三栏态显示；其余态以抽屉覆盖。
const inspectorInline = computed(() => layout.value === '3col' && ui.inspectorOpen)
const inspectorDrawer = computed(() => layout.value !== '3col' && ui.inspectorOpen)
// 内联导航栏在 ≥768px 显示；<768px 改为抽屉。
const railInline = computed(() => isDesktop.value)

// 全局快捷键：Ctrl/Cmd+W 关标签、? 帮助、Esc 关抽屉；不接管 Ctrl+Enter（RpView 本地绑定保留）。
useShortcuts({ inspectorAsDrawer: () => layout.value !== '3col' })

onMounted(async () => {
  try {
    await ws.loadStories()
    if (ws.stories.length) ws.openStory(ws.stories[0].path, ws.stories[0].name)
  } catch (e: any) {
    toast.error(e.message || '无法连接后端')
  }
})
</script>

<template>
  <div class="shell">
    <TopBar @new-project="showNew = true" />

    <div class="body">
      <!-- 左侧导航（内联：≥768px，可折叠） -->
      <nav v-if="railInline" class="rail" :class="{ collapsed: ui.railCollapsed }">
        <button
          class="rail__toggle"
          :title="ui.railCollapsed ? '展开导航' : '折叠导航'"
          aria-label="折叠/展开导航"
          @click="ui.toggleRail()"
        >
          {{ ui.railCollapsed ? '»' : '«' }}
        </button>
        <button
          v-for="(meta, kind) in ws.tabMeta"
          :key="kind"
          class="rail__btn"
          :title="meta.title"
          :disabled="!ws.currentPath"
          @click="ws.openTab(kind as TabKind)"
        >
          <span class="rail__icon">{{ meta.icon }}</span>
          <span class="rail__label">{{ meta.title }}</span>
        </button>
      </nav>

      <!-- 中央工作区 -->
      <main class="work">
        <template v-if="ws.currentPath">
          <TabBar />
          <div class="work__view grow">
            <Transition name="view-fade" mode="out-in">
              <component
                :is="VIEW_MAP[ws.activeTab.kind]"
                v-if="ws.activeTab"
                :key="ws.activeTab.id"
                :tab="ws.activeTab"
              />
              <EmptyState v-else icon="◈" title="没有打开的标签" hint="从左侧导航或 ＋ 打开一个视图" />
            </Transition>
          </div>
        </template>

        <EmptyState
          v-else
          icon="📖"
          title="欢迎使用 NovelAgent 工作台"
          hint="创建一个项目开始你的多 Agent 小说 / RP 创作。每个项目自包含、相互隔离。"
        >
          <template #action>
            <BaseButton variant="primary" @click="showNew = true">＋ 新建项目</BaseButton>
          </template>
        </EmptyState>
      </main>

      <!-- Inspector 内联（三栏态） -->
      <InspectorHost v-if="inspectorInline" />
    </div>

    <!-- Inspector 抽屉（768-1199px 与 <768px） -->
    <div v-if="inspectorDrawer" class="drawer-overlay" @click.self="ui.closeInspector()">
      <InspectorHost class="drawer-panel" />
    </div>

    <!-- 移动端导航抽屉（<768px） -->
    <div v-if="!railInline && ui.railDrawerOpen" class="drawer-overlay" @click.self="ui.closeRailDrawer()">
      <nav class="rail drawer-panel drawer-left">
        <button
          v-for="(meta, kind) in ws.tabMeta"
          :key="kind"
          class="rail__btn"
          :title="meta.title"
          :disabled="!ws.currentPath"
          @click="ws.openTab(kind as TabKind); ui.closeRailDrawer()"
        >
          <span class="rail__icon">{{ meta.icon }}</span>
          <span class="rail__label">{{ meta.title }}</span>
        </button>
      </nav>
    </div>

    <NewProjectModal v-if="showNew" @close="showNew = false" />
    <HelpPanel v-if="ui.helpOpen" />
    <ToastHost />
    <ConfirmHost />
  </div>
</template>

<style scoped>
.shell {
  display: flex;
  flex-direction: column;
  height: 100%;
}
.body {
  flex: 1 1 auto;
  min-height: 0;
  display: flex;
}
.rail {
  width: 84px;
  flex: none;
  background: var(--surface);
  border-right: 1px solid var(--border);
  display: flex;
  flex-direction: column;
  padding: var(--sp-1) 0;
  gap: 2px;
  transition: width var(--dur-fast) var(--ease);
}
.rail.collapsed {
  width: 52px;
}
.rail__toggle {
  display: flex;
  align-items: center;
  justify-content: center;
  height: 28px;
  margin-bottom: var(--sp-1);
  background: none;
  border: none;
  color: var(--text-faint);
  cursor: pointer;
  font-size: 14px;
}
.rail__toggle:hover {
  color: var(--text);
  background: var(--surface-2);
}
.rail__btn {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 2px;
  padding: var(--sp-2) 0;
  background: none;
  border: none;
  cursor: pointer;
  color: var(--text-muted);
  border-left: 2px solid transparent;
}
.rail__btn:hover:not(:disabled) {
  background: var(--surface-2);
  color: var(--text);
}
.rail__btn:disabled {
  opacity: 0.35;
  cursor: not-allowed;
}
.rail__icon {
  font-size: 18px;
}
.rail__label {
  font-size: var(--fs-xs);
}
.rail.collapsed .rail__label {
  display: none;
}
.rail.collapsed .rail__btn {
  padding: var(--sp-3) 0;
}
.work {
  flex: 1 1 auto;
  min-width: 0;
  display: flex;
  flex-direction: column;
}
.work__view {
  min-height: 0;
  overflow: hidden;
}
.view-fade-enter-active,
.view-fade-leave-active {
  transition: opacity var(--dur-fast) var(--ease), transform var(--dur-fast) var(--ease);
}
.view-fade-enter-from,
.view-fade-leave-to {
  opacity: 0;
  transform: translateY(4px);
}

/* —— 抽屉覆盖层（Inspector / 移动端导航） —— */
.drawer-overlay {
  position: fixed;
  inset: 0;
  background: var(--overlay);
  z-index: var(--z-drawer);
  display: flex;
  justify-content: flex-end;
}
.drawer-panel {
  height: 100%;
  box-shadow: var(--shadow-pop);
  animation: drawer-in var(--dur-mid) var(--ease);
}
.drawer-left {
  margin-right: auto;
  width: 200px;
}
@keyframes drawer-in {
  from {
    transform: translateX(24px);
    opacity: 0;
  }
  to {
    transform: none;
    opacity: 1;
  }
}
</style>
