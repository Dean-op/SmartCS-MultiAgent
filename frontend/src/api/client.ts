export type UserProfile = { id: string; email: string; role: 'customer' | 'admin' }
export type Conversation = {
  conversation_id: string
  title: string
  last_message_preview: string
  updated_at: string
}
export type ChatMessage = {
  id: string
  role: 'user' | 'assistant'
  content: string
  reasoning_content: string | null
  status: 'pending' | 'completed' | 'pending_review' | 'failed' | 'cancelled'
  request_id: string | null
  trace_id: string | null
  latency_ms: number | null
  created_at: string
}
export type KnowledgeDocument = {
  id: string
  title: string
  source: string
  content?: string
  content_hash: string
  indexed_hash: string | null
  indexed_at: string | null
  is_indexed: boolean
  created_at: string
  updated_at: string
}

const TOKEN_KEY = 'ecommerce-agent-token'

export function getToken() {
  return sessionStorage.getItem(TOKEN_KEY)
}

export function setToken(token: string | null) {
  if (token) sessionStorage.setItem(TOKEN_KEY, token)
  else sessionStorage.removeItem(TOKEN_KEY)
}

export class ApiError extends Error {
  constructor(public status: number, public code: string, message: string) {
    super(message)
  }
}

export async function api<T>(path: string, init: RequestInit = {}): Promise<T> {
  const headers = new Headers(init.headers)
  if (!(init.body instanceof FormData)) headers.set('Content-Type', 'application/json')
  const token = getToken()
  if (token) headers.set('Authorization', `Bearer ${token}`)
  const response = await fetch(path, { ...init, headers })
  if (!response.ok) {
    const payload = await response.json().catch(() => null)
    if (response.status === 401) {
      setToken(null)
      window.dispatchEvent(new Event('auth:expired'))
    }
    throw new ApiError(
      response.status,
      payload?.error?.code ?? 'http_error',
      payload?.error?.message ?? `HTTP ${response.status}`,
    )
  }
  if (response.status === 204) return undefined as T
  return response.json() as Promise<T>
}
