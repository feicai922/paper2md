<script setup>
// 拖拽上传区(支持多选)—— 用 Element Plus 图标,样式走全局 .drop-zone
import { ref } from 'vue'
import { UploadFilled } from '@element-plus/icons-vue'

const props = defineProps({
  multiple: { type: Boolean, default: true },
  disabled: { type: Boolean, default: false },
})
const emit = defineEmits(['files'])

const over = ref(false)
const input = ref(null)

function pick() {
  if (!props.disabled) input.value?.click()
}
function onChange(e) {
  const input = e.target
  const fs = Array.from(input.files || [])
  // 先取出文件再清空 input,且**清空放在异步里**:
  // 同步清空会在 emit 触发父组件上传前把 files 置空,某些浏览器下表现为
  // "选了文件但没反应"(实测踩过)。nextTick 后清空还能支持重复选同一个文件。
  if (fs.length) emit('files', fs)
  setTimeout(() => { try { input.value = '' } catch { /* 忽略 */ } }, 0)
}
function onDrop(e) {
  over.value = false
  if (props.disabled) return
  const fs = Array.from(e.dataTransfer?.files || []).filter((f) =>
    f.name.toLowerCase().endsWith('.pdf'),
  )
  if (fs.length) emit('files', fs)
}
</script>

<template>
  <div>
    <div
      class="drop-zone"
      :class="{ 'is-over': over, 'is-disabled': disabled }"
      @click="pick"
      @dragenter.prevent="over = true"
      @dragover.prevent="over = true"
      @dragleave.prevent="over = false"
      @drop.prevent="onDrop"
    >
      <el-icon :size="42" color="#93b4f5" style="margin-bottom: 10px">
        <UploadFilled />
      </el-icon>
      <div class="title">
        点击选择 或 拖拽 PDF 到此处
        <small v-if="multiple">（可多选，批量识别）</small>
      </div>
      <div class="desc">本地 PaddleOCR 识别，文件不出本机</div>
    </div>

    <input
      ref="input"
      type="file"
      accept="application/pdf"
      :multiple="multiple"
      style="display: none"
      @change="onChange"
    />
  </div>
</template>
