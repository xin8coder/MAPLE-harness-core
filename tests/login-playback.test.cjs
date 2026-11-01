const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const { test } = require('node:test');

const root = path.resolve(__dirname, '..');
const source = fs.readFileSync(path.join(root, 'deploy/sandbox/public/login.js'), 'utf8');
const fixture = JSON.parse(fs.readFileSync(path.join(root, 'deploy/sandbox/public/case-demo.json'), 'utf8'));

async function mount(reducedMotion = false) {
  const elements = new Map(), timers = new Map(), animations = [];
  const element = id => {
    if (elements.has(id)) return elements.get(id);
    const node = {
      dataset: {}, value: id === 'playback-speed' ? '3' : '', type: id === 'password' ? 'password' : '',
      attributes: {}, listeners: {}, children: [],
      setAttribute(name, value) { this.attributes[name] = value; },
      getAttribute(name) { return this.attributes[name]; },
      addEventListener(name, callback) { this.listeners[name] = callback; },
      replaceChildren(...nodes) { this.children = nodes; },
      appendChild(child) { this.children.push(child); child.onload?.(); },
      querySelector() { return element(id + '-label'); },
      animate(frames, options) {
        const animation = { options, cancelled: false, cancel() { this.cancelled = true; } };
        animations.push(animation);
        return animation;
      },
    };
    elements.set(id, node);
    return node;
  };
  const document = { getElementById: element, querySelectorAll: () => [],
    createElement: tag => element(tag + elements.size), head: element('head'), documentElement: { dataset: {} } };
  const Observer = class {
    constructor(callback) { this.callback = callback; }
    observe() { this.callback([{ isIntersecting: true }]); }
    disconnect() {}
  };
  let timerId = 0;
  const window = {
    matchMedia: () => ({ matches: reducedMotion }), addEventListener() {}, IntersectionObserver: Observer,
    lucide: { createIcons() {} }, echarts: { init: () => ({ on() {}, resize() {}, setOption() {} }) },
  };
  vm.runInNewContext(source, {
    document, window, Intl, ResizeObserver: class { observe() {} }, IntersectionObserver: Observer,
    requestAnimationFrame: callback => callback(),
    fetch: async () => ({ ok: true, json: async () => fixture }),
    setInterval(callback, delay) { const id = ++timerId; timers.set(id, { callback, delay }); return id; },
    clearInterval: id => timers.delete(id),
  });
  await new Promise(setImmediate);
  return { element, timers, animations };
}

test('recorded login playback defaults to three times the original speed', async () => {
  assert.ok(fs.readFileSync(path.join(root, 'deploy/sandbox/public/index.html'), 'utf8').includes('<option value="3" selected>'));
  const { element, timers, animations } = await mount();
  assert.equal(element('front-count').textContent, '8 个帕累托方案');
  assert.equal(timers.size, 1);
  assert.equal([...timers.values()][0].delay, 1400);
  assert.equal(animations[0].options.duration, 1400);
});

test('speed changes replace the timer without resuming a paused preview', async () => {
  const { element, timers, animations } = await mount();
  element('playback-speed').value = '2';
  element('playback-speed').listeners.change();
  assert.equal(timers.size, 1);
  assert.equal([...timers.values()][0].delay, 2100);
  assert.equal(animations[0].cancelled, true);
  element('playback').listeners.click();
  assert.equal(timers.size, 0);
  element('playback-speed').value = '1';
  element('playback-speed').listeners.change();
  assert.equal(timers.size, 0);
  element('playback').listeners.click();
  assert.equal([...timers.values()][0].delay, 4200);
});

test('reduced motion starts paused and does not animate the progress indicator', async () => {
  const { element, timers, animations } = await mount(true);
  assert.equal(timers.size, 0);
  assert.equal(element('playback').getAttribute('aria-label'), '播放回放');
  element('playback').listeners.click();
  assert.equal(timers.size, 1);
  assert.equal(animations.length, 0);
});
