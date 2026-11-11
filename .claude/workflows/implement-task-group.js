export const meta = {
  name: 'implement-task-group',
  description: 'Task manager / specialist developers / code reviewer: implement an OpenSpec task group or a GitHub issue as a PR in its own worktree, then handle CI and Copilot review comments until clean',
  whenToUse: 'Implement one task group of an OpenSpec change (mode "implement"), one GitHub issue (mode "issue"), or handle the CI and Copilot feedback of an existing PR (mode "review"). Roles live in .claude/agents/.',
  phases: [
    { title: 'Prepare', detail: 'task-manager creates the worktree and branch, gathers follow-ups, routes tasks' },
    { title: 'Implement', detail: 'backend-developer / frontend-developer / platform-engineer write code and tests' },
    { title: 'Review', detail: 'code-reviewer re-runs checks and reviews; loops back to the owning developer' },
    { title: 'Deliver', detail: 'task-manager files follow-ups, pushes and opens the PR' },
    { title: 'Copilot', detail: 'wait for CI + Copilot, triage, fix, reply, resolve, re-request' },
  ],
}

// args:
//   implement: { mode: 'implement', change, group, tasks, branch, devExtra?, extra? }
//   issue:     { mode: 'issue', issue, branch, devExtra?, extra? }
//   review:    { mode: 'review', pr, branch }
//   all:       main? - absolute path of the main checkout (default: the
//              current working directory). Work happens in a separate git
//              worktree per branch, created by the task-manager; root? may
//              point at an existing worktree (review mode) to skip that step.
const REPO = 'infonl/podiumd-admin-tool'
const A = args || {}
const MODE = A.mode || 'implement'
const CHANGE = A.change || 'add-foundation'
const BRANCH = A.branch
const MAIN = A.main || null
const MAX_REVIEW_ROUNDS = 4
const MAX_COPILOT_ROUNDS = 3
const DEV_ROLES = ['backend-developer', 'frontend-developer', 'platform-engineer']
if (!BRANCH) throw new Error('args.branch is required')
if (!['implement', 'issue', 'review'].includes(MODE)) throw new Error(`unknown mode ${MODE}`)
if (MODE === 'issue' && !A.issue) throw new Error('args.issue is required in issue mode')
if (MODE === 'review' && !A.pr) throw new Error('args.pr is required in review mode')

// The worktree every agent works in, once the task-manager has prepared it.
let WORK = A.root || null
const at = rel => (WORK ? `${WORK}/${rel}` : rel)
const role = name => `You are the ${name.toUpperCase()}. First read and follow your role definition in ${at(`.claude/agents/${name}.md`)}, and the repository rules in ${at('CLAUDE.md')} (developer roles: especially "Developer rules").`
const ctx = () => `Work ONLY in the git worktree ${WORK} (GitHub ${REPO}, branch ${BRANCH}). Never switch branches in the main checkout${MAIN ? ' ' + MAIN : ''}.`
const mainCtx = () => `Main checkout: ${MAIN || 'your current working directory'} (GitHub ${REPO}). Never switch its branch; create or reuse a separate worktree for ${BRANCH}.`

