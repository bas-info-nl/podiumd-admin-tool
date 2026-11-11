export const meta = {
  name: 'implement-task-group',
  description: 'Task manager / specialist developers / code reviewer: implement an OpenSpec task group or a GitHub issue as a PR in its own worktree, then handle CI and Copilot review comments until clean',
  whenToUse: 'Implement one task group of an OpenSpec change (mode "implement"), one GitHub issue (mode "issue"), or handle the CI and Copilot feedback of an existing PR (mode "review"). Add resume: true to continue an interrupted implement/issue run. Roles live in .claude/agents/.',
  phases: [
    { title: 'Prepare', detail: 'task-manager creates (or resumes) the worktree and branch, gathers follow-ups, routes tasks' },
    { title: 'Implement', detail: 'backend-developer / frontend-developer / platform-engineer write code and tests' },
    { title: 'Review', detail: 'code-reviewer re-runs checks and reviews; blocking issues go to the owning role' },
    { title: 'Deliver', detail: 'task-manager files follow-ups, pushes and opens the PR' },
    { title: 'Copilot', detail: 'wait for CI + Copilot, triage, fix, reply, resolve, re-request' },
  ],
}

// args:
//   implement: { mode: 'implement', change, group, tasks, branch, devExtra?, extra?, resume? }
//   issue:     { mode: 'issue', issue, branch, devExtra?, extra?, resume? }
//   review:    { mode: 'review', pr, branch, root? }
//   all:       main? - absolute path of the main checkout (default: the
//              current working directory). Work happens in a separate git
//              worktree per branch, created by the task-manager; in review
//              mode root? may point at an existing worktree.
//   resume:    true continues an interrupted implement/issue run on the
//              existing branch and worktree, briefed from the commits made so far.
const REPO = 'infonl/podiumd-admin-tool'
const A = args || {}
const MODE = A.mode || 'implement'
const CHANGE = A.change || 'add-foundation'
const BRANCH = A.branch
const MAIN = A.main ? A.main.replace(/\/+$/, '') : null
const RESUME = A.resume === true
const MAX_REVIEW_ROUNDS = 4
const MAX_COPILOT_ROUNDS = 3
const MAX_INSERTED_PACKAGES = 3
const DEV_ROLES = ['backend-developer', 'frontend-developer', 'platform-engineer']
// 'orchestrator' owns CLAUDE.md and .claude/**: findings there become exact diffs for the main session.
const OWNERS = [...DEV_ROLES, 'orchestrator']
if (!BRANCH) throw new Error('args.branch is required')
if (!['implement', 'issue', 'review'].includes(MODE)) throw new Error(`unknown mode ${MODE}`)
if (MODE === 'issue' && !A.issue) throw new Error('args.issue is required in issue mode')
if (MODE === 'review' && !A.pr) throw new Error('args.pr is required in review mode')
if (A.root && (!A.root.startsWith('/') || (MAIN && A.root.replace(/\/+$/, '') === MAIN))) throw new Error('args.root must be an absolute worktree path, not the main checkout')

