from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]


def test_package_updates_are_not_applied_by_routine_base_highstate():
    role = (ROOT / "states/roles/base.sls").read_text()
    assert "- package_updates" in role


def test_fwupd_is_updated_only_for_explicit_host_opt_in():
    state = (ROOT / "states/package_updates/init.sls").read_text()
    defaults = (ROOT / "pillar/package_updates/defaults.sls").read_text()
    host = (ROOT / "pillar/minions/mgmt_rdt_dev.sls").read_text()
    assert "enabled: false" in defaults
    assert "latest_packages:" in host
    assert "    - fwupd" in host
    assert "pkg.latest" in state
    assert "only_upgrade: true" in state


def test_default_update_manager_applies_cross_platform_salt_uptodate():
    state = (ROOT / "states/package_updates/init.sls").read_text()
    assert "pkg.uptodate" in state
    assert "pillar.get" in state
    assert "os_family" in state
    assert "dist_upgrade: {{ cfg.get('debian_dist_upgrade', False) }}" in state


def test_default_policy_enables_salt_updates_and_disables_competing_native_manager():
    defaults = (ROOT / "pillar/package_updates/defaults.sls").read_text()
    assert "manager: salt" in defaults
    assert "enabled: false" in defaults
    assert "native_unattended: false" in defaults
    assert "automatic_reboot: false" in defaults


def test_salt_master_reboots_only_in_its_explicit_maintenance_window():
    host = (ROOT / "pillar/minions/mgmt_rdt_dev.sls").read_text()
    assert "automatic_reboot: true" in host
    assert "reboot_time: '06:00'" in host
    assert "OnCalendar=*-*-* {{ cfg.get('reboot_time', '06:00') }}:00" in (ROOT / "states/package_updates/init.sls").read_text()
    assert "Persistent=false" in (ROOT / "states/package_updates/init.sls").read_text()


def test_native_apt_never_reboots_outside_the_controlled_window():
    state = (ROOT / "states/package_updates/init.sls").read_text()
    assert 'Unattended-Upgrade::Automatic-Reboot "false";' in state


def test_native_unattended_policy_handles_supported_package_families():
    state = (ROOT / "states/package_updates/init.sls").read_text()
    for platform in ("Debian", "RedHat", "Suse"):
        assert platform in state
    for feature in ("unattended-upgrades", "apt-daily-upgrade.timer", "dnf-automatic", "dnf-automatic-install.timer", "dnf5-plugin-automatic", "dnf5-automatic.timer"):
        assert feature in state


