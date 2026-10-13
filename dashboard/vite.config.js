import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// The dev server proxies to `server.mjs`, NOT directly to Traccar.
//
// It is tempting to point /api at Traccar here and skip the extra hop. Doing that
// would make development and production take different authentication paths: in
// production the tachograph API is reached through the proxy, which is the only
// place the service token exists. A dev setup that bypasses it would let a broken
// proxy ship undetected, because nothing in development would have used it.
//
// So: run `npm run serve` in one terminal and `npm run dev` in another. The dev
// server then exercises exactly the same server-side code the container does.
const PROXY_TARGET = process.env.DASHBOARD_PROXY_TARGET || 'http://127.0.0.1:8083'

export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      '/api': { target: PROXY_TARGET, changeOrigin: false },
      '/tacho': { target: PROXY_TARGET, changeOrigin: false },
    },
  },
})
