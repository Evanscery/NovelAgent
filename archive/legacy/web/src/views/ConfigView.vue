<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import { api } from '@/api/client'
import { useToastStore } from '@/stores/toast'
import CodeEditor from '@/components/CodeEditor.vue'
import BaseButton from '@/components/BaseButton.vue'

interface SettingCard {
  name: string
  title: string
  icon: string
  desc: string
}

const SETTING_CARDS: SettingCard[] = [
  { name: 'server', title: '启动与访问', icon: '🌐', desc: '端口、自动打开浏览器、跨设备访问' },
  { name: 'models', title: '模型通道', icon: '🧠', desc: '真实写作模型与运行供应商' },
  { name: 'agents', title: '角色与技能', icon: '🧩', desc: 'Agent 分工、GM 技能与工具权限' },
  { name: 'pipeline', title: '创作流程', icon: '🧭', desc: '从规划、审查到写作归档的流程' },
  { name: 'runtime', title: '运行策略', icon: '⚡', desc: '重试、恢复、上下文预算与缓存' },
  { name: 'recall', title: '记忆召回', icon: '🗃', desc: '历史记忆索引与检索策略' },
]

const toast = useToastStore()
const configs = ref<{ name: string; exists: boolean }[]>([])
const cards = ref<SettingCard[]>([...SETTING_CARDS])
const selected = ref('server')
const content = ref('')
const original = ref('')
const loading = ref(false)
const saving = ref(false)
const dirty = ref(false)
const expert = ref(false)
const dragging = ref('')

const selectedCard = computed(() => cards.value.find((c) => c.name === selected.value))
const selectedExists = computed(() => configs.value.find((c) => c.name === selected.value)?.exists !== false)

const serverHost = computed({
  get: () => matchYamlScalar('host') || '127.0.0.1',
  set: (value: string) => setYamlScalar('host', value || '127.0.0.1'),
})
const serverPort = computed({
  get: () => matchYamlScalar('port') || '8765',
  set: (value: string) => setYamlScalar('port', value || '8765'),
})
const serverOpenBrowser = computed({
  get: () => (matchYamlScalar('open_browser') || 'false').toLowerCase() === 'true',
  set: (value: boolean) => setYamlScalar('open_browser', value ? 'true' : 'false'),
})

async function loadList() {
  try {
    const data = await api.listConfigs()
    configs.value = data.configs
    await select(configs.value.some((c) => c.name === selected.value && c.exists) ? selected.value : 'server')
  } catch (e: any) {
    toast.error(e.message || '加载设置失败')
  }
}

async function select(name: string) {
  selected.value = name
  loading.value = true
  try {
    const data = await api.readConfig(name)
    content.value = data.content
    original.value = data.content
    dirty.value = false
  } catch (e: any) {
    content.value = ''
    original.value = ''
    dirty.value = false
    toast.error(e.message || '读取设置失败')
  } finally {
    loading.value = false
  }
}

async function save() {
  saving.value = true
  try {
    await api.writeConfig(selected.value, content.value)
    original.value = content.value
    dirty.value = false
    toast.success(`已保存「${selectedCard.value?.title || selected.value}」`)
  } catch (e: any) {
    toast.error(e.message || '保存失败')
  } finally {
    saving.value = false
  }
}

function reset() {
  content.value = original.value
}

function matchYamlScalar(key: string): string {
  const match = content.value.match(new RegExp(`(^|\\n)\\s*${key}:\\s*([^\\n#]+)`, 'm'))
  return match?.[2]?.trim() || ''
}

function setYamlScalar(key: string, value: string) {
  const pattern = new RegExp(`(^|\\n)(\\s*)${key}:\\s*[^\\n#]*(.*)`, 'm')
  const replacement = (_all: string, prefix: string, indent: string, suffix: string) => `${prefix}${indent}${key}: ${value}${suffix || ''}`
  if (pattern.test(content.value)) content.value = content.value.replace(pattern, replacement)
  else content.value = `${content.value.trimEnd()}\n  ${key}: ${value}\n`
}

function onDragStart(name: string) {
  dragging.value = name
}

