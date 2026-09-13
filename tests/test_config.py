import pytest

from magicbooking_sync.config import load_config


def test_load_config_reads_from_environment(monkeypatch):
    monkeypatch.setenv("MAGICBOOKING_BASE_URL", "https://hurstprimary.magicbooking.co.uk")
    monkeypatch.setenv("MAGICBOOKING_USERNAME", "parent@example.com")
    monkeypatch.setenv("MAGICBOOKING_PASSWORD", "hunter2")
    monkeypatch.setenv("GOOGLE_OAUTH_CLIENT_ID", "client-id")
    monkeypatch.setenv("GOOGLE_OAUTH_CLIENT_SECRET", "client-secret")
    monkeypatch.setenv("GOOGLE_OAUTH_REFRESH_TOKEN", "refresh-token")
    monkeypatch.setenv("GOOGLE_CALENDAR_ID", "cal@group.calendar.google.com")

    config = load_config()

    assert config.magicbooking_base_url == "https://hurstprimary.magicbooking.co.uk"
    assert config.magicbooking_username == "parent@example.com"
    assert config.magicbooking_password == "hunter2"
    assert config.google.client_id == "client-id"
    assert config.google.client_secret == "client-secret"
    assert config.google.refresh_token == "refresh-token"
    assert config.google.calendar_id == "cal@group.calendar.google.com"


def test_load_config_falls_back_to_ssm_when_env_vars_missing(monkeypatch):
    class FakeSSMClient:
        def get_parameters_by_path(self, Path, WithDecryption, Recursive):
            assert Path == "/magicbooking-calendar-sync/"
            assert WithDecryption is True
            assert Recursive is True
            return {
                "Parameters": [
                    {"Name": "/magicbooking-calendar-sync/magicbooking/username", "Value": "u"},
                    {"Name": "/magicbooking-calendar-sync/magicbooking/password", "Value": "p"},
                    {"Name": "/magicbooking-calendar-sync/google/oauth_client_id", "Value": "cid"},
                    {"Name": "/magicbooking-calendar-sync/google/oauth_client_secret", "Value": "csecret"},
                    {"Name": "/magicbooking-calendar-sync/google/oauth_refresh_token", "Value": "rtoken"},
                    {"Name": "/magicbooking-calendar-sync/google/calendar_id", "Value": "cal@x"},
                ]
            }

    # Ensure complete isolation: delete all SSM-backed env vars to force SSM fallback
    monkeypatch.delenv("MAGICBOOKING_USERNAME", raising=False)
    monkeypatch.delenv("MAGICBOOKING_PASSWORD", raising=False)
    monkeypatch.delenv("GOOGLE_OAUTH_CLIENT_ID", raising=False)
    monkeypatch.delenv("GOOGLE_OAUTH_CLIENT_SECRET", raising=False)
    monkeypatch.delenv("GOOGLE_OAUTH_REFRESH_TOKEN", raising=False)
    monkeypatch.delenv("GOOGLE_CALENDAR_ID", raising=False)
    monkeypatch.setenv("MAGICBOOKING_BASE_URL", "https://hurstprimary.magicbooking.co.uk")

    import magicbooking_sync.config as config_module
    monkeypatch.setattr(config_module, "_ssm_client", lambda: FakeSSMClient())

    config = load_config()

    assert config.magicbooking_username == "u"
    assert config.magicbooking_password == "p"
    assert config.google.client_id == "cid"
    assert config.google.calendar_id == "cal@x"