// The worktree every agent works in, once the task-manager has prepared it.
let WORK = A.root ? A.root.replace(/\/+$/, '') : null
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
  nextRole: { type: 'string', description: 'hand-off notes for the next developer role, e.g. changed API endpoints/models and the exported openapi.json' },
  orchestrator: { type: 'string', description: 'exact diffs for CLAUDE.md or .claude/** that the orchestrator must apply' },
}, required: ['summary', 'done', 'notDone', 'replies', 'checksPassed', 'commits', 'decisions'] }
const REVIEW = { type: 'object', properties: {
  approved: { type: 'boolean' },
  checksRun: { type: 'array', items: { type: 'object', properties: { command: { type: 'string' }, passed: { type: 'boolean' }, exitCode: { type: 'integer', description: '-1 when not applicable' }, note: { type: 'string' } }, required: ['command', 'passed', 'exitCode', 'note'] } },
  blocking: { type: 'array', items: { type: 'object', properties: { file: { type: 'string' }, issue: { type: 'string' }, fix: { type: 'string' }, owner: { type: 'string', enum: OWNERS } }, required: ['file', 'issue', 'fix', 'owner'] } },
  suggestions: { type: 'array', items: { type: 'object', properties: { text: { type: 'string' }, later: { type: 'string', description: 'non-empty when this belongs to later work (e.g. "task group 6"): it is filed as a follow-up issue' } }, required: ['text'] } },
  decisions: DECISIONS,
  summary: { type: 'string' },
}, required: ['approved', 'checksRun', 'blocking', 'suggestions', 'decisions', 'summary'] }
const PREPARE = { type: 'object', properties: {
  prepared: { type: 'boolean', description: 'true only when the worktree exists on the feature branch, created from (or, in review/resume mode, tracking) origin' },
  worktree: { type: 'string', description: 'absolute path of the worktree' },
  branch: { type: 'string', description: "output of 'git -C <worktree> branch --show-current'" },
  linkedWorktree: { type: 'boolean', description: "true only when <worktree> is a linked worktree, not the main checkout: [ \"$(git -C <worktree> rev-parse --absolute-git-dir)\" != \"$(cd <worktree> && cd \"$(git rev-parse --git-common-dir)\" && pwd -P)\" ]" },
  mainCheckout: { type: 'string', description: "output of 'git rev-parse --show-toplevel' in the main checkout" },
  assignments: { type: 'array', description: 'ordered work packages; cross-stack: backend first, then frontend, then platform', items: { type: 'object', properties: {
    role: { type: 'string', enum: DEV_ROLES },
    tasks: { type: 'string', description: 'the exact tasks / part of the issue for this role, quoted verbatim' },
    brief: { type: 'string', description: 'what already exists (in resume mode: what the commits so far already did), related follow-ups (in scope / context only), hand-off expectations' },
  }, required: ['role', 'tasks', 'brief'] } },
  relatedFollowUps: { type: 'array', items: { type: 'string' } },
  reason: { type: 'string', description: 'why not prepared (empty when prepared)' },
}, required: ['prepared', 'worktree', 'branch', 'linkedWorktree', 'mainCheckout', 'assignments', 'relatedFollowUps', 'reason'] }
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
  localBranch: { type: 'string', description: "output of 'git -C <worktree> branch --show-current'" },
  linkedWorktree: { type: 'boolean', description: "true only when <worktree> is a linked worktree, not the main checkout: [ \"$(git -C <worktree> rev-parse --absolute-git-dir)\" != \"$(cd <worktree> && cd \"$(git rev-parse --git-common-dir)\" && pwd -P)\" ]" },
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
}, required: ['pr', 'headRefName', 'localBranch', 'linkedWorktree', 'headSha', 'ciPassed', 'ciSummary', 'ciOwner', 'infraReruns', 'copilotReviewed', 'findings'] }
const TRIAGE = { type: 'object', properties: {
  decisions: { type: 'array', items: { type: 'object', properties: {
    id: { type: 'string' },
    decision: { type: 'string', enum: ['fix', 'follow-up', 'decline'] },
    owner: { type: 'string', enum: [...OWNERS, 'none'], description: 'for fix: the role whose area the code is in (orchestrator for CLAUDE.md and .claude/**)' },
    reason: { type: 'string' },
    expectedFix: { type: 'string', description: 'for fix: what to change and which test proves it (for orchestrator: the exact diff)' },
    issueTitle: { type: 'string' }, issueBody: { type: 'string' },
    reply: { type: 'string', description: 'text for the PR thread (decline/follow-up); for fix the developer supplies the final reply' },
  }, required: ['id', 'decision', 'owner', 'reason', 'reply'] } },
  userDecisions: DECISIONS,
  summary: { type: 'string' },
}, required: ['decisions', 'userDecisions', 'summary'] }
const APPLY = { type: 'object', properties: {
  results: { type: 'array', items: { type: 'object', properties: {
    id: { type: 'string' },
    done: { type: 'boolean', description: 'true only when the reply/comment (and issue, for follow-up) exists and the thread is resolved' },
    link: { type: 'string', description: 'issue or comment URL, when there is one' },
    note: { type: 'string' },
  }, required: ['id', 'done', 'note'] } },
  summary: { type: 'string' },
}, required: ['results', 'summary'] }

const result = { mode: MODE, branch: BRANCH, resume: RESUME, decisions: [], deferred: [], orchestrator: [], unrouted: [] }
const keyOf = s => String(s || '').trim().toLowerCase()
const addDecisions = (from, list) => {
  for (const d of list || []) if (!result.decisions.some(x => keyOf(x.question) === keyOf(d.question))) result.decisions.push({ from, ...d })
}
const addDeferred = (from, review) => {
  for (const s of (review && review.suggestions) || []) if (s.later && !result.deferred.some(x => keyOf(x.text) === keyOf(s.text))) result.deferred.push({ from, ...s })
}
const addOrchestrator = (from, note) => {
  if (note && !result.orchestrator.some(x => keyOf(x.note) === keyOf(note))) result.orchestrator.push({ from, note })
}
// Blocking issues in another developer's area that this run did not fix.
const addUnrouted = (from, list) => { for (const b of list || []) result.unrouted.push({ from, ...b }) }
// Keep every earlier reply whose id the newer report dropped.
const mergeReplies = (previous, current) => [...current, ...previous.filter(p => !current.some(c => c.id === p.id))]

