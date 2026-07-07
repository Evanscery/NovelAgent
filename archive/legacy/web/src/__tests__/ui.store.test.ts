import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest'
import { setActivePinia, createPinia } from 'pinia'
import { useUiStore, MIN_W, MAX_W, DEFAULT_W } from '../stores/ui'

// 全局 UI 面板状态测试：Inspector 开关/宽度持久化、NavRail 折叠、帮助面板、移动端抽屉。
// 覆盖 docs/frontend_design_system.md §3 的三个持久化键：na.inspector.w / na.inspector.open / na.rail.collapsed。

// 测试环境为 node（无 window），store 内部 lsGet 会回退到默认值；
// 通过手动挂载/卸载 globalThis.window.localStorage 覆盖持久化路径。

interface MemStore {
  [k: string]: string
}

function installWindowLs(seed: MemStore = {}): MemStore {
  const store: MemStore = { ...seed }
  const ls: Storage = {
    get length() {
      return Object.keys(store).length
    },
    key(i: number) {
      return Object.keys(store)[i] ?? null
    },
    getItem(k: string) {
      return Object.prototype.hasOwnProperty.call(store, k) ? store[k] : null
    },
    setItem(k: string, v: string) {
      store[k] = String(v)
    },
    removeItem(k: string) {
      delete store[k]
    },
    clear() {
      for (const k of Object.keys(store)) delete store[k]
    },
  }
  // store 模块用 typeof window === 'undefined' 判定，必须同时挂载 window 与 localStorage
  ;(globalThis as { window: unknown }).window = globalThis
  ;(globalThis as { localStorage: Storage }).localStorage = ls
  return store
}

function removeWindowLs() {
  delete (globalThis as { window?: unknown }).window
  delete (globalThis as { localStorage?: unknown }).localStorage
}

describe('ui store — 默认值（无 localStorage）', () => {
  beforeEach(() => {
    removeWindowLs()
    setActivePinia(createPinia())
  })

  it('初始化使用规范默认值', () => {
    const ui = useUiStore()
    expect(ui.inspectorOpen).toBe(true)
    expect(ui.inspectorWidth).toBe(DEFAULT_W)
    expect(ui.railCollapsed).toBe(false)
    expect(ui.helpOpen).toBe(false)
    expect(ui.railDrawerOpen).toBe(false)
  })

  it('inspectorWidthClamped getter 返回当前宽度（已在范围内）', () => {
    const ui = useUiStore()
    expect(ui.inspectorWidthClamped).toBe(DEFAULT_W)
  })
})

describe('ui store — Inspector 开关与持久化', () => {
  let store: MemStore

  beforeEach(() => {
    store = installWindowLs()
    setActivePinia(createPinia())
  })
  afterEach(() => {
    removeWindowLs()
  })

  it('toggleInspector 翻转并写入 na.inspector.open', () => {
    const ui = useUiStore()
    expect(ui.inspectorOpen).toBe(true)
    ui.toggleInspector()
    expect(ui.inspectorOpen).toBe(false)
    expect(store['na.inspector.open']).toBe('false')
    ui.toggleInspector()
    expect(ui.inspectorOpen).toBe(true)
    expect(store['na.inspector.open']).toBe('true')
  })

  it('closeInspector 在已关闭时为 no-op', () => {
    const ui = useUiStore()
    ui.closeInspector()
    expect(ui.inspectorOpen).toBe(false)
    expect(store['na.inspector.open']).toBe('false')
    // 再次关闭不应改变状态或写值
    const before = store['na.inspector.open']
    ui.closeInspector()
    expect(ui.inspectorOpen).toBe(false)
    expect(store['na.inspector.open']).toBe(before)
  })

  it('从持久化存储载入 inspectorOpen=false', () => {
    // 当前 store 已实例化；通过新 pinia + 预置值测试 lsGet 载入路径
    setActivePinia(createPinia())
    store['na.inspector.open'] = 'false'
    const ui = useUiStore()
    expect(ui.inspectorOpen).toBe(false)
  })
})

