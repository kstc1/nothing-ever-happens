import argparse
import asyncio
import os
import sys
from datetime import datetime, timezone

from dotenv import load_dotenv

from bot.telegram_notifier import send_telegram_message


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Send a test Telegram alert.")
    parser.add_argument(
        "--message",
        default="Telegram notifier test",
        help="Custom message text for the test alert.",
    )
    return parser.parse_args()


async def _run(message: str) -> int:
    bot_token = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
    chat_id = os.getenv("TELEGRAM_CHAT_ID", "").strip()
    if not bot_token or not chat_id:
        print("Missing TELEGRAM_BOT_TOKEN or TELEGRAM_CHAT_ID in environment/.env.")
        return 1

    ts = datetime.now(timezone.utc).isoformat()
    payload = f"🧪 <b>Telegram Test</b>\n{message}\nUTC: {ts}"
    await send_telegram_message(payload)
    print("Telegram test message sent. Check your Telegram chat.")
    return 0


def main() -> int:
    load_dotenv()
    args = _parse_args()
    return asyncio.run(_run(args.message))


if __name__ == "__main__":
    raise SystemExit(main())
