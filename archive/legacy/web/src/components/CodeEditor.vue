<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, shallowRef, watch } from 'vue'
import { marked } from 'marked'
import { EditorState, Compartment, type Extension } from '@codemirror/state'
import { EditorView, keymap } from '@codemirror/view'
import { yaml } from '@codemirror/lang-yaml'
import { markdown } from '@codemirror/lang-markdown'
import { basicSetup } from 'codemirror'

const props = defineProps<{ modelValue: string; language?: string; markdown?: boolean }>()
const emit = defineEmits<{ (e: 'update:modelValue', v: string): void; (e: 'save'): void }>()

const mode = ref<'edit' | 'preview'>('edit')
const host = ref<HTMLElement | null>(null)
const view = shallowRef<EditorView | null>(null)
const langCompartment = new Compartment()

const rendered = computed(() => {
  if (!props.markdown) return ''
  return marked.parse(props.modelValue || '', { breaks: true }) as string
})

function languageExtension(): Extension {
  const lang = (props.language || '').toLowerCase()
  if (lang === 'yaml' || lang === 'yml') return yaml()
  if (lang === 'md' || lang === 'markdown') return markdown()
  return []
}

// EditorView theme: chrome + gutters reference design tokens (tokens.css).
// No hardcoded colors — syntax highlighting falls back to CodeMirror defaults.
const editorTheme = EditorView.theme({
  '&': {
    backgroundColor: 'var(--surface)',
    color: 'var(--text)',
    height: '100%',
    fontFamily: 'var(--font-mono)',
    fontSize: 'var(--fs-sm)',
  },
  '.cm-scroller': {
    fontFamily: 'var(--font-mono)',
    lineHeight: 'var(--lh-normal)',
  },
  '.cm-content': {
    caretColor: 'var(--primary)',
    padding: 'var(--sp-3)',
  },
  '.cm-gutters': {
    backgroundColor: 'var(--bg)',
    color: 'var(--text-faint)',
    border: 'none',
  },
  '.cm-activeLine': { backgroundColor: 'var(--surface-2)' },
  '.cm-activeLineGutter': {
    backgroundColor: 'var(--surface-2)',
    color: 'var(--text-muted)',
  },
  '&.cm-focused': { outline: 'none' },
  '&.cm-focused .cm-selectionBackground': { backgroundColor: 'var(--surface-3)' },
  '.cm-selectionBackground': { backgroundColor: 'var(--surface-3)' },
  '.cm-cursor': { borderLeftColor: 'var(--primary)' },
})

onMounted(() => {
  if (!host.value) return
  view.value = new EditorView({
    state: EditorState.create({
      doc: props.modelValue || '',
      extensions: [
        basicSetup,
        EditorView.lineWrapping,
        editorTheme,
        keymap.of([
          {
            key: 'Mod-s',
            preventDefault: true,
            run: () => {
              emit('save')
              return true
            },
          },
        ]),
        langCompartment.of(languageExtension()),
        EditorView.updateListener.of((v) => {
          if (v.docChanged) emit('update:modelValue', v.state.doc.toString())
        }),
      ],
    }),
    parent: host.value,
  })
})

// External modelValue updates (e.g. 还原 / 载入新文件) → replace doc without emit loop.
watch(
  () => props.modelValue,
  (val) => {
    const v = view.value
    if (!v) return
    const cur = v.state.doc.toString()
    const next = val ?? ''
    if (next !== cur) v.dispatch({ changes: { from: 0, to: cur.length, insert: next } })
  },
)

// language prop change → reconfigure language extension (preserves undo history).
watch(
  () => props.language,
  () => {
    view.value?.dispatch({ effects: langCompartment.reconfigure(languageExtension()) })
  },
)

watch(
  () => props.markdown,
  (md) => {
    if (!md) mode.value = 'edit'
  },
)

onBeforeUnmount(() => {
  view.value?.destroy()
  view.value = null
})
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
    <div v-show="mode === 'edit'" ref="host" class="editor__host" />
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
.editor__host {
  flex: 1 1 auto;
  min-height: 0;
  background: var(--surface);
  overflow: hidden;
}
.editor__host :deep(.cm-editor) {
  height: 100%;
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
