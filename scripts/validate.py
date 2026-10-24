#!/usr/bin/env python3
"""Static validation for the redsalt-master repository.

This intentionally does not require a running Salt master. It checks file
presence, YAML parseability, Jinja syntax, role/top-file consistency, and
obvious committed secret patterns.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

try:
    import yaml
except Exception as exc:  # pragma: no cover
    print(f"ERROR: PyYAML is required for validation: {exc}", file=sys.stderr)
    sys.exit(2)

try:
    from jinja2 import Environment
except Exception as exc:  # pragma: no cover
    print(f"ERROR: Jinja2 is required for validation: {exc}", file=sys.stderr)
    sys.exit(2)

ROOT = Path(__file__).resolve().parents[1]
REQUIRED = [
    'README.md',
    'docs/architecture.md',
    'docs/operations.md',
    'docs/package-updates.md',
    'docs/security.md',
    'pillar/top.sls',
    'pillar/common/defaults.sls',
    'pillar/firewall/defaults.sls',
    'pillar/generated/darth_ssh_source.sls',
    'pillar/roles/defaults.sls',
    'pillar/restic_backup/defaults.sls',
    'pillar/minions/mgmt_rdt_dev.sls',
    'pillar/package_updates/defaults.sls',
    'pillar/minions/rdt_kali.sls',
    'pillar/minions/example-vllm-node.sls',
    'salt-master.d/redsalt-roots.conf.example',
    'states/top.sls',
    'states/common/init.sls',
    'states/caddy/init.sls',
    'states/caddy/files/Caddyfile.j2',
    'states/firewall/init.sls',
    'states/firewall/refresh.sls',
    'states/firewall/files/redsalt-apply-ufw.py.j2',
    'states/firewall/files/redsalt-refresh-darth-firewall-source.py.j2',
    'states/kali_workstation/init.sls',
    'states/redsalt_master_sync/init.sls',
    'states/redsalt_master_sync/files/redsalt-sync-prd.sh',
    'states/redsalt_highstate_convergence/init.sls',
    'states/redsalt_highstate_convergence/files/redsalt-highstate-convergence.py',
    'states/redsalt_package_updates/init.sls',
    'states/redsalt_package_updates/files/redsalt-package-updates.py',
    'states/restic_backup/init.sls',
    'states/package_updates/init.sls',
    'states/package_updates/scheduled.sls',
    'states/package_updates/files/redsalt-reboot-if-required.py',
    'states/restic_backup/files/rdt-restic-backup.sh.j2',
    'states/restic_backup/files/restic-backup.service.j2',
    'states/restic_backup/files/restic-backup.timer.j2',
    'states/users/init.sls',
    'states/docker/init.sls',
    'states/nvidia/init.sls',
    'states/models/init.sls',
    'states/vllm/init.sls',
    'states/vllm/files/docker-compose.yml.j2',
    'states/vllm/files/clear-corrupt-triton-cache.sh.j2',
    'states/vllm/files/vllm.env.j2',
    'states/vllm/files/vllm-openai.service.j2',
    'tests/test_repo_static.py',
    'tests/test_package_updates.py',
    'tests/test_redsalt_package_updates.py',
]
ROLE_NAMES = {'base', 'docker', 'nvidia', 'llm_vllm', 'salt_master', 'kali_workstation', 'restic_backup'}
DARTHAI_PUBLIC_KEY = 'ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIMKydWK+ac8LWsdujDXLIVTfAo5D1PxMr0+pcUn6Z5sG darth@hermes-agent-rdt-dev-1-remote-management'
SECRET_PATTERNS = [
    re.compile(r'(?i)(api[_-]?key|token|password|secret)\s*[:=]\s*[A-Za-z0-9_./+=-]{20,}'),
    re.compile(r'gh[pousr]_[A-Za-z0-9_]{20,}'),
    re.compile(r'hf_[A-Za-z0-9]{20,}'),
]


def fail(message: str) -> None:
    print(f'ERROR: {message}', file=sys.stderr)
    sys.exit(1)


def load_yaml(path: Path):
    try:
        return yaml.safe_load(path.read_text())
    except Exception as exc:
        fail(f'YAML parse failed for {path.relative_to(ROOT)}: {exc}')


def check_required() -> None:
    missing = [p for p in REQUIRED if not (ROOT / p).exists()]
    if missing:
        fail('missing required files: ' + ', '.join(missing))


def check_yaml() -> None:
    for path in list((ROOT / 'pillar').rglob('*.sls')) + list(ROOT.rglob('*.yaml')) + list(ROOT.rglob('*.yml')):
        load_yaml(path)


def check_jinja() -> None:
    env = Environment()
    for path in list((ROOT / 'states').rglob('*.sls')) + list((ROOT / 'states').rglob('*.j2')):
        try:
            env.parse(path.read_text())
        except Exception as exc:
            fail(f'Jinja parse failed for {path.relative_to(ROOT)}: {exc}')


def check_roles() -> None:
    roles_defaults = load_yaml(ROOT / 'pillar/roles/defaults.sls') or {}
    roles = set((roles_defaults.get('roles') or {}).keys())
    if roles != ROLE_NAMES:
        fail(f'pillar/roles/defaults.sls roles {sorted(roles)} != expected {sorted(ROLE_NAMES)}')

    top = (ROOT / 'states/top.sls').read_text()
    for role in ROLE_NAMES:
        if f"roles:{role}:true" not in top:
            fail(f'states/top.sls missing pillar matcher for role {role}')
        if not (ROOT / f'states/roles/{role}.sls').exists():
            fail(f'missing state role file for {role}')


def check_managed_users() -> None:
    common_defaults = load_yaml(ROOT / 'pillar/common/defaults.sls') or {}
    users = common_defaults.get('managed_users') or []
    darthai = next((user for user in users if user.get('name') == 'darthai'), None)
    if not darthai:
        fail('pillar/common/defaults.sls missing managed_users entry for darthai')
    if darthai.get('home') != '/home/darthai':
        fail('darthai managed user must use /home/darthai as home')
    if DARTHAI_PUBLIC_KEY not in (darthai.get('ssh_authorized_keys') or []):
        fail('darthai managed user missing expected SSH public key')

    base_role = (ROOT / 'states/roles/base.sls').read_text()
    if '- users' not in base_role:
        fail('states/roles/base.sls must include users state')


def check_restic_backup() -> None:
    defaults = load_yaml(ROOT / 'pillar/restic_backup/defaults.sls') or {}
    cfg = defaults.get('restic_backup') or {}
    if cfg.get('enabled') is not False:
        fail('restic_backup defaults must keep backups disabled until per-host secrets are provisioned')
    retention = cfg.get('retention') or {}
    if retention.get('daily') != 14 or retention.get('weekly') != 8 or retention.get('monthly') != 12:
        fail('restic_backup retention must default to 14 daily / 8 weekly / 12 monthly')
    includes = [str(x) for x in (cfg.get('includes') or [])]
    for required in ['/etc', '/root', '/home', '/opt', '/usr/local', '/var/lib', '/var/spool/cron']:
        if required not in includes:
            fail(f'restic_backup default includes missing {required}')
    excludes = [str(x) for x in (cfg.get('excludes') or [])]
    for required in ['/var/lib/docker/overlay2', '/var/lib/containerd', '/var/lib/kubelet']:
        if required not in excludes:
            fail(f'restic_backup default excludes missing {required}')

    rdt_kali = load_yaml(ROOT / 'pillar/minions/rdt_kali.sls') or {}
    kali_restic = rdt_kali.get('restic_backup') or {}
    if 'rdt-kali' not in [str(x) for x in (kali_restic.get('tags') or [])]:
        fail('rdt_kali restic_backup must tag snapshots with rdt-kali')
    if '/usr/share/wordlists' not in [str(x) for x in (kali_restic.get('excludes') or [])]:
        fail('rdt_kali restic_backup must exclude large wordlists by default')

    script = (ROOT / 'states/restic_backup/files/rdt-restic-backup.sh.j2').read_text()
    for required in ['flock -n', 'RESTIC_PASSWORD_FILE', 'forget', '--prune', 'check --read-data-subset']:
        if required not in script:
            fail(f'restic backup script missing required behavior: {required}')
    state = (ROOT / 'states/restic_backup/init.sls').read_text()
    for required in ['replace: False', 'mode: \'0600\'', 'service.dead']:
        if required not in state:
            fail(f'restic_backup state missing safe manual-secret behavior: {required}')


def check_qwen_tool_template() -> None:
    template = (ROOT / 'states/vllm/files/qwen25_coder_tool_chat_template.jinja').read_text()
    if '<think>\\n\\n</think>\\n\\n' not in template:
        fail('Qwen chat template must prefill an empty think block to suppress thinking output')


def check_firewall() -> None:
    firewall_defaults = load_yaml(ROOT / 'pillar/firewall/defaults.sls') or {}
    firewall = firewall_defaults.get('firewall') or {}
    if firewall.get('enabled') is not True:
        fail('pillar/firewall/defaults.sls must enable firewall by default')
    if firewall.get('default_incoming') != 'deny':
        fail('firewall default_incoming must be deny')
    if firewall.get('default_outgoing') != 'allow':
        fail('firewall default_outgoing must be allow')
    ssh_sources = ((firewall.get('ssh') or {}).get('allowed_sources') or [])
    if not any(str(source).endswith('/32') for source in ssh_sources):
        fail('firewall ssh allowed_sources must contain at least one /32 fallback')
    salt_sources = ((firewall.get('salt') or {}).get('master_sources') or [])
    if not all(str(source).endswith('/32') for source in salt_sources):
        fail('firewall salt master_sources must be tightly scoped /32 CIDRs')
    minion_sources = ((firewall.get('salt') or {}).get('minion_sources') or [])
    if not all(str(source).endswith('/32') for source in minion_sources):
        fail('firewall salt minion_sources must be tightly scoped /32 CIDRs')
    salt_ports = set((firewall.get('salt') or {}).get('master_ports') or [])
    if salt_ports != {4505, 4506}:
        fail('firewall salt master_ports must be exactly 4505 and 4506')

    kali_pillar = load_yaml(ROOT / 'pillar/minions/rdt_kali.sls') or {}
    kali_roles = kali_pillar.get('roles') or {}
    if kali_roles.get('kali_workstation') is not True:
        fail('rdt_kali pillar must enable roles:kali_workstation')
    kali_salt_sources = (((kali_pillar.get('firewall') or {}).get('salt') or {}).get('master_sources') or [])
    if '10.10.10.0/24' not in [str(source) for source in kali_salt_sources]:
        fail('rdt_kali pillar must allow the private LAN Salt master/source CIDR 10.10.10.0/24')

    dynamic = load_yaml(ROOT / 'pillar/generated/darth_ssh_source.sls') or {}
    darth_sources = ((dynamic.get('firewall_dynamic') or {}).get('darth_ssh_sources') or [])
    if not any(str(source).endswith('/32') for source in darth_sources):
        fail('generated Darth SSH source pillar must contain at least one /32 source')

    base_role = (ROOT / 'states/roles/base.sls').read_text()
    if '- firewall' not in base_role:
        fail('states/roles/base.sls must include firewall state')


def check_package_updates() -> None:
    defaults = load_yaml(ROOT / 'pillar/package_updates/defaults.sls') or {}
    cfg = defaults.get('package_updates') or {}
    if cfg.get('manager') not in {'salt', 'native'}:
        fail('package_updates manager must be salt or native')
    if cfg.get('enabled') is not False:
        fail('package_updates defaults must remain opt-in until explicitly assigned per host')
    if cfg.get('native_unattended') is not False:
        fail('native unattended managers must default off to avoid package-manager races')
    state = (ROOT / 'states/package_updates/init.sls').read_text()
    for required in ['pkg.uptodate', 'unattended-upgrades', 'dnf-automatic-install.timer', 'dnf5-plugin-automatic', 'dnf5-automatic.timer', 'Persistent=false']:
        if required not in state:
            fail(f'package update state missing platform behavior: {required}')
    if 'APT::Periodic::Unattended-Upgrade "0";' not in state:
        fail('Salt-owned Debian updates must explicitly disable native unattended installs')
    scheduled_state = (ROOT / 'states/package_updates/scheduled.sls').read_text()
    if 'pkg.uptodate:' not in scheduled_state or 'scheduled_run:' not in scheduled_state:
        fail('scheduled updates need a separate mutating state protected by explicit schedule policy')
    if 'package_updates.scheduled' not in (ROOT / 'states/redsalt_package_updates/files/redsalt-package-updates.py').read_text():
        fail('scheduled runner must invoke the dedicated scheduled package-update state')
    if 'scheduled_apply_authorized' not in scheduled_state or 'approved_preview_sha256' not in scheduled_state:
        fail('scheduled state must reject live applies without matching exact-preview authorization')
    if "approved_hash|length == 64" not in scheduled_state or 'approval_valid and scheduled_apply_authorized == approved_hash' not in scheduled_state:
        fail('scheduled apply approval must require a nonempty 64-character fingerprint before equality')
    if "opts.get('test', False)" not in scheduled_state:
        fail('scheduled state must use Salt template test-mode options for preview execution')
    if "'pillar=' + json.dumps({'scheduled_apply_authorized'" not in (ROOT / 'states/redsalt_package_updates/files/redsalt-package-updates.py').read_text():
        fail('scheduled runner must pass approval through Salt state Pillar override')
    role = (ROOT / 'states/roles/base.sls').read_text()
    if '- package_updates' not in role:
        fail('states/roles/base.sls must include package_updates state')
    top = (ROOT / 'pillar/top.sls').read_text()
    if '- package_updates.defaults' not in top:
        fail('pillar/top.sls must include global package_updates defaults')
    master = load_yaml(ROOT / 'pillar/minions/mgmt_rdt_dev.sls') or {}
    master_cfg = master.get('package_updates') or {}
    if master_cfg.get('manager') != 'salt' or master_cfg.get('enabled') is not True:
        fail('mgmt.rdt.dev must explicitly enable Salt-managed package updates')
    if master_cfg.get('automatic_reboot') is not True or master_cfg.get('reboot_time') != '06:00':
        fail('mgmt.rdt.dev must explicitly set its reboot check to 06:00')
    if master_cfg.get('debian_dist_upgrade') is not False:
        fail('mgmt.rdt.dev must keep Debian dist_upgrade disabled')
    if master_cfg.get('native_unattended') is not False:
        fail('mgmt.rdt.dev must not run a competing native package updater')


def check_kali_package_updates() -> None:
    kali = load_yaml(ROOT / 'pillar/minions/rdt_kali.sls') or {}
    cfg = kali.get('package_updates') or {}
    if cfg.get('enabled') is not True or cfg.get('manager') != 'salt' or cfg.get('scheduled') is not True:
        fail('rdt-kali must explicitly opt in to scheduled Salt package updates')
    if cfg.get('cadence_days') != 7 or cfg.get('stale_after_days', 0) < 8:
        fail('rdt-kali must use weekly updates and a separately observable stale threshold')
    if cfg.get('window_days') != ['Sat'] or cfg.get('window_start') != '02:00' or cfg.get('window_end') != '05:00':
        fail('rdt-kali must keep updates inside the documented Saturday maintenance window')
    if cfg.get('timezone') != 'America/Chicago' or cfg.get('require_idle') is not True:
        fail('rdt-kali updates must use its local timezone and require an idle interactive session')
    if cfg.get('max_upgrades') != 750 or cfg.get('timeout_seconds') != 3600:
        fail('rdt-kali update safety limits are missing or changed')
    if cfg.get('debian_dist_upgrade') is not False or cfg.get('native_unattended') is not False:
        fail('rdt-kali must disable distribution upgrade and native unattended updates')
    if cfg.get('automatic_reboot') is not False:
        fail('rdt-kali automatic reboot must remain disabled')
    if cfg.get('approved_preview_sha256') != '':
        fail('rdt-kali must remain non-mutating until the exact preview is approved')
    package_state = (ROOT / 'states/package_updates/init.sls').read_text()
    if "os_family == 'Debian' and not cfg.get('native_unattended', False)" not in package_state:
        fail('Salt-owned Kali update policy must explicitly disable native unattended APT installs')
    master = load_yaml(ROOT / 'pillar/minions/mgmt_rdt_dev.sls') or {}
    managed = ((master.get('redsalt_package_updates') or {}).get('managed_minions') or [])
    if managed != ['rdt-kali']:
        fail('package update runner scope must explicitly contain only rdt-kali')
    role = (ROOT / 'states/roles/salt_master.sls').read_text()
    if '- redsalt_package_updates' not in role:
        fail('salt_master role must include redsalt_package_updates scheduler state')
    base_role = (ROOT / 'states/roles/base.sls').read_text()
    package_state = (ROOT / 'states/package_updates/init.sls').read_text()
    if "enabled and manager == 'salt' and not scheduled" not in package_state:
        fail('scheduled package updates must be excluded from routine base highstate')
    runner = (ROOT / 'states/redsalt_package_updates/files/redsalt-package-updates.py').read_text()
    for required in ('pkg.refresh_db', 'pkg.list_upgrades', 'state.apply', 'manual_attention', 'stale_minions'):
        if required not in runner:
            fail(f'package update runner missing required evidence behavior: {required}')


def check_no_obvious_secrets() -> None:
    skip_dirs = {'.git', '__pycache__', '.pytest_cache'}
    for path in ROOT.rglob('*'):
        if not path.is_file() or any(part in skip_dirs for part in path.parts):
            continue
        text = path.read_text(errors='ignore')
        for pattern in SECRET_PATTERNS:
            if pattern.search(text):
                fail(f'possible committed secret in {path.relative_to(ROOT)}')


def main() -> int:
    check_required()
    check_yaml()
    check_jinja()
    check_roles()
    check_managed_users()
    check_restic_backup()
    check_qwen_tool_template()
    check_firewall()
    check_package_updates()
    check_kali_package_updates()
    check_no_obvious_secrets()
    print('redsalt-master validation passed')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
