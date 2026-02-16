import { defineConfig, loadEnv } from 'vite'
import react from '@vitejs/plugin-react'

// https://vite.dev/config/
export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, process.cwd(), '')
  const host = env.VITE_DEV_HOST || '127.0.0.1'
  const apiProxyTarget = env.VITE_API_PROXY_TARGET || 'http://127.0.0.1:8050'

  return {
    plugins: [react()],
    server: {
      host,
      proxy: {
        '/api': apiProxyTarget,
      },
    },
  }
})
