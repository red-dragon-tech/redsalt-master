from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[1]
BASELINE_MODEL = "Qwen/Qwen3.5-35B-A3B-GPTQ-Int4"
BASELINE_SERVED = "qwen3.5-35b-a3b-gptq-int4"
CANDIDATE_MODEL = "Qwen/Qwen3.8-27B-FP8"
CANDIDATE_SERVED = "qwen3.8-27b-fp8"


def load_yaml(relpath: str):
    return yaml.safe_load((ROOT / relpath).read_text())


def test_candidate_config_is_not_active_rdt_llm_pillar():
    active = load_yaml("pillar/minions/rdt_llm.sls")["vllm"]

    assert active["model"] == BASELINE_MODEL
    assert active["served_model_name"] == BASELINE_SERVED


def test_qwen38_candidate_config_records_model_and_serving_flags():
    candidate = load_yaml("pillar/candidates/rdt_llm_qwen38_27b_fp8.sls")["vllm_candidate"]
    extra_args = [str(arg) for arg in candidate["extra_args"]]

    assert candidate["model"] == CANDIDATE_MODEL
    assert candidate["served_model_name"] == CANDIDATE_SERVED
    assert candidate["max_model_len"] <= 32768
    assert "--enable-auto-tool-choice" in extra_args
    assert "--tool-call-parser" in extra_args
    assert extra_args[extra_args.index("--tool-call-parser") + 1] == "qwen3_coder"
    assert "--reasoning-parser" in extra_args
    assert extra_args[extra_args.index("--reasoning-parser") + 1] == "qwen3"
    assert "--kv-cache-dtype" in extra_args
    assert extra_args[extra_args.index("--kv-cache-dtype") + 1] == "fp8"
    assert "--hf-overrides" not in extra_args
    assert "--quantization" not in extra_args


def test_qwen38_rollout_runbook_requires_salt_gates_and_rollback():
    text = (ROOT / "docs" / "rdt-qwen38-fp8-candidate-rollout.md").read_text()

    assert "Qwen/Qwen3.8-27B-FP8" in text
    assert "qwen3.8-27b-fp8" in text
    assert "state.show_highstate" in text
    assert "state.apply test=True" in text
    assert BASELINE_MODEL in text
    assert BASELINE_SERVED in text
    assert "Do not apply" in text
