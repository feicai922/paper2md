<script setup>
// 文件清单
import { Document } from '@element-plus/icons-vue'
import { fmtBytes } from '../api'
import StatusPill from './StatusPill.vue'

defineProps({
  jobs: { type: Array, default: () => [] },
})
</script>

<template>
  <div class="file-list">
    <div v-for="j in jobs" :key="j.job_id" class="file-item">
      <el-icon class="muted"><Document /></el-icon>
      <span class="name">{{ j.filename }}</span>
      <span class="size">{{ j.page_count ? j.page_count + ' 页 · ' : '' }}{{ fmtBytes(j.src_bytes) }}</span>
      <StatusPill :status="j.status" />
    </div>
  </div>
</template>
