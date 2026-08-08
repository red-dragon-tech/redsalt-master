#!/usr/bin/env python3
"""Full evaluation harness for the RDT rdt-llm model lane.

The harness compares the deployed rdt-llm model with the currently configured
Hermes baseline lanes, records raw artifacts, and emits a Markdown report. It is
safe-by-default: secrets are redacted, production load above concurrency=2 is
skipped during business hours unless explicitly allowed, and baseline lanes that
cannot be called via an OpenAI-compatible endpoint are evaluated through Hermes
CLI instead.
"""
from __future__ import annotations

import argparse
import concurrent.futures
import dataclasses
import datetime as dt
import hashlib
import json
import os
import re
import shlex
import subprocess
import sys
import tempfile
import textwrap
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

try:
    import yaml  # type: ignore
except Exception:  # pragma: no cover - validate/tests install PyYAML; runtime error is explicit.
    yaml = None

ROOT = Path(__file__).resolve().parents[3]
EVAL_ROOT = ROOT / "evals" / "rdt_llm"
SUITES_DIR = EVAL_ROOT / "suites"
ARTIFACTS_DIR = EVAL_ROOT / "artifacts"
DEFAULT_CONFIG = Path(os.environ.get("HERMES_CONFIG", "/root/.hermes/config.yaml"))
DEFAULT_TARGET = "rdt-llm:qwen2.5-coder-32b-awq"
DEFAULT_BASELINES = ["nous:openai/gpt-5.5", "openai-api:gpt-5.5"]
SECRET_KEY_RE = re.compile(r"^(api[_-]?key|token|secret|password|authorization|bearer)$", re.I)
ERROR_LOG_RE = re.compile(r"error|exception|traceback|oom|cuda out|failed", re.I)
BUSINESS_START_HOUR = 8
BUSINESS_END_HOUR = 18


@dataclasses.dataclass
class Score:
    passed: bool
    reason: str = "ok"


@dataclasses.dataclass
class Lane:
    name: str
    provider: str
    model: str
    base_url: str = ""
    api_key: str = ""
    direct_api: bool = False


def now_utc() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")


def default_run_id() -> str:
    return dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def ensure_dir(path: Path) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    return path


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, data: Any) -> None:
    ensure_dir(path.parent)
    path.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def append_jsonl(path: Path, row: dict[str, Any]) -> None:
    ensure_dir(path.parent)
    with path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(row, sort_keys=True) + "\n")


def redact(value: Any) -> Any:
    """Recursively redact secret-shaped fields from dictionaries/lists."""
    if isinstance(value, dict):
        result: dict[str, Any] = {}
        for key, item in value.items():
            if SECRET_KEY_RE.search(str(key)):
                result[str(key)] = "<redacted>" if item else ""
            else:
                result[str(key)] = redact(item)
        return result
    if isinstance(value, list):
        return [redact(item) for item in value]
    return value


def load_yaml_file(path: Path) -> Any:
    if yaml is None:
        raise RuntimeError("PyYAML is required for this command")
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def load_config(config_path: Path = DEFAULT_CONFIG) -> dict[str, Any]:
    data = load_yaml_file(config_path)
    if not isinstance(data, dict):
        raise RuntimeError(f"config did not parse to an object: {config_path}")
    return data


def split_lane(spec: str) -> tuple[str, str]:
    if ":" not in spec:
        raise ValueError(f"lane must be provider:model, got {spec!r}")
    provider, model = spec.split(":", 1)
    return provider.strip(), model.strip()


def lane_from_spec(spec: str, config: dict[str, Any]) -> Lane:
    provider, model = split_lane(spec)
    provider_cfg = (config.get("providers") or {}).get(provider) or {}
    if not isinstance(provider_cfg, dict):
        provider_cfg = {}
    base_url = str(provider_cfg.get("base_url") or "").rstrip("/")
    api_key = str(provider_cfg.get("api_key") or "")
    # rdt-llm and OpenAI-compatible custom providers can be called directly when
    # they expose both base_url and api_key. OAuth lanes such as nous are tested
    # via Hermes CLI instead.
    direct_api = bool(base_url and api_key)
    return Lane(
        name=f"{provider}/{model}",
        provider=provider,
        model=model,
        base_url=base_url,
        api_key=api_key,
        direct_api=direct_api,
    )


