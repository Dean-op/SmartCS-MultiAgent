import { ApiError, getToken } from './client'

export type SseEvent = { event: string; data: Record<string, unknown> }

export function createSseParser(onEvent: (event: SseEvent) => void) {
  let buffer = ''

  function drain() {
    buffer = buffer.replaceAll('\r\n', '\n')
    let boundary = buffer.indexOf('\n\n')
    while (boundary >= 0) {
      const block = buffer.slice(0, boundary)
      buffer = buffer.slice(boundary + 2)
      if (block && !block.startsWith(':')) {
        let event = 'message'
        const data: string[] = []
        for (const line of block.split('\n')) {
          if (line.startsWith('event:')) event = line.slice(6).trim()
          if (line.startsWith('data:')) data.push(line.slice(5).trimStart())
        }
        if (data.length) onEvent({ event, data: JSON.parse(data.join('\n')) })
      }
      boundary = buffer.indexOf('\n\n')
    }
  }

  return {
    feed(chunk: string) {
      buffer += chunk
      drain()
    },
    end() {
      if (buffer && !buffer.endsWith('\n\n')) buffer += '\n\n'
      drain()
    },
  }
}

export async function streamChat(
  payload: { message: string; conversation_id?: string },
  onEvent: (event: SseEvent) => void,
  signal: AbortSignal,
  onHeaders?: (headers: Headers) => void,
) {
  const token = getToken()
  const response = await fetch('/api/v1/chat/stream', {
    method: 'POST',
    headers: {
      Accept: 'text/event-stream',
      'Content-Type': 'application/json',
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
    },
    body: JSON.stringify(payload),
    signal,
  })
  if (!response.ok || !response.body) {
    const error = await response.json().catch(() => null)
    throw new ApiError(
      response.status,
      error?.error?.code ?? 'stream_error',
      error?.error?.message ?? '无法建立流式连接',
    )
  }
  onHeaders?.(response.headers)
  const parser = createSseParser(onEvent)
  const reader = response.body.getReader()
  const decoder = new TextDecoder()
  while (true) {
    const { value, done } = await reader.read()
    if (done) break
    parser.feed(decoder.decode(value, { stream: true }))
  }
  parser.feed(decoder.decode())
  parser.end()
}
