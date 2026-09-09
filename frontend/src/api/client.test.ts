import { afterEach, describe, expect, it, vi } from 'vitest'
import { api } from './client'

describe('API client', () => {
  afterEach(() => vi.restoreAllMocks())

  it('lets the browser set multipart boundaries for FormData uploads', async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(JSON.stringify({ id: 'document-1' }), {
        status: 200,
        headers: { 'Content-Type': 'application/json' },
      }),
    )
    vi.stubGlobal('fetch', fetchMock)
    const body = new FormData()
    body.append('file', new Blob(['pdf']), 'policy.pdf')

    await api('/api/v1/knowledge/documents/pdf', { method: 'POST', body })

    const headers = fetchMock.mock.calls[0][1].headers as Headers
    expect(headers.has('Content-Type')).toBe(false)
  })
})
