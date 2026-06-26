<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { useWorkspaceStore } from '@/stores/workspace'
import { useToastStore } from '@/stores/toast'
import TopBar from '@/components/TopBar.vue'
import TabBar from '@/components/TabBar.vue'
import ToastHost from '@/components/ToastHost.vue'
import ConfirmHost from '@/components/ConfirmHost.vue'
import NewProjectModal from '@/components/NewProjectModal.vue'
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
const showNew = ref(false)

const VIEW_MAP: Record<string, any> = {
  overview: OverviewView,
  novel: NovelView,
  card: CardView,
  rp: RpView,
  prompt: PromptView,
  config: ConfigView,
  files: FilesView,
  run: RunView,
}

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
      <!-- 左侧导航 -->
      <nav class="rail">
        <button
          v-for="(meta, kind) in ws.tabMeta"
          :key="kind"
          class="rail__btn"
          :title="meta.title"
          :disabled="!ws.currentPath"
          @click="ws.openTab(kind as any)"
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
    </div>

    <NewProjectModal v-if="showNew" @close="showNew = false" />
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
  padding: var(--sp-2) 0;
  gap: 2px;
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
</style>
