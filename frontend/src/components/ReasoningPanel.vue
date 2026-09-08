<script setup lang="ts">
import { ref, useId, watch } from 'vue'
import { MdPreview } from 'md-editor-v3'

const props = defineProps<{ content: string; streaming?: boolean }>()
const previewId = `reasoning-${useId().replaceAll(':', '')}`
const open = ref(Boolean(props.streaming))
watch(() => props.streaming, (value) => { open.value = Boolean(value) })
</script>

<template>
  <details v-if="content" class="reasoning-panel" :open="open" @toggle="open = ($event.target as HTMLDetailsElement).open">
    <summary><span>模型推理过程</span><small>模型生成，仅供参考</small></summary>
    <MdPreview :id="previewId" :model-value="content" :no-mermaid="true" :no-katex="true" :no-echarts="true" />
  </details>
</template>
