from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[1]


def rdt_llm_vllm():
    data = yaml.safe_load((ROOT / "pillar" / "minions" / "rdt_llm.sls").read_text())
    return data["vllm"]


def rdt_llm_caddy():
    data = yaml.safe_load((ROOT / "pillar" / "minions" / "rdt_llm.sls").read_text())
    return data["caddy"]


def test_rdt_llm_canary_advertises_hermes_minimum_context():
    vllm = rdt_llm_vllm()

    assert vllm["max_model_len"] >= 64000
    assert vllm["env_vars"]["VLLM_ALLOW_LONG_MAX_MODEL_LEN"] == "1"


def test_rdt_llm_canary_enables_qwen_yarn_context_extension():
    vllm = rdt_llm_vllm()
    extra_args = vllm["extra_args"]

    assert "--hf-overrides" in extra_args
    overrides = yaml.safe_load(extra_args[extra_args.index("--hf-overrides") + 1])
    rope = overrides["rope_parameters"]
    assert rope["rope_type"] == "yarn"
    assert rope["factor"] == 4.0
    assert rope["original_max_position_embeddings"] == 32768


def test_rdt_llm_canary_uses_fp8_kv_cache_to_reduce_vram_pressure():
    vllm = rdt_llm_vllm()
    extra_args = vllm["extra_args"]

    assert "--kv-cache-dtype" in extra_args
    assert extra_args[extra_args.index("--kv-cache-dtype") + 1] == "fp8"


def test_rdt_llm_caddy_serves_new_dns_name_and_legacy_host():
    caddy = rdt_llm_caddy()
    hosts = {server["host"]: server for server in caddy["servers"]}

    assert "llm.ai.rdt.dev" in hosts
    assert "ai.redspectre.rdt.dev" in hosts

    for host in ["llm.ai.rdt.dev", "ai.redspectre.rdt.dev"]:
        assert hosts[host]["upstream"] == "127.0.0.1:8000"
        assert hosts[host]["require_bearer_token"] is True
