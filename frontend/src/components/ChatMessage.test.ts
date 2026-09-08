import { mount } from '@vue/test-utils'
import { config, XSSPlugin } from 'md-editor-v3'
import { describe, expect, it } from 'vitest'
import ChatMessage from './ChatMessage.vue'

config({
  markdownItPlugins(plugins) {
    return [...plugins, { type: 'xss', plugin: XSSPlugin, options: {} }]
  },
})

describe('ChatMessage', () => {
  it('renders markdown without executable script or event attributes', async () => {
    const wrapper = mount(ChatMessage, {
      props: {
        message: {
          id: 'message-1',
          role: 'assistant',
          content: '# 安全回答\n<script>alert(1)</script>\n```js" onmouseover="alert(2)\ncode\n```',
          reasoning_content: '<img src=x onerror=alert(3)>',
          status: 'completed',
          request_id: null,
          trace_id: null,
          latency_ms: null,
          created_at: new Date().toISOString(),
        },
      },
    })

    await new Promise((resolve) => setTimeout(resolve, 20))

    expect(wrapper.find('h1').text()).toBe('安全回答')
    expect(wrapper.find('script').exists()).toBe(false)
    const executableAttributes = wrapper.findAll('*').flatMap((element) =>
      Object.keys(element.attributes()).filter((name) => name.startsWith('on')),
    )
    expect(executableAttributes).toEqual([])
  })
})
