'use strict'

const { app, BrowserWindow, Menu, dialog, ipcMain, shell, session } = require('electron')
const { join } = require('node:path')
const { pathToFileURL } = require('node:url')
const { readFileSync, writeFileSync, renameSync } = require('node:fs')
const { serverOrigin, connectionTarget, sameOrigin, externalLink } = require('./policy.cjs')

app.setName('MAPLE Harness')
const connectionPage = pathToFileURL(join(__dirname, 'connection.html')).href
let launcher
let workspace
let config = { server: '', language: 'en' }
let quitting = false
const trustedCertificates = new Map()
const explorerWindows = new Set()

function openExplorer(url, origin) {
  const view = new BrowserWindow({
    width: 1340, height: 900, minWidth: 420, minHeight: 560, backgroundColor: '#ffffff',
    title: 'MAPLE | Solution Explorer',
    webPreferences: { contextIsolation: true, nodeIntegration: false, sandbox: true, partition: 'persist:maple-workspace' },
  })
  explorerWindows.add(view)
  view.on('closed', () => explorerWindows.delete(view))
  for (const eventName of ['will-navigate', 'will-redirect']) {
    view.webContents.on(eventName, (event, target) => { if (!sameOrigin(target, origin)) event.preventDefault() })
  }
  view.webContents.setWindowOpenHandler(() => ({ action: 'deny' }))
  view.webContents.on('will-attach-webview', event => event.preventDefault())
  view.loadURL(url).catch(error => { dialog.showErrorBox('MAPLE', error.message); view.destroy() })
}

function text(en, zh) { return config.language === 'zh' ? zh : en }
function save() {
  const path = join(app.getPath('userData'), 'connection.json')
  writeFileSync(`${path}.tmp`, JSON.stringify(config), { mode: 0o600 })
  renameSync(`${path}.tmp`, path)
}

function guardSender(event) {
  if (!launcher || event.sender !== launcher.webContents || event.senderFrame?.url !== connectionPage) {
    throw new Error('Connection settings are available only to the local connection window.')
  }
}

function connectionWindow() {
  if (launcher && !launcher.isDestroyed()) { launcher.show(); launcher.focus(); return }
  launcher = new BrowserWindow({
    width: 520, height: 490, minWidth: 380, minHeight: 430, backgroundColor: '#ffffff',
    title: 'MAPLE Harness', autoHideMenuBar: true,
    webPreferences: { preload: join(__dirname, 'preload.cjs'), contextIsolation: true, nodeIntegration: false, sandbox: true },
  })
  launcher.webContents.setWindowOpenHandler(() => ({ action: 'deny' }))
  launcher.webContents.on('will-navigate', event => event.preventDefault())
  launcher.on('closed', () => { launcher = undefined })
  launcher.loadURL(connectionPage)
}

function installMenu() {
  Menu.setApplicationMenu(Menu.buildFromTemplate([
    { label: 'MAPLE Harness', submenu: [
      { label: text('Server connection', '服务器连接'), click: connectionWindow },
      { label: text('Show workspace', '显示工作区'), click: () => workspace?.show() },
      { label: text('Reload', '重新加载'), click: () => workspace?.reload() },
      { label: text('Open in browser', '在浏览器中打开'), click: () => {
        if (config.server) shell.openExternal(config.server)
      } },
      { type: 'separator' },
      { label: text('About MAPLE Harness', '关于 MAPLE Harness'), click: () => dialog.showMessageBox({
        message: 'MAPLE Harness Desktop',
        detail: text('Remote client for MAPLE Harness, built on DeepSeek Harness. Optimization runs on the connected server.',
          'MAPLE Harness 的远程桌面客户端，应用基于 DeepSeek Harness。优化任务在所连接的服务器运行。'),
      }) },
      { label: text('Quit', '退出'), role: 'quit' },
    ] },
    { label: text('Edit', '编辑'), submenu: [{ role: 'undo' }, { role: 'redo' }, { type: 'separator' }, { role: 'cut' }, { role: 'copy' }, { role: 'paste' }, { role: 'selectAll' }] },
    { label: text('View', '视图'), submenu: [{ role: 'resetZoom' }, { role: 'zoomIn' }, { role: 'zoomOut' }, { role: 'togglefullscreen' }] },
  ]))
}

