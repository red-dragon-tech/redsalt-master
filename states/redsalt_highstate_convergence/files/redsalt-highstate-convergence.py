#!/usr/bin/env python3
"""Run recurring RedSalt highstate convergence from the Salt master.

This wrapper is intended to be launched by a systemd timer on the Salt master.
It avoids overlapping Salt runs, runs non-master minions in small batches, handles
master self-highstate with salt-call to reduce overhead on small masters, records
compact per-minion status, and prints only on failure so monitoring can stay
failure-only.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

LOCK_PATH = Path('/run/redsalt-highstate-convergence.lock')
SYNC_LOCK_PATH = Path('/run/redsalt-master-sync.lock')
STATUS_DIR = Path('/var/lib/redsalt/highstate-status')
LOG_PATH = Path('/var/log/redsalt-highstate-convergence.log')
TMP_SWAP = Path('/swapfile.redsalt-highstate-temp')
TARGET = '*'
BATCH_SIZE = '1'
SALT_TIMEOUT_SECONDS = '600'
MASTER_ID_CMD = ['salt-call', '--local', '--out=json', '--log-level=quiet', 'config.get', 'id']


def utc_now() -> str:
    return datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')


def log(message: str) -> None:
    LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    with LOG_PATH.open('a', encoding='utf-8') as fh:
        fh.write(f'[{utc_now()}] {message}\n')


def run(cmd: list[str], timeout: int = 900) -> subprocess.CompletedProcess[str]:
    log('run: ' + ' '.join(cmd))
    return subprocess.run(cmd, text=True, capture_output=True, timeout=timeout, check=False)


def parse_json_objects(raw: str) -> Any:
    raw = raw.strip()
    if not raw:
        return None
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        decoder = json.JSONDecoder()
        idx = 0
        merged: dict[str, Any] = {}
        saw = False
        while idx < len(raw):
            while idx < len(raw) and raw[idx].isspace():
                idx += 1
            if idx >= len(raw):
                break
            obj, idx = decoder.raw_decode(raw, idx)
            if isinstance(obj, dict):
                merged.update(obj)
                saw = True
            else:
                raise ValueError(f'unexpected JSON member: {obj!r}')
        if saw:
            return merged
        raise


def get_master_id() -> str:
    proc = run(MASTER_ID_CMD, timeout=60)
    if proc.returncode != 0:
        raise RuntimeError(f'could not determine master minion id: {proc.stderr or proc.stdout}')
    data = parse_json_objects(proc.stdout)
    if isinstance(data, dict) and 'local' in data:
        return str(data['local'])
    if isinstance(data, str):
        return data
    raise RuntimeError(f'unexpected master id output: {proc.stdout[:500]}')


def list_accepted_minions() -> list[str]:
    proc = run(['salt-key', '--out=json', '--list=acc'], timeout=120)
    if proc.returncode != 0:
        raise RuntimeError(f'salt-key failed: {proc.stderr or proc.stdout}')
    data = parse_json_objects(proc.stdout)
    if not isinstance(data, dict):
        raise RuntimeError(f'unexpected salt-key output: {proc.stdout[:500]}')
    return sorted(str(x) for x in data.get('minions', []))


def summarize_state_return(ret: Any) -> dict[str, int | bool]:
    summary = {'total': 0, 'changed': 0, 'failed': 0, 'success': True}
    if not isinstance(ret, dict):
        summary['failed'] = 1
        summary['success'] = False
        return summary
    for state_ret in ret.values():
        if not isinstance(state_ret, dict) or 'result' not in state_ret:
            continue
        summary['total'] += 1
        if state_ret.get('result') is not True:
            summary['failed'] += 1
            summary['success'] = False
        changes = state_ret.get('changes')
        if changes:
            summary['changed'] += 1
    return summary


def write_status(minion: str, payload: dict[str, Any]) -> None:
    STATUS_DIR.mkdir(parents=True, exist_ok=True)
    tmp = STATUS_DIR / f'.{minion}.json.tmp'
    dst = STATUS_DIR / f'{minion}.json'
    tmp.write_text(json.dumps(payload, indent=2, sort_keys=True) + '\n', encoding='utf-8')
    os.replace(tmp, dst)


def mem_total_kb() -> int:
    for line in Path('/proc/meminfo').read_text().splitlines():
        if line.startswith('MemTotal:'):
            return int(line.split()[1])
    return 0


def swap_active(path: Path) -> bool:
    proc = run(['swapon', '--show=NAME', '--noheadings'], timeout=30)
    return str(path) in proc.stdout.splitlines()


def ensure_temp_swap() -> bool:
    if mem_total_kb() >= 1048576 or swap_active(TMP_SWAP):
        return False
    log('enabling temporary 1G swap for low-memory self-highstate')
    if TMP_SWAP.exists():
        TMP_SWAP.unlink()
    proc = run(['fallocate', '-l', '1G', str(TMP_SWAP)], timeout=120)
    if proc.returncode != 0:
        proc = run(['dd', 'if=/dev/zero', f'of={TMP_SWAP}', 'bs=1M', 'count=1024', 'status=none'], timeout=180)
        if proc.returncode != 0:
            raise RuntimeError(f'could not create temp swap: {proc.stderr or proc.stdout}')
    TMP_SWAP.chmod(0o600)
    for cmd in (['mkswap', str(TMP_SWAP)], ['swapon', str(TMP_SWAP)]):
        proc = run(cmd, timeout=60)
        if proc.returncode != 0:
            raise RuntimeError(f'{cmd[0]} failed: {proc.stderr or proc.stdout}')
    return True


def remove_temp_swap(enabled: bool) -> None:
    if not enabled:
        return
    log('disabling temporary swap')
    run(['swapoff', str(TMP_SWAP)], timeout=120)
    try:
        TMP_SWAP.unlink()
    except FileNotFoundError:
        pass


def run_remote_minions(master_id: str, minions: list[str], started: str) -> tuple[list[dict[str, Any]], list[str]]:
    targets = [m for m in minions if m != master_id]
    results: list[dict[str, Any]] = []
    failures: list[str] = []
    if not targets:
        return results, failures
    target_expr = ','.join(targets)
    proc = run([
        'salt', '-t', SALT_TIMEOUT_SECONDS, '--batch-size', BATCH_SIZE,
        '-L', target_expr, 'state.apply', '--out=json', '--state-output=changes'
    ], timeout=int(SALT_TIMEOUT_SECONDS) * max(1, len(targets)) + 120)
    raw = proc.stdout.strip()
    parsed: Any = {}
    try:
        parsed = parse_json_objects(raw) or {}
    except Exception as exc:  # noqa: BLE001
        failures.append(f'remote highstate JSON parse failed: {exc}; stdout={raw[:500]} stderr={proc.stderr[:500]}')
        parsed = {}
    if proc.returncode != 0:
        failures.append(f'remote highstate command rc={proc.returncode}; stderr={proc.stderr[:500]}')
    returned = set(parsed.keys()) if isinstance(parsed, dict) else set()
    for minion in targets:
        finished = utc_now()
        if minion not in returned:
            payload = {
                'minion': minion,
                'started_at': started,
                'finished_at': finished,
                'success': False,
                'failed': 1,
                'changed': 0,
                'total': 0,
                'jid': None,
                'mode': 'master-batch',
                'error': 'missing return from salt command',
            }
            failures.append(f'{minion}: missing return')
        else:
            summary = summarize_state_return(parsed[minion])
            payload = {
                'minion': minion,
                'started_at': started,
                'finished_at': finished,
                'jid': None,
                'mode': 'master-batch',
                **summary,
            }
            if not payload['success']:
                failures.append(f"{minion}: highstate failed states={payload['failed']} changed={payload['changed']} total={payload['total']}")
        write_status(minion, payload)
        results.append(payload)
    return results, failures


def run_master_self(master_id: str, started: str) -> tuple[dict[str, Any], list[str]]:
    failures: list[str] = []
    swap_enabled = False
    try:
        swap_enabled = ensure_temp_swap()
        proc = run([
            'salt-call', '--retcode-passthrough', '--out=json', '--log-level=quiet',
            'state.apply', '--state-output=changes'
        ], timeout=int(SALT_TIMEOUT_SECONDS) + 300)
    finally:
        remove_temp_swap(swap_enabled)
    finished = utc_now()
    parsed: Any = None
    try:
        parsed = parse_json_objects(proc.stdout)
    except Exception as exc:  # noqa: BLE001
        failures.append(f'{master_id}: self-highstate JSON parse failed: {exc}; stdout={proc.stdout[:500]} stderr={proc.stderr[:500]}')
    local_ret = parsed.get('local') if isinstance(parsed, dict) and 'local' in parsed else parsed
    summary = summarize_state_return(local_ret)
    if proc.returncode != 0:
        summary['success'] = False
        failures.append(f'{master_id}: self-highstate rc={proc.returncode}; stderr={proc.stderr[:500]}')
    payload = {
        'minion': master_id,
        'started_at': started,
        'finished_at': finished,
        'jid': None,
        'mode': 'salt-call-local',
        **summary,
    }
    if not payload['success'] and not any(f.startswith(master_id + ':') for f in failures):
        failures.append(f"{master_id}: self-highstate failed states={payload['failed']} changed={payload['changed']} total={payload['total']}")
    write_status(master_id, payload)
    return payload, failures


def main() -> int:
    started = utc_now()
    STATUS_DIR.mkdir(parents=True, exist_ok=True)
    LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    lock_fd = os.open(LOCK_PATH, os.O_CREAT | os.O_RDWR, 0o600)
    sync_lock_fd = os.open(SYNC_LOCK_PATH, os.O_CREAT | os.O_RDWR, 0o600)
    try:
        import fcntl
        try:
            fcntl.flock(lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return 0
        try:
            fcntl.flock(sync_lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            log('redsalt-master-sync lock is held; skipping convergence run')
            return 0
        log('convergence run start')
        failures: list[str] = []
        master_id = get_master_id()
        minions = list_accepted_minions()
        if not minions:
            raise RuntimeError('no accepted minions found')
        results, remote_failures = run_remote_minions(master_id, minions, started)
        failures.extend(remote_failures)
        master_payload, master_failures = run_master_self(master_id, started)
        results.append(master_payload)
        failures.extend(master_failures)
        aggregate = {
            'started_at': started,
            'finished_at': utc_now(),
            'master_id': master_id,
            'minions': minions,
            'success': not failures,
            'failures': failures,
            'results': results,
        }
        write_status('summary', aggregate)
        log('convergence run complete success=' + str(not failures))
        if failures:
            print('ISSUE: RedSalt highstate convergence failed')
            print(f'Started: {started}')
            print(f'Finished: {aggregate["finished_at"]}')
            print(f'Status dir: {STATUS_DIR}')
            print(f'Log: {LOG_PATH}')
            print('Failures:')
            for failure in failures:
                print(f'- {failure}')
            return 1
        return 0
    except Exception as exc:  # noqa: BLE001
        log('fatal: ' + repr(exc))
        print('ISSUE: RedSalt highstate convergence wrapper failed')
        print(f'Started: {started}')
        print(f'Log: {LOG_PATH}')
        print(f'Error: {exc}')
        return 1
    finally:
        os.close(sync_lock_fd)
        os.close(lock_fd)


if __name__ == '__main__':
    raise SystemExit(main())
