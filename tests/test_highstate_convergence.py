import importlib.util
from pathlib import Path


MODULE_PATH = Path(__file__).parents[1] / "states/redsalt_highstate_convergence/files/redsalt-highstate-convergence.py"
spec = importlib.util.spec_from_file_location("redsalt_highstate_convergence", MODULE_PATH)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


def test_parse_salt_prefix_and_json_payload():
    raw = "Executing run on ['example-vllm-node']\n\n{\n  \"example-vllm-node\": {\"result\": true}\n}\n"
    assert module.parse_json_objects(raw) == {"example-vllm-node": {"result": True}}


def test_parse_adjacent_json_objects_merges_minions():
    raw = '{"rdt-kali": {"result": true}}\n{"example-vllm-node": {"result": true}}'
    assert module.parse_json_objects(raw) == {
        "rdt-kali": {"result": True},
        "example-vllm-node": {"result": True},
    }


def test_parse_rejects_non_json_output():
    try:
        module.parse_json_objects("salt command failed")
    except ValueError as exc:
        assert "no JSON object" in str(exc)
    else:
        raise AssertionError("expected ValueError")


PACKAGE_RUNNER_PATH = Path(__file__).parents[1] / "states/redsalt_package_updates/files/redsalt-package-updates.py"
package_spec = importlib.util.spec_from_file_location("redsalt_package_updates", PACKAGE_RUNNER_PATH)
assert package_spec is not None and package_spec.loader is not None
package_runner = importlib.util.module_from_spec(package_spec)
package_spec.loader.exec_module(package_runner)


def test_package_runner_keeps_allowlisted_targets_for_visible_policy_validation():
    policies = {
        "rdt-kali": {"enabled": True, "manager": "salt", "scheduled": True},
        "mgmt.rdt.dev": {"enabled": True, "manager": "salt", "scheduled": True},
        "ubuntu-native": {"enabled": True, "manager": "native", "scheduled": True},
        "example": {"enabled": False, "manager": "salt", "scheduled": True},
        "unscheduled": {"enabled": True, "manager": "salt", "scheduled": False},
    }
    assert package_runner.eligible_minions(policies) == sorted(policies)


def test_package_runner_respects_success_cadence_and_stale_threshold():
    now = package_runner.parse_timestamp("2026-10-23T05:30:00Z")
    assert package_runner.is_due(None, 7, now)
    assert not package_runner.is_due("2026-10-18T05:30:00Z", 7, now)
    assert package_runner.is_due("2026-10-15T05:30:00Z", 7, now)
    assert not package_runner.is_stale("2026-10-15T05:30:00Z", 9, now)
    assert package_runner.is_stale("2026-10-13T05:30:00Z", 9, now)


def test_package_runner_does_not_retry_failed_upgrade_repeatedly_in_same_week():
    now = package_runner.parse_timestamp("2026-10-24T08:30:00Z")
    assert now is not None
    assert not package_runner.retry_due("2026-10-24T08:00:00Z", 7, now)
    assert package_runner.retry_due("2026-10-17T08:00:00Z", 7, now)


def test_package_runner_checks_maintenance_window_and_idle_sessions():
    now = package_runner.parse_timestamp("2026-10-23T05:30:00Z")
    assert package_runner.in_window("05:00", "07:00", now)
    assert not package_runner.in_window("06:00", "07:00", now)
    assert package_runner.is_idle_session_output("")
    assert not package_runner.is_idle_session_output("2 1000 darth seat0 tty1 active")


def test_package_runner_checks_weekday_in_local_window():
    now = package_runner.parse_timestamp("2026-10-24T08:30:00Z")
    assert now is not None
    local_now = now.astimezone(package_runner.ZoneInfo("America/Chicago"))
    assert package_runner.is_window_day(["Sat"], local_now)
    assert not package_runner.is_window_day(["Sun"], local_now)
