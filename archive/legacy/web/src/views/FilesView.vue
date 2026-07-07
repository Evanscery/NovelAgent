<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { api, type FileEntry } from '@/api/client'
import { useWorkspaceStore } from '@/stores/workspace'
import { useToastStore } from '@/stores/toast'
import { useConfirmStore } from '@/stores/confirm'
import EmptyState from '@/components/EmptyState.vue'
import BaseButton from '@/components/BaseButton.vue'

interface Shelf {
  key: string
  title: string
  icon: string
  desc: string
}

const SHELVES: Shelf[] = [
  { key: 'lore', title: '设定集', icon: '📚', desc: '世界观、角色、地点、文风' },
  { key: 'state', title: '当前状态', icon: '🧭', desc: '后台真相与玩家可见信息' },
  { key: 'outline', title: '大纲', icon: '🗺', desc: '主线、章节与当前弧线' },
  { key: 'prompts', title: '创作指令', icon: '✎', desc: '写作、审查、归档等 Agent 指令' },
  { key: 'modules', title: '模块', icon: '🧩', desc: '风格、模式、输出契约' },
  { key: 'presets', title: '预设', icon: '🎛', desc: '模块挂载方案' },
  { key: 'front', title: '前端组件', icon: '🪪', desc: '角色卡正则前端脚本' },
  { key: 'data', title: '导入数据', icon: '📦', desc: 'card_ir、runtime_plan 等结构化资料' },
]

// 与后端 EDITABLE_DIRS / TEXT_SUFFIXES 对齐（app/web/api_files.py）。
// 重命名只允许在同名同目录内修改文件名，且新名后缀必须落在 TEXT_SUFFIXES 内。
const ALLOWED_SUFFIX = /\.(md|yaml|yml|json|txt)$/i

const ws = useWorkspaceStore()
const toast = useToastStore()
const confirm = useConfirmStore()
const files = ref<FileEntry[]>([])
const editableDirs = ref<string[]>([])
const loading = ref(false)
const filter = ref('')
const activeShelf = ref('lore')
const preview = ref<FileEntry | null>(null)
const previewContent = ref('')
const previewLoading = ref(false)

// 重命名内联编辑状态：editing 指向当前正在重命名的 FileEntry；同一时间最多一个。
const editing = ref<FileEntry | null>(null)
const renameValue = ref('')
const renaming = ref(false)
// committing 用于在 confirm.ask / api.moveFile 的 await 期间抑制 input 失焦触发的 cancelRename。
let committing = false

const editableSet = computed(() => new Set(editableDirs.value))

const shelfFiles = computed(() => {
  const q = filter.value.trim().toLowerCase()
  return files.value.filter((f) => {
    if (f.dir !== activeShelf.value) return false
    return !q || f.name.toLowerCase().includes(q) || f.rel.toLowerCase().includes(q)
  })
})

const active = computed(() => SHELVES.find((s) => s.key === activeShelf.value) || SHELVES[0])
const fileCountByShelf = computed(() => {
  const map: Record<string, number> = {}
  for (const f of files.value) map[f.dir] = (map[f.dir] || 0) + 1
  return map
})

async function load() {
  if (!ws.currentPath) return
  loading.value = true
  try {
    const data = await api.listFiles(ws.currentPath)
    files.value = data.files
    editableDirs.value = data.editable_dirs
    const firstNonEmpty = SHELVES.find((s) => fileCount(data.files, s.key) > 0)
    if (firstNonEmpty) activeShelf.value = firstNonEmpty.key
  } catch (e: any) {
    toast.error(e.message || '加载素材库失败')
  } finally {
    loading.value = false
  }
}

function fileCount(list: FileEntry[], key: string) {
  return list.filter((f) => f.dir === key).length
}

function open(f: FileEntry) {
  ws.openTab('prompt', { rel: f.rel })
}

// 轻量预览：点击卡片先只读展示前若干行，确认后再进入编辑，避免误开一堆编辑标签。
async function showPreview(f: FileEntry) {
  // 处于该卡片的重命名编辑态时，点击卡片本身不应触发预览。
  if (editing.value?.rel === f.rel) return
  preview.value = f
  previewContent.value = ''
  previewLoading.value = true
  try {
    const data = await api.readFile(ws.currentPath, f.rel)
    previewContent.value = data.content
  } catch (e: any) {
    toast.error(e.message || '读取预览失败')
    preview.value = null
  } finally {
    previewLoading.value = false
  }
}

