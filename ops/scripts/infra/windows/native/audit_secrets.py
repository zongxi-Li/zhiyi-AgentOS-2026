"""Check known run secrets without displaying their values. Run before down."""
import hashlib
from pathlib import Path
import subprocess
import sys

from native_runtime import ROOT, credentials, write_json


def main(run):
    known = [value.encode() for value in credentials(run).values()]
    candidates = list(run.rglob('*.log')) + list(run.rglob('*.json'))
    candidates += list((ROOT / 'ops/scripts/infra/windows/native').glob('*.*'))
    candidates += [ROOT / 'apps/agent/requirements.native-tools.lock']
    leaks = []
    for path in candidates:
        content = path.read_bytes()
        if any(secret in content for secret in known):
            leaks.append(str(path))
    staged = subprocess.check_output(['git', 'diff', '--cached', '--binary'], cwd=ROOT)
    assert not any(secret in staged for secret in known), 'Known secret found in index'
    result = {'status': 'FAIL' if leaks else 'PASS', 'filesScanned': len(candidates),
              'leakPaths': leaks, 'knownSecretValuesLogged': False if not leaks else True,
              'stagedDiffSha256': hashlib.sha256(staged).hexdigest(),
              'credentialsStorage': 'Windows current-user DPAPI; removed by down'}
    write_json(run / 'secret-audit.json', result)
    print(result)
    return bool(leaks)


if __name__ == '__main__':
    raise SystemExit(main(Path(sys.argv[1]).absolute()))
