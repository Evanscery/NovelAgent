<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref } from 'vue'
import { api, type RunJob, type SceneContent } from '@/api/client'
import { useWorkspaceStore } from '@/stores/workspace'
import { useToastStore } from '@/stores/toast'
import BaseButton from '@/components/BaseButton.vue'

const ws = useWorkspaceStore()
const toast = useToastStore()

const mode = ref<'draft' | 'rp' | 'import' | 'book' | 'eval'>('draft')
const runner = ref<'mock' | 'pi_rpc' | 'direct'>('mock')
const sceneId = ref('C01S01')
const recommended = ref(false)
const rpText = ref('')
const importInput = ref('')
// book 模式参数：写整本书。
const chapters = ref(3)
const minWords = ref(3000)
// eval 模式：评估完成后给一个去概览看报告的入口。
const evalDone = ref(false)
const expert = ref(false)
const job = ref<RunJob | null>(null)
const running = ref(false)
// NOVEL-A5：创作完成后拉取刚写的场景正文做预览。
const preview = ref<SceneContent | null>(null)
const previewLoading = ref(false)
const previewError = ref('')
let timer: number | null = null

// 从已有归档推断「下一场」编号，免去玩家手动维护 C0xS0y 的技术细节。
// 基于 archive/C0xS0y 的真实列表，不假设每章固定场数（NOVEL-A7）。
function recommendNextScene(chapters: string[], archives: string[]): string {
  const ids = [...chapters, ...archives]
    .map((s) => (s || '').trim())
    .filter((s) => /^C\d{2}S\d{2}$/i.test(s))
  if (!ids.length) return 'C01S01'
  // 取最大 (chapter, scene)。
  const max = ids.reduce(
    (acc, id) => {
      const c = parseInt(id.slice(1, 3), 10)
      const s = parseInt(id.slice(4, 6), 10)
      if (c > acc.c || (c === acc.c && s > acc.s)) return { c, s }
      return acc
    },
    { c: 0, s: 0 },
  )
  // 同章下一场；场次溢出两位（>=99）才进入下一章第 1 场（安全上限，非固定章长假设）。
  if (max.s >= 99) return `C${String(max.c + 1).padStart(2, '0')}S01`
  return `C${String(max.c).padStart(2, '0')}S${String(max.s + 1).padStart(2, '0')}`
}

const sceneIdHint = computed(() =>
  recommended.value ? '已根据当前进度自动推荐，可直接创作。' : '例如 C01S01。',
)

// book 模式：把 job.logs 里含「第 N 章」的行抽成逐章进度列表。
const chapterProgress = computed(() => {
  const logs = job.value?.logs || []
  return logs.filter((l) => /第\s*\d+\s*章/.test(l))
})

function gotoOverview() {
  ws.openTab('overview')
}

function stopPoll() {
  if (timer) {
    clearInterval(timer)
    timer = null
  }
}

async function poll(jobId: string) {
  stopPoll()
  timer = window.setInterval(async () => {
    try {
      const j = await api.getJob(jobId)
      job.value = j
      if (j.status === 'done' || j.status === 'error') {
        stopPoll()
        running.value = false
        if (j.status === 'done') {
          if (mode.value === 'draft' && j.result?.scene_id) {
            toast.success('创作任务完成')
            await loadPreview(j.result.scene_id)
          } else if (mode.value === 'book') {
            const n = Array.isArray(j.result?.chapters_written)
              ? j.result.chapters_written.length
              : 0
            toast.success(`已写完 ${n} 章`)
            // 零→完成路径可发现：写完直接预览第一章，引导去作品页阅读。
            if (n > 0) await loadPreview('C01S01')
          } else if (mode.value === 'eval') {
            toast.success('评估完成')
            evalDone.value = true
          } else {
            toast.success('创作任务完成')
          }
        } else {
          toast.error(j.error || '创作失败')
        }
      }
    } catch (e: any) {
      stopPoll()
      running.value = false
      toast.error(e.message || '轮询失败')
    }
  }, 700)
}

async function loadPreview(sceneId: string) {
  if (!ws.currentPath) return
  preview.value = null
  previewError.value = ''
  previewLoading.value = true
  try {
    preview.value = await api.readScene(ws.currentPath, sceneId)
  } catch (e: any) {
    previewError.value = e.message || '读取刚写的正文失败'
  } finally {
    previewLoading.value = false
  }
}

function readInNovel() {
  if (preview.value) {
    ws.openTab('novel')
  }
}

