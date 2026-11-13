import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'
import process from 'node:process'

export default defineConfig({
  base: process.env.VITE_APP_BASE || '/',
  plugins: [vue()],
  server: { proxy: { '/api': 'http://127.0.0.1:8091' } },
})
