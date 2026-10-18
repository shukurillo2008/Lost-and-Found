"""Telegram bot service entrypoint (aiogram 3.x, long polling).

Wires the process to the shared Django ORM via ``django.setup()``, registers
the blocked-user middleware and all routers, then polls forever.
"""
import asyncio
import logging
import os
import sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent    # /app
sys.path.insert(0, str(BASE_DIR / "web"))
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")

import django

django.setup()

from django.conf import settings  # noqa: E402

from aiogram import Bot, Dispatcher  # noqa: E402
from aiogram.client.default import DefaultBotProperties  # noqa: E402
from aiogram.enums import ParseMode  # noqa: E402

from bot import browse, handlers, wizards  # noqa: E402
from bot.middleware import BlockedUserMiddleware  # noqa: E402

logger = logging.getLogger("bot")
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)

HEARTBEAT_SECONDS = 60


async def run_polling(bot: Bot, dispatcher: Dispatcher):
    await dispatcher.start_polling(
        bot,
        handle_signals=True,
    )


async def idle_forever():
    while True:
        logger.warning(
            "BOT_TOKEN is not set; the bot cannot reach Telegram. "
            "Set BOT_TOKEN in .env and restart the bot container."
        )
        logger.info("bot heartbeat: idle")
        await asyncio.sleep(HEARTBEAT_SECONDS)


def build_dispatcher() -> Dispatcher:
    dispatcher = Dispatcher()
    dispatcher.message.outer_middleware(BlockedUserMiddleware())
    dispatcher.callback_query.outer_middleware(BlockedUserMiddleware())
    dispatcher.include_router(handlers.router)
    dispatcher.include_router(wizards.router)
    dispatcher.include_router(browse.router)
    dispatcher.include_router(handlers.fallback_router)
    return dispatcher


async def bootstrap():
    if not settings.BOT_TOKEN:
        await idle_forever()
        return

    bot = Bot(
        token=settings.BOT_TOKEN,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )
    dispatcher = build_dispatcher()
    logger.info("Starting long polling for @%s...", (await bot.get_me()).username)
    await run_polling(bot, dispatcher)


def main():
    logger.info("Starting Campus Lost & Found bot service (aiogram 3.x).")
    try:
        asyncio.run(bootstrap())
    except (KeyboardInterrupt, SystemExit):
        logger.info("Bot service stopped.")


if __name__ == "__main__":
    main()