async function start() {
  if (!ws.currentPath && mode.value !== 'import') {
    toast.warning('请先选择项目')
    return
  }
  if (mode.value === 'book' && chapters.value < 1) {
    toast.warning('章节数至少为 1')
    return
  }
  const kindMap = {
    draft: 'run-scene',
    rp: 'rp-turn',
    import: 'import',
    book: 'write-book',
    eval: 'evaluate-book',
  } as const
  const kind = kindMap[mode.value]
  const params: Record<string, unknown> = { story_path: ws.currentPath }
  if (mode.value === 'draft') {
    params.scene_id = sceneId.value
    params.runner = runner.value
  } else if (mode.value === 'rp') {
    params.text = rpText.value
  } else if (mode.value === 'import') {
    params.input = importInput.value
  } else if (mode.value === 'book') {
    params.chapters = chapters.value
    params.min_words = minWords.value
    params.runner = runner.value
  } else if (mode.value === 'eval') {
    params.runner = runner.value
  }
  running.value = true
  job.value = null
  preview.value = null
  previewError.value = ''
  evalDone.value = false
  try {
    const started = await api.startRun(kind, params)
    job.value = started
    poll(started.job_id)
  } catch (e: any) {
    running.value = false
    toast.error(e.message || '启动失败')
  }
}

function onExpertToggle(e: Event) {
  expert.value = (e.target as HTMLDetailsElement).open
}

async function loadRecommendation() {
  if (!ws.currentPath) return
  try {
    const data = await api.getStory(ws.currentPath)
    const next = recommendNextScene(data.chapters, data.archives)
    sceneId.value = next
    recommended.value = true
  } catch {
    // 推荐失败不影响手动输入，静默回退。
    recommended.value = false
  }
}

onMounted(loadRecommendation)
onUnmounted(stopPoll)
</script>

