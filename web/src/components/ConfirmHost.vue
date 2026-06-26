<script setup lang="ts">
import { useConfirmStore } from '@/stores/confirm'
import BaseModal from './BaseModal.vue'
import BaseButton from './BaseButton.vue'

const confirm = useConfirmStore()
</script>

<template>
  <BaseModal v-if="confirm.open" :title="confirm.title" width="420px" @close="confirm.resolve(false)">
    <p style="margin: 0; color: var(--text-muted)">{{ confirm.message }}</p>
    <template #footer>
      <BaseButton variant="ghost" @click="confirm.resolve(false)">取消</BaseButton>
      <BaseButton :variant="confirm.danger ? 'danger' : 'primary'" @click="confirm.resolve(true)">
        {{ confirm.confirmText }}
      </BaseButton>
    </template>
  </BaseModal>
</template>
