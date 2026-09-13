import httpx
import pytest

from magicbooking_sync.portal_client import PortalLoginError, login


def test_login_raises_when_antiforgery_field_missing():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text="<html><body>no token here</body></html>")

    transport = httpx.MockTransport(handler)
    real_client_cls = httpx.Client
    try:
        httpx.Client = lambda *a, **k: real_client_cls(*a, transport=transport, **k)
        with pytest.raises(PortalLoginError, match="antiforgery"):
            login(base_url="https://example.invalid", username="u", password="p")
    finally:
        httpx.Client = real_client_cls
