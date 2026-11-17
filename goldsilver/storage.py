"""Writing report/JSON/diagnostic files."""

from __future__ import annotations

import json
import logging
from dataclasses import asdict
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

from . import __version__
from .fetcher import FetchedPage
from .models import MetalData

log = logging.getLogger(__name__)


def _atomic_write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(text, encoding="utf-8", newline="\n")
    tmp.replace(path)


def _atomic_write_bytes(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_bytes(data)
    tmp.replace(path)


def build_payload(gold: MetalData, silver: MetalData, now: datetime,
                  warnings: list[str], message_count: int) -> dict[str, Any]:
    return {
        "meta": {
            "generated_at_ist": now.isoformat(),
            "tool_version": __version__,
            "report_message_count": message_count,
            "validation_warnings": warnings,
        },
        "gold": asdict(gold),
        "silver": asdict(silver),
    }


def save_outputs(payload: dict[str, Any], report_text: str, output_dir: Path,
                 now: datetime) -> tuple[Path, Path]:
    stamp = now.strftime("%Y%m%d_%H%M%S")
    json_text = json.dumps(payload, ensure_ascii=False, indent=2) + "\n"
    json_path = output_dir / f"gold_silver_{stamp}.json"
    txt_path = output_dir / f"gold_silver_{stamp}.txt"
    _atomic_write_text(json_path, json_text)
    _atomic_write_text(txt_path, report_text)
    # Stable names for "the latest run".
    _atomic_write_text(output_dir / "gold_silver_latest.json", json_text)
    _atomic_write_text(output_dir / "gold_silver_latest.txt", report_text)
    log.info("Saved %s and %s", json_path, txt_path)
    return json_path, txt_path


def save_diagnostics(output_dir: Path, now: datetime, pages: dict[str, Optional[FetchedPage]],
                     parsed: dict[str, MetalData], errors: dict[str, str],
                     validation_errors: list[str], validation_warnings: list[str],
                     raw_error_bodies: Optional[dict[str, bytes]] = None) -> Path:
    folder = output_dir / "diagnostics" / now.strftime("%Y%m%d_%H%M%S")
    folder.mkdir(parents=True, exist_ok=True)
    summary: dict[str, Any] = {
        "generated_at_ist": now.isoformat(),
        "tool_version": __version__,
        "errors": errors,
        "validation_errors": validation_errors,
        "validation_warnings": validation_warnings,
        "pages": {},
        "parsed": {k: asdict(v) for k, v in parsed.items()},
    }
    for name, page in pages.items():
        if page is None:
            summary["pages"][name] = None
            continue
        summary["pages"][name] = {
            "url": page.url, "final_url": page.final_url, "http_status": page.status_code,
            "bytes": len(page.content), "elapsed_seconds": round(page.elapsed_seconds, 3),
            "fetched_at_ist": page.fetched_at.isoformat(),
        }
        _atomic_write_bytes(folder / f"{name}.html", page.content)
    for name, body in (raw_error_bodies or {}).items():
        if body:
            _atomic_write_bytes(folder / f"{name}_error_body.html", body[:2_000_000])
    _atomic_write_text(folder / "diagnostics.json", json.dumps(summary, ensure_ascii=False, indent=2) + "\n")
    log.info("Diagnostics saved to %s", folder)
    return folder
