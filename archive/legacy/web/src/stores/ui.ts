import { defineStore } from 'pinia'

// 全局 UI 面板状态（Inspector / NavRail 折叠 / 帮助面板 / 移动端抽屉）。
// 持久化键对齐 docs/frontend_design_system.md §3：na.inspector.w / na.inspector.open / na.rail.collapsed。

const W_KEY = 'na.inspector.w'
const OPEN_KEY = 'na.inspector.open'
const RAIL_KEY = 'na.rail.collapsed'

export const MIN_W = 200
export const MAX_W = 480
export const DEFAULT_W = 280

function lsGet(key: string, fallback: boolean): boolean
function lsGet(key: string, fallback: number): number
function lsGet(key: string, fallback: boolean | number): boolean | number {
  if (typeof window === 'undefined' || !window.localStorage) return fallback
  const v = window.localStorage.getItem(key)
  if (v === null) return fallback
  return typeof fallback === 'boolean' ? v === 'true' : Number(v)
}

export const useUiStore = defineStore('ui', {
  state: () => ({
    inspectorOpen: lsGet(OPEN_KEY, true) as boolean,
    inspectorWidth: lsGet(W_KEY, DEFAULT_W) as number,
    railCollapsed: lsGet(RAIL_KEY, false) as boolean,
    helpOpen: false,
    railDrawerOpen: false, // 移动端（<768px）导航抽屉开关
  }),
  getters: {
    inspectorWidthClamped(state): number {
      const w = state.inspectorWidth
      if (!Number.isFinite(w)) return DEFAULT_W
      return Math.min(MAX_W, Math.max(MIN_W, Math.round(w)))
    },
  },
  actions: {
    toggleInspector() {
      this.inspectorOpen = !this.inspectorOpen
      lsSet(OPEN_KEY, this.inspectorOpen)
    },
    closeInspector() {
      if (!this.inspectorOpen) return
      this.inspectorOpen = false
      lsSet(OPEN_KEY, false)
    },
    setInspectorWidth(w: number) {
      this.inspectorWidth = Math.min(MAX_W, Math.max(MIN_W, Math.round(w)))
      lsSet(W_KEY, this.inspectorWidth)
    },
    toggleRail() {
      this.railCollapsed = !this.railCollapsed
      lsSet(RAIL_KEY, this.railCollapsed)
    },
    toggleHelp() {
      this.helpOpen = !this.helpOpen
    },
    closeHelp() {
      this.helpOpen = false
    },
    toggleRailDrawer() {
      this.railDrawerOpen = !this.railDrawerOpen
    },
    closeRailDrawer() {
      this.railDrawerOpen = false
    },
  },
})

function lsSet(key: string, v: boolean | number) {
  if (typeof window === 'undefined' || !window.localStorage) return
  window.localStorage.setItem(key, String(v))
}
