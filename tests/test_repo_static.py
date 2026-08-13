from pathlib import Path
import subprocess


def test_static_validator_passes():
    root = Path(__file__).resolve().parents[1]
    result = subprocess.run(
        ['python3', 'scripts/validate.py'],
        cwd=root,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        check=False,
    )
    assert result.returncode == 0, result.stdout
    assert 'validation passed' in result.stdout
