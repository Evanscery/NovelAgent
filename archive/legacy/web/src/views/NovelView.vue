<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import { api, type ChapterContent, type NovelIndex, type SceneContent } from '@/api/client'
import { useWorkspaceStore } from '@/stores/workspace'
import { useToastStore } from '@/stores/toast'
import EmptyState from '@/components/EmptyState.vue'

const ws = useWorkspaceStore()
const toast = useToastStore()

const index = ref<NovelIndex | null>(null)
const reading = ref<ChapterContent | SceneContent | null>(null)
const loading = ref(false)
const readingLoading = ref(false)
// null = 章节模式（读 novels/chapter_NN.txt）；scene_id = 单场全文本模式。
const activeSceneId = ref<string | null>(null)

const activeChapter = computed(() => (reading.value && 'chapter' in reading.value && !activeSceneId.value ? reading.value.chapter : 0))
const totalChars = computed(() => index.value?.chapters.reduce((s, c) => s + c.char_count, 0) || 0)

async function loadIndex() {
  if (!ws.currentPath) return
  loading.value = true
  try {
    index.value = await api.listNovel(ws.currentPath)
    if (index.value.has_novel) {
      await openChapter(index.value.chapters[0].number)
    } else if (index.value.scenes.length) {
      await openScene(index.value.scenes[0].scene_id)
    } else {
      reading.value = null
    }
  } catch (e: any) {
    toast.error(e.message || '加载作品失败')
  } finally {
    loading.value = false
  }
}

async function openChapter(num: number) {
  if (!ws.currentPath) return
  activeSceneId.value = null
  readingLoading.value = true
  try {
    reading.value = await api.readChapter(ws.currentPath, String(num))
  } catch (e: any) {
    toast.error(e.message || '读取章节失败')
  } finally {
    readingLoading.value = false
  }
}

async function openScene(sceneId: string) {
  if (!ws.currentPath) return
  activeSceneId.value = sceneId
  readingLoading.value = true
  try {
    reading.value = await api.readScene(ws.currentPath, sceneId)
  } catch (e: any) {
    toast.error(e.message || '读取场景失败')
  } finally {
    readingLoading.value = false
  }
}

function isCurrentChapter(num: number) {
  return activeSceneId.value === null && activeChapter.value === num
}
function isCurrentScene(sceneId: string) {
  return activeSceneId.value === sceneId
}

watch(() => ws.currentPath, loadIndex)
onMounted(loadIndex)
</script>

<template>
  <div v-if="loading" class="loading">加载中…</div>
  <EmptyState
    v-else-if="!index || (!index.has_novel && !index.scenes.length)"
    icon="📖"
    title="还没有可读的作品"
    hint="去「创作」跑几场（用 direct 模式），生成的章节会在这里以书籍版式呈现。mock 干跑不产生正文。"
  />
  <div v-else class="novel">
    <!-- 左侧目录：章节 + 场景 -->
    <aside class="toc scroll">
      <div class="toc__head">
        <h3>目 录</h3>
        <span v-if="index.has_novel" class="toc__meta">{{ index.chapters.length }} 章 · {{ totalChars }} 字</span>
      </div>
      <ul v-if="index.has_novel" class="toc__group">
        <li
          v-for="c in index.chapters"
          :key="c.file"
          :class="['toc__item toc__item--chapter', { on: isCurrentChapter(c.number) }]"
          @click="openChapter(c.number)"
        >
          <div class="toc__chapter-head">
            <span class="toc__num">第 {{ c.number }} 章</span>
            <span class="toc__title">{{ c.title }}</span>
            <span class="toc__count">{{ c.char_count }} 字</span>
          </div>
          <ul v-if="c.scene_ids.length" class="toc__scenes-in-chapter">
            <li
              v-for="sid in c.scene_ids"
              :key="sid"
              :class="['toc__subscene', { on: isCurrentScene(sid) }]"
              @click.stop="openScene(sid)"
            >
              {{ sid }}
            </li>
          </ul>
        </li>
      </ul>
      <details v-if="index.scenes.length" class="toc__scenes">
        <summary>场景全本（{{ index.scenes.length }}）</summary>
        <ul class="toc__group">
          <li
            v-for="s in index.scenes"
            :key="s.scene_id"
            :class="['toc__item toc__item--scene', { on: isCurrentScene(s.scene_id) }]"
            @click="openScene(s.scene_id)"
          >
            <span class="toc__num">{{ s.scene_id }}</span>
            <span class="toc__count">{{ s.char_count }} 字</span>
          </li>
        </ul>
      </details>
    </aside>

    <!-- 右侧阅读窗：书籍版式 -->
    <section class="reader scroll">
      <div v-if="readingLoading" class="loading">翻页中…</div>
      <article v-else-if="reading" class="page">
        <header class="page__head">
          <h1 class="page__title">{{ (activeSceneId ? activeSceneId : ('title' in reading ? reading.title : `第 ${reading.chapter} 章`)) }}</h1>
          <p v-if="activeSceneId" class="page__sub">场景全本 · 第 {{ reading.chapter }} 章</p>
          <p v-else class="page__sub">第 {{ reading.chapter }} 章 · {{ reading.char_count }} 字</p>
        </header>
        <div class="page__body">{{ reading.body || '（本章暂无正文）' }}</div>
      </article>
      <EmptyState v-else icon="📖" title="选择一个章节开始阅读" hint="点击左侧目录中的章节或场景。" />
    </section>
  </div>
