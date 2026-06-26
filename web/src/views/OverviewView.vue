<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { api, type NovelIndex, type StoryPayload } from '@/api/client'
import { useWorkspaceStore } from '@/stores/workspace'
import { useToastStore } from '@/stores/toast'
import EmptyState from '@/components/EmptyState.vue'

const ws = useWorkspaceStore()
const toast = useToastStore()
const data = ref<StoryPayload | null>(null)
const novel = ref<NovelIndex | null>(null)
const loading = ref(false)
const expert = ref(false)

// 面向作者的技术块（后台真相 / 玩家可见 / 摘要 / 索引 / 评估 / 日志 / 上次响应），
// 默认折叠进「专家信息」，避免把作者首页变成系统看板（NOVEL-A4）。
const EXPERT_SECTIONS: { key: keyof StoryPayload; label: string }[] = [
  { key: 'state', label: 'State（后台真相）' },
  { key: 'player_visible', label: 'Player Visible（玩家可见）' },
  { key: 'summaries', label: 'Summaries' },
  { key: 'index', label: 'Memory Index' },
  { key: 'evaluation', label: 'Evaluation' },
  { key: 'journal', label: 'Latest Journal' },
  { key: 'last_response', label: 'Last Response' },
]

const totalChars = computed(() => novel.value?.chapters.reduce((s, c) => s + c.char_count, 0) || 0)
const projectBlurb = computed(() => {
  const text = data.value?.project || ''
  const firstLine = text.split('\n').find((l) => l.trim() && !l.trim().startsWith('#')) || ''
  return firstLine.trim().slice(0, 120)
})

async function load() {
  if (!ws.currentPath) return
  loading.value = true
  try {
    const [story, novelIdx] = await Promise.all([
      api.getStory(ws.currentPath),
      api.listNovel(ws.currentPath).catch(() => null),
    ])
    data.value = story
    novel.value = novelIdx
  } catch (e: any) {
    toast.error(e.message || '加载失败')
  } finally {
    loading.value = false
  }
}

function gotoNovel() {
  ws.openTab('novel')
}

onMounted(load)
</script>

<template>
  <div v-if="loading" class="loading">加载中…</div>
  <EmptyState v-else-if="!data" icon="◈" title="暂无概览" hint="选择或新建一个项目" />
  <div v-else class="overview scroll">
    <!-- 作品主页卡：把作者最关心的「我写到哪了 / 去读我的书」放在首位（NOVEL-A4） -->
    <section class="work-hero">
      <div class="work-hero__icon">📖</div>
      <div class="work-hero__body">
        <h2>我的作品</h2>
        <p class="work-hero__blurb">{{ projectBlurb || '（尚未填写项目说明）' }}</p>
        <div class="work-hero__stats">
          <span><strong>{{ data.chapters.length }}</strong> 章</span>
          <span><strong>{{ totalChars || '—' }}</strong> 字</span>
          <span><strong>{{ data.archives.length }}</strong> 个归档场景</span>
        </div>
      </div>
      <button class="work-hero__cta" @click="gotoNovel">去阅读 →</button>
    </section>

    <div class="meta-grid">
      <div class="meta-card">
        <div class="meta-card__n">{{ data.chapters.length }}</div>
        <div class="meta-card__l">章节</div>
      </div>
      <div class="meta-card">
        <div class="meta-card__n">{{ data.archives.length }}</div>
        <div class="meta-card__l">归档场景</div>
      </div>
      <div class="meta-card">
        <div class="meta-card__n">{{ totalChars || '—' }}</div>
        <div class="meta-card__l">总字数</div>
      </div>
      <div class="meta-card">
        <div class="meta-card__n">{{ data.card_ir ? '✓' : '—' }}</div>
        <div class="meta-card__l">角色卡</div>
      </div>
    </div>

    <!-- 专家信息：默认折叠，避免向作者暴露后台真相 / last_response / card_ir 等技术 internals -->
    <details class="sec sec--expert" :open="expert" @toggle="expert = ($event.target as HTMLDetailsElement).open">
      <summary class="sec__head">专家信息 · 后台状态与运行日志</summary>
      <div class="sec__expert-body">
        <details v-for="s in EXPERT_SECTIONS" :key="s.key" class="sec sec--inner">
          <summary class="sec__head sec__head--inner">{{ s.label }}</summary>
          <pre class="sec__body">{{ data[s.key] || '（空）' }}</pre>
        </details>
        <details class="sec sec--inner">
          <summary class="sec__head sec__head--inner">Chapters / Archives</summary>
          <pre class="sec__body">{{ [...data.chapters, ...data.archives].join('\n') || '（空）' }}</pre>
        </details>
      </div>
    </details>
  </div>
