"""Background worker service entrypoint.

Milestone 1 scaffolding: wires the process to the shared Django ORM
(``django.setup()``) and keeps the container alive. The matching runs,
retention alerts, report expiry tasks and the 09:00 office digest arrive
in Milestone 7.
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

logger = logging.getLogger("worker")
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)

HEARTBEAT_SECONDS = 30


async def run():
    logger.info("Worker service scaffolding is running; heartbeat every %ss.", HEARTBEAT_SECONDS)
    while True:
        logger.info("worker heartbeat: alive")
        await asyncio.sleep(HEARTBEAT_SECONDS)


def main():
    logger.info("Starting Campus Lost & Found worker service (scheduler from Milestone 7).")
    asyncio.run(run())


if __name__ == "__main__":
    main()