async function connect(value) {
  const { origin, url: launchUrl } = connectionTarget(value.server)
  config = { server: origin, language: value.language === 'zh' ? 'zh' : 'en' }
  if (workspace && !workspace.isDestroyed()) workspace.destroy()
  const current = new BrowserWindow({
    width: 1360, height: 900, minWidth: 760, minHeight: 560, backgroundColor: '#ffffff',
    title: 'MAPLE Harness',
    webPreferences: { contextIsolation: true, nodeIntegration: false, sandbox: true, partition: 'persist:maple-workspace' },
  })
  workspace = current
  current.webContents.on('will-navigate', (event, url) => {
    if (sameOrigin(url, origin)) return
    event.preventDefault()
    if (externalLink(url)) shell.openExternal(url)
  })
  current.webContents.on('will-redirect', (event, url) => {
    if (!sameOrigin(url, origin)) event.preventDefault()
  })
  current.webContents.setWindowOpenHandler(({ url }) => {
    if (sameOrigin(url, origin) && new URL(url).pathname.startsWith('/liveopt-api/explorer/')) openExplorer(url, origin)
    else if (sameOrigin(url, origin)) current.loadURL(url)
    else if (externalLink(url)) shell.openExternal(url)
    return { action: 'deny' }
  })
  current.webContents.on('will-attach-webview', event => event.preventDefault())
  current.on('closed', () => {
    if (workspace === current) workspace = undefined
    if (!quitting) connectionWindow()
  })
  installMenu()
  try {
    await current.loadURL(launchUrl)
    save()
    launcher?.hide()
    return { ok: true }
  } catch (error) {
    if (!current.isDestroyed()) current.destroy()
    connectionWindow()
    return { ok: false, error: String(error.message) }
  }
}

if (!app.requestSingleInstanceLock()) app.quit()
else {
  app.on('second-instance', () => { (workspace || launcher)?.show(); (workspace || launcher)?.focus() })
  app.on('before-quit', () => { quitting = true })
  app.on('window-all-closed', () => { if (process.platform !== 'darwin') app.quit() })
  app.on('activate', () => { if (!workspace && !launcher) connectionWindow(); else (workspace || launcher)?.show() })
  app.on('certificate-error', async (event, contents, url, error, certificate, callback) => {
    const trustedWindow = workspace && (contents === workspace.webContents || [...explorerWindows].some(view => contents === view.webContents))
    if (!trustedWindow || !sameOrigin(url, config.server)) return callback(false)
    event.preventDefault()
    const fingerprint = certificate.fingerprint256
    if (!fingerprint) return callback(false)
    if (trustedCertificates.get(config.server) === fingerprint) return callback(true)
    const result = await dialog.showMessageBox(workspace, {
      type: 'warning', defaultId: 0, cancelId: 0, noLink: true,
      buttons: [text('Cancel', '取消'), text('Trust for this launch', '仅本次启动信任')],
      message: text('The server certificate is not trusted.', '服务器证书不受信任。'),
      detail: `${config.server}\n${error}\nSHA-256: ${fingerprint}\n\n${text('Verify this fingerprint with your server administrator before continuing.', '请先向服务器管理员核对指纹，再继续连接。')}`,
    })
    if (result.response === 1) trustedCertificates.set(config.server, fingerprint)
    callback(result.response === 1)
  })
  app.whenReady().then(() => {
    try {
      const stored = JSON.parse(readFileSync(join(app.getPath('userData'), 'connection.json'), 'utf8'))
      config = { server: stored.server ? serverOrigin(stored.server) : '', language: stored.language === 'zh' ? 'zh' : 'en' }
    } catch {}
    const remote = session.fromPartition('persist:maple-workspace')
    remote.setPermissionRequestHandler((_contents, _permission, callback) => callback(false))
    remote.setPermissionCheckHandler(() => false)
    remote.on('will-download', (_event, item) => {
      item.setSaveDialogOptions({ title: text('Save optimization artifact', '保存优化产物') })
      item.once('done', (_event, state) => {
        if (state === 'interrupted' && !quitting) dialog.showErrorBox(text('Download interrupted', '下载中断'), item.getFilename())
      })
    })
    ipcMain.handle('maple:connection', event => { guardSender(event); return config })
    ipcMain.handle('maple:connect', async (event, value) => {
      guardSender(event)
      try { return await connect(value) } catch (error) { return { ok: false, error: String(error.message) } }
    })
    installMenu()
    connectionWindow()
  })
}
