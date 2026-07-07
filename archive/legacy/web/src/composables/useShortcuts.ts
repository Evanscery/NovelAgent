import { onMounted, onUnmounted } from 'vue'
import { useWorkspaceStore } from '@/stores/workspace'
import { useConfirmStore } from '@/stores/confirm'
import { useUiStore } from '@/stores/ui'

export interface ShortcutOptions {
  // 当 Inspector 处于抽屉态（窄屏）时，Esc 应关掉它；三栏内联态不应被 Esc 关闭。
  // 返回 true 表示当前 Inspector 是抽屉。App.vue 根据响应式布局传入。
  inspectorAsDrawer?: () => boolean
}

// 判断事件目标是否在文本输入控件内 —— 输入态不拦截 ? / 单字符快捷键。
function isTextInput(t: EventTarget | null): boolean {
  if (!(t instanceof HTMLElement)) return false
  const tag = t.tagName
  if (tag === 'INPUT' || tag === 'TEXTAREA') return true
  if (t.isContentEditable) return true
  return false
}

/**
 * 全局键盘快捷键。在 App 根组件 onMounted 调用，自动 onUnmounted 注销。
 *
 * 只接管 Ctrl/Cmd+W（关标签）、?（帮助）、Esc（关顶层抽屉/帮助）。
 * **不接管** Ctrl/Cmd+Enter —— RpView.vue:95-100 自带本地 send 绑定保持原样，
 * 本组合件对其完全忽略，二者互不干扰（都是 window keydown 监听，独立触发）。
 */
export function useShortcuts(opts: ShortcutOptions = {}): void {
  const ws = useWorkspaceStore()
  const confirm = useConfirmStore()
  const ui = useUiStore()

  function onKey(e: KeyboardEvent) {
    const mod = e.ctrlKey || e.metaKey

    // Ctrl/Cmd+W —— 关闭当前标签，脏则二次确认。
    if (mod && e.key.toLowerCase() === 'w') {
      e.preventDefault()
      e.stopPropagation()
      const tab = ws.activeTab
      if (!tab) return
      void closeActiveTab(tab.id, tab.dirty)
      return
    }

    // ? —— 切换帮助面板（输入态不拦截，避免吃掉用户打字）。
    if (!mod && e.key === '?' && !isTextInput(e.target)) {
      e.preventDefault()
      ui.toggleHelp()
      return
    }

    // Esc —— 关顶层：帮助 > 导航抽屉 > Inspector 抽屉。
    // （模态 BaseModal 自带 Esc 监听，这里只补抽屉；重复关帮助是幂等的。）
    if (e.key === 'Escape') {
      if (ui.helpOpen) {
        ui.closeHelp()
        e.stopPropagation()
        return
      }
      if (ui.railDrawerOpen) {
        ui.closeRailDrawer()
        e.stopPropagation()
        return
      }
      const asDrawer = opts.inspectorAsDrawer ? opts.inspectorAsDrawer() : false
      if (asDrawer && ui.inspectorOpen) {
        ui.closeInspector()
        e.stopPropagation()
      }
    }
  }

  async function closeActiveTab(id: string, dirty: boolean) {
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

  let handler = onKey
  onMounted(() => {
    window.addEventListener('keydown', handler, true)
  })
  onUnmounted(() => {
    window.removeEventListener('keydown', handler, true)
  })
}
