<script setup lang="ts">
import { computed, ref } from 'vue'
import type { Conversation } from '../api/client'

const props = defineProps<{ items: Conversation[]; activeId: string | null }>()
const emit = defineEmits<{ select: [id: string]; create: [] }>()
const query = ref('')
const filtered = computed(() => {
  const text = query.value.trim().toLowerCase()
  return text ? props.items.filter((item) => item.title.toLowerCase().includes(text)) : props.items
})
</script>

<template>
  <aside class="conversation-panel">
    <button class="primary-button new-chat" @click="emit('create')">＋ 新建会话</button>
    <input v-model="query" class="search-input" placeholder="搜索会话" aria-label="搜索会话" />
    <div class="conversation-list">
      <button
        v-for="item in filtered"
        :key="item.conversation_id"
        class="conversation-item"
        :class="{ active: item.conversation_id === activeId }"
        @click="emit('select', item.conversation_id)"
      >
        <strong>{{ item.title }}</strong>
        <span>{{ item.last_message_preview }}</span>
        <time>{{ new Date(item.updated_at).toLocaleString('zh-CN') }}</time>
      </button>
      <p v-if="!filtered.length" class="empty-hint">还没有会话，从一个问题开始吧。</p>
    </div>
  </aside>
</template>
