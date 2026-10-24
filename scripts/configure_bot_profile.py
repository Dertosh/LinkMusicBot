"""Run: python -m scripts.configure_bot_profile (uses configured bot credentials)."""
import asyncio
import logging
from telegram import Bot
from linkmusicbot.settings import secrets
from linkmusicbot.about import DESCRIPTIONS, SHORT_DESCRIPTIONS


async def main():
    """Publish configured bot descriptions for the default, English, and Russian locales."""
    async with Bot(secrets["telegram_token"]) as bot:
        for language in ("", "en", "ru"):
            key = language or "en"
            await bot.set_my_description(DESCRIPTIONS[key], language_code=language)
            await bot.set_my_short_description(SHORT_DESCRIPTIONS[key], language_code=language)
        print("Bot descriptions updated: default, English, Russian")


if __name__ == "__main__":
    logging.disable(logging.CRITICAL)
    asyncio.run(main())
