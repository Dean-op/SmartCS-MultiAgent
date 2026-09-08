<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { api } from '../api/client'
import AppShell from '../components/AppShell.vue'

type Review = { review_id: string; refund_number: string; amount: string; reason: string; created_at: string }
const reviews = ref<Review[]>([])
const message = ref('')

async function load() {
  reviews.value = await api<Review[]>('/api/v1/reviews/pending')
}

async function resolve(review: Review, decision: 'approve' | 'reject') {
  const action = decision === 'approve' ? '通过' : '拒绝'
  if (!confirm(`确认${action}退款 ${review.refund_number}？`)) return
  const note = prompt('审核备注（可选）') || null
  const response = await api<{ message: { content: string } }>(
    `/api/v1/reviews/${review.review_id}/${decision}`,
    { method: 'POST', body: JSON.stringify({ note }) },
  )
  message.value = response.message.content
  await load()
}

onMounted(load)
</script>

<template>
  <AppShell title="退款审核" subtitle="Human-in-the-loop · LangGraph interrupt / resume">
    <p v-if="message" class="success-banner">{{ message }}</p>
    <section class="review-board">
      <div class="section-title"><div><h2>待审核队列</h2><p>{{ reviews.length }} 条记录等待处理</p></div><button @click="load">刷新</button></div>
      <div v-if="reviews.length" class="review-grid">
        <article v-for="review in reviews" :key="review.review_id" class="review-card">
          <header><span>退款单</span><strong>{{ review.refund_number }}</strong></header>
          <div class="review-amount">¥ {{ review.amount }}</div>
          <p>{{ review.reason }}</p>
          <time>{{ new Date(review.created_at).toLocaleString('zh-CN') }}</time>
          <footer><button class="danger-button" @click="resolve(review, 'reject')">拒绝</button><button class="primary-button" @click="resolve(review, 'approve')">通过并恢复</button></footer>
        </article>
      </div>
      <div v-else class="editor-empty">当前没有待审核退款。</div>
    </section>
  </AppShell>
</template>
