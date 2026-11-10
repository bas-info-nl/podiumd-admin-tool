export const meta = {
  name: 'implement-task-group',
  description: 'Task manager / senior developer / code reviewer: implement an OpenSpec task group as a PR, then handle CI and Copilot review comments until clean',
  whenToUse: 'Implement one task group of an OpenSpec change (mode "implement"), or handle the Copilot review of an existing PR (mode "review"). Roles live in .claude/agents/.',
  phases: [
    { title: 'Prepare', detail: 'task-manager creates the branch from origin/main' },
    { title: 'Implement', detail: 'senior-developer writes code and tests' },
    { title: 'Review', detail: 'code-reviewer re-runs checks and reviews; loops back to developer' },
    { title: 'Deliver', detail: 'task-manager pushes and opens the PR' },
    { title: 'Copilot', detail: 'wait for CI + Copilot, triage, fix, reply, resolve, re-request' },
  ],
}

// args:
//   implement: { mode: 'implement', change, group, tasks, branch, devExtra?, extra? }
//   review:    { mode: 'review', pr, branch }
//   both:      root? - absolute path of the repository checkout. When omitted,
//              the agents use their current working directory (the workspace
//              the workflow runs in) and repo-relative paths.
const REPO = 'infonl/podiumd-admin-tool'
const A = args || {}
const ROOT = A.root || null
const MODE = A.mode || 'implement'
const CHANGE = A.change || 'add-foundation'
const BRANCH = A.branch
const MAX_REVIEW_ROUNDS = 4
const MAX_COPILOT_ROUNDS = 3
if (!BRANCH) throw new Error('args.branch is required')

const repoPath = rel => (ROOT ? `${ROOT}/${rel}` : rel)
const role = name => `You are the ${name.toUpperCase()}. First read and follow your role definition in ${repoPath(`.claude/agents/${name}.md`)}, and the repository rules in ${repoPath('CLAUDE.md')}.`
const CTX = `Repository ${ROOT || 'in your current working directory (the workspace this workflow runs in); paths are relative to the repository root'} (GitHub ${REPO}). Feature branch: ${BRANCH}.`

const DEV = { type: 'object', properties: {
  summary: { type: 'string' },
  done: { type: 'array', items: { type: 'string' } },
  notDone: { type: 'array', items: { type: 'object', properties: { item: { type: 'string' }, reason: { type: 'string' } }, required: ['item', 'reason'] } },
  replies: { type: 'array', items: { type: 'object', properties: { id: { type: 'string' }, reply: { type: 'string' } }, required: ['id', 'reply'] } },
  checksPassed: { type: 'boolean' },
  commits: { type: 'array', items: { type: 'string' } },
}, required: ['summary', 'done', 'notDone', 'replies', 'checksPassed', 'commits'] }
const REVIEW = { type: 'object', properties: {
  approved: { type: 'boolean' },
  checksRun: { type: 'array', items: { type: 'object', properties: { command: { type: 'string' }, passed: { type: 'boolean' }, note: { type: 'string' } }, required: ['command', 'passed', 'note'] } },
  blocking: { type: 'array', items: { type: 'object', properties: { file: { type: 'string' }, issue: { type: 'string' }, fix: { type: 'string' } }, required: ['file', 'issue', 'fix'] } },
  suggestions: { type: 'array', items: { type: 'string' } },
  summary: { type: 'string' },
}, required: ['approved', 'checksRun', 'blocking', 'suggestions', 'summary'] }
const FEEDBACK = { type: 'object', properties: {
  pr: { type: 'integer' },
  headSha: { type: 'string' },
  ciPassed: { type: 'boolean' },
  ciSummary: { type: 'string' },
  copilotReviewed: { type: 'boolean' },
  findings: { type: 'array', items: { type: 'object', properties: {
    id: { type: 'string', description: 'review thread id (PRRT_...) or "body:<short-slug>" for review-body findings' },
    kind: { type: 'string', enum: ['thread', 'body'] },
    path: { type: 'string' }, line: { type: 'integer' }, body: { type: 'string' },
  }, required: ['id', 'kind', 'path', 'body'] } },
}, required: ['pr', 'headSha', 'ciPassed', 'ciSummary', 'copilotReviewed', 'findings'] }
const TRIAGE = { type: 'object', properties: {
  decisions: { type: 'array', items: { type: 'object', properties: {
    id: { type: 'string' },
    decision: { type: 'string', enum: ['fix', 'follow-up', 'decline'] },
    reason: { type: 'string' },
    expectedFix: { type: 'string', description: 'for fix: what to change and which test proves it' },
    issueTitle: { type: 'string' }, issueBody: { type: 'string' },
    reply: { type: 'string', description: 'text for the PR thread (decline/follow-up); for fix the developer supplies the final reply' },
  }, required: ['id', 'decision', 'reason', 'reply'] } },
  summary: { type: 'string' },
}, required: ['decisions', 'summary'] }

