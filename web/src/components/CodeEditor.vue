<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { marked } from 'marked'

const props = defineProps<{ modelValue: string; language?: string; markdown?: boolean }>()
const emit = defineEmits<{ (e: 'update:modelValue', v: string): void; (e: 'save'): void }>()

const mode = ref<'edit' | 'preview'>('edit')

const rendered = computed(() => {
  if (!props.markdown) return ''
  return marked.parse(props.modelValue || '', { breaks: true }) as string
})

function onInput(e: Event) {
  emit('update:modelValue', (e.target as HTMLTextAreaElement).value)
}
function onKey(e: KeyboardEvent) {
  if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 's') {
    e.preventDefault()
    emit('save')
  }
}
watch(
  () => props.markdown,
  (md) => {
    if (!md) mode.value = 'edit'
  },
)
</script>

<template>
  <div class="editor">
    <div class="editor__bar">
      <span class="editor__lang mono">{{ language || 'text' }}</span>
      <span class="grow" />
      <template v-if="markdown">
        <button :class="['editor__tab', { on: mode === 'edit' }]" @click="mode = 'edit'">编辑</button>
        <button :class="['editor__tab', { on: mode === 'preview' }]" @click="mode = 'preview'">预览</button>
      </template>
    </div>
    <textarea
      v-show="mode === 'edit'"
      class="editor__area mono"
      :value="modelValue"
      spellcheck="false"
      @input="onInput"
      @keydown="onKey"
    />
    <!-- 预览仅渲染本地工作区内容；前端为受信任的本地创作工具。 -->
    <div v-show="mode === 'preview'" class="editor__preview markdown" v-html="rendered" />
  </div>
</template>

<style scoped>
.editor {
  display: flex;
  flex-direction: column;
  height: 100%;
  min-height: 0;
  border: 1px solid var(--border);
  border-radius: var(--radius-md);
  overflow: hidden;
  background: var(--surface);
}
.editor__bar {
  display: flex;
  align-items: center;
  gap: var(--sp-2);
  padding: var(--sp-1) var(--sp-2);
  border-bottom: 1px solid var(--border);
  background: var(--surface-2);
}
.editor__lang {
  font-size: var(--fs-xs);
  color: var(--text-muted);
  text-transform: uppercase;
}
.editor__tab {
  background: none;
  border: none;
  color: var(--text-muted);
  font-size: var(--fs-sm);
  padding: 2px var(--sp-2);
  border-radius: var(--radius-sm);
  cursor: pointer;
}
.editor__tab.on {
  background: var(--surface-3);
  color: var(--text);
}
.editor__area {
  flex: 1 1 auto;
  min-height: 0;
  resize: none;
  border: none;
  outline: none;
  padding: var(--sp-3);
  background: var(--surface);
  color: var(--text);
  font-size: var(--fs-sm);
  line-height: var(--lh-normal);
  tab-size: 2;
}
.editor__preview {
  flex: 1 1 auto;
  min-height: 0;
  overflow: auto;
  padding: var(--sp-4);
}
</style>

<style>
.markdown h1,
.markdown h2,
.markdown h3 {
  margin: 0.6em 0 0.3em;
}
.markdown p {
  margin: 0.5em 0;
}
.markdown code {
  background: var(--surface-2);
  padding: 0 4px;
  border-radius: 4px;
}
.markdown pre {
  background: var(--surface-2);
  padding: var(--sp-3);
  border-radius: var(--radius-sm);
  overflow: auto;
}
.markdown ul,
.markdown ol {
  padding-left: 1.4em;
}
</style>
