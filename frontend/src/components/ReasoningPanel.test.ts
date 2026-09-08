import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'
import ReasoningPanel from './ReasoningPanel.vue'

describe('ReasoningPanel', () => {
  it('opens while reasoning streams and collapses when the answer starts', async () => {
    const wrapper = mount(ReasoningPanel, {
      props: { content: '推理内容', streaming: true },
    })

    expect((wrapper.find('details').element as HTMLDetailsElement).open).toBe(true)
    await wrapper.setProps({ streaming: false })
    expect((wrapper.find('details').element as HTMLDetailsElement).open).toBe(false)
  })
})
