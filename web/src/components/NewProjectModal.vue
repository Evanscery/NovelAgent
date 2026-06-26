<script setup lang="ts">
import { ref } from 'vue'
import { api } from '@/api/client'
import { useWorkspaceStore } from '@/stores/workspace'
import { useToastStore } from '@/stores/toast'
import BaseModal from './BaseModal.vue'
import BaseButton from './BaseButton.vue'

const emit = defineEmits<{ (e: 'close'): void }>()
const ws = useWorkspaceStore()
const toast = useToastStore()

const name = ref('')
const theme = ref('')
const creating = ref(false)
const error = ref('')

async function create() {
  error.value = ''
  if (!name.value.trim()) {
    error.value = '请填写项目名称'
    return
  }
  creating.value = true
  try {
    const story = await api.createWorkspace(name.value.trim(), theme.value.trim())
    toast.success(`已创建项目 ${story.name}`)
    await ws.loadStories()
    ws.openStory(story.path, story.name)
    emit('close')
  } catch (e: any) {
    error.value = e.message || '创建失败'
  } finally {
    creating.value = false
  }
}
</script>

<template>
  <BaseModal title="新建项目" width="440px" @close="emit('close')">
    <div class="form">
      <label class="field">
        <span class="field__l">项目名称</span>
        <input v-model="name" class="field__c" placeholder="字母/数字/下划线/连字符/中文，1-64 字" autofocus />
      </label>
      <label class="field">
        <span class="field__l">主题 / 设定种子</span>
        <textarea v-model="theme" class="field__c" rows="3" placeholder="一句话描述世界观或主题（写入 PROJECT.md / premise）" />
      </label>
      <p v-if="error" class="err">{{ error }}</p>
      <p class="muted" style="font-size: var(--fs-xs)">
        将复用工作区模板创建自包含项目（lore / state / memory / prompts / presets …）。
      </p>
    </div>
    <template #footer>
      <BaseButton variant="ghost" @click="emit('close')">取消</BaseButton>
      <BaseButton variant="primary" :loading="creating" @click="create">创建并打开</BaseButton>
    </template>
  </BaseModal>
</template>

<style scoped>
.form {
  display: flex;
  flex-direction: column;
  gap: var(--sp-3);
}
.field {
  display: flex;
  flex-direction: column;
  gap: var(--sp-1);
}
.field__l {
  font-size: var(--fs-xs);
  color: var(--text-muted);
}
.field__c {
  padding: var(--sp-2);
  background: var(--bg);
  border: 1px solid var(--border);
  border-radius: var(--radius-sm);
  color: var(--text);
}
.err {
  margin: 0;
  color: var(--danger);
  font-size: var(--fs-sm);
}
</style>
