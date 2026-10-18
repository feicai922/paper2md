<script setup>
// Markdown 渲染:标题/段落/表格/图片/代码,公式用 KaTeX。
//
// 为什么不用 <pre> 直接显示:后端产出的 md 带标题层级、HTML 表格、内联图片和
// LaTeX 公式,当纯文本看就是一堵墙 —— 这个组件负责把它们真正渲染出来。
import { computed } from 'vue'
import MarkdownIt from 'markdown-it'
import DOMPurify from 'dompurify'
import katex from 'katex'
import 'katex/dist/katex.min.css'

const props = defineProps({
  source: { type: String, default: '' },
})

const md = new MarkdownIt({ html: true, linkify: true })

// 先把公式换成占位符 → markdown-it 渲染 → 再换回 KaTeX HTML。
// 不这么做的话,$ 里的下划线/星号会被当成强调语法,公式就花了。
function protectMath(text) {
  const store = []
  const put = (tex, display) => {
    store.push({ tex, display })
    return `@@MATH${store.length - 1}@@`
  }
  let out = text.replace(/\$\$([\s\S]+?)\$\$/g, (_, tex) => put(tex.trim(), true))
  out = out.replace(/(^|[^\\$])\$([^$\n]+?)\$/g, (_, pre, tex) => pre + put(tex.trim(), false))
  return { out, store }
}

function renderMath({ tex, display }) {
  try {
    return katex.renderToString(tex, {
      displayMode: display,
      throwOnError: false,
      strict: 'ignore',
      output: 'html',
    })
  } catch {
    return `<code>${tex.replace(/[<>&]/g, '')}</code>`
  }
}

const html = computed(() => {
  if (!props.source) return ''
  const { out, store } = protectMath(props.source)
  let rendered = md.render(out)
  rendered = rendered.replace(/@@MATH(\d+)@@/g, (_, i) => {
    const item = store[Number(i)]
    return item ? renderMath(item) : ''
  })
  return DOMPurify.sanitize(rendered, { ADD_ATTR: ['target', 'align'] })
})
</script>

<template>
  <div class="md-body" v-html="html" />
</template>

<style scoped>
.md-body {
  font-size: 14px;
  line-height: 1.75;
  color: #1f2937;
  word-break: break-word;
}

.md-body :deep(h1) { font-size: 21px; margin: 24px 0 12px; line-height: 1.4; }
.md-body :deep(h2) { font-size: 18px; margin: 22px 0 10px; line-height: 1.45; }
.md-body :deep(h3) { font-size: 16px; margin: 20px 0 8px; line-height: 1.5; }
.md-body :deep(h4),
.md-body :deep(h5),
.md-body :deep(h6) { font-size: 15px; margin: 16px 0 8px; }

.md-body :deep(p) { margin: 10px 0; }
.md-body :deep(hr) {
  border: none;
  border-top: 1px dashed #d1d5db;
  margin: 22px 0;
}

.md-body :deep(img) {
  max-width: 100%;
  height: auto;
  display: block;
  margin: 10px auto;
}

.md-body :deep(div[style*="text-align: center"]) { margin: 8px 0; }

.md-body :deep(table) {
  border-collapse: collapse;
  margin: 14px auto;
  font-size: 13px;
  max-width: 100%;
  display: block;
  overflow-x: auto;
  white-space: normal;
}
.md-body :deep(table td),
.md-body :deep(table th) {
  border: 1px solid #d1d5db;
  padding: 5px 9px;
  vertical-align: top;
}
.md-body :deep(table th) { background: #f3f4f6; font-weight: 600; }

.md-body :deep(pre) {
  background: #f8fafc;
  border: 1px solid #e5e7eb;
  border-radius: 8px;
  padding: 12px 14px;
  overflow-x: auto;
  font-size: 12.5px;
}
.md-body :deep(code) {
  font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
  background: #f3f4f6;
  padding: 1px 4px;
  border-radius: 4px;
}
.md-body :deep(pre code) { background: none; padding: 0; }

.md-body :deep(blockquote) {
  margin: 12px 0;
  padding: 2px 14px;
  border-left: 3px solid var(--el-color-primary-light-5);
  color: #4b5563;
  background: #f9fafb;
}

.md-body :deep(a) { color: var(--el-color-primary); }

/* KaTeX 公式太宽时允许横向滚动,别撑破布局 */
.md-body :deep(.katex-display) {
  overflow-x: auto;
  overflow-y: hidden;
  padding: 4px 0;
}
</style>
