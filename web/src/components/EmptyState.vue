<script setup lang="ts">
const emit = defineEmits<{ (e: 'pick', text: string): void }>()

const cards = [
  { q: '越王勾践剑是什么年代的？', sub: '从一件文物开始' },
  { q: '曾侯乙编钟有什么特别之处？', sub: '听一段讲解' },
  { q: '我想看青铜器，去哪几座博物馆比较好？', sub: '按兴趣找馆' },
  { q: '给我讲讲《清明上河图》', sub: '书画背后的故事' },
]
</script>

<template>
  <div class="hero">
    <h1>今天想了解点什么？</h1>
    <p>我掌握了一批国内博物馆与其馆藏文物的公开资料，回答会附上资料来源。</p>
    <div class="cards">
      <button v-for="c in cards" :key="c.q" class="card" @click="emit('pick', c.q)">
        {{ c.q }}
        <small>{{ c.sub }}</small>
      </button>
    </div>
  </div>
</template>
