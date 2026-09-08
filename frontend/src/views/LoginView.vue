<script setup lang="ts">
import { ref } from 'vue'
import { useRouter } from 'vue-router'
import { auth } from '../composables/auth'

const router = useRouter()
const email = ref('alice@example.com')
const password = ref('customer-password')
const loading = ref(false)
const error = ref('')

async function submit() {
  loading.value = true
  error.value = ''
  try {
    await auth.login(email.value, password.value)
    await router.push(auth.user.value?.role === 'admin' ? '/admin/knowledge' : '/chat')
  } catch (exception) {
    error.value = exception instanceof Error ? exception.message : '登录失败'
  } finally {
    loading.value = false
  }
}

function fillAdmin() {
  email.value = 'admin@example.com'
  password.value = 'admin-password'
}
</script>

<template>
  <main class="login-page">
    <section class="login-copy">
      <span class="eyebrow">ECOMMERCE · MULTI-AGENT</span>
      <h1>把每一次咨询，<br /><em>交给正确的 Agent。</em></h1>
      <p>订单、商品、退款与企业知识，由专属 Agent 协作完成，并保留完整会话、推理与执行轨迹。</p>
      <div class="capability-row"><span>LangGraph</span><span>Hybrid RAG</span><span>Human Review</span></div>
    </section>
    <form class="login-card" @submit.prevent="submit">
      <div class="brand login-brand"><span class="brand-mark">智</span><strong>智服台</strong></div>
      <h2>欢迎回来</h2><p>登录以进入智能客服工作台</p>
      <label>邮箱<input v-model="email" type="email" autocomplete="username" required /></label>
      <label>密码<input v-model="password" type="password" autocomplete="current-password" required /></label>
      <p v-if="error" class="error-banner">{{ error }}</p>
      <button class="primary-button login-button" :disabled="loading">{{ loading ? '登录中…' : '登录' }}</button>
      <button type="button" class="text-button" @click="fillAdmin">使用管理员演示账号</button>
      <small class="demo-note">默认已填充 customer 演示账号</small>
    </form>
  </main>
</template>
