from pathlib import Path
import importlib.util
import subprocess
import sys

import yaml


ROOT = Path(__file__).resolve().parents[1]


def test_caddy_auth_is_generic_and_removes_the_retired_rdt_snippet():
    state = (ROOT / "states/caddy/init.sls").read_text()
    template = (ROOT / "states/caddy/files/Caddyfile.j2").read_text()
    active = state.split("caddy-rdt-llm-auth-snippet-absent:", maxsplit=1)[1].split(
        "caddyfile:", maxsplit=1
    )[0]

    assert "file.absent:" in active
    assert "/etc/caddy/rdt-llm-auth.caddy" in active
    assert "cmd.run:" not in active
    assert "import /etc/caddy/rdt-llm-auth.caddy" not in template
    assert '@authorized header Authorization "Bearer {env.CADDY_BEARER_TOKEN}"' in template



def test_retired_minion_is_not_targeted_or_kept_as_host_pillar():
    pillar_top = yaml.safe_load((ROOT / "pillar/top.sls").read_text())

    assert "rdt-llm" not in yaml.safe_dump(pillar_top)
    assert not (ROOT / "pillar/minions/rdt_llm.sls").exists()


def test_retired_candidate_overlay_is_removed():
    assert not (ROOT / "pillar/candidates/rdt_llm_qwen38_27b_fp8.sls").exists()


def test_active_retired_evaluation_tools_are_not_versioned():
    makefile = (ROOT / "Makefile").read_text()

    assert "rdt-llm-eval" not in makefile
    assert not (ROOT / "scripts/rdt_llm_regression_watch.py").exists()
    assert not (ROOT / "evals/rdt_llm").exists()
    archive_readme = (ROOT / "archive/rdt-llm/README.md").read_text()
    eval_readme = (ROOT / "archive/rdt-llm/evals/README.md").read_text()
    rollback_plan = (ROOT / "archive/rdt-llm/qwen35-to-qwen25-rollback.md").read_text()
    archived_watchdog = (ROOT / "archive/rdt-llm/rdt_llm_regression_watch.py").read_text()
    assert "traceability only" in archive_readme
    assert "ARCHIVED, HISTORICAL ONLY" in eval_readme
    assert "## Run" not in eval_readme
    assert "./evals/rdt_llm/run_full_eval.sh" not in eval_readme
    assert "--allow-business-hours-load" not in eval_readme
    assert "ARCHIVED, HISTORICAL ONLY" in rollback_plan
    assert "ARCHIVED, HISTORICAL ONLY" in archived_watchdog
    for archived_tool in (
        ROOT / "archive/rdt-llm/evals/run_full_eval.sh",
        ROOT / "archive/rdt-llm/evals/scripts/rdt_llm_full_eval.py",
        ROOT / "archive/rdt-llm/rdt_llm_regression_watch.py",
    ):
        assert archived_tool.stat().st_mode & 0o111 == 0
    watcher = subprocess.run(
        [sys.executable, str(ROOT / "archive/rdt-llm/rdt_llm_regression_watch.py")],
        text=True,
        capture_output=True,
        check=False,
    )
    assert watcher.returncode != 0
    assert "ARCHIVED, HISTORICAL ONLY" in watcher.stderr


def test_retired_rollback_plan_is_archived_not_active():
    old_plan = ROOT / ".hermes/plans/2026-08-13_213345-qwen35-to-qwen25-rollback.md"
    archived_plan = ROOT / "archive/rdt-llm/qwen35-to-qwen25-rollback.md"

    assert not old_plan.exists()
    assert archived_plan.is_file()


def test_archived_eval_cli_refuses_to_run_and_infra_probe_is_inert(tmp_path):
    archived_script = ROOT / "archive/rdt-llm/evals/scripts/rdt_llm_full_eval.py"
    result = subprocess.run(
        [sys.executable, str(archived_script), "infra"],
        text=True,
        capture_output=True,
        check=False,
    )
    assert result.returncode != 0
    assert "ARCHIVED, HISTORICAL ONLY" in result.stderr

    spec = importlib.util.spec_from_file_location("archived_rdt_llm_eval", archived_script)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    module.run_command = lambda *args, **kwargs: (_ for _ in ()).throw(
        AssertionError("archived infra probe must not execute commands")
    )
    report = module.infra_probe(tmp_path)
    assert report["status"] == "ARCHIVED"
