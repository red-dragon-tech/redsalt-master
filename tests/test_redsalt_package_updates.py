import importlib.util
from pathlib import Path

ROOT = Path(__file__).parents[1]
MODULE_PATH = ROOT / "states/redsalt_package_updates/files/redsalt-package-updates.py"
SPEC = importlib.util.spec_from_file_location("redsalt_package_updates_test_module", MODULE_PATH)
assert SPEC is not None and SPEC.loader is not None
runner = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(runner)


def test_runner_keeps_explicitly_allowlisted_targets_for_policy_validation():
    policies = {
        "rdt-kali": {"enabled": True, "manager": "salt", "scheduled": True},
        "mgmt.rdt.dev": {"enabled": True, "manager": "salt", "scheduled": True},
        "ubuntu-native": {"enabled": True, "manager": "native", "scheduled": True},
        "disabled": {"enabled": False, "manager": "salt", "scheduled": True},
        "ordinary": {"enabled": True, "manager": "salt", "scheduled": False},
    }
    assert runner.eligible_minions(policies) == sorted(policies)


def test_runner_rejects_wildcards_and_compound_salt_target_syntax():
    assert runner.is_safe_exact_minion_id("rdt-kali")
    assert runner.is_safe_exact_minion_id("mgmt.rdt.dev")
    assert not runner.is_safe_exact_minion_id("*")
    assert not runner.is_safe_exact_minion_id("rdt-kali,other")
    assert not runner.is_safe_exact_minion_id("../etc")


def test_runner_interval_checks_match_local_window_even_when_master_utc_differs():
    unit = (ROOT / "states/redsalt_package_updates/init.sls").read_text()
    assert "OnCalendar=hourly" in unit
    assert "Persistent=false" in unit
    assert "RandomizedDelaySec=2min" in unit
    assert "Conflicts=redsalt-master-sync.service" not in unit
    convergence = (ROOT / "states/redsalt_highstate_convergence/files/redsalt-highstate-convergence.py").read_text()
    assert "PACKAGE_UPDATES_LOCK_PATH" in convergence
    assert "package updates lock is held; skipping convergence run" in convergence


def test_runner_checks_weekly_due_schedule_and_staleness():
    now = runner.parse_timestamp("2026-10-24T08:30:00Z")
    assert now is not None
    assert runner.is_due(None, 7, now)
    assert runner.is_due("2026-10-17T08:30:00Z", 7, now)
    assert not runner.is_due("2026-10-18T08:30:00Z", 7, now)
    assert runner.is_stale(None, 9, now)
    assert not runner.is_stale("2026-10-15T08:30:00Z", 9, now)
    assert runner.is_stale("2026-10-13T08:30:00Z", 9, now)


def test_successful_preview_waits_for_weekly_cadence_before_repreview():
    now = runner.parse_timestamp("2026-10-24T08:30:00Z")
    assert now is not None
    assert not runner.retry_due("2026-10-24T08:00:00Z", 7, now)


def test_explicit_approval_allows_previewed_work_to_be_rechecked():
    source = MODULE_PATH.read_text()
    assert "policy.get('approved_preview_sha256')" in source
    assert "preview_is_approved(policy, preview)" in source


def test_runner_does_not_retry_a_failed_run_until_cadence_is_due():
    now = runner.parse_timestamp("2026-10-24T08:30:00Z")
    assert now is not None
    assert not runner.retry_due("2026-10-24T08:00:00Z", 7, now)
    assert runner.retry_due("2026-10-17T08:00:00Z", 7, now)


def test_runner_checks_maintenance_window_timezone_and_weekday():
    now = runner.parse_timestamp("2026-10-24T08:30:00Z")
    assert now is not None
    local_now = now.astimezone(runner.ZoneInfo("America/Chicago"))
    assert runner.is_window_day(["Sat"], local_now)
    assert not runner.is_window_day(["Sun"], local_now)
    assert runner.in_window("02:00", "05:00", local_now)
    assert not runner.in_window("06:00", "07:00", local_now)


