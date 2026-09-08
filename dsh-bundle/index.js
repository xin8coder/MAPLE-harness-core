import { readFileSync } from 'node:fs'

export const name = 'liveopt-skill'
export const inject = ['skills']

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
  return skillDefinitions.map((definition) => ctx.skills.register({
    name: definition.name,
    description: definition.description,
    whenToUse: definition.whenToUse,
    source: 'bundled',
    content: bodyAfterFrontmatter(readFileSync(definition.path, 'utf8')).trim(),
    invocation: { modelInvocable: true, userInvocable: true },
  }))
}