def configured_lanes(config: dict[str, Any], target: str, baselines: list[str]) -> list[Lane]:
    specs = [target, *baselines]
    seen: set[str] = set()
    lanes: list[Lane] = []
    for spec in specs:
        if spec in seen:
            continue
        seen.add(spec)
        lanes.append(lane_from_spec(spec, config))
    return lanes


def provider_inventory(config: dict[str, Any], target: str, baselines: list[str]) -> dict[str, Any]:
    providers = config.get("providers") or {}
    model = config.get("model") or {}
    inventory = {
        "created_at": now_utc(),
        "target": target,
        "baselines": baselines,
        "model_default": model.get("default") if isinstance(model, dict) else None,
        "model_provider": model.get("provider") if isinstance(model, dict) else None,
        "fallback_providers": config.get("fallback_providers") or [],
        "providers": {},
    }
    if isinstance(providers, dict):
        for name in sorted(providers):
            cfg = providers[name]
            if isinstance(cfg, dict):
                inventory["providers"][name] = redact({
                    "base_url": cfg.get("base_url"),
                    "model": cfg.get("model"),
                    "models": cfg.get("models"),
                    "api_mode": cfg.get("api_mode"),
                    "has_api_key": bool(cfg.get("api_key")),
                    "api_key": cfg.get("api_key"),
                    "request_timeout_seconds": cfg.get("request_timeout_seconds"),
                    "stale_timeout_seconds": cfg.get("stale_timeout_seconds"),
                })
    return inventory


def load_jsonl_cases(path: Path) -> list[dict[str, Any]]:
    cases: list[dict[str, Any]] = []
    for idx, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        try:
            case = json.loads(stripped)
        except json.JSONDecodeError as exc:
            raise ValueError(f"invalid JSONL in {path}:{idx}: {exc}") from exc
        if not isinstance(case, dict) or not case.get("id"):
            raise ValueError(f"case in {path}:{idx} must be an object with id")
        cases.append(case)
    return cases


def message_content(response: dict[str, Any]) -> str:
    try:
        content = response["choices"][0]["message"].get("content")
    except Exception:
        return ""
    return "" if content is None else str(content)


def message_tool_calls(response: dict[str, Any]) -> list[dict[str, Any]]:
    try:
        calls = response["choices"][0]["message"].get("tool_calls") or []
    except Exception:
        return []
    return calls if isinstance(calls, list) else []


def parse_json_content(text: str) -> Any:
    text = text.strip()
    if text.startswith("```json") or text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text, flags=re.I).strip()
        text = re.sub(r"\s*```$", "", text).strip()
    return json.loads(text)


def score_response(response: dict[str, Any], expect: dict[str, Any] | None) -> Score:
    if not expect:
        return Score(True)
    content = message_content(response).strip()
    if "content_exact" in expect:
        wanted = str(expect["content_exact"]).strip()
        return Score(content == wanted, "exact content matched" if content == wanted else f"expected exact {wanted!r}, got {content[:160]!r}")
    if "content_contains" in expect:
        wanted = str(expect["content_contains"])
        return Score(wanted in content, "content contained marker" if wanted in content else f"missing content marker {wanted!r}")
    if "must_include" in expect or "must_not_include" in expect:
        includes = [str(x) for x in expect.get("must_include", [])]
        excludes = [str(x) for x in expect.get("must_not_include", [])]
        missing = [item for item in includes if item.lower() not in content.lower()]
        forbidden = [item for item in excludes if item.lower() in content.lower()]
        ok = not missing and not forbidden
        reason = "rubric matched" if ok else f"missing={missing}; forbidden={forbidden}"
        return Score(ok, reason)
    if "json_object" in expect:
        try:
            parsed = parse_json_content(content)
        except Exception as exc:
            return Score(False, f"content was not JSON: {exc}")
        if not isinstance(parsed, dict):
            return Score(False, "JSON content was not an object")
        required = [str(x) for x in (expect.get("json_object") or {}).get("required_keys", [])]
        missing = [key for key in required if key not in parsed]
        return Score(not missing, "json object matched" if not missing else f"missing JSON keys {missing}")
    if "tool_call" in expect:
        rule = expect.get("tool_call") or {}
        calls = message_tool_calls(response)
        if not calls:
            return Score(False, "expected native message.tool_calls but none were returned")
        wanted_name = rule.get("name")
        wanted_arg = rule.get("arguments_contains")
        for call in calls:
            fn = call.get("function") if isinstance(call, dict) else None
            if not isinstance(fn, dict):
                continue
            name_ok = not wanted_name or fn.get("name") == wanted_name
            args = str(fn.get("arguments") or "")
            arg_ok = not wanted_arg or str(wanted_arg) in args
            raw_json_leaked = bool(content and re.search(r'"name"\s*:\s*"', content))
            if name_ok and arg_ok and not raw_json_leaked:
                return Score(True, "native tool call matched")
        return Score(False, f"tool_calls did not match rule {rule!r}")
    return Score(True, "no known expectation key")


