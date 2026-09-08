<script setup lang="ts">
import { MdEditor } from 'md-editor-v3'
import type { ToolbarNames } from 'md-editor-v3'
import type { KnowledgeDocument } from '../api/client'

defineProps<{ document: KnowledgeDocument }>()
const emit = defineEmits<{ save: []; remove: []; import: [event: Event] }>()
const toolbars: ToolbarNames[] = [
  'bold', 'italic', '-', 'title', 'quote', 'unorderedList', 'orderedList',
  'code', 'link', '-', 'preview', 'catalog', 'fullscreen',
]
</script>

<template>
  <section class="editor-card">
    <div class="document-fields">
      <label>文档标题<input v-model="document.title" maxlength="200" /></label>
      <label>Source<input v-model="document.source" maxlength="128" placeholder="refund-policy.md" /></label>
      <label class="file-button">导入 .md<input type="file" accept=".md,text/markdown" @change="emit('import', $event)" /></label>
    </div>
    <MdEditor v-model="document.content" language="zh-CN" preview-theme="github" :toolbars="toolbars" :no-upload-img="true" />
    <div class="editor-actions">
      <button class="danger-button" @click="emit('remove')">删除文档</button>
      <button class="primary-button" @click="emit('save')">保存文档</button>
    </div>
  </section>
</template>
