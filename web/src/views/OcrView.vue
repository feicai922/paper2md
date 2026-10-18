<script setup>
// 转换首页:上传 → 提交 → 结果。轮询在本页统一管理。
import { ref, computed, onUnmounted } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { Refresh, Delete, Plus } from '@element-plus/icons-vue'
import { api, OUTPUT_LABEL } from '../api'
import UploadDrop from '../components/UploadDrop.vue'
import UploadSetup from '../components/UploadSetup.vue'
import JobResult from '../components/JobResult.vue'
import BatchResult from '../components/BatchResult.vue'
import StatusPill from '../components/StatusPill.vue'

const health = ref(null)
const recent = ref([])          // 最近任务(含未完成的)
const healthError = ref('')
const uploading = ref(false)
const uploadError = ref('')

const batch = ref(null)
const mode = ref('')            // '' | 'single' | 'batch'
const singleJob = ref(null)
const batchJobs = ref([])

let timer = null
const isBusy = computed(() => mode.value !== '')
const DONE = ['succeeded', 'failed', 'canceled']

async function loadRecent() {
  try {
    recent.value = await api.jobs()
  } catch { /* 瞬时错误时忽略 */ }
}

async function checkHealth() {
  try {
    health.value = await api.health()
    healthError.value = ''
  } catch (e) {
    health.value = null
    healthError.value = e.message
  }
}

async function onFiles(files) {
  uploading.value = true
  uploadError.value = ''
  try {
    const d = await api.uploadBatch(files)
    batch.value = d
    mode.value = ''
    singleJob.value = null
    batchJobs.value = []
    ElMessage.success(`已上传 ${d.count} 个文件`)
  } catch (e) {
    uploadError.value = e.message
    ElMessage.error('上传失败：' + e.message)
  } finally {
    uploading.value = false
  }
}

const startError = ref('')

async function onStart(payload = {}) {
  if (!batch.value) return
  startError.value = ''
  const files = batch.value.jobs || []
  let d
  try {
    d = await api.startBatch(batch.value.batch_id, payload)
  } catch (e) {
    // 错误必须回传给 UploadSetup 显示:父组件的异常传不回子组件,
    // 所以存进 startError 由子组件通过 props 展示
    startError.value = e.message
    ElMessage.error('提交失败：' + e.message)
    return
  }
  if (d.errors && d.errors.length) {
    ElMessage.warning(`${d.errors.length} 个任务未能提交：${d.errors[0]}`)
  }
  batch.value = null
  if (files.length <= 1) {
    mode.value = 'single'
    singleJob.value = d.jobs[0]
    pollSingle()
  } else {
    mode.value = 'batch'
    batchJobs.value = d.jobs
    pollBatch()
  }
  ElMessage.success(`已提交 ${d.started} 个任务（串行转换）`)
  checkHealth()
}

function stopPoll() {
  if (timer) { clearInterval(timer); timer = null }
}

function pollSingle() {
  stopPoll()
  const tick = async () => {
    if (!singleJob.value) return
    try {
      const j = await api.job(singleJob.value.job_id)
      singleJob.value = j
      loadRecent()
      if (DONE.includes(j.status)) {
        stopPoll()
        checkHealth()
      }
    } catch { /* 忽略瞬时错误 */ }
  }
  tick()
  timer = setInterval(tick, 3000)
}

function pollBatch() {
  stopPoll()
  const tick = async () => {
    const ids = batchJobs.value.map((j) => j.job_id)
    if (!ids.length) return
    try {
      const all = await api.jobs()
      const map = new Map(all.map((j) => [j.job_id, j]))
      batchJobs.value = ids.map((id) => map.get(id)).filter(Boolean)
      const done = batchJobs.value.filter((j) => DONE.includes(j.status)).length
      if (done === ids.length) {
        stopPoll()
        checkHealth()
      }
    } catch { /* 忽略 */ }
  }
  tick()
  timer = setInterval(tick, 3000)
}

async function onCancel() {
  try {
    await ElMessageBox.confirm('确定取消？已转换的部分不会保留。', '取消任务', {
      confirmButtonText: '确定取消',
      cancelButtonText: '继续',
      type: 'warning',
    })
  } catch { return }

  if (mode.value === 'single' && singleJob.value) {
    await api.cancel(singleJob.value.job_id)
    pollSingle()
  } else {
    for (const j of batchJobs.value) {
      if (['queued', 'running'].includes(j.status)) await api.cancel(j.job_id)
    }
    pollBatch()
  }
  ElMessage.info('已取消')
}

