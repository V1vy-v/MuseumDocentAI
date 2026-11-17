/** 时间展示与会话分组 */

export function relTime(iso?: string): string {
  if (!iso) return ''
  const t = new Date(iso).getTime()
  if (Number.isNaN(t)) return ''
  const diff = (Date.now() - t) / 1000
  if (diff < 60) return '刚刚'
  if (diff < 3600) return `${Math.floor(diff / 60)} 分钟前`
  if (diff < 86400) return `${Math.floor(diff / 3600)} 小时前`
  if (diff < 86400 * 7) return `${Math.floor(diff / 86400)} 天前`
  const d = new Date(t)
  return `${d.getMonth() + 1}月${d.getDate()}日`
}

export type GroupName = '今天' | '昨天' | '近 7 天' | '更早'

/** 历史列表分组：今天 / 昨天 / 近 7 天 / 更早 */
export function groupOf(iso?: string): GroupName {
  const t = new Date(iso || 0).getTime()
  if (Number.isNaN(t)) return '更早'
  const now = new Date()
  const startToday = new Date(now.getFullYear(), now.getMonth(), now.getDate()).getTime()
  if (t >= startToday) return '今天'
  if (t >= startToday - 86400000) return '昨天'
  if (t >= startToday - 86400000 * 7) return '近 7 天'
  return '更早'
}

let seq = 0
export function uid(prefix = 'm'): string {
  seq += 1
  return `${prefix}-${Date.now().toString(36)}-${seq}`
}
