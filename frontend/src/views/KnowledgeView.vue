<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { MdPreview } from 'md-editor-v3'
import { api, type KnowledgeDocument } from '../api/client'
import AppShell from '../components/AppShell.vue'
import KnowledgeEditor from '../components/KnowledgeEditor.vue'

type SearchItem = { chunk_id: string; source: string; content: string; score: number }
const documents = ref<KnowledgeDocument[]>([])
const selected = ref<KnowledgeDocument | null>(null)
const loading = ref(false)
const message = ref('')
const query = ref('')
const results = ref<SearchItem[]>([])
const documentQuery = ref('')
const indexed = computed(() => documents.value.filter((item) => item.is_indexed).length)
const filteredDocuments = computed(() => {
  const value = documentQuery.value.trim().toLowerCase()
  return value
    ? documents.value.filter((item) => `${item.title} ${item.source}`.toLowerCase().includes(value))
    : documents.value
})

async function load() {
  documents.value = await api<KnowledgeDocument[]>('/api/v1/knowledge/documents')
}

async function select(item: KnowledgeDocument) {
  selected.value = await api<KnowledgeDocument>(`/api/v1/knowledge/documents/${item.id}`)
}

function createNew() {
  selected.value = {
    id: '', title: '新知识文档', source: 'new-policy.md', content: '# 新知识文档\n\n',
    content_hash: '', indexed_hash: null, indexed_at: null, is_indexed: false,
    created_at: '', updated_at: '',
  }
}

async function save() {
  if (!selected.value) return
  const body = JSON.stringify({
    title: selected.value.title, source: selected.value.source, content: selected.value.content,
  })
  selected.value = selected.value.id
    ? await api(`/api/v1/knowledge/documents/${selected.value.id}`, { method: 'PUT', body })
    : await api('/api/v1/knowledge/documents', { method: 'POST', body })
  message.value = '文档已保存，重建后对 Knowledge Agent 生效。'
  await load()
}

async function remove() {
  if (!selected.value?.id || !confirm('确认删除该知识文档？删除后需要重建索引。')) return
  await api(`/api/v1/knowledge/documents/${selected.value.id}`, { method: 'DELETE' })
  selected.value = null
  message.value = '文档已删除，请重建知识库。'
  await load()
}

async function rebuild() {
  loading.value = true
  try {
    const result = await api<{ documents: number; chunks: number; duration_ms: number }>('/api/v1/knowledge/rebuild', { method: 'POST' })
    message.value = `重建完成：${result.documents} 个文档，${result.chunks} 个 Chunk，${result.duration_ms}ms`
    await load()
  } finally { loading.value = false }
}

async function search() {
  results.value = (await api<{ items: SearchItem[] }>('/api/v1/knowledge/search', {
    method: 'POST', body: JSON.stringify({ query: query.value }),
  })).items
}

function importFile(event: Event) {
  const file = (event.target as HTMLInputElement).files?.[0]
  if (!file || !selected.value) return
  file.text().then((content) => {
    if (!selected.value) return
    selected.value.content = content
    selected.value.source = file.name.toLowerCase().replace(/[^a-z0-9.-]+/g, '-')
  })
}

onMounted(load)
</script>

<template>
  <AppShell title="知识库管理" subtitle="PostgreSQL 文档源 · Milvus Hybrid Retrieval">
    <div class="stats-grid">
      <div><small>知识文档</small><strong>{{ documents.length }}</strong></div>
      <div><small>已索引</small><strong>{{ indexed }}</strong></div>
      <div><small>待重建</small><strong>{{ documents.length - indexed }}</strong></div>
      <button class="primary-button" :disabled="loading" @click="rebuild">{{ loading ? '正在重建…' : '重建知识库' }}</button>
    </div>
    <p v-if="message" class="success-banner">{{ message }}</p>
    <div class="knowledge-layout">
      <aside class="document-list-card">
        <div class="section-title"><h2>文档</h2><button @click="createNew">＋ 新建</button></div>
        <input v-model="documentQuery" class="search-input" placeholder="搜索标题或 Source" />
        <button v-for="item in filteredDocuments" :key="item.id" class="document-item" @click="select(item)">
          <span :class="['index-dot', { indexed: item.is_indexed }]"></span>
          <div><strong>{{ item.title }}</strong><small>{{ item.source }}</small></div>
        </button>
      </aside>
      <KnowledgeEditor v-if="selected" :document="selected" @save="save" @remove="remove" @import="importFile" />
      <div v-else class="editor-empty">选择一份文档，或新建知识内容。</div>
    </div>
    <section class="retrieval-card">
      <div><h2>Retrieval Playground</h2><p>验证 Hybrid + RRF + Reranker 的最终 Top-3。</p></div>
      <form @submit.prevent="search"><input v-model="query" placeholder="输入政策问题" required /><button class="primary-button">检索</button></form>
      <div class="search-results">
        <article v-for="item in results" :key="item.chunk_id">
          <header><strong>{{ item.source }}</strong><span>{{ item.score.toFixed(3) }}</span></header>
          <MdPreview :id="`chunk-${item.chunk_id}`" :model-value="item.content" :no-mermaid="true" :no-katex="true" />
        </article>
      </div>
    </section>
  </AppShell>
</template>
