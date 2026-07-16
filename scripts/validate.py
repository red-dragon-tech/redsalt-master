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
    'docs/security.md',
    'pillar/top.sls',
    'pillar/common/defaults.sls',
    'pillar/firewall/defaults.sls',
    'pillar/generated/darth_ssh_source.sls',
    'pillar/roles/defaults.sls',
    'pillar/minions/mgmt_rdt_dev.sls',
    'pillar/minions/example-vllm-node.sls',
    'salt-master.d/redsalt-roots.conf.example',
    'states/top.sls',
    'states/common/init.sls',
    'states/firewall/init.sls',
    'states/firewall/refresh.sls',
    'states/firewall/files/redsalt-apply-ufw.py.j2',
    'states/firewall/files/redsalt-refresh-darth-firewall-source.py.j2',
    'states/redsalt_master_sync/init.sls',
    'states/redsalt_master_sync/files/redsalt-sync-prd.sh',
    'states/users/init.sls',
    'states/docker/init.sls',
    'states/nvidia/init.sls',
    'states/models/init.sls',
    'states/vllm/init.sls',
    'states/vllm/files/docker-compose.yml.j2',
    'states/vllm/files/vllm.env.j2',
    'states/vllm/files/vllm-openai.service.j2',
    'tests/test_repo_static.py',
]
ROLE_NAMES = {'base', 'docker', 'nvidia', 'llm_vllm', 'salt_master'}
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
    salt_ports = set((firewall.get('salt') or {}).get('master_ports') or [])
    if salt_ports != {4505, 4506}:
        fail('firewall salt master_ports must be exactly 4505 and 4506')

    dynamic = load_yaml(ROOT / 'pillar/generated/darth_ssh_source.sls') or {}
    darth_sources = ((dynamic.get('firewall_dynamic') or {}).get('darth_ssh_sources') or [])
    if not any(str(source).endswith('/32') for source in darth_sources):
        fail('generated Darth SSH source pillar must contain at least one /32 source')

    base_role = (ROOT / 'states/roles/base.sls').read_text()
    if '- firewall' not in base_role:
        fail('states/roles/base.sls must include firewall state')


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
    check_firewall()
    check_no_obvious_secrets()
    print('redsalt-master validation passed')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
