"""Telegram bot service entrypoint.

Milestone 1 scaffolding: wires the process to the shared Django ORM
(``django.setup()``), validates configuration and keeps the container alive.
Bot handlers, FSM wizards, i18n strings and middleware arrive in Milestone 3.
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

logger = logging.getLogger("bot")
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)

HEARTBEAT_SECONDS = 60


async def run():
    if not settings.BOT_TOKEN:
        logger.warning(
            "BOT_TOKEN is not set. The bot service cannot poll Telegram. "
            "Set BOT_TOKEN in .env and restart the container."
        )
    else:
        logger.info("BOT_TOKEN loaded (value hidden). Long-polling starts in Milestone 3.")

    logger.info("Bot service scaffolding is running; heartbeat every %ss.", HEARTBEAT_SECONDS)
    while True:
        logger.info("bot heartbeat: alive")
        await asyncio.sleep(HEARTBEAT_SECONDS)


def main():
    logger.info("Starting Campus Lost & Found bot service (aiogram 3.x from Milestone 3).")
    asyncio.run(run())


if __name__ == "__main__":
    main()
