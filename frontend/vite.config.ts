/// <reference types="vitest" />
import { connect } from 'node:net'
import { defineConfig, type Plugin } from 'vite'
import react from '@vitejs/plugin-react'
import { resolveFallback } from './fallback/resolve'

const BACKEND = process.env.VITE_API_URL ?? 'http://localhost:8000'

/**
 * TEMPORARY: while nothing listens on the backend port, answer /api/* from fallback/api/ (marked
 * with X-Data-Source: fallback so the UI can say so). As soon as the backend is up, requests go
 * to the proxy below and the UI switches over by itself. VITE_API_FALLBACK=off disables it.
 * GET /api/__health is answered here: {"backend": true|false}.
 */
function apiFallback(target: string): Plugin {
  const { hostname, port } = new URL(target)
  let up = false
  let checkedAt = 0
  const probe = () =>
    new Promise<boolean>((resolve) => {
      const s = connect(Number(port) || 80, hostname)
      const done = (ok: boolean) => {
        s.destroy()
        resolve(ok)
      }
      s.setTimeout(400, () => done(false))
      s.once('connect', () => done(true))
      s.once('error', () => done(false))
    })
  const backendUp = async () => {
    if (Date.now() - checkedAt > 2000) {
      up = await probe()
      checkedAt = Date.now()
    }
    return up
  }
  return {
    name: 'api-fallback',
    apply: 'serve',
    configureServer(server) {
      // runs before Vite's own middlewares, so before the /api proxy
      server.middlewares.use(async (req, res, next) => {
        if (!req.url?.startsWith('/api/')) return next()
        if (req.url.startsWith('/api/__health')) {
          res.setHeader('Content-Type', 'application/json')
          return res.end(JSON.stringify({ backend: await backendUp() }))
        }
        if (await backendUp()) return next()
        const chunks: Buffer[] = []
        for await (const c of req) chunks.push(c as Buffer)
        let body: Record<string, unknown> | null = null
        try {
          body = chunks.length ? (JSON.parse(Buffer.concat(chunks).toString('utf8')) as Record<string, unknown>) : null
        } catch {
          body = null
        }
        const r = resolveFallback(req.method ?? 'GET', new URL(req.url, 'http://localhost'), body)
        if (!r) {
          res.writeHead(502, { 'Content-Type': 'text/plain', 'X-Data-Source': 'fallback' })
          return res.end('backend not reachable and no fallback data for this request')
        }
        res.writeHead(r.status, { 'Content-Type': r.contentType, 'X-Data-Source': 'fallback', ...r.headers })
        res.end(r.body)
      })
    },
  }
}

export default defineConfig({
  plugins: [react(), ...(process.env.VITE_API_FALLBACK === 'off' ? [] : [apiFallback(BACKEND)])],
  server: {
    port: 5173,
    strictPort: true,
    // The app only talks to the backend. In dev, /api is proxied to the FastAPI server.
    proxy: {
      '/api': {
        target: BACKEND,
        changeOrigin: true,
        // backend went away mid-request → 502 (the UI shows "backend isn't reachable"), not Vite's generic 500
        configure: (proxy) => {
          proxy.on('error', (_err, _req, res) => {
            if ('writeHead' in res && !res.headersSent) res.writeHead(502, { 'Content-Type': 'text/plain' }).end('backend not reachable')
          })
        },
      },
    },
  },
  build: {
    chunkSizeWarningLimit: 1200,
    rollupOptions: { output: { manualChunks: { echarts: ['echarts'] } } },
  },
  test: { include: ['src/**/*.test.ts'] },
})
