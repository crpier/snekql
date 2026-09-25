#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/../.."
uv run python -m scratchpad.dual_descriptors.check
uv run python -m scratchpad.dual_descriptors.evidence
PYTHON_CONTEXT_AWARE_WARNINGS=1 uv run snektest scratchpad/dual_descriptors
uv run ty check scratchpad/dual_descriptors --output-format concise
uv run ruff check scratchpad/dual_descriptors --output-format concise
uv run ruff format --check scratchpad/dual_descriptors
