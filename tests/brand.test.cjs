const assert = require('node:assert/strict')
const { readFileSync } = require('node:fs')
const { join } = require('node:path')
const { runInNewContext } = require('node:vm')
const test = require('node:test')

const root = join(__dirname, '..')

test('web brand follows locale while retaining conversation titles and legacy interfaces', () => {
  let client
  let language = 'zh'
  const listeners = new Set()
  const disposers = []
  const locale = {
    getSnapshot: () => ({ active: language }),
    register: () => () => {},
    subscribe: callback => { listeners.add(callback); return () => listeners.delete(callback) },
  }
  const document = {
    title: 'Morning orders - MAPLE Harness',
    querySelector: () => true,
    querySelectorAll: () => [],
    createElement: () => ({ dataset: {} }),
    head: { appendChild: () => {} },
    documentElement: { style: {} },
  }
  runInNewContext(readFileSync(join(root, 'dsh-bundle/client.js'), 'utf8'), {
    window: {
      location: { hostname: 'ai.lanchou.cloud', protocol: 'https:' },
      __ModuleLoader__: { load: definition => { client = definition.factory(() => ({})) } },
    },
    document,
    MutationObserver: class { observe() {} disconnect() {} },
  })
  client.apply({
    get: name => name === 'locale' ? locale : { getTheme: () => ({ preference: 'light' }) },
    effect: (callback, label) => { if (label === 'liveopt: document brand') disposers.push(callback()) },
    on: () => {},
    slots: { inject: () => {} },
  })
  assert.equal(document.title, 'Morning orders - 澜筹')
  language = 'en'; listeners.forEach(callback => callback())
  assert.equal(document.title, 'Morning orders - lanchou')
  for (const oldBrand of ['DeepSeek Harness', 'LiveOpt Harness', 'MAPLE Harness']) {
    document.title = `Keep MAPLE in this request - ${oldBrand}`
    listeners.forEach(callback => callback())
    assert.equal(document.title, 'Keep MAPLE in this request - lanchou')
  }
  language = 'zh'; listeners.forEach(callback => callback())
  assert.equal(document.title, 'Keep MAPLE in this request - 澜筹')
  disposers.forEach(dispose => dispose())
  assert.equal(listeners.size, 0)
})

test('desktop rebranding preserves its existing profile and workspace partition', () => {
  let name, userData
  const source = readFileSync(join(root, 'desktop/main.cjs'), 'utf8')
  runInNewContext(source, {
    __dirname: join(root, 'desktop'),
    require: module => module === 'electron' ? { app: {
      getPath: () => '/profiles',
      setName: value => { name = value },
      setPath: (key, value) => { if (key === 'userData') userData = value },
      requestSingleInstanceLock: () => false,
      quit: () => {},
    } } : module === './policy.cjs' ? require('../desktop/policy.cjs') : require(module),
  })
  assert.equal(name, 'lanchou')
  assert.equal(userData, join('/profiles', 'MAPLE Harness'))
  assert.match(source, /partition: 'persist:maple-workspace'/)
  assert.match(source, /ipcMain.handle\('maple:connection'/)
})

test('application version and algorithm identity stay distinct', () => {
  const bundle = JSON.parse(readFileSync(join(root, 'dsh-bundle/package.json'), 'utf8'))
  const desktop = JSON.parse(readFileSync(join(root, 'desktop/package.json'), 'utf8'))
  const runtime = JSON.parse(readFileSync(join(root, 'runtime/package.json'), 'utf8'))
  const lock = JSON.parse(readFileSync(join(root, 'desktop/package-lock.json'), 'utf8'))
  assert.equal(desktop.version, bundle.version)
  assert.equal(runtime.version, bundle.version)
  assert.equal(lock.packages[''].version, bundle.version)
  const source = readFileSync(join(root, 'dsh-bundle/client.js'), 'utf8')
  assert.ok(source.includes(`const LIVEOPT_APP_VERSION = '${bundle.version}'`))
  assert.match(source, /t\('Algorithm'\).*'MAPLE'/)
  assert.equal(desktop.build.appId, 'org.maple.harness.desktop')
  assert.equal(desktop.build.productName, 'lanchou')
})
