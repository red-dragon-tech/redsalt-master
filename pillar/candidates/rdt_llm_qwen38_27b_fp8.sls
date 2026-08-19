# Candidate-only vLLM configuration for evaluating Qwen3.8 on rdt-llm.
# This file is intentionally not included by pillar/top.sls and does not affect
# live minions until an operator explicitly copies/references it in a reviewed
# rollout branch.

vllm_candidate:
  model: Qwen/Qwen3.8-27B-FP8
  served_model_name: qwen3.8-27b-fp8
  strategy: same-host-blue-green-test-window
  baseline_model: Qwen/Qwen3.5-35B-A3B-GPTQ-Int4
  baseline_served_model_name: qwen3.5-35b-a3b-gptq-int4
  port: 8000
  bind_host: 127.0.0.1
  host: 0.0.0.0
  gpu_count: all
  gpu_memory_utilization: 0.90
  max_model_len: 32768
  tensor_parallel_size: 1
  enable_prefix_caching: true
  trust_remote_code: false
  env_vars:
    VLLM_ALLOW_LONG_MAX_MODEL_LEN: '1'
  extra_args:
    - --dtype
    - bfloat16
    - --kv-cache-dtype
    - fp8
    - --max-num-batched-tokens
    - '4096'
    - --enable-auto-tool-choice
    - --tool-call-parser
    - qwen3_coder
    - --reasoning-parser
    - qwen3
  required_validation:
    - state.show_highstate
    - state.apply test=True
    - /v1/models shows qwen3.8-27b-fp8
    - native OpenAI message.tool_calls pass
    - rdt-llm smoke/readiness pass
  rollback:
    model: Qwen/Qwen3.5-35B-A3B-GPTQ-Int4
    served_model_name: qwen3.5-35b-a3b-gptq-int4