const DECISIONS = { type: 'array', description: 'design questions for the user that could not be settled within scope', items: { type: 'object', properties: {
  question: { type: 'string' }, options: { type: 'array', items: { type: 'string' } }, recommendation: { type: 'string' },
}, required: ['question', 'options', 'recommendation'] } }
const DEV = { type: 'object', properties: {
  summary: { type: 'string' },
  done: { type: 'array', items: { type: 'string' } },
  notDone: { type: 'array', items: { type: 'object', properties: { item: { type: 'string' }, reason: { type: 'string' } }, required: ['item', 'reason'] } },
  replies: { type: 'array', items: { type: 'object', properties: { id: { type: 'string' }, reply: { type: 'string' } }, required: ['id', 'reply'] } },
  checksPassed: { type: 'boolean' },
  commits: { type: 'array', items: { type: 'string' } },
  decisions: DECISIONS,
  handoff: { type: 'string', description: 'notes for the next developer role (e.g. changed API endpoints/models and openapi.json), or exact diffs for CLAUDE.md / .claude/** for the orchestrator' },
}, required: ['summary', 'done', 'notDone', 'replies', 'checksPassed', 'commits', 'decisions'] }
const REVIEW = { type: 'object', properties: {
  approved: { type: 'boolean' },
  checksRun: { type: 'array', items: { type: 'object', properties: { command: { type: 'string' }, passed: { type: 'boolean' }, exitCode: { type: 'integer' }, note: { type: 'string' } }, required: ['command', 'passed', 'note'] } },
  blocking: { type: 'array', items: { type: 'object', properties: { file: { type: 'string' }, issue: { type: 'string' }, fix: { type: 'string' }, owner: { type: 'string', enum: DEV_ROLES } }, required: ['file', 'issue', 'fix', 'owner'] } },
  suggestions: { type: 'array', items: { type: 'object', properties: { text: { type: 'string' }, later: { type: 'string', description: 'non-empty when this belongs to later work (e.g. "task group 6"): the task-manager files it as a follow-up issue' } }, required: ['text'] } },
  decisions: DECISIONS,
  summary: { type: 'string' },
}, required: ['approved', 'checksRun', 'blocking', 'suggestions', 'decisions', 'summary'] }
const PREPARE = { type: 'object', properties: {
  prepared: { type: 'boolean', description: 'true only when the worktree exists on the feature branch, created from (or in review mode tracking) origin' },
  worktree: { type: 'string', description: 'absolute path of the worktree' },
  assignments: { type: 'array', description: 'ordered work packages; cross-stack: backend first, then frontend, then platform', items: { type: 'object', properties: {
    role: { type: 'string', enum: DEV_ROLES },
    tasks: { type: 'string', description: 'the exact tasks / part of the issue for this role, quoted verbatim' },
    brief: { type: 'string', description: 'what already exists, related follow-ups (in scope / context only), hand-off expectations' },
  }, required: ['role', 'tasks', 'brief'] } },
  relatedFollowUps: { type: 'array', items: { type: 'string' } },
  reason: { type: 'string', description: 'why not prepared (empty when prepared)' },
}, required: ['prepared', 'worktree', 'assignments', 'relatedFollowUps', 'reason'] }
const DELIVERY = { type: 'object', properties: {
  created: { type: 'boolean', description: 'true only if gh pr create succeeded (or an open PR for this exact branch already exists)' },
  pr: { type: 'integer', description: 'the PR number; 0 when created is false' },
  url: { type: 'string' },
  headRefName: { type: 'string', description: "from 'gh pr view <pr> --json headRefName'" },
  followUpIssues: { type: 'array', items: { type: 'string' }, description: 'URLs of follow-up issues filed for deferred suggestions' },
  error: { type: 'string', description: 'what went wrong when created is false' },
}, required: ['created', 'pr', 'url', 'headRefName', 'followUpIssues'] }
const FEEDBACK = { type: 'object', properties: {
  pr: { type: 'integer' },
  headRefName: { type: 'string', description: "from 'gh pr view <pr> --json headRefName'" },
  headSha: { type: 'string' },
  ciPassed: { type: 'boolean', description: 'all required checks passed or were skipped' },
  ciSummary: { type: 'string' },
  ciOwner: { type: 'string', enum: [...DEV_ROLES, 'none'], description: 'when CI is red: the developer role whose area the failure is in (backend job -> backend-developer, frontend job -> frontend-developer, hygiene/CodeQL/workflow/infra -> platform-engineer)' },
  infraReruns: { type: 'array', items: { type: 'string' }, description: 'jobs re-run once because of an infrastructure error' },
  copilotReviewed: { type: 'boolean' },
  findings: { type: 'array', items: { type: 'object', properties: {
    id: { type: 'string', description: 'review thread id (PRRT_...) or "body:<short-slug>" for review-body findings' },
    kind: { type: 'string', enum: ['thread', 'body'] },
    path: { type: 'string' }, line: { type: 'integer' }, body: { type: 'string' },
  }, required: ['id', 'kind', 'path', 'body'] } },
}, required: ['pr', 'headRefName', 'headSha', 'ciPassed', 'ciSummary', 'ciOwner', 'infraReruns', 'copilotReviewed', 'findings'] }
const TRIAGE = { type: 'object', properties: {
  decisions: { type: 'array', items: { type: 'object', properties: {
    id: { type: 'string' },
    decision: { type: 'string', enum: ['fix', 'follow-up', 'decline'] },
    owner: { type: 'string', enum: [...DEV_ROLES, 'none'], description: 'for fix: the developer role whose area the code is in' },
    reason: { type: 'string' },
    expectedFix: { type: 'string', description: 'for fix: what to change and which test proves it' },
    issueTitle: { type: 'string' }, issueBody: { type: 'string' },
    reply: { type: 'string', description: 'text for the PR thread (decline/follow-up); for fix the developer supplies the final reply' },
  }, required: ['id', 'decision', 'owner', 'reason', 'reply'] } },
  summary: { type: 'string' },
}, required: ['decisions', 'summary'] }
const APPLY = { type: 'object', properties: {
  results: { type: 'array', items: { type: 'object', properties: {
    id: { type: 'string' },
    done: { type: 'boolean', description: 'true only when the reply/comment (and issue, for follow-up) exists and the thread is resolved' },
    link: { type: 'string', description: 'issue or comment URL, when there is one' },
    note: { type: 'string' },
  }, required: ['id', 'done', 'note'] } },
  summary: { type: 'string' },
}, required: ['results', 'summary'] }

