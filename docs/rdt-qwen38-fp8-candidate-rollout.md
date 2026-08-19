# RDT Qwen3.8 FP8 candidate rollout

This document prepares a candidate evaluation for `Qwen/Qwen3.8-27B-FP8` on the existing single-host `rdt-llm` vLLM service. It does not authorize applying the model change.

## Candidate

- Candidate backend model: `Qwen/Qwen3.8-27B-FP8`
- Candidate served model name: `qwen3.8-27b-fp8`
- Baseline backend model: `Qwen/Qwen3.5-35B-A3B-GPTQ-Int4`
- Baseline served model name: `qwen3.5-35b-a3b-gptq-int4`
- Candidate pillar reference: `pillar/candidates/rdt_llm_qwen38_27b_fp8.sls`

The candidate pillar file is intentionally not included by `pillar/top.sls`. It is a reviewed reference for a later controlled swap branch.

## Why FP8 first

The host currently serves one model at high GPU utilization. FP8 is the safer first candidate than full `Qwen/Qwen3.8-27B` because it is more likely to fit on the existing host with useful context and less likely to require large reductions in throughput.

## Do not apply yet

Do not apply this candidate directly. Do not edit live pillar or restart vLLM from this runbook. A live swap requires separate approval and a controlled window.

## Pre-swap validation

Before any live model-serving change, confirm the candidate model is publicly resolvable and validate Salt rendering/dry-run behavior:

```bash
python3 - <<'PY'
import urllib.request
for model in ['Qwen/Qwen3.8-27B-FP8', 'Qwen/Qwen3.5-35B-A3B-GPTQ-Int4']:
    url = 'https://huggingface.co/api/models/' + model
    with urllib.request.urlopen(url, timeout=20) as r:
        print(model, 'api_status=', r.status)
PY

salt rdt-llm state.show_highstate
salt rdt-llm state.apply test=True
```

The Salt gates must show zero failures before any real apply.

## Candidate vLLM flags to validate

The candidate config uses:

```text
--dtype bfloat16
--kv-cache-dtype fp8
--max-num-batched-tokens 4096
--enable-auto-tool-choice
--tool-call-parser qwen3_coder
--reasoning-parser qwen3
```

These are candidate assumptions and must be validated against the actual running `vllm/vllm-openai` image. If the image rejects `qwen3_coder` or `--reasoning-parser qwen3`, stop and update the candidate config; do not guess with prompt-side workarounds.

## Baseline capture

Before the swap, capture Qwen3.5 baseline artifacts:

```bash
rdt-llm-smoke
rdt-llm-readiness --runs 3
hermes-phase2-issue-triage-batch red-dragon-tech/hermes 3 8 10 12 14 --json --fail-on-mismatch
hermes-phase2-test100 --fail-on-mismatch
```

Current baseline artifacts are under:

```text
/opt/shared/repos/hermes/artifacts/rdt-llm-candidate-models/qwen3.8-27b-fp8-baseline/
```

## Candidate validation after swap

After a controlled Qwen3.8 test swap, run:

```bash
rdt-llm-smoke
rdt-llm-readiness --runs 3
hermes-phase2-issue-triage-batch red-dragon-tech/hermes 3 8 10 12 14 --json --fail-on-mismatch
hermes-phase2-test100 --fail-on-mismatch
```

Promotion requires:

- `/v1/models` shows `qwen3.8-27b-fp8`;
- direct exact completion passes;
- native OpenAI `message.tool_calls` pass;
- no pseudo-tool-call plain text appears;
- Hermes terminal/tool probe passes;
- Phase 2 issue triage batch passes;
- Phase 2 routing smoke has no dangerous false-local routes;
- no material latency, OOM, or restart instability appears.

## Rollback

Rollback target:

- `Qwen/Qwen3.5-35B-A3B-GPTQ-Int4`
- `qwen3.5-35b-a3b-gptq-int4`

After rollback, verify:

```bash
rdt-llm-smoke
rdt-llm-readiness --runs 1
curl -fsS https://llm.ai.rdt.dev/v1/models
```

Record candidate results and any rollback in Hermes issue #31.
