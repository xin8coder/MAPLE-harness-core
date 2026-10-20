'use strict'
const form = document.getElementById('connection')
const language = document.getElementById('language')
const button = document.getElementById('connect')
const status = document.getElementById('status')
let busy = false
function render() {
  const zh = language.value === 'zh'
  document.documentElement.lang = zh ? 'zh-CN' : 'en'
  document.getElementById('subtitle').textContent = zh ? '桌面客户端' : 'Desktop'
  document.getElementById('language-label').textContent = zh ? '启动窗口语言' : 'Launcher language'
  document.getElementById('server-label').textContent = zh ? '服务器地址或首次连接链接' : 'Server address or launch link'
  button.textContent = busy ? (zh ? '正在连接…' : 'Connecting...') : (zh ? '连接' : 'Connect')
  button.disabled = busy
}
language.addEventListener('change', render)
form.addEventListener('submit', async event => {
  event.preventDefault()
  busy = true; status.textContent = ''; render()
  try {
    const result = await window.mapleConnection.connect({ server: document.getElementById('server').value, language: language.value })
    if (!result.ok) status.textContent = result.error
  } catch (error) { status.textContent = error.message }
  finally { busy = false; render() }
})
window.mapleConnection.read().then(config => {
  document.getElementById('server').value = config.server || ''
  language.value = config.language || 'en'
  render()
}).catch(error => { status.textContent = error.message })
render()
