#!/usr/bin/env bash
# PROTOTYPE: reproduce issue #246's baseline and compare both type designs.
set -euo pipefail

root="$(git rev-parse --show-toplevel)"
cd "$root"

baseline_output="$(mktemp)"
baseline_probe="$(mktemp --suffix=.py)"
trap 'rm -f "$baseline_output" "$baseline_probe"' EXIT
cp prototypes/issue_246/current_negative_probe.txt "$baseline_probe"

uv run ty check prototypes/issue_246/current_positive.py

echo "current interface: model, projection, and returning inference pass"

if uv run ty check "$baseline_probe" \
  --output-format concise >"$baseline_output" 2>&1; then
  echo "baseline unexpectedly passed" >&2
  exit 1
fi

unused_ignores="$(grep -c 'error\[unused-ignore-comment\]' "$baseline_output")"
if [[ "$unused_ignores" != "27" ]]; then
  cat "$baseline_output" >&2
  echo "expected 27 current-interface escapes, found $unused_ignores" >&2
  exit 1
fi

echo "current interface: 27 cross-family expectations are not enforced"

uv run ty check \
  prototypes/issue_246/facade_design.py \
  prototypes/issue_246/facade_positive.py \
  prototypes/issue_246/facade_negative.py

echo "namespace facades: positive and expected-rejection probes pass"

uv run ty check \
  prototypes/issue_246/propagated_design.py \
  prototypes/issue_246/propagated_positive.py \
  prototypes/issue_246/propagated_negative.py

echo "propagated witness: positive and expected-rejection probes pass"
