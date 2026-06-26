<script setup lang="ts">
// 通用按钮，状态完整（见设计规范 §4.1）。
withDefaults(
  defineProps<{
    variant?: 'primary' | 'secondary' | 'ghost' | 'danger'
    size?: 'sm' | 'md'
    loading?: boolean
    disabled?: boolean
    title?: string
    type?: 'button' | 'submit'
  }>(),
  { variant: 'secondary', size: 'md', loading: false, disabled: false, type: 'button' },
)
</script>

<template>
  <button
    :class="['btn', `btn--${variant}`, `btn--${size}`]"
    :disabled="disabled || loading"
    :type="type"
    :title="title"
  >
    <span v-if="loading" class="btn__spin" aria-hidden="true"></span>
    <slot />
  </button>
</template>

<style scoped>
.btn {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: var(--sp-2);
  border: 1px solid transparent;
  border-radius: var(--radius-sm);
  cursor: pointer;
  white-space: nowrap;
  transition: background var(--dur-fast) var(--ease), border-color var(--dur-fast) var(--ease),
    opacity var(--dur-fast) var(--ease);
}
.btn:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}
.btn--md {
  height: 32px;
  padding: 0 var(--sp-3);
  font-size: var(--fs-md);
}
.btn--sm {
  height: 26px;
  padding: 0 var(--sp-2);
  font-size: var(--fs-sm);
}
.btn--primary {
  background: var(--primary);
  color: var(--primary-contrast);
}
.btn--primary:hover:not(:disabled) {
  background: var(--primary-hover);
}
.btn--secondary {
  background: var(--surface-2);
  color: var(--text);
  border-color: var(--border);
}
.btn--secondary:hover:not(:disabled) {
  background: var(--surface-3);
}
.btn--ghost {
  background: transparent;
  color: var(--text-muted);
}
.btn--ghost:hover:not(:disabled) {
  background: var(--surface-2);
  color: var(--text);
}
.btn--danger {
  background: var(--danger);
  color: #fff;
}
.btn--danger:hover:not(:disabled) {
  background: var(--danger-hover);
}
.btn__spin {
  width: 12px;
  height: 12px;
  border: 2px solid currentColor;
  border-top-color: transparent;
  border-radius: 50%;
  animation: spin 0.6s linear infinite;
}
@keyframes spin {
  to {
    transform: rotate(360deg);
  }
}
</style>
