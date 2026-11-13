// Static checks for the agent setup: the role files, the shared settings and
// the references the workflow script makes to them. Nothing here starts an agent.
//
// Run with: node --test ".claude/tests/*.test.mjs"   (or: check.sh hooks)
import assert from 'node:assert/strict'
import { readFileSync, readdirSync } from 'node:fs'
import { dirname, join } from 'node:path'
import { test } from 'node:test'
import { fileURLToPath } from 'node:url'

const claude = join(dirname(fileURLToPath(import.meta.url)), '..')
const read = (...parts) => readFileSync(join(claude, ...parts), 'utf8')

// ---------- role files (.claude/agents/*.md)

// The frontmatter fields Claude Code reads that this repository uses. A field
// outside this list is ignored by Claude Code without an error, so a typo such
// as `tool:` would silently give a role every tool.
const FIELDS = ['name', 'description', 'tools', 'model', 'effort']
const TOOLS = ['Bash', 'Read', 'Write', 'Edit', 'Grep', 'Glob']
const MODELS = /^(inherit|sonnet|opus|haiku|fable|claude-[a-z0-9-]+)$/
const EFFORTS = ['low', 'medium', 'high', 'xhigh', 'max']
const EDIT_TOOLS = ['Write', 'Edit', 'NotebookEdit']

function frontmatter(file) {
  const match = /^---\n([\s\S]*?)\n---\n/.exec(read('agents', file))
  assert.ok(match, `${file}: no frontmatter block`)
  const fields = {}
  for (const line of match[1].split('\n')) {
    const field = /^([A-Za-z]+):\s*(.*)$/.exec(line)
    assert.ok(field, `${file}: cannot read frontmatter line "${line}"`)
    assert.ok(!(field[1] in fields), `${file}: "${field[1]}" is set twice`)
    fields[field[1]] = field[2].trim()
  }
  return fields
}

const roleFiles = readdirSync(join(claude, 'agents')).filter(f => f.endsWith('.md'))
const roles = Object.fromEntries(roleFiles.map(f => [f.replace(/\.md$/, ''), frontmatter(f)]))
const toolsOf = role => roles[role].tools.split(',').map(t => t.trim())

test('every role file has valid frontmatter', () => {
  assert.ok(roleFiles.length > 0, 'no role files found')
  for (const [role, fields] of Object.entries(roles)) {
    for (const key of Object.keys(fields)) assert.ok(FIELDS.includes(key), `${role}: unknown frontmatter field "${key}"`)
    assert.equal(fields.name, role, `${role}: name must equal the file name`)
    assert.ok(fields.description, `${role}: description is empty`)
    // Without `tools` a role inherits every tool, so each role lists its own.
    assert.ok(fields.tools, `${role}: tools must be listed`)
    for (const tool of toolsOf(role)) assert.ok(TOOLS.includes(tool), `${role}: unknown tool "${tool}"`)
    assert.match(fields.model ?? '', MODELS, `${role}: model must be inherit, an alias or a full model id`)
    if ('effort' in fields) assert.ok(EFFORTS.includes(fields.effort), `${role}: unknown effort "${fields.effort}"`)
  }
})

test('the tool lists enforce what CLAUDE.md says each role never does', () => {
  // The code-reviewer never edits code.
  for (const tool of EDIT_TOOLS) assert.ok(!toolsOf('code-reviewer').includes(tool), `code-reviewer must not have ${tool}`)
  // The task-manager never writes production code: it may tick tasks.md (Edit), not create files.
  assert.ok(!toolsOf('task-manager').includes('Write'), 'task-manager must not have Write')
  // The developers write code and tests.
  for (const role of ['backend-developer', 'frontend-developer', 'platform-engineer']) {
    for (const tool of ['Write', 'Edit', 'Bash']) assert.ok(toolsOf(role).includes(tool), `${role} needs ${tool}`)
  }
})

// ---------- shared settings (.claude/settings.json)

const settings = JSON.parse(read('settings.json'))
const { allow = [], deny = [] } = settings.permissions ?? {}

// matches(rule, command): whether a Bash permission rule matches a command, as
// Claude Code documents it: `*` stands for any text, and a rule that ends in
// " *" as its only wildcard also matches the bare command.
function matches(rule, command) {
  const pattern = /^Bash\((.*)\)$/.exec(rule)?.[1]
  if (pattern === undefined) return false
  const escape = text => text.replace(/[.+?^${}()|[\]\\]/g, '\\$&')
  const soleTrailing = pattern.endsWith(' *') && pattern.indexOf('*') === pattern.length - 1
  const source = soleTrailing
    ? `${escape(pattern.slice(0, -2))}( .*)?`
    : pattern.split('*').map(escape).join('.*')
  return new RegExp(`^${source}$`).test(command)
}
const denied = command => deny.some(rule => matches(rule, command))
const allowed = command => !denied(command) && allow.some(rule => matches(rule, command))

