import { createApp } from 'vue'
import { createRouter, createWebHistory } from 'vue-router'
import * as ElementPlusIconsVue from '@element-plus/icons-vue'

// ⚠️ 必须显式引入「服务式」组件的样式。
// unplugin-vue-components 的按需引入只覆盖**模板里用的**组件(el-card/el-button 等);
// ElMessage / ElMessageBox 是我们在 .vue 里显式 import 的,样式不会自动注入 ——
// 实测后果:删除确认弹窗没有定位与尺寸样式,整个框乱飘、遮罩也不正常。
import 'element-plus/theme-chalk/el-message.css'
import 'element-plus/theme-chalk/el-message-box.css'
import 'element-plus/theme-chalk/el-overlay.css'
import 'element-plus/theme-chalk/el-loading.css'

import './styles.css'

import App from './App.vue'
import OcrView from './views/OcrView.vue'
import ArchiveView from './views/ArchiveView.vue'

// Element Plus 走**按需引入**(见 vite.config.js 的 resolver):
// 组件与样式在用到的地方自动导入,这里不再 app.use(ElementPlus)。
// 图标仍需显式注册(体积很小,全量约 100KB)。

const router = createRouter({
  history: createWebHistory(),
  routes: [
    { path: '/', name: 'ocr', component: OcrView },
    { path: '/archive', name: 'archive', component: ArchiveView },
    { path: '/:pathMatch(.*)*', redirect: '/' },
  ],
})

const app = createApp(App)

for (const [name, comp] of Object.entries(ElementPlusIconsVue)) {
  app.component(name, comp)
}

app.use(router)
app.mount('#app')