// Developer -> reviewer loop for one developer role.
// Returns { dev, review, history, ownDone, foreign, nextRole }.
async function buildAndReview(devRole, devPrompt, scope, label, diffBase) {
  let dev = await agent(`${role(devRole)}\n${ctx()}\n${devPrompt}`, { label: `${devRole}:${label}`, phase: 'Implement', schema: DEV })
  if (!dev) throw new Error(`${devRole} failed`)
  const history = []
  const nextNotes = []
  const absorb = d => {
    addDecisions(devRole, d.decisions)
    addOrchestrator(devRole, d.orchestrator)
    if (d.nextRole && !nextNotes.includes(d.nextRole)) nextNotes.push(d.nextRole)
  }
  absorb(dev)
  let review = null
  // Done for this role when approved, or when blocking issues remain but none are its own.
  // approved:false with an empty blocking list (e.g. a failing check) is NOT done.
  const isOwnDone = r => r.approved || (r.blocking.length > 0 && !r.blocking.some(b => b.owner === devRole))
  let mine = []
  for (let round = 1; round <= MAX_REVIEW_ROUNDS; round++) {
    review = await agent(`${role('code-reviewer')}\n${ctx()}\nReview the work of the ${devRole} on ${BRANCH}: ${diffBase}, plus anything uncommitted. Scope: ${scope}\nName the owner role for every blocking issue (orchestrator for CLAUDE.md and .claude/**).\nDeveloper report (round ${round}): ${JSON.stringify(dev)}\n${history.length ? 'Previous rounds: ' + JSON.stringify(history) : ''}`,
      { label: `code-reviewer:${label}-${round}`, phase: 'Review', schema: REVIEW })
    if (!review) throw new Error('code-reviewer failed')
    addDecisions('code-reviewer', review.decisions)
    addDeferred(devRole, review)
    mine = review.blocking.filter(b => b.owner === devRole)
    history.push({ round, approved: review.approved, blocking: review.blocking })
    log(`${label} (${devRole}) review round ${round}: ${review.approved ? 'APPROVED' : `${review.blocking.length} blocking (${mine.length} own)`}`)
    // Stop when approved, when nothing left is this role's to fix, or when the budget is spent.
    if (isOwnDone(review) || round === MAX_REVIEW_ROUNDS) break
    const previous = dev
    dev = await agent(`${role(devRole)}\n${ctx()}\nThe code-reviewer did not approve. Fix every blocking issue owned by ${devRole}: ${JSON.stringify(mine)}${mine.length ? '' : ' (none listed: the review is not approved, so fix whatever made it fail, e.g. a failing check in checksRun)'}. Issues owned by other roles are routed separately; do not touch them. Re-run all checks, commit locally (no push). Return a reply for every finding id in the original assignment: carry over your previous replies and update them where this round changes them.\nORIGINAL ASSIGNMENT: ${devPrompt}\nPREVIOUS REPORT: ${JSON.stringify(previous)}\nFULL REVIEW: ${JSON.stringify(review)}`,
      { label: `${devRole}:${label}-fix-${round}`, phase: 'Implement', schema: DEV })
    if (!dev) throw new Error(`${devRole} failed`)
    dev = { ...dev, replies: mergeReplies(previous.replies, dev.replies) }
    absorb(dev)
  }
  const foreign = review.blocking.filter(b => b.owner !== devRole)
  for (const b of foreign.filter(b => b.owner === 'orchestrator')) addOrchestrator('code-reviewer', `${b.file}: ${b.issue} — fix: ${b.fix}`)
  return { dev, review, history, ownDone: isOwnDone(review), foreign, nextRole: nextNotes.join('\n') }
}

// Runs the ordered assignments; blocking issues in another role's area become
// extra packages for that role, inserted right after (capped). Hand-off notes accumulate.
async function runAssignments(assignments, extraScope, labelPrefix, diffBase) {
  const queue = [...assignments]
  const out = []
  let handoff = ''
  let inserted = 0
  for (let i = 0; i < queue.length; i++) {
    const a = queue[i]
    const scope = `${a.tasks}${extraScope && !a.inserted ? '; additional in-scope work: ' + extraScope : ''}`
    const built = await buildAndReview(a.role, `Implement: ${scope}\nBrief from the task-manager:\n${a.brief}${handoff ? '\nHand-off notes from earlier developer roles:\n' + handoff : ''}`, scope, `${labelPrefix}-${i + 1}`, diffBase)
    out.push({ role: a.role, tasks: a.tasks, inserted: !!a.inserted, approved: built.review.approved, ownDone: built.ownDone, rounds: built.history.length, review: built.review, dev: built.dev })
    if (built.nextRole) handoff = [handoff, built.nextRole].filter(Boolean).join('\n')
    if (!built.ownDone) { log(`${a.role} work not approved; stopping before later assignments`); break }
    // Route blocking issues owned by another developer role to that role.
    const byOwner = {}
    for (const b of built.foreign.filter(b => DEV_ROLES.includes(b.owner))) (byOwner[b.owner] = byOwner[b.owner] || []).push(b)
    let insertAt = i + 1
    for (const owner of DEV_ROLES) {
      if (!byOwner[owner]) continue
      if (inserted >= MAX_INSERTED_PACKAGES) { addUnrouted(`${a.role} review`, byOwner[owner]); log(`cap of ${MAX_INSERTED_PACKAGES} extra packages reached; ${byOwner[owner].length} issue(s) for ${owner} not routed`); continue }
      queue.splice(insertAt++, 0, { role: owner, inserted: true, tasks: `Fix the blocking review findings in your area: ${JSON.stringify(byOwner[owner])}`, brief: `Raised by the code-reviewer while reviewing the ${a.role} work on: ${a.tasks}` })
      inserted++
    }
  }
  return { out, skipped: queue.slice(out.length).map(a => ({ role: a.role, tasks: a.tasks })) }
}

