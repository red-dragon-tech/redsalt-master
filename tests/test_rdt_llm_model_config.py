from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[1]
REQUESTED_MODEL = "Qwen/Qwen3.5-Coder-32B-Instruct-FP8"
REQUESTED_SERVED_MODEL = "qwen3.5-coder-32b-instruct-fp8"


def rdt_llm_vllm():
    data = yaml.safe_load((ROOT / "pillar" / "minions" / "rdt_llm.sls").read_text())
    return data["vllm"]


def rdt_llm_caddy():
    data = yaml.safe_load((ROOT / "pillar" / "minions" / "rdt_llm.sls").read_text())
    return data["caddy"]


def test_rdt_llm_uses_requested_qwen35_fp8_model():
    vllm = rdt_llm_vllm()

    assert vllm["model"] == REQUESTED_MODEL
    assert vllm["served_model_name"] == REQUESTED_SERVED_MODEL


def test_rdt_llm_uses_64k_hermes_compatibility_runtime_settings():
    vllm = rdt_llm_vllm()

    assert vllm["gpu_memory_utilization"] == 0.92
    assert vllm["max_model_len"] == 64000
    assert vllm["enable_prefix_caching"] is True
    assert vllm["env_vars"]["VLLM_ALLOW_LONG_MAX_MODEL_LEN"] == "1"


def test_rdt_llm_removes_awq_specific_tuning_but_keeps_long_context_scaling():
    vllm = rdt_llm_vllm()
    extra_args = vllm["extra_args"]

    assert "--quantization" not in extra_args
    assert "--cpu-offload-gb" not in extra_args
    assert "--enforce-eager" not in extra_args
    assert "--hf-overrides" in extra_args
    overrides = yaml.safe_load(extra_args[extra_args.index("--hf-overrides") + 1])
    rope = overrides["rope_parameters"]
    assert rope["rope_type"] == "yarn"
    assert rope["factor"] == 4.0
    assert rope["original_max_position_embeddings"] == 32768
    assert "--kv-cache-dtype" in extra_args
    assert extra_args[extra_args.index("--kv-cache-dtype") + 1] == "fp8"


def test_rdt_llm_keeps_native_vllm_tool_call_flags():
    vllm = rdt_llm_vllm()
    extra_args = vllm["extra_args"]

    assert "--enable-auto-tool-choice" in extra_args
    assert "--tool-call-parser" in extra_args
    assert extra_args[extra_args.index("--tool-call-parser") + 1] == "qwen"
    assert "--chat-template" in extra_args


def test_rdt_llm_caddy_serves_new_dns_name_and_legacy_host():
    caddy = rdt_llm_caddy()
    hosts = {server["host"]: server for server in caddy["servers"]}

    assert "llm.ai.rdt.dev" in hosts
    assert "ai.redspectre.rdt.dev" in hosts

    for host in ["llm.ai.rdt.dev", "ai.redspectre.rdt.dev"]:
        assert hosts[host]["upstream"] == "127.0.0.1:8000"
        assert hosts[host]["require_bearer_token"] is True
