import assert from 'node:assert/strict'
import test from 'node:test'
import { createRequire } from 'node:module'
import { resolve } from 'node:path'
import { pathToFileURL } from 'node:url'
import { apply } from '../dsh-bundle/index.js'

test('installed official DSH assembles the current language for each request', {
  skip: !process.env.DSH_NODE_MODULES,
}, async () => {
  const require = createRequire(resolve(process.env.DSH_NODE_MODULES, 'maple-test.cjs'))
  const { Context } = await import(pathToFileURL(require.resolve('@deepseek-ai/cordis')))
  const { SystemPrompt } = await import(pathToFileURL(require.resolve('@deepseek-ai/dsh-system-prompt')))
  const ctx = new Context()
  let preference = 'en'
  ctx.provide('settings', { describe: () => [{ ns: 'locale', value: { preference } }] })
  ctx.provide('skills', { register: () => () => {} })
  try {
    await ctx.plugin(SystemPrompt, {})
    apply(ctx)
    for (const language of ['en', 'zh', 'en']) {
      preference = language
      const assembly = await ctx.systemPrompt.assemble()
      const section = assembly.sections.find(item => item.name === 'maple:response-language')
      assert.match(section.text, language === 'zh' ? /Use Simplified Chinese/ : /Use English/)
    }
  } finally { await ctx.fiber.dispose() }
})
