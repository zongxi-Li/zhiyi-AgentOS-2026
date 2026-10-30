import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'windows/native'))
import terminal_service


def test_terminal_transport_credential_is_separate_from_runtime_and_provider_secrets(tmp_path):
    creds = {'hmac': 'host-secret', 'deepseek': 'model-secret', 'token': 'api-secret'}
    values = terminal_service.desktop_environment(tmp_path, {'portOffset': 400}, creds)
    assert values['KINLIN_TERMINAL_ENDPOINT'] == 'http://127.0.0.1:19166'
    assert len(values['KINLIN_TERMINAL_TOKEN']) == 64
    assert set(values) == {'KINLIN_TERMINAL_ENDPOINT', 'KINLIN_TERMINAL_TOKEN'}
    assert all(value not in values['KINLIN_TERMINAL_TOKEN'] for value in creds.values())
    assert terminal_service.desktop_environment(tmp_path, {'portOffset': 400}, creds) == values
