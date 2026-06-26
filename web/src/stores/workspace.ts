import { defineStore } from 'pinia'
import { api, type StoryItem } from '@/api/client'

// 多标签工作台的标签类型。
export type TabKind = 'overview' | 'card' | 'rp' | 'prompt' | 'config' | 'files' | 'run' | 'novel'

export interface WorkTab {
  id: string
  kind: TabKind
  title: string
  dirty: boolean
  // 视图相关的轻量上下文（如正在编辑的文件 rel / 配置名）
  ctx?: Record<string, any>
}

const TAB_META: Record<TabKind, { title: string; icon: string }> = {
  overview: { title: '概览', icon: '◈' },
  novel: { title: '作品', icon: '📖' },
  card: { title: '角色卡', icon: '🪪' },
  rp: { title: 'RP 对话', icon: '💬' },
  prompt: { title: 'Prompt', icon: '✎' },
  config: { title: '设置', icon: '⚙' },
  files: { title: '素材库', icon: '📚' },
  run: { title: '创作', icon: '✦' },
}

let tabSeq = 1

export const useWorkspaceStore = defineStore('workspace', {
  state: () => ({
    stories: [] as StoryItem[],
    currentPath: '' as string,
    currentName: '' as string,
    tabs: [] as WorkTab[],
    activeTabId: '' as string,
    loadingStories: false,
  }),
  getters: {
    activeTab(state): WorkTab | undefined {
      return state.tabs.find((t) => t.id === state.activeTabId)
    },
    hasDirty(state): boolean {
      return state.tabs.some((t) => t.dirty)
    },
    tabMeta: () => TAB_META,
  },
  actions: {
    async loadStories() {
      this.loadingStories = true
      try {
        this.stories = await api.listStories()
      } finally {
        this.loadingStories = false
      }
    },
    openStory(path: string, name: string) {
      if (this.currentPath === path) return
      this.currentPath = path
      this.currentName = name
      // 切项目即重置标签上下文（项目隔离），默认打开概览。
      this.tabs = []
      this.activeTabId = ''
      this.openTab('overview')
    },
    openTab(kind: TabKind, ctx?: Record<string, any>): WorkTab {
      // 对单例型标签（同 kind 且无独立 ctx）复用已有标签。
      const singleton = ['overview', 'novel', 'card', 'rp', 'run', 'files'].includes(kind)
      if (singleton) {
        const existing = this.tabs.find((t) => t.kind === kind)
        if (existing) {
          this.activeTabId = existing.id
          return existing
        }
      }
      const meta = TAB_META[kind]
      let title = meta.title
      if (kind === 'prompt' && ctx?.rel) title = ctx.rel.split('/').pop()
      if (kind === 'config' && ctx?.name) title = `cfg: ${ctx.name}`
      const tab: WorkTab = { id: `tab-${tabSeq++}`, kind, title, dirty: false, ctx }
      this.tabs.push(tab)
      this.activeTabId = tab.id
      return tab
    },
    activateTab(id: string) {
      this.activeTabId = id
    },
    closeTab(id: string) {
      const idx = this.tabs.findIndex((t) => t.id === id)
      if (idx === -1) return
      this.tabs.splice(idx, 1)
      if (this.activeTabId === id) {
        const next = this.tabs[idx] || this.tabs[idx - 1]
        this.activeTabId = next ? next.id : ''
      }
    },
    setDirty(id: string, dirty: boolean) {
      const tab = this.tabs.find((t) => t.id === id)
      if (tab) tab.dirty = dirty
    },
    reorderTabs(fromId: string, toId: string) {
      const from = this.tabs.findIndex((t) => t.id === fromId)
      const to = this.tabs.findIndex((t) => t.id === toId)
      if (from === -1 || to === -1) return
      const [moved] = this.tabs.splice(from, 1)
      this.tabs.splice(to, 0, moved)
    },
    setTabs(tabs: WorkTab[]) {
      this.tabs = tabs
    },
  },
})
