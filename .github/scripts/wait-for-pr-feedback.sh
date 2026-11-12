#!/usr/bin/env bash
# Wait until a pull request has its feedback: the required checks have finished
# and the Copilot review of the current head commit has been submitted.
#
# Usage:
#   wait-for-pr-feedback.sh PR [TIMEOUT_SECONDS [INTERVAL_SECONDS]]
#
# Polls with `gh` (so it needs an authenticated gh, in a checkout of the
# repository) and prints one JSON object on stdout when both are done or the
# timeout has passed; progress goes to stderr:
#
#   {"pr":28,"headSha":"<sha>","ciPassed":true,"copilotReviewed":true,
#    "timedOut":false,
#    "required":{"total":5,"pending":0,"failed":0,"checks":[{"name":"backend","bucket":"pass"}]}}
#
# ciPassed is true when every required check has finished and none failed or was
# cancelled. A skipped check counts as passing: the CI path gates skip the areas
# a pull request does not touch. The exit status is 0 on a timeout too
# ("timedOut": true); it is non-zero only for a usage error or a failing gh call.
#
# The default timeout stays under ten minutes, the longest a single agent
# command may run; call the script again to wait longer.
set -euo pipefail

if [[ $# -lt 1 || $# -gt 3 || ! $1 =~ ^[0-9]+$ || ! ${2:-540} =~ ^[0-9]+$ || ! ${3:-30} =~ ^[0-9]+$ ]]; then
  echo "usage: $0 PR [TIMEOUT_SECONDS [INTERVAL_SECONDS]]" >&2
  exit 2
fi
pr=$1
timeout=${2:-540}
interval=${3:-30}

# The REST reviews endpoint reports the Copilot reviewer with the [bot] suffix.
copilot_review_filter='.[] | select(.user.login == "copilot-pull-request-reviewer[bot]") | .commit_id'
# One compact JSON object: the counts, and the name and bucket of each check.
required_filter='{
  total: length,
  pending: (map(select(.bucket == "pending")) | length),
  failed: (map(select(.bucket == "fail" or .bucket == "cancel")) | length),
  checks: map({name, bucket})
} | tojson'
none_reported='{"total":0,"pending":0,"failed":0,"checks":[]}'

# count <json> <key>: the integer value of a top-level count in the summary.
count() {
  if [[ $1 =~ \"$2\":([0-9]+) ]]; then
    echo "${BASH_REMATCH[1]}"
  else
    echo "cannot read \"$2\" from: $1" >&2
    exit 1
  fi
}

deadline=$((SECONDS + timeout))
while :; do
  head=$(gh pr view "$pr" --json headRefOid --jq .headRefOid)

  # `gh pr checks` exits non-zero while checks are pending or failed, and when
  # none are reported yet (just after a push), so read its JSON, not its status.
  required=$(gh pr checks "$pr" --required --json name,bucket --jq "$required_filter") || true
  if [[ -z $required ]]; then
    required=$none_reported
  fi
  total=$(count "$required" total)
  pending=$(count "$required" pending)
  failed=$(count "$required" failed)

  checks_done=false
  if ((total > 0 && pending == 0)); then
    checks_done=true
  fi
  ci_passed=false
  if [[ $checks_done == true ]] && ((failed == 0)); then
    ci_passed=true
  fi

  # Reviews come back oldest first, so the last line is the latest Copilot review.
  reviewed_commit=$(gh api --paginate "repos/{owner}/{repo}/pulls/${pr}/reviews" --jq "$copilot_review_filter" | tail -n 1)
  copilot_reviewed=false
  if [[ -n $reviewed_commit && $reviewed_commit == "$head" ]]; then
    copilot_reviewed=true
  fi

  echo "PR #${pr} head ${head}: ${total} required check(s), ${pending} pending, ${failed} failed; Copilot reviewed head: ${copilot_reviewed}" >&2

  timed_out=false
  if [[ $checks_done == true && $copilot_reviewed == true ]]; then
    break
  fi
  if ((SECONDS + interval > deadline)); then
    timed_out=true
    break
  fi
  sleep "$interval"
done

printf '{"pr":%s,"headSha":"%s","ciPassed":%s,"copilotReviewed":%s,"timedOut":%s,"required":%s}\n' \
  "$pr" "$head" "$ci_passed" "$copilot_reviewed" "$timed_out" "$required"
