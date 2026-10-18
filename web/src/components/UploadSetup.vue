<script setup>
// 上传后的提交区:确认文件清单,点「开始转换」提交到转换队列
import { ref, computed } from 'vue'
import { VideoPlay } from '@element-plus/icons-vue'
import { fmtBytes } from '../api'
import FileList from './FileList.vue'

const props = defineProps({
  jobs: { type: Array, default: () => [] },
  startError: { type: String, default: '' },
})
const emit = defineEmits(['start', 'cancel'])

const starting = ref(false)
const error = ref('')
// 引擎:MinerU 最好(文字层 + 公式/表格);另两个是 PaddleX 的备选
const pipeline = ref('MinerU')

const totalBytes = computed(() => props.jobs.reduce((a, j) => a + (j.src_bytes || 0), 0))
const totalPages = computed(() => props.jobs.reduce((a, j) => a + (j.page_count || 0), 0))

// 父组件回传的错误优先展示(它是真正失败的原因)
const shownError = computed(() => props.startError || error.value)

async function start() {
  starting.value = true
  error.value = ''
  try {
    await emit('start', { pipeline: pipeline.value })
  } catch (e) {
    error.value = e.message
  } finally {
    starting.value = false
  }
}
</script>

<template>
  <el-card shadow="never">
    <div style="display: flex; justify-content: space-between; align-items: center; gap: 12px; margin-bottom: 16px">
      <span style="font-weight: 600">
        {{ jobs.length }} 个文件
        <span class="muted" style="font-weight: 400; font-size: 13px">
          （{{ totalPages ? totalPages + ' 页 · ' : '' }}{{ fmtBytes(totalBytes) }}）
        </span>
      </span>
      <el-button text @click="emit('cancel')">换一批文件</el-button>
    </div>

    <FileList :jobs="jobs" />

    <el-form label-position="top" style="margin-bottom: 6px">
      <el-form-item label="识别管线">
        <el-radio-group v-model="pipeline">
          <el-radio-button value="MinerU">MinerU · 推荐</el-radio-button>
          <el-radio-button value="PP-StructureV3">PaddleX 标准 · 快</el-radio-button>
          <el-radio-button value="PaddleOCR-VL">PaddleX 精细</el-radio-button>
        </el-radio-group>
        <div class="muted" style="font-size: 12.5px; margin-top: 6px; width: 100%">
          <template v-if="pipeline === 'MinerU'">
            文字层 + 公式/表格识别:没有 OCR 错字,公式是干净 LaTeX;固定约 45 秒模型加载,之后约 1 秒/页。
          </template>
          <template v-else-if="pipeline === 'PP-StructureV3'">
            PaddleX 版面分析 + OCR:依赖少,约 10~20 秒/页,偶有英文错字。
          </template>
          <template v-else>
            PaddleX 的 VLM 管线:文字更干净,但约 30~40 秒/页。
          </template>
        </div>
      </el-form-item>
    </el-form>

    <el-alert type="info" :closable="false" show-icon style="margin-bottom: 18px">
      <template #title>
        版面分析 + 识别在 GPU 上跑，<b>同一时间只转换一个文档</b>（多个文件会排队）。
        约 10~20 秒/页，首次要多等约 30 秒加载模型。
      </template>
    </el-alert>

    <div style="display: flex; align-items: center; gap: 14px; flex-wrap: wrap">
      <el-button
        type="primary"
        size="large"
        :loading="starting"
        :icon="VideoPlay"
        @click="start"
      >
        开始转换{{ jobs.length > 1 ? `（${jobs.length} 个文件）` : '' }}
      </el-button>
      <span class="muted" style="font-size: 12.5px">
        产出 Markdown 正文（标题/段落/公式/表格）+ 原位置插图
      </span>
    </div>

    <el-alert
      v-if="shownError"
      type="error"
      :closable="false"
      show-icon
      style="margin-top: 14px"
      :title="'提交失败：' + shownError"
    />
  </el-card>
</template>