test('settings.json holds well-formed permission rules', () => {
  assert.deepEqual(Object.keys(settings), ['permissions'], 'only permissions are shared; other settings stay personal')
  for (const rule of [...allow, ...deny]) {
    assert.equal(typeof rule, 'string')
    assert.match(rule, /^[A-Za-z_]+\(.+\)$/, `"${rule}" is not a Tool(pattern) rule`)
    // ":*" is only a wildcard at the very end of a pattern; elsewhere the colon is literal.
    assert.ok(!/:\*(?!\)$)/.test(rule), `"${rule}" uses ":*" before the end of the pattern`)
  }
  assert.equal(new Set(allow).size, allow.length, 'duplicate allow rule')
  assert.equal(new Set(deny).size, deny.length, 'duplicate deny rule')
})

test('the deny rules block merging, pushing to main and force-pushing', () => {
  const blocked = [
    'gh pr merge 31 --squash',
    'git push origin main',
    'git push -u origin main',
    'git push origin main --tags',
    'git push origin HEAD:main',
    'git push origin feat/x:main --tags',
    'git push --force origin feat/x',
    'git push --force-with-lease origin feat/x',
    'git push -f origin feat/x',
    'git push origin feat/x -f',
    'git -C /work/tree push origin main',
    'git -C /work/tree push origin HEAD:main',
    'git -C /work/tree push --force origin feat/x',
    'git -C /work/tree push -f origin feat/x',
  ]
  for (const command of blocked) assert.ok(denied(command), `not denied: ${command}`)
})

test('the deny rules leave ordinary work alone', () => {
  const free = [
    'git push -u origin feat/add-foundation-6',
    'git push origin feat/main-menu',
    'git -C /work/tree push -u origin chore/x',
    'gh pr create --fill',
    'gh pr view 31',
    'git commit -m "fix"',
  ]
  for (const command of free) assert.ok(!denied(command), `denied: ${command}`)
})

test('the shared allowlist is read-only', () => {
  // Pushing and writing to GitHub would be allowed for every role, so they stay in personal settings.
  const writes = [
    'git push -u origin feat/x',
    'git commit -m "fix"',
    'git worktree add ../x',
    'gh pr create --fill',
    'gh pr edit 31 --add-reviewer @copilot',
    'gh pr comment 31 --body hi',
    'gh issue create --title x',
    'gh api graphql -f query=x',
    'gh run rerun 1 --failed',
  ]
  for (const command of writes) assert.ok(!allowed(command), `the allowlist allows a write: ${command}`)
  for (const command of ['gh pr checks 31 --required', '.github/scripts/check.sh backend', 'git status --short']) {
    assert.ok(allowed(command), `the allowlist no longer allows: ${command}`)
  }
})

// ---------- the workflow script's references to the roles

const script = read('workflows', 'implement-task-group.js')
// One chunk per run(...) call: the role it starts and the prompt text up to the next call.
const calls = script.split(/\brun\(/).slice(1).map(chunk => ({ role: /^'([^']+)'/.exec(chunk)?.[1], text: chunk }))

test('the workflow only starts roles that exist', () => {
  const literal = calls.filter(c => c.role)
  assert.ok(literal.length > 0, 'no run(\'<role>\', ...) calls found')
  for (const { role } of literal) assert.ok(role in roles, `the workflow starts "${role}", which has no role file`)
  const devRoles = /const DEV_ROLES = \[([^\]]*)\]/.exec(script)
  assert.ok(devRoles, 'DEV_ROLES not found')
  for (const role of devRoles[1].split(',').map(r => r.trim().replace(/'/g, ''))) {
    assert.ok(role in roles, `DEV_ROLES names "${role}", which has no role file`)
  }
})

test('every role section a prompt points to exists in that role file', () => {
  let found = 0
  for (const { role, text } of calls.filter(c => c.role)) {
    for (const [, title] of text.matchAll(/"([^"]+)" in your role/g)) {
      found++
      const body = read('agents', `${role}.md`)
      const heading = new RegExp(`^#+ ${title}$`, 'm').test(body)
      const boldTerm = body.includes(`**${title}.**`) || body.includes(`**${title}**`)
      assert.ok(heading || boldTerm, `the workflow sends the ${role} to "${title}", which is not a heading or bold term in its role file`)
    }
  }
  assert.ok(found > 0, 'no "... in your role" references found; has the wording changed?')
})

test('every phase the workflow uses is declared in meta.phases', () => {
  const declared = [...script.matchAll(/\{ title: '([^']+)', detail:/g)].map(m => m[1])
  assert.ok(declared.length > 0, 'meta.phases not found')
  const used = [...script.matchAll(/phase: '([^']+)'/g), ...script.matchAll(/\bphase\('([^']+)'\)/g)].map(m => m[1])
  for (const title of used) assert.ok(declared.includes(title), `phase "${title}" is not declared in meta.phases`)
})
