from __future__ import annotations

from unittest.mock import patch

import pytest

import bot.healthchecks as healthchecks
from bot.healthchecks import ping_healthchecks


class _FakeResponse:
    def __init__(self, *, status: int, body: str) -> None:
        self.status = status
        self._body = body

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False

    async def text(self) -> str:
        return self._body


class _FakeSession:
    def __init__(self, *, response: _FakeResponse | None = None, error: Exception | None = None) -> None:
        self.response = response
        self.error = error
        self.calls: list[str] = []

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False

    def get(self, url):
        self.calls.append(url)
        if self.error is not None:
            raise self.error
        return self.response


@pytest.fixture(autouse=True)
def _reset_log_flags():
    healthchecks._disabled_logged = False
    healthchecks._ok_logged = False
    yield


@pytest.mark.asyncio
async def test_ping_disabled_when_url_unset(monkeypatch, caplog):
    caplog.set_level("INFO", logger="bot.healthchecks")
    monkeypatch.delenv("HEALTHCHECKS_PING_URL", raising=False)
    with patch("bot.healthchecks.aiohttp.ClientSession") as client_session:
        first = await ping_healthchecks()
        second = await ping_healthchecks()
    assert first == "disabled"
    assert second == "disabled"
    client_session.assert_not_called()
    assert caplog.text.count("HEALTHCHECKS_PING_URL is unset") == 1


@pytest.mark.asyncio
async def test_ping_refuses_non_http_url(monkeypatch, caplog):
    monkeypatch.setenv("HEALTHCHECKS_PING_URL", "hc-ping.com/not-a-url")
    with patch("bot.healthchecks.aiohttp.ClientSession") as client_session:
        result = await ping_healthchecks()
    assert result == "failed"
    client_session.assert_not_called()
    assert "must start with http:// or https://" in caplog.text


@pytest.mark.asyncio
async def test_ping_get_success(monkeypatch, caplog):
    caplog.set_level("INFO", logger="bot.healthchecks")
    monkeypatch.setenv(
        "HEALTHCHECKS_PING_URL",
        "https://hc-ping.com/5bf66975-d4c7-4bf5-bcc8-b8d8a82ea278/",
    )
    fake = _FakeSession(response=_FakeResponse(status=200, body="OK\n"))
    with patch("bot.healthchecks.aiohttp.ClientSession", return_value=fake):
        first = await ping_healthchecks()
        second = await ping_healthchecks()
    assert first == "ok"
    assert second == "ok"
    assert fake.calls == [
        "https://hc-ping.com/5bf66975-d4c7-4bf5-bcc8-b8d8a82ea278",
        "https://hc-ping.com/5bf66975-d4c7-4bf5-bcc8-b8d8a82ea278",
    ]
    assert caplog.text.count("healthchecks ping ok") == 1


@pytest.mark.asyncio
async def test_ping_logs_non_ok_body(monkeypatch, caplog):
    monkeypatch.setenv("HEALTHCHECKS_PING_URL", "https://hc-ping.com/uuid")
    fake = _FakeSession(response=_FakeResponse(status=200, body="OK (not found)"))
    with patch("bot.healthchecks.aiohttp.ClientSession", return_value=fake):
        result = await ping_healthchecks()
    assert result == "failed"
    assert "healthchecks ping failed status=200" in caplog.text
    assert "not found" in caplog.text


@pytest.mark.asyncio
async def test_ping_logs_exception(monkeypatch, caplog):
    monkeypatch.setenv("HEALTHCHECKS_PING_URL", "https://hc-ping.com/uuid")
    fake = _FakeSession(error=RuntimeError("network down"))
    with patch("bot.healthchecks.aiohttp.ClientSession", return_value=fake):
        result = await ping_healthchecks()
    assert result == "failed"
    assert "healthchecks ping error" in caplog.text
    assert "network down" in caplog.text