const fixBase = `'git log origin/${BRANCH}..HEAD' and 'git diff origin/${BRANCH}...HEAD'`
// Runs fix packages until every developer-owned blocking issue is cleared.
// Blocking issues in another developer's area become extra packages (sharing the
// run-wide cap). ok is true only when all packages are done and nothing
// developer-owned is left; only then may the fixes be pushed.
let insertedFixPackages = 0
async function fixUntilClear(packages, label) {
  const queue = [...packages]
  let replies = []
  let anyDone = false
  const leftover = []
  for (let i = 0; i < queue.length; i++) {
    const p = queue[i]
    const r = await buildAndReview(p.owner, p.prompt, p.scope, `${label}-${i + 1}-${p.owner}`, fixBase)
    replies = replies.concat(r.dev.replies)
    if (!r.ownDone) return { ok: false, replies, anyDone, leftover }
    anyDone = true
    const byOwner = {}
    for (const b of r.foreign.filter(b => DEV_ROLES.includes(b.owner))) (byOwner[b.owner] = byOwner[b.owner] || []).push(b)
    for (const owner of DEV_ROLES) {
      if (!byOwner[owner]) continue
      if (insertedFixPackages >= MAX_INSERTED_PACKAGES) { leftover.push(...byOwner[owner]); continue }
      insertedFixPackages++
      queue.push({ owner, prompt: `Fix these blocking review findings in your area, raised while reviewing the ${p.owner} fix on PR #${pr}: ${JSON.stringify(byOwner[owner])}. Test-first, commit locally (no push).`, scope: `blocking findings for ${owner}: ${JSON.stringify(byOwner[owner])}` })
    }
  }
  return { ok: !leftover.length, replies, anyDone, leftover }
}

let pr = A.pr || null
let deliveredDeferred = 0

// Prepare: worktree, follow-ups, routing (skipped in review mode when root is given).
phase('Prepare')
const what = MODE === 'implement'
  ? `task group ${A.group} (tasks ${A.tasks}) of openspec/changes/${CHANGE}/tasks.md`
  : MODE === 'issue' ? `GitHub issue #${A.issue} (read it with 'gh issue view ${A.issue} --comments')` : `the existing PR #${pr}`