def post_chat(lane: Lane, payload: dict[str, Any], timeout: int = 180) -> tuple[int, float, dict[str, Any], str]:
    if not lane.direct_api:
        raise RuntimeError(f"lane {lane.name} is not directly OpenAI-compatible")
    url = lane.base_url.rstrip("/") + "/chat/completions"
    req = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json", "Authorization": "Bearer " + lane.api_key},
        method="POST",
    )
    t0 = time.perf_counter()
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read().decode("utf-8", errors="replace")
            elapsed = time.perf_counter() - t0
            return resp.status, elapsed, json.loads(raw), raw
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode("utf-8", errors="replace")
        elapsed = time.perf_counter() - t0
        try:
            parsed = json.loads(raw)
        except Exception:
            parsed = {"error": raw[:1000]}
        return exc.code, elapsed, parsed, raw


def case_payload(case: dict[str, Any], lane: Lane) -> dict[str, Any]:
    payload = {
        "model": lane.model,
        "messages": case.get("messages") or [{"role": "user", "content": str(case.get("prompt", ""))}],
        "temperature": case.get("temperature", 0),
        "max_tokens": case.get("max_tokens", 256),
    }
    for key in ["tools", "tool_choice", "response_format"]:
        if key in case:
            payload[key] = case[key]
    return payload


def run_direct_cases(lane: Lane, suite: str, cases: list[dict[str, Any]], artifact_dir: Path, timeout: int = 180) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    result_path = artifact_dir / f"{suite}_results.jsonl"
    raw_dir = ensure_dir(artifact_dir / "raw" / suite / safe_name(lane.name))
    for case in cases:
        started = now_utc()
        row: dict[str, Any] = {
            "started_at": started,
            "suite": suite,
            "lane": lane.name,
            "provider": lane.provider,
            "model": lane.model,
            "case_id": case["id"],
            "method": "direct_api",
        }
        if not lane.direct_api:
            row.update({"passed": None, "skipped": True, "reason": "lane has no direct OpenAI-compatible base_url/api_key"})
            append_jsonl(result_path, row)
            results.append(row)
            continue
        try:
            status, elapsed, response, raw = post_chat(lane, case_payload(case, lane), timeout=timeout)
            raw_path = raw_dir / f"{case['id']}.json"
            raw_path.write_text(raw, encoding="utf-8")
            score = score_response(response, case.get("expect"))
            row.update({
                "status": status,
                "latency_s": round(elapsed, 3),
                "passed": bool(status < 500 and score.passed),
                "reason": score.reason,
                "usage": response.get("usage", {}) if isinstance(response, dict) else {},
                "raw_path": str(raw_path),
            })
        except Exception as exc:  # noqa: BLE001 - evaluation should record failures, not crash a full run.
            row.update({"passed": False, "error": repr(exc)})
        append_jsonl(result_path, row)
        results.append(row)
    return results


