<script setup lang="ts">
import { computed, nextTick, onMounted, ref } from 'vue'
import { api } from '@/api/client'
import { useWorkspaceStore } from '@/stores/workspace'
import { useToastStore } from '@/stores/toast'

interface Bubble {
  role: 'player' | 'gm' | 'character' | 'system' | 'dice'
  who?: string
  text: string
  // 后端解析出的显性字段（仅 player 气泡），用于轻量展示，不需用户手填。
  meta?: { intent?: string; target?: string }
}

const ws = useWorkspaceStore()
const toast = useToastStore()
const input = ref('')
const sending = ref(false)
const bubbles = ref<Bubble[]>([])
const streamEl = ref<HTMLElement | null>(null)
// RP-A4：中间态（解析出的 intent/target 标签）默认对玩家隐藏，专家模式才显示。
const debug = ref(false)
// RP-A7：GM 要求玩家掷骰时的 pending 状态（跑团 player 源）。
const pendingRoll = ref<{ notation: string; scene_id: string; intent: string } | null>(null)

const INTENT_LABEL: Record<string, string> = {
  dialogue: '对话',
  attack: '攻击',
  move: '移动',
  inspect: '查看',
  act: '行动',
  unknown: '行动',
}

const canSend = computed(() => !!input.value.trim() && !sending.value)

async function scrollDown() {
  await nextTick()
  if (streamEl.value) streamEl.value.scrollTop = streamEl.value.scrollHeight
}

function ingestResponse(payload: any, playerBubble: Bubble) {
  // 后端从自然语言里解析出的显性字段，回填到玩家气泡的 meta（不要求用户输入）。
  const parsed = payload.parsed_input || {}
  playerBubble.meta = {
    intent: parsed.intent,
    target: parsed.target,
  }
  const resp = payload.response || {}
  if (resp.gm_narration) bubbles.value.push({ role: 'gm', who: 'GM', text: resp.gm_narration })
  for (const r of resp.character_reactions || []) {
    if (r.role === 'narrator') continue // 旁白已由 gm_narration 呈现，避免重复
    bubbles.value.push({
      role: 'character',
      who: r.speaker || r.name || r.character || '角色',
      text: r.text || r.reaction || JSON.stringify(r),
    })
  }
  for (const s of resp.skill_invocations || []) {
    bubbles.value.push({ role: 'dice', who: s.skill === 'dice_roll' ? '🎲 掷骰' : s.skill, text: s.detail || JSON.stringify(s.output) })
  }
  // RP-A7：GM 要求玩家掷骰 → 显示掷骰按钮，阻塞等待玩家点击。
  const pending = resp.pending
  if (pending && pending.kind === 'player_dice' && pending.status === 'awaiting_roll') {
    pendingRoll.value = { notation: pending.notation, scene_id: pending.scene_id, intent: pending.intent }
  } else {
    pendingRoll.value = null
  }
}

async function send() {
  const text = input.value.trim()
  if (!text) return
  if (!ws.currentPath) {
    toast.warning('请先选择项目')
    return
  }
  const playerBubble: Bubble = { role: 'player', who: '你', text }
  bubbles.value.push(playerBubble)
  input.value = ''
  sending.value = true
  await scrollDown()
  try {
    const payload = await api.rpTurn(ws.currentPath, text)
    ingestResponse(payload, playerBubble)
  } catch (e: any) {
    bubbles.value.push({ role: 'system', text: `错误：${e.message || '提交失败'}` })
    toast.error(e.message || '提交失败')
  } finally {
    sending.value = false
    await scrollDown()
  }
}

function onKey(e: KeyboardEvent) {
  if ((e.ctrlKey || e.metaKey) && e.key === 'Enter') {
    e.preventDefault()
    send()
  }
}

