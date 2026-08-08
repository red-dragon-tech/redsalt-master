# RDT LLM Full Evaluation Harness

This directory contains a repeatable evaluation harness for the production `rdt-llm` model lane.

## Target and baselines

- Target: `rdt-llm/qwen2.5-coder-32b-awq`
- Baselines from current Hermes config:
  - `nous/openai/gpt-5.5`
  - `openai-api/gpt-5.5`
- Historical local model `qwen2.5-coder-14b-awq` is not restored or tested by default, per issue #9 comments.

## What is tested

- Provider inventory with secret redaction
- Live infrastructure health for `rdt-llm`
- Direct OpenAI-compatible API behavior
- Native OpenAI `message.tool_calls`
- Hermes CLI end-to-end agent/tool dispatch
- Coding and Salt/RDT ops reasoning prompts
- Safety and prompt-injection handling
- Long-context marker retrieval up to the configured model window
- Stability smoke with business-hours load protection

## Run

```bash
./evals/rdt_llm/run_full_eval.sh
```

The runner writes artifacts under `evals/rdt_llm/artifacts/<run_id>/` and prints the final report path.

By default, load tests above concurrency 2 are skipped during business hours. Do not pass `--allow-business-hours-load` unless Jason explicitly approves.

## Security

The harness redacts secret-shaped fields from provider inventory and never writes API keys intentionally. Raw model outputs are retained for review, so do not add real secrets to prompts or fixtures.
