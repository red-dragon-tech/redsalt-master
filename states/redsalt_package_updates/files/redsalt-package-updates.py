#!/usr/bin/env python3
"""Run explicitly enrolled Salt package updates inside each minion's safe window.

The master timer is only a scheduler. This runner never updates hosts unless
pillar explicitly opts them into manager=salt. Per-minion policy controls
cadence, local-time window, interactive-session guard, and upgrade limit.
"""
from __future__ import annotations

import fcntl
import hashlib
import json
import os
import re
import subprocess

from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

LOCK_PATH = Path('/run/redsalt-package-updates.lock')
SYNC_LOCK_PATH = Path('/run/redsalt-master-sync.lock')
CONVERGENCE_LOCK_PATH = Path('/run/redsalt-highstate-convergence.lock')
STATUS_DIR = Path('/var/lib/redsalt/package-updates')
LOG_PATH = Path('/var/log/redsalt-package-updates.log')
SALT_TIMEOUT_SECONDS = 900
ALERT_INTERVAL = timedelta(hours=24)


def utc_now() -> str:
    return datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')


def parse_timestamp(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace('Z', '+00:00'))
    except (TypeError, ValueError):
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def parse_json_objects(raw: str) -> Any:
    raw = raw.strip()
    if not raw:
        return None
    decoder = json.JSONDecoder()
    objects: list[Any] = []
    idx = 0
    while idx < len(raw):
        starts = [pos for pos in (raw.find('{', idx), raw.find('[', idx)) if pos >= 0]
        if not starts:
            break
        idx = min(starts)
        try:
            obj, idx = decoder.raw_decode(raw, idx)
        except json.JSONDecodeError:
            idx += 1
            continue
        objects.append(obj)
    if not objects:
        raise ValueError('no JSON object found in command output')
    if len(objects) == 1:
        return objects[0]
    merged: dict[str, Any] = {}
    if all(isinstance(obj, dict) for obj in objects):
        for obj in objects:
            merged.update(obj)
        return merged
    raise ValueError('unexpected mixed JSON output')


def run(cmd: list[str], timeout: int = SALT_TIMEOUT_SECONDS) -> subprocess.CompletedProcess[str]:
    return subprocess.run(cmd, text=True, capture_output=True, timeout=timeout, check=False)


def eligible_minions(policies: dict[str, Any]) -> list[str]:
    # discover_policies has already restricted this mapping to the explicit
    # management-pillar allowlist. Keep misconfigured targets in the result so
    # their bad opt-in becomes a visible failure instead of silent omission.
    return sorted(policies)


def is_safe_exact_minion_id(minion: str) -> bool:
    return minion not in {'', '.', '..'} and re.fullmatch(r'[A-Za-z0-9._-]+', minion) is not None


def in_window(start: str, end: str, now: datetime) -> bool:
    try:
        start_hour, start_minute = (int(part) for part in start.split(':', 1))
        end_hour, end_minute = (int(part) for part in end.split(':', 1))
        start_minute_of_day = start_hour * 60 + start_minute
        end_minute_of_day = end_hour * 60 + end_minute
    except (AttributeError, TypeError, ValueError):
        return False
    if not (0 <= start_hour < 24 and 0 <= start_minute < 60 and 0 <= end_hour < 24 and 0 <= end_minute < 60):
        return False
    if start_minute_of_day == end_minute_of_day:
        return False
    current = now.hour * 60 + now.minute
    if start_minute_of_day < end_minute_of_day:
        return start_minute_of_day <= current < end_minute_of_day
    return current >= start_minute_of_day or current < end_minute_of_day


def window_has_time_remaining(start: str, end: str, now: datetime, required_seconds: int) -> bool:
    """Require a bounded operation to fit before the current local window ends."""
    try:
        sh, sm = (int(part) for part in start.split(':', 1))
        eh, em = (int(part) for part in end.split(':', 1))
        start_minute = sh * 60 + sm
        end_minute = eh * 60 + em
    except (AttributeError, TypeError, ValueError):
        return False
    if not (0 <= sh < 24 and 0 <= sm < 60 and 0 <= eh < 24 and 0 <= em < 60):
        return False
    if start_minute == end_minute or not in_window(start, end, now):
        return False
    current_seconds = now.hour * 3600 + now.minute * 60 + now.second
    end_seconds = end_minute * 60
    if start_minute > end_minute and current_seconds >= start_minute * 60:
        end_seconds += 24 * 3600
    remaining = end_seconds - current_seconds
    return remaining >= required_seconds


