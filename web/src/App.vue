<script setup lang="ts">
import { computed, nextTick, onMounted, ref, watch } from 'vue'
import AppSidebar from './components/AppSidebar.vue'
import ChatMessage from './components/ChatMessage.vue'
import Composer from './components/Composer.vue'
import EmptyState from './components/EmptyState.vue'
import { chat, init, send, sendVoice, stop } from './stores/chat'

const LS_THEME = 'museum_chat_theme'
const dark = ref(localStorage.getItem(LS_THEME) === 'dark')
const sideOpen = ref(false)
const scroller = ref<HTMLElement | null>(null)

function applyTheme(): void {
  document.documentElement.dataset.theme = dark.value ? 'dark' : 'light'
  localStorage.setItem(LS_THEME, dark.value ? 'dark' : 'light')
}
applyTheme()

function toggleTheme(): void {
  dark.value = !dark.value
  applyTheme()
}

const title = computed(() => chat.title || '新对话')
const empty = computed(() => chat.messages.length === 0)

/* ---------- 滚动：只有用户本来就在底部时才自动跟随 ----------
 * 否则观众往上翻看历史时，新生成的字会把人拽回底部，非常烦。 */
let stick = true
function onScroll(): void {
  const el = scroller.value
  if (!el) return
  stick = el.scrollHeight - el.scrollTop - el.clientHeight < 80
}
function toBottom(): void {
  const el = scroller.value
  if (el) el.scrollTop = el.scrollHeight
}

watch(
  () => [chat.messages.length, chat.messages[chat.messages.length - 1]?.content?.length ?? 0],
  () => nextTick(() => { if (stick) toBottom() }),
)

watch(
  () => chat.currentId,
  () => nextTick(() => { stick = true; toBottom() }),
)

async function onPick(text: string): Promise<void> {
  await send(text)
}

function onNavigate(): void {
  sideOpen.value = false
}

onMounted(async () => {
  await init()
  await nextTick()
  toBottom()
})
</script>

<template>
  <div class="app">
    <AppSidebar
      :class="{ open: sideOpen }"
      :dark="dark"
      @toggle-theme="toggleTheme"
      @navigate="onNavigate"
    />
    <div class="scrim" :class="{ show: sideOpen }" @click="sideOpen = false"></div>

    <main class="main">
      <header class="topbar">
        <button class="icon-btn only-mobile" title="历史对话" @click="sideOpen = true">☰</button>
        <div class="title">{{ title }}</div>
        <div class="badge">回答附馆内资料来源</div>
      </header>

      <div ref="scroller" class="scroll" @scroll="onScroll">
        <div class="thread">
          <EmptyState v-if="empty" @pick="onPick" />
          <ChatMessage
            v-for="m in chat.messages"
            :key="m.id"
            :message="m"
          />
        </div>
      </div>

      <Composer
        :streaming="chat.streaming"
        :hint="chat.hint"
        @send="send"
        @voice="sendVoice"
        @stop="stop"
      />
    </main>
  </div>
</template>
