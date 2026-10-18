// 后端 API 封装。所有组件只通过这里访问接口。

async function req(method, path, { json, form } = {}) {
  const opt = { method, headers: {} }
  if (json !== undefined) {
    opt.headers['Content-Type'] = 'application/json'
    opt.body = JSON.stringify(json)
  }
  if (form) opt.body = form
  const r = await fetch(path, opt)
  let data = null
  try { data = await r.json() } catch { /* 可能是空响应 */ }
  if (!r.ok) {
    const msg = (data && (data.detail || data.message)) || ('HTTP ' + r.status)
    throw new Error(typeof msg === 'string' ? msg : JSON.stringify(msg))
  }
  return data
}

export const api = {
  health: () => req('GET', '/health'),

  // 单文件
  uploadOne: (file) => {
    const fd = new FormData()
    fd.append('file', file)
    return req('POST', '/api/jobs', { form: fd })
  },

  // 批量:一次入库多个 PDF
  uploadBatch: (files) => {
    const fd = new FormData()
    files.forEach((f) => fd.append('files', f))
    return req('POST', '/api/batches', { form: fd })
  },

  startBatch: (batchId, payload = {}) => req('POST', `/api/batches/${batchId}/start`, { json: payload }),
  startOne: (jobId, payload = {}) => req('POST', `/api/jobs/${jobId}/start`, { json: payload }),

  jobs: () => req('GET', '/api/jobs'),
  job: (id) => req('GET', `/api/jobs/${id}`),
  cancel: (id) => req('POST', `/api/jobs/${id}/cancel`),
  remove: (id) => req('DELETE', `/api/jobs/${id}`),
  preview: (id) => req('GET', `/api/jobs/${id}/preview`),

  archive: () => req('GET', '/api/archive'),
}

export function fmtBytes(n) {
  if (n === null || n === undefined) return '—'
  const units = [['GB', 1073741824], ['MB', 1048576], ['KB', 1024]]
  for (const [k, d] of units) if (n >= d) return (n / d).toFixed(1) + ' ' + k
  return n + ' B'
}

export function fmtTime(ts) {
  if (!ts) return ''
  const d = new Date(ts * 1000)
  const p = (x) => String(x).padStart(2, '0')
  return `${p(d.getHours())}:${p(d.getMinutes())}`
}

// 产物 key → 界面文案
export const OUTPUT_LABEL = {
  markdown: 'Markdown 正文（.md）',
  md_zip: 'Markdown + 图片（ZIP）',
}

export const STATUS_TEXT = {
  uploaded: '待开始', queued: '排队中', running: '转换中',
  succeeded: '已完成', failed: '失败', canceled: '已取消',
}
export const STATUS_CLASS = {
  uploaded: '', queued: 'run', running: 'run',
  succeeded: 'ok', failed: 'err', canceled: '',
}