<template>
  <div class="creation scroll">
    <section class="hero">
      <div class="hero__icon">✦</div>
      <div>
        <h2>创作控制台</h2>
        <p>把技术运行包装成创作者能理解的任务：写下一场、推进 RP、导入素材。</p>
      </div>
    </section>

    <section class="modes">
      <button :class="['mode', { on: mode === 'draft' }]" @click="mode = 'draft'">
        <span>✍</span>
        <strong>写下一场</strong>
        <small>运行完整创作流水线，生成并归档一个场景。</small>
      </button>
      <button :class="['mode', { on: mode === 'book' }]" @click="mode = 'book'">
        <span>📚</span>
        <strong>写整本书</strong>
        <small>一次写多章正文，逐章导出 txt。</small>
      </button>
      <button :class="['mode', { on: mode === 'eval' }]" @click="mode = 'eval'">
        <span>📊</span>
        <strong>评估</strong>
        <small>对整本书做评估，生成评估报告。</small>
      </button>
      <button :class="['mode', { on: mode === 'rp' }]" @click="mode = 'rp'">
        <span>💬</span>
        <strong>推进 RP</strong>
        <small>输入玩家行动，立即推进一回合。</small>
      </button>
      <button :class="['mode', { on: mode === 'import' }]" @click="mode = 'import'">
        <span>📥</span>
        <strong>导入素材</strong>
        <small>导入角色卡、剧本、设定集或小说文本。</small>
      </button>
    </section>

    <section class="panel">
      <template v-if="mode === 'draft'">
        <label class="field">
          <span>场景编号</span>
          <input v-model="sceneId" />
          <small>{{ sceneIdHint }}</small>
        </label>
        <label class="field">
          <span>运行方式</span>
          <select v-model="runner">
            <option value="mock">干跑验证（mock，不调用 LLM）</option>
            <option value="pi_rpc">Pi RPC</option>
            <option value="direct">正式写作（direct，会调用真实 LLM）</option>
          </select>
        </label>
      </template>

      <template v-else-if="mode === 'book'">
        <label class="field">
          <span>章节数</span>
          <input v-model.number="chapters" type="number" min="1" />
          <small>本次写多少章（接着已有章节继续写）。</small>
        </label>
        <label class="field">
          <span>每章最少字数</span>
          <input v-model.number="minWords" type="number" min="0" />
          <small>仅 direct runner 会触发扩写；mock 章节刻意短。</small>
        </label>
        <label class="field">
          <span>运行方式</span>
          <select v-model="runner">
            <option value="mock">干跑验证（mock，不调用 LLM）</option>
            <option value="direct">正式写作（direct，会调用真实 LLM）</option>
          </select>
        </label>
      </template>

      <template v-else-if="mode === 'eval'">
        <label class="field">
          <span>运行方式</span>
          <select v-model="runner">
            <option value="mock">干跑验证（mock，不调用 LLM）</option>
            <option value="direct">正式评估（direct，会调用真实 LLM）</option>
          </select>
        </label>
        <small class="muted">评估报告写至 evaluation/final_report.md，完成后可在概览页查看。</small>
      </template>

      <label v-if="mode === 'rp'" class="field">
        <span>玩家行动</span>
        <textarea v-model="rpText" rows="3" placeholder="例如：走到窗边，观察街上的可疑人影。" />
      </label>

      <label v-if="mode === 'import'" class="field">
        <span>素材路径</span>
        <input v-model="importInput" placeholder="如 docs/source.md 或 path/to/card.json" />
        <small>酒馆卡会走专用管线；其他文本走通用管线。</small>
      </label>

      <details class="expert" @toggle="onExpertToggle">
        <summary>专家信息</summary>
        <p v-if="mode === 'draft'">底层任务：run-scene · runner={{ runner }} · scene_id={{ sceneId }}</p>
        <p v-else-if="mode === 'book'">底层任务：write-book · runner={{ runner }} · chapters={{ chapters }} · min_words={{ minWords }}</p>
        <p v-else-if="mode === 'eval'">底层任务：evaluate-book · runner={{ runner }}</p>
        <p v-else-if="mode === 'rp'">底层任务：rp-turn · 自然语言会由后端解析 intent/target。</p>
        <p v-else>底层任务：import · 专用管线缺失时降级到通用管线。</p>
      </details>

      <div class="actions">
        <BaseButton variant="primary" :loading="running" @click="start">
          {{ mode === 'draft' ? '开始创作' : mode === 'book' ? '开始写整本书' : mode === 'eval' ? '开始评估' : mode === 'rp' ? '推进一回合' : '开始导入' }}
        </BaseButton>
        <span v-if="runner === 'direct' && (mode === 'draft' || mode === 'book' || mode === 'eval')" class="warn">⚠ 会调用真实 LLM</span>
      </div>
    </section>

    <section v-if="job" class="panel job">
      <div class="job__head">
        <span>{{ mode === 'draft' ? '写作任务' : mode === 'book' ? '写整本书任务' : mode === 'eval' ? '评估任务' : mode === 'rp' ? 'RP 回合' : '导入任务' }}</span>
        <span :class="['badge', `badge--${job.status}`]">{{ job.status }}</span>
        <span class="mono muted">{{ job.job_id }}</span>
      </div>
      <pre v-if="job.error" class="job__err">{{ job.error }}</pre>
      <!-- book 模式：把 logs 里「第 N 章」行渲染成逐章进度列表 -->
      <ul v-if="mode === 'book' && chapterProgress.length" class="chapter-list">
        <li v-for="(line, i) in chapterProgress" :key="i">{{ line }}</li>
      </ul>
      <pre v-else-if="job.logs?.length" class="job__logs">{{ job.logs.join('\n') }}</pre>
      <details v-if="job.result" class="expert" open>
        <summary>任务结果</summary>
        <pre class="job__result">{{ JSON.stringify(job.result, null, 2) }}</pre>
      </details>
    </section>

    <!-- eval 模式：完成后给一个去概览看评估报告的入口 -->
    <section v-if="job?.status === 'done' && mode === 'eval' && evalDone" class="panel eval-done">
      <span>评估报告已生成。</span>
      <BaseButton size="sm" variant="ghost" @click="gotoOverview">查看评估报告 →</BaseButton>
    </section>

    <!-- NOVEL-A5：创作完成后直接预览刚写的正文，并提供「去作品页完整阅读」 -->
    <section v-if="job?.status === 'done' && (mode === 'draft' || mode === 'book')" class="panel preview-panel">
      <div class="preview-panel__head">
        <h3>📖 刚写完的内容</h3>
        <BaseButton size="sm" variant="ghost" :disabled="!preview" @click="readInNovel">在作品页完整阅读 →</BaseButton>
      </div>
      <div v-if="previewLoading" class="muted">正在读取正文…</div>
      <div v-else-if="previewError" class="muted">{{ previewError }}</div>
      <article v-else-if="preview" class="preview-panel__body">
        <div class="preview-panel__title">{{ preview.scene_id }}</div>
        <div class="preview-panel__text">{{ preview.body }}</div>
      </article>
    </section>
  </div>
</template>

