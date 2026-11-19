"""CLI entrypoint for ANT Monitor."""

from __future__ import annotations

import argparse
import asyncio
import signal
import sys
from typing import Sequence

from ant_monitor.config import MonitorConfig
from ant_monitor.service import configure_logging, run_from_config


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    """Parse CLI flags for one-shot verification or continuous daemon mode."""
    parser = argparse.ArgumentParser(
        prog="ant-monitor",
        description="Real-time Binance ANTUSDT, Nasdaq ANT, and Anthropic IPO news monitor.",
    )
    parser.add_argument(
        "--env-file",
        default=None,
        help="Optional path to a .env configuration file.",
    )
    parser.add_argument(
        "--once",
        action="store_true",
        help="Fetch one snapshot, output/send the report, and exit.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print formatted Telegram messages to stdout instead of sending via Bot API.",
    )
    return parser.parse_args(argv)


async def _async_main(args: argparse.Namespace) -> int:
    config = MonitorConfig.from_env(dotenv_path=args.env_file)
    configure_logging(log_file=config.log_file, level=config.log_level)

    stop_event = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, stop_event.set)
        except NotImplementedError:
            pass

    await run_from_config(
        config=config,
        once=args.once,
        dry_run=args.dry_run,
        stop_event=stop_event,
    )
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    """Run the CLI entrypoint and exit with appropriate status code."""
    args = parse_args(argv)
    try:
        return asyncio.run(_async_main(args))
    except ValueError as exc:
        print(f"Configuration error: {exc}", file=sys.stderr)
        return 2
    except KeyboardInterrupt:
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