// Developer -> reviewer loop. Returns { dev, review, history }.
async function buildAndReview(devPrompt, scope, label) {
  let dev = await agent(`${role('senior-developer')}\n${CTX}\n${devPrompt}`, { label: `senior-developer:${label}`, phase: 'Implement', schema: DEV })
  if (!dev) throw new Error('senior-developer failed')
  const history = []
  let review = null
  for (let round = 1; round <= MAX_REVIEW_ROUNDS; round++) {
    review = await agent(`${role('code-reviewer')}\n${CTX}\nReview the local commits on ${BRANCH} that are not yet on origin (${MODE === 'implement' && label === 'implement' ? `'git diff origin/main...HEAD'` : `'git log origin/${BRANCH}..HEAD' and 'git diff origin/${BRANCH}...HEAD'`}), plus anything uncommitted. Scope: ${scope}\nDeveloper report (round ${round}): ${JSON.stringify(dev)}\n${history.length ? 'Previous rounds: ' + JSON.stringify(history) : ''}`,
      { label: `code-reviewer:${label}-${round}`, phase: 'Review', schema: REVIEW })
    if (!review) throw new Error('code-reviewer failed')
    history.push({ round, approved: review.approved, blocking: review.blocking })
    log(`${label} review round ${round}: ${review.approved ? 'APPROVED' : review.blocking.length + ' blocking'}`)
    if (review.approved || round === MAX_REVIEW_ROUNDS) break
    dev = await agent(`${role('senior-developer')}\n${CTX}\nThe code-reviewer did not approve. Fix every blocking issue, re-run all checks, commit locally (no push). Keep your per-finding replies up to date.\nREVIEW: ${JSON.stringify(review)}`,
      { label: `senior-developer:${label}-fix-${round}`, phase: 'Implement', schema: DEV })
    if (!dev) throw new Error('senior-developer failed')
  }
  return { dev, review, history }
}

let pr = A.pr || null
const result = { mode: MODE, branch: BRANCH }

if (MODE === 'implement') {
  const TASKS = A.tasks, GROUP = A.group
  phase('Prepare')
  const brief = await agent(`${role('task-manager')}\n${CTX}\nPrepare task group ${GROUP} (tasks ${TASKS}) of openspec/changes/${CHANGE}/tasks.md: create ${BRANCH} from origin/main and return the brief for the senior-developer.`, { label: 'task-manager:prepare', phase: 'Prepare' })
  if (!brief) throw new Error('task-manager failed to prepare')

  const scope = `tasks ${TASKS} of openspec/changes/${CHANGE}/tasks.md${A.devExtra ? '; additional in-scope work: ' + A.devExtra : ''}`
  const built = await buildAndReview(`Implement ${scope}.\nBrief from the task-manager:\n${brief}`, scope, 'implement')
  result.implementation = { approved: built.review.approved, rounds: built.history.length, review: built.review, dev: built.dev }

  phase('Deliver')
  const delivered = await agent(`${role('task-manager')}\n${CTX}\nDeliver task group ${GROUP} (tasks ${TASKS}) of change ${CHANGE}. Reviewer approved: ${built.review.approved}. Review history: ${JSON.stringify(built.history)}. Final review: ${JSON.stringify(built.review)}. Developer report: ${JSON.stringify(built.dev)}.${A.extra ? '\nExtra instructions: ' + A.extra : ''}\nTick the completed tasks, push ${BRANCH}, open the PR (draft if not approved). Do not wait for CI or Copilot yet and do not switch back to main yet — the Copilot phase follows. Return ONLY the PR number as digits.`,
    { label: 'task-manager:deliver', phase: 'Deliver' })
  pr = parseInt(String(delivered || '').match(/\d+/)?.[0] || '', 10)
  if (!pr) throw new Error('task-manager did not return a PR number: ' + delivered)
  log(`PR #${pr} opened`)
}
result.pr = pr

