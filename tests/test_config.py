import pytest
from conftest import TOKEN
from fastapi.testclient import TestClient
from pydantic import ValidationError

from api.config import Settings
from api.dedup import Deduplicator
from api.main import create_app


@pytest.mark.parametrize(
    "values",
    [
        {},
        {"webhook_token": "short"},
        {"webhook_token": "a" * 32 + "\n"},
        {"webhook_token": "replace-with-a-random-secret-of-at-least-32-characters"},
        {"webhook_token": TOKEN, "dry_run": False},
        {"webhook_token": TOKEN, "dry_run": False, "flowise_read_only_confirmed": True},
        {"webhook_token": TOKEN, "flowise_base_url": "http://user:secret@host"},
        {"webhook_token": TOKEN, "flowise_base_url": "http://host/path"},
        {"webhook_token": TOKEN, "flowise_base_url": "http://host/?key=secret"},
        {"webhook_token": TOKEN, "flowise_base_url": "file:///etc/passwd"},
        {"webhook_token": TOKEN, "flowise_chatflow_id": "../../evil"},
        {"webhook_token": TOKEN, "flowise_timeout_seconds": float("inf")},
    ],
)
def test_fail_closed_settings(values):
    with pytest.raises(ValidationError):
        Settings(**values)


def test_live_http_requires_explicit_opt_in():
    with pytest.raises(ValidationError, match="HTTPS"):
        Settings(
            webhook_token=TOKEN,
            dry_run=False,
            flowise_read_only_confirmed=True,
            flowise_api_key="test-key",
            flowise_chatflow_id="test-flow",
        )


def test_environment_secret_file_and_conflicts(monkeypatch, tmp_path):
    for name in Settings.model_fields:
        monkeypatch.delenv(name.upper(), raising=False)
    monkeypatch.delenv("FLOWISE_API_KEY_FILE", raising=False)
    secret = tmp_path / "token"
    secret.write_text(TOKEN + "\n")
    monkeypatch.setenv("WEBHOOK_TOKEN_FILE", str(secret))
    settings = Settings.from_environment()
    assert settings.webhook_token.get_secret_value() == TOKEN
    assert TOKEN not in repr(settings)
    monkeypatch.setenv("WEBHOOK_TOKEN", TOKEN)
    with pytest.raises(ValueError, match="either"):
        Settings.from_environment()


def test_startup_errors_do_not_echo_secrets(monkeypatch):
    monkeypatch.setenv("WEBHOOK_TOKEN", "private-bad-value")
    monkeypatch.delenv("WEBHOOK_TOKEN_FILE", raising=False)
    with pytest.raises(RuntimeError) as exc, TestClient(create_app()):
        pass
    assert "private-bad-value" not in str(exc.value)


def test_dedup_ttl_capacity_and_failure_release():
    now = [0]
    cache = Deduplicator(ttl=10, max_entries=2, max_inflight=1, clock=lambda: now[0])
    assert cache.claim("one") == "claimed"
    assert cache.claim("one") == "busy"
    assert cache.claim("two") == "busy"
    cache.release("one")
    assert cache.claim("one") == "claimed"
    cache.finish("one")
    assert cache.claim("one") == "duplicate"
    now[0] = 11
    assert cache.claim("one") == "claimed"
    cache.finish("one")
    for key in ["two", "three"]:
        assert cache.claim(key) == "claimed"
        cache.finish(key)
    assert len(cache.completed) == 2
    assert cache.claim("one") == "claimed"
