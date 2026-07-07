<script setup lang="ts">
import { onMounted, ref, watch } from 'vue'
import { api } from '@/api/client'
import { useWorkspaceStore, type WorkTab } from '@/stores/workspace'
import { useToastStore } from '@/stores/toast'
import CodeEditor from '@/components/CodeEditor.vue'
import BaseButton from '@/components/BaseButton.vue'

const props = defineProps<{ tab: WorkTab }>()
const ws = useWorkspaceStore()
const toast = useToastStore()

const content = ref('')
const original = ref('')
const loading = ref(false)
const saving = ref(false)
const suffix = ref('text')

const rel = props.tab.ctx?.rel as string

async function load() {
  if (!rel || !ws.currentPath) return
  loading.value = true
  try {
    const data = await api.readFile(ws.currentPath, rel)
    content.value = data.content
    original.value = data.content
    suffix.value = data.suffix
    ws.setDirty(props.tab.id, false)
  } catch (e: any) {
    toast.error(e.message || '读取失败')
  } finally {
    loading.value = false
  }
}

async function save() {
  if (!rel || !ws.currentPath) return
  saving.value = true
  try {
    await api.writeFile(ws.currentPath, rel, content.value)
    original.value = content.value
    ws.setDirty(props.tab.id, false)
    toast.success(`已保存 ${rel}`)
  } catch (e: any) {
    toast.error(e.message || '保存失败')
  } finally {
    saving.value = false
  }
}

watch(content, (v) => ws.setDirty(props.tab.id, v !== original.value))
onMounted(load)
</script>

<template>
  <div class="prompt">
    <div class="prompt__bar">
      <span class="mono prompt__path">{{ rel }}</span>
      <span v-if="tab.dirty" class="prompt__dirty">● 未保存</span>
      <span class="grow" />
      <BaseButton size="sm" variant="ghost" :disabled="!tab.dirty" @click="content = original">还原</BaseButton>
      <BaseButton size="sm" variant="primary" :loading="saving" :disabled="!tab.dirty" @click="save">
        保存 (Ctrl/Cmd+S)
      </BaseButton>
    </div>
    <div class="prompt__body">
      <div v-if="loading" class="muted" style="padding: var(--sp-4)">加载中…</div>
      <CodeEditor
        v-else
        v-model="content"
        :language="suffix"
        :markdown="suffix === 'md'"
        @save="save"
      />
    </div>
  </div>
</template>

<style scoped>
.prompt {
  display: flex;
  flex-direction: column;
  height: 100%;
  min-height: 0;
}
.prompt__bar {
  display: flex;
  align-items: center;
  gap: var(--sp-2);
  padding: var(--sp-2) var(--sp-3);
  border-bottom: 1px solid var(--border);
  background: var(--surface);
}
.prompt__path {
  font-size: var(--fs-sm);
  color: var(--text-muted);
}
.prompt__dirty {
  font-size: var(--fs-xs);
  color: var(--warning);
}
.prompt__body {
  flex: 1 1 auto;
  min-height: 0;
  padding: var(--sp-3);
}
</style>