def is_window_day(days: list[str], now: datetime) -> bool:
    return now.strftime('%a') in days


def is_due(last_success: str | None, cadence_days: int, now: datetime) -> bool:
    """Return whether the successful-update cadence has elapsed."""
    previous = parse_timestamp(last_success)
    return previous is None or now.astimezone(timezone.utc) - previous >= timedelta(days=cadence_days)


def retry_due(last_attempt: str | None, cadence_days: int, now: datetime) -> bool:
    """Limit repeated failed attempts to at most one per policy cadence."""
    previous = parse_timestamp(last_attempt)
    if previous is None:
        return True
    age = now.astimezone(timezone.utc) - previous
    return age >= timedelta(days=cadence_days)


def is_stale(last_success: str | None, stale_days: int, now: datetime) -> bool:
    previous = parse_timestamp(last_success)
    return previous is None or now.astimezone(timezone.utc) - previous > timedelta(days=stale_days)


def is_idle_session_output(output: str) -> bool:
    return not any(line.strip() for line in output.splitlines())


def summarize_state_return(ret: Any) -> dict[str, int | bool]:
    summary: dict[str, int | bool] = {'total': 0, 'changed': 0, 'failed': 0, 'success': True}
    if not isinstance(ret, dict):
        summary.update(failed=1, success=False)
        return summary
    for state_ret in ret.values():
        if not isinstance(state_ret, dict) or 'result' not in state_ret:
            continue
        summary['total'] += 1
        if state_ret.get('result') is not True:
            summary['failed'] += 1
            summary['success'] = False
        if state_ret.get('changes'):
            summary['changed'] += 1
    if summary['total'] == 0:
        summary.update(failed=1, success=False)
    return summary


def summarize_test_return(ret: Any, minion_id: str) -> dict[str, Any]:
    summary: dict[str, Any] = {'total': 0, 'planned': 0, 'failed': 0, 'success': True, 'planned_changes': []}
    if not isinstance(ret, dict):
        summary.update(failed=1, success=False)
        return summary
    for state_id, state_ret in ret.items():
        if not isinstance(state_ret, dict) or 'result' not in state_ret:
            continue
        summary['total'] += 1
        if state_ret.get('result') is False:
            summary['failed'] += 1
            summary['success'] = False
        if state_ret.get('changes'):
            summary['planned'] += 1
            summary['planned_changes'].append({
                'state_id': str(state_id),
                'name': str(state_ret.get('name', '')),
                'changes': state_ret.get('changes'),
                'comment': str(state_ret.get('comment', '')),
            })
    if summary['total'] == 0:
        summary.update(failed=1, success=False)
    fingerprint_payload = {'minion_id': minion_id, 'planned_changes': summary['planned_changes']}
    summary['planned_changes_sha256'] = hashlib.sha256(
        json.dumps(fingerprint_payload, sort_keys=True, separators=(',', ':')).encode()
    ).hexdigest()
    return summary


def preview_is_approved(policy: dict[str, Any], preview: dict[str, Any]) -> bool:
    approved = policy.get('approved_preview_sha256')
    return (
        isinstance(approved, str)
        and len(approved) == 64
        and approved == preview.get('planned_changes_sha256')
        and preview.get('success') is True
    )


def status_path(minion: str) -> Path:
    # Salt minion IDs are not trusted as filesystem paths.
    safe = ''.join(char if char.isalnum() or char in '._-' else '_' for char in minion)
    if safe in {'', '.', '..'}:
        raise ValueError('invalid minion id')
    return STATUS_DIR / f'{safe}.json'


