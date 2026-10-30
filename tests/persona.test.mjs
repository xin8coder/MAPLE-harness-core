import assert from 'node:assert/strict'
import test from 'node:test'
import { readFileSync } from 'node:fs'
import { apply, mapleWorkflowInstruction } from '../dsh-bundle/index.js'

test('MAPLE workflow and skills are available without the coding persona', () => {
  const sections = []
  const skills = []
  apply({
    settings: { describe: () => [] },
    effect: (callback) => callback(),
    systemPrompt: { section: (value) => { sections.push(value) } },
    skills: { register: (value) => { skills.push(value); return () => {} } },
  })
  assert.deepEqual(skills.map(skill => skill.name), ['maple', 'maple-data', 'maple-results'])
  assert.equal(sections.find(section => section.name === 'maple:assistant-workflow').text, mapleWorkflowInstruction)
  assert.match(mapleWorkflowInstruction, /same|accepted session/)
  assert.match(mapleWorkflowInstruction, /Never invent completed runs/)
  assert.match(mapleWorkflowInstruction, /no assistant text in between/)
  assert.match(sections.find(section => section.name === 'maple:response-language').text(), /Simplified Chinese/)
})

test('saved standard sessions retain their id with only MAPLE tools enabled', () => {
  const patch = readFileSync(new URL('../dsh-bundle/cordis.patch.yml', import.meta.url), 'utf8')
  const preset = patch.split('- id: preset-standard\n')[1].split('\n- id: preset-ptc')[0]
  assert.match(preset, /id: standard/)
  assert.match(preset, /MAPLE/)
  assert.match(preset, /dsh-tool-ask-user/)
  assert.match(preset, /dsh-tool-skill/)
  assert.doesNotMatch(preset, /dsh-tool-(bash|pwsh|fs|subagent|web|workflow|goal)/)
  assert.doesNotMatch(preset, /dsh-agent-instructions|dsh-skill-filesystem/)
  assert.match(patch, /id: locale\n  config:\n    preference: zh/)
  assert.match(patch, /includeHarnessIdentity: false/)
})
