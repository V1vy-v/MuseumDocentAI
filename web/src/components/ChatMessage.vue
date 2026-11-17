<script setup lang="ts">
import { computed, ref } from 'vue'
import { renderMarkdown } from '../utils/markdown'
import { speak } from '../stores/chat'
import type { ChatMessage } from '../types'

const props = defineProps<{ message: ChatMessage }>()

/* 流式期间用纯文本（快、不闪），定稿后再交给 markdown 排版 */
const html = computed(() => {
  if (!props.message.done || props.message.streaming) return ''
  return renderMarkdown(props.message.content || '')
})

const copied = ref(false)
async function copy(): Promise<void> {
  try {
    await navigator.clipboard.writeText(props.message.content || '')
    copied.value = true
  } catch {
    copied.value = false
  }
  window.setTimeout(() => { copied.value = false }, 1500)
}

const speakState = ref<'idle' | 'loading' | 'playing'>('idle')
let audio: HTMLAudioElement | null = null

async function toggleSpeak(): Promise<void> {
  if (speakState.value === 'playing') {
    audio?.pause()
    audio = null
    speakState.value = 'idle'
    return
  }
  speakState.value = 'loading'
  try {
    const el = await speak(props.message.content || '')
    if (!el) throw new Error('没有音频')
    audio = el
    speakState.value = 'playing'
    el.onended = () => {
      audio = null
      speakState.value = 'idle'
    }
  } catch {
    speakState.value = 'idle'
  }
}

function openSource(url?: string): { href: string; target: string; rel: string } | null {
  // 只放行站内资料路径，避免把后端返回的任意字符串当成链接
  return url && url.startsWith('/api/kb/')
    ? { href: url, target: '_blank', rel: 'noopener' }
    : null
}
</script>

<template>
  <div class="row" :class="[message.role, { err: !!message.error }]">
    <template v-if="message.role === 'user'">
      <div class="bubble">
        <span v-if="message.voice" class="mic-mark">🎤</span>{{ message.content }}
      </div>
    </template>

    <template v-else>
      <div class="avatar">🏛</div>
      <div class="bot-body">
        <div v-if="message.error" class="content rendered error-text">
          <p><strong>出错了：</strong>{{ message.error }}</p>
        </div>

        <div v-else-if="message.done && !message.streaming" class="content rendered" v-html="html"></div>

        <div v-else class="content">
          <span v-if="!message.content" class="thinking"><i></i><i></i><i></i></span>
          <template v-else>{{ message.content }}<span class="caret"></span></template>
        </div>

        <div v-if="message.sources.length || (message.done && message.content && !message.error)" class="tools">
          <template v-for="(s, i) in message.sources" :key="i">
            <a
              v-if="openSource(s.url)"
              class="chip"
              :href="openSource(s.url)!.href"
              :target="openSource(s.url)!.target"
              :rel="openSource(s.url)!.rel"
              :title="s.heading || s.title"
            >📄 {{ s.title }}</a>
            <span v-else class="chip plain" title="这条来源来自历史记录，原始链接不可用">📄 {{ s.title }}</span>
          </template>

          <template v-if="message.done && message.content && !message.error">
            <button class="act" @click="copy">{{ copied ? '已复制' : '复制' }}</button>
            <button class="act" @click="toggleSpeak">
              {{ speakState === 'loading' ? '合成中…' : speakState === 'playing' ? '⏹ 停止' : '🔊 朗读' }}
            </button>
          </template>
        </div>
      </div>
    </template>
  </div>
</template>