const result = { mode: MODE, branch: BRANCH, decisions: [], handoffs: [] }
const addDecisions = (from, list) => { for (const d of list || []) result.decisions.push({ from, ...d }) }
// Keep every earlier reply whose id the newer report dropped.
const mergeReplies = (previous, current) => [...current, ...previous.filter(p => !current.some(c => c.id === p.id))]

// Developer -> reviewer loop for one developer role. Returns { dev, review, history }.
async function buildAndReview(devRole, devPrompt, scope, label, diffBase) {
  let dev = await agent(`${role(devRole)}\n${ctx()}\n${devPrompt}`, { label: `${devRole}:${label}`, phase: 'Implement', schema: DEV })
  if (!dev) throw new Error(`${devRole} failed`)
  const history = []
  let review = null
  for (let round = 1; round <= MAX_REVIEW_ROUNDS; round++) {
    review = await agent(`${role('code-reviewer')}\n${ctx()}\nReview the work of the ${devRole} on ${BRANCH}: ${diffBase}, plus anything uncommitted. Scope: ${scope}\nDeveloper report (round ${round}): ${JSON.stringify(dev)}\n${history.length ? 'Previous rounds: ' + JSON.stringify(history) : ''}`,
      { label: `code-reviewer:${label}-${round}`, phase: 'Review', schema: REVIEW })
    if (!review) throw new Error('code-reviewer failed')
    history.push({ round, approved: review.approved, blocking: review.blocking })
    log(`${label} (${devRole}) review round ${round}: ${review.approved ? 'APPROVED' : review.blocking.length + ' blocking'}`)
    if (review.approved || round === MAX_REVIEW_ROUNDS) break
    const previous = dev
    dev = await agent(`${role(devRole)}\n${ctx()}\nThe code-reviewer did not approve. Fix every blocking issue in your area, re-run all checks, commit locally (no push). For blocking issues owned by another role, explain in handoff exactly what that role must do. Return a reply for every finding id in the original assignment: carry over your previous replies and update them where this round changes them.\nORIGINAL ASSIGNMENT: ${devPrompt}\nPREVIOUS REPORT: ${JSON.stringify(previous)}\nREVIEW: ${JSON.stringify(review)}`,
      { label: `${devRole}:${label}-fix-${round}`, phase: 'Implement', schema: DEV })
    if (!dev) throw new Error(`${devRole} failed`)
    dev = { ...dev, replies: mergeReplies(previous.replies, dev.replies) }
  }
  addDecisions(devRole, dev.decisions)
  addDecisions('code-reviewer', review.decisions)
  if (dev.handoff) result.handoffs.push({ from: devRole, note: dev.handoff })
  return { dev, review, history }
}

