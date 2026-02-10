from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from pathlib import Path
import os
import re
from typing import Iterable

import pandas as pd

from automation.timezone_utils import format_date_br


DEFAULT_OUTPUT_DIR = "mapas_gerados/automacao"
DEFAULT_UNITS_ENV = "MAP_AUTOMATION_UNITS"


@dataclass
class DailyMapResult:
    unidade: str
    target_date: date
    success: bool
    filename: str | None = None
    pdf_bytes: bytes | None = None
    local_path: str | None = None
    warning: str | None = None
    error: str | None = None
    drive_file_id: str | None = None
    drive_web_view_link: str | None = None


def get_available_units() -> list[str]:
    from core.api_client import list_unidades

    df_units = list_unidades()
    if df_units.empty or "nome_fantasia" not in df_units.columns:
        return []
    values = (
        df_units["nome_fantasia"]
        .dropna()
        .astype(str)
        .str.strip()
        .replace("", pd.NA)
        .dropna()
        .unique()
        .tolist()
    )
    return sorted(values)


def get_configured_units_from_env(env_var: str = DEFAULT_UNITS_ENV) -> list[str]:
    raw = os.getenv(env_var, "")
    if not raw.strip():
        return []
    return [part.strip() for part in raw.split(",") if part.strip()]


def resolve_units(requested_units: Iterable[str] | None = None) -> list[str]:
    available_units = get_available_units()
    if not available_units:
        raise RuntimeError("No units found from Feegow API.")

    if requested_units is None:
        requested = []
    else:
        requested = [str(x).strip() for x in requested_units if str(x).strip()]

    if not requested:
        return available_units

    normalized_available = {_norm_unit_name(x): x for x in available_units}
    resolved: list[str] = []
    missing: list[str] = []

    for unit in requested:
        key = _norm_unit_name(unit)
        if key not in normalized_available:
            missing.append(unit)
            continue
        canonical = normalized_available[key]
        if canonical not in resolved:
            resolved.append(canonical)

    if missing:
        raise ValueError(
            "Units not available in API response: "
            + ", ".join(missing)
        )

    return resolved


def build_daily_filename(unidade: str, target_date: date) -> str:
    unit_safe = _sanitize_filename(unidade)
    return f"MAPA_DIARIO_{unit_safe}_{target_date.strftime('%d-%m-%Y')}.pdf"


def generate_daily_maps_for_units(
    *,
    target_date: date,
    units: Iterable[str],
    save_local: bool = True,
    output_dir: str = DEFAULT_OUTPUT_DIR,
) -> list[DailyMapResult]:
    from core.map_generator import generate_daily_maps

    selected_units = list(units)
    target_date_str = format_date_br(target_date)
    output_path = Path(output_dir)

    if save_local:
        output_path.mkdir(parents=True, exist_ok=True)

    results: list[DailyMapResult] = []
    for unit in selected_units:
        try:
            payload = generate_daily_maps(start_date=target_date_str, unidade_id=unit)
            parsed = _extract_pdf_from_payload(payload, expected_unit=unit)
            if parsed["warning"]:
                results.append(
                    DailyMapResult(
                        unidade=unit,
                        target_date=target_date,
                        success=False,
                        warning=parsed["warning"],
                    )
                )
                continue

            pdf_bytes = parsed["pdf_bytes"]
            if pdf_bytes is None:
                results.append(
                    DailyMapResult(
                        unidade=unit,
                        target_date=target_date,
                        success=False,
                        warning="PDF payload is empty.",
                    )
                )
                continue

            filename = build_daily_filename(unit, target_date)
            local_path = None

            if save_local:
                file_path = output_path / filename
                file_path.write_bytes(pdf_bytes)
                local_path = str(file_path)

            results.append(
                DailyMapResult(
                    unidade=unit,
                    target_date=target_date,
                    success=True,
                    filename=filename,
                    pdf_bytes=pdf_bytes,
                    local_path=local_path,
                )
            )
        except Exception as exc:
            results.append(
                DailyMapResult(
                    unidade=unit,
                    target_date=target_date,
                    success=False,
                    error=str(exc),
                )
            )

    return results


def _extract_pdf_from_payload(payload: object, *, expected_unit: str) -> dict:
    if not isinstance(payload, dict) or not payload:
        return {"warning": "No data returned.", "pdf_bytes": None}

    if "warning" in payload:
        return {"warning": str(payload["warning"]), "pdf_bytes": None}

    if expected_unit in payload and isinstance(payload[expected_unit], (bytes, bytearray)):
        return {"warning": None, "pdf_bytes": bytes(payload[expected_unit])}

    for _, value in payload.items():
        if isinstance(value, (bytes, bytearray)):
            return {"warning": None, "pdf_bytes": bytes(value)}

    return {"warning": "No PDF bytes found in response.", "pdf_bytes": None}


def _sanitize_filename(text: str) -> str:
    sanitized = re.sub(r"[^A-Za-z0-9._-]+", "_", str(text).strip())
    sanitized = sanitized.strip("_")
    return sanitized or "UNIDADE"


def _norm_unit_name(text: str) -> str:
    return " ".join(str(text).strip().split()).casefold()
