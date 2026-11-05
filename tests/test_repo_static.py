from pathlib import Path
import subprocess
import sys


def test_static_validator_passes():
    root = Path(__file__).resolve().parents[1]
    result = subprocess.run(
        [sys.executable, 'scripts/validate.py'],
        cwd=root,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        check=False,
    )
    assert result.returncode == 0, result.stdout
    assert 'validation passed' in result.stdout


def test_promptfoo_redteam_deployment_is_opt_in_and_never_autoruns_or_exposes_http():
    root = Path(__file__).resolve().parents[1]
    state = (root / 'states/kali_workstation/init.sls').read_text()
    pillar = (root / 'pillar/minions/rdt_kali.sls').read_text()
    assert "cfg.get('promptfoo_mcp_redteam', {})" in state
    assert "promptfoo.get('enabled', False)" in state
    assert 'pkg.installed:' in state
    assert 'nodejs' in state and 'npm' in state
    assert 'promptfoo_mcp_redteam.py' in state
    assert ' check --project-dir ' in state
    assert 'redteam run' not in state
    assert 'mcp --transport http' not in state
    assert 'enabled: true' in pillar
    assert 'REPLACE-WITH-AUTHORIZED-MCP-ENDPOINT.example/mcp' in pillar


def test_promptfoo_setup_executes_as_configured_unprivileged_owner():
    root = Path(__file__).resolve().parents[1]
    state = (root / 'states/kali_workstation/init.sls').read_text()
    init_at = state.index('kali-promptfoo-redteam-project-init:')
    init_end = state.index('kali-promptfoo-redteam-prerequisite-check:', init_at)
    init_state = state[init_at:init_end]
    check_at = state.index('kali-promptfoo-redteam-prerequisite-check:')
    check_end = state.index('{% endif %}', check_at)
    check_state = state[check_at:check_end]
    assert 'runas: {{ promptfoo_owner }}' in init_state
    assert 'runas: {{ promptfoo_owner }}' in check_state
    assert "project_repo_config.get('mode', '0750')" in state
    assert 'kali-promptfoo-redteam-node-version:' in state
    assert 'process.versions.node' in state
