import { defineStore } from 'pinia'

interface ConfirmOptions {
  title: string
  message: string
  confirmText?: string
  danger?: boolean
}

export const useConfirmStore = defineStore('confirm', {
  state: () => ({
    open: false,
    title: '',
    message: '',
    confirmText: '确认',
    danger: false,
    _resolve: null as null | ((ok: boolean) => void),
  }),
  actions: {
    ask(opts: ConfirmOptions): Promise<boolean> {
      this.title = opts.title
      this.message = opts.message
      this.confirmText = opts.confirmText || '确认'
      this.danger = !!opts.danger
      this.open = true
      return new Promise((resolve) => {
        this._resolve = resolve
      })
    },
    resolve(ok: boolean) {
      this.open = false
      if (this._resolve) this._resolve(ok)
      this._resolve = null
    },
  },
})