if (!WORK || MODE !== 'review') {
  const how = MODE === 'review'
    ? `Reuse or add a worktree for the existing branch ${BRANCH} (tracking origin). Assignments may be empty.`
    : RESUME
      ? `RESUME an interrupted run: reuse the existing branch ${BRANCH} and its worktree (add one tracking the branch if none exists; do NOT create a new branch). Read 'git log origin/main..HEAD', 'git status' and${MODE === 'implement' ? ' tasks.md' : ' the issue'} to see what is already done, and route only the remaining work, saying in each brief what the existing commits already did. Uncommitted changes from the interrupted developer: list them in the brief so the developer reviews them before continuing.`
      : `Create a new worktree with branch ${BRANCH} from origin/main. Gather related follow-ups and route the work into ordered assignments for the developer roles (see "Route and brief" in your role).`
  const prep = await agent(`${role('task-manager')}\n${mainCtx()}\nPrepare ${what}. ${how}${A.devExtra ? `\nAdditional in-scope work from the orchestrator: ${A.devExtra}` : ''}\nSet prepared to true only when the worktree is ready on ${BRANCH}; otherwise false with the reason.`,
    { label: 'task-manager:prepare', phase: 'Prepare', schema: PREPARE })
  if (!prep) throw new Error('task-manager failed to prepare')
  if (prep.prepared !== true) throw new Error('task-manager did not prepare the worktree: ' + prep.reason)
  const norm = p => String(p || '').replace(/\/+$/, '')
  const w = norm(prep.worktree)
  if (!w.startsWith('/')) throw new Error(`task-manager returned a non-absolute worktree path: "${prep.worktree}"`)
  if (!MAIN && !norm(prep.mainCheckout).startsWith('/')) throw new Error(`task-manager did not report the main checkout path: "${prep.mainCheckout}"`)
  if (w === norm(MAIN || prep.mainCheckout)) throw new Error('the worktree is the main checkout; refusing to continue')
  if (prep.linkedWorktree !== true) throw new Error(`${w} is not a linked git worktree (it may be the main checkout); refusing to continue`)
  if (prep.branch !== BRANCH) throw new Error(`worktree ${w} is on ${prep.branch}, not ${BRANCH}; refusing to continue`)
  WORK = w
  result.worktree = WORK
  result.relatedFollowUps = prep.relatedFollowUps
  log(`Worktree ${WORK}; ${prep.assignments.length} assignment(s): ${prep.assignments.map(a => a.role).join(' -> ') || 'none'}`)

  if (MODE !== 'review') {
    if (!prep.assignments.length && !RESUME) throw new Error('task-manager returned no assignments')
    let built, skipped
    if (prep.assignments.length) {
      ({ out: built, skipped } = await runAssignments(prep.assignments, A.devExtra, MODE, `'git log origin/main..HEAD' and 'git diff origin/main...HEAD'`))
    } else {
      // Resume with all work already done: one review pass over the whole branch, then deliver.
      const review = await agent(`${role('code-reviewer')}\n${ctx()}\nThis is a resumed run with no work left. Review the whole branch ${BRANCH} ('git log origin/main..HEAD' and 'git diff origin/main...HEAD') for ${what}. Name the owner role for every blocking issue.`,
        { label: 'code-reviewer:resume-check', phase: 'Review', schema: REVIEW })
      if (!review) throw new Error('code-reviewer failed')
      addDecisions('code-reviewer', review.decisions)
      addDeferred('resume', review)
      for (const x of review.blocking.filter(x => x.owner === 'orchestrator')) addOrchestrator('code-reviewer', `${x.file}: ${x.issue} — fix: ${x.fix}`)
      addUnrouted('resume-check', review.blocking.filter(x => DEV_ROLES.includes(x.owner)))
      const resumeOk = review.approved || (review.blocking.length > 0 && review.blocking.every(x => x.owner === 'orchestrator'))
      built = [{ role: 'resume', tasks: 'already implemented before the interruption', inserted: false, approved: review.approved, ownDone: resumeOk, rounds: 1, review, dev: null }]
      skipped = []
    }
    const last = built[built.length - 1]
    const lastOk = last.review.approved || (last.review.blocking.length > 0 && last.review.blocking.every(b => b.owner === 'orchestrator'))
    const allApproved = !skipped.length && built.every(b => b.ownDone) && lastOk
    result.implementation = { allApproved, packages: built.map(b => ({ role: b.role, tasks: b.tasks, inserted: b.inserted, approved: b.approved, rounds: b.rounds })), skipped }

    phase('Deliver')
    deliveredDeferred = result.deferred.length
    const delivered = await agent(`${role('task-manager')}\n${ctx()}\nDeliver ${what}. All work approved: ${allApproved}. Per package: ${JSON.stringify(built.map(b => ({ role: b.role, tasks: b.tasks, inserted: b.inserted, approved: b.approved, rounds: b.rounds, review: b.review, dev: b.dev })))}.${skipped.length ? `\nNot attempted (an earlier package was not approved): ${JSON.stringify(skipped)}. List these in the PR.` : ''}\nDecisions for the user: ${JSON.stringify(result.decisions)}\nDeferred suggestions to file as follow-up issues (label follow-up plus bug or enhancement): ${JSON.stringify(result.deferred)}\nChanges the orchestrator must apply to CLAUDE.md / .claude/** (mention them in the PR, do not apply them): ${JSON.stringify(result.orchestrator)}${A.extra ? '\nExtra instructions: ' + A.extra : ''}\n${MODE === 'implement' ? 'Tick the completed, undisputed tasks in tasks.md and commit that. ' : `The PR body must say "Fixes #${A.issue}". `}File the follow-up issues, push ${BRANCH}, open the PR (draft if not all approved), with a "Decisions for you" section if there are decisions. Do not wait for CI or Copilot yet — the Copilot phase follows. After creating the PR, run 'gh pr view <number> --json headRefName,url' and report exactly what it returns. If anything failed, set created=false and explain in error; never guess a PR number.`,
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
// Approved fix commits that stayed local because a later fix package was not cleared.
let unpushedLocalCommits = false
const collect = async label => {
  const fb = await agent(`${role('task-manager')}\n${ctx()}\nPR #${pr}. Make sure the worktree is on ${BRANCH} and up to date with origin. Wait (poll every ~30s, at most ~15 minutes) until (a) the required checks have finished (skipped counts as passing) and (b) the Copilot review of the current head SHA has been submitted (see "Copilot reviews" in your role). If a required job failed because of an infrastructure error, re-run it once and wait again (see "Infrastructure failures" in your role); never re-run code failures. Then return the CI result, the owner of any CI failure, and every Copilot finding that still needs handling: all UNRESOLVED review threads, plus review-body findings (e.g. "previously missed issues") that are not in this already-handled list: ${JSON.stringify(handled)}. Do not change anything else.`,
    { label, phase: 'Copilot', schema: FEEDBACK })
  if (!fb) throw new Error('task-manager failed to collect feedback')
  if (fb.pr !== pr || fb.headRefName !== BRANCH) throw new Error(`PR #${fb.pr} is for branch ${fb.headRefName}, expected #${pr} on ${BRANCH}; refusing to touch it`)
  if (fb.linkedWorktree !== true) throw new Error(`${WORK} is not a linked git worktree (it may be the main checkout); refusing to continue`)
  if (fb.localBranch !== BRANCH) throw new Error(`worktree ${WORK} is on ${fb.localBranch}, not ${BRANCH}; refusing to continue`)
  pushedSinceCollect = false
  lastCiPassed = fb.ciPassed
  if (fb.infraReruns.length) (result.infraReruns = result.infraReruns || []).push(...fb.infraReruns)
  // Recompute on every collection: a later review of a newer head overrides
  // an earlier timeout (the earlier one stays visible in its round's note).
  result.copilotTimedOut = !fb.copilotReviewed
  return fb
}
const orchestratorIds = new Set()
for (let round = 1; round <= MAX_COPILOT_ROUNDS; round++) {
  const fb = await collect(`task-manager:collect-${round}`)
  // Orchestrator-owned threads stay open on purpose until the main session applies their diff: ignore them here.
  const findings = fb.findings.filter(f => !orchestratorIds.has(f.id))
  log(`Copilot round ${round}: CI ${fb.ciPassed ? 'green' : 'RED'}, Copilot ${fb.copilotReviewed ? 'reviewed' : 'not reviewed'}, ${findings.length} finding(s)`)
  const entry = { round, ci: fb.ciSummary, copilotReviewed: fb.copilotReviewed, findings: findings.length }
  result.copilotRounds.push(entry)
  if (!fb.ciPassed) entry.note = 'CI failing — needs attention'
  if (!fb.copilotReviewed) {
    // A collector timeout is not a clean review: record it. With CI green and
    // nothing to handle, stop; with CI red, fall through to the CI repair.
    entry.note = `Copilot review of head ${fb.headSha} not received within the wait window (timeout)${fb.ciPassed ? '' : '; CI failing'}`
    if (!findings.length && fb.ciPassed) break
  }
  if (fb.copilotReviewed && fb.ciPassed && !findings.length) break
  if (!findings.length && !fb.ciPassed) {
    // CI red without Copilot findings: the owning developer fixes CI.
    const owner = DEV_ROLES.includes(fb.ciOwner) ? fb.ciOwner : 'platform-engineer'
    const ci = await fixUntilClear([{ owner, prompt: `CI on PR #${pr} is failing: ${fb.ciSummary}. You may not use 'gh' — the summary above is what you get; reproduce locally, fix the cause test-first, commit locally.`, scope: `fix the failing CI on PR #${pr}` }], `ci-${round}`)
    entry.ciFix = { owner, approved: ci.ok }
    addUnrouted(`ci-${round}`, ci.leftover)
    if (!ci.ok) {
      entry.note = 'CI fix not cleared by the code-reviewer (or blocking issues left for another role); nothing pushed'
      if (ci.anyDone) unpushedLocalCommits = true
      break
    }
    const pushed = await agent(`${role('task-manager')}\n${ctx()}\nPush the approved CI fix commits on ${BRANCH} for PR #${pr}. Request a new Copilot review. Do not merge.`, { label: `task-manager:push-ci-${round}`, phase: 'Copilot' })
    if (!pushed) throw new Error('task-manager failed to push the CI fix')
    pushedSinceCollect = true
    continue
  }

  const triage = await agent(`${role('code-reviewer')}\n${ctx()}\nTriage the Copilot findings on PR #${pr} (see "Triaging Copilot review comments" in your role). Read the code at the referenced locations on ${BRANCH} before deciding. One decision per finding id; for fix, name the owner role (orchestrator for CLAUDE.md and .claude/**, with the exact diff as expectedFix). Report design questions for the user in userDecisions.\nFINDINGS: ${JSON.stringify(findings)}`,
    { label: `code-reviewer:triage-${round}`, phase: 'Copilot', schema: TRIAGE })
  if (!triage) throw new Error('code-reviewer failed to triage')
  addDecisions('code-reviewer', triage.userDecisions)
  const fixes = triage.decisions.filter(d => d.decision === 'fix')
  const orchestratorFixes = fixes.filter(f => f.owner === 'orchestrator')
  const devFixes = fixes.filter(f => f.owner !== 'orchestrator')
  for (const f of orchestratorFixes) addOrchestrator('copilot', `${f.id}: ${f.expectedFix || f.reason}`)
  entry.decisions = triage.decisions.map(d => ({ id: d.id, decision: d.decision, owner: d.owner, reason: d.reason }))
  log(`Triage: ${fixes.length} fix (${orchestratorFixes.length} for the orchestrator), ${triage.decisions.filter(d => d.decision === 'follow-up').length} follow-up, ${triage.decisions.filter(d => d.decision === 'decline').length} decline`)

  // Developer fixes per owning role (backend -> frontend -> platform), plus any blocking
  // issues they raise for other roles; nothing is pushed unless all are cleared.
  const packages = DEV_ROLES.map(owner => ({ owner, mine: devFixes.filter(f => (DEV_ROLES.includes(f.owner) ? f.owner : 'platform-engineer') === owner) }))
    .filter(p => p.mine.length)
    .map(p => ({ owner: p.owner, prompt: `Fix these Copilot findings on PR #${pr}, as triaged by the code-reviewer. Test-first: reproduce each with a failing test. Commit locally (no push). Give a PR-thread reply per finding id.\nFIXES: ${JSON.stringify(p.mine)}`, scope: `the Copilot fixes listed for PR #${pr}: ${JSON.stringify(p.mine.map(f => ({ id: f.id, expectedFix: f.expectedFix })))}` }))
  const fixRun = packages.length ? await fixUntilClear(packages, `copilot-${round}`) : { ok: true, replies: [], anyDone: false, leftover: [] }
  const replies = fixRun.replies
  addUnrouted(`copilot-${round}`, fixRun.leftover)
  entry.fixApproved = fixRun.ok
  if (!fixRun.ok) {
    entry.note = 'Copilot fixes not cleared by the code-reviewer (or blocking issues left for another role); nothing pushed'
    if (fixRun.anyDone) unpushedLocalCommits = true
    break
  }

  // Orchestrator-owned fixes stay open (unresolved) until the main session applies them.
  const applyDecisions = triage.decisions.filter(d => !(d.decision === 'fix' && d.owner === 'orchestrator'))
  const applied = await agent(`${role('task-manager')}\n${ctx()}\nApply the code-reviewer's triage of the Copilot findings on PR #${pr} (see "Copilot reviews" in your role):\n${devFixes.length ? `1. Push the approved fix commits on ${BRANCH}.\n` : ''}2. For each decision: fix -> reply with the developer's reply (naming the commit) and resolve; follow-up -> create the GitHub issue (label follow-up plus bug or enhancement), reply with its link and resolve; decline -> reply with the reason and resolve. Review-body findings (id starts with "body:") have no thread: cover them in one PR comment.\n${devFixes.length ? `3. Request a new Copilot review: gh pr edit ${pr} --add-reviewer @copilot\n` : ''}${orchestratorFixes.length ? `Leave these findings untouched (the orchestrator applies their fix to CLAUDE.md / .claude/**): ${JSON.stringify(orchestratorFixes.map(f => f.id))}.\n` : ''}No @mentions. Do not merge. Return one result per finding id you handled: done is true only when its reply/comment (and issue, for follow-up) actually exists and its thread is resolved; otherwise done is false with the error in note.\nTRIAGE: ${JSON.stringify(applyDecisions)}\nDEVELOPER REPLIES: ${JSON.stringify(replies)}`,
    { label: `task-manager:apply-${round}`, phase: 'Copilot', schema: APPLY })
  if (!applied) throw new Error('task-manager failed to apply the triage')
  entry.applied = applied
  if (devFixes.length) pushedSinceCollect = true
  // Only mark findings handled once their replies/issues actually exist; the
  // rest are collected again (threads stay unresolved) and reported at handover.
  const doneIds = new Set(applied.results.filter(r => r.done === true).map(r => r.id))
  for (const f of orchestratorFixes) orchestratorIds.add(f.id)
  const orchIds = orchestratorIds
  const summarize = f => ({ id: f.id, path: f.path, line: f.line, gist: f.body.slice(0, 120) })
  handled.push(...findings.filter(f => doneIds.has(f.id) || orchIds.has(f.id)).map(summarize))
  for (const f of findings.filter(f => !doneIds.has(f.id) && !orchIds.has(f.id))) {
    const r = applied.results.find(x => x.id === f.id)
    const item = { ...summarize(f), note: r ? r.note : 'no result reported by the task-manager' }
    const i = unapplied.findIndex(u => u.id === f.id)
    if (i >= 0) unapplied[i] = item
    else unapplied.push(item)
  }
  // A later round may complete a finding that failed earlier.
  for (let i = unapplied.length - 1; i >= 0; i--) if (doneIds.has(unapplied[i].id)) unapplied.splice(i, 1)
  const failedHere = findings.filter(f => !doneIds.has(f.id) && !orchIds.has(f.id)).map(f => f.id)
  if (failedHere.length) entry.failed = unapplied.filter(u => failedHere.includes(u.id))
  // Nothing pushed and CI green: Copilot will not review again, so we are done.
  // With CI red, continue: the threads are resolved now, so the next round
  // collects no findings and takes the CI-repair branch.
  if (!devFixes.length && fb.ciPassed) break
}
if (pushedSinceCollect) {
  // The round budget ran out right after a push: collect once more so the
  // handover reports the CI and Copilot status of the head actually on the PR.
  // Remaining findings are reported as outstanding, not triaged or fixed.
  const fb = await collect('task-manager:final-collect')
  const findings = fb.findings.filter(f => !orchestratorIds.has(f.id))
  log(`Final collection: CI ${fb.ciPassed ? 'green' : 'RED'}, Copilot ${fb.copilotReviewed ? 'reviewed' : 'not reviewed'}, ${findings.length} outstanding finding(s)`)
  const entry = { round: 'final', ci: fb.ciSummary, copilotReviewed: fb.copilotReviewed, findings: findings.length }
  if (!fb.ciPassed) entry.note = 'CI failing — needs attention'
  if (!fb.copilotReviewed) entry.note = `Copilot review of head ${fb.headSha} not received within the wait window (timeout)${fb.ciPassed ? '' : '; CI failing'}`
  if (findings.length) {
    entry.outstanding = findings.map(f => ({ id: f.id, path: f.path, line: f.line, gist: f.body.slice(0, 120) }))
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
const deferredAfterDelivery = result.deferred.slice(deliveredDeferred)

const report = await agent(`${role('task-manager')}\n${ctx()}\nFinal hand-over for PR #${pr} (see "Hand over" in your role): confirm there are no unresolved review threads apart from orchestrator-owned ones, and report the required checks ('gh pr checks ${pr} --required'; note skipped ones). Leave the worktree ${WORK} in place.${deferredAfterDelivery.length ? `\nFile these deferred suggestions (raised after delivery) as follow-up issues and list the links: ${JSON.stringify(deferredAfterDelivery)}.` : ''}\nReturn a concise message to the user. Start with "Decisions for you" if there are any: ${JSON.stringify(result.decisions)}. Then: PR URL, CI results, the implementation packages (approved, rounds, inserted, skipped): ${JSON.stringify(result.implementation || null)}, what happened with the Copilot findings (fixed / follow-up issues with links / declined), follow-up issues filed at delivery (${JSON.stringify(result.followUpIssues || [])}), related follow-ups found at prepare (${JSON.stringify(result.relatedFollowUps || [])}), changes the orchestrator must apply to CLAUDE.md / .claude/** (${JSON.stringify(result.orchestrator)}), infrastructure re-runs (${JSON.stringify(result.infraReruns || [])}), and the worktree path. Ask them to review. Do not merge.${result.unrouted.length ? '\nIMPORTANT: these blocking review issues in another role\'s area were NOT fixed in this run; list them as outstanding and file a follow-up issue for each: ' + JSON.stringify(result.unrouted) : ''}${unpushedLocalCommits ? `\nIMPORTANT: some approved fix commits are only local in ${WORK} because a later fix package was not cleared. Say so.` : ''}${result.copilotTimedOut ? `\nIMPORTANT: the Copilot review was NOT received within the wait window (timeout). Tell the user the Copilot review is still outstanding and must be checked before merging.` : ''}${result.ciStillFailing ? `\nIMPORTANT: the Copilot loop ended while the last observed CI run was failing. Tell the user CI is red and needs attention.` : ''}${result.outstandingFindings ? `\nIMPORTANT: the Copilot round budget is exhausted and these findings on the final head were NOT handled: ${JSON.stringify(result.outstandingFindings)}. List them as outstanding for the user.` : ''}${result.unappliedFindings ? `\nIMPORTANT: the reply, comment or issue for these Copilot findings could NOT be applied: ${JSON.stringify(result.unappliedFindings)}. List them as outstanding for the user.` : ''}\nCopilot rounds: ${JSON.stringify(result.copilotRounds)}`,
  { label: 'task-manager:handover', phase: 'Copilot' })
result.handover = report
return result
