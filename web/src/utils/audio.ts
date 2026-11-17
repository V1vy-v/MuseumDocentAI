/**
 * 浏览器录音 → 16kHz 单声道 16bit WAV。
 *
 * 为什么要在前端转一道：MediaRecorder 录出来是 webm/opus，
 * 而后端的语音识别接口要 WAV。这里用 AudioContext 解码后下混、降采样，
 * 手写 WAV 头，不依赖任何第三方库。
 */

export async function blobToWav(blob: Blob): Promise<ArrayBuffer> {
  const Ctx = window.AudioContext || (window as any).webkitAudioContext
  const ctx: AudioContext = new Ctx()
  const decoded = await ctx.decodeAudioData(await blob.arrayBuffer())
  await ctx.close()

  const chCount = decoded.numberOfChannels
  const len = decoded.length
  const mono = new Float32Array(len)
  for (let c = 0; c < chCount; c++) {
    const ch = decoded.getChannelData(c)
    for (let i = 0; i < len; i++) mono[i] += ch[i] / chCount
  }

  const rate = 16000                        // 语音识别用 16k 足够，文件也小
  const ratio = decoded.sampleRate / rate
  const outLen = Math.max(1, Math.floor(len / ratio))
  const pcm = new Int16Array(outLen)
  for (let i = 0; i < outLen; i++) {
    let v = mono[Math.min(len - 1, Math.floor(i * ratio))]
    v = Math.max(-1, Math.min(1, v))
    pcm[i] = v < 0 ? v * 0x8000 : v * 0x7fff
  }
  return encodeWav(pcm, rate)
}

function encodeWav(pcm: Int16Array, rate: number): ArrayBuffer {
  const buf = new ArrayBuffer(44 + pcm.length * 2)
  const view = new DataView(buf)
  const str = (off: number, s: string) => {
    for (let i = 0; i < s.length; i++) view.setUint8(off + i, s.charCodeAt(i))
  }

  str(0, 'RIFF')
  view.setUint32(4, 36 + pcm.length * 2, true)
  str(8, 'WAVE')
  str(12, 'fmt ')
  view.setUint32(16, 16, true)
  view.setUint16(20, 1, true)               // PCM
  view.setUint16(22, 1, true)               // 单声道
  view.setUint32(24, rate, true)
  view.setUint32(28, rate * 2, true)        // 字节率 = 采样率 × 声道 × 位深/8
  view.setUint16(32, 2, true)               // 块对齐
  view.setUint16(34, 16, true)              // 16bit
  str(36, 'data')
  view.setUint32(40, pcm.length * 2, true)

  let off = 44
  for (let i = 0; i < pcm.length; i++, off += 2) view.setInt16(off, pcm[i], true)
  return buf
}

/** 播放 base64 WAV；被浏览器拦截自动播放时静默失败 */
export function playBase64Wav(b64: string): HTMLAudioElement | null {
  if (!b64) return null
  const audio = new Audio('data:audio/wav;base64,' + b64)
  audio.play().catch(() => {})
  return audio
}