def test_reboot_checker_does_not_reboot_without_os_signal():
    import importlib.util

    path = ROOT / "states/package_updates/files/redsalt-reboot-if-required.py"
    spec = importlib.util.spec_from_file_location("redsalt_reboot_if_required", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    assert module.reboot_required() is False


def test_update_state_renders_valid_yaml_for_debian_redhat_and_suse():
    try:
        import yaml
        from jinja2 import Environment
    except ImportError as exc:
        raise AssertionError(f"YAML/Jinja test dependencies are required: {exc}")

    template = Environment().from_string((ROOT / "states/package_updates/init.sls").read_text())
    targeted_fwupd = template.render(
        salt={"pillar.get": lambda key, default=None: {
            "enabled": True, "manager": "salt", "refresh": True,
            "debian_dist_upgrade": False, "latest_packages": ["fwupd"],
        } if key == "package_updates" else default},
        grains={"os_family": "Debian", "os": "Ubuntu"},
    )
    parsed_fwupd = yaml.safe_load(targeted_fwupd)
    assert "package-updates-latest-fwupd" in parsed_fwupd
    fwupd_options = parsed_fwupd["package-updates-latest-fwupd"]["pkg.latest"]
    assert {"only_upgrade": True} in fwupd_options
    assert {"dist_upgrade": False} in fwupd_options

    for os_family in ("Debian", "RedHat", "Suse"):
        for manager, native in (("salt", False), ("native", True)):
            rendered = template.render(
                salt={"pillar.get": lambda key, default=None: {
                    "enabled": True,
                    "manager": manager,
                    "refresh": True,
                    "debian_dist_upgrade": False,
                    "automatic_reboot": False,
                    "native_unattended": native,
                    "dnf_upgrade_type": "default",
                    "download_updates": True,
                } if key == "package_updates" else default},
                grains={"os_family": os_family, "transactional": os_family == "Suse"},
            )
            parsed = yaml.safe_load(rendered)
            assert isinstance(parsed, dict)
            if manager == "native" and os_family == "Debian":
                assert "package-updates-apt-daily-upgrade-timer" in parsed
            if manager == "native" and os_family == "RedHat":
                assert "package-updates-dnf-automatic-install-timer" in parsed
            if manager == "native" and os_family == "Suse":
                assert "package-updates-native-suse-unsupported" in parsed

    native_apt = template.render(
        salt={"pillar.get": lambda key, default=None: {
            "enabled": True, "manager": "native", "native_unattended": True,
            "automatic_reboot": True, "reboot_time": "05:00",
        } if key == "package_updates" else default},
        grains={"os_family": "Debian", "os": "Ubuntu"},
    )
    assert 'Unattended-Upgrade::Automatic-Reboot "false";' in native_apt
    assert "OnCalendar=*-*-* 05:00:00" in native_apt

    native_apt_origins = template.render(
        salt={"pillar.get": lambda key, default=None: {
            "enabled": True, "manager": "native", "native_unattended": True,
            "unattended_upgrade_origins": ["Ubuntu:noble-security"],
        } if key == "package_updates" else default},
        grains={"os_family": "Debian", "os": "Ubuntu"},
    )
    assert '"Ubuntu:noble-security";' in native_apt_origins

    rendered_fedora = template.render(
        salt={"pillar.get": lambda key, default=None: {
            "enabled": True, "manager": "native", "native_unattended": True,
            "dnf_upgrade_type": "default", "download_updates": True,
        } if key == "package_updates" else default},
        grains={"os_family": "RedHat", "os": "Fedora", "transactional": False},
    )
    assert "package-updates-dnf5-automatic-timer" in yaml.safe_load(rendered_fedora)


def test_package_update_policy_is_in_global_pillar_top():
    top = (ROOT / "pillar/top.sls").read_text()
    assert "- package_updates.defaults" in top


def test_kali_has_explicit_weekly_salt_updates_and_no_automatic_reboot():
    import yaml

    pillar = yaml.safe_load((ROOT / "pillar/minions/rdt_kali.sls").read_text())
    cfg = pillar["package_updates"]
    assert cfg["enabled"] is True
    assert cfg["manager"] == "salt"
    assert cfg["cadence_days"] == 7
    assert cfg["scheduled"] is True
    assert cfg["approved_preview_sha256"] == ""
    assert cfg["debian_dist_upgrade"] is False
    assert cfg["automatic_reboot"] is False


def test_weekly_runner_is_managed_by_salt_master_role():
    role = (ROOT / "states/roles/salt_master.sls").read_text()
    assert "- redsalt_package_updates" in role


def test_scheduled_kali_highstate_does_not_run_package_update_state():
    state = (ROOT / "states/package_updates/init.sls").read_text()
    assert "enabled and manager == 'salt' and not scheduled" in state


def test_salt_owned_debian_updates_disable_native_unattended_install():
    state = (ROOT / "states/package_updates/init.sls").read_text()
    assert "package-updates-disable-debian-native-auto-upgrades" in state
    assert 'APT::Periodic::Unattended-Upgrade "0";' in state
    assert "os_family == 'Debian' and not cfg.get('native_unattended', False)" in state


def test_scheduled_package_updates_use_a_separate_mutating_state():
    template = (ROOT / "states/package_updates/init.sls").read_text()
    scheduled = (ROOT / "states/package_updates/scheduled.sls").read_text()
    runner = (ROOT / "states/redsalt_package_updates/files/redsalt-package-updates.py").read_text()
    assert "pkg.uptodate" in scheduled
    assert "scheduled_run:" in scheduled
    assert "package_updates.scheduled" in runner
    assert "package-updates-disable-debian-native-auto-upgrades" in template
    assert "os_family == 'Debian' and not cfg.get('native_unattended', False)" in template
    assert "and not scheduled and not cfg.get('native_unattended', False)" not in template
    assert "scheduled_apply_authorized" in scheduled
    assert "approved_preview_sha256" in scheduled
    assert "opts.get('test', False)" in scheduled


def test_scheduled_apply_state_rejects_missing_or_mismatched_live_approval():
    from jinja2 import Environment
    import yaml

    source = (ROOT / "states/package_updates/scheduled.sls").read_text()
    env = Environment()

    def render(test_mode, auth):
        cfg = {"enabled": True, "scheduled": True, "manager": "salt", "approved_preview_sha256": "a" * 64}
        salt = {"pillar.get": lambda key, default=None: cfg if key == "package_updates" else auth if key == "scheduled_apply_authorized" else default}
        text = env.from_string(source).render(salt=salt, grains={"os_family": "Debian"}, opts={"test": test_mode})
        return yaml.safe_load(text) or {}

    assert "package-updates-scheduled-uptodate" in render(True, False)
    assert "package-updates-scheduled-uptodate" in render(False, "a" * 64)
    assert "package-updates-scheduled-uptodate" not in render(False, False)
    assert "package-updates-scheduled-policy-rejected" in render(False, False)


def test_empty_approval_cannot_authorize_empty_one_run_override():
    from jinja2 import Environment
    import yaml

    source = (ROOT / "states/package_updates/scheduled.sls").read_text()
    cfg = {"enabled": True, "scheduled": True, "manager": "salt", "approved_preview_sha256": ""}
    salt = {"pillar.get": lambda key, default=None: cfg if key == "package_updates" else "" if key == "scheduled_apply_authorized" else default}
    rendered = Environment().from_string(source).render(
        salt=salt, grains={"os_family": "Debian"}, opts={"test": False}
    )
    data = yaml.safe_load(rendered) or {}
    assert "package-updates-scheduled-uptodate" not in data
    assert "package-updates-scheduled-policy-rejected" in data


def test_package_update_operator_docs_exist_and_explain_policy_choice():
    docs = (ROOT / "docs/package-updates.md").read_text()
    assert "Do not enable both managers" in docs
    assert "SUSE" in docs and "rejected" in docs
    assert "Automatic reboot is disabled by default" in docs
    assert "mgmt.rdt.dev" in docs and "disabled until a host opts" in docs


def test_package_update_validator_passes():
    result = subprocess.run(
        [sys.executable, "scripts/validate.py"], cwd=ROOT, text=True,
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT, check=False,
    )
    assert result.returncode == 0, result.stdout
