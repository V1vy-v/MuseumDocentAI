<script setup lang="ts">
import { onBeforeUnmount, ref } from 'vue'
import { blobToWav } from '../utils/audio'

const props = defineProps<{
  streaming: boolean
  hint: string
}>()

const emit = defineEmits<{
  (e: 'send', text: string): void
  (e: 'voice', blob: Blob): void
  (e: 'stop'): void
}>()

const text = ref('')
const box = ref<HTMLTextAreaElement | null>(null)
const micOn = ref(false)
const localHint = ref('')
let recorder: MediaRecorder | null = null
let chunks: Blob[] = []
let stream: MediaStream | null = null

function autoGrow(): void {
  const el = box.value
  if (!el) return
  el.style.height = 'auto'
  el.style.height = `${Math.min(el.scrollHeight, 180)}px`
}

function submit(): void {
  const q = text.value.trim()
  if (!q || props.streaming) return
  text.value = ''
  autoGrow()
  emit('send', q)
}

function onKeydown(e: KeyboardEvent): void {
  // isComposing：中文输入法选词时的回车不能当发送，否则会打断选词
  if (e.key === 'Enter' && !e.shiftKey && !e.isComposing) {
    e.preventDefault()
    submit()
  }
}

function onSendClick(): void {
  if (props.streaming) emit('stop')
  else submit()
}

async function toggleMic(): Promise<void> {
  if (micOn.value) {
    recorder?.stop()
    return
  }
  if (props.streaming || !navigator.mediaDevices || !window.MediaRecorder) {
    localHint.value = '这个浏览器不支持录音，请用 Chrome / Edge，并通过 127.0.0.1 或 https 访问。'
    return
  }
  try {
    stream = await navigator.mediaDevices.getUserMedia({ audio: true })
  } catch (e) {
    localHint.value = `拿不到麦克风权限：${(e as Error).message}`
    return
  }

  chunks = []
  recorder = new MediaRecorder(stream)
  recorder.ondataavailable = (ev) => {
    if (ev.data && ev.data.size) chunks.push(ev.data)
  }
  recorder.onstop = async () => {
    micOn.value = false
    localHint.value = ''
    stream?.getTracks().forEach((t) => t.stop())
    const blob = new Blob(chunks, { type: chunks[0]?.type || 'audio/webm' })
    if (blob.size < 2000) {
      localHint.value = '录音太短，再说一次吧。'
      return
    }
    // 先转成 16k WAV 再上交，让后端拿到它认识的格式
    try {
      const wav = await blobToWav(blob)
      emit('voice', new Blob([wav], { type: 'audio/wav' }))
    } catch (e) {
      localHint.value = `音频处理失败：${(e as Error).message}`
    }
  }
  recorder.start()
  micOn.value = true
  localHint.value = '正在录音…再点一次结束并发送'
}

onBeforeUnmount(() => {
  stream?.getTracks().forEach((t) => t.stop())
})
</script>

<template>
  <div class="composer-wrap">
    <div class="composer">
      <button
        class="icon-btn mic"
        :class="{ rec: micOn }"
        :title="micOn ? '结束并发送' : '语音提问'"
        @click="toggleMic"
      >🎤</button>

      <textarea
        ref="box"
        v-model="text"
        rows="1"
        placeholder="问我关于博物馆、文物或参观的问题…"
        :disabled="streaming"
        @input="autoGrow"
        @keydown="onKeydown"
      ></textarea>

      <button
        class="send"
        :class="{ stop: streaming }"
        :title="streaming ? '停止生成' : '发送（Enter）'"
        :disabled="!streaming && !text.trim()"
        @click="onSendClick"
      >{{ streaming ? '■' : '↑' }}</button>
    </div>

    <div class="hint">
      {{ localHint || hint || (micOn ? '正在录音…' : 'Enter 发送 · Shift + Enter 换行 · 🎤 可语音提问') }}
    </div>
  </div>
</template>
