#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/../.."
uv run python -m scratchpad.dual_typing_parity.check
uv run python -m scratchpad.dual_typing_parity.evidence
PYTHON_CONTEXT_AWARE_WARNINGS=1 uv run snektest scratchpad/dual_typing_parity
uv run ty check scratchpad/dual_typing_parity --output-format concise
uv run ruff check scratchpad/dual_typing_parity --output-format concise
uv run ruff format --check scratchpad/dual_typing_parity