function closePreview() {
  preview.value = null
  previewContent.value = ''
}

function editFromPreview() {
  if (preview.value) {
    const f = preview.value
    closePreview()
    open(f)
  }
}

// 预览正文：截断过长内容，避免一次性渲染超大文件。
const previewBody = computed(() => {
  const max = 6000
  const text = previewContent.value
  if (text.length <= max) return text
  return `${text.slice(0, max)}\n\n…（预览已截断，打开编辑可查看完整内容）`
})

function friendlyName(f: FileEntry) {
  return f.name.replace(/\.(md|yaml|yml|json|txt)$/i, '')
}

// 仅可编辑目录（EDITABLE_DIRS）内的文件允许重命名；非可编辑条目不显示 ✎。
function canRename(f: FileEntry): boolean {
  return editableSet.value.has(f.dir)
}

function startRename(f: FileEntry) {
  if (renaming.value) return
  editing.value = f
  renameValue.value = f.name
  renaming.value = false
  committing = false
}

// 模板 ref 回调：input 挂载时立即聚焦并全选文件名（不含后缀），便于直接覆盖主名。
function focusRenameInput(el: Element | unknown) {
  if (!(el instanceof HTMLInputElement)) return
  el.focus()
  // 选中 basename（去掉后缀），符合大多数重命名 UX。
  const dot = el.value.lastIndexOf('.')
  if (dot > 0) el.setSelectionRange(0, dot)
  else el.select()
}

function cancelRename() {
  // confirm.ask / moveFile await 期间会触发 input blur，此时不应丢弃编辑结果。
  if (committing) return
  editing.value = null
  renameValue.value = ''
  renaming.value = false
}

function validateNewName(name: string, f: FileEntry): string | null {
  const n = name.trim()
  if (!n) return '文件名不能为空'
  if (n === f.name) return null // 无变化，由调用方短路
  if (/[\\/]/.test(n) || n.includes('..')) return '文件名不能包含路径分隔符或 ..'
  if (!ALLOWED_SUFFIX.test(n)) return '后缀必须是 .md/.yaml/.yml/.json/.txt 之一'
  return null
}

async function confirmRename() {
  if (!editing.value || renaming.value) return
  const f = editing.value
  const newName = renameValue.value.trim()
  const err = validateNewName(newName, f)
  if (err) {
    toast.error(err)
    return
  }
  if (newName === f.name) {
    editing.value = null
    renameValue.value = ''
    return
  }

  // 同目录内重命名（name only），新 rel = <原 dir>/<newName>。
  const newRel = `${f.dir}/${newName}`
  const exists = files.value.some((x) => x.rel === newRel)

  committing = true
  try {
    let overwrite = false
    if (exists) {
      const ok = await confirm.ask({
        title: '目标已存在',
        message: `「${newName}」已存在，是否覆盖原文件？`,
        confirmText: '覆盖',
        danger: true,
      })
      if (!ok) {
        editing.value = null
        renameValue.value = ''
        return
      }
      overwrite = true
    }
    renaming.value = true
    try {
      await api.moveFile(ws.currentPath!, f.rel, newRel, overwrite)
      toast.success('已重命名')
      // 若正在预览该文件，关闭预览避免引用失效路径。
      if (preview.value?.rel === f.rel) closePreview()
      editing.value = null
      renameValue.value = ''
      await load()
    } catch (e: any) {
      toast.error(e?.message || '重命名失败')
    } finally {
      renaming.value = false
    }
  } finally {
    committing = false
  }
}

onMounted(load)
</script>

