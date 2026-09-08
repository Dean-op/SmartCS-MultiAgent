import { createRouter, createWebHashHistory } from 'vue-router'
import { auth } from './composables/auth'

const router = createRouter({
  history: createWebHashHistory(),
  routes: [
    { path: '/', redirect: '/chat' },
    { path: '/login', component: () => import('./views/LoginView.vue') },
    { path: '/chat', component: () => import('./views/ChatView.vue'), meta: { auth: true } },
    { path: '/admin/knowledge', component: () => import('./views/KnowledgeView.vue'), meta: { auth: true, admin: true } },
    { path: '/admin/reviews', component: () => import('./views/ReviewsView.vue'), meta: { auth: true, admin: true } },
  ],
})

router.beforeEach(async (to) => {
  if (!to.meta.auth) return true
  if (!auth.token.value) return '/login'
  if (!auth.user.value) {
    try {
      await auth.loadProfile()
    } catch {
      auth.logout()
      return '/login'
    }
  }
  if (to.meta.admin && auth.user.value?.role !== 'admin') return '/chat'
  return true
})

export default router
