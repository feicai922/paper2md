<script setup>
// 单任务结果:状态 / 进度 / 阶段 / 下载 / Markdown 渲染预览
import { computed, ref, watch } from 'vue'
import { Download, Close, Document, RefreshRight } from '@element-plus/icons-vue'
import { api, fmtBytes, OUTPUT_LABEL } from '../api'
import StatusPill from './StatusPill.vue'
import ProgressBar from './ProgressBar.vue'
import StepProgress from './StepProgress.vue'
import MarkdownView from './MarkdownView.vue'

const props = defineProps({
  job: { type: Object, required: true },
})
const emit = defineEmits(['cancel', 'restart'])

const canCancel = computed(() => ['queued', 'running'].includes(props.job.status))

const stats = computed(() => {
  const j = props.job
  const out = []
  if (j.page_count) out.push({ k: '页数', v: j.page_count })
  if (j.src_bytes) out.push({ k: '原文件', v: fmtBytes(j.src_bytes) })
  if (j.sizes?.markdown) out.push({ k: 'Markdown', v: fmtBytes(j.sizes.markdown) })
  const eng = j.engine || j.pipeline
  if (eng) out.push({ k: '管线', v: eng + (j.device ? ' · ' + j.device : '') })
  if (j.timings_text?.total) out.push({ k: '总耗时', v: j.timings_text.total, highlight: true })
  return out
})

const TYPE_MAP = { markdown: 'primary', md_zip: 'success' }
const downloads = computed(() => {
  const j = props.job
  if (j.status !== 'succeeded' || !j.downloads) return []
  return Object.entries(j.downloads).map(([k, url]) => ({
    key: k,
    url,
    label: OUTPUT_LABEL[k] || k,
    type: TYPE_MAP[k] || 'default',
  }))
})

// --- Markdown 预览 ---
const preview = ref('')
const previewTruncated = ref(false)
const previewError = ref('')
const previewLoading = ref(false)
const showPreview = ref(true)
let loadedFor = ''

async function loadPreview() {
  const j = props.job
  if (!j?.job_id || !(j.downloads || {}).markdown) return
  previewLoading.value = true
  previewError.value = ''
  try {
    const d = await api.preview(j.job_id)
    preview.value = d.text || ''
    previewTruncated.value = !!d.truncated
    loadedFor = j.job_id
  } catch (e) {
    previewError.value = e.message
  } finally {
    previewLoading.value = false
  }
}

watch(
  () => [props.job?.job_id, props.job?.status],
  () => {
    const j = props.job
    if (j?.status === 'succeeded' && loadedFor !== j.job_id) loadPreview()
  },
  { immediate: true },
)
</script>

<template>
  <el-card shadow="never">
    <div style="display: flex; justify-content: space-between; align-items: center; gap: 12px; flex-wrap: wrap">
      <span style="font-weight: 600; word-break: break-all">{{ job.filename }}</span>
      <StatusPill :status="job.status" />
    </div>

    <div style="margin-top: 18px">
      <ProgressBar
        :progress="job.progress"
        :message="job.message"
        :indeterminate="['queued', 'running'].includes(job.status) && !job.progress_known"
      />
    </div>

    <StepProgress :stage="job.stage" :status="job.status" />

    <div v-if="stats.length" style="margin-top: 20px">
      <el-descriptions :column="3" border size="small">
        <el-descriptions-item v-for="s in stats" :key="s.k" :label="s.k">
          <span :style="s.highlight ? 'color: var(--el-color-primary); font-weight: 600' : ''">
            {{ s.v }}
          </span>
        </el-descriptions-item>
      </el-descriptions>
    </div>

    <div v-if="downloads.length || canCancel" style="margin-top: 18px; display: flex; gap: 10px; flex-wrap: wrap">
      <el-button
        v-for="d in downloads"
        :key="d.key"
        :type="d.type"
        :icon="Download"
        tag="a"
        :href="d.url"
      >{{ d.label }}</el-button>
      <el-button v-if="canCancel" :icon="Close" @click="emit('cancel')">取消</el-button>
      <el-button
        v-if="job.status === 'succeeded'"
        :icon="RefreshRight"
        @click="emit('restart', job.job_id)"
      >重新转换</el-button>
    </div>

    <el-alert
      v-if="job.error"
      type="error"
      :closable="false"
      show-icon
      style="margin-top: 16px"
      :title="job.error"
    />

    <!-- Markdown 预览:真正渲染(标题/表格/图片/公式) -->
    <div v-if="job.status === 'succeeded'" style="margin-top: 20px">
      <div
        style="display: flex; align-items: center; gap: 8px; cursor: pointer; user-select: none"
        @click="showPreview = !showPreview"
      >
        <el-icon><Document /></el-icon>
        <span style="font-weight: 600; font-size: 14px">Markdown 预览</span>
        <el-button v-if="showPreview" link type="primary" size="small" @click.stop="loadPreview">刷新</el-button>
        <span class="muted" style="font-size: 12.5px">{{ showPreview ? '收起' : '展开' }}</span>
      </div>

      <div v-if="showPreview" style="margin-top: 12px">
        <div v-if="previewLoading" class="muted" style="font-size: 13px">加载中…</div>
        <el-alert
          v-else-if="previewError"
          type="error"
          :closable="false"
          show-icon
          :title="'预览加载失败：' + previewError"
        />
        <template v-else>
          <div class="preview-box">
            <MarkdownView :source="preview" />
          </div>
          <div v-if="previewTruncated" class="muted" style="font-size: 12.5px; margin-top: 6px">
            内容较长，这里只渲染开头部分；完整内容请下载 Markdown。
          </div>
        </template>
      </div>
    </div>
  </el-card>
</template>

<style scoped>
.preview-box {
  max-height: 70vh;
  overflow: auto;
  background: #fff;
  border: 1px solid var(--line);
  border-radius: 8px;
  padding: 18px 22px;
}
</style>