def test_runner_detects_interactive_sessions_conservatively():
    assert runner.is_idle_session_output("")
    assert not runner.is_idle_session_output("2 1000 darth seat0 tty1 active")


def test_active_session_deferral_does_not_consume_weekly_attempt():
    source = MODULE_PATH.read_text()
    start = source.index("if not is_idle_session_output(session_output):")
    end = source.index("payload.update({'last_attempt': started", start)
    deferred = source[start:end]
    assert "'last_result': 'skipped_active_session'" in deferred
    assert "'last_attempt': started" not in deferred


def test_runner_checks_interactive_sessions_on_the_target_minion():
    source = MODULE_PATH.read_text()
    assert "minion, 'cmd.run', 'loginctl list-sessions --no-legend'" in source
    assert "run(['loginctl', 'list-sessions'" not in source


def test_runner_fails_closed_on_missing_or_failed_salt_results():
    assert runner.summarize_state_return(None)["success"] is False
    assert runner.summarize_state_return({"package": {"result": False}})["failed"] == 1
    assert runner.summarize_state_return({"package": {"result": True, "changes": {"old": 1}}})["changed"] == 1


def test_scheduled_runner_uses_distinct_preview_and_apply_state_ids():
    source = MODULE_PATH.read_text()
    assert "'package_updates.scheduled', 'test=True'" in source
    assert "'package_updates.scheduled', '--out=json'" in source


def test_test_mode_preview_allows_planned_changes_but_rejects_failed_state():
    preview = runner.summarize_test_return({"package": {"result": None, "changes": {"new": "x"}}}, "rdt-kali")
    assert preview["success"] is True
    assert preview["planned"] == 1
    assert preview["planned_changes"] == [{
        "state_id": "package", "name": "", "changes": {"new": "x"}, "comment": ""
    }]
    assert len(preview["planned_changes_sha256"]) == 64
    failed = runner.summarize_test_return({"package": {"result": False, "changes": {}}}, "rdt-kali")
    assert failed["success"] is False
    assert failed["failed"] == 1


def test_missing_target_policy_is_recorded_as_a_failed_status(monkeypatch, tmp_path):
    monkeypatch.setattr(runner, "STATUS_DIR", tmp_path)
    now = runner.parse_timestamp("2026-10-24T08:30:00Z")
    assert now is not None
    result = runner.update_minion("rdt-kali", {"configuration_error": "missing package_updates pillar"}, now)
    assert result["last_result"] == "failed"
    assert "could not read explicit minion package update policy" in result["last_error"]
    assert (tmp_path / "rdt-kali.json").exists()


def test_maintenance_window_rechecks_remaining_time_before_apply():
    now = runner.parse_timestamp("2026-10-24T09:55:00Z")
    assert now is not None
    local_now = now.astimezone(runner.ZoneInfo("America/Chicago"))
    assert not runner.window_has_time_remaining("02:00", "05:00", local_now, 600)
    assert runner.window_has_time_remaining("02:00", "05:00", local_now, 60)
    assert not runner.window_has_time_remaining("22:00", "02:00", local_now, 600)
    overnight = runner.parse_timestamp("2026-10-25T06:55:00Z")
    assert overnight is not None
    assert runner.window_has_time_remaining(
        "22:00", "02:00", overnight.astimezone(runner.ZoneInfo("America/Chicago")), 60
    )
    assert not runner.window_has_time_remaining(
        "02:00", "05:00", local_now, 2 * 3600 + 360
    )


def test_preview_fingerprint_is_bound_to_the_target_minion():
    ret = {"package": {"result": None, "changes": {"new": "x"}}}
    kali = runner.summarize_test_return(ret, minion_id="rdt-kali")
    other = runner.summarize_test_return(ret, minion_id="other-minion")
    assert kali["planned_changes_sha256"] != other["planned_changes_sha256"]
    assert runner.preview_is_approved({"approved_preview_sha256": kali["planned_changes_sha256"]}, kali)
    assert not runner.preview_is_approved({"approved_preview_sha256": kali["planned_changes_sha256"]}, other)


