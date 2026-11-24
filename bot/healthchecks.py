"""Success pings for a Healthchecks.io dead man's switch.

The ping URL is a secret (it contains the check UUID or project ping key).
This module never logs the URL.
"""

import logging
import os

import aiohttp

logger = logging.getLogger(__name__)

_disabled_logged = False
_ok_logged = False


def _ping_url() -> str:
    return os.getenv("HEALTHCHECKS_PING_URL", "").strip()


async def ping_healthchecks() -> str:
    """Send one success ping.

    Returns ``ok``, ``disabled``, or ``failed``. Does not raise: a monitoring
    outage must not stop the trading loop. Failures are logged.
    """
    global _disabled_logged, _ok_logged

    url = _ping_url()
    if not url:
        if not _disabled_logged:
            logger.info("healthchecks ping disabled: HEALTHCHECKS_PING_URL is unset")
            _disabled_logged = True
        return "disabled"

    if not (url.startswith("https://") or url.startswith("http://")):
        logger.error(
            "healthchecks ping refused: HEALTHCHECKS_PING_URL must start with http:// or https://"
        )
        return "failed"

    url = url.rstrip("/")
    try:
        timeout = aiohttp.ClientTimeout(total=10)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.get(url) as resp:
                body = (await resp.text()).strip()
                if resp.status != 200 or body != "OK":
                    logger.error(
                        "healthchecks ping failed status=%s body=%s",
                        resp.status,
                        body[:200],
                    )
                    return "failed"
    except Exception:
        logger.exception("healthchecks ping error")
        return "failed"

    if not _ok_logged:
        logger.info("healthchecks ping ok")
        _ok_logged = True
    return "ok"
