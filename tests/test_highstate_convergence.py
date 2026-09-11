import importlib.util
from pathlib import Path


MODULE_PATH = Path(__file__).parents[1] / "states/redsalt_highstate_convergence/files/redsalt-highstate-convergence.py"
spec = importlib.util.spec_from_file_location("redsalt_highstate_convergence", MODULE_PATH)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


def test_parse_salt_prefix_and_json_payload():
    raw = "Executing run on ['rdt-llm']\n\n{\n  \"rdt-llm\": {\"result\": true}\n}\n"
    assert module.parse_json_objects(raw) == {"rdt-llm": {"result": True}}


def test_parse_adjacent_json_objects_merges_minions():
    raw = '{"rdt-kali": {"result": true}}\n{"rdt-llm": {"result": true}}'
    assert module.parse_json_objects(raw) == {
        "rdt-kali": {"result": True},
        "rdt-llm": {"result": True},
    }


def test_parse_rejects_non_json_output():
    try:
        module.parse_json_objects("salt command failed")
    except ValueError as exc:
        assert "no JSON object" in str(exc)
    else:
        raise AssertionError("expected ValueError")
