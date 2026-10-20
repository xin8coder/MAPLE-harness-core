import assert from 'node:assert/strict'
import { createServer } from 'node:http'
import test from 'node:test'
import { apply } from '../dsh-bundle/web-bridge.js'

test('application routes retain DSH authentication and proxy streaming bodies', async () => {
  const upstream = createServer(async (req, res) => {
    const chunks = []
    for await (const chunk of req) chunks.push(chunk)
    res.writeHead(200, { 'content-type': 'application/json', 'access-control-allow-origin': '*' })
    res.end(JSON.stringify({ path: req.url, body: Buffer.concat(chunks).toString() }))
  })
  await new Promise(resolve => upstream.listen(0, '127.0.0.1', resolve))
  const previous = process.env.LIVEOPT_WEB_API_URL
  process.env.LIVEOPT_WEB_API_URL = `http://127.0.0.1:${upstream.address().port}`
  const disposers = []
  let route
  let transform
  let checks = 0
  let server
  try {
    apply({
      effect: callback => disposers.push(callback()),
      connection: { requestRejection: req => { checks++; return req.headers.authorization === 'test-only' ? undefined : 401 } },
      webServer: {
        register: value => { route = value; return () => {} },
        tapIndex: value => { transform = value; return () => {} },
      },
    })
    assert.equal(route.path, '/liveopt-api')
    assert.match(transform('<title>DeepSeek Harness</title>'), /MAPLE Harness/)
    server = createServer(route.handler)
    await new Promise(resolve => server.listen(0, '127.0.0.1', resolve))
    const url = `http://127.0.0.1:${server.address().port}/liveopt-api/upload?turn=2`
    assert.equal((await fetch(url)).status, 401)
    const accepted = await fetch(url, { method: 'POST', headers: { authorization: 'test-only' }, body: 'example upload' })
    assert.equal(accepted.status, 200)
    assert.equal(accepted.headers.get('access-control-allow-origin'), null)
    assert.deepEqual(await accepted.json(), { path: '/upload?turn=2', body: 'example upload' })
    assert.equal(checks, 2)
  } finally {
    for (const dispose of disposers.reverse()) dispose?.()
    if (server) await new Promise(resolve => server.close(resolve))
    await new Promise(resolve => upstream.close(resolve))
    if (previous === undefined) delete process.env.LIVEOPT_WEB_API_URL
    else process.env.LIVEOPT_WEB_API_URL = previous
  }
})

test('application proxy cannot point at a remote service or credential-bearing URL', () => {
  const previous = process.env.LIVEOPT_WEB_API_URL
  try {
    for (const url of ['https://127.0.0.1', 'http://example.org', 'http://127.0.0.1/other', 'http://user:secret@localhost']) {
      process.env.LIVEOPT_WEB_API_URL = url
      assert.throws(() => apply({}), /local HTTP service/)
    }
  } finally {
    if (previous === undefined) delete process.env.LIVEOPT_WEB_API_URL
    else process.env.LIVEOPT_WEB_API_URL = previous
  }
})