// Runs the ordered assignments, passing hand-off notes forward.
async function runAssignments(assignments, extraScope, labelPrefix, diffBase) {
  const out = []
  let handoff = ''
  for (const [i, a] of assignments.entries()) {
    const scope = `${a.tasks}${extraScope ? '; additional in-scope work: ' + extraScope : ''}`
    const built = await buildAndReview(a.role, `Implement: ${scope}\nBrief from the task-manager:\n${a.brief}${handoff ? '\nHand-off from the previous developer role:\n' + handoff : ''}`, scope, `${labelPrefix}-${i + 1}`, diffBase)
    out.push({ role: a.role, tasks: a.tasks, approved: built.review.approved, rounds: built.history.length, review: built.review, dev: built.dev })
    handoff = built.dev.handoff || ''
    if (!built.review.approved) { log(`${a.role} work not approved; stopping before later assignments`); break }
  }
  return out
}

let pr = A.pr || null

// Prepare: worktree, follow-ups, routing (skipped in review mode when root is given).
phase('Prepare')
const what = MODE === 'implement'
  ? `task group ${A.group} (tasks ${A.tasks}) of openspec/changes/${CHANGE}/tasks.md`
  : MODE === 'issue' ? `GitHub issue #${A.issue} (read it with 'gh issue view ${A.issue} --comments')` : `the existing PR #${pr}`
if (!WORK || MODE !== 'review') {
  const prep = await agent(`${role('task-manager')}\n${mainCtx()}\nPrepare ${what}. ${MODE === 'review' ? `Reuse or add a worktree for the existing branch ${BRANCH} (tracking origin). Assignments may be empty.` : `Create a new worktree with branch ${BRANCH} from origin/main. Gather related follow-ups and route the work into ordered assignments for the developer roles (see "Route and brief" in your role).`}${A.devExtra ? `\nAdditional in-scope work from the orchestrator: ${A.devExtra}` : ''}\nSet prepared to true only when the worktree is ready on ${BRANCH}; otherwise false with the reason.`,
    { label: 'task-manager:prepare', phase: 'Prepare', schema: PREPARE })
  if (!prep) throw new Error('task-manager failed to prepare')
  if (prep.prepared !== true) throw new Error('task-manager did not prepare the worktree: ' + prep.reason)
  WORK = prep.worktree
  result.worktree = WORK
  result.relatedFollowUps = prep.relatedFollowUps
  log(`Worktree ${WORK}; ${prep.assignments.length} assignment(s): ${prep.assignments.map(a => a.role).join(' -> ') || 'none'}`)

  if (MODE !== 'review') {
    if (!prep.assignments.length) throw new Error('task-manager returned no assignments')
    const built = await runAssignments(prep.assignments, A.devExtra, MODE, `'git log origin/main..HEAD' and 'git diff origin/main...HEAD'`)
    result.implementation = built.map(b => ({ role: b.role, tasks: b.tasks, approved: b.approved, rounds: b.rounds }))
    const allApproved = built.length === prep.assignments.length && built.every(b => b.approved)

    phase('Deliver')
    const deferred = built.flatMap(b => b.review.suggestions.filter(s => s.later).map(s => ({ from: b.role, ...s })))
    const delivered = await agent(`${role('task-manager')}\n${ctx()}\nDeliver ${what}. All work approved: ${allApproved}. Per assignment: ${JSON.stringify(built.map(b => ({ role: b.role, tasks: b.tasks, approved: b.approved, rounds: b.rounds, review: b.review, dev: b.dev })))}.\nDecisions for the user so far: ${JSON.stringify(result.decisions)}\nDeferred suggestions to file as follow-up issues (label follow-up plus bug or enhancement): ${JSON.stringify(deferred)}${A.extra ? '\nExtra instructions: ' + A.extra : ''}\n${MODE === 'implement' ? 'Tick the completed, undisputed tasks in tasks.md and commit that. ' : `The PR body must say "Fixes #${A.issue}". `}File the follow-up issues, push ${BRANCH}, open the PR (draft if not all approved), with a "Decisions for you" section if there are decisions. Do not wait for CI or Copilot yet — the Copilot phase follows. After creating the PR, run 'gh pr view <number> --json headRefName,url' and report exactly what it returns. If anything failed, set created=false and explain in error; never guess a PR number.`,
      { label: 'task-manager:deliver', phase: 'Deliver', schema: DELIVERY })
    if (!delivered || delivered.created !== true) throw new Error('task-manager did not create the PR: ' + (delivered ? delivered.error || 'no error given' : 'no result'))
    if (!Number.isInteger(delivered.pr) || delivered.pr <= 0) throw new Error('task-manager returned an invalid PR number: ' + JSON.stringify(delivered))
    if (delivered.headRefName !== BRANCH) throw new Error(`PR #${delivered.pr} is for branch ${delivered.headRefName}, not ${BRANCH}; refusing to continue`)
    pr = delivered.pr
    result.prUrl = delivered.url
    result.followUpIssues = delivered.followUpIssues
    log(`PR #${pr} opened`)
  }
}
result.pr = pr

