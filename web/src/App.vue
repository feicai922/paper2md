<script setup>
import { RouterView, useRoute, useRouter } from 'vue-router'
import { computed } from 'vue'
import { Document, FolderOpened } from '@element-plus/icons-vue'

const route = useRoute()
const router = useRouter()

const active = computed(() => (route.name === 'archive' ? 'archive' : 'ocr'))

function go(name) {
  router.push({ ocr: '/', archive: '/archive' }[name] || '/')
}
</script>

<template>
  <div class="wrap">
    <div class="page-head">
      <div>
        <h1>PDF → Markdown</h1>
        <div class="sub">
          本地 PaddleX 版面分析 · 标题层级 / 公式 LaTeX / 表格 / 插图按原位置保留
        </div>
      </div>

      <el-radio-group :model-value="active" @change="go">
        <el-radio-button value="ocr">
          <el-icon style="margin-right: 5px"><Document /></el-icon>转换
        </el-radio-button>
        <el-radio-button value="archive">
          <el-icon style="margin-right: 5px"><FolderOpened /></el-icon>归档
        </el-radio-button>
      </el-radio-group>
    </div>

    <RouterView />
  </div>
</template>

<style scoped>
.page-head :deep(.el-radio-button__inner) {
  display: inline-flex;
  align-items: center;
  padding: 9px 16px;
}
</style>
