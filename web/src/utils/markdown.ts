/**
 * markdown 渲染：marked 解析 + DOMPurify 净化。
 *
 * 为什么要净化：模型输出是不可信文本，直接塞 innerHTML 会有 XSS 风险。
 * 讲解词一般不含 HTML，但资料片段里可能出现；宁可多净化一道。
 */

import { marked } from 'marked'
import DOMPurify from 'dompurify'

marked.setOptions({ gfm: true, breaks: true })

// 站内资料链接（/api/kb/...）和外部链接都在新标签页打开
DOMPurify.addHook('afterSanitizeAttributes', (node) => {
  if (node.tagName === 'A') {
    node.setAttribute('target', '_blank')
    node.setAttribute('rel', 'noopener noreferrer')
  }
})

export function renderMarkdown(src: string): string {
  const raw = marked.parse(src ?? '', { async: false }) as string
  return DOMPurify.sanitize(raw, { USE_PROFILES: { html: true } })
}