def read_status(minion: str) -> dict[str, Any]:
    try:
        data = json.loads(status_path(minion).read_text(encoding='utf-8'))
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return {}
    return data if isinstance(data, dict) else {}


def write_status(minion: str, payload: dict[str, Any]) -> None:
    STATUS_DIR.mkdir(parents=True, exist_ok=True)
    dst = status_path(minion)
    tmp = dst.with_name('.' + dst.name + '.tmp')
    tmp.write_text(json.dumps(payload, indent=2, sort_keys=True) + '\n', encoding='utf-8')
    os.replace(tmp, dst)


def write_summary(payload: dict[str, Any]) -> None:
    STATUS_DIR.mkdir(parents=True, exist_ok=True)
    dst = STATUS_DIR / 'summary.json'
    tmp = STATUS_DIR / '.summary.json.tmp'
    tmp.write_text(json.dumps(payload, indent=2, sort_keys=True) + '\n', encoding='utf-8')
    os.replace(tmp, dst)


def log(message: str) -> None:
    LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    if LOG_PATH.exists() and LOG_PATH.stat().st_size > 2 * 1024 * 1024:
        previous = LOG_PATH.read_bytes()[-1024 * 1024:]
        LOG_PATH.write_bytes(previous)
    with LOG_PATH.open('a', encoding='utf-8') as stream:
        stream.write(f'[{utc_now()}] {message}\n')


def salt_json(
    cmd: list[str], label: str, timeout: int = SALT_TIMEOUT_SECONDS
) -> dict[str, Any]:
    proc = run(cmd, timeout=timeout)
    if proc.returncode != 0:
        raise RuntimeError(f'{label} failed (rc={proc.returncode})')
    parsed = parse_json_objects(proc.stdout)
    if not isinstance(parsed, dict):
        raise RuntimeError(f'{label} returned unexpected data')
    return parsed


def discover_policies() -> dict[str, Any]:
    master = salt_json(
        ['salt-call', '--local', '--out=json', '--log-level=quiet', 'config.get', 'id'],
        'local master id query',
    )
    master_id = master.get('local')
    if not isinstance(master_id, str) or not master_id.strip():
        raise RuntimeError('could not determine Salt master id')
    management = salt_json([
        'salt', '-t', '60', master_id, 'pillar.get', 'redsalt_package_updates', '--out=json'
    ], 'management package update policy query').get(master_id)
    managed = management.get('managed_minions') if isinstance(management, dict) else None
    if (not isinstance(managed, list) or not managed
            or any(not isinstance(item, str) or not is_safe_exact_minion_id(item) for item in managed)):
        raise RuntimeError('redsalt_package_updates:managed_minions must explicitly list monitored targets')
    policies: dict[str, Any] = {}
    for minion in sorted({str(item) for item in managed}):
        try:
            returned = salt_json([
                'salt', '-t', '60', minion, 'pillar.get', 'package_updates', '--out=json'
            ], f'{minion} package update pillar query')
            policy = returned.get(minion)
            if isinstance(policy, dict):
                policies[minion] = policy
            else:
                policies[minion] = {'enabled': True, 'manager': 'salt', 'scheduled': True,
                                    'configuration_error': 'target did not return package update policy'}
        except (RuntimeError, ValueError, KeyError, TypeError, OSError, subprocess.TimeoutExpired) as exc:
            policies[minion] = {'enabled': True, 'manager': 'salt', 'scheduled': True,
                                'configuration_error': str(exc)}
    return policies