function onDrop(name: string) {
  const from = cards.value.findIndex((c) => c.name === dragging.value)
  const to = cards.value.findIndex((c) => c.name === name)
  if (from === -1 || to === -1 || from === to) return
  const [moved] = cards.value.splice(from, 1)
  cards.value.splice(to, 0, moved)
  dragging.value = ''
}

function onExpertToggle(e: Event) {
  expert.value = (e.target as HTMLDetailsElement).open
}

watch(content, (v) => (dirty.value = v !== original.value))
onMounted(loadList)
</script>

<template>
  <div class="settings">
    <aside class="settings__cards scroll" aria-label="设置分类">
      <button
        v-for="card in cards"
        :key="card.name"
        draggable="true"
        :class="['setting-card', { on: card.name === selected, missing: !configs.find((c) => c.name === card.name)?.exists }]"
        @click="select(card.name)"
        @dragstart="onDragStart(card.name)"
        @dragover.prevent
        @drop="onDrop(card.name)"
      >
        <span class="setting-card__icon">{{ card.icon }}</span>
        <span class="setting-card__text">
          <strong>{{ card.title }}</strong>
          <small>{{ card.desc }}</small>
        </span>
        <span class="setting-card__grab">⋮⋮</span>
      </button>
    </aside>

    <section class="settings__main">
      <div class="settings__hero">
        <div class="hero-icon">{{ selectedCard?.icon || '⚙' }}</div>
        <div>
          <h2>{{ selectedCard?.title || '设置' }}</h2>
          <p>{{ selectedCard?.desc || '调整项目运行方式' }}</p>
        </div>
        <span class="grow" />
        <span v-if="dirty" class="dirty">● 未保存</span>
        <BaseButton size="sm" variant="ghost" :disabled="!dirty" @click="reset">还原</BaseButton>
        <BaseButton size="sm" variant="primary" :loading="saving" :disabled="!dirty || !selectedExists" @click="save">保存设置</BaseButton>
      </div>

      <div v-if="loading" class="loading">加载中…</div>
      <div v-else class="settings__body scroll">
        <div v-if="selected === 'server'" class="form-grid">
          <label class="form-field">
            <span>监听地址</span>
            <input v-model="serverHost" placeholder="127.0.0.1" />
            <small>默认只允许本机访问；跨设备访问时才改为 0.0.0.0。</small>
          </label>
          <label class="form-field">
            <span>前端端口</span>
            <input v-model="serverPort" inputmode="numeric" placeholder="8765" />
            <small>双击启动后浏览器打开的端口。</small>
          </label>
          <label class="toggle-card">
            <input v-model="serverOpenBrowser" type="checkbox" />
            <span>
              <strong>启动后自动打开浏览器</strong>
              <small>推荐开启，双击 start.bat 后直接进入工作台。</small>
            </span>
          </label>
        </div>

        <div v-else class="friendly-panel">
          <h3>{{ selectedCard?.title }}</h3>
          <p>
            这里先展示面向创作者的说明。完整图形化表单会按真实使用频率逐步补齐；
            目前如需精细调整，可展开下方专家模式。
          </p>
          <ul>
            <li v-if="selected === 'models'">正式写作请确认模型供应商与密钥已配置，mock 仅用于流程验证。</li>
            <li v-if="selected === 'agents'">GM 可使用 dice_roll 等内置技能；后续 profile 权限会在这里图形化配置。</li>
            <li v-if="selected === 'pipeline'">创作流程会从设定、规划、审查、写作到归档逐步推进。</li>
            <li v-if="selected === 'runtime'">运行策略控制重试、恢复、上下文预算与 prompt 快照。</li>
            <li v-if="selected === 'recall'">记忆召回会索引 summaries、index 与 fulltext，辅助保持连续性。</li>
          </ul>
        </div>

        <details v-if="selectedExists" :open="expert" class="expert" @toggle="onExpertToggle">
          <summary>专家模式：查看 / 编辑底层配置</summary>
          <p class="expert__hint">仅在你明确知道这些字段含义时编辑。普通创作者无需接触文件名或 YAML。</p>
          <CodeEditor v-model="content" language="yaml" @save="save" />
        </details>
      </div>
    </section>
  </div>