</template>

<style scoped>
.overview {
  height: 100%;
  padding: var(--sp-4);
  display: flex;
  flex-direction: column;
  gap: var(--sp-3);
}
.loading {
  padding: var(--sp-5);
  color: var(--text-muted);
}
/* 作品主页卡 */
.work-hero {
  flex: none;
  display: flex;
  align-items: center;
  gap: var(--sp-4);
  padding: var(--sp-5);
  border-radius: var(--radius-lg);
  border: 1px solid var(--border);
  background: linear-gradient(135deg, var(--surface), var(--surface-2));
  box-shadow: var(--shadow-sm);
}
.work-hero__icon {
  width: 56px;
  height: 56px;
  flex: none;
  display: grid;
  place-items: center;
  border-radius: var(--radius-lg);
  background: var(--bg);
  font-size: 28px;
}
.work-hero__body {
  flex: 1 1 auto;
  min-width: 0;
}
.work-hero h2 {
  margin: 0;
  font-size: var(--fs-xl);
}
.work-hero__blurb {
  margin: var(--sp-1) 0 var(--sp-2);
  color: var(--text-muted);
  font-size: var(--fs-sm);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.work-hero__stats {
  display: flex;
  gap: var(--sp-4);
  font-size: var(--fs-sm);
  color: var(--text-muted);
}
.work-hero__stats strong {
  color: var(--text);
  font-size: var(--fs-lg);
  margin-right: 2px;
}
.work-hero__cta {
  flex: none;
  padding: var(--sp-2) var(--sp-4);
  border: 1px solid var(--primary);
  background: color-mix(in srgb, var(--primary) 12%, transparent);
  color: var(--primary);
  border-radius: var(--radius-sm);
  font-weight: 600;
  cursor: pointer;
  transition: background var(--dur-fast) var(--ease);
}
.work-hero__cta:hover {
  background: color-mix(in srgb, var(--primary) 22%, transparent);
}
.meta-grid {
  flex: none;
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(120px, 1fr));
  gap: var(--sp-3);
}
.meta-card {
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: var(--radius-md);
  padding: var(--sp-3);
  text-align: center;
}
.meta-card__n {
  font-size: var(--fs-2xl);
  font-weight: 600;
}
.meta-card__l {
  font-size: var(--fs-xs);
  color: var(--text-muted);
}
.sec {
  flex: none;
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: var(--radius-md);
  overflow: hidden;
}
.sec--expert {
  background: var(--surface);
}
.sec__head {
  padding: var(--sp-3);
  cursor: pointer;
  font-weight: 500;
  user-select: none;
}
.sec--expert > .sec__head {
  color: var(--text-muted);
  font-size: var(--fs-sm);
  border-left: 3px solid var(--text-faint);
}
.sec__expert-body {
  padding: var(--sp-2) var(--sp-3) var(--sp-3);
  display: flex;
  flex-direction: column;
  gap: var(--sp-2);
}
.sec--inner {
  background: var(--bg);
}
.sec__head--inner {
  padding: var(--sp-2) var(--sp-3);
  font-size: var(--fs-sm);
  color: var(--text-muted);
}
.sec__body {
  margin: 0;
  padding: var(--sp-3);
  border-top: 1px solid var(--border);
  background: var(--bg);
  white-space: pre-wrap;
  word-break: break-word;
  font-size: var(--fs-xs);
  max-height: 300px;
  overflow: auto;
}
</style>
