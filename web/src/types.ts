/** 与后端 schemas 对应的数据类型（见 backend/app/schemas/session.py） */

export interface SessionSummary {
  session_id: string
  title: string
  created_at: string
  updated_at: string
  message_count: number
}

export interface SourceItem {
  title: string
  heading?: string
  url?: string
  score?: number
}

export interface MessageItem {
  role: 'user' | 'assistant'
  content: string
  sources?: string[]
  sources_detail?: SourceItem[]
  created_at?: string
  resolved?: string
  tokens?: number
}

export interface SessionMessages {
  session_id: string
  title: string
  summary: string
  created_at: string
  updated_at: string
  last_prompt_tokens: number
  messages: MessageItem[]
}

export interface IndexStats {
  ready: boolean
  dim: number
  collection: string
  error: string
  last_sync?: { files?: number; rebuilt?: number; chunks?: number }
}

export interface Health {
  status: string
  index: IndexStats
}

/** 界面里的一条消息（比后端多几个纯展示用的字段） */
export interface ChatMessage {
  id: string
  role: 'user' | 'assistant'
  content: string
  sources: SourceItem[]
  /** 正在流式接收 */
  streaming?: boolean
  /** 出错信息；有值时不渲染正文 */
  error?: string
  /** 是否来自语音提问（界面上加个 🎤 前缀） */
  voice?: boolean
  /** 是否已经定稿（定稿后才渲染 markdown，流式期间用纯文本避免反复重排） */
  done?: boolean
}