<template>
  <div class="library">
    <aside class="library__shelves scroll">
      <button
        v-for="s in SHELVES"
        :key="s.key"
        :class="['shelf', { on: s.key === activeShelf }]"
        @click="activeShelf = s.key"
      >
        <span class="shelf__icon">{{ s.icon }}</span>
        <span class="shelf__text">
          <strong>{{ s.title }}</strong>
          <small>{{ s.desc }}</small>
        </span>
        <span class="shelf__count">{{ fileCountByShelf[s.key] || 0 }}</span>
      </button>
    </aside>

    <section class="library__main">
      <div class="library__hero">
        <div class="hero__icon">{{ active.icon }}</div>
        <div>
          <h2>{{ active.title }}</h2>
          <p>{{ active.desc }}</p>
        </div>
        <span class="grow" />
        <input v-model="filter" class="library__filter" placeholder="搜索当前分类…" />
      </div>

      <div v-if="loading" class="loading">加载中…</div>
      <EmptyState v-else-if="!files.length" icon="🗂" title="暂无项目资料" hint="新建项目或导入剧本后，这里会显示可编辑资料。" />
      <EmptyState v-else-if="!shelfFiles.length" icon="🔎" title="没有匹配资料" hint="换一个分类或清空搜索。" />
      <div v-else class="library__grid scroll">
        <div
          v-for="f in shelfFiles"
          :key="f.rel"
          class="doc-card"
          role="button"
          tabindex="0"
          @click="showPreview(f)"
          @keydown.enter.prevent="showPreview(f)"
        >
          <div class="doc-card__top">
            <span class="doc-card__kind">{{ f.suffix || 'txt' }}</span>
            <button
              v-if="canRename(f) && editing?.rel !== f.rel"
              class="doc-card__rename"
              type="button"
              title="重命名"
              :disabled="renaming"
              @click.stop="startRename(f)"
            >✎</button>
          </div>

          <template v-if="editing?.rel === f.rel">
            <input
              v-model="renameValue"
              class="doc-card__rename-input"
              type="text"
              spellcheck="false"
              :disabled="renaming"
              :ref="focusRenameInput"
              @click.stop
              @keydown.enter.prevent="confirmRename"
              @keydown.esc.prevent="cancelRename"
              @blur="cancelRename"
            />
            <small class="doc-card__rename-hint">Enter 确认 · Esc 取消</small>
          </template>
          <template v-else>
            <strong>{{ friendlyName(f) }}</strong>
            <small>{{ active.title }} · {{ Math.max(1, Math.round(f.size / 1024)) }} KB</small>
            <span class="doc-card__cta">预览 →</span>
          </template>
        </div>
      </div>

      <Transition name="drawer">
        <aside v-if="preview" class="preview">
          <header class="preview__bar">
            <div class="preview__title">
              <span class="doc-card__kind">{{ preview.suffix || 'txt' }}</span>
              <strong>{{ friendlyName(preview) }}</strong>
            </div>
            <span class="grow" />
            <BaseButton size="sm" variant="ghost" @click="closePreview">关闭</BaseButton>
            <BaseButton size="sm" variant="primary" @click="editFromPreview">打开编辑</BaseButton>
          </header>
          <div class="preview__body scroll">
            <div v-if="previewLoading" class="muted">加载中…</div>
            <pre v-else>{{ previewBody || '（空文件）' }}</pre>
          </div>
        </aside>
      </Transition>
    </section>
  </div>
</template>

