<script setup lang="ts">
import { computed, onUnmounted, ref } from 'vue'
import { useWorkspaceStore, type TabKind } from '@/stores/workspace'
import { useUiStore } from '@/stores/ui'

const ws = useWorkspaceStore()
const ui = useUiStore()

const kind = computed<TabKind | undefined>(() => ws.activeTab?.kind)
const ctx = computed(() => ws.activeTab?.ctx)

// 各视图的 Inspector 标题。
const TITLE: Record<TabKind, string> = {
  overview: '进度概览',
  novel: '章节信息',
  card: '角色卡 IR',
  rp: '状态 / 掷骰',
  prompt: '模块挂载顺序',
  config: '配置字段',
  files: '文件信息',
  run: '运行日志',
}

const title = computed(() => (kind.value ? TITLE[kind.value] : 'Inspector'))

// —— 拖拽改宽（左边缘手柄）。三栏内联态生效；抽屉态宽度固定。 ——
const dragging = ref(false)

function onHandleDown(e: MouseEvent) {
  e.preventDefault()
  dragging.value = true
  document.addEventListener('mousemove', onMove)
  document.addEventListener('mouseup', onUp)
}
function onMove(e: MouseEvent) {
  // Inspector 贴右；新宽 = 视口右边缘 - 鼠标 x。
  const w = window.innerWidth - e.clientX
  ui.setInspectorWidth(w)
}
function onUp() {
  dragging.value = false
  document.removeEventListener('mousemove', onMove)
  document.removeEventListener('mouseup', onUp)
}
onUnmounted(() => {
  document.removeEventListener('mousemove', onMove)
  document.removeEventListener('mouseup', onUp)
})

const panelStyle = computed(() => ({
  width: `${ui.inspectorWidthClamped}px`,
}))
</script>

<template>
  <aside class="inspector" :style="panelStyle">
    <div class="inspector__handle" :class="{ active: dragging }" @mousedown="onHandleDown" aria-hidden="true" />
    <header class="inspector__head">
      <span class="inspector__title">{{ title }}</span>
      <button class="inspector__x" aria-label="收起 Inspector" @click="ui.closeInspector()">›</button>
    </header>
    <div class="inspector__body scroll">
      <template v-if="!kind">
        <p class="hint">未打开标签。从左侧导航或 TabBar ＋ 打开视图后，此处显示对应上下文。</p>
      </template>
      <template v-else>
        <!-- 概览：进度概览 -->
        <section v-if="kind === 'overview'" class="ctx">
          <div class="ctx-row"><span class="k">当前项目</span><span class="v">{{ ws.currentName || '—' }}</span></div>
          <div class="ctx-row"><span class="k">打开标签</span><span class="v">{{ ws.tabs.length }}</span></div>
          <div class="ctx-row"><span class="k">未保存</span><span class="v">{{ ws.hasDirty ? '是' : '否' }}</span></div>
          <p class="hint">进度四步（创建 / 设定 / 写作 / 评估）详见概览主页。</p>
        </section>

        <!-- 作品：章节信息 -->
        <section v-else-if="kind === 'novel'" class="ctx">
          <p class="hint">成稿章节存于 <code>novels/chapter_*.txt</code>。在作品页选择章节阅读；Inspector 不复述正文，仅提示索引位置。</p>
        </section>

        <!-- 角色卡：card_ir 摘要 -->
        <section v-else-if="kind === 'card'" class="ctx">
          <p class="hint">角色卡 IR（<code>data/card_ir.json</code>）在角色卡页渲染。此处仅提示：ST 正则 widget 由 <code>front/</code> 脚本驱动。</p>
        </section>

        <!-- RP：状态 / 获骰 -->
        <section v-else-if="kind === 'rp'" class="ctx">
          <p class="hint">RP 状态与获骰记录由 RP 对话页维护。canonical state 存于 <code>state/state.md</code>，玩家可见态存于 <code>state/player_visible/</code>。</p>
          <p class="hint">获骰徽章挂在对应气泡；玩家主动骰通过页内骰按钮触发。</p>
        </section>

        <!-- Prompt：模块挂载顺序 -->
        <section v-else-if="kind === 'prompt'" class="ctx">
          <p class="hint"><b>模块挂载顺序</b>（prompt 组装次序）：</p>
          <ol class="mount-order">
            <li>Agent 任务 prompt</li>
            <li>preset 全局模块</li>
            <li>preset 文风模块</li>
            <li>Agent 专属模块</li>
            <li>agents.yaml 额外挂载</li>
            <li>输出 artifact 约束</li>
            <li>输入文件上下文</li>
            <li>本轮步骤元数据</li>
          </ol>
          <p class="hint" v-if="ctx?.rel">当前文件：<code>{{ ctx.rel }}</code></p>
        </section>

        <!-- 配置：yaml 字段提示 -->
        <section v-else-if="kind === 'config'" class="ctx">
          <p class="hint">配置为 YAML 白名单编辑。常见字段：<code>modules</code>、<code>preset</code>、<code>profile</code>、<code>runner</code>。保存即写回文件。</p>
          <p class="hint" v-if="ctx?.name">当前配置：<code>{{ ctx.name }}</code></p>
        </section>

        <!-- 文件：选中文件信息 -->
        <section v-else-if="kind === 'files'" class="ctx">
          <div class="ctx-row" v-if="ctx?.rel"><span class="k">选中文件</span><span class="v mono">{{ ctx.rel }}</span></div>
          <p class="hint" v-else>在素材库选择一个文件后，此处显示其相对路径与可编辑性。</p>
          <p class="hint">仅 <code>prompts/ modules/ presets/ config/</code> 等可编辑目录支持写入与重命名。</p>
        </section>

        <!-- 运行：job 日志镜像 -->
        <section v-else-if="kind === 'run'" class="ctx">
          <p class="hint">运行 job 日志在创作页实时轮询展示。Inspector 仅提示：job 状态 / 日志 / 结果由 <code>/api/run</code> 返回，无需在此复述。</p>
        </section>
      </template>
    </div>
  </aside>