</template>

<style scoped>
.settings {
  display: flex;
  height: 100%;
  min-height: 0;
  background: var(--bg);
}
.settings__cards {
  width: 300px;
  flex: none;
  border-right: 1px solid var(--border);
  padding: var(--sp-3);
  display: flex;
  flex-direction: column;
  gap: var(--sp-2);
  background: var(--surface);
}
.setting-card {
  display: grid;
  grid-template-columns: 34px 1fr auto;
  align-items: center;
  gap: var(--sp-2);
  width: 100%;
  padding: var(--sp-3);
  text-align: left;
  border: 1px solid transparent;
  border-radius: var(--radius-md);
  background: transparent;
  color: var(--text);
  cursor: grab;
  transition: background var(--dur-fast) var(--ease), border-color var(--dur-fast) var(--ease), transform var(--dur-fast) var(--ease);
}
.setting-card:hover {
  background: var(--surface-2);
  transform: translateY(-1px);
}
.setting-card.on {
  background: var(--surface-3);
  border-color: var(--primary);
}
.setting-card.missing {
  opacity: 0.55;
}
.setting-card__icon {
  width: 34px;
  height: 34px;
  border-radius: var(--radius-md);
  display: grid;
  place-items: center;
  background: var(--bg);
}
.setting-card__text {
  display: flex;
  flex-direction: column;
  gap: 2px;
}
.setting-card__text small,
.setting-card__grab {
  color: var(--text-faint);
  font-size: var(--fs-xs);
}
.settings__main {
  flex: 1 1 auto;
  min-width: 0;
  display: flex;
  flex-direction: column;
}
.settings__hero {
  flex: none;
  display: flex;
  align-items: center;
  gap: var(--sp-3);
  padding: var(--sp-4);
  border-bottom: 1px solid var(--border);
  background: linear-gradient(135deg, var(--surface), var(--surface-2));
}
.hero-icon {
  width: 48px;
  height: 48px;
  display: grid;
  place-items: center;
  border-radius: var(--radius-lg);
  background: var(--bg);
  font-size: 24px;
}
.settings__hero h2 {
  margin: 0;
  font-size: var(--fs-xl);
}
.settings__hero p {
  margin: 2px 0 0;
  color: var(--text-muted);
}
.dirty {
  color: var(--warning);
  font-size: var(--fs-xs);
}
.loading {
  padding: var(--sp-5);
  color: var(--text-muted);
}
.settings__body {
  flex: 1 1 auto;
  min-height: 0;
  padding: var(--sp-4);
}
.form-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(260px, 1fr));
  gap: var(--sp-3);
}
.form-field,
.toggle-card,
.friendly-panel {
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: var(--radius-md);
  padding: var(--sp-4);
}
.form-field {
  display: flex;
  flex-direction: column;
  gap: var(--sp-2);
}
.form-field span,
.toggle-card strong {
  font-weight: 600;
}
.form-field small,
.toggle-card small,
.friendly-panel p,
.friendly-panel li,
.expert__hint {
  color: var(--text-muted);
  font-size: var(--fs-sm);
}
.form-field input {
  height: 36px;
  padding: 0 var(--sp-2);
  color: var(--text);
  background: var(--bg);
  border: 1px solid var(--border);
  border-radius: var(--radius-sm);
}
.toggle-card {
  display: flex;
  align-items: flex-start;
  gap: var(--sp-3);
}
.toggle-card input {
  margin-top: 4px;
}
.toggle-card span {
  display: flex;
  flex-direction: column;
  gap: 4px;
}
.friendly-panel {
  max-width: 720px;
}
.friendly-panel h3 {
  margin-top: 0;
}
.expert {
  margin-top: var(--sp-4);
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: var(--radius-md);
  overflow: hidden;
}
.expert summary {
  padding: var(--sp-3) var(--sp-4);
  cursor: pointer;
  user-select: none;
}
.expert__hint {
  margin: 0;
  padding: 0 var(--sp-4) var(--sp-3);
}
.expert :deep(.editor) {
  border-top: 1px solid var(--border);
}
</style>
