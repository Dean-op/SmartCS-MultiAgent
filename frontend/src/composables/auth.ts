import { readonly, ref } from 'vue'
import { api, getToken, setToken, type UserProfile } from '../api/client'

const token = ref<string | null>(getToken())
const user = ref<UserProfile | null>(null)

async function login(email: string, password: string) {
  const response = await api<{ access_token: string }>('/api/v1/auth/login', {
    method: 'POST',
    body: JSON.stringify({ email, password }),
  })
  token.value = response.access_token
  setToken(token.value)
  await loadProfile()
}

async function loadProfile() {
  user.value = await api<UserProfile>('/api/v1/auth/me')
  return user.value
}

function logout() {
  token.value = null
  user.value = null
  setToken(null)
}

export const auth = {
  token: readonly(token),
  user: readonly(user),
  login,
  loadProfile,
  logout,
}
