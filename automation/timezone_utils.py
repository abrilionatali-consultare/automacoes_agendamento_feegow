from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo


DEFAULT_TIMEZONE = "America/Sao_Paulo"


@dataclass(frozen=True)
class TargetDateResolution:
    mode: str
    timezone: str
    now_local: datetime
    target_date: date


def now_in_timezone(timezone_name: str = DEFAULT_TIMEZONE) -> datetime:
    return datetime.now(ZoneInfo(timezone_name))


def resolve_target_date(
    mode: str,
    *,
    timezone_name: str = DEFAULT_TIMEZONE,
    explicit_date: date | None = None,
) -> TargetDateResolution:
    normalized_mode = (mode or "").strip().lower()
    now_local = now_in_timezone(timezone_name)

    if normalized_mode == "today":
        target = now_local.date()
    elif normalized_mode == "tomorrow":
        target = now_local.date() + timedelta(days=1)
    elif normalized_mode == "date":
        if explicit_date is None:
            raise ValueError("explicit_date is required when mode='date'.")
        target = explicit_date
    else:
        raise ValueError("mode must be one of: today, tomorrow, date")

    return TargetDateResolution(
        mode=normalized_mode,
        timezone=timezone_name,
        now_local=now_local,
        target_date=target,
    )


def format_date_br(target_date: date) -> str:
    return target_date.strftime("%d-%m-%Y")

