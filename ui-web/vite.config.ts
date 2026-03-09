import { defineConfig, loadEnv } from 'vite'
import react from '@vitejs/plugin-react'

// https://vite.dev/config/
export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, process.cwd(), '')
  const host = env.VITE_DEV_HOST || '127.0.0.1'
  const apiProxyTarget = env.VITE_API_PROXY_TARGET || 'http://127.0.0.1:8050'

  return {
    plugins: [react()],
    build: {
      rollupOptions: {
        output: {
          manualChunks(id) {
            const normalized = id.replace(/\\/g, '/')
            if (normalized.includes('/src/features/process-governance/')) {
              return 'process-governance'
            }
            if (
              normalized.includes('/src/entities/governance/')
              || normalized.endsWith('/src/shared/api/processApi.ts')
            ) {
              return 'process-governance-data'
            }
            if (normalized.includes('/node_modules/react/')) {
              return 'react-vendor'
            }
            if (normalized.includes('/node_modules/react-dom/')) {
              return 'react-vendor'
            }
            if (normalized.includes('/node_modules/@mui/x-charts/')) {
              return 'mui-charts'
            }
            if (normalized.includes('/node_modules/@mui/x-data-grid/')) {
              return 'mui-data-grid'
            }
            if (normalized.includes('/node_modules/ag-grid-')) {
              return 'ag-grid'
            }
            if (
              normalized.includes('/node_modules/@mui/material/')
              || normalized.includes('/node_modules/@mui/icons-material/')
              || normalized.includes('/node_modules/@emotion/')
            ) {
              return 'mui-core'
            }
            return undefined
          },
        },
      },
    },
    server: {
      host,
      proxy: {
        '/api': apiProxyTarget,
      },
    },
  }
})
