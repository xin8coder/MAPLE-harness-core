import { readFileSync } from 'node:fs'

export const name = 'liveopt-skill'
export const inject = ['skills', 'systemPrompt', 'settings']

export function responseLanguageInstruction(preference) {
  const language = String(preference || '').toLowerCase().split('-')[0]
  const fallback = ['zh', 'en'].includes(language)
    ? `Use ${language === 'zh' ? 'Simplified Chinese' : 'English'} when the current request is language-neutral (for example, only a file or a number). `
    : 'For language-neutral requests, follow the recent user conversation or uploaded document language. '
  return 'Respond in the language of the user\'s latest request without requiring a language instruction. '
    + 'Chinese user input means Chinese replies, clarification questions, objective labels, and result summaries, even if the UI is English. '
    + 'English table keys, tool output, and quoted code do not change the conversation language. '
    + fallback
    + 'Keep code identifiers, tool names, JSON keys, file paths, and original data values unchanged. '
    + 'Honor explicit requests to translate or quote content in another language. '
    + 'Remain silent while the optimization progress component is active.'
}

const skillDefinitions = [
  {
    path: new URL('./skills/liveopt/SKILL.md', import.meta.url),
    name: 'liveopt',
    description: 'Solve a natural-language optimization problem once, then adapt its accepted state through later natural-language updates.',
    whenToUse: 'Use for exact, scalar evolutionary, or Pareto optimization that may receive later data, objective, or constraint updates.',
  },
  {
    path: new URL('./skills/liveopt-data/SKILL.md', import.meta.url),
    name: 'liveopt-data',
    description: 'Prepare uploaded documents or public tabular files as LiveOpt context without copying their contents into chat.',
    whenToUse: 'Use when optimization inputs come from browser uploads or CSV, TSV, JSON, JSONL, or XLSX workspace data.',
  },
  {
    path: new URL('./skills/liveopt-results/SKILL.md', import.meta.url),
    name: 'liveopt-results',
    description: 'Export and present accepted LiveOpt solutions and iteration history.',
    whenToUse: 'Use after a successful LiveOpt solve when the user wants CSV, JSON, ZIP, convergence, or solution-set output.',
  },
]

function bodyAfterFrontmatter(text) {
  if (!text.startsWith('---\n')) return text
  const end = text.indexOf('\n---\n', 4)
  return end < 0 ? text : text.slice(end + 5)
}

export function apply(ctx) {
  ctx.effect(() => ctx.systemPrompt.section({
    name: 'maple:response-language',
    order: 90,
    // Re-read the durable host preference on every model step, including tools.
    text: () => responseLanguageInstruction(ctx.settings.describe({ redactSecrets: true }).find(row => row.ns === 'locale')?.value?.preference),
  }), 'maple: response language')
  return skillDefinitions.map((definition) => ctx.skills.register({
    name: definition.name,
    description: definition.description,
    whenToUse: definition.whenToUse,
    source: 'bundled',
    content: bodyAfterFrontmatter(readFileSync(definition.path, 'utf8')).trim(),
    invocation: { modelInvocable: true, userInvocable: true },
  }))
}
