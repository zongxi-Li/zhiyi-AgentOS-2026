"""Repair tools must select an N03 directory explicitly and never create missing stores."""
from pathlib import Path
import subprocess
import sys

import pytest

ROOT = Path(__file__).resolve().parents[4]


@pytest.mark.parametrize('script', ['backfill_identity_runs.py', 'backfill_resume_attempts.py'])
def test_backfill_requires_explicit_existing_data_directory(script, tmp_path):
    command = [sys.executable, str(ROOT / 'ops/scripts' / script)]
    missing_argument = subprocess.run(command, capture_output=True, text=True)
    assert missing_argument.returncode == 2
    assert '--data-dir' in missing_argument.stderr
    missing_stores = subprocess.run(command + ['--data-dir', str(tmp_path)], capture_output=True)
    assert missing_stores.returncode == 2
    assert list(tmp_path.iterdir()) == []