def test_reboot_attention_is_preserved_until_a_verified_clear_result():
    source = MODULE_PATH.read_text()
    assert "if old.get('reboot_required') is True and 'manual_attention' in old:" in source


def test_runner_records_reboot_needed_without_scheduling_a_reboot():
    source = MODULE_PATH.read_text()
    assert "file.file_exists', '/var/run/reboot-required'" in source
    assert "reboot is not automatic and needs an approved maintenance/reboot action" in source
    assert "systemctl reboot" not in source


def test_runner_throttles_repeat_alerts_but_keeps_status_evidence():
    source = MODULE_PATH.read_text()
    assert "failure_alerts" in source
    assert "last_failure_alert_at" in source
    assert "if failure_alerts or alerts or attention" in source
    assert "'stale_minions': stale_minions" in source
    assert "'monitoring_complete': bool(eligible)" in source
    assert "if not eligible:" in source
    assert "preview_is_approved(policy, preview)" in source
    assert "'test=True'" in source


def test_preview_does_not_apply_packages_without_exact_host_approval(monkeypatch, tmp_path):
    monkeypatch.setattr(runner, "STATUS_DIR", tmp_path)
    commands = []

    def fake_run(cmd, timeout=runner.SALT_TIMEOUT_SECONDS):
        commands.append(cmd)
        return runner.subprocess.CompletedProcess(cmd, 0, "", "")

    def fake_salt_json(cmd, label, timeout=runner.SALT_TIMEOUT_SECONDS):
        commands.append(cmd)
        if ("maintenance-window time check" in label
                or "pre-apply maintenance-window time check" in label
                or "post-revalidation maintenance-window time check" in label):
            return {"rdt-kali": "2026-10-24T02:00:00-05:00"}
        if "loginctl" in " ".join(cmd):
            return {"rdt-kali": ""}
        if "pkg.refresh_db" in cmd:
            return {"rdt-kali": True}
        if "pkg.list_upgrades" in cmd:
            return {"rdt-kali": {"pkg-a": "2.0"}}
        if "state.apply" in cmd and "test=True" in cmd:
            return {"rdt-kali": {"pkg-update": {"result": None, "changes": {"planned": 1}}}}
        raise AssertionError(f"unexpected Salt call: {cmd}")

    monkeypatch.setattr(runner, "run", fake_run)
    monkeypatch.setattr(runner, "salt_json", fake_salt_json)
    now = runner.parse_timestamp("2026-10-24T08:30:00Z")
    assert now is not None
    result = runner.update_minion("rdt-kali", {
        "enabled": True, "manager": "salt", "scheduled": True,
        "approved_preview_sha256": "", "timezone": "America/Chicago",
        "window_days": ["Sat"], "window_start": "02:00", "window_end": "05:00",
        "require_idle": True, "cadence_days": 7, "stale_after_days": 9,
        "max_upgrades": 750, "timeout_seconds": 3600,
        "refresh": True, "debian_dist_upgrade": False,
        "native_unattended": False, "automatic_reboot": False,
    }, now)
    assert result["last_result"] == "preview_ready", result
    assert result["test_mode_preview"]["planned"] == 1
    assert not any("state.apply" in cmd and "test=True" not in cmd for cmd in commands)