// Copilot / CI feedback loop
phase('Copilot')
const handled = []
// Findings whose reply, comment or issue the task-manager could not complete.
const unapplied = []
result.copilotRounds = []
let lastCiPassed = true
// True when commits were pushed after the last collection, so the last
// observed CI and Copilot status describe an older head.
let pushedSinceCollect = false
const collect = async label => {
  const fb = await agent(`${role('task-manager')}\n${ctx()}\nPR #${pr}. Make sure the worktree is on ${BRANCH} and up to date with origin. Wait (poll every ~30s, at most ~15 minutes) until (a) the required checks have finished (skipped counts as passing) and (b) the Copilot review of the current head SHA has been submitted (see "Copilot reviews" in your role). If a required job failed because of an infrastructure error, re-run it once and wait again (see "Infrastructure failures" in your role); never re-run code failures. Then return the CI result, the owner of any CI failure, and every Copilot finding that still needs handling: all UNRESOLVED review threads, plus review-body findings (e.g. "previously missed issues") that are not in this already-handled list: ${JSON.stringify(handled)}. Do not change anything else.`,
    { label, phase: 'Copilot', schema: FEEDBACK })
  if (!fb) throw new Error('task-manager failed to collect feedback')
  if (fb.pr !== pr || fb.headRefName !== BRANCH) throw new Error(`PR #${fb.pr} is for branch ${fb.headRefName}, expected #${pr} on ${BRANCH}; refusing to touch it`)
  pushedSinceCollect = false
  lastCiPassed = fb.ciPassed
  if (fb.infraReruns.length) (result.infraReruns = result.infraReruns || []).push(...fb.infraReruns)
  // Recompute on every collection: a later review of a newer head overrides
  // an earlier timeout (the earlier one stays visible in its round's note).
  result.copilotTimedOut = !fb.copilotReviewed
  return fb
}
const fixBase = `'git log origin/${BRANCH}..HEAD' and 'git diff origin/${BRANCH}...HEAD'`
for (let round = 1; round <= MAX_COPILOT_ROUNDS; round++) {
  const fb = await collect(`task-manager:collect-${round}`)
  log(`Copilot round ${round}: CI ${fb.ciPassed ? 'green' : 'RED'}, Copilot ${fb.copilotReviewed ? 'reviewed' : 'not reviewed'}, ${fb.findings.length} finding(s)`)
  const entry = { round, ci: fb.ciSummary, copilotReviewed: fb.copilotReviewed, findings: fb.findings.length }
  result.copilotRounds.push(entry)
  if (!fb.ciPassed) entry.note = 'CI failing — needs attention'
  if (!fb.copilotReviewed) {
    // A collector timeout is not a clean review: record it. With CI green and
    // nothing to handle, stop; with CI red, fall through to the CI repair.
    entry.note = `Copilot review of head ${fb.headSha} not received within the wait window (timeout)${fb.ciPassed ? '' : '; CI failing'}`
    if (!fb.findings.length && fb.ciPassed) break
  }
  if (fb.copilotReviewed && fb.ciPassed && !fb.findings.length) break
  if (!fb.findings.length && !fb.ciPassed) {
    // CI red without Copilot findings: the owning developer fixes CI.
    const owner = DEV_ROLES.includes(fb.ciOwner) ? fb.ciOwner : 'platform-engineer'
    const ci = await buildAndReview(owner, `CI on PR #${pr} is failing: ${fb.ciSummary}. You may not use 'gh' — the summary above is what you get; reproduce locally, fix the cause test-first, commit locally.`, `fix the failing CI on PR #${pr}`, `ci-${round}`, fixBase)
    entry.ciFix = { owner, approved: ci.review.approved }
    if (!ci.review.approved) break
    const pushed = await agent(`${role('task-manager')}\n${ctx()}\nPush the approved CI fix commits on ${BRANCH} for PR #${pr}. Request a new Copilot review. Do not merge.`, { label: `task-manager:push-ci-${round}`, phase: 'Copilot' })
    if (!pushed) throw new Error('task-manager failed to push the CI fix')
    pushedSinceCollect = true
    continue
  }

  const triage = await agent(`${role('code-reviewer')}\n${ctx()}\nTriage the Copilot findings on PR #${pr} (see "Triaging Copilot review comments" in your role). Read the code at the referenced locations on ${BRANCH} before deciding. One decision per finding id; for fix, name the owner role.\nFINDINGS: ${JSON.stringify(fb.findings)}`,
    { label: `code-reviewer:triage-${round}`, phase: 'Copilot', schema: TRIAGE })
  if (!triage) throw new Error('code-reviewer failed to triage')
  const fixes = triage.decisions.filter(d => d.decision === 'fix')
  entry.decisions = triage.decisions.map(d => ({ id: d.id, decision: d.decision, owner: d.owner, reason: d.reason }))
  log(`Triage: ${fixes.length} fix, ${triage.decisions.filter(d => d.decision === 'follow-up').length} follow-up, ${triage.decisions.filter(d => d.decision === 'decline').length} decline`)

  // Fixes per owning role, in the cross-stack order backend -> frontend -> platform.
  let replies = []
  let fixesApproved = true
  for (const owner of DEV_ROLES) {
    const mine = fixes.filter(f => (DEV_ROLES.includes(f.owner) ? f.owner : 'platform-engineer') === owner)
    if (!mine.length) continue
    const fixResult = await buildAndReview(owner, `Fix these Copilot findings on PR #${pr}, as triaged by the code-reviewer. Test-first: reproduce each with a failing test. Commit locally (no push). Give a PR-thread reply per finding id.\nFIXES: ${JSON.stringify(mine)}`,
      `the Copilot fixes listed for PR #${pr}: ${JSON.stringify(mine.map(f => ({ id: f.id, expectedFix: f.expectedFix })))}`, `copilot-${round}-${owner}`, fixBase)
    replies = replies.concat(fixResult.dev.replies)
    if (!fixResult.review.approved) { fixesApproved = false; break }
  }
  entry.fixApproved = fixesApproved
  if (!fixesApproved) {
    entry.note = 'Copilot fixes not approved by the code-reviewer; nothing pushed'
    break
  }

  const applied = await agent(`${role('task-manager')}\n${ctx()}\nApply the code-reviewer's triage of the Copilot findings on PR #${pr} (see "Copilot reviews" in your role):\n${fixes.length ? `1. Push the approved fix commits on ${BRANCH}.\n` : ''}2. For each decision: fix -> reply with the developer's reply (naming the commit) and resolve; follow-up -> create the GitHub issue (label follow-up plus bug or enhancement), reply with its link and resolve; decline -> reply with the reason and resolve. Review-body findings (id starts with "body:") have no thread: cover them in one PR comment.\n${fixes.length ? `3. Request a new Copilot review: gh pr edit ${pr} --add-reviewer @copilot\n` : ''}No @mentions. Do not merge. Return one result per finding id: done is true only when its reply/comment (and issue, for follow-up) actually exists and its thread is resolved; otherwise done is false with the error in note.\nTRIAGE: ${JSON.stringify(triage.decisions)}\nDEVELOPER REPLIES: ${JSON.stringify(replies)}`,
    { label: `task-manager:apply-${round}`, phase: 'Copilot', schema: APPLY })
  if (!applied) throw new Error('task-manager failed to apply the triage')
  entry.applied = applied
  if (fixes.length) pushedSinceCollect = true
  // Only mark findings handled once their replies/issues actually exist; the
  // rest are collected again (threads stay unresolved) and reported at handover.
  const doneIds = new Set(applied.results.filter(r => r.done === true).map(r => r.id))
  const summarize = f => ({ id: f.id, path: f.path, line: f.line, gist: f.body.slice(0, 120) })
  handled.push(...fb.findings.filter(f => doneIds.has(f.id)).map(summarize))
  for (const f of fb.findings.filter(f => !doneIds.has(f.id))) {
    const r = applied.results.find(x => x.id === f.id)
    const item = { ...summarize(f), note: r ? r.note : 'no result reported by the task-manager' }
    const i = unapplied.findIndex(u => u.id === f.id)
    if (i >= 0) unapplied[i] = item
    else unapplied.push(item)
  }
  // A later round may complete a finding that failed earlier.
  for (let i = unapplied.length - 1; i >= 0; i--) if (doneIds.has(unapplied[i].id)) unapplied.splice(i, 1)
  const failedHere = fb.findings.filter(f => !doneIds.has(f.id)).map(f => f.id)
  if (failedHere.length) entry.failed = unapplied.filter(u => failedHere.includes(u.id))
  // Nothing pushed and CI green: Copilot will not review again, so we are done.
  // With CI red, continue: the threads are resolved now, so the next round
  // collects no findings and takes the CI-repair branch.
  if (!fixes.length && fb.ciPassed) break
}
if (pushedSinceCollect) {
  // The round budget ran out right after a push: collect once more so the
  // handover reports the CI and Copilot status of the head actually on the PR.
  // Remaining findings are reported as outstanding, not triaged or fixed.
  const fb = await collect('task-manager:final-collect')
  log(`Final collection: CI ${fb.ciPassed ? 'green' : 'RED'}, Copilot ${fb.copilotReviewed ? 'reviewed' : 'not reviewed'}, ${fb.findings.length} outstanding finding(s)`)
  const entry = { round: 'final', ci: fb.ciSummary, copilotReviewed: fb.copilotReviewed, findings: fb.findings.length }
  if (!fb.ciPassed) entry.note = 'CI failing — needs attention'
  if (!fb.copilotReviewed) entry.note = `Copilot review of head ${fb.headSha} not received within the wait window (timeout)${fb.ciPassed ? '' : '; CI failing'}`
  if (fb.findings.length) {
    entry.outstanding = fb.findings.map(f => ({ id: f.id, path: f.path, line: f.line, gist: f.body.slice(0, 120) }))
    result.outstandingFindings = entry.outstanding
  }
  result.copilotRounds.push(entry)
}
if (unapplied.length) result.unappliedFindings = unapplied
if (!lastCiPassed) {
  // The loop ended (round budget exhausted or a fix not approved) while the
  // last observed CI run was red.
  const last = result.copilotRounds[result.copilotRounds.length - 1]
  last.note = `${last.note ? last.note + '; ' : ''}Copilot loop ended with CI still failing in the last observed run`
  result.ciStillFailing = true
}

