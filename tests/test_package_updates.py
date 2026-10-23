from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]


def test_package_update_role_is_included_in_base_role():
    role = (ROOT / "states/roles/base.sls").read_text()
    assert "- package_updates" in role


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
