<script setup lang="ts">
import { useRouter } from 'vue-router'
import { auth } from '../composables/auth'

defineProps<{ title: string; subtitle?: string }>()
const router = useRouter()

function logout() {
  auth.logout()
  router.push('/login')
}
</script>

<template>
  <div class="app-shell">
    <aside class="nav-panel">
      <div class="brand">
        <span class="brand-mark">智</span>
        <div><strong>智服台</strong><small>Multi-Agent Service</small></div>
      </div>
      <nav>
        <RouterLink to="/chat">智能客服</RouterLink>
        <RouterLink v-if="auth.user.value?.role === 'admin'" to="/admin/knowledge">知识库管理</RouterLink>
        <RouterLink v-if="auth.user.value?.role === 'admin'" to="/admin/reviews">退款审核</RouterLink>
      </nav>
      <div class="account-card">
        <span class="avatar">{{ auth.user.value?.email.slice(0, 1).toUpperCase() }}</span>
        <div><strong>{{ auth.user.value?.email }}</strong><small>{{ auth.user.value?.role }}</small></div>
        <button class="icon-button" title="退出登录" @click="logout">↗</button>
      </div>
    </aside>
    <main class="workspace">
      <header class="page-header">
        <div><h1>{{ title }}</h1><p v-if="subtitle">{{ subtitle }}</p></div>
        <span class="service-status"><i></i> 服务在线</span>
      </header>
      <slot />
    </main>
  </div>
</template>