def test_approved_run_requires_fresh_successful_preview_before_mutation(monkeypatch, tmp_path):
    monkeypatch.setattr(runner, "STATUS_DIR", tmp_path)
    commands = []

    def fake_run(cmd, timeout=runner.SALT_TIMEOUT_SECONDS):
        commands.append(cmd)
        return runner.subprocess.CompletedProcess(cmd, 0, "", "")

    def fake_salt_json(cmd, label, timeout=runner.SALT_TIMEOUT_SECONDS):
        commands.append(cmd)
        joined = " ".join(cmd)
        if ("maintenance-window time check" in label
                or "pre-apply maintenance-window time check" in label
                or "post-revalidation maintenance-window time check" in label):
            return {"rdt-kali": "2026-10-24T02:00:00-05:00"}
        if "loginctl" in joined:
            return {"rdt-kali": ""}
        if "pkg.refresh_db" in joined:
            return {"rdt-kali": True}
        if "pkg.list_upgrades" in joined:
            return {"rdt-kali": {}} if "post-update" in label else {"rdt-kali": {"pkg-a": "2.0"}}
        if "state.apply" in joined and "test=True" in joined:
            return {"rdt-kali": {"pkg-update": {"result": None, "changes": {"planned": 1}}}}
        if "state.apply" in joined:
            return {"rdt-kali": {"pkg-update": {"result": True, "changes": {"old": "1", "new": "2"}}}}
        if "reboot-required" in joined:
            return {"rdt-kali": False}
        raise AssertionError(f"unexpected Salt call: {cmd}")

    monkeypatch.setattr(runner, "run", fake_run)
    monkeypatch.setattr(runner, "salt_json", fake_salt_json)
    now = runner.parse_timestamp("2026-10-24T08:30:00Z")
    assert now is not None
    policy = {
        "enabled": True, "manager": "salt", "scheduled": True,
        "refresh": True, "debian_dist_upgrade": False,
        "native_unattended": False, "automatic_reboot": False,
        "approved_preview_sha256": "pending", "timezone": "America/Chicago",
        "window_days": ["Sat"], "window_start": "02:00", "window_end": "05:00",
        "require_idle": True, "cadence_days": 7, "stale_after_days": 9,
        "max_upgrades": 750, "timeout_seconds": 3600,
    }
    calculated_preview = runner.summarize_test_return({
        "pkg-update": {"result": None, "changes": {"planned": 1}}
    }, "rdt-kali")
    policy["approved_preview_sha256"] = calculated_preview["planned_changes_sha256"]
    result = runner.update_minion("rdt-kali", policy, now)
    assert result["last_result"] == "success", result
    assert any("state.apply" in cmd and "test=True" not in cmd for cmd in commands)


def test_runner_repreviews_after_approval_and_refuses_changed_plan(monkeypatch, tmp_path):
    monkeypatch.setattr(runner, "STATUS_DIR", tmp_path)
    commands = []
    preview_count = 0

    def fake_run(cmd, timeout=runner.SALT_TIMEOUT_SECONDS):
        commands.append(cmd)
        return runner.subprocess.CompletedProcess(cmd, 0, "", "")

    def fake_salt_json(cmd, label, timeout=runner.SALT_TIMEOUT_SECONDS):
        nonlocal preview_count
        commands.append(cmd)
        joined = " ".join(cmd)
        if ("maintenance-window time check" in label
                or "pre-apply maintenance-window time check" in label
                or "post-revalidation maintenance-window time check" in label):
            return {"rdt-kali": "2026-10-24T02:00:00-05:00"}
        if "loginctl" in joined:
            return {"rdt-kali": ""}
        if "pkg.refresh_db" in joined:
            return {"rdt-kali": True}
        if "pkg.list_upgrades" in joined:
            return {"rdt-kali": {"pkg-a": "2.0"}}
        if "state.apply" in joined and "test=True" in joined:
            preview_count += 1
            changes = {"planned": 1 if preview_count == 1 else 2}
            return {"rdt-kali": {"pkg-update": {"result": None, "changes": changes}}}
        raise AssertionError(f"unexpected Salt call: {cmd}")

    monkeypatch.setattr(runner, "run", fake_run)
    monkeypatch.setattr(runner, "salt_json", fake_salt_json)
    now = runner.parse_timestamp("2026-10-24T08:30:00Z")
    assert now is not None
    approved = runner.summarize_test_return(
        {"pkg-update": {"result": None, "changes": {"planned": 1}}}, "rdt-kali"
    )["planned_changes_sha256"]
    result = runner.update_minion("rdt-kali", {
        "enabled": True, "manager": "salt", "scheduled": True,
        "approved_preview_sha256": approved, "timezone": "America/Chicago",
        "window_days": ["Sat"], "window_start": "02:00", "window_end": "05:00",
        "require_idle": True, "cadence_days": 7, "stale_after_days": 9,
        "max_upgrades": 750, "timeout_seconds": 3600, "refresh": True,
        "debian_dist_upgrade": False, "native_unattended": False,
        "automatic_reboot": False,
    }, now)
    assert preview_count == 2
    assert result["last_result"] == "preview_changed"
    assert "changed after approval" in result["last_error"]
    assert not any("state.apply" in cmd and "test=True" not in cmd for cmd in commands)


