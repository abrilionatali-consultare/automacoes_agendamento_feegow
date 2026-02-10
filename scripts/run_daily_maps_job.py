from __future__ import annotations

import argparse
from datetime import date, datetime
import logging
import os
from pathlib import Path
import sys


ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

logging.getLogger("streamlit").setLevel(logging.ERROR)

from automation.daily_maps import (
    DEFAULT_OUTPUT_DIR,
    DailyMapResult,
    generate_daily_maps_for_units,
    get_configured_units_from_env,
    resolve_units,
)
from automation.drive_uploader import GoogleDriveUploader, is_drive_upload_configured
from automation.timezone_utils import DEFAULT_TIMEZONE, resolve_target_date


def main() -> int:
    args = parse_args()

    requested_units = parse_units_input(args.units)
    if not requested_units:
        requested_units = get_configured_units_from_env()

    explicit_date = parse_optional_date(args.date)
    resolved_date = resolve_target_date(
        args.when,
        timezone_name=args.timezone,
        explicit_date=explicit_date,
    )

    try:
        units = resolve_units(requested_units if requested_units else None)
    except Exception as exc:
        print(f"[ERROR] Unit resolution failed: {exc}")
        return 2

    print(
        "[INFO] Starting map generation "
        f"mode={resolved_date.mode} target_date={resolved_date.target_date:%d-%m-%Y} "
        f"timezone={resolved_date.timezone} units={len(units)}"
    )

    generation = generate_daily_maps_for_units(
        target_date=resolved_date.target_date,
        units=units,
        save_local=args.save_local,
        output_dir=args.output_dir,
    )

    if args.upload_drive:
        upload_results_to_drive(generation)

    summarize(generation)

    has_error = any(not r.success and not r.warning for r in generation)
    has_warning = any(r.warning for r in generation)

    if has_error:
        return 1
    if args.fail_on_warning and has_warning:
        return 3
    return 0


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Generate Feegow daily room maps and optionally upload to Google Drive."
    )
    parser.add_argument(
        "--when",
        choices=["today", "tomorrow", "date"],
        default="today",
        help="Date reference in the configured timezone.",
    )
    parser.add_argument(
        "--date",
        default="",
        help="Explicit target date in DD-MM-YYYY (required when --when=date).",
    )
    parser.add_argument(
        "--units",
        default="",
        help=(
            "Comma-separated unit names. "
            "If empty, uses MAP_AUTOMATION_UNITS; if also empty, uses all units from API."
        ),
    )
    parser.add_argument(
        "--timezone",
        default=os.getenv("MAP_AUTOMATION_TIMEZONE", DEFAULT_TIMEZONE),
        help="IANA timezone name used for date resolution.",
    )
    parser.add_argument(
        "--save-local",
        type=str_to_bool,
        default=str_to_bool(os.getenv("MAP_AUTOMATION_SAVE_LOCAL", "true")),
        help="Save generated PDFs in local filesystem.",
    )
    parser.add_argument(
        "--output-dir",
        default=os.getenv("MAP_AUTOMATION_OUTPUT_DIR", DEFAULT_OUTPUT_DIR),
        help="Output directory when --save-local=true.",
    )
    parser.add_argument(
        "--upload-drive",
        type=str_to_bool,
        default=str_to_bool(os.getenv("MAP_AUTOMATION_UPLOAD_DRIVE", "true")),
        help="Upload generated files to Google Drive.",
    )
    parser.add_argument(
        "--fail-on-warning",
        type=str_to_bool,
        default=str_to_bool(os.getenv("MAP_AUTOMATION_FAIL_ON_WARNING", "false")),
        help="Return non-zero exit code when warnings occur.",
    )
    return parser.parse_args()


def parse_optional_date(raw_date: str) -> date | None:
    value = (raw_date or "").strip()
    if not value:
        return None
    try:
        return datetime.strptime(value, "%d-%m-%Y").date()
    except ValueError as exc:
        raise ValueError("Invalid --date format. Use DD-MM-YYYY.") from exc


def parse_units_input(raw_units: str) -> list[str]:
    if not raw_units.strip():
        return []
    return [part.strip() for part in raw_units.split(",") if part.strip()]


def str_to_bool(value: str | bool) -> bool:
    if isinstance(value, bool):
        return value
    normalized = str(value).strip().lower()
    if normalized in {"1", "true", "yes", "y", "on"}:
        return True
    if normalized in {"0", "false", "no", "n", "off"}:
        return False
    raise argparse.ArgumentTypeError(f"Invalid boolean value: {value}")


def upload_results_to_drive(results: list[DailyMapResult]) -> None:
    if not is_drive_upload_configured("diario"):
        print(
            "[WARN] Google Drive upload skipped. "
            "Missing OAuth files (credentials/token) or root folder for daily maps."
        )
        return

    uploader = GoogleDriveUploader()
    for result in results:
        if not result.success or not result.pdf_bytes or not result.filename:
            continue
        try:
            uploaded = uploader.upload_map_pdf(
                map_type="diario",
                target_date=result.target_date,
                filename=result.filename,
                file_bytes=result.pdf_bytes,
            )
            result.drive_file_id = uploaded.file_id
            result.drive_web_view_link = uploaded.web_view_link
            print(
                f"[INFO] Uploaded unidade={result.unidade} file_id={uploaded.file_id}"
            )
        except Exception as exc:
            result.error = f"Drive upload failed: {exc}"
            result.success = False


def summarize(results: list[DailyMapResult]) -> None:
    success_count = sum(1 for r in results if r.success)
    warning_count = sum(1 for r in results if r.warning)
    error_count = sum(1 for r in results if not r.success and not r.warning)

    for result in results:
        if result.success:
            print(
                "[OK] "
                f"unidade={result.unidade} "
                f"file={result.filename} "
                f"local={result.local_path or '-'} "
                f"drive={result.drive_file_id or '-'}"
            )
            continue
        if result.warning:
            print(f"[WARN] unidade={result.unidade} message={result.warning}")
            continue
        print(f"[ERROR] unidade={result.unidade} message={result.error}")

    print(
        "[SUMMARY] "
        f"success={success_count} "
        f"warnings={warning_count} "
        f"errors={error_count} "
        f"total={len(results)}"
    )


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except ValueError as exc:
        print(f"[ERROR] {exc}")
        raise SystemExit(2) from exc
    except Exception as exc:  # pragma: no cover
        print(f"[FATAL] {exc}")
        raise SystemExit(1) from exc
