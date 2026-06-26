import { defineStore } from 'pinia'

export type ToastKind = 'success' | 'info' | 'warning' | 'error'

export interface Toast {
  id: number
  kind: ToastKind
  message: string
}

let seq = 1

export const useToastStore = defineStore('toast', {
  state: () => ({ toasts: [] as Toast[] }),
  actions: {
    push(kind: ToastKind, message: string, ttl = 3200) {
      const id = seq++
      this.toasts.push({ id, kind, message })
      const life = kind === 'error' ? Math.max(ttl, 6000) : ttl
      setTimeout(() => this.dismiss(id), life)
      return id
    },
    success(message: string) {
      return this.push('success', message)
    },
    info(message: string) {
      return this.push('info', message)
    },
    warning(message: string) {
      return this.push('warning', message)
    },
    error(message: string) {
      return this.push('error', message)
    },
    dismiss(id: number) {
      this.toasts = this.toasts.filter((t) => t.id !== id)
    },
  },
})