async function onRestart(jobId) {
  try {
    await ElMessageBox.confirm(
      '用当前引擎重新转换这个文件？产物会被覆盖（源 PDF 保留）。',
      '重新转换',
      { confirmButtonText: '重新转换', cancelButtonText: '取消', type: 'info' },
    )
  } catch { return }
  try {
    const j = await api.startOne(jobId)
    singleJob.value = j
    pollSingle()
    ElMessage.success('已提交，排队中…')
  } catch (e) {
    ElMessage.error('提交失败：' + e.message)
  }
}

function openJob(row) {
  stopPoll()
  batch.value = null
  if (DONE.includes(row.status) || ['queued', 'running'].includes(row.status)) {
    mode.value = 'single'
    singleJob.value = row
    if (['queued', 'running'].includes(row.status)) pollSingle()
  }
}

function reset() {
  stopPoll()
  batch.value = null
  mode.value = ''
  singleJob.value = null
  batchJobs.value = []
}

onUnmounted(stopPoll)
checkHealth()
loadRecent()
</script>

<template>
  <div>
    <el-alert
      v-if="healthError"
      type="error"
      :closable="false"
      show-icon
      style="margin-bottom: 16px"
      :title="'无法连接本服务：' + healthError"
    />
    <el-alert
      v-else-if="health"
      :type="health.engine?.available ? 'success' : 'warning'"
      :closable="false"
      show-icon
      style="margin-bottom: 16px"
    >
      <template v-if="health.engine?.available">
        就绪 · 引擎 {{ health.engine.pipeline }} · 提交后按队列逐个转换（不占用常驻显存）
      </template>
      <template v-else>
        引擎不可用（找不到 {{ health.engine?.python }}），请检查 paddle 环境
      </template>
    </el-alert>

    <el-card v-if="!batch && !isBusy" shadow="never">
      <UploadDrop :disabled="uploading" @files="onFiles" />
      <div v-if="uploading" class="muted" style="margin-top: 12px; text-align: center">
        <el-icon class="is-loading"><Refresh /></el-icon> 正在上传…
      </div>
      <el-alert
        v-if="uploadError"
        type="error"
        :closable="false"
        show-icon
        style="margin-top: 12px"
        :title="'上传失败：' + uploadError"
      />
    </el-card>

    <UploadSetup
      v-if="batch"
      :jobs="batch.jobs"
      :start-error="startError"
      @start="onStart"
      @cancel="reset"
    />

    <JobResult
      v-if="mode === 'single' && singleJob"
      :job="singleJob"
      @cancel="onCancel"
      @restart="onRestart"
    />
    <BatchResult
      v-if="mode === 'batch' && batchJobs.length"
      :jobs="batchJobs"
      @cancel="onCancel"
    />

    <!-- 最近任务:上传前后的历史都能看到(不只完成的) -->
    <el-card v-if="recent.length" shadow="never">
      <template #header>
        <div style="display: flex; justify-content: space-between; align-items: center">
          <span style="font-weight: 600; font-size: 14px">最近任务</span>
          <el-button link type="primary" size="small" @click="loadRecent">刷新</el-button>
        </div>
      </template>
      <el-table :data="recent.slice(0, 8)" size="small" @row-click="(r) => openJob(r)">
        <el-table-column prop="filename" label="文件" min-width="200" show-overflow-tooltip />
        <el-table-column label="页数" width="70">
          <template #default="{ row }">{{ row.page_count || '—' }}</template>
        </el-table-column>
        <el-table-column label="状态" width="170">
          <template #default="{ row }">
            <StatusPill :status="row.status" />
            <span
              v-if="['queued', 'running'].includes(row.status) && row.progress_known"
              class="mono muted"
              style="margin-left: 6px; font-size: 12px"
            >
              {{ Math.round((row.progress || 0) * 100) }}%
            </span>
          </template>
        </el-table-column>
        <el-table-column label="下载" width="240">
          <template #default="{ row }">
            <el-button
              v-for="(url, k) in row.downloads || {}"
              :key="k"
              link type="primary" size="small"
              tag="a" :href="url"
              :label="k === 'md_zip' ? 'ZIP' : 'MD'"
            />
          </template>
        </el-table-column>
      </el-table>
    </el-card>

    <el-card shadow="never">
      <div style="display: flex; justify-content: space-between; align-items: center; gap: 12px; flex-wrap: wrap">
        <span style="font-weight: 600; font-size: 14px">快捷操作</span>
        <div style="display: flex; gap: 10px; flex-wrap: wrap">
          <el-button :icon="Refresh" @click="checkHealth">刷新状态</el-button>
          <el-button v-if="isBusy || batch" :icon="Plus" type="primary" plain @click="reset">
            新任务
          </el-button>
        </div>
      </div>
    </el-card>
  </div>
</template>
