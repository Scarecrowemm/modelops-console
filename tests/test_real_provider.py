import pytest

from app import providers, real_provider


def test_real_provider_is_disabled_without_env(monkeypatch):
    for key in ("MODELOPS_REAL_BASE_URL", "MODELOPS_REAL_API_KEY", "MODELOPS_REAL_MODEL"):
        monkeypatch.delenv(key, raising=False)
    assert real_provider.available() is False
    model = {"id": "real-chat", "provider_id": "prov_real", "display_name": "Real Chat"}
    with pytest.raises(providers.ProviderError):
        providers.call(model, [{"role": "user", "content": "hi"}])
