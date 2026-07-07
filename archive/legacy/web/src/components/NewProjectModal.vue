<script setup lang="ts">
import { onUnmounted, ref } from 'vue'
import { api, type RunJob } from '@/api/client'
import { useWorkspaceStore } from '@/stores/workspace'
import { useToastStore } from '@/stores/toast'
import BaseModal from './BaseModal.vue'
import BaseButton from './BaseButton.vue'

const emit = defineEmits<{ (e: 'close'): void }>()
const ws = useWorkspaceStore()
const toast = useToastStore()

const name = ref('')
const theme = ref('')
// runner 为空字符串表示「仅创建空项目」（快速路径）；否则触发 bootstrap 后台任务。
const runner = ref<'' | 'mock' | 'pi_rpc' | 'direct'>('')
const creating = ref(false)
const error = ref('')

// Bootstrap 任务轮询状态。fast path（runner=''）不使用。
const bootstrapJob = ref<RunJob | null>(null)
const bootstrapping = ref(false)
let timer: number | null = null

function stopPoll() {
  if (timer !== null) {
    clearInterval(timer)
    timer = null
  }
}

function resetJobState() {
  stopPoll()
  bootstrapJob.value = null
  bootstrapping.value = false
}

async function poll(jobId: string, storyPath: string, storyName: string) {
  stopPoll()
  timer = window.setInterval(async () => {
    try {
      const j = await api.getJob(jobId)
      bootstrapJob.value = j
      if (j.status === 'done' || j.status === 'error') {
        stopPoll()
        bootstrapping.value = false
        if (j.status === 'done') {
          toast.success(`已生成设定：${storyName}`)
          await ws.loadStories()
          ws.openStory(storyPath, storyName)
          emit('close')
        } else {
          // bootstrap 失败：保持项目已创建，但设定未生成 → 内联报错，不关闭弹窗。
          error.value = j.error || '设定生成失败'
        }
      }
    } catch (e: any) {
      stopPoll()
      bootstrapping.value = false
      error.value = e.message || '轮询失败'
    }
  }, 700)
}

async function create() {
  error.value = ''
  if (!name.value.trim()) {
    error.value = '请填写项目名称'
    return
  }
  creating.value = true
  try {
    const story = await api.createWorkspace(
      name.value.trim(),
      theme.value.trim(),
      runner.value || undefined,
    )
    if (story.job_id) {
      // 进入 bootstrap 轮询：项目已脚手架，设定生成在后台跑。
      bootstrapping.value = true
      bootstrapJob.value = null
      poll(story.job_id, story.path, story.name)
    } else {
      // fast path：未传 runner，项目已就绪，直接打开。
      toast.success(`已创建项目 ${story.name}`)
      await ws.loadStories()
      ws.openStory(story.path, story.name)
      emit('close')
    }
  } catch (e: any) {
    error.value = e.message || '创建失败'
  } finally {
    creating.value = false
  }
}

// 关闭/卸载必须清掉轮询，避免 orphan timer。
function requestClose() {
  resetJobState()
  emit('close')
}

onUnmounted(stopPoll)
</script>

<template>
  <BaseModal title="新建项目" width="460px" @close="requestClose">
    <div class="form">
      <label class="field">
        <span class="field__l">项目名称</span>
        <input v-model="name" class="field__c" placeholder="字母/数字/下划线/连字符/中文，1-64 字" autofocus />
      </label>
      <label class="field">
        <span class="field__l">主题 / 设定种子</span>
        <textarea v-model="theme" class="field__c" rows="3" placeholder="一句话描述世界观或主题（写入 PROJECT.md / premise）" />
      </label>
      <label class="field">
        <span class="field__l">运行方式</span>
        <select v-model="runner" class="field__c">
          <option value="">仅创建空项目（不生成设定）</option>
          <option value="mock">生成设定（mock 干跑，不调用 LLM）</option>
          <option value="pi_rpc">生成设定（Pi RPC）</option>
          <option value="direct">生成设定（direct，⚠ 会调用真实 LLM）</option>
        </select>
        <small v-if="runner === 'direct'" class="warn">⚠ direct 会调用真实 LLM，请确认已配置模型与密钥。</small>
      </label>

      <!-- Bootstrap 轮询进度：状态徽章 + 日志预览 -->
      <div v-if="bootstrapping || bootstrapJob" class="progress">
        <div class="progress__head">
          <span>正在生成设定…</span>
          <span v-if="bootstrapJob" :class="['badge', `badge--${bootstrapJob.status}`]">{{ bootstrapJob.status }}</span>
        </div>
        <pre v-if="bootstrapJob?.error" class="progress__err">{{ bootstrapJob.error }}</pre>
        <pre v-if="bootstrapJob?.logs?.length" class="progress__logs">{{ bootstrapJob.logs.slice(-8).join('\n') }}</pre>
      </div>

      <p v-if="error" class="err">{{ error }}</p>
      <p v-if="!bootstrapping" class="muted" style="font-size: var(--fs-xs)">
        {{ runner ? '脚手架完成后立即在后台启动 init-story 设定生成任务。' : '将复用工作区模板创建自包含项目（lore / state / memory / prompts / presets …）。' }}
      </p>
    </div>
    <template #footer>
      <BaseButton variant="ghost" :disabled="bootstrapping" @click="requestClose">取消</BaseButton>
      <BaseButton variant="primary" :loading="creating || bootstrapping" @click="create">
        {{ runner ? '创建并生成设定' : '创建并打开' }}
      </BaseButton>
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
.warn {
  color: var(--warning);
  font-size: var(--fs-xs);
}
.muted {
  color: var(--text-muted);
  font-size: var(--fs-sm);
}
.progress {
  margin-top: var(--sp-1);
  padding: var(--sp-2);
  background: var(--bg);
  border: 1px solid var(--border);
  border-radius: var(--radius-sm);
  display: flex;
  flex-direction: column;
  gap: var(--sp-1);
}
.progress__head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--sp-2);
  font-size: var(--fs-sm);
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
.progress__err,
.progress__logs {
  margin: 0;
  padding: var(--sp-1);
  background: var(--surface-2);
  border-radius: var(--radius-sm);
  font-size: var(--fs-xs);
  white-space: pre-wrap;
  word-break: break-word;
  max-height: 160px;
  overflow: auto;
}
.progress__err {
  color: var(--danger);
}
</style>
