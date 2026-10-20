const { test } = require('node:test')
const assert = require('node:assert/strict')
const { serverOrigin, connectionTarget, sameOrigin, externalLink } = require('../policy.cjs')

test('HTTPS servers and local development endpoints are accepted', () => {
  assert.equal(serverOrigin('https://192.168.1.4:3000/'), 'https://192.168.1.4:3000')
  assert.equal(serverOrigin('http://127.0.0.1:3000'), 'http://127.0.0.1:3000')
  assert.equal(serverOrigin('http://[::1]:3000'), 'http://[::1]:3000')
})
test('remote plaintext, credential-bearing and non-web origins are rejected', () => {
  for (const input of ['http://192.168.1.4:3000', 'https://user:pass@server', 'file:///etc/passwd', 'javascript:alert(1)', 'https://host/path', 'https://host/?token=abc']) {
    assert.throws(() => serverOrigin(input))
  }
})
test('navigation and external links cannot escape to an OS protocol', () => {
  assert.equal(sameOrigin('https://server/api', 'https://server'), true)
  assert.equal(sameOrigin('https://server.attacker/api', 'https://server'), false)
  for (const value of ['file:///etc/passwd', 'shell:run', 'javascript:alert(1)', 'https://user:pass@host']) assert.equal(externalLink(value), false)
  assert.equal(externalLink('https://github.com/deepseek-ai/deepseek-harness'), true)
})

test('official launch links are accepted without persisting the token', () => {
  const result = connectionTarget('https://192.168.1.4:3000/?token=test-only')
  assert.equal(result.origin, 'https://192.168.1.4:3000')
  assert.equal(result.url, 'https://192.168.1.4:3000/?token=test-only')
  for (const value of ['https://host/?token=', 'https://host/?token=x&token=y', 'https://host/?redirect=evil', 'https://host/path?token=x']) {
    assert.throws(() => connectionTarget(value))
  }
})
