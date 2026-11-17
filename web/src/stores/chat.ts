/**
 * 会话与问答的全局状态。
 *
 * 只有一份实例（模块级 reactive），组件直接读写，不引入 pinia —— 这个应用的状态
 * 很浅，一层 reactive 足够，少一个依赖就少一处版本冲突。
 *
 * 一个容易踩的点：往 reactive 数组里 push 原始对象后，必须从数组里【读回来】
 * 再改字段。Vue 3 的响应式跟踪在 proxy 上，直接改原始对象不会触发视图更新。
 */

import { computed, reactive } from 'vue'
import { api, jsonHeaders } from '../api/client'
import { streamChat } from '../api/chat'
import { blobToWav, playBase64Wav } from '../utils/audio'
import { uid } from '../utils/format'
import type { ChatMessage, Health, SessionMessages, SessionSummary, SourceItem } from '../types'

const LS_SESSION = 'museum_chat_session_id'

export const chat = reactive({
  sessions: [] as SessionSummary[],
  currentId: '',
  title: '',
  messages: [] as ChatMessage[],
  streaming: false,
  health: null as Health | null,
  healthError: '',
  hint: '',
  search: '',
  loaded: false,
})

let abort: AbortController | null = null

export const filteredSessions = computed(() => {
  const kw = chat.search.trim().toLowerCase()
  if (!kw) return chat.sessions
  return chat.sessions.filter((s) => (s.title || '').toLowerCase().includes(kw))
})

export const indexReady = computed(() => !!chat.health?.index?.ready)

/* ---------------- 基础 ---------------- */

export async function checkHealth(): Promise<void> {
  try {
    chat.health = await api<Health>('/api/health')
    chat.healthError = ''
  } catch (e) {
    chat.health = null
    chat.healthError = (e as Error).message
  }
}

export async function refreshSessions(): Promise<void> {
  try {
    const data = await api<{ sessions: SessionSummary[]; count: number }>('/api/sessions?limit=50')
    chat.sessions = data.sessions || []
  } catch {
    // 列表刷新失败不该打断正在进行的对话，静默即可
  }
}

function setCurrent(id: string): void {
  chat.currentId = id
  if (id) localStorage.setItem(LS_SESSION, id)
  else localStorage.removeItem(LS_SESSION)
}

async function ensureSession(): Promise<string> {
  if (chat.currentId) return chat.currentId
  const data = await api<{ session_id: string }>('/api/sessions', { method: 'POST' })
  setCurrent(data.session_id)
  return chat.currentId
}

function toSources(m: { sources_detail?: SourceItem[]; sources?: string[] }): SourceItem[] {
  if (m.sources_detail && m.sources_detail.length) return m.sources_detail
  return (m.sources || []).map((t) => ({ title: t, heading: '', url: '' }))
}

/* ---------------- 会话 ---------------- */

export function newChat(): void {
  if (chat.streaming) return
  setCurrent('')
  chat.title = ''
  chat.messages = []
  chat.hint = ''
}

export async function openSession(id: string): Promise<void> {
  if (!id || chat.streaming) return
  setCurrent(id)
  chat.messages = []
  chat.hint = ''
  chat.title = ''
  try {
    const data = await api<SessionMessages>(`/api/sessions/${encodeURIComponent(id)}/messages`)
    chat.title = data.title || ''
    chat.messages = (data.messages || []).map((m) => ({
      id: uid(),
      role: m.role,
      content: m.content || '',
      sources: toSources(m),
      done: true,
      voice: m.role === 'user' && (m.content || '').startsWith('🎤'),
    }))
  } catch (e) {
    chat.messages = [
      { id: uid(), role: 'assistant', content: '', sources: [], done: true, error: (e as Error).message },
    ]
  }
}

export async function deleteSession(id: string): Promise<void> {
  try {
    await api(`/api/sessions/${encodeURIComponent(id)}`, { method: 'DELETE' })
  } catch {
    // 删除是幂等的，后端即使报错也按已删处理
  }
  if (id === chat.currentId) newChat()
  await refreshSessions()
}

/* ---------------- 问答 ---------------- */

export function stop(): void {
  abort?.abort()
}

export async function send(text: string): Promise<void> {
  const q = text.trim()
  if (!q || chat.streaming) return

  chat.streaming = true
  chat.hint = ''
  chat.messages.push({ id: uid(), role: 'user', content: q, sources: [], done: true })
  chat.messages.push({ id: uid(), role: 'assistant', content: '', sources: [], streaming: true })

  // 读回代理对象再改字段，否则改动不会触发渲染
  const bot = chat.messages[chat.messages.length - 1]
  abort = new AbortController()

  try {
    await ensureSession()
    const answer = await streamChat({
      question: q,
      sessionId: chat.currentId,
      signal: abort.signal,
      handlers: {
        onMeta: (d) => {
          // 来源在第一个字之前就到了，先显示出来，观众不用干等
          bot.sources = toSources(d)
        },
        onDelta: (t) => {
          bot.content += t
        },
        onDone: (d) => {
          if (d.answer) bot.content = d.answer
        },
      },
    })
    bot.content = answer
  } catch (e) {
    const err = e as Error
    if (err.name === 'AbortError') {
      if (!bot.content) bot.content = '（已停止生成）'
    } else {
      bot.error = err.message || String(e)
    }
  } finally {
    bot.streaming = false
    bot.done = true
    chat.streaming = false
    abort = null
    await refreshSessions()
  }
}

/** 语音提问：录音 → 16k WAV → /api/voice（识别 + 回答 + 播报一次完成） */
export async function sendVoice(blob: Blob): Promise<void> {
  if (chat.streaming) return
  chat.streaming = true
  chat.hint = '识别并生成中…'

  try {
    const wav = await blobToWav(blob)
    const fd = new FormData()
    fd.append('audio', new Blob([wav], { type: 'audio/wav' }), 'question.wav')
    fd.append('session_id', await ensureSession())

    const res = await fetch('/api/voice', { method: 'POST', body: fd })
    const text = await res.text()
    let data: any = {}
    try {
      data = text ? JSON.parse(text) : {}
    } catch {
      data = {}
    }
    if (!res.ok) throw new Error(data.hint || data.error || `HTTP ${res.status}`)

    chat.messages.push({
      id: uid(), role: 'user', content: data.question || '（没听清）',
      sources: [], done: true, voice: true,
    })
    chat.messages.push({
      id: uid(), role: 'assistant', content: data.answer || '',
      sources: toSources(data), done: true, voice: false,
    })
    playBase64Wav(data.audio_base64 || '')
    await refreshSessions()
  } catch (e) {
    chat.messages.push({
      id: uid(), role: 'assistant', content: '', sources: [],
      done: true, error: (e as Error).message,
    })
  } finally {
    chat.streaming = false
    chat.hint = ''
  }
}

/** 朗读一段回答（POST /api/tts） */
export async function speak(text: string): Promise<HTMLAudioElement | null> {
  const data = await api<{ audio_base64: string }>('/api/tts', {
    method: 'POST',
    headers: jsonHeaders,
    body: JSON.stringify({ text }),
  })
  if (!data.audio_base64) throw new Error('后端没有返回音频')
  return playBase64Wav(data.audio_base64)
}

/* ---------------- 启动 ---------------- */

export async function init(): Promise<void> {
  await checkHealth()
  await refreshSessions()

  const saved = localStorage.getItem(LS_SESSION) || ''
  if (saved && chat.sessions.some((s) => s.session_id === saved)) {
    await openSession(saved)
  } else {
    setCurrent('')
  }
  chat.loaded = true
}
