#!/usr/bin/env bash
# Fail when a Dockerfile writes a tool version or uses an unpinned image.
#
# Usage: check-dockerfile-versions.sh [DOCKERFILE...]   (default: Dockerfile)
#
# The Node.js and Python versions of the image have one source each, .nvmrc and
# backend/.python-version (README, "Tool versions"); `docker build` receives
# them as build args. So in a Dockerfile:
#
# - every image in FROM, COPY --from and RUN --mount from= is pinned by digest
#   (@sha256:<64 hex>), unless it is `scratch` or an earlier stage;
# - an image tag holds no digit outside a ${BUILD_ARG}: a literal version such
#   as `26.13.0` or `3` would be a second source;
# - an ARG default is no version: no dotted number, and no digit at all for an
#   ARG whose name ends in VERSION.
#
# Comments are ignored. Exits 1 on a problem, listing each one.
set -euo pipefail

if [[ $# -eq 0 ]]; then
  set -- Dockerfile
fi

problems=0

problem() {
  echo "$1:$2: $3" >&2
  problems=$((problems + 1))
}

# check_image <file> <line> <image reference>
check_image() {
  local file=$1 line=$2 ref=$3 name tag
  if [[ ! ${ref} =~ @sha256:[0-9a-f]{64}$ ]]; then
    problem "${file}" "${line}" "image '${ref}' is not pinned by digest (@sha256:...)"
  fi
  name=${ref%%@*}
  tag=""
  # A tag follows the last ':' after the last '/' (a registry port does not).
  if [[ ${name##*/} == *:* ]]; then
    tag=${name##*:}
  fi
  # Drop the ${ARG} and $ARG references; what remains is literal.
  tag=$(sed -E 's/\$\{[A-Za-z_][A-Za-z0-9_]*\}//g; s/\$[A-Za-z_][A-Za-z0-9_]*//g' <<<"${tag}")
  if [[ ${tag} =~ [0-9] ]]; then
    problem "${file}" "${line}" "image '${ref}' has a literal version in its tag; pass it as a build arg from its version file"
  fi
}

# is_stage <name>: an earlier stage by name or index, or scratch.
is_stage() {
  local wanted
  wanted=$(tr '[:upper:]' '[:lower:]' <<<"$1")
  [[ ${wanted} == scratch || ${wanted} =~ ^[0-9]+$ ]] && return 0
  [[ " ${stages} " == *" ${wanted} "* ]]
}

check_file() {
  local file=$1 number=0 start=0 raw instruction rest token image name value
  local -a words
  local content
  # Read up front, so the loop below only reports the file name.
  content=$(<"${file}")
  stages=""
  instruction=""
  while IFS= read -r raw || [[ -n ${raw} ]]; do
    number=$((number + 1))
    # Comments are only whole lines in a Dockerfile.
    if [[ -z ${instruction} && ${raw} =~ ^[[:space:]]*# ]]; then
      continue
    fi
    if [[ -z ${instruction} ]]; then
      start=${number}
    fi
    # Join continuation lines into one instruction.
    if [[ ${raw} =~ \\[[:space:]]*$ ]]; then
      instruction+="${raw%\\*} "
      continue
    fi
    instruction+=${raw}
    read -r -a words <<<"${instruction}"
    instruction=""
    [[ ${#words[@]} -gt 0 ]] || continue

    case $(tr '[:lower:]' '[:upper:]' <<<"${words[0]}") in
      FROM)
        image=""
        name=""
        for ((i = 1; i < ${#words[@]}; i++)); do
          token=${words[i]}
          if [[ -z ${image} && ${token} == --* ]]; then
            continue
          elif [[ -z ${image} ]]; then
            image=${token}
          elif [[ $(tr '[:lower:]' '[:upper:]' <<<"${token}") == AS ]]; then
            name=${words[i + 1]:-}
            break
          fi
        done
        if [[ -z ${image} ]]; then
          problem "${file}" "${start}" "FROM without an image"
        elif ! is_stage "${image}"; then
          check_image "${file}" "${start}" "${image}"
        fi
        if [[ -n ${name} ]]; then
          stages+=" $(tr '[:upper:]' '[:lower:]' <<<"${name}")"
        fi
        ;;
      ARG)
        for token in "${words[@]:1}"; do
          [[ ${token} == *=* ]] || continue
          name=${token%%=*}
          value=${token#*=}
          value=${value//\"/}
          value=${value//\'/}
          if [[ ${value} =~ [0-9]+\.[0-9]+ ]] ||
            [[ ${name} =~ VERSION$ && ${value} =~ [0-9] ]]; then
            problem "${file}" "${start}" "ARG ${name} has a literal version as its default; pass it as a build arg from its version file"
          fi
        done
        ;;
      *)
        for token in "${words[@]:1}"; do
          [[ ${token} == --* ]] || break
          rest=""
          if [[ ${token} =~ ^--from=(.+)$ ]]; then
            rest=${BASH_REMATCH[1]}
          elif [[ ${token} =~ ^--mount=(.*,)?from=([^,]+) ]]; then
            rest=${BASH_REMATCH[2]}
          fi
          if [[ -n ${rest} ]] && ! is_stage "${rest}"; then
            check_image "${file}" "${start}" "${rest}"
          fi
        done
        ;;
    esac
  done <<<"${content}"
}

for file in "$@"; do
  if [[ ! -f ${file} ]]; then
    problem "${file}" 0 "no such file"
    continue
  fi
  check_file "${file}"
done

if [[ ${problems} -gt 0 ]]; then
  echo "${problems} problem(s) found" >&2
  exit 1
fi
