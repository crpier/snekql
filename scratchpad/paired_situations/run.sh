#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/../.."
mkdir -p .git/approach-situations
uv run python -m scratchpad.paired_situations.check
uv run python -m scratchpad.paired_situations.check --dual
uv run python -m scratchpad.paired_situations.evolution
uv run python -m scratchpad.paired_situations.evidence
uv run python -m scratchpad.paired_situations.navigation
uv run python -m scratchpad.paired_situations.tour
PYTHON_CONTEXT_AWARE_WARNINGS=1 uv run snektest scratchpad/paired_situations
uv run ty check scratchpad/paired_situations
uv run ruff check scratchpad/paired_situations
uv run ruff format --check scratchpad/paired_situations