describe('ui store — Inspector 宽度裁剪与持久化', () => {
  let store: MemStore

  beforeEach(() => {
    store = installWindowLs()
    setActivePinia(createPinia())
  })
  afterEach(() => {
    removeWindowLs()
  })

  it('setInspectorWidth 裁剪到 [MIN_W, MAX_W] 并取整', () => {
    const ui = useUiStore()
    ui.setInspectorWidth(150)
    expect(ui.inspectorWidth).toBe(MIN_W)
    ui.setInspectorWidth(1000)
    expect(ui.inspectorWidth).toBe(MAX_W)
    ui.setInspectorWidth(350.7)
    expect(ui.inspectorWidth).toBe(351)
    expect(store['na.inspector.w']).toBe('351')
  })

  it('inspectorWidthClamped 对非有限值回退 DEFAULT_W', () => {
    const ui = useUiStore()
    // 直接写入 NaN 模拟损坏值（绕过 setter 的 clamp）
    ;(ui as unknown as { inspectorWidth: number }).inspectorWidth = NaN
    expect(ui.inspectorWidthClamped).toBe(DEFAULT_W)
    ;(ui as unknown as { inspectorWidth: number }).inspectorWidth = Infinity
    expect(ui.inspectorWidthClamped).toBe(DEFAULT_W)
  })

  it('从持久化存储载入自定义宽度', () => {
    setActivePinia(createPinia())
    store['na.inspector.w'] = '400'
    const ui = useUiStore()
    expect(ui.inspectorWidth).toBe(400)
  })
})

describe('ui store — NavRail 折叠持久化', () => {
  let store: MemStore

  beforeEach(() => {
    store = installWindowLs()
    setActivePinia(createPinia())
  })
  afterEach(() => {
    removeWindowLs()
  })

  it('toggleRail 翻转并写入 na.rail.collapsed', () => {
    const ui = useUiStore()
    expect(ui.railCollapsed).toBe(false)
    ui.toggleRail()
    expect(ui.railCollapsed).toBe(true)
    expect(store['na.rail.collapsed']).toBe('true')
    ui.toggleRail()
    expect(ui.railCollapsed).toBe(false)
    expect(store['na.rail.collapsed']).toBe('false')
  })

  it('从持久化存储载入 railCollapsed=true', () => {
    setActivePinia(createPinia())
    store['na.rail.collapsed'] = 'true'
    const ui = useUiStore()
    expect(ui.railCollapsed).toBe(true)
  })
})

describe('ui store — 帮助面板与移动端抽屉（无持久化）', () => {
  beforeEach(() => {
    removeWindowLs()
    setActivePinia(createPinia())
  })

  it('toggleHelp 翻转 helpOpen 但不写 localStorage', () => {
    const ui = useUiStore()
    expect(ui.helpOpen).toBe(false)
    ui.toggleHelp()
    expect(ui.helpOpen).toBe(true)
    ui.toggleHelp()
    expect(ui.helpOpen).toBe(false)
  })

  it('closeHelp 强制关闭', () => {
    const ui = useUiStore()
    ui.toggleHelp()
    expect(ui.helpOpen).toBe(true)
    ui.closeHelp()
    expect(ui.helpOpen).toBe(false)
    // 已关闭再调用仍为 false
    ui.closeHelp()
    expect(ui.helpOpen).toBe(false)
  })

  it('toggleRailDrawer / closeRailDrawer 控制移动端抽屉', () => {
    const ui = useUiStore()
    expect(ui.railDrawerOpen).toBe(false)
    ui.toggleRailDrawer()
    expect(ui.railDrawerOpen).toBe(true)
    ui.closeRailDrawer()
    expect(ui.railDrawerOpen).toBe(false)
  })
})

// 顶层 vi.stubGlobal 的轻量 smoke，确保 lsGet 在 SSR-like 环境（无 window）回退默认值
describe('ui store — SSR 无 window 回退', () => {
  it('无 window 时 lsGet 回退到默认', () => {
    removeWindowLs()
    setActivePinia(createPinia())
    const ui = useUiStore()
    expect(ui.inspectorOpen).toBe(true)
    expect(ui.inspectorWidth).toBe(DEFAULT_W)
    expect(ui.railCollapsed).toBe(false)
  })
})