def test_changed_plan_preserves_prior_reboot_manual_attention(monkeypatch, tmp_path):
    monkeypatch.setattr(runner, "STATUS_DIR", tmp_path)
    initial = {
        "minion": "rdt-kali", "last_result": "success", "success": True,
        "reboot_required": True, "reboot_check_verified": True,
        "manual_attention": "OS reports reboot required; reboot is not automatic.",
    }
    runner.write_status("rdt-kali", initial)
    commands = []

    def fake_run(cmd, timeout=runner.SALT_TIMEOUT_SECONDS):
        commands.append(cmd)
        return runner.subprocess.CompletedProcess(cmd, 0, "", "")

    def fake_salt_json(cmd, label, timeout=runner.SALT_TIMEOUT_SECONDS):
        commands.append(cmd)
        joined = " ".join(cmd)
        if "maintenance-window time check" in label:
            return {"rdt-kali": "2026-10-24T02:00:00-05:00"}
        if "loginctl" in joined:
            return {"rdt-kali": ""}
        if "pkg.refresh_db" in joined:
            return {"rdt-kali": True}
        if "pkg.list_upgrades" in joined:
            return {"rdt-kali": {"pkg-a": "2.0"}}
        if "state.apply" in joined and "test=True" in joined:
            changes = {"planned": 1} if "approved-plan revalidation" not in label else {"planned": 2}
            return {"rdt-kali": {"pkg-update": {"result": None, "changes": changes}}}
        raise AssertionError(f"unexpected Salt call: {cmd}")

    monkeypatch.setattr(runner, "run", fake_run)
    monkeypatch.setattr(runner, "salt_json", fake_salt_json)
    now = runner.parse_timestamp("2026-10-24T08:30:00Z")
    approved = runner.summarize_test_return(
        {"pkg-update": {"result": None, "changes": {"planned": 1}}}, "rdt-kali"
    )["planned_changes_sha256"]
    result = runner.update_minion("rdt-kali", {
        "enabled": True, "manager": "salt", "scheduled": True,
        "approved_preview_sha256": approved, "timezone": "America/Chicago",
        "window_days": ["Sat"], "window_start": "02:00", "window_end": "05:00",
        "require_idle": True, "cadence_days": 7, "stale_after_days": 9,
        "max_upgrades": 750, "timeout_seconds": 3600, "refresh": True,
        "debian_dist_upgrade": False, "native_unattended": False,
        "automatic_reboot": False,
    }, now)
    assert result["last_result"] == "preview_changed"
    assert result["reboot_required"] is True
    assert "reboot required" in result["manual_attention"]
    assert "plan also changed" in result["manual_attention"]


