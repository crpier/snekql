#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/../.."
uv run python -m scratchpad.paired_advanced.check
uv run python -m scratchpad.paired_advanced.evidence
PYTHON_CONTEXT_AWARE_WARNINGS=1 uv run snektest scratchpad/paired_advanced
uv run ty check scratchpad/paired_advanced --output-format concise
uv run ruff check scratchpad/paired_advanced --output-format concise
uv run ruff format --check scratchpad/paired_advanced