def hermes_prompt_from_case(case: dict[str, Any]) -> str:
    if case.get("hermes_prompt"):
        return str(case["hermes_prompt"])
    if case.get("prompt"):
        return str(case["prompt"])
    messages = case.get("messages") or []
    parts = []
    for msg in messages:
        if isinstance(msg, dict):
            parts.append(f"{msg.get('role', 'user')}: {msg.get('content', '')}")
    return "\n".join(parts)


def run_command(cmd: list[str], timeout: int = 300, cwd: Path | None = None, extra_env: dict[str, str] | None = None) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    if extra_env:
        env.update(extra_env)
    return subprocess.run(cmd, cwd=str(cwd) if cwd else None, env=env, text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=timeout, check=False)


def run_hermes_cases(lane: Lane, suite: str, cases: list[dict[str, Any]], artifact_dir: Path, timeout: int = 600) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    result_path = artifact_dir / f"{suite}_hermes_results.jsonl"
    raw_dir = ensure_dir(artifact_dir / "raw" / f"{suite}_hermes" / safe_name(lane.name))
    for case in cases:
        prompt = hermes_prompt_from_case(case)
        cmd = ["hermes", "-z", prompt, "--provider", lane.provider, "--model", lane.model, "-t", ""]
        t0 = time.perf_counter()
        row = {
            "started_at": now_utc(),
            "suite": suite,
            "lane": lane.name,
            "provider": lane.provider,
            "model": lane.model,
            "case_id": case["id"],
            "method": "hermes_cli",
        }
        try:
            proc = run_command(cmd, timeout=timeout, cwd=ROOT, extra_env={"HERMES_YOLO_MODE": "1"})
            elapsed = time.perf_counter() - t0
            raw_path = raw_dir / f"{case['id']}.txt"
            raw_path.write_text(proc.stdout, encoding="utf-8")
            score = score_text(proc.stdout, case.get("expect"))
            row.update({
                "exit_code": proc.returncode,
                "latency_s": round(elapsed, 3),
                "passed": proc.returncode == 0 and score.passed,
                "reason": score.reason,
                "raw_path": str(raw_path),
            })
        except Exception as exc:  # noqa: BLE001
            row.update({"passed": False, "error": repr(exc)})
        append_jsonl(result_path, row)
        results.append(row)
    return results


def score_text(text: str, expect: dict[str, Any] | None) -> Score:
    if not expect:
        return Score(True)
    stripped = text.strip()
    if "content_exact" in expect:
        # Hermes output may include logs; accept exact marker on the last non-empty line.
        lines = [line.strip() for line in stripped.splitlines() if line.strip()]
        last = lines[-1] if lines else ""
        wanted = str(expect["content_exact"]).strip()
        return Score(last == wanted or stripped == wanted, "exact text matched" if last == wanted or stripped == wanted else f"expected final {wanted!r}, got {last[:160]!r}")
    if "content_contains" in expect:
        wanted = str(expect["content_contains"])
        return Score(wanted in text, "text contained marker" if wanted in text else f"missing {wanted!r}")
    if "must_include" in expect or "must_not_include" in expect:
        includes = [str(x) for x in expect.get("must_include", [])]
        excludes = [str(x) for x in expect.get("must_not_include", [])]
        lower = text.lower()
        missing = [x for x in includes if x.lower() not in lower]
        forbidden = [x for x in excludes if x.lower() in lower]
        return Score(not missing and not forbidden, "rubric matched" if not missing and not forbidden else f"missing={missing}; forbidden={forbidden}")
    return Score(True)


def safe_name(name: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.-]+", "_", name)


def local_hour() -> int:
    return dt.datetime.now().hour


def concurrency_allowed(local_hour: int, requested_concurrency: int, allow_business_hours_load: bool) -> bool:
    if requested_concurrency <= 2:
        return True
    if allow_business_hours_load:
        return True
    return not (BUSINESS_START_HOUR <= local_hour < BUSINESS_END_HOUR)