def update_minion(minion: str, policy: dict[str, Any], now: datetime) -> dict[str, Any]:
    old = read_status(minion)
    started = utc_now()
    payload = dict(old)
    payload.update({'minion': minion, 'manager': 'salt'})
    try:
        if policy.get('configuration_error'):
            raise RuntimeError('could not read explicit minion package update policy')
        if not all(key in policy for key in ('cadence_days', 'stale_after_days')):
            raise RuntimeError('explicit minion package update policy is missing cadence/staleness values')
        payload['cadence_days'] = int(policy['cadence_days'])
        payload['stale_after_days'] = int(policy['stale_after_days'])
        if (policy.get('debian_dist_upgrade') is not False
                or policy.get('native_unattended') is not False
                or policy.get('automatic_reboot') is not False
                or policy.get('refresh') is not True):
            raise RuntimeError('Kali policy must explicitly retain safe Salt-only, no-reboot update semantics')
        if (policy.get('enabled') is not True or policy.get('manager') != 'salt'
                or policy.get('scheduled') is not True):
            raise RuntimeError('allowlisted minion must explicitly opt into scheduled Salt updates')
        timezone_name = str(policy['timezone'])
        try:
            local_now = now.astimezone(ZoneInfo(timezone_name))
        except ZoneInfoNotFoundError as exc:
            raise RuntimeError('unknown configured timezone') from exc

        days = policy.get('window_days')
        if not isinstance(days, list) or not days:
            raise RuntimeError('package update maintenance days must be explicitly configured')
        if not is_window_day([str(day) for day in days], local_now):
            return payload
        if 'window_start' not in policy or 'window_end' not in policy:
            raise RuntimeError('package update maintenance window must be explicitly configured')
        cadence_days = int(policy['cadence_days'])
        stale_after_days = int(policy['stale_after_days'])
        payload['stale_after_days'] = stale_after_days
        max_upgrades = int(policy['max_upgrades'])
        timeout_seconds = int(policy['timeout_seconds'])
        if cadence_days < 1 or stale_after_days <= cadence_days or max_upgrades < 1:
            raise RuntimeError('invalid cadence, staleness, or upgrade-limit policy values')
        if not 30 <= timeout_seconds <= 3600:
            raise RuntimeError('package update timeout must be between 30 and 3600 seconds')
        if not in_window(str(policy['window_start']), str(policy['window_end']), local_now):
            return payload
        if policy.get('require_idle') is not True:
            raise RuntimeError('package update idle-session safety gate must be explicitly enabled')
        if old.get('last_result') == 'deferred_window_deadline':
            due = True
        elif (old.get('last_result') == 'preview_ready'
                and policy.get('approved_preview_sha256')
                == old.get('test_mode_preview', {}).get('planned_changes_sha256')):
            due = True
        elif old.get('last_result') in {'failed', 'preview_ready', 'skipped_active_session'}:
            due = retry_due(old.get('last_attempt'), cadence_days, now)
        else:
            due = is_due(old.get('last_success'), cadence_days, now)
        approved_fingerprint = policy.get('approved_preview_sha256')
        if approved_fingerprint and approved_fingerprint != old.get('test_mode_preview', {}).get('planned_changes_sha256'):
            due = True
        if not due:
            return payload

        if policy.get('require_idle') is True:
            session_by_id = salt_json([
                'salt', '-t', '60', minion, 'cmd.run', 'loginctl list-sessions --no-legend', '--out=json'
            ], f'{minion} interactive-session check', timeout=90)
            session_output = session_by_id.get(minion)
            if not isinstance(session_output, str):
                raise RuntimeError('could not verify interactive-session safety gate')
            if not is_idle_session_output(session_output):
                payload.update({
                    'last_result': 'skipped_active_session',
                    'finished_at': utc_now(),
                    'last_error': 'interactive session detected; updates deferred',
                })
                write_status(minion, payload)
                return payload

        payload.update({'last_attempt': started, 'last_result': 'running', 'last_error': None})

        refresh_by_id = salt_json([
            'salt', '-t', '120', minion, 'pkg.refresh_db', '--out=json'
        ], f'{minion} package metadata refresh', timeout=150)
        if refresh_by_id.get(minion) is not True:
            raise RuntimeError('package metadata refresh failed')
        upgrades_by_id = salt_json([
            'salt', '-t', '60', minion, 'pkg.list_upgrades', '--out=json'
        ], f'{minion} package-upgrade inventory', timeout=90)
        upgrades = upgrades_by_id.get(minion)
        if not isinstance(upgrades, dict):
            raise RuntimeError('package-upgrade inventory missing target return')
        upgrade_count = len(upgrades)
        payload['available_upgrades'] = upgrade_count
        if upgrade_count > max_upgrades:
            raise RuntimeError(f'upgrade count {upgrade_count} exceeds safety limit {max_upgrades}')

        if upgrade_count:
            clock_by_id = salt_json([
                'salt', '-t', '30', minion, 'cmd.run', 'date --iso-8601=seconds', '--out=json'
            ], f'{minion} maintenance-window time check', timeout=60)
            host_time = clock_by_id.get(minion)
            if not isinstance(host_time, str):
                raise RuntimeError('could not verify target maintenance-window deadline')
            host_local_now = parse_timestamp(host_time)
            if host_local_now is None:
                raise RuntimeError('target maintenance-window clock returned invalid timestamp')
            host_local_now = host_local_now.astimezone(ZoneInfo(timezone_name))
            if not is_window_day([str(day) for day in days], host_local_now) or not window_has_time_remaining(
                str(policy['window_start']), str(policy['window_end']), host_local_now,
                timeout_seconds * 2 + 900,
            ):
                payload.update({
                    'last_result': 'deferred_window_deadline',
                    'finished_at': utc_now(),
                    'last_error': 'target clock is outside the configured maintenance day/window',
                })
                write_status(minion, payload)
                return payload
            if not window_has_time_remaining(
                str(policy['window_start']), str(policy['window_end']),
                host_local_now, timeout_seconds + 600,
            ):
                payload.update({
                    'last_result': 'deferred_window_deadline',
                    'finished_at': utc_now(),
                    'last_error': 'not enough maintenance-window time remains for bounded preview, update, and verification',
                })
                write_status(minion, payload)
                return payload
            preview_by_id = salt_json([
                'salt', '-t', str(timeout_seconds),
                minion, 'state.apply', 'package_updates.scheduled', 'test=True', '--out=json',
                '--state-output=changes',
                'pillar=' + json.dumps({'scheduled_apply_authorized': policy.get('approved_preview_sha256', '')}, separators=(',', ':'))
            ], f'{minion} package update test-mode preview',
                timeout=timeout_seconds + 120)
            preview = summarize_test_return(preview_by_id.get(minion), minion)
            payload['test_mode_preview'] = preview
            if preview['success'] is not True:
                raise RuntimeError(f"package update test-mode preview failed ({preview['failed']} failed of {preview['total']})")
            if preview['planned'] == 0:
                raise RuntimeError('package upgrades were found but test mode produced no reviewable planned changes')
            payload['last_attempt'] = started
            payload['last_result'] = 'preview_ready'
            payload['finished_at'] = utc_now()
            payload['last_error'] = None
            payload['success'] = True
            payload['approved_preview_sha256'] = policy.get('approved_preview_sha256')
            payload['manual_attention'] = 'Test-mode preview is ready; live package application awaits approval of this exact plan fingerprint.'
            write_status(minion, payload)
            if not preview_is_approved(policy, preview):
                if old.get('reboot_required') is True and old.get('manual_attention'):
                    payload['manual_attention'] = old['manual_attention']
                    payload['reboot_required'] = True
                    payload['reboot_check_verified'] = old.get('reboot_check_verified', False)
                    write_status(minion, payload)
                return payload
            if not window_has_time_remaining(
                str(policy['window_start']), str(policy['window_end']),
                host_local_now, timeout_seconds + 600,
            ):
                payload.update({
                    'last_result': 'deferred_window_deadline',
                    'finished_at': utc_now(),
                    'last_error': 'maintenance window no longer has enough time for bounded update and verification',
                })
                write_status(minion, payload)
                return payload
            apply_clock_by_id = salt_json([
                'salt', '-t', '30', minion, 'cmd.run', 'date --iso-8601=seconds', '--out=json'
            ], f'{minion} pre-apply maintenance-window time check', timeout=60)
            apply_time = apply_clock_by_id.get(minion)
            apply_now = parse_timestamp(apply_time) if isinstance(apply_time, str) else None
            if apply_now is None:
                raise RuntimeError('could not verify target clock immediately before package application')
            apply_now = apply_now.astimezone(ZoneInfo(timezone_name))
            if (not is_window_day([str(day) for day in days], apply_now)
                    or not window_has_time_remaining(
                        str(policy['window_start']), str(policy['window_end']), apply_now,
                        timeout_seconds + 600)):
                payload.update({
                    'last_result': 'deferred_window_deadline',
                    'finished_at': utc_now(),
                    'last_error': 'maintenance window deadline is too near or has passed; live update deferred',
                })
                write_status(minion, payload)
                return payload
            if policy.get('require_idle') is True:
                final_session = salt_json([
                    'salt', '-t', '60', minion, 'cmd.run',
                    'loginctl list-sessions --no-legend', '--out=json'
                ], f'{minion} pre-apply interactive-session check', timeout=90).get(minion)
                if not isinstance(final_session, str):
                    raise RuntimeError('could not verify interactive-session safety immediately before package application')
                if not is_idle_session_output(final_session):
                    payload.update({
                        'last_result': 'skipped_active_session',
                        'finished_at': utc_now(),
                        'last_error': 'interactive session detected before package application; updates deferred',
                    })
                    write_status(minion, payload)
                    return payload
            # Package indexes may move while an operator approval is pending.
            # Re-preview immediately before live apply and require the same digest.
            latest_refresh_by_id = salt_json([
                'salt', '-t', '120', minion, 'pkg.refresh_db', '--out=json'
            ], f'{minion} approved-plan metadata refresh', timeout=150)
            if latest_refresh_by_id.get(minion) is not True:
                raise RuntimeError('could not refresh package metadata before applying approved plan')
            latest_preview_by_id = salt_json([
                'salt', '-t', str(timeout_seconds),
                minion, 'state.apply', 'package_updates.scheduled', 'test=True', '--out=json',
                '--state-output=changes',
                'pillar=' + json.dumps({'scheduled_apply_authorized': policy.get('approved_preview_sha256', '')}, separators=(',', ':'))
            ], f'{minion} approved-plan revalidation preview',
                timeout=timeout_seconds + 120)
            latest_preview = summarize_test_return(latest_preview_by_id.get(minion), minion)
            if (latest_preview.get('success') is not True
                    or latest_preview.get('planned_changes_sha256') != preview.get('planned_changes_sha256')):
                payload.update({
                    'last_result': 'preview_changed',
                    'finished_at': utc_now(),
                    'last_error': 'test-mode plan changed after approval; live update blocked pending renewed approval',
                    'test_mode_preview': latest_preview,
                    'manual_attention': 'Package plan changed after approval; review and approve the new exact test-mode fingerprint.',
                })
                if old.get('reboot_required') is True and old.get('manual_attention'):
                    payload['manual_attention'] = (
                        old['manual_attention'] + ' Package plan also changed after approval; review the new exact test-mode fingerprint.'
                    )
                    payload['reboot_required'] = True
                    payload['reboot_check_verified'] = old.get('reboot_check_verified', False)
                write_status(minion, payload)
                return payload
            after_preview_clock = salt_json([
                'salt', '-t', '30', minion, 'cmd.run', 'date --iso-8601=seconds', '--out=json'
            ], f'{minion} post-revalidation maintenance-window time check', timeout=60)
            after_preview_time = after_preview_clock.get(minion)
            apply_now = parse_timestamp(after_preview_time) if isinstance(after_preview_time, str) else None
            if apply_now is None:
                raise RuntimeError('could not verify target clock after approved-plan revalidation')
            apply_now = apply_now.astimezone(ZoneInfo(timezone_name))
            if (not is_window_day([str(day) for day in days], apply_now)
                    or not window_has_time_remaining(
                        str(policy['window_start']), str(policy['window_end']), apply_now,
                        timeout_seconds + 600)):
                payload.update({
                    'last_result': 'deferred_window_deadline',
                    'finished_at': utc_now(),
                    'last_error': 'maintenance window closed or too near expiry during plan revalidation',
                })
                write_status(minion, payload)
                return payload
            if policy.get('require_idle') is True:
                final_session = salt_json([
                    'salt', '-t', '60', minion, 'cmd.run',
                    'loginctl list-sessions --no-legend', '--out=json'
                ], f'{minion} final pre-apply interactive-session check', timeout=90).get(minion)
                if not isinstance(final_session, str):
                    raise RuntimeError('could not verify interactive-session safety after plan revalidation')
                if not is_idle_session_output(final_session):
                    payload.update({
                        'last_result': 'skipped_active_session',
                        'finished_at': utc_now(),
                        'last_error': 'interactive session detected after plan revalidation; updates deferred',
                    })
                    write_status(minion, payload)
                    return payload
            payload['approved_preview_sha256'] = policy['approved_preview_sha256']
            state_by_id = salt_json([
                'salt', '-t', str(timeout_seconds),
                minion, 'state.apply', 'package_updates.scheduled', '--out=json', '--state-output=changes',
                'pillar=' + json.dumps({'scheduled_apply_authorized': policy.get('approved_preview_sha256', '')}, separators=(',', ':'))
            ], f'{minion} package update',
                timeout=timeout_seconds + 120)
            state_ret = state_by_id.get(minion)
            result = summarize_state_return(state_ret)
            payload.update(result)
            if result['success'] is not True:
                raise RuntimeError(f"Salt package state failed ({result['failed']} failed of {result['total']})")
            remaining_by_id = salt_json([
                'salt', '-t', '60', minion, 'pkg.list_upgrades', '--out=json'
            ], f'{minion} post-update verification', timeout=90)
            remaining = remaining_by_id.get(minion)
            if not isinstance(remaining, dict):
                raise RuntimeError('post-update package inventory missing target return')
            payload['remaining_upgrades'] = len(remaining)
            if remaining:
                raise RuntimeError(f'{len(remaining)} package upgrades remain after update')
        else:
            payload.update({'total': 0, 'changed': 0, 'failed': 0, 'success': True, 'remaining_upgrades': 0})

        reboot_by_id = salt_json([
            'salt', '-t', '60', minion, 'file.file_exists', '/var/run/reboot-required', '--out=json'
        ], f'{minion} reboot-required verification', timeout=90)
        reboot_required = reboot_by_id.get(minion)
        if not isinstance(reboot_required, bool):
            raise RuntimeError('reboot-required check did not return a boolean')
        payload['reboot_required'] = reboot_required
        payload['reboot_check_verified'] = True
        if reboot_required:
            payload['manual_attention'] = 'OS reports reboot required; reboot is not automatic and needs an approved maintenance/reboot action.'
        else:
            payload.pop('manual_attention', None)

        payload['last_success'] = utc_now()
        payload['last_result'] = 'success'
        payload['last_error'] = None
    except (RuntimeError, ValueError, KeyError, TypeError, OSError, subprocess.TimeoutExpired) as exc:
        if old.get('reboot_required') is True and 'manual_attention' in old:
            payload['manual_attention'] = old['manual_attention']
        payload.update({
            'success': False,
            'failed': 1,
            'last_attempt': started,
            'last_result': 'failed',
            'last_error': str(exc),
        })
    payload['finished_at'] = utc_now()
    write_status(minion, payload)
    return payload


