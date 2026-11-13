#!/usr/bin/env bash
# Tests for wait-for-pr-feedback.sh. Puts a stub `gh` first on PATH, which
# answers from a few state files, and asserts the JSON the script prints.
#
# Usage: .github/scripts/test-wait-for-pr-feedback.sh   (exits non-zero on a failure)
set -euo pipefail

script="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/wait-for-pr-feedback.sh"
work=$(mktemp -d)
trap 'rm -rf "${work}"' EXIT

failures=0

# The stub reads its behaviour from files in $STUB:
#   mode        pass | fail | none (no required checks are reported at all)
#   done_after  the number of the first `gh pr checks` call that reports finished checks
#   reviewed    the commit of the latest Copilot review
# The head commit is always "head1".
mkdir -p "${work}/bin" "${work}/state"
cat >"${work}/bin/gh" <<'STUB'
#!/usr/bin/env bash
set -euo pipefail
case "$1 $2" in
  "pr view")
    echo head1
    ;;
  "pr checks")
    calls=$(($(cat "$STUB/calls") + 1))
    echo "$calls" >"$STUB/calls"
    mode=$(cat "$STUB/mode")
    if [[ $mode == none ]]; then
      echo "no required checks reported on the branch" >&2
      exit 1
    fi
    if ((calls < $(cat "$STUB/done_after"))); then
      echo '{"total":2,"pending":1,"failed":0,"checks":[{"name":"backend","bucket":"pending"},{"name":"frontend","bucket":"skipping"}]}'
      exit 8
    fi
    if [[ $mode == fail ]]; then
      echo '{"total":2,"pending":0,"failed":1,"checks":[{"name":"backend","bucket":"fail"},{"name":"frontend","bucket":"skipping"}]}'
      exit 1
    fi
    echo '{"total":2,"pending":0,"failed":0,"checks":[{"name":"backend","bucket":"pass"},{"name":"frontend","bucket":"skipping"}]}'
    ;;
  "api --paginate")
    # Oldest first, as the REST API returns reviews.
    printf 'older\n%s\n' "$(cat "$STUB/reviewed")"
    ;;
  *)
    echo "stub gh: unexpected call: $*" >&2
    exit 64
    ;;
esac
STUB
chmod +x "${work}/bin/gh"

# run <mode> <done_after> <reviewed> <timeout>: the script's JSON line, with a 1 second interval.
run() {
  echo 0 >"${work}/state/calls"
  echo "$1" >"${work}/state/mode"
  echo "$2" >"${work}/state/done_after"
  echo "$3" >"${work}/state/reviewed"
  STUB="${work}/state" PATH="${work}/bin:${PATH}" "${script}" 7 "$4" 1 2>/dev/null
}

# expect <name> <json> <fragment>...: every fragment must occur in the JSON.
expect() {
  local name=$1 json=$2 fragment missing=()
  shift 2
  for fragment in "$@"; do
    if [[ $json != *"$fragment"* ]]; then
      missing+=("$fragment")
    fi
  done
  if [[ ${#missing[@]} -eq 0 ]]; then
    echo "ok   ${name}"
  else
    echo "FAIL ${name}"
    echo "       got:     ${json}"
    printf '       missing: %s\n' "${missing[@]}"
    failures=$((failures + 1))
  fi
}

expect "checks finish on the third poll, Copilot reviewed the head" \
  "$(run pass 3 head1 20)" \
  '"pr":7' '"headSha":"head1"' '"ciPassed":true' '"copilotReviewed":true' '"timedOut":false' '"total":2,"pending":0,"failed":0'

expect "a skipped check counts as passing and is still listed" \
  "$(run pass 1 head1 20)" \
  '"ciPassed":true' '{"name":"frontend","bucket":"skipping"}'

expect "a failed check: done, but CI did not pass" \
  "$(run fail 1 head1 20)" \
  '"ciPassed":false' '"copilotReviewed":true' '"timedOut":false' '"failed":1'

expect "the review is of an older commit: times out, CI result still reported" \
  "$(run pass 1 older 2)" \
  '"ciPassed":true' '"copilotReviewed":false' '"timedOut":true'

expect "no required checks reported yet: keeps waiting, then times out" \
  "$(run none 1 head1 2)" \
  '"ciPassed":false' '"timedOut":true' '"required":{"total":0,"pending":0,"failed":0,"checks":[]}'

expect "checks still pending at the timeout" \
  "$(run pass 99 head1 2)" \
  '"ciPassed":false' '"timedOut":true' '"pending":1'

# Usage errors exit with status 2 and print nothing on stdout.
for bad in "" "abc" "7 soon" "7 10 1 extra"; do
  status=0
  # shellcheck disable=SC2086  # the arguments are split on purpose
  out=$(PATH="${work}/bin:${PATH}" "${script}" $bad 2>/dev/null) || status=$?
  if [[ $status -eq 2 && -z $out ]]; then
    echo "ok   usage error for arguments: '${bad}'"
  else
    echo "FAIL usage error for arguments: '${bad}' (status ${status}, stdout '${out}')"
    failures=$((failures + 1))
  fi
done

if [[ $failures -gt 0 ]]; then
  echo "${failures} test(s) failed"
  exit 1
fi
echo "all tests passed"