// RP-A7：玩家点击掷骰按钮，本地掷骰后把结果回传给 GM 判定。
async function rollDice() {
  const p = pendingRoll.value
  if (!p || !ws.currentPath) return
  // 解析 notation（形如 1d20 / 3d6+2）并在客户端掷骰——玩家的主动权在前端。
  const m = /^(\d*)d(\d+)(?:\s*([+-])\s*(\d+))?$/.exec(p.notation)
  let total = 0
  if (m) {
    const count = m[1] ? parseInt(m[1], 10) : 1
    const sides = parseInt(m[2], 10)
    const mod = m[3] ? parseInt((m[3] + m[4]), 10) : 0
    let sum = 0
    for (let i = 0; i < count; i++) sum += Math.floor(Math.random() * sides) + 1
    total = sum + mod
  } else {
    total = Math.floor(Math.random() * 20) + 1
  }
  bubbles.value.push({ role: 'dice', who: '🎲 你掷骰', text: `${p.notation} => ${total}` })
  pendingRoll.value = null
  sending.value = true
  await scrollDown()
  try {
    const payload = await api.rpTurn(ws.currentPath, '', { scene_id: p.scene_id, notation: p.notation, total })
    ingestResponse(payload, { role: 'player', who: '你', text: '' })
  } catch (e: any) {
    bubbles.value.push({ role: 'system', text: `判定失败：${e.message || '提交失败'}` })
    toast.error(e.message || '判定失败')
  } finally {
    sending.value = false
    await scrollDown()
  }
}
onMounted(() => {
  bubbles.value.push({
    role: 'system',
    text: '用自然语言描述你的行动或对话，世界会随之推进。',
  })
})
</script>

<template>
  <div class="rp">
    <div ref="streamEl" class="rp__stream scroll">
      <div v-for="(b, i) in bubbles" :key="i" :class="['turn', `turn--${b.role}`]">
        <!-- 系统提示居中、无气泡 -->
        <div v-if="b.role === 'system'" class="sys">{{ b.text }}</div>

        <!-- 掷骰：居中徽章 -->
        <div v-else-if="b.role === 'dice'" class="dice">
          <span class="dice__tag">{{ b.who }}</span>
          <span class="dice__val">{{ b.text }}</span>
        </div>

        <!-- 玩家 / GM / 角色：头像 + 气泡 -->
        <template v-else>
          <div class="avatar" :class="`avatar--${b.role}`">
            {{ b.role === 'player' ? '你' : b.role === 'gm' ? 'GM' : (b.who || '角')[0] }}
          </div>
          <div class="bubble-wrap">
            <div class="bubble-head">
              <span class="bubble-who">{{ b.who }}</span>
              <template v-if="debug">
                <span v-if="b.meta?.intent" class="chip">{{ INTENT_LABEL[b.meta.intent] || b.meta.intent }}</span>
                <span v-if="b.meta?.target" class="chip chip--target">→ {{ b.meta.target }}</span>
              </template>
            </div>
            <div :class="['bubble', `bubble--${b.role}`]">{{ b.text }}</div>
          </div>
        </template>
      </div>
    </div>

    <!-- RP-A7：GM 要求玩家掷骰时显示掷骰按钮 -->
    <div v-if="pendingRoll" class="rp__pending">
      <span class="rp__pending-hint">GM 等你掷骰：</span>
      <button class="rp__roll-btn" :disabled="sending" @click="rollDice">
        <span class="rp__roll-die">🎲</span>
        掷 {{ pendingRoll.notation }}
      </button>
    </div>

    <div class="rp__input">
      <textarea
        v-model="input"
        class="rp__textarea"
        rows="2"
        placeholder="描述你的行动或要说的话，例如：走到吧台前，问老板镇上最近的怪事。"
        @keydown="onKey"
      />
      <button class="send" :disabled="!canSend" @click="send">
        <span v-if="sending" class="send__spin" />
        <span v-else>发送</span>
      </button>
    </div>
    <div class="rp__hint">
      <span>Ctrl / Cmd + Enter 发送 · 直接写自然语言即可，无需任何命令</span>
      <button class="debug-toggle" :class="{ on: debug }" @click="debug = !debug" title="显示解析出的 intent / target 等中间态（专家模式）">
        {{ debug ? '◉ 专家' : '○ 专家' }}
      </button>
    </div>
  </div>