<style scoped>
.library {
  display: flex;
  height: 100%;
  min-height: 0;
}
.library__shelves {
  width: 310px;
  flex: none;
  padding: var(--sp-3);
  border-right: 1px solid var(--border);
  background: var(--surface);
  display: flex;
  flex-direction: column;
  gap: var(--sp-2);
}
.shelf {
  display: grid;
  grid-template-columns: 34px 1fr auto;
  gap: var(--sp-2);
  align-items: center;
  width: 100%;
  padding: var(--sp-3);
  border: 1px solid transparent;
  border-radius: var(--radius-md);
  background: transparent;
  color: var(--text);
  text-align: left;
  cursor: pointer;
  transition: background var(--dur-fast) var(--ease), border-color var(--dur-fast) var(--ease), transform var(--dur-fast) var(--ease);
}
.shelf:hover {
  background: var(--surface-2);
  transform: translateY(-1px);
}
.shelf.on {
  background: var(--surface-3);
  border-color: var(--primary);
}
.shelf__icon {
  width: 34px;
  height: 34px;
  display: grid;
  place-items: center;
  border-radius: var(--radius-md);
  background: var(--bg);
}
.shelf__text {
  display: flex;
  flex-direction: column;
  gap: 2px;
}
.shelf__text small,
.shelf__count {
  color: var(--text-faint);
  font-size: var(--fs-xs);
}
.library__main {
  flex: 1 1 auto;
  min-width: 0;
  display: flex;
  flex-direction: column;
  position: relative;
}
.library__hero {
  flex: none;
  display: flex;
  align-items: center;
  gap: var(--sp-3);
  padding: var(--sp-4);
  border-bottom: 1px solid var(--border);
  background: linear-gradient(135deg, var(--surface), var(--surface-2));
}
.hero__icon {
  width: 48px;
  height: 48px;
  display: grid;
  place-items: center;
  border-radius: var(--radius-lg);
  background: var(--bg);
  font-size: 24px;
}
.library__hero h2 {
  margin: 0;
}
.library__hero p {
  margin: 2px 0 0;
  color: var(--text-muted);
}
.library__filter {
  width: 240px;
  height: 34px;
  padding: 0 var(--sp-2);
  color: var(--text);
  background: var(--bg);
  border: 1px solid var(--border);
  border-radius: var(--radius-sm);
}
.loading {
  padding: var(--sp-5);
  color: var(--text-muted);
}
.library__grid {
  flex: 1 1 auto;
  min-height: 0;
  padding: var(--sp-4);
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(220px, 1fr));
  align-content: start;
  gap: var(--sp-3);
}
.doc-card {
  min-height: 150px;
  display: flex;
  flex-direction: column;
  align-items: flex-start;
  gap: var(--sp-2);
  padding: var(--sp-4);
  border: 1px solid var(--border);
  border-radius: var(--radius-lg);
  background: var(--surface);
  color: var(--text);
  text-align: left;
  cursor: pointer;
  box-shadow: var(--shadow-sm);
  transition: transform var(--dur-fast) var(--ease), border-color var(--dur-fast) var(--ease), box-shadow var(--dur-fast) var(--ease);
}
.doc-card:hover {
  transform: translateY(-2px);
  border-color: var(--primary);
  box-shadow: var(--shadow-md);
}
.doc-card:focus-visible {
  outline: 2px solid var(--primary);
  outline-offset: 2px;
}
.doc-card__top {
  width: 100%;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--sp-2);
}
.doc-card__kind {
  padding: 2px 7px;
  border-radius: var(--radius-pill);
  background: var(--surface-3);
  color: var(--text-muted);
  font-size: var(--fs-xs);
  text-transform: uppercase;
}
.doc-card__rename {
  width: 26px;
  height: 26px;
  display: grid;
  place-items: center;
  border: 1px solid transparent;
  border-radius: var(--radius-sm);
  background: transparent;
  color: var(--text-muted);
  font-size: var(--fs-md);
  line-height: 1;
  cursor: pointer;
  transition: background var(--dur-fast) var(--ease), color var(--dur-fast) var(--ease), border-color var(--dur-fast) var(--ease);
}
.doc-card__rename:hover:not(:disabled) {
  background: var(--surface-2);
  color: var(--primary);
  border-color: var(--border);
}
.doc-card__rename:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}
.doc-card small {
  color: var(--text-muted);
}
.doc-card__cta {
  margin-top: auto;
  color: var(--primary);
  font-size: var(--fs-sm);
}
.doc-card__rename-input {
  width: 100%;
  height: 32px;
  padding: 0 var(--sp-2);
  color: var(--text);
  background: var(--bg);
  border: 1px solid var(--primary);
  border-radius: var(--radius-sm);
  font-size: var(--fs-sm);
}
.doc-card__rename-input:focus {
  outline: none;
  border-color: var(--primary);
  box-shadow: 0 0 0 2px color-mix(in srgb, var(--primary) 30%, transparent);
}
.doc-card__rename-hint {
  color: var(--text-faint);
  font-size: var(--fs-xs);
}
/* 预览抽屉：从右侧滑入，覆盖在素材区上方 */
.preview {
  position: absolute;
  top: 0;
  right: 0;
  bottom: 0;
  width: min(560px, 60%);
  flex: none;
  display: flex;
  flex-direction: column;
  background: var(--surface);
  border-left: 1px solid var(--border);
  box-shadow: var(--shadow-lg);
  z-index: 5;
}
.preview__bar {
  flex: none;
  display: flex;
  align-items: center;
  gap: var(--sp-2);
  padding: var(--sp-3) var(--sp-4);
  border-bottom: 1px solid var(--border);
}
.preview__title {
  display: flex;
  align-items: center;
  gap: var(--sp-2);
  min-width: 0;
}
.preview__title strong {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.preview__body {
  flex: 1 1 auto;
  min-height: 0;
  padding: var(--sp-3) var(--sp-4);
}
.preview__body pre {
  margin: 0;
  white-space: pre-wrap;
  word-break: break-word;
  font-size: var(--fs-sm);
  color: var(--text);
}
.muted {
  color: var(--text-muted);
}
.drawer-enter-active,
.drawer-leave-active {
  transition: transform var(--dur-mid) var(--ease), opacity var(--dur-mid) var(--ease);
}
.drawer-enter-from,
.drawer-leave-to {
  transform: translateX(24px);
  opacity: 0;
}
</style>
