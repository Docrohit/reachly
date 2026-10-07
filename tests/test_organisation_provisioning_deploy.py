import json
import stat
import pytest
from deploy.enable_organisation_provisioning import enable


def test_enable_existing_client_preserves_config_and_is_idempotent(tmp_path):
    config = tmp_path / 'generation.json'
    original = {'clients': {'hyclinics': {'token_env': 'SERVICE_TOKEN', 'provider': 'clinic-provider', 'business_ids': ['legacy']},
                            'other': {'business_ids': ['other']}}, 'providers': {'clinic-provider': {}}}
    config.write_text(json.dumps(original))
    config.chmod(0o640)
    env = tmp_path / 'runtime.env'
    env.write_text(f'REACHLY_GENERATION_CONFIG={config}\nSERVICE_TOKEN=synthetic-only\n')
    assert enable(env) is True
    expected = json.loads(json.dumps(original))
    expected['clients']['hyclinics']['organisation_provisioning'] = True
    assert json.loads(config.read_text()) == expected
    assert stat.S_IMODE(config.stat().st_mode) == 0o640
    backup, = tmp_path.glob('.before-org-onboarding-*')
    assert json.loads(backup.read_text()) == original
    assert stat.S_IMODE(backup.stat().st_mode) == 0o600
    assert enable(env) is False
    assert len(list(tmp_path.glob('.before-org-onboarding-*'))) == 1


def test_missing_service_configuration_fails_closed(tmp_path):
    config = tmp_path / 'generation.json'
    config.write_text('{"clients": {}}')
    env = tmp_path / 'runtime.env'
    env.write_text(f'REACHLY_GENERATION_CONFIG={config}\n')
    with pytest.raises(ValueError, match='already be configured'):
        enable(env)
    assert json.loads(config.read_text()) == {'clients': {}}
    assert not list(tmp_path.glob('.before-org-onboarding-*'))
