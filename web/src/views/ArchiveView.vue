<script setup>
// 归档页:按日期分组的识别记录,支持搜索 / 下载 / 删除
import { ref, computed, onMounted } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { Search, Refresh, Delete, Download } from '@element-plus/icons-vue'
import { api, fmtBytes, fmtTime, OUTPUT_LABEL } from '../api'
import StatusPill from '../components/StatusPill.vue'

const data = ref(null)
const loading = ref(true)
const err = ref('')
const q = ref('')
const st = ref('')

const SHORT = { markdown: 'Markdown', md_zip: 'Markdown + 图片（ZIP）' }

function match(j) {
  if (st.value && j.status !== st.value) return false
  const needle = q.value.trim().toLowerCase()
  if (needle && !(j.filename || '').toLowerCase().includes(needle)) return false
  return true
}

const groups = computed(() => {
  if (!data.value?.dates) return []
  const out = []
  for (const d of data.value.dates) {
    const jobs = (d.jobs || []).filter(match)
    if (jobs.length) out.push({ date: d.date, count: jobs.length, jobs })
  }
  return out
})

const stats = computed(() => {
  const shown = groups.value.reduce((a, g) => a + g.count, 0)
  return { shown, days: groups.value.length }
})

// el-collapse 需要数组形式的 v-model
const opened = ref([])

async function load() {
  loading.value = true
  try {
    data.value = await api.archive()
    err.value = ''
    // 默认展开所有日期
    opened.value = (data.value.dates || []).map((d) => d.date)
  } catch (e) {
    err.value = e.message
  } finally {
    loading.value = false
  }
}

async function doDelete(id, name) {
  try {
    await ElMessageBox.confirm(
      `确定删除「${name}」？任务文件与产物会被一并删除，不可恢复。`,
      '删除记录',
      { confirmButtonText: '确认删除', cancelButtonText: '取消', type: 'warning' },
    )
  } catch { return }
  try {
    await api.remove(id)
    ElMessage.success('已删除')
    await load()
  } catch (e) {
    ElMessage.error('删除失败：' + e.message)
  }
}

function metaOf(j) {
  const m = []
  if (j.page_count) m.push(j.page_count + ' 页')
  if (j.src_bytes) m.push(fmtBytes(j.src_bytes))
  if (j.timings_text?.total) m.push('耗时 ' + j.timings_text.total)
  m.push(fmtTime(j.created_at))
  return m.join(' · ')
}

onMounted(load)
</script>

<template>
  <div>
    <el-alert
      v-if="err"
      type="error"
      :closable="false"
      show-icon
      style="margin-bottom: 16px"
      :title="'加载失败：' + err"
    />

    <el-card shadow="never">
      <div style="display: flex; gap: 10px; flex-wrap: wrap; margin-bottom: 16px">
        <el-input
          v-model="q"
          placeholder="搜索文件名…"
          :prefix-icon="Search"
          clearable
          style="flex: 1; min-width: 200px"
        />
        <el-select v-model="st" placeholder="全部状态" clearable style="width: 140px">
          <el-option value="succeeded" label="已完成" />
          <el-option value="running" label="识别中" />
          <el-option value="failed" label="失败" />
        </el-select>
        <el-button :icon="Refresh" @click="load">刷新</el-button>
      </div>

      <div class="stat-row">
        <span><b>{{ stats.shown }}</b> 条记录</span>
        <span><b>{{ stats.days }}</b> 个日期</span>
      </div>

      <el-skeleton v-if="loading" :rows="5" animated style="margin-top: 16px" />
      <el-empty v-else-if="!groups.length" description="没有匹配的记录" />

      <el-collapse v-else v-model="opened">
        <el-collapse-item v-for="g in groups" :key="g.date" :name="g.date">
          <template #title>
            <span style="font-weight: 600">{{ g.date }}</span>
            <span class="muted" style="margin-left: 10px; font-size: 12.5px">{{ g.count }} 条</span>
          </template>

          <div v-for="j in g.jobs" :key="j.job_id" class="file-item" style="align-items: flex-start">
            <div class="name">
              <div style="font-weight: 500; margin-bottom: 3px">{{ j.filename }}</div>
              <div class="muted" style="font-size: 12px">{{ metaOf(j) }}</div>

              <div style="margin-top: 8px; display: flex; gap: 8px; flex-wrap: wrap; align-items: center">
                <StatusPill :status="j.status" />
                <template v-if="j.status === 'succeeded'">
                  <el-button
                    v-for="(url, k) in j.downloads"
                    :key="k"
                    link
                    type="primary"
                    size="small"
                    :icon="Download"
                    tag="a"
                    :href="url"
                  >{{ SHORT[k] || OUTPUT_LABEL[k] || k }}</el-button>
                </template>
                <el-button
                  link
                  type="danger"
                  size="small"
                  :icon="Delete"
                  @click="doDelete(j.job_id, j.filename)"
                >删除</el-button>
              </div>
            </div>
          </div>
        </el-collapse-item>
      </el-collapse>
    </el-card>
  </div>
</template>

<style scoped>
:deep(.el-collapse-item__header) {
  font-size: 15px;
  gap: 10px;
}
</style>