def main() -> int:
    started = utc_now()
    STATUS_DIR.mkdir(parents=True, exist_ok=True)
    lock_path = LOCK_PATH
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    with lock_path.open('a+', encoding='utf-8') as lock:
        try:
            fcntl.flock(lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return 0
        held_locks = []
        try:
            for path in (SYNC_LOCK_PATH, CONVERGENCE_LOCK_PATH):
                fd = os.open(path, os.O_CREAT | os.O_RDWR, 0o600)
                held_locks.append(fd)
                try:
                    fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                except BlockingIOError:
                    return 0
            if Path('/run/lock').is_dir():
                fallback_lock = Path('/run/lock/redsalt-highstate-convergence.lock')
                fd = os.open(fallback_lock, os.O_CREAT | os.O_RDWR, 0o600)
                held_locks.append(fd)
                try:
                    fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                except BlockingIOError:
                    log('legacy highstate convergence lock is held; skipping package update')
                    return 0
            policies = discover_policies()
            eligible = eligible_minions(policies)
            now = datetime.now(timezone.utc)
            results: list[dict[str, Any]] = []
            for minion in eligible:
                try:
                    results.append(update_minion(minion, policies[minion], now))
                except Exception as exc:  # keep monitoring other explicitly managed hosts
                    result = read_status(minion)
                    result.update({
                        'minion': minion,
                        'last_result': 'failed',
                        'success': False,
                        'last_error': f'unhandled per-minion runner error: {exc}',
                        'finished_at': utc_now(),
                    })
                    write_status(minion, result)
                    results.append(result)
            failures: list[str] = []
            failure_alerts: list[str] = []
            alerts: list[str] = []
            attention: list[str] = []
            stale_minions: list[str] = []
            has_attention = False
            for result in results:
                minion = result['minion']
                # A previously failed run remains visible until a later success,
                # even when this invocation is outside the local maintenance window.
                if result.get('last_result') == 'failed':
                    failure = f"{minion}: {result.get('last_error', 'package update failed')}"
                    failures.append(failure)
                    last_failure_alert = parse_timestamp(result.get('last_failure_alert_at'))
                    if last_failure_alert is None or now - last_failure_alert >= ALERT_INTERVAL:
                        failure_alerts.append(failure)
                        result['last_failure_alert_at'] = utc_now()
                elif result.get('last_result') == 'skipped_active_session' and (
                    not result.get('last_success')
                    or is_stale(result.get('last_success'), int(result.get('stale_after_days', 9)), now)
                ):
                    failure = f"{minion}: no successful package update yet; interactive session continues to defer maintenance"
                    failures.append(failure)
                    last_failure_alert = parse_timestamp(result.get('last_failure_alert_at'))
                    if last_failure_alert is None or now - last_failure_alert >= ALERT_INTERVAL:
                        failure_alerts.append(failure)
                        result['last_failure_alert_at'] = utc_now()
                if result.get('manual_attention'):
                    has_attention = True
                    notice = f"{minion}: {result['manual_attention']}"
                    last_attention_alert = parse_timestamp(result.get('last_attention_alert_at'))
                    if last_attention_alert is None or now - last_attention_alert >= ALERT_INTERVAL:
                        attention.append(notice)
                        result['last_attention_alert_at'] = utc_now()
                stale = is_stale(result.get('last_success'), int(result.get('stale_after_days', 9)), now)
                result['stale'] = stale
                if stale:
                    stale_minions.append(minion)
                    last_alert = parse_timestamp(result.get('last_alert_at'))
                    if last_alert is None or now - last_alert >= ALERT_INTERVAL:
                        alerts.append(f"{minion}: package update success is stale or has never succeeded")
                        result['last_alert_at'] = utc_now()
                write_status(minion, result)
            summary = {
                'started_at': started,
                'finished_at': utc_now(),
                'eligible_minions': eligible,
                'monitored_minions': eligible,
                'monitoring_complete': bool(eligible),
                'success': not failures and not stale_minions and not has_attention,
                'failures': failures,
                'failure_alerts': failure_alerts,
                'manual_attention': attention,
                'stale_minions': stale_minions,
                'stale_alerts': alerts,
                'results': results,
            }
            write_summary(summary)
            if not eligible:
                print('ISSUE: RedSalt package update monitor has no explicitly managed minions')
                return 1
            if failure_alerts or alerts or attention:
                log(f'package update run completed with {len(failures)} failures and {len(alerts)} stale alerts')
                print('ISSUE: RedSalt package update policy needs attention')
                for item in failure_alerts + alerts + attention:
                    print(f'- {item}')
                print(f'Status: {STATUS_DIR}/summary.json')
                return 1
            log(f'package update check completed for {len(eligible)} opted-in minions')
            return 0
        except (RuntimeError, ValueError, OSError, subprocess.TimeoutExpired) as exc:
            log(f'package update runner failed: {exc}')
            print('ISSUE: RedSalt package update runner failed')
            print(f'Error: {exc}')
            return 1
        finally:
            for fd in held_locks:
                os.close(fd)


if __name__ == '__main__':
    raise SystemExit(main())
