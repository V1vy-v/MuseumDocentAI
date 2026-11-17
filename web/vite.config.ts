import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'

// base 用相对路径：打包产物挂到 /app/ 或任意子路径都能正确加载资源。
// （如果写成 '/'，挂在 /app 下时 assets 会去根路径找，直接白屏。）
export default defineConfig({
  base: './',
  plugins: [vue()],
  server: {
    port: 5173,
    // 显式绑 IPv4：默认只监听 IPv6 的 ::1，导致浏览器打开 127.0.0.1:5173 连不上，
    // 看起来像"服务没起来"，很难排查。
    host: '127.0.0.1',
    strictPort: true,
    // 开发时把 /api 反代到本地后端，前端不用处理跨域
    proxy: {
      '/api': {
        target: 'http://127.0.0.1:8000',
        changeOrigin: true,
      },
    },
  },
  build: {
    outDir: 'dist',
    emptyOutDir: true,
    chunkSizeWarningLimit: 800,
  },
})
