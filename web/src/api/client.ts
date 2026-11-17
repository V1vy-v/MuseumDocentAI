/**
 * 后端请求的统一入口。
 *
 * 错误体约定（见 backend/docs/接口文档.md）：
 *   业务错误由 main.py 的异常处理器摊平成 { error, hint }
 *   但 FastAPI 自带的参数校验错误仍然是 { detail: [...] }
 * 两种都在这里归一成 ApiError，界面只拿 message 显示。
 */

export class ApiError extends Error {
  payload: unknown
  status: number

  constructor(message: string, status: number, payload: unknown) {
    super(message)
    this.name = 'ApiError'
    this.status = status
    this.payload = payload
  }
}

function pickMessage(data: any, status: number): string {
  if (data && typeof data === 'object') {
    if (typeof data.hint === 'string' && data.hint) return data.hint
    if (typeof data.error === 'string' && data.error) return data.error
    const d = data.detail
    if (typeof d === 'string' && d) return d
    if (d && typeof d === 'object') {
      if (typeof d.hint === 'string' && d.hint) return d.hint
      if (typeof d.error === 'string' && d.error) return d.error
    }
    if (Array.isArray(d) && d.length && d[0]?.msg) return String(d[0].msg)
  }
  return `HTTP ${status}`
}

export async function api<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(path, init)
  const text = await res.text()
  let data: any = {}
  try {
    data = text ? JSON.parse(text) : {}
  } catch {
    data = { _raw: text }
  }
  if (!res.ok) {
    throw new ApiError(pickMessage(data, res.status), res.status, data)
  }
  return data as T
}

export const jsonHeaders = { 'Content-Type': 'application/json; charset=utf-8' }
