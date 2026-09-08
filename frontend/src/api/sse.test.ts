import { describe, expect, it } from 'vitest'
import { createSseParser } from './sse'

describe('SSE parser', () => {
  it('reassembles events split across arbitrary network chunks', () => {
    const events: Array<{ event: string; data: Record<string, unknown> }> = []
    const parser = createSseParser((event) => events.push(event))

    parser.feed('event: reasoning_delta\ndata: {"con')
    parser.feed('tent":"先判断"}\n\nevent: delta\ndata: {"content":"你')
    parser.feed('好"}\n\n: ping\n\n')
    parser.end()

    expect(events).toEqual([
      { event: 'reasoning_delta', data: { content: '先判断' } },
      { event: 'delta', data: { content: '你好' } },
    ])
  })
})
