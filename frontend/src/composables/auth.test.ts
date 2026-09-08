import { afterEach, describe, expect, it, vi } from 'vitest'
import { api } from '../api/client'
import { auth } from './auth'

describe('auth state', () => {
  afterEach(() => {
    auth.logout()
    vi.restoreAllMocks()
  })

  it('clears reactive user and token when any API returns 401', async () => {
    vi.stubGlobal('fetch', vi.fn()
      .mockResolvedValueOnce(new Response(JSON.stringify({ access_token: 'token-1' }), { status: 200 }))
      .mockResolvedValueOnce(new Response(JSON.stringify({ id: 'u1', email: 'alice@example.com', role: 'customer' }), { status: 200 }))
      .mockResolvedValueOnce(new Response(JSON.stringify({ error: { code: 'http_error', message: 'Unauthorized' } }), { status: 401 })))

    await auth.login('alice@example.com', 'customer-password')
    await expect(api('/api/v1/protected')).rejects.toThrow('Unauthorized')

    expect(auth.token.value).toBeNull()
    expect(auth.user.value).toBeNull()
  })
})
