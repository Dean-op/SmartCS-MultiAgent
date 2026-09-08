<script setup lang="ts">
import { MdPreview } from 'md-editor-v3'
import type { ChatMessage } from '../api/client'
import ReasoningPanel from './ReasoningPanel.vue'

defineProps<{ message: ChatMessage; streaming?: boolean }>()
</script>

<template>
  <article class="message" :class="message.role">
    <div class="message-label">{{ message.role === 'user' ? '你' : 'AI 客服' }}</div>
    <div class="message-bubble">
      <ReasoningPanel
        v-if="message.role === 'assistant'"
        :content="message.reasoning_content || ''"
        :streaming="streaming && !message.content"
      />
      <MdPreview
        v-if="message.role === 'assistant' && message.content"
        :id="`answer-${message.id}`"
        :model-value="message.content"
        :no-mermaid="true"
        :no-katex="true"
        :no-echarts="true"
      />
      <p v-else-if="message.role === 'user'">{{ message.content }}</p>
      <span v-else class="typing"><i></i><i></i><i></i></span>
      <footer v-if="message.role === 'assistant'">
        <span :class="['message-status', message.status]">{{ message.status }}</span>
        <span v-if="message.latency_ms" class="message-status">{{ (message.latency_ms / 1000).toFixed(2) }}s</span>
        <details v-if="message.request_id || message.trace_id" class="trace-details">
          <summary>调用信息</summary>
          <code v-if="message.request_id">Request {{ message.request_id }}</code>
          <code v-if="message.trace_id">Trace {{ message.trace_id }}</code>
        </details>
      </footer>
    </div>
  </article>
</template>
