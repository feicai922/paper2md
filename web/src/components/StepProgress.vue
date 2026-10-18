<script setup>
// 阶段进度:转换(版面分析 + 识别)→ 打包(用 el-steps)
import { computed } from 'vue'
import { Search, Download } from '@element-plus/icons-vue'

const props = defineProps({
  stage: { type: String, default: '' },
  status: { type: String, default: '' },
})

const STEPS = [
  { key: 'convert', label: '版面分析 + 识别', icon: Search },
  { key: 'export', label: '导出 Markdown / 图片', icon: Download },
]
const ORDER = STEPS.map((s) => s.key)

// el-steps 的 active:0 表示还没开始,1 表示第一步完成…
const active = computed(() => {
  if (props.status === 'succeeded' || props.stage === 'done') return STEPS.length
  const i = ORDER.indexOf(props.stage)
  return i < 0 ? 0 : i
})
</script>

<template>
  <el-steps
    :active="active"
    :process-status="status === 'failed' ? 'error' : 'process'"
    :finish-status="status === 'failed' ? 'error' : 'success'"
    align-center
    style="margin-top: 18px"
  >
    <el-step v-for="s in STEPS" :key="s.key" :title="s.label">
      <template #icon>
        <el-icon><component :is="s.icon" /></el-icon>
      </template>
    </el-step>
  </el-steps>
</template>
