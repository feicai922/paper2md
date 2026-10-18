<script setup>
import { computed } from 'vue'
import { STATUS_TEXT } from '../api'

const props = defineProps({
  status: { type: String, default: '' },
})

// Element Plus 的标签类型
const TYPE_MAP = {
  succeeded: 'success',
  failed: 'danger',
  running: 'primary',
  queued: 'info',
  canceled: 'info',
  uploaded: 'warning',
}

const text = computed(() => STATUS_TEXT[props.status] || props.status)
const type = computed(() => TYPE_MAP[props.status] || 'info')
const effect = computed(() =>
  props.status === 'running' || props.status === 'uploaded' ? 'light' : 'light',
)
</script>

<template>
  <el-tag :type="type" :effect="effect" size="small" disable-transitions>{{ text }}</el-tag>
</template>
