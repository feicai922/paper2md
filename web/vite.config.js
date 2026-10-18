import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'
import AutoImport from 'unplugin-auto-import/vite'
import Components from 'unplugin-vue-components/vite'
import { ElementPlusResolver } from 'unplugin-vue-components/resolvers'

// 产物直接输出到 app/static/dist,由 FastAPI 托管。
//
// Element Plus 用**按需引入**:全量引入会让 JS 膨胀到 1.2MB(gzip 395KB),
// 按需后只打包实际用到的组件(体积约为 1/4)。
// ElMessage / ElMessageBox 这类"服务式"组件由 AutoImport 处理样式导入。
export default defineConfig({
  plugins: [
    vue(),
    AutoImport({ resolvers: [ElementPlusResolver()] }),
    Components({ resolvers: [ElementPlusResolver()] }),
  ],
  build: {
    outDir: '../app/static/dist',
    emptyOutDir: true,
    // 文件名带内容哈希:否则浏览器会缓存旧的 app.js,
    // 改完前端刷新还是老代码 —— 表现为"点了没反应"(实测踩过)。
    rollupOptions: {
      output: {
        entryFileNames: 'app-[hash].js',
        chunkFileNames: 'chunk-[hash].js',
        assetFileNames: 'app-[hash].[ext]',
      },
    },
  },
  server: {
    port: 5273,
    proxy: {
      '/api': 'http://127.0.0.1:8300',
      '/health': 'http://127.0.0.1:8300',
    },
  },
})
