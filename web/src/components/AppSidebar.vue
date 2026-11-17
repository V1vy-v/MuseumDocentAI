<script setup lang="ts">
import { computed, onBeforeUnmount, ref } from 'vue'
import {
  chat, filteredSessions, deleteSession, newChat, openSession,
} from '../stores/chat'
import { groupOf } from '../utils/format'
import type { SessionSummary } from '../types'

const emit = defineEmits<{
  (e: 'toggle-theme'): void
  (e: 'navigate'): void
}>()

defineProps<{ dark: boolean }>()

const GROUPS = ['今天', '昨天', '近 7 天', '更早'] as const

const grouped = computed(() => {
  const map = new Map<string, SessionSummary[]>()
  for (const s of filteredSessions.value) {
    const g = groupOf(s.updated_at || s.created_at)
    const list = map.get(g) || []
    list.push(s)
    map.set(g, list)
  }
  return GROUPS
    .filter((g) => map.has(g))
    .map((g) => ({ name: g, items: map.get(g)! }))
})

/* 两步确认删除：第一次点变成「确认」，3 秒内再点才真删。
 * 不用 confirm()：连续弹窗会被浏览器静默屏蔽，之后按钮彻底失效且没有报错。 */
const armedId = ref('')
let timer: number | undefined

function onDelete(id: string): void {
  if (armedId.value === id) {
    window.clearTimeout(timer)
    armedId.value = ''
    void deleteSession(id)
    return
  }
  armedId.value = id
  window.clearTimeout(timer)
  timer = window.setTimeout(() => { armedId.value = '' }, 3000)
}

onBeforeUnmount(() => window.clearTimeout(timer))

async function onOpen(id: string): Promise<void> {
  await openSession(id)
  emit('navigate')
}

function onCreate(): void {
  newChat()
  emit('navigate')
}
</script>

<template>
  <aside class="sidebar">
    <div class="side-head">
      <div class="brand"><span class="logo">🏛</span><span>博物馆讲解员</span></div>
      <button class="new-chat" @click="onCreate">＋ 新对话</button>
    </div>

    <div class="side-search">
      <input v-model="chat.search" type="search" placeholder="搜索对话" autocomplete="off" />
    </div>

    <div class="side-list">
      <p v-if="!grouped.length" class="side-empty">
        {{ chat.search ? '没有匹配的对话。' : '还没有对话记录。点上面的「新对话」开始。' }}
      </p>

      <template v-for="g in grouped" :key="g.name">
        <div class="side-group">{{ g.name }}</div>
        <div
          v-for="s in g.items"
          :key="s.session_id"
          class="sItem"
          :class="{ active: s.session_id === chat.currentId }"
          @click="onOpen(s.session_id)"
        >
          <div class="t" :title="`${s.title || '未命名对话'} · ${s.message_count} 条消息`">
            {{ s.title || '（未命名对话）' }}
          </div>
          <button
            class="del"
            :class="{ armed: armedId === s.session_id }"
            :title="armedId === s.session_id ? '再点一次确认删除' : '删除这个对话'"
            @click.stop="onDelete(s.session_id)"
          >{{ armedId === s.session_id ? '确认' : '✕' }}</button>
        </div>
      </template>
    </div>

    <div class="side-foot">
      <span
        class="dot"
        :class="chat.health ? (chat.health.index.ready ? 'ok' : 'warn') : 'bad'"
      ></span>
      <span class="status">
        {{ chat.health ? (chat.health.index.ready ? '服务正常 · 向量检索' : '关键词模式') : '连不上后端' }}
      </span>
      <span class="sp"></span>
      <a href="/debug" title="调试台（开发自测用）">调试台</a>
      <button class="icon-btn" :title="dark ? '切到浅色' : '切到深色'" @click="emit('toggle-theme')">
        {{ dark ? '☀️' : '🌙' }}
      </button>
    </div>
  </aside>
</template>