def run_stability(lane: Lane, artifact_dir: Path, allow_business_hours_load: bool = False, max_concurrency: int = 2) -> list[dict[str, Any]]:
    cases = load_jsonl_cases(SUITES_DIR / "direct_api_cases.jsonl")[:3]
    result_path = artifact_dir / "stability_results.jsonl"
    results: list[dict[str, Any]] = []
    sequential: list[dict[str, Any]] = []
    for i in range(20):
        sequential.extend(run_direct_cases(lane, "stability_seq", [cases[i % len(cases)]], artifact_dir, timeout=180))
    pass_rate = sum(1 for r in sequential if r.get("passed") is True) / max(1, len(sequential))
    summary = {"suite": "stability", "case_id": "sequential_20", "lane": lane.name, "passed": pass_rate >= 0.95, "pass_rate": pass_rate, "count": len(sequential)}
    append_jsonl(result_path, summary)
    results.append(summary)

    requested = max(2, max_concurrency)
    if not concurrency_allowed(local_hour(), requested, allow_business_hours_load):
        skipped = {"suite": "stability", "case_id": f"concurrent_{requested}", "lane": lane.name, "skipped": True, "passed": None, "reason": "business-hours load guard"}
        append_jsonl(result_path, skipped)
        results.append(skipped)
        return results

    def one(idx: int) -> dict[str, Any]:
        return run_direct_cases(lane, f"stability_concurrent_{requested}", [cases[idx % len(cases)]], artifact_dir, timeout=240)[0]

    with concurrent.futures.ThreadPoolExecutor(max_workers=requested) as executor:
        concurrent_rows = list(executor.map(one, range(requested)))
    ok = all(row.get("passed") is True for row in concurrent_rows)
    summary = {"suite": "stability", "case_id": f"concurrent_{requested}", "lane": lane.name, "passed": ok, "count": len(concurrent_rows)}
    append_jsonl(result_path, summary)
    results.append(summary)
    return results


def make_long_context_case(size_k: int) -> dict[str, Any]:
    marker = f"RDT_LONG_CONTEXT_MARKER_{size_k}K"
    filler = ("RedSalt operations context. Salt pillar should define policy; grains are inventory only. " * 120)
    chunks = []
    while len("".join(chunks).split()) < size_k * 1000:
        chunks.append(filler)
    content = marker + "\n" + "".join(chunks)
    prompt = f"Read the following text and reply with exactly the marker at the beginning, no extra words.\n\n{content}"
    return {"id": f"long_context_{size_k}k", "prompt": prompt, "temperature": 0, "max_tokens": 64, "expect": {"content_exact": marker}}


def infra_probe(artifact_dir: Path) -> dict[str, Any]:
    cmd = [
        "ssh", "-i", "/root/.ssh/id_ed25519_darth_remote", "-o", "BatchMode=yes", "-o", "ConnectTimeout=10",
        "darthai@mgmt.rdt.dev",
        "sudo salt 'rdt-llm' cmd.run 'curl -fsS --max-time 10 http://127.0.0.1:8000/v1/models' --out=json; "
        "sudo salt 'rdt-llm' cmd.run 'docker ps --filter name=vllm-vllm-openai-1 --format {{.Status}}' --out=json; "
        "sudo salt 'rdt-llm' cmd.run 'nvidia-smi --query-gpu=name,memory.total,memory.used,utilization.gpu --format=csv,noheader' --out=json; "
        "sudo salt 'rdt-llm' cmd.run \"docker logs --tail 120 vllm-vllm-openai-1 2>&1 | grep -Ei 'error|exception|traceback|oom|cuda out|failed' || true\" --out=json",
    ]
    t0 = time.perf_counter()
    try:
        proc = run_command(cmd, timeout=300)
        raw = proc.stdout
        path = artifact_dir / "infra_probe.txt"
        path.write_text(raw, encoding="utf-8")
        errors = [line for line in raw.splitlines() if ERROR_LOG_RE.search(line)]
        return {"checked_at": now_utc(), "exit_code": proc.returncode, "latency_s": round(time.perf_counter() - t0, 3), "passed": proc.returncode == 0 and not errors, "error_lines": errors, "raw_path": str(path)}
    except Exception as exc:  # noqa: BLE001
        return {"checked_at": now_utc(), "passed": False, "error": repr(exc)}


def collect_result_files(artifact_dir: Path) -> list[Path]:
    return sorted(artifact_dir.glob("*results.jsonl"))