const report = await agent(`${role('task-manager')}\n${ctx()}\nFinal hand-over for PR #${pr} (see "Hand over" in your role): confirm there are no unresolved review threads and report the required checks ('gh pr checks ${pr} --required'; note skipped ones). Leave the worktree ${WORK} in place. Return a concise message to the user. Start with "Decisions for you" if there are any: ${JSON.stringify(result.decisions)}. Then: PR URL, CI results, what happened with the Copilot findings (fixed / follow-up issues with links / declined), follow-up issues filed at delivery (${JSON.stringify(result.followUpIssues || [])}), hand-off notes that need the orchestrator (e.g. diffs for CLAUDE.md or .claude/**): ${JSON.stringify(result.handoffs)}, infrastructure re-runs (${JSON.stringify(result.infraReruns || [])}), and the worktree path. Ask them to review. Do not merge.${result.copilotTimedOut ? `\nIMPORTANT: the Copilot review was NOT received within the wait window (timeout). Tell the user the Copilot review is still outstanding and must be checked before merging.` : ''}${result.ciStillFailing ? `\nIMPORTANT: the Copilot loop ended while the last observed CI run was failing. Tell the user CI is red and needs attention.` : ''}${result.outstandingFindings ? `\nIMPORTANT: the Copilot round budget is exhausted and these findings on the final head were NOT handled: ${JSON.stringify(result.outstandingFindings)}. List them as outstanding for the user.` : ''}${result.unappliedFindings ? `\nIMPORTANT: the reply, comment or issue for these Copilot findings could NOT be applied: ${JSON.stringify(result.unappliedFindings)}. List them as outstanding for the user.` : ''}\nCopilot rounds: ${JSON.stringify(result.copilotRounds)}`,
  { label: 'task-manager:handover', phase: 'Copilot' })
result.handover = report
return result