</template>

<style scoped>
.inspector {
  position: relative;
  flex: none;
  background: var(--surface);
  border-left: 1px solid var(--border);
  display: flex;
  flex-direction: column;
  min-width: 0;
}
.inspector__handle {
  position: absolute;
  left: -3px;
  top: 0;
  bottom: 0;
  width: 6px;
  cursor: col-resize;
  z-index: 1;
}
.inspector__handle:hover,
.inspector__handle.active {
  background: var(--primary);
  opacity: 0.35;
}
.inspector__head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: var(--sp-3) var(--sp-3);
  border-bottom: 1px solid var(--border);
  flex: none;
}
.inspector__title {
  font-size: var(--fs-sm);
  font-weight: 600;
  color: var(--text-muted);
  letter-spacing: 0.02em;
}
.inspector__x {
  width: 24px;
  height: 24px;
  background: none;
  border: 1px solid transparent;
  border-radius: var(--radius-sm);
  color: var(--text-muted);
  cursor: pointer;
  font-size: 16px;
  line-height: 1;
}
.inspector__x:hover {
  background: var(--surface-2);
  color: var(--text);
}
.inspector__body {
  flex: 1 1 auto;
  padding: var(--sp-3);
  min-height: 0;
}
.hint {
  margin: 0 0 var(--sp-2);
  font-size: var(--fs-sm);
  color: var(--text-muted);
  line-height: var(--lh-normal);
}
.ctx {
  display: flex;
  flex-direction: column;
  gap: var(--sp-2);
}
.ctx-row {
  display: flex;
  justify-content: space-between;
  gap: var(--sp-2);
  font-size: var(--fs-sm);
}
.ctx-row .k {
  color: var(--text-faint);
}
.ctx-row .v {
  color: var(--text);
  text-align: right;
  word-break: break-all;
}
.mount-order {
  margin: var(--sp-1) 0 var(--sp-2);
  padding-left: var(--sp-4);
  font-size: var(--fs-xs);
  color: var(--text-muted);
  line-height: var(--lh-normal);
}
.mount-order li {
  margin-bottom: 2px;
}
code {
  font-family: var(--font-mono);
  font-size: var(--fs-xs);
  padding: 1px var(--sp-1);
  background: var(--surface-2);
  border-radius: var(--radius-sm);
}
</style>
