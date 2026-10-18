<script setup>
// 批量任务结果:整批进度 + 每个文件状态与下载
import { computed } from 'vue'
import { Download, Close } from '@element-plus/icons-vue'
import ProgressBar from './ProgressBar.vue'
import StatusPill from './StatusPill.vue'

const props = defineProps({
  jobs: { type: Array, default: () => [] },
})
const emit = defineEmits(['cancel'])

const DONE = ['succeeded', 'failed', 'canceled']
const BUSY = ['queued', 'running']

const overall = computed(() => {
  if (!props.jobs.length) return 0
  return props.jobs.reduce((a, j) => a + (j.progress || 0), 0) / props.jobs.length
})

const doneCount = computed(() => props.jobs.filter((j) => DONE.includes(j.status)).length)
const okCount = computed(() => props.jobs.filter((j) => j.status === 'succeeded').length)
const failCount = computed(() => props.jobs.filter((j) => j.status === 'failed').length)
const allDone = computed(() => doneCount.value === props.jobs.length)
const anyQueued = computed(() => props.jobs.some((j) => j.status === 'queued'))
const unknown = computed(() => props.jobs.some((j) => BUSY.includes(j.status) && !j.progress_known))

const message = computed(() => {
  let s = `已完成 ${doneCount.value}/${props.jobs.length}`
  if (okCount.value) s += `（成功 ${okCount.value}）`
  if (failCount.value) s += `（失败 ${failCount.value}）`
  if (anyQueued.value) s += ` · 其余排队中（串行转换）`
  return s
})

const SHORT = { markdown: 'MD', md_zip: 'ZIP' }
</script>

<template>
  <el-card shadow="never">
    <div style="display: flex; justify-content: space-between; align-items: center; gap: 12px; flex-wrap: wrap">
      <span style="font-weight: 600">批量任务（{{ jobs.length }} 个文件）</span>
      <StatusPill :status="allDone ? 'succeeded' : 'running'" />
    </div>

    <div style="margin-top: 18px">
      <ProgressBar :progress="overall" :message="message" :indeterminate="!allDone && unknown" />
    </div>

    <div v-if="!allDone" style="margin-top: 16px">
      <el-button :icon="Close" @click="emit('cancel')">取消全部</el-button>
    </div>

    <div class="file-list" style="margin-top: 18px">
      <div v-for="j in jobs" :key="j.job_id" class="file-item">
        <span class="name">
          {{ j.filename }}
          <div v-if="BUSY.includes(j.status)" class="muted" style="font-size: 12.5px; margin-top: 3px">
            {{ j.message }}
          </div>
          <div
            v-else-if="j.status === 'failed'"
            style="font-size: 12.5px; margin-top: 3px; color: var(--el-color-danger)"
          >
            {{ (j.error || '').slice(0, 70) }}
          </div>
          <div v-else-if="j.status === 'succeeded'" style="margin-top: 5px">
            <el-button
              v-for="(url, k) in j.downloads"
              :key="k"
              link
              type="primary"
              size="small"
              :icon="Download"
              tag="a"
              :href="url"
              style="margin-right: 10px"
            >{{ SHORT[k] || k }}</el-button>
          </div>
        </span>
        <StatusPill :status="j.status" />
      </div>
    </div>
  </el-card>
</template>
