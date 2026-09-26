import { fileURLToPath, URL } from 'node:url'
import react from '@vitejs/plugin-react'
import { defineConfig } from 'vitest/config'

// 빌드 결과는 저장소의 static/studio/ 로 — 8780 서버가 그대로 정적 제공한다(커밋 대상, 설계서 §11.1).
// base './' : 서버가 / 에서 주든 다른 경로에서 주든 자산 경로가 깨지지 않게 상대 경로로.
export default defineConfig({
  base: './',
  plugins: [react()],
  resolve: { alias: { '@': fileURLToPath(new URL('./src', import.meta.url)) } },
  build: {
    outDir: '../static/studio',
    emptyOutDir: true, // outDir 이 프로젝트 밖이라 명시해야 이전 빌드가 지워진다
    chunkSizeWarningLimit: 2000, // localhost 전용이라 antd·echarts 크기는 문제가 안 된다
    rollupOptions: {
      output: {
        manualChunks: (id: string) => {
          if (id.includes('node_modules/echarts') || id.includes('node_modules/zrender')) return 'echarts'
          if (id.includes('node_modules/antd') || id.includes('node_modules/@ant-design') || id.includes('node_modules/rc-'))
            return 'antd'
          return undefined
        },
      },
    },
  },
  test: {
    environment: 'jsdom',
    globals: true,
    setupFiles: ['./src/test/setup.tsx'],
    css: false,
    testTimeout: 30000, // antd 첫 렌더가 느린 PC(다른 작업과 CPU 경합)에서도 흔들리지 않게
  },
  server: {
    port: 5173,
    // 개발 중: 화면은 5173, API 는 8780 으로. 서버의 Origin 검사는 STUDIO_DEV_ORIGIN=http://localhost:5173 로 푼다.
    proxy: { '/api': 'http://127.0.0.1:8780' },
  },
})
