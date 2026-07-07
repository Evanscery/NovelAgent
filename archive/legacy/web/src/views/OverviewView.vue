<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { api, type NovelIndex, type StoryPayload } from '@/api/client'
import { useWorkspaceStore } from '@/stores/workspace'
import { useToastStore } from '@/stores/toast'
import EmptyState from '@/components/EmptyState.vue'

// bootstrap_done 由后端 load_story_payload 计算（outline/master_outline.md 非空）。
// client.ts 的 StoryPayload 暂未声明该字段（由另一并行 worker 补充），此处局部扩展。
type StoryPayloadExt = StoryPayload & { bootstrap_done?: boolean }

const ws = useWorkspaceStore()
const toast = useToastStore()
const data = ref<StoryPayloadExt | null>(null)
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

// 4 步创作进度：① 项目已创建 ② 设定已生成 ③ 写作进度 ④ 已评估。
const stepCreated = computed(() => data.value !== null)
const stepBootstrapped = computed(() => !!data.value?.bootstrap_done)
const chapterCount = computed(() => data.value?.chapters.length ?? 0)
const stepWritten = computed(() => chapterCount.value > 0)
const stepEvaluated = computed(() => !!(data.value?.evaluation && data.value.evaluation.trim()))

// 当前活跃步骤（第一个未完成的）；全完成时为 null → CTA 指向阅读。
const activeStep = computed(() => {
  if (!stepCreated.value) return 1
  if (!stepBootstrapped.value) return 2
  if (!stepWritten.value) return 3
  if (!stepEvaluated.value) return 4
  return null
})

interface Step {
  n: number
  label: string
  done: boolean
  detail: string
}
const steps = computed<Step[]>(() => [
  { n: 1, label: '项目已创建', done: stepCreated.value, detail: stepCreated.value ? projectBlurb.value || '已就绪' : '待创建' },
  { n: 2, label: '设定已生成', done: stepBootstrapped.value, detail: stepBootstrapped.value ? '设定/大纲已就绪' : '待生成设定' },
  { n: 3, label: '写作进度', done: stepWritten.value, detail: `${chapterCount.value} 章` },
  { n: 4, label: '已评估', done: stepEvaluated.value, detail: stepEvaluated.value ? '评估报告已生成' : '待评估' },
])

function gotoActiveCta() {
  switch (activeStep.value) {
    case 2:
    case 3:
    case 4:
      ws.openTab('run')
      break
    case null:
      ws.openTab('novel')
      break
    default:
      ws.openTab('run')
  }
}

const ctaLabel = computed(() => {
  switch (activeStep.value) {
    case 1:
      return '去创建项目 →'
    case 2:
      return '去生成设定 →'
    case 3:
      return '去写作 →'
    case 4:
      return '去评估 →'
    default:
      return '去阅读 →'
  }
})

async function load() {
  if (!ws.currentPath) return
  loading.value = true
  try {
    const [story, novelIdx] = await Promise.all([
      api.getStory(ws.currentPath),
      api.listNovel(ws.currentPath).catch(() => null),
    ])
    data.value = story as StoryPayloadExt
    novel.value = novelIdx
  } catch (e: any) {
    toast.error(e.message || '加载失败')
  } finally {
    loading.value = false
  }
}

onMounted(load)
</script>

<template>
  <div v-if="loading" class="loading">加载中…</div>
  <EmptyState v-else-if="!data" data-test="overview-empty" icon="◈" title="暂无概览" hint="选择或新建一个项目" />
  <div v-else class="overview scroll">
    <!-- 创作进度枢纽：4 步引导零→完成全流程（NOVEL-A4 进化） -->
    <section class="progress-hero">
      <div class="progress-hero__head">
        <div class="progress-hero__icon">📖</div>
        <div class="progress-hero__intro">
          <h2>我的作品</h2>
          <p class="progress-hero__blurb">{{ projectBlurb || '（尚未填写项目说明）' }}</p>
        </div>
      </div>
      <ol class="steps">
        <li
          v-for="s in steps"
          :key="s.n"
          :class="['step', { 'step--done': s.done, 'step--active': activeStep === s.n }]"
        >
          <div class="step__n">{{ s.done ? '✓' : s.n }}</div>
          <div class="step__body">
            <div class="step__label">{{ s.label }}</div>
            <div class="step__detail">{{ s.detail }}</div>
          </div>
        </li>
      </ol>
      <div class="progress-hero__cta">
        <button class="cta-btn" @click="gotoActiveCta">{{ ctaLabel }}</button>
      </div>
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
/* 创作进度枢纽 */
.progress-hero {
  flex: none;
  display: flex;
  flex-direction: column;
  gap: var(--sp-3);
  padding: var(--sp-5);
  border-radius: var(--radius-lg);
  border: 1px solid var(--border);
  background: linear-gradient(135deg, var(--surface), var(--surface-2));
  box-shadow: var(--shadow-sm);
}
.progress-hero__head {
  display: flex;
  align-items: center;
  gap: var(--sp-3);
}
.progress-hero__icon {
  width: 48px;
  height: 48px;
  flex: none;
  display: grid;
  place-items: center;
  border-radius: var(--radius-lg);
  background: var(--bg);
  font-size: 24px;
}
.progress-hero__intro {
  min-width: 0;
}
.progress-hero h2 {
  margin: 0;
  font-size: var(--fs-xl);
}
.progress-hero__blurb {
  margin: var(--sp-1) 0 0;
  color: var(--text-muted);
  font-size: var(--fs-sm);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.steps {
  list-style: none;
  margin: 0;
  padding: 0;
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(140px, 1fr));
  gap: var(--sp-2);
}
.step {
  display: flex;
  align-items: center;
  gap: var(--sp-2);
  padding: var(--sp-2) var(--sp-3);
  border: 1px solid var(--border);
  border-radius: var(--radius-md);
  background: var(--surface);
  transition: border-color var(--dur-fast) var(--ease), box-shadow var(--dur-fast) var(--ease);
}
.step--done {
  border-color: color-mix(in srgb, var(--success) 40%, var(--border));
}
.step--active {
  border-color: var(--primary);
  box-shadow: 0 0 0 2px color-mix(in srgb, var(--primary) 20%, transparent);
}
.step__n {
  width: 28px;
  height: 28px;
  flex: none;
  display: grid;
  place-items: center;
  border-radius: var(--radius-pill);
  background: var(--surface-3);
  color: var(--text-muted);
  font-size: var(--fs-sm);
  font-weight: 600;
}
.step--done .step__n {
  background: var(--success);
  color: var(--bg);
}
.step--active .step__n {
  background: var(--primary);
  color: var(--primary-contrast);
}
.step__body {
  min-width: 0;
}
.step__label {
  font-weight: 600;
  font-size: var(--fs-sm);
}
.step__detail {
  font-size: var(--fs-xs);
  color: var(--text-muted);
}
.progress-hero__cta {
  display: flex;
  justify-content: flex-end;
}
.cta-btn {
  padding: var(--sp-2) var(--sp-4);
  border: 1px solid var(--primary);
  background: color-mix(in srgb, var(--primary) 12%, transparent);
  color: var(--primary);
  border-radius: var(--radius-sm);
  font-weight: 600;
  cursor: pointer;
  transition: background var(--dur-fast) var(--ease);
}
.cta-btn:hover {
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
