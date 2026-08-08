import importlib.util
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / "evals" / "rdt_llm" / "scripts" / "rdt_llm_full_eval.py"


def load_module():
    spec = importlib.util.spec_from_file_location("rdt_llm_full_eval", MODULE_PATH)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    import sys
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_redact_secrets_recursively():
    mod = load_module()
    data = {
        "api_key": "should-not-leak",
        "nested": {"token": "also-secret", "model": "qwen2.5-coder-32b-awq"},
        "items": [{"password": "hidden"}, {"base_url": "https://example.test/v1"}],
    }

    data["has_api_key"] = True

    redacted = mod.redact(data)

    assert redacted["api_key"] == "<redacted>"
    assert redacted["has_api_key"] is True
    assert redacted["nested"]["token"] == "<redacted>"
    assert redacted["nested"]["model"] == "qwen2.5-coder-32b-awq"
    assert redacted["items"][0]["password"] == "<redacted>"
    assert redacted["items"][1]["base_url"] == "https://example.test/v1"


def test_score_content_exact_and_json_object():
    mod = load_module()
    exact_response = {"choices": [{"message": {"content": " RDT_LLM_EVAL_OK\n"}}]}
    json_response = {"choices": [{"message": {"content": '{"status":"ok","count":2}'}}]}

    exact = mod.score_response(exact_response, {"content_exact": "RDT_LLM_EVAL_OK"})
    parsed = mod.score_response(json_response, {"json_object": {"required_keys": ["status", "count"]}})

    assert exact.passed is True
    assert parsed.passed is True


def test_score_native_tool_call_rejects_raw_json_content():
    mod = load_module()
    good_response = {
        "choices": [
            {
                "message": {
                    "content": None,
                    "tool_calls": [
                        {"type": "function", "function": {"name": "report_marker", "arguments": '{"marker":"RDT_DIRECT_TOOL_OK"}'}}
                    ],
                }
            }
        ]
    }
    bad_response = {"choices": [{"message": {"content": '{"name":"report_marker","arguments":{}}'}}]}

    good = mod.score_response(good_response, {"tool_call": {"name": "report_marker", "arguments_contains": "RDT_DIRECT_TOOL_OK"}})
    bad = mod.score_response(bad_response, {"tool_call": {"name": "report_marker"}})

    assert good.passed is True
    assert bad.passed is False
    assert "tool_calls" in bad.reason


def test_business_hours_guard_blocks_concurrency_after_limit():
    mod = load_module()

    assert mod.concurrency_allowed(local_hour=10, requested_concurrency=4, allow_business_hours_load=False) is False
    assert mod.concurrency_allowed(local_hour=20, requested_concurrency=4, allow_business_hours_load=False) is True
    assert mod.concurrency_allowed(local_hour=10, requested_concurrency=2, allow_business_hours_load=False) is True


def test_load_jsonl_cases(tmp_path):
    mod = load_module()
    case_file = tmp_path / "cases.jsonl"
    case_file.write_text('\n'.join([
        json.dumps({"id": "one", "messages": [], "expect": {"content_exact": "x"}}),
        "",
        json.dumps({"id": "two", "messages": [], "expect": {"content_contains": "y"}}),
    ]))

    cases = mod.load_jsonl_cases(case_file)

    assert [case["id"] for case in cases] == ["one", "two"]


def test_committed_eval_suite_files_are_loadable():
    mod = load_module()
    suite_dir = ROOT / "evals" / "rdt_llm" / "suites"
    expected = [
        "direct_api_cases.jsonl",
        "tool_call_cases.jsonl",
        "hermes_agent_cases.jsonl",
        "coding_cases.jsonl",
        "ops_reasoning_cases.jsonl",
        "safety_cases.jsonl",
    ]

    for filename in expected:
        cases = mod.load_jsonl_cases(suite_dir / filename)
        assert cases, filename
        assert all("id" in case and "expect" in case for case in cases), filename


def test_manifest_tracks_current_target_and_baselines():
    manifest_path = ROOT / "evals" / "rdt_llm" / "suites" / "manifest.yaml"
    data = load_module().load_yaml_file(manifest_path)

    assert data["lanes"]["target"]["provider"] == "rdt-llm"
    assert data["lanes"]["target"]["model"] == "qwen2.5-coder-32b-awq"
    assert {lane["provider"] for lane in data["lanes"]["baselines"]} == {"nous", "openai-api"}
    assert data["thresholds"]["target_required_pass_rate"] == 0.95


def test_collect_result_files_does_not_duplicate_hermes_results(tmp_path):
    mod = load_module()
    (tmp_path / "direct-api_results.jsonl").write_text("{}\n")
    (tmp_path / "hermes-agent_hermes_results.jsonl").write_text("{}\n")

    files = mod.collect_result_files(tmp_path)

    assert [path.name for path in files] == ["direct-api_results.jsonl", "hermes-agent_hermes_results.jsonl"]