// Copilot / CI feedback loop
phase('Copilot')
const handled = []
result.copilotRounds = []
let lastCiPassed = true
// True when commits were pushed after the last collection, so the last
// observed CI and Copilot status describe an older head.
let pushedSinceCollect = false
const collect = async label => {
  const fb = await agent(`${role('task-manager')}\n${CTX}\nPR #${pr}. Make sure the local checkout is on ${BRANCH} and up to date with origin. Wait (poll every ~30s, at most ~15 minutes) until (a) the required checks have finished and (b) the Copilot review of the current head SHA has been submitted (see "Copilot reviews" in your role). Then return the CI result and every Copilot finding that still needs handling: all UNRESOLVED review threads, plus review-body findings (e.g. "previously missed issues") that are not in this already-handled list: ${JSON.stringify(handled)}. Do not change anything.`,
    { label, phase: 'Copilot', schema: FEEDBACK })
  if (!fb) throw new Error('task-manager failed to collect feedback')
  pushedSinceCollect = false
  lastCiPassed = fb.ciPassed
  // Recompute on every collection: a later review of a newer head overrides
  // an earlier timeout (the earlier one stays visible in its round's note).
  result.copilotTimedOut = !fb.copilotReviewed
  return fb
}
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
    // CI red without Copilot findings: let the developer fix CI.
    const ci = await buildAndReview(`CI on PR #${pr} is failing: ${fb.ciSummary}. Inspect the failed jobs ('gh' is NOT allowed for you — the summary above is what you get; reproduce locally), fix the cause test-first, commit locally.`, `fix the failing CI on PR #${pr}`, `ci-${round}`)
    entry.ciFix = { approved: ci.review.approved }
    if (!ci.review.approved) break
    const pushed = await agent(`${role('task-manager')}\n${CTX}\nPush the approved CI fix commits on ${BRANCH} for PR #${pr}. Request a new Copilot review. Do not merge.`, { label: `task-manager:push-ci-${round}`, phase: 'Copilot' })
    if (!pushed) throw new Error('task-manager failed to push the CI fix')
    pushedSinceCollect = true
    continue
  }

  const triage = await agent(`${role('code-reviewer')}\n${CTX}\nTriage the Copilot findings on PR #${pr} (see "Triaging Copilot review comments" in your role). Read the code at the referenced locations on ${BRANCH} before deciding. One decision per finding id.\nFINDINGS: ${JSON.stringify(fb.findings)}`,
    { label: `code-reviewer:triage-${round}`, phase: 'Copilot', schema: TRIAGE })
  if (!triage) throw new Error('code-reviewer failed to triage')
  const fixes = triage.decisions.filter(d => d.decision === 'fix')
  entry.decisions = triage.decisions.map(d => ({ id: d.id, decision: d.decision, reason: d.reason }))
  log(`Triage: ${fixes.length} fix, ${triage.decisions.filter(d => d.decision === 'follow-up').length} follow-up, ${triage.decisions.filter(d => d.decision === 'decline').length} decline`)

  let fixResult = null
  if (fixes.length) {
    fixResult = await buildAndReview(`Fix these Copilot findings on PR #${pr}, as triaged by the code-reviewer. Test-first: reproduce each with a failing test. Commit locally (no push). Give a PR-thread reply per finding id.\nFIXES: ${JSON.stringify(fixes)}`,
      `the Copilot fixes listed for PR #${pr}: ${JSON.stringify(fixes.map(f => ({ id: f.id, expectedFix: f.expectedFix })))}`, `copilot-${round}`)
    entry.fixApproved = fixResult.review.approved
    if (!fixResult.review.approved) {
      entry.note = 'Copilot fixes not approved by the code-reviewer; nothing pushed'
      break
    }
  }

  const applied = await agent(`${role('task-manager')}\n${CTX}\nApply the code-reviewer's triage of the Copilot findings on PR #${pr} (see "Copilot reviews" in your role):\n${fixes.length ? `1. Push the approved fix commits on ${BRANCH}.\n` : ''}2. For each decision: fix -> reply with the developer's reply (naming the commit) and resolve; follow-up -> create the GitHub issue (label follow-up plus bug or enhancement), reply with its link and resolve; decline -> reply with the reason and resolve. Review-body findings (id starts with "body:") have no thread: cover them in one PR comment.\n${fixes.length ? `3. Request a new Copilot review: gh pr edit ${pr} --add-reviewer @copilot\n` : ''}No @mentions. Do not merge. Report what you did per id.\nTRIAGE: ${JSON.stringify(triage.decisions)}\nDEVELOPER REPLIES: ${JSON.stringify(fixResult ? fixResult.dev.replies : [])}`,
    { label: `task-manager:apply-${round}`, phase: 'Copilot' })
  // Only mark findings handled once their replies/issues actually exist.
  if (!applied) throw new Error('task-manager failed to apply the triage')
  if (fixes.length) pushedSinceCollect = true
  handled.push(...fb.findings.map(f => ({ id: f.id, path: f.path, line: f.line, gist: f.body.slice(0, 120) })))
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
  if (!fb.copilotReviewed) entry.note = `Copilot review of head ${fb.headSha} not received within the wait window (timeout)`
  if (fb.findings.length) {
    entry.outstanding = fb.findings.map(f => ({ id: f.id, path: f.path, line: f.line, gist: f.body.slice(0, 120) }))
    result.outstandingFindings = entry.outstanding
  }
  result.copilotRounds.push(entry)
}
if (!lastCiPassed) {
  // The loop ended (round budget exhausted or a fix not approved) while the
  // last observed CI run was red.
  const last = result.copilotRounds[result.copilotRounds.length - 1]
  last.note = `${last.note ? last.note + '; ' : ''}Copilot loop ended with CI still failing in the last observed run`
  result.ciStillFailing = true
}

const report = await agent(`${role('task-manager')}\n${CTX}\nFinal hand-over for PR #${pr}: confirm there are no unresolved review threads and report the required checks ('gh pr checks ${pr} --required'). Switch the local checkout back to main ('git switch main && git pull --ff-only'). Return a concise message to the user: PR URL, CI results, what happened with the Copilot findings (fixed / follow-up issues with links / declined), and ask them to review before the next task group starts. Do not merge.${result.copilotTimedOut ? `\nIMPORTANT: the Copilot review was NOT received within the wait window (timeout). Tell the user the Copilot review is still outstanding and must be checked before merging.` : ''}${result.ciStillFailing ? `\nIMPORTANT: the Copilot loop ended while the last observed CI run was failing. Tell the user CI is red and needs attention.` : ''}${result.outstandingFindings ? `\nIMPORTANT: the Copilot round budget is exhausted and these findings on the final head were NOT handled: ${JSON.stringify(result.outstandingFindings)}. List them as outstanding for the user.` : ''}\nCopilot rounds: ${JSON.stringify(result.copilotRounds)}`,
  { label: 'task-manager:handover', phase: 'Copilot' })
result.handover = report
return result