</template>

<style scoped>
.rp {
  display: flex;
  flex-direction: column;
  height: 100%;
  min-height: 0;
  background:
    radial-gradient(1200px 400px at 50% -10%, color-mix(in srgb, var(--accent-rp) 12%, transparent), transparent 70%),
    var(--bg);
}
.rp__stream {
  flex: 1 1 auto;
  min-height: 0;
  padding: var(--sp-4) var(--sp-5);
  display: flex;
  flex-direction: column;
  gap: var(--sp-4);
}

/* 一行 = 一个回合单元 */
.turn {
  display: flex;
  gap: var(--sp-3);
  align-items: flex-start;
  max-width: 860px;
  width: 100%;
}
.turn--player {
  flex-direction: row-reverse;
  align-self: flex-end;
}
.turn--gm,
.turn--character {
  align-self: flex-start;
}

/* 头像 */
.avatar {
  flex: none;
  width: 38px;
  height: 38px;
  border-radius: var(--radius-pill);
  display: grid;
  place-items: center;
  font-size: var(--fs-sm);
  font-weight: 700;
  color: var(--primary-contrast);
  box-shadow: var(--shadow-sm);
  user-select: none;
}
.avatar--player {
  background: linear-gradient(135deg, var(--primary), var(--primary-hover));
}
.avatar--gm {
  background: linear-gradient(135deg, #5a6b8c, var(--border-strong));
  color: var(--text);
}
.avatar--character {
  background: linear-gradient(135deg, var(--accent-rp), color-mix(in srgb, var(--accent-rp) 60%, #000));
}

.bubble-wrap {
  display: flex;
  flex-direction: column;
  gap: 4px;
  min-width: 0;
  max-width: 78%;
}
.turn--player .bubble-wrap {
  align-items: flex-end;
}
.bubble-head {
  display: flex;
  align-items: center;
  gap: var(--sp-1);
  font-size: var(--fs-xs);
}
.bubble-who {
  color: var(--text-muted);
  font-weight: 600;
}
.chip {
  font-size: 11px;
  line-height: 1;
  padding: 3px 7px;
  border-radius: var(--radius-pill);
  background: var(--surface-3);
  color: var(--text-muted);
  border: 1px solid var(--border);
}
.chip--target {
  color: var(--accent-rp);
  border-color: color-mix(in srgb, var(--accent-rp) 40%, transparent);
}

/* 气泡 */
.bubble {
  padding: var(--sp-3) var(--sp-4);
  font-size: var(--fs-md);
  line-height: var(--lh-normal);
  white-space: pre-wrap;
  word-break: break-word;
  box-shadow: var(--shadow-sm);
}
.bubble--player {
  background: linear-gradient(135deg, var(--primary), var(--primary-hover));
  color: var(--primary-contrast);
  border-radius: var(--radius-lg) var(--radius-lg) var(--radius-sm) var(--radius-lg);
}
.bubble--gm {
  background: var(--surface-2);
  border: 1px solid var(--border);
  color: var(--text);
  border-radius: var(--radius-lg) var(--radius-lg) var(--radius-lg) var(--radius-sm);
  font-style: italic;
}
.bubble--character {
  background: var(--surface);
  border: 1px solid color-mix(in srgb, var(--accent-rp) 35%, var(--border));
  border-radius: var(--radius-lg) var(--radius-lg) var(--radius-lg) var(--radius-sm);
}

/* 系统行 */
.sys {
  align-self: center;
  margin: 0 auto;
  color: var(--text-faint);
  font-size: var(--fs-xs);
  text-align: center;
  padding: 2px var(--sp-3);
}
.turn:has(.sys) {
  justify-content: center;
}

/* 掷骰徽章 */
.dice {
  align-self: center;
  margin: 0 auto;
  display: inline-flex;
  align-items: center;
  gap: var(--sp-2);
  padding: 6px var(--sp-3);
  border-radius: var(--radius-pill);
  background: color-mix(in srgb, var(--warning) 14%, var(--surface-3));
  border: 1px solid color-mix(in srgb, var(--warning) 45%, transparent);
  box-shadow: var(--shadow-sm);
}
.turn:has(.dice) {
  justify-content: center;
}
.dice__tag {
  font-size: var(--fs-xs);
  font-weight: 700;
  color: var(--warning);
}
.dice__val {
  font-family: var(--font-mono);
  font-size: var(--fs-sm);
  color: var(--text);
}

/* 输入区 */
.rp__pending {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: var(--sp-3);
  padding: var(--sp-2) var(--sp-5);
  animation: pending-in var(--dur-mid) var(--ease);
}
.rp__pending-hint {
  font-size: var(--fs-sm);
  color: var(--text-muted);
}
.rp__roll-btn {
  display: inline-flex;
  align-items: center;
  gap: var(--sp-2);
  padding: var(--sp-2) var(--sp-4);
  border: 1px solid var(--warning);
  background: color-mix(in srgb, var(--warning) 14%, var(--surface-3));
  color: var(--warning);
  font-weight: 700;
  font-size: var(--fs-md);
  border-radius: var(--radius-pill);
  cursor: pointer;
  transition: transform var(--dur-fast) var(--ease), background var(--dur-fast) var(--ease);
}
.rp__roll-btn:hover:not(:disabled) {
  transform: translateY(-1px) scale(1.02);
  background: color-mix(in srgb, var(--warning) 22%, var(--surface-3));
}
.rp__roll-btn:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}
.rp__roll-die {
  font-size: 18px;
}
@keyframes pending-in {
  from { opacity: 0; transform: translateY(4px); }
  to { opacity: 1; transform: translateY(0); }
}

/* 输入区 */
.rp__input {
  display: flex;
  gap: var(--sp-2);
  padding: var(--sp-3) var(--sp-5) 0;
  align-items: flex-end;
}
.rp__textarea {
  flex: 1 1 auto;
  min-height: 52px;
  max-height: 180px;
  resize: vertical;
  padding: var(--sp-3);
  background: var(--surface);
  color: var(--text);
  border: 1px solid var(--border-strong);
  border-radius: var(--radius-md);
  font-size: var(--fs-md);
  line-height: var(--lh-normal);
  transition: border-color var(--dur-fast) var(--ease);
}
.rp__textarea:focus {
  outline: none;
  border-color: var(--primary);
}
.send {
  flex: none;
  height: 52px;
  min-width: 84px;
  padding: 0 var(--sp-4);
  border: none;
  border-radius: var(--radius-md);
  background: linear-gradient(135deg, var(--primary), var(--primary-hover));
  color: var(--primary-contrast);
  font-size: var(--fs-md);
  font-weight: 600;
  cursor: pointer;
  display: grid;
  place-items: center;
  transition: filter var(--dur-fast) var(--ease), opacity var(--dur-fast) var(--ease);
}
.send:hover:not(:disabled) {
  filter: brightness(1.08);
}
.send:disabled {
  opacity: 0.45;
  cursor: not-allowed;
}
.send__spin {
  width: 16px;
  height: 16px;
  border: 2px solid color-mix(in srgb, var(--primary-contrast) 50%, transparent);
  border-top-color: var(--primary-contrast);
  border-radius: 50%;
  animation: spin 0.7s linear infinite;
}
@keyframes spin {
  to {
    transform: rotate(360deg);
  }
}
.rp__hint {
  padding: var(--sp-1) var(--sp-5) var(--sp-3);
  font-size: var(--fs-xs);
  color: var(--text-faint);
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--sp-3);
}
.debug-toggle {
  background: none;
  border: 1px solid var(--border);
  color: var(--text-faint);
  font-size: var(--fs-xs);
  padding: 2px var(--sp-2);
  border-radius: var(--radius-pill);
  cursor: pointer;
  transition: color var(--dur-fast) var(--ease), border-color var(--dur-fast) var(--ease);
}
.debug-toggle.on {
  color: var(--warning);
  border-color: color-mix(in srgb, var(--warning) 50%, transparent);
}
.debug-toggle:hover {
  color: var(--text-muted);
}
</style>
