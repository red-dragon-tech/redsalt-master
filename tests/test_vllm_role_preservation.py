from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[1]


def test_generic_example_node_keeps_llm_vllm_role():
    example = yaml.safe_load((ROOT / "pillar/minions/example-vllm-node.sls").read_text())

    assert example["roles"]["llm_vllm"] is True


def test_generic_llm_vllm_role_keeps_shared_caddy_capability():
    role = yaml.safe_load((ROOT / "states/roles/llm_vllm.sls").read_text())

    assert {"models", "vllm", "caddy"}.issubset(set(role["include"]))


def test_shared_qwen_tool_template_still_prefills_empty_think_block():
    template = (ROOT / "states/vllm/files/qwen25_coder_tool_chat_template.jinja").read_text()

    assert "<think>\\n\\n</think>\\n\\n" in template
