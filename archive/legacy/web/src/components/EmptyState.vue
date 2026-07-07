<script setup lang="ts">
withDefaults(defineProps<{ icon?: string; title: string; hint?: string }>(), { icon: '◌' })
</script>

<template>
  <div class="empty">
    <div class="empty__icon">{{ icon }}</div>
    <div class="empty__title">{{ title }}</div>
    <div v-if="hint" class="empty__hint">{{ hint }}</div>
    <div v-if="$slots.action" class="empty__action"><slot name="action" /></div>
  </div>
</template>

<style scoped>
.empty {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  text-align: center;
  gap: var(--sp-2);
  padding: var(--sp-8) var(--sp-4);
  color: var(--text-muted);
  height: 100%;
}
.empty__icon {
  font-size: 40px;
  opacity: 0.6;
}
.empty__title {
  font-size: var(--fs-lg);
  color: var(--text);
}
.empty__hint {
  max-width: 360px;
  font-size: var(--fs-sm);
}
.empty__action {
  margin-top: var(--sp-3);
}
</style>
