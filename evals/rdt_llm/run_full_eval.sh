#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
RUN_ID="${RUN_ID:-$(date -u +%Y%m%dT%H%M%SZ)}"
SCRIPT="$ROOT/evals/rdt_llm/scripts/rdt_llm_full_eval.py"

cd "$ROOT"
python3 "$SCRIPT" full --run-id "$RUN_ID" "$@"
