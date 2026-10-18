<script setup>
import { computed } from 'vue'

const props = defineProps({
  progress: { type: Number, default: 0 },
  message: { type: String, default: '' },
  showPercent: { type: Boolean, default: true },
  // 后端还没给出真实百分比时用「不确定进度条」,别拿假百分比假装在走
  indeterminate: { type: Boolean, default: false },
})

const pct = computed(() => Math.round((props.progress || 0) * 100))
</script>

<template>
  <div>
    <el-progress
      :percentage="pct"
      :stroke-width="8"
      :show-text="false"
      :indeterminate="indeterminate"
      :color="pct >= 100 ? '#16a34a' : '#2563eb'"
    />
    <div class="meta">
      <span class="muted" style="font-size: 13px">{{ message || '—' }}</span>
      <span v-if="showPercent && !indeterminate" class="mono muted" style="font-size: 13px">{{ pct }}%</span>
      <span v-else-if="indeterminate" class="muted" style="font-size: 13px">识别中</span>
    </div>
  </div>
</template>

<style scoped>
.meta {
  display: flex;
  justify-content: space-between;
  gap: 12px;
  margin-top: 7px;
}
</style>
