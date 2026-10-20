import { request } from 'node:http'

export const name = 'maple-web-bridge'
export const inject = ['webServer', 'connection']

export function apply(ctx) {
  const target = new URL(process.env.LIVEOPT_WEB_API_URL || `http://127.0.0.1:${process.env.LIVEOPT_WEB_API_PORT || '8766'}`)
  if (target.protocol !== 'http:' || !['127.0.0.1', '[::1]', 'localhost'].includes(target.hostname) ||
      target.username || target.password || target.pathname !== '/' || target.search || target.hash) {
    throw new Error('The MAPLE sidecar endpoint must be a local HTTP service')
  }
  ctx.effect(() => ctx.webServer.register({
    kind: 'prefix',
    path: '/liveopt-api',
    handler(req, res) {
      const rejection = ctx.connection.requestRejection(req)
      if (rejection !== undefined) {
        res.writeHead(rejection)
        res.end(rejection === 401 ? 'unauthorized' : 'forbidden')
        return
      }
      const upstream = request({
        hostname: target.hostname.replace(/^\[|\]$/g, ''), port: target.port,
        path: req.url.slice('/liveopt-api'.length) || '/', method: req.method,
        headers: { ...req.headers, host: target.host },
      }, response => {
        const headers = { ...response.headers }
        delete headers['access-control-allow-origin']
        res.writeHead(response.statusCode || 502, headers)
        response.pipe(res)
      })
      upstream.on('error', () => {
        if (!res.headersSent) res.writeHead(502, { 'content-type': 'application/json' })
        res.end(JSON.stringify({ error: 'MAPLE application service is unavailable' }))
      })
      req.on('aborted', () => upstream.destroy())
      req.pipe(upstream)
    },
  }), 'maple: same-origin application routes')
  ctx.effect(() => ctx.webServer.tapIndex(html => html.replace('<title>DeepSeek Harness</title>', '<title>MAPLE Harness</title>')))
}