<style scoped>
.creation {
  height: 100%;
  padding: var(--sp-4);
  display: flex;
  flex-direction: column;
  gap: var(--sp-4);
}
.hero,
.panel,
.mode {
  border: 1px solid var(--border);
  background: var(--surface);
  box-shadow: var(--shadow-sm);
}
.hero {
  flex: none;
  display: flex;
  align-items: center;
  gap: var(--sp-3);
  padding: var(--sp-4);
  border-radius: var(--radius-lg);
  background: linear-gradient(135deg, var(--surface), var(--surface-2));
}
.hero__icon {
  width: 48px;
  height: 48px;
  display: grid;
  place-items: center;
  border-radius: var(--radius-lg);
  background: var(--primary);
  color: var(--primary-contrast);
  font-size: 24px;
}
.hero h2 {
  margin: 0;
}
.hero p {
  margin: 2px 0 0;
  color: var(--text-muted);
}
.modes {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(220px, 1fr));
  gap: var(--sp-3);
}
.mode {
  min-height: 136px;
  padding: var(--sp-4);
  border-radius: var(--radius-lg);
  color: var(--text);
  display: flex;
  flex-direction: column;
  gap: var(--sp-2);
  text-align: left;
  cursor: pointer;
  transition: transform var(--dur-fast) var(--ease), border-color var(--dur-fast) var(--ease), box-shadow var(--dur-fast) var(--ease);
}
.mode:hover {
  transform: translateY(-2px);
  box-shadow: var(--shadow-md);
}
.mode.on {
  border-color: var(--primary);
  background: color-mix(in srgb, var(--primary) 10%, var(--surface));
}
.mode span {
  font-size: 24px;
}
.mode small,
.field small,
.expert p {
  color: var(--text-muted);
  font-size: var(--fs-sm);
}
.panel {
  border-radius: var(--radius-lg);
  padding: var(--sp-4);
  display: flex;
  flex-direction: column;
  gap: var(--sp-3);
}
.field {
  display: flex;
  flex-direction: column;
  gap: var(--sp-2);
  max-width: 620px;
}
.field span {
  font-weight: 600;
}
.field input,
.field select,
.field textarea {
  color: var(--text);
  background: var(--bg);
  border: 1px solid var(--border);
  border-radius: var(--radius-sm);
  padding: var(--sp-2);
}
.field input,
.field select {
  height: 36px;
}
.actions {
  display: flex;
  align-items: center;
  gap: var(--sp-3);
}
.warn {
  color: var(--warning);
  font-size: var(--fs-xs);
}
.expert {
  max-width: 720px;
  border-top: 1px dashed var(--border);
  padding-top: var(--sp-2);
}
.expert summary {
  cursor: pointer;
  color: var(--text-muted);
  font-size: var(--fs-sm);
}
.job__head {
  display: flex;
  align-items: center;
  gap: var(--sp-2);
}
.badge {
  font-size: var(--fs-xs);
  padding: 1px var(--sp-2);
  border-radius: var(--radius-pill);
  background: var(--surface-3);
}
.badge--pending,
.badge--running {
  color: var(--warning);
}
.badge--done {
  color: var(--success);
}
.badge--error {
  color: var(--danger);
}
.job__err,
.job__logs,
.job__result {
  margin: 0;
  padding: var(--sp-2);
  background: var(--bg);
  border-radius: var(--radius-sm);
  font-size: var(--fs-xs);
  white-space: pre-wrap;
  word-break: break-word;
  max-height: 300px;
  overflow: auto;
}
.job__err {
  color: var(--danger);
}
.chapter-list {
  margin: 0;
  padding: var(--sp-2) var(--sp-2) var(--sp-2) var(--sp-4);
  background: var(--bg);
  border-radius: var(--radius-sm);
  font-size: var(--fs-xs);
  list-style: disc;
  max-height: 300px;
  overflow: auto;
}
.chapter-list li {
  padding: 2px 0;
  color: var(--text);
  white-space: pre-wrap;
  word-break: break-word;
}
.eval-done {
  flex-direction: row;
  align-items: center;
  justify-content: space-between;
  gap: var(--sp-3);
  max-width: 720px;
}
.muted {
  color: var(--text-muted);
  font-size: var(--fs-sm);
}
.preview-panel {
  max-width: 720px;
}
.preview-panel__head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--sp-3);
}
.preview-panel__head h3 {
  margin: 0;
  font-size: var(--fs-md);
}
.preview-panel__body {
  margin-top: var(--sp-2);
  border-top: 1px solid var(--border);
  padding-top: var(--sp-3);
}
.preview-panel__title {
  text-align: center;
  font-size: var(--fs-sm);
  color: var(--text-faint);
  margin-bottom: var(--sp-2);
}
.preview-panel__text {
  font-size: var(--fs-md);
  line-height: 1.9;
  text-indent: 2em;
  white-space: pre-wrap;
  word-break: break-word;
  max-height: 360px;
  overflow: auto;
  color: var(--text);
}
</style>
