<script setup lang="ts">
import { useToastStore } from '@/stores/toast'
const toast = useToastStore()
</script>

<template>
  <div class="toast-host">
    <transition-group name="toast">
      <div v-for="t in toast.toasts" :key="t.id" :class="['toast', `toast--${t.kind}`]" @click="toast.dismiss(t.id)">
        <span class="toast__dot">
          <svg v-if="t.kind === 'success'" class="toast__check" viewBox="0 0 16 16" aria-hidden="true"><path d="M3.5 8.5l3 3 6-6.5" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" /></svg>
        </span>
        <span class="toast__msg">{{ t.message }}</span>
      </div>
    </transition-group>
  </div>
</template>

<style scoped>
.toast-host {
  position: fixed;
  right: var(--sp-4);
  bottom: var(--sp-4);
  display: flex;
  flex-direction: column;
  gap: var(--sp-2);
  z-index: var(--z-toast);
}
.toast {
  display: flex;
  align-items: center;
  gap: var(--sp-2);
  min-width: 240px;
  max-width: 380px;
  padding: var(--sp-3);
  background: var(--surface);
  border: 1px solid var(--border);
  border-left-width: 3px;
  border-radius: var(--radius-md);
  box-shadow: var(--shadow-md);
  cursor: pointer;
  font-size: var(--fs-sm);
}
.toast__dot {
  width: 16px;
  height: 16px;
  border-radius: 50%;
  flex: none;
  display: grid;
  place-items: center;
}
.toast__check {
  width: 16px;
  height: 16px;
  color: var(--bg);
  /* 勾选出现时做一次轻微的弹性放大，强化「已保存」的反馈 */
  transform-origin: center;
  animation: toast-check var(--dur-mid) var(--ease-bounce);
}
@keyframes toast-check {
  0% { transform: scale(0.2); opacity: 0; }
  60% { transform: scale(1.2); opacity: 1; }
  100% { transform: scale(1); opacity: 1; }
}
.toast--success {
  border-left-color: var(--success);
}
.toast--success .toast__dot {
  background: var(--success);
}
.toast--info {
  border-left-color: var(--primary);
}
.toast--info .toast__dot {
  background: var(--primary);
}
.toast--warning {
  border-left-color: var(--warning);
}
.toast--warning .toast__dot {
  background: var(--warning);
}
.toast--error {
  border-left-color: var(--danger);
}
.toast--error .toast__dot {
  background: var(--danger);
}
.toast-enter-active,
.toast-leave-active {
  transition: all var(--dur-mid) var(--ease);
}
.toast-enter-from,
.toast-leave-to {
  opacity: 0;
  transform: translateX(20px);
}
</style>