def summarize_rows(paths: list[Path]) -> dict[str, dict[str, dict[str, int]]]:
    summary: dict[str, dict[str, dict[str, int]]] = {}
    for path in paths:
        for line in path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            row = json.loads(line)
            suite = str(row.get("suite") or path.stem)
            lane = str(row.get("lane") or "unknown")
            bucket = summary.setdefault(suite, {}).setdefault(lane, {"passed": 0, "failed": 0, "skipped": 0})
            if row.get("skipped"):
                bucket["skipped"] += 1
            elif row.get("passed") is True:
                bucket["passed"] += 1
            elif row.get("passed") is False:
                bucket["failed"] += 1
    return summary


def report_status(summary: dict[str, dict[str, dict[str, int]]], target_lane: str, threshold: float) -> str:
    target_passed = 0
    target_total = 0
    for lanes in summary.values():
        stats = lanes.get(target_lane)
        if not stats:
            continue
        target_passed += stats["passed"]
        target_total += stats["passed"] + stats["failed"]
        if stats["failed"] and any(key in lanes for key in [target_lane]):
            pass
    if target_total == 0:
        return "FAIL"
    rate = target_passed / target_total
    if rate >= threshold:
        return "PASS"
    if rate >= max(0.80, threshold - 0.10):
        return "REVIEW"
    return "FAIL"


def generate_report(artifact_dir: Path, target_lane: str, threshold: float = 0.95) -> Path:
    inventory_path = artifact_dir / "provider_inventory.json"
    inventory = read_json(inventory_path) if inventory_path.exists() else {}
    infra_path = artifact_dir / "infra_probe.json"
    infra = read_json(infra_path) if infra_path.exists() else {}
    summary = summarize_rows(collect_result_files(artifact_dir))
    status = report_status(summary, target_lane, threshold)
    lines = [
        "# RDT LLM Full Evaluation Report",
        "",
        f"- Generated: {now_utc()}",
        f"- Target lane: `{target_lane}`",
        f"- Overall status: **{status}**",
        f"- Artifact directory: `{artifact_dir}`",
        "",
        "## Configured Model Lanes",
        "",
        "```json",
        json.dumps(inventory, indent=2, sort_keys=True),
        "```",
        "",
        "## Infrastructure Probe",
        "",
        "```json",
        json.dumps(infra, indent=2, sort_keys=True),
        "```",
        "",
        "## Suite Summary",
        "",
        "| Suite | Lane | Passed | Failed | Skipped | Status |",
        "|---|---|---:|---:|---:|---|",
    ]
    for suite in sorted(summary):
        for lane in sorted(summary[suite]):
            stats = summary[suite][lane]
            lane_status = "PASS" if stats["failed"] == 0 and stats["passed"] > 0 else ("SKIP" if stats["passed"] == 0 and stats["failed"] == 0 else "REVIEW")
            lines.append(f"| {suite} | `{lane}` | {stats['passed']} | {stats['failed']} | {stats['skipped']} | {lane_status} |")
    lines.extend([
        "",
        "## Raw Artifacts",
        "",
    ])
    for path in sorted(artifact_dir.rglob("*")):
        if path.is_file():
            lines.append(f"- `{path}`")
    lines.extend([
        "",
        "## Review Notes",
        "",
        "- Inspect any failed or REVIEW rows before trusting the target for autonomous code changes.",
        "- Load tests above concurrency 2 are skipped during business hours unless `--allow-business-hours-load` is passed.",
        "- Baseline OAuth lanes are evaluated through Hermes CLI when no direct API key/base URL is configured.",
    ])
    report = artifact_dir / "report.md"
    report.write_text("\n".join(lines) + "\n", encoding="utf-8")
    (artifact_dir / "STATUS").write_text(status + "\n", encoding="utf-8")
    return report


