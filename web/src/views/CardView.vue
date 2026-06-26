<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { api, type CardPayload } from '@/api/client'
import { useWorkspaceStore } from '@/stores/workspace'
import { useToastStore } from '@/stores/toast'
import EmptyState from '@/components/EmptyState.vue'

const ws = useWorkspaceStore()
const toast = useToastStore()
const card = ref<CardPayload | null>(null)
const loading = ref(false)

async function load() {
  if (!ws.currentPath) return
  loading.value = true
  try {
    card.value = await api.getCard(ws.currentPath)
  } catch (e: any) {
    toast.error(e.message || '加载角色卡失败')
  } finally {
    loading.value = false
  }
}
onMounted(load)
</script>

<template>
  <div v-if="loading" class="loading">加载中…</div>
  <EmptyState v-else-if="!card" icon="🪪" title="暂无角色卡" hint="导入酒馆卡或在 data/card_ir.json 中定义" />
  <div v-else class="card-page scroll">
    <!-- card_html 由后端生成，card_ir 字段已 HTML 转义（见 app/card_front.py） -->
    <div class="card-render" v-html="card.card_html" />

    <section v-if="card.card_view.alternate_greetings?.length" class="block">
      <h4>备选开场白</h4>
      <div v-for="(g, i) in card.card_view.alternate_greetings" :key="i" class="greet">{{ g }}</div>
    </section>

    <section v-if="card.card_view.world_rules?.length" class="block">
      <h4>世界规则</h4>
      <ul>
        <li v-for="(r, i) in card.card_view.world_rules" :key="i">{{ r }}</li>
      </ul>
    </section>

    <section class="block">
      <h4>
        前端组件（正则渲染）
        <span class="muted" style="font-weight: 400; font-size: var(--fs-xs)">
          脚本 {{ card.front_script_count }} · 命中 {{ card.widgets.total_matches }}
        </span>
      </h4>
      <!-- ST 风格正则脚本模板，按酒馆语义保留（本地受信任脚本） -->
      <div v-if="card.widgets.html" class="widget-render" v-html="card.widgets.html" />
      <p v-else class="muted">该工作区 front/ 目录暂无正则前端脚本。</p>
    </section>
  </div>
</template>

<style scoped>
.card-page {
  height: 100%;
  padding: var(--sp-4);
  display: flex;
  flex-direction: column;
  gap: var(--sp-4);
}
.loading {
  padding: var(--sp-5);
  color: var(--text-muted);
}
.card-render,
.widget-render {
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: var(--radius-md);
  padding: var(--sp-4);
}
.block {
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: var(--radius-md);
  padding: var(--sp-4);
}
.block h4 {
  margin: 0 0 var(--sp-2);
}
.greet {
  padding: var(--sp-2);
  border-left: 2px solid var(--accent-rp);
  margin-bottom: var(--sp-2);
  color: var(--text-muted);
}
</style>

<style>
/* card_html 内部结构的基础样式（来自 render_card_view_html） */
.card-view h2 {
  margin: 0 0 var(--sp-2);
}
.card-view .card-field {
  margin-bottom: var(--sp-3);
}
.card-view .card-label {
  font-size: var(--fs-xs);
  color: var(--text-muted);
  text-transform: uppercase;
}
</style>
