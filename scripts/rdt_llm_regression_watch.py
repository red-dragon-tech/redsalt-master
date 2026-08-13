#!/usr/bin/env python3
"""Small rdt-llm regression watchdog.

Silent on success. Prints an ISSUE line on failure so existing Slack/error-only
ops dispatchers can route the alert. This intentionally runs only the smallest
safe subset of the full eval harness.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
HARNESS = ROOT / "evals" / "rdt_llm" / "scripts" / "rdt_llm_full_eval.py"


def run(args: list[str], timeout: int = 900) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(HARNESS), *args],
        cwd=str(ROOT),
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        timeout=timeout,
        check=False,
    )


def main() -> int:
    run_id = "watchdog"
    failures: list[str] = []
    for command in ["inventory", "infra", "direct-api", "tool-calls", "report"]:
        proc = run([command, "--run-id", run_id, "--target", "rdt-llm:qwen2.5-coder-32b-awq", "--timeout", "240", "--baseline", "rdt-llm:qwen2.5-coder-32b-awq"])
        if proc.returncode != 0:
            failures.append(f"{command} rc={proc.returncode}: {proc.stdout.strip()[-1000:]}")
    status_path = ROOT / "evals" / "rdt_llm" / "artifacts" / run_id / "STATUS"
    status = status_path.read_text(encoding="utf-8").strip() if status_path.exists() else "UNKNOWN"
    if status not in {"PASS", "REVIEW"}:
        failures.append(f"report status={status}")
    if failures:
        print("ISSUE: rdt-llm regression watch failed: " + " | ".join(failures))
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
