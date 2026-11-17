/**
 * 流式问答（POST /api/chat/stream，SSE over fetch）。
 *
 * 为什么不用 EventSource：EventSource 只能发 GET，没法带 JSON body，
 * 而这个接口需要传 { question, session_id }。所以用 fetch + ReadableStream 自己解析。
 *
 * 后端事件序列：meta（来源/消解结果）→ delta*（文本增量）→ done（含 usage）
 *              出错时发 error（此时响应头已发出，改不了状态码）
 */

import { jsonHeaders } from './client'

export interface StreamHandlers {
  onMeta?: (data: {
    session_id: string
    sources?: string[]
    sources_detail?: Array<{ title: string; heading?: string; url?: string; score?: number }>
    resolved?: string
  }) => void
  onDelta?: (text: string) => void
  onDone?: (data: { answer?: string; usage?: unknown }) => void
}

/** 解析一个 SSE 事件块 → [事件名, 数据] */
function parseBlock(block: string): Array<[string, any]> {
  let name = 'message'
  const dataLines: string[] = []
  for (const line of block.split('\n')) {
    if (line.startsWith('event:')) name = line.slice(6).trim()
    else if (line.startsWith('data:')) dataLines.push(line.slice(5).trim())
  }
  if (!dataLines.length) return []
  try {
    return [[name, JSON.parse(dataLines.join('\n'))]]
  } catch {
    return []
  }
}

export async function streamChat(opts: {
  question: string
  sessionId: string
  signal: AbortSignal
  handlers: StreamHandlers
}): Promise<string> {
  const { question, sessionId, signal, handlers } = opts

  const res = await fetch('/api/chat/stream', {
    method: 'POST',
    headers: jsonHeaders,
    body: JSON.stringify({ question, session_id: sessionId }),
    signal,
  })
  if (!res.ok || !res.body) {
    throw new Error(`HTTP ${res.status}`)
  }

  const reader = res.body.getReader()
  const decoder = new TextDecoder('utf-8')
  let buf = ''
  let answer = ''

  for (;;) {
    const { done, value } = await reader.read()
    if (done) break
    // stream: true 必须加：一个汉字可能被切在两个数据块之间，不加会解码成乱码
    buf += decoder.decode(value, { stream: true }).replace(/\r\n/g, '\n')

    let idx: number
    while ((idx = buf.indexOf('\n\n')) >= 0) {
      const block = buf.slice(0, idx)
      buf = buf.slice(idx + 2)
      for (const [name, data] of parseBlock(block)) {
        if (name === 'meta') handlers.onMeta?.(data)
        else if (name === 'delta') {
          answer += data.text ?? ''
          handlers.onDelta?.(data.text ?? '')
        } else if (name === 'done') {
          if (typeof data.answer === 'string' && data.answer) answer = data.answer
          handlers.onDone?.(data)
        } else if (name === 'error') {
          throw new Error(data.hint || data.error || '生成失败')
        }
      }
    }
  }

  if (!answer) throw new Error('没有收到回答，请重试')
  return answer
}