def test_runner_applies_only_when_repreview_matches_approved_plan(monkeypatch, tmp_path):
    monkeypatch.setattr(runner, "STATUS_DIR", tmp_path)
    commands = []
    preview_count = 0

    def fake_run(cmd, timeout=runner.SALT_TIMEOUT_SECONDS):
        commands.append(cmd)
        return runner.subprocess.CompletedProcess(cmd, 0, "", "")

    def fake_salt_json(cmd, label, timeout=runner.SALT_TIMEOUT_SECONDS):
        nonlocal preview_count
        commands.append(cmd)
        joined = " ".join(cmd)
        if ("maintenance-window time check" in label
                or "pre-apply maintenance-window time check" in label
                or "post-revalidation maintenance-window time check" in label):
            return {"rdt-kali": "2026-10-24T02:00:00-05:00"}
        if "loginctl" in joined:
            return {"rdt-kali": ""}
        if "pkg.refresh_db" in joined:
            return {"rdt-kali": True}
        if "pkg.list_upgrades" in joined:
            if any("state.apply" in call and "test=True" not in call for call in commands):
                return {"rdt-kali": {}}
            return {"rdt-kali": {"pkg-a": "2.0"}}
        if "state.apply" in joined and "test=True" in joined:
            preview_count += 1
            return {"rdt-kali": {"pkg-update": {"result": None, "changes": {"planned": 1}}}}
        if "file.file_exists" in joined:
            return {"rdt-kali": False}
        if "state.apply" in joined:
            return {"rdt-kali": {"pkg-update": {"result": True, "changes": {"updated": 1}}}}
        raise AssertionError(f"unexpected Salt call: {cmd}")

    monkeypatch.setattr(runner, "run", fake_run)
    monkeypatch.setattr(runner, "salt_json", fake_salt_json)
    now = runner.parse_timestamp("2026-10-24T08:30:00Z")
    assert now is not None
    approved = runner.summarize_test_return(
        {"pkg-update": {"result": None, "changes": {"planned": 1}}}, "rdt-kali"
    )["planned_changes_sha256"]
    result = runner.update_minion("rdt-kali", {
        "enabled": True, "manager": "salt", "scheduled": True,
        "approved_preview_sha256": approved, "timezone": "America/Chicago",
        "window_days": ["Sat"], "window_start": "02:00", "window_end": "05:00",
        "require_idle": True, "cadence_days": 7, "stale_after_days": 9,
        "max_upgrades": 750, "timeout_seconds": 3600, "refresh": True,
        "debian_dist_upgrade": False, "native_unattended": False,
        "automatic_reboot": False,
    }, now)
    assert preview_count == 2
    assert result["last_result"] == "success", result.get("last_error")
    apply_calls = [cmd for cmd in commands if "state.apply" in cmd and "test=True" not in cmd]
    assert len(apply_calls) == 1
    assert any(any(arg.startswith("pillar=") and approved in arg for arg in cmd) for cmd in apply_calls)


def test_runner_rechecks_idle_session_immediately_before_mutation(monkeypatch, tmp_path):
    monkeypatch.setattr(runner, "STATUS_DIR", tmp_path)
    commands = []
    idle_checks = 0

    def fake_run(cmd, timeout=runner.SALT_TIMEOUT_SECONDS):
        commands.append(cmd)
        return runner.subprocess.CompletedProcess(cmd, 0, "", "")

    def fake_salt_json(cmd, label, timeout=runner.SALT_TIMEOUT_SECONDS):
        nonlocal idle_checks
        commands.append(cmd)
        joined = " ".join(cmd)
        if "loginctl" in joined:
            idle_checks += 1
            return {"rdt-kali": "" if idle_checks == 1 else "2 1000 user seat0 tty1 active"}
        if ("maintenance-window time check" in label
                or "pre-apply maintenance-window time check" in label
                or "post-revalidation maintenance-window time check" in label):
            return {"rdt-kali": "2026-10-24T02:00:00-05:00"}
        if "pkg.refresh_db" in joined:
            return {"rdt-kali": True}
        if "pkg.list_upgrades" in joined:
            return {"rdt-kali": {"pkg-a": "2.0"}}
        if "state.apply" in joined and "test=True" in joined:
            return {"rdt-kali": {"pkg-update": {"result": None, "changes": {"planned": 1}}}}
        raise AssertionError(f"unexpected Salt call: {cmd}")

    monkeypatch.setattr(runner, "run", fake_run)
    monkeypatch.setattr(runner, "salt_json", fake_salt_json)
    now = runner.parse_timestamp("2026-10-24T08:30:00Z")
    assert now is not None
    preview = runner.summarize_test_return(
        {"pkg-update": {"result": None, "changes": {"planned": 1}}}, "rdt-kali"
    )
    result = runner.update_minion("rdt-kali", {
        "enabled": True, "manager": "salt", "scheduled": True,
        "approved_preview_sha256": preview["planned_changes_sha256"],
        "timezone": "America/Chicago", "window_days": ["Sat"],
        "window_start": "02:00", "window_end": "05:00", "require_idle": True,
        "cadence_days": 7, "stale_after_days": 9, "max_upgrades": 750,
        "timeout_seconds": 3600, "refresh": True, "debian_dist_upgrade": False,
        "native_unattended": False, "automatic_reboot": False,
    }, now)
    assert idle_checks == 2
    assert result["last_result"] == "skipped_active_session"
    assert not any("state.apply" in cmd and "test=True" not in cmd for cmd in commands)


