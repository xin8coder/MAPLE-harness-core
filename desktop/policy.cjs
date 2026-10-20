'use strict'

function serverOrigin(value) {
  const target = connectionTarget(value)
  if (target.url !== `${target.origin}/`) throw new Error('Enter only the server origin.')
  return target.origin
}

function connectionTarget(value) {
  const url = new URL(String(value).trim())
  const local = ['localhost', '127.0.0.1', '[::1]'].includes(url.hostname)
  if (url.protocol !== 'https:' && !(url.protocol === 'http:' && local)) {
    throw new Error('Use HTTPS, or HTTP on localhost.')
  }
  const params = [...url.searchParams]
  if (url.username || url.password || url.hash || url.pathname !== '/' ||
      (params.length > 0 && (params.length !== 1 || params[0][0] !== 'token' || !params[0][1]))) {
    throw new Error('Use the server origin or the launch link printed by MAPLE. Other paths and parameters are not supported.')
  }
  return { origin: url.origin, url: url.href }
}

function sameOrigin(url, origin) {
  try { return new URL(url).origin === origin } catch { return false }
}

function externalLink(value) {
  try {
    const url = new URL(value)
    return url.protocol === 'https:' && !url.username && !url.password
  } catch { return false }
}

module.exports = { serverOrigin, connectionTarget, sameOrigin, externalLink }