</template>

<style scoped>
.novel {
  height: 100%;
  min-height: 0;
  display: flex;
}
.loading {
  padding: var(--sp-5);
  color: var(--text-muted);
}
/* 左侧目录 */
.toc {
  width: 300px;
  flex: none;
  border-right: 1px solid var(--border);
  background: var(--surface);
  padding: var(--sp-3);
}
.toc__head {
  display: flex;
  align-items: baseline;
  justify-content: space-between;
  padding: 0 var(--sp-2) var(--sp-3);
  border-bottom: 1px solid var(--border);
}
.toc__head h3 {
  margin: 0;
  letter-spacing: 0.2em;
  font-size: var(--fs-sm);
  color: var(--text-muted);
}
.toc__meta {
  font-size: var(--fs-xs);
  color: var(--text-faint);
}
.toc__group {
  list-style: none;
  margin: 0;
  padding: 0;
}
.toc__item {
  display: grid;
  grid-template-columns: auto 1fr auto;
  gap: var(--sp-2);
  align-items: baseline;
  padding: var(--sp-2) var(--sp-3);
  margin: var(--sp-1) 0;
  border-radius: var(--radius-sm);
  cursor: pointer;
  transition: background var(--dur-fast) var(--ease);
}
.toc__item:hover {
  background: var(--surface-2);
}
.toc__item.on {
  background: color-mix(in srgb, var(--primary) 12%, var(--surface));
  border-left: 3px solid var(--primary);
}
.toc__item--scene {
  grid-template-columns: auto 1fr;
}
.toc__item--chapter {
  display: flex;
  flex-direction: column;
  gap: var(--sp-1);
}
.toc__item--chapter > .toc__num,
.toc__item--chapter > .toc__title,
.toc__item--chapter > .toc__count {
  /* 章节头部行用 grid 子项自然排布：把头部三元素包成一行 */
}
.toc__chapter-head {
  display: grid;
  grid-template-columns: auto 1fr auto;
  gap: var(--sp-2);
  align-items: baseline;
  width: 100%;
}
.toc__scenes-in-chapter {
  list-style: none;
  margin: 0;
  padding: 0 0 0 var(--sp-4);
  display: flex;
  flex-direction: column;
  gap: 2px;
}
.toc__subscene {
  font-size: var(--fs-xs);
  color: var(--text-faint);
  font-variant-numeric: tabular-nums;
  padding: 1px var(--sp-2);
  border-radius: var(--radius-sm);
  cursor: pointer;
  transition: color var(--dur-fast) var(--ease), background var(--dur-fast) var(--ease);
}
.toc__subscene:hover {
  color: var(--text-muted);
  background: var(--surface-2);
}
.toc__subscene.on {
  color: var(--primary);
  background: color-mix(in srgb, var(--primary) 12%, var(--surface));
}
.toc__num {
  font-size: var(--fs-xs);
  color: var(--text-faint);
  font-variant-numeric: tabular-nums;
}
.toc__item.on .toc__num {
  color: var(--primary);
}
.toc__title {
  font-size: var(--fs-sm);
  color: var(--text);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.toc__count {
  font-size: var(--fs-xs);
  color: var(--text-faint);
}
.toc__scenes {
  margin-top: var(--sp-3);
  border-top: 1px dashed var(--border);
  padding-top: var(--sp-2);
}
.toc__scenes summary {
  padding: 0 var(--sp-2);
  font-size: var(--fs-xs);
  color: var(--text-muted);
  cursor: pointer;
}
/* 右侧阅读窗：书籍级排版 */
.reader {
  flex: 1 1 auto;
  min-width: 0;
  background: var(--bg);
}
.page {
  max-width: 720px;
  margin: 0 auto;
  padding: var(--sp-6) var(--sp-4) var(--sp-8);
}
.page__head {
  text-align: center;
  margin-bottom: var(--sp-6);
  padding-bottom: var(--sp-4);
  border-bottom: 1px solid var(--border);
}
.page__title {
  margin: 0;
  font-size: var(--fs-2xl);
  letter-spacing: 0.05em;
}
.page__sub {
  margin: var(--sp-2) 0 0;
  font-size: var(--fs-xs);
  color: var(--text-faint);
}
.page__body {
  font-size: var(--fs-md);
  line-height: 1.9;
  text-indent: 2em;
  color: var(--text);
  white-space: pre-wrap;
  word-break: break-word;
}
</style>