def test_preview_fingerprint_must_match_explicit_approval():
    preview = runner.summarize_test_return({"package": {"result": None, "changes": {"new": "x"}}}, "rdt-kali")
    assert runner.preview_is_approved({"approved_preview_sha256": preview["planned_changes_sha256"]}, preview)
    assert not runner.preview_is_approved({"approved_preview_sha256": ""}, preview)
    assert not runner.preview_is_approved({"approved_preview_sha256": "0" * 64}, preview)


def test_test_preview_helper_binds_plan_hash_to_host_identity():
    source = MODULE_PATH.read_text()
    assert "def summarize_test_return(ret: Any, minion_id: str)" in source
    assert "fingerprint_payload = {'minion_id': minion_id" in source


def test_stale_preview_fingerprint_forces_fresh_preview():
    source = MODULE_PATH.read_text()
    assert "approved_fingerprint != old.get('test_mode_preview', {}).get('planned_changes_sha256')" in source


def test_weekly_state_runs_are_separate_from_regular_highstate():
    base_role = (ROOT / "states/roles/base.sls").read_text()
    assert "- package_updates" in base_role
    package_state = (ROOT / "states/package_updates/init.sls").read_text()
    assert "enabled and manager == 'salt' and not scheduled" in package_state
    salt_master_role = (ROOT / "states/roles/salt_master.sls").read_text()
    assert "- redsalt_package_updates" in salt_master_role


def test_kali_has_explicit_safe_scheduled_update_policy():
    import yaml

    pillar = yaml.safe_load((ROOT / "pillar/minions/rdt_kali.sls").read_text())
    cfg = pillar["package_updates"]
    assert cfg["enabled"] is True
    assert cfg["manager"] == "salt"
    assert cfg["scheduled"] is True
    assert cfg["approved_preview_sha256"] == ""
    assert cfg["cadence_days"] == 7
    assert cfg["stale_after_days"] >= cfg["cadence_days"]
    assert cfg["window_days"] == ["Sat"]
    assert cfg["window_start"] == "02:00"
    assert cfg["window_end"] == "05:00"
    assert cfg["timezone"] == "America/Chicago"
    assert cfg["require_idle"] is True
    assert cfg["max_upgrades"] == 750
    assert cfg["debian_dist_upgrade"] is False
    assert cfg["native_unattended"] is False
    assert cfg["automatic_reboot"] is False


def test_validator_requires_the_kali_update_policy_and_runner():
    validator = (ROOT / "scripts/validate.py").read_text()
    assert "def check_kali_package_updates" in validator
    assert "redsalt_package_updates" in validator


def test_package_update_docs_define_kali_ownership_and_safety():
    docs = (ROOT / "docs/package-updates.md").read_text()
    assert "rdt-kali" in docs
    assert "America/Chicago" in docs
    assert "automatic_reboot: false" in docs
    assert "considered stale after `stale_after_days: 9`" in docs
    assert "Not a live-apply authorization" in docs
