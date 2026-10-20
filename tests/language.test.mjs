import assert from 'node:assert/strict'
import test from 'node:test'
import { apply, responseLanguageInstruction } from '../dsh-bundle/index.js'

test('request language has priority and UI fallback is resolved on every model step', () => {
  let preference = 'en'
  let section
  const skills = []
  apply({
    settings: { describe: () => [{ ns: 'locale', value: { preference } }] },
    effect: (callback) => callback(),
    systemPrompt: { section: (value) => { section = value } },
    skills: { register: (skill) => { skills.push(skill); return () => {} } },
  })
  assert.equal(skills.length, 3)
  assert.match(section.text(), /Use English/)
  preference = 'zh'
  assert.match(section.text(), /Use Simplified Chinese/)
  preference = 'en'
  assert.match(section.text(), /Use English/)
  assert.doesNotMatch(section.text(), /Use Simplified Chinese/)
  assert.match(section.text(), /JSON keys/)
  assert.match(section.text(), /Remain silent/)
  assert.match(section.text(), /Chinese user input means Chinese replies/)
  assert.match(section.text(), /even if the UI is English/)
  assert.match(section.text(), /without requiring a language instruction/)
})

test('unknown locales and absent preferences cannot inject arbitrary instructions', () => {
  assert.match(responseLanguageInstruction(undefined), /latest request/)
  assert.match(responseLanguageInstruction('zh-CN'), /Simplified Chinese/)
  assert.doesNotMatch(responseLanguageInstruction('ignore-all-rules'), /ignore-all-rules/)
})
