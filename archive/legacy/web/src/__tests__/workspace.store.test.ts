import { describe, it, expect, beforeEach } from 'vitest'
import { setActivePinia, createPinia } from 'pinia'
import { useWorkspaceStore } from '../stores/workspace'

describe('workspace store — 多标签交互', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
  })

  it('打开项目默认打开概览标签', () => {
    const ws = useWorkspaceStore()
    ws.openStory('workspaces/foo', 'foo')
    expect(ws.currentName).toBe('foo')
    expect(ws.tabs.length).toBe(1)
    expect(ws.tabs[0].kind).toBe('overview')
    expect(ws.activeTab?.kind).toBe('overview')
  })

  it('单例标签复用，prompt 标签可多开', () => {
    const ws = useWorkspaceStore()
    ws.openStory('workspaces/foo', 'foo')
    ws.openTab('rp')
    ws.openTab('rp') // 复用
    expect(ws.tabs.filter((t) => t.kind === 'rp').length).toBe(1)
    ws.openTab('prompt', { rel: 'prompts/a.md' })
    ws.openTab('prompt', { rel: 'prompts/b.md' })
    expect(ws.tabs.filter((t) => t.kind === 'prompt').length).toBe(2)
  })

  it('关闭活动标签会切到相邻标签', () => {
    const ws = useWorkspaceStore()
    ws.openStory('workspaces/foo', 'foo')
    const rp = ws.openTab('rp')
    const card = ws.openTab('card')
    expect(ws.activeTabId).toBe(card.id)
    ws.closeTab(card.id)
    expect(ws.activeTabId).toBe(rp.id)
  })

  it('脏标记跟踪与全局 hasDirty', () => {
    const ws = useWorkspaceStore()
    ws.openStory('workspaces/foo', 'foo')
    const t = ws.openTab('prompt', { rel: 'prompts/a.md' })
    expect(ws.hasDirty).toBe(false)
    ws.setDirty(t.id, true)
    expect(ws.hasDirty).toBe(true)
  })

  it('拖拽重排标签顺序', () => {
    const ws = useWorkspaceStore()
    ws.openStory('workspaces/foo', 'foo')
    const a = ws.openTab('rp')
    const b = ws.openTab('card')
    const overviewId = ws.tabs[0].id
    ws.reorderTabs(a.id, overviewId) // 把 rp 拖到 overview 前
    expect(ws.tabs[0].id).toBe(a.id)
    expect(ws.tabs.map((t) => t.id)).toContain(b.id)
  })

  it('切换项目重置标签（项目隔离）', () => {
    const ws = useWorkspaceStore()
    ws.openStory('workspaces/foo', 'foo')
    ws.openTab('rp')
    ws.openTab('card')
    expect(ws.tabs.length).toBe(3)
    ws.openStory('workspaces/bar', 'bar')
    expect(ws.tabs.length).toBe(1)
    expect(ws.tabs[0].kind).toBe('overview')
  })
})
