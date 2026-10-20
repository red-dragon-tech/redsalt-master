> ARCHIVED, HISTORICAL ONLY. Do not run commands or contact endpoints described below. The RDT LLM service has been retired; this directory is retained for traceability, not as an active runbook. This document is intentionally non-operational; old commands and targets are omitted.

# RDT LLM Full Evaluation Harness

This directory contains a repeatable evaluation harness for the production `rdt-llm` model lane.

## Target and baselines

- Target: `rdt-llm/qwen3.5-35b-a3b-gptq-int4`
- Baselines from current Hermes config:
  - `nous/openai/gpt-5.5`
  - `openai-api/gpt-5.5`
- Historical local model `qwen2.5-coder-32b-awq` is not restored or tested by default after the Qwen3.5 GPTQ rollout.

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

## Security
Historical harness behavior and outputs are not current operational guidance. No evaluation entry point is active.
