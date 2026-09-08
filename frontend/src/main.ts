import { createApp } from 'vue'
import { config, XSSPlugin } from 'md-editor-v3'
import 'md-editor-v3/lib/style.css'
import 'md-editor-v3/lib/preview.css'
import App from './App.vue'
import router from './router'
import './styles/main.css'

config({
  markdownItPlugins(plugins) {
    return [...plugins, { type: 'xss', plugin: XSSPlugin, options: {} }]
  },
})

createApp(App).use(router).mount('#app')