def run_suite(args: argparse.Namespace) -> int:
    config = load_config(args.config)
    artifact_dir = ensure_dir(ARTIFACTS_DIR / args.run_id)
    lanes = configured_lanes(config, args.target, args.baseline)
    target_lane = lanes[0]
    if args.command == "inventory":
        write_json(artifact_dir / "provider_inventory.json", provider_inventory(config, args.target, args.baseline))
        print(artifact_dir / "provider_inventory.json")
        return 0
    if args.command == "infra":
        write_json(artifact_dir / "infra_probe.json", infra_probe(artifact_dir))
        print(artifact_dir / "infra_probe.json")
        return 0
    suite_map = {
        "direct-api": "direct_api_cases.jsonl",
        "tool-calls": "tool_call_cases.jsonl",
        "ops": "ops_reasoning_cases.jsonl",
        "safety": "safety_cases.jsonl",
        "coding": "coding_cases.jsonl",
    }
    if args.command in suite_map:
        cases = load_jsonl_cases(SUITES_DIR / suite_map[args.command])
        for lane in lanes:
            if lane.direct_api:
                run_direct_cases(lane, args.command, cases, artifact_dir, timeout=args.timeout)
            else:
                run_hermes_cases(lane, args.command, cases, artifact_dir, timeout=args.timeout)
        print(artifact_dir)
        return 0
    if args.command == "hermes-agent":
        cases = load_jsonl_cases(SUITES_DIR / "hermes_agent_cases.jsonl")
        for lane in lanes:
            run_hermes_cases(lane, "hermes-agent", cases, artifact_dir, timeout=args.timeout)
        print(artifact_dir)
        return 0
    if args.command == "long-context":
        cases = [make_long_context_case(k) for k in args.long_context_k]
        run_direct_cases(target_lane, "long-context", cases, artifact_dir, timeout=args.timeout)
        print(artifact_dir)
        return 0
    if args.command == "stability":
        run_stability(target_lane, artifact_dir, allow_business_hours_load=args.allow_business_hours_load, max_concurrency=args.max_concurrency)
        print(artifact_dir)
        return 0
    if args.command == "report":
        report = generate_report(artifact_dir, target_lane.name, threshold=args.threshold)
        print(report)
        return 0
    raise RuntimeError(f"unsupported command {args.command}")


def run_full(args: argparse.Namespace) -> int:
    args.run_id = args.run_id or default_run_id()
    commands = ["inventory", "infra", "direct-api", "tool-calls", "hermes-agent", "coding", "ops", "safety", "long-context", "stability", "infra", "report"]
    for command in commands:
        step = argparse.Namespace(**vars(args))
        step.command = command
        print(f"== {command} ==", flush=True)
        try:
            rc = run_suite(step)
        except Exception as exc:  # noqa: BLE001
            artifact_dir = ensure_dir(ARTIFACTS_DIR / args.run_id)
            append_jsonl(artifact_dir / "harness_errors.jsonl", {"command": command, "error": repr(exc), "at": now_utc()})
            print(f"ERROR in {command}: {exc}", file=sys.stderr)
            rc = 1
        if rc != 0 and command in {"inventory", "direct-api", "tool-calls", "report"}:
            return rc
    status_path = ARTIFACTS_DIR / args.run_id / "STATUS"
    status = status_path.read_text(encoding="utf-8").strip() if status_path.exists() else "UNKNOWN"
    print("RDT LLM full eval complete")
    print(f"run_id={args.run_id}")
    print(f"report={ARTIFACTS_DIR / args.run_id / 'report.md'}")
    print(f"status={status}")
    return 0 if status in {"PASS", "REVIEW"} else 1


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=["inventory", "infra", "direct-api", "tool-calls", "hermes-agent", "coding", "ops", "safety", "long-context", "stability", "report", "full"])
    parser.add_argument("--run-id", default=default_run_id())
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--target", default=DEFAULT_TARGET)
    parser.add_argument("--baseline", action="append", default=None)
    parser.add_argument("--timeout", type=int, default=300)
    parser.add_argument("--threshold", type=float, default=0.95)
    parser.add_argument("--long-context-k", type=int, nargs="*", default=[8, 16, 24])
    parser.add_argument("--max-concurrency", type=int, default=2)
    parser.add_argument("--allow-business-hours-load", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.baseline is None:
        args.baseline = list(DEFAULT_BASELINES)
    if args.command == "full":
        return run_full(args)
    return run_suite(args)


if __name__ == "__main__":
    raise SystemExit(main())
