from __future__ import annotations

from unittest.mock import patch

import pytest

from bot.telegram_notifier import send_telegram_message


class _FakeResponse:
    def __init__(self, *, status: int, body: str = "ok") -> None:
        self.status = status
        self._body = body

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False

    async def text(self) -> str:
        return self._body


class _FakeSession:
    def __init__(self, *, response: _FakeResponse) -> None:
        self.response = response
        self.calls: list[dict] = []

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False

    def post(self, url, *, json, timeout):
        self.calls.append({"url": url, "json": json, "timeout": timeout})
        return self.response


@pytest.mark.asyncio
async def test_send_telegram_message_skips_when_env_missing(monkeypatch):
    monkeypatch.delenv("TELEGRAM_BOT_TOKEN", raising=False)
    monkeypatch.delenv("TELEGRAM_CHAT_ID", raising=False)

    with patch("bot.telegram_notifier.aiohttp.ClientSession") as client_session:
        await send_telegram_message("hello")
    client_session.assert_not_called()


@pytest.mark.asyncio
async def test_send_telegram_message_posts_payload(monkeypatch):
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "abc123")
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "987")

    fake_session = _FakeSession(response=_FakeResponse(status=200))
    with patch("bot.telegram_notifier.aiohttp.ClientSession", return_value=fake_session):
        await send_telegram_message("hello world")

    assert len(fake_session.calls) == 1
    call = fake_session.calls[0]
    assert call["url"] == "https://api.telegram.org/botabc123/sendMessage"
    assert call["json"] == {
        "chat_id": "987",
        "text": "hello world",
        "parse_mode": "HTML",
    }
    assert call["timeout"] == 10.0


@pytest.mark.asyncio
async def test_send_telegram_message_logs_non_200(monkeypatch, caplog):
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "abc123")
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "987")

    fake_session = _FakeSession(response=_FakeResponse(status=500, body="bad request"))
    with patch("bot.telegram_notifier.aiohttp.ClientSession", return_value=fake_session):
        await send_telegram_message("hello")

    assert "Failed to send telegram message" in caplog.text


@pytest.mark.asyncio
async def test_send_telegram_message_logs_exception(monkeypatch, caplog):
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "abc123")
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "987")

    class _FailingSession:
        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        def post(self, *args, **kwargs):
            raise RuntimeError("network down")

    with patch("bot.telegram_notifier.aiohttp.ClientSession", return_value=_FailingSession()):
        await send_telegram_message("hello")

    assert "Error sending telegram message" in caplog.text
