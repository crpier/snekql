#!/usr/bin/env bash
# PROTOTYPE: reproduce issue #245's baseline and compare two readiness designs.
set -euo pipefail

root="$(git rev-parse --show-toplevel)"
cd "$root"

baseline_output="$(mktemp)"
baseline_probe="$(mktemp --suffix=.py)"
trap 'rm -f "$baseline_output" "$baseline_probe"' EXIT
cp prototypes/issue_245/current_negative_probe.txt "$baseline_probe"

if uv run ty check "$baseline_probe" \
  --output-format concise >"$baseline_output" 2>&1; then
  echo "baseline unexpectedly passed" >&2
  exit 1
fi

unused_ignores="$(grep -c 'error\[unused-ignore-comment\]' "$baseline_output")"
if [[ "$unused_ignores" != "11" ]]; then
  cat "$baseline_output" >&2
  echo "expected 11 current-interface escapes, found $unused_ignores" >&2
  exit 1
fi

echo "current interface: 11 guaranteed-incomplete queries are accepted"

uv run ty check \
  prototypes/issue_245/typestate_design.py \
  prototypes/issue_245/typestate_positive.py \
  prototypes/issue_245/typestate_negative.py

echo "private typestate: positive and expected-rejection probes pass"

uv run ty check \
  prototypes/issue_245/nominal_design.py \
  prototypes/issue_245/nominal_positive.py \
  prototypes/issue_245/nominal_negative.py

echo "nominal stages: positive and expected-rejection probes pass"
