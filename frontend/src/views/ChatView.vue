<script setup lang="ts">
import { nextTick, onMounted, ref } from 'vue'
import { api, type ChatMessage, type Conversation } from '../api/client'
import { streamChat, type SseEvent } from '../api/sse'
import AppShell from '../components/AppShell.vue'
import ChatMessageView from '../components/ChatMessage.vue'
import ConversationList from '../components/ConversationList.vue'

const conversations = ref<Conversation[]>([])
const messages = ref<ChatMessage[]>([])
const activeId = ref<string | null>(null)
const draft = ref('')
const running = ref(false)
const stage = ref('准备就绪')
const error = ref('')
const messageArea = ref<HTMLElement | null>(null)
const mobileSidebar = ref(false)
let controller: AbortController | null = null

const examples = [
  '我的订单 EC2026080016 现在是什么状态？',
  'SKU ELEC-HUB-001 这个商品多少钱？',
  '退款单 RF2026080001 处理到哪了？',
  '平台的七天无理由退款政策是什么？',
  '查询订单 EC2026080016，同时告诉我相关退款单 RF2026080001 的状态。',
]

async function loadConversations() {
  conversations.value = (await api<{ items: Conversation[] }>('/api/v1/conversations')).items
}

async function selectConversation(id: string) {
  mobileSidebar.value = false
  activeId.value = id
  const response = await api<{ items: ChatMessage[] }>(`/api/v1/conversations/${id}/messages`)
  messages.value = response.items
  await scrollToEnd()
}

function newConversation() {
  mobileSidebar.value = false
  activeId.value = null
  messages.value = []
  draft.value = ''
  stage.value = '新会话'
}

async function scrollToEnd() {
  await nextTick()
  messageArea.value?.scrollTo({ top: messageArea.value.scrollHeight, behavior: 'smooth' })
}

function handleEvent(event: SseEvent, assistant: ChatMessage) {
  const data = event.data
  if (event.event === 'conversation') {
    activeId.value = String(data.conversation_id)
    assistant.id = String(data.assistant_message_id)
  } else if (event.event === 'status') {
    stage.value = `${String(data.phase)} · ${String(data.name)}`
  } else if (event.event === 'reasoning_delta') {
    assistant.reasoning_content = (assistant.reasoning_content || '') + String(data.content)
  } else if (event.event === 'delta') {
    assistant.content += String(data.content)
  } else if (event.event === 'done') {
    assistant.reasoning_content = String(data.reasoning_content || '')
    assistant.content = String(data.content)
    assistant.status = data.status as ChatMessage['status']
    assistant.latency_ms = Number(data.latency_ms || 0) || null
    stage.value = assistant.status === 'pending_review' ? '等待人工审核' : '已完成'
  } else if (event.event === 'error') {
    assistant.status = 'failed'
    error.value = String(data.message || '生成失败')
  }
  void scrollToEnd()
}

async function send() {
  const content = draft.value.trim()
  if (!content || running.value) return
  draft.value = ''
  error.value = ''
  running.value = true
  const now = new Date().toISOString()
  const userMessage: ChatMessage = {
    id: crypto.randomUUID(), role: 'user', content, reasoning_content: null,
    status: 'completed', request_id: null, trace_id: null, latency_ms: null, created_at: now,
  }
  const assistant: ChatMessage = {
    id: crypto.randomUUID(), role: 'assistant', content: '', reasoning_content: '',
    status: 'pending', request_id: null, trace_id: null, latency_ms: null, created_at: now,
  }
  messages.value.push(userMessage, assistant)
  controller = new AbortController()
  try {
    await streamChat(
      {
        message: content,
        client_message_id: userMessage.id,
        ...(activeId.value ? { conversation_id: activeId.value } : {}),
      },
      (event) => handleEvent(event, assistant),
      controller.signal,
      (headers) => {
        assistant.request_id = headers.get('x-request-id')
        assistant.trace_id = headers.get('traceparent')?.split('-')[1] || null
      },
    )
    await loadConversations()
  } catch (exception) {
    assistant.status = controller.signal.aborted ? 'cancelled' : 'failed'
    error.value = controller.signal.aborted
      ? '已停止生成'
      : exception instanceof Error ? exception.message : '生成失败'
  } finally {
    running.value = false
    controller = null
  }
}

function stop() {
  controller?.abort()
}

onMounted(loadConversations)
</script>

<template>
  <AppShell title="智能客服" subtitle="Router 自动选择最合适的 Specialist Agent">
    <div class="chat-layout">
      <ConversationList :class="{ 'mobile-open': mobileSidebar }" :items="conversations" :active-id="activeId" @select="selectConversation" @create="newConversation" />
      <section class="chat-main">
        <button class="mobile-conversation-toggle" @click="mobileSidebar = !mobileSidebar">☰ 会话</button>
        <div ref="messageArea" class="message-area">
          <div v-if="!messages.length" class="welcome-state">
            <span class="welcome-icon">✦</span><h2>今天想了解什么？</h2>
            <p>我会自动协调订单、退款、商品与知识库 Agent。</p>
            <div class="example-grid">
              <button v-for="example in examples" :key="example" @click="draft = example">{{ example }}</button>
            </div>
          </div>
          <ChatMessageView
            v-for="message in messages"
            :key="message.id"
            :message="message"
            :streaming="running && message === messages.at(-1)"
          />
        </div>
        <div class="composer-wrap">
          <p v-if="error" class="error-banner compact">{{ error }}</p>
          <div class="run-stage"><i :class="{ active: running }"></i>{{ stage }}</div>
          <form class="composer" @submit.prevent="send">
            <textarea
              v-model="draft"
              rows="2"
              maxlength="4000"
              placeholder="输入问题，Enter 发送，Shift+Enter 换行"
              @keydown.enter.exact.prevent="send"
            ></textarea>
            <button v-if="running" type="button" class="stop-button" @click="stop">■ 停止</button>
            <button v-else class="send-button" :disabled="!draft.trim()">发送 ↑</button>
          </form>
        </div>
      </section>
    </div>
  </AppShell>
</template>
