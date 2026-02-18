#!/usr/bin/env python3
"""
OpenCode Discord Bot — Entry point

Usage:
    python main.py                      # uses ./config.yaml
    python main.py --config /path.yaml
    python main.py --debug
"""

import argparse
import asyncio
import logging
import signal
import sys
from pathlib import Path

import yaml

from src.opencode_client import OpenCodeClient
from src.discord_bot import OpenCodeBot

log = logging.getLogger("opencode_discord_bot")


def load_config(path: Path) -> dict:
    with open(path) as f:
        return yaml.safe_load(f)


async def run(config: dict) -> None:
    dc = config.get("discord", {})
    oc = config.get("opencode", {})

    # Build OpenCode client
    client = OpenCodeClient(
        hostname=oc.get("hostname", "127.0.0.1"),
        port=oc.get("port", 4096),
        working_directory=oc.get("working_directory", "."),
        username=oc.get("username"),
        password=oc.get("password"),
    )

    # Build Discord bot
    bot = OpenCodeBot(
        opencode=client,
        allowed_channels=dc.get("allowed_channels"),
        command_prefix=dc.get("prefix", "!"),
    )

    # Graceful shutdown
    loop = asyncio.get_running_loop()
    shutdown_event = asyncio.Event()

    def _signal_handler() -> None:
        log.info("Shutdown signal received")
        shutdown_event.set()

    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, _signal_handler)

    try:
        # Start OpenCode server
        log.info("Starting OpenCode server …")
        await client.start_server()

        # Start Discord bot (runs until closed)
        log.info("Starting Discord bot …")
        bot_task = asyncio.create_task(bot.start(dc["token"]))
        shutdown_task = asyncio.create_task(shutdown_event.wait())

        # Wait for either the bot to crash or a shutdown signal
        done, _ = await asyncio.wait(
            [bot_task, shutdown_task],
            return_when=asyncio.FIRST_COMPLETED,
        )

        if bot_task in done:
            # Bot exited on its own — propagate any exception
            bot_task.result()

    except KeyboardInterrupt:
        pass
    finally:
        log.info("Shutting down …")
        await bot.cleanup_sessions()
        await bot.close()
        await client.stop_server()
        log.info("Goodbye.")


def main() -> None:
    parser = argparse.ArgumentParser(description="OpenCode Discord Bot")
    parser.add_argument(
        "--config",
        type=Path,
        default=Path("config.yaml"),
        help="Path to config.yaml (default: ./config.yaml)",
    )
    parser.add_argument(
        "--debug",
        action="store_true",
        help="Enable debug logging",
    )
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.debug else logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )

    if not args.config.exists():
        log.error("Config file not found: %s", args.config)
        log.error("Copy config.yaml.example to config.yaml and fill in your values.")
        sys.exit(1)

    config = load_config(args.config)

    if not config.get("discord", {}).get("token"):
        log.error("discord.token is required in config.yaml")
        sys.exit(1)

    asyncio.run(run(config))


if __name__ == "__main__":
    main()
