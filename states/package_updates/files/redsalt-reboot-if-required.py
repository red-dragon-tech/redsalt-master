#!/usr/bin/env python3
"""Reboot only when the OS reports one is required, in the maintenance window."""
import shutil
import subprocess
import sys
from pathlib import Path


def reboot_required():
    if Path('/var/run/reboot-required').exists() or Path('/run/reboot-required').exists():
        return True
    if Path('/run/ostree-booted').exists() and shutil.which('rpm-ostree'):
        result = subprocess.run(
            ['rpm-ostree', 'status', '--json'], capture_output=True, text=True, check=False
        )
        if result.returncode != 0:
            raise RuntimeError('rpm-ostree status check failed')
        import json
        status = json.loads(result.stdout)
        deployments = status.get('deployments') or []
        return bool(deployments and deployments[0].get('pending'))
    checker = shutil.which('needs-restarting')
    if checker:
        result = subprocess.run([checker, '-r'], check=False)
        if result.returncode == 1:
            return True
        if result.returncode == 0:
            return False
        raise RuntimeError(f'needs-restarting returned {result.returncode}')
    return False


def main():
    try:
        if not reboot_required():
            print('No reboot required.')
            return 0
        print('OS reports reboot required; scheduling reboot now.')
        return subprocess.run(['/usr/bin/systemctl', 'reboot'], check=False).returncode
    except Exception as exc:
        print(f'ERROR: reboot requirement check failed: {exc}', file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
