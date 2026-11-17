"""Command-line orchestration: fetch -> parse -> validate -> save -> (optionally) Telegram."""

from __future__ import annotations

import argparse
import logging
import sys
from typing import Callable, Optional

from .config import ConfigError, Settings
from .fetcher import FetchedPage, FetchError, build_session, fetch_html
from .logging_setup import redact, setup_logging
from .models import MetalData
from .parsers import ParseError, parse_gold, parse_silver
from .report import ReportError, build_blocks, pack_messages, render_text
from .storage import build_payload, save_diagnostics, save_outputs
from .telegram_client import TelegramClient, TelegramError
from .timeutil import now_ist
from .validation import validate_pair

log = logging.getLogger("goldsilver")

EXIT_OK = 0
EXIT_UNEXPECTED = 1
EXIT_EXTRACTION = 2
EXIT_CONFIG = 3
EXIT_TELEGRAM = 4


def parse_args(argv: Optional[list[str]] = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(
        prog="python main.py",
        description="Fetch Chennai gold & silver rates and send a report to a Telegram group.")
    p.add_argument("--dry-run", action="store_true",
                   help="fetch, validate, save and print the report, but do NOT send to Telegram")
    p.add_argument("--no-telegram", action="store_true",
                   help="skip Telegram delivery; normal extraction and file output")
    p.add_argument("--output-dir", help="override OUTPUT_DIR")
    p.add_argument("--log-level", choices=["DEBUG", "INFO", "WARNING", "ERROR"],
                   help="override LOG_LEVEL")
    return p.parse_args(argv)


def _configure_stdio() -> None:
    """Windows consoles default to cp1252, which cannot print the rupee sign."""
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure:
            try:
                reconfigure(encoding="utf-8", errors="replace")
            except (OSError, ValueError):
                pass


def main(argv: Optional[list[str]] = None) -> int:
    _configure_stdio()
    args = parse_args(argv)
    try:
        settings = Settings.from_env(output_dir_override=args.output_dir)
    except ConfigError as exc:
        print(f"CONFIG ERROR: {exc}", file=sys.stderr)
        return EXIT_CONFIG

    setup_logging(settings.log_dir, args.log_level or settings.log_level, settings.secrets())
    deliver = not (args.dry_run or args.no_telegram)
    if deliver:
        problems = settings.telegram_problems()
        if problems:
            for problem in problems:
                log.error("Telegram configuration: %s", problem)
            print("CONFIG ERROR: Telegram is not configured correctly: " + "; ".join(problems)
                  + ". Set them in .env (see .env.example), or run with --dry-run / --no-telegram.",
                  file=sys.stderr)
            return EXIT_CONFIG
    try:
        return _run(settings, args, deliver)
    except KeyboardInterrupt:
        print("Interrupted.", file=sys.stderr)
        return 130
    except Exception as exc:  # last-resort handler; never leak the token
        log.exception("Unexpected error")
        print(f"FAILED: unexpected error: {redact(str(exc), settings.secrets())} "
              f"(see {settings.log_dir})", file=sys.stderr)
        return EXIT_UNEXPECTED


def _run(settings: Settings, args: argparse.Namespace, deliver: bool) -> int:
    now = now_ist()
    session = build_session(settings)

    sources: list[tuple[str, str, Callable[..., MetalData]]] = [
        ("gold", settings.gold_url, parse_gold),
        ("silver", settings.silver_url, parse_silver),
    ]
    pages: dict[str, Optional[FetchedPage]] = {}
    parsed: dict[str, MetalData] = {}
    errors: dict[str, str] = {}
    error_bodies: dict[str, bytes] = {}

    for name, url, parser in sources:
        pages[name] = None
        try:
            page = fetch_html(session, url, settings)
            pages[name] = page
            parsed[name] = parser(page.content, url, final_url=page.final_url,
                                  status=page.status_code, fetched_at_ist=page.fetched_at.isoformat())
        except FetchError as exc:
            errors[name] = str(exc)
            if exc.content:
                error_bodies[name] = exc.content
            log.error("%s: fetch failed: %s", name, exc)
        except ParseError as exc:
            errors[name] = str(exc)
            log.error("%s: parse failed: %s", name, exc)

    validation_errors: list[str] = []
    validation_warnings: list[str] = []
    if not errors:
        result = validate_pair(parsed["gold"], parsed["silver"], now, settings.max_data_age_days)
        validation_errors, validation_warnings = result.errors, result.warnings
        for w in validation_warnings:
            log.warning("Validation warning: %s", w)
        for e in validation_errors:
            log.error("Validation error: %s", e)

    if errors or validation_errors:
        folder = save_diagnostics(settings.output_dir, now, pages, parsed, errors,
                                  validation_errors, validation_warnings, error_bodies)
        reasons = [f"{k}: {v}" for k, v in errors.items()] + validation_errors
        print("FAILED: nothing was sent to Telegram. " + " | ".join(reasons)
              + f" | Diagnostics: {folder}", file=sys.stderr)
        return EXIT_EXTRACTION

    gold, silver = parsed["gold"], parsed["silver"]
    blocks = build_blocks(gold, silver, now)
    report_text = render_text(blocks)
    try:
        messages = pack_messages(blocks)
    except ReportError as exc:
        log.error("Could not split report: %s", exc)
        print(f"FAILED: {exc}", file=sys.stderr)
        return EXIT_UNEXPECTED

    payload = build_payload(gold, silver, now, validation_warnings, len(messages))
    json_path, txt_path = save_outputs(payload, report_text, settings.output_dir, now)

    if args.dry_run:
        print(report_text)
        print(f"DRY RUN OK: report saved to {txt_path} (JSON: {json_path}); "
              f"NOT sent to Telegram ({len(messages)} message(s) prepared).")
        return EXIT_OK
    if not deliver:
        print(f"OK: report saved to {txt_path} (JSON: {json_path}); Telegram delivery skipped (--no-telegram).")
        return EXIT_OK

    client = TelegramClient(
        token=settings.telegram_bot_token or "",
        chat_id=settings.telegram_chat_id or "",
        disable_notification=settings.telegram_disable_notification,
        timeout=settings.telegram_timeout,
        max_retries=settings.telegram_max_retries,
        backoff_seconds=settings.backoff_seconds,
    )
    try:
        sent = client.send_messages(messages)
    except TelegramError as exc:
        log.error("Telegram delivery failed after %d/%d message(s): %s", exc.delivered, exc.total, exc)
        print(f"PARTIAL: report saved to {txt_path}, but Telegram delivery FAILED "
              f"({exc.delivered}/{exc.total} message(s) sent): {exc}", file=sys.stderr)
        return EXIT_TELEGRAM
    print(f"OK: report saved to {txt_path} (JSON: {json_path}) and delivered to Telegram ({sent} message(s)).")
    return EXIT_OK
