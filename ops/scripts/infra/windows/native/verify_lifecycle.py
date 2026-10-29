"""Exercise rollback with a real Host listener while the normal pair stays up."""
from pathlib import Path
import socket
import sys

from native_runtime import owned, port_free, read_json, snapshot, up, write_json


def free_port():
    with socket.socket() as listener:
        listener.bind(('127.0.0.1', 0))
        return listener.getsockname()[1]


def main(run):
    primary = read_json(run / 'state.json')
    assert snapshot(primary)['coreReady']
    failure_run = run / 'failure-exercise'
    ai_port, host_port = free_port(), free_port()
    try:
        up(failure_run, ai_port, host_port, fail_after_host=True)
    except RuntimeError as exc:
        assert str(exc) == 'Intentional failure after real Host startup', str(exc)
    else:
        raise AssertionError('Failure exercise did not fail')
    state = read_json(failure_run / 'state.json')
    assert all(owned(record) is None for record in state['processes'].values())
    port_free(ai_port)
    port_free(host_port)
    assert not (failure_run / 'credentials.dpapi').exists()
    assert snapshot(primary)['coreReady']
    result = {'status': 'PASS', 'failure': 'after real Host health before AI start',
              'ownedProcessesAbsent': True, 'portsReleased': True, 'credentialsRemoved': True,
              'originalPairStillHealthy': True, 'failureRun': str(failure_run)}
    write_json(run / 'startup-rollback.json', result)
    print(result)


if __name__ == '__main__':
    main(Path(sys.argv[1]).absolute())
