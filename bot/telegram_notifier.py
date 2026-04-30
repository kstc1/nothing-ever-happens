import logging
import aiohttp
import os

logger = logging.getLogger(__name__)

async def send_telegram_message(message: str) -> None:
    bot_token = os.getenv("TELEGRAM_BOT_TOKEN")
    chat_id = os.getenv("TELEGRAM_CHAT_ID")
    
    if not bot_token or not chat_id:
        return
        
    url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
    payload = {
        "chat_id": chat_id,
        "text": message,
        "parse_mode": "HTML"
    }
    
    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(url, json=payload, timeout=10.0) as resp:
                if resp.status != 200:
                    text = await resp.text()
                    logger.warning("Failed to send telegram message: status=%s text=%s", resp.status, text)
    except Exception as e:
        logger.warning("Error sending telegram message: %s", e)
