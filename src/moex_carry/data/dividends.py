from __future__ import annotations

from dataclasses import replace
from datetime import date, datetime
from pathlib import Path
from typing import Iterable, Optional

import pandas as pd

from moex_carry.domain.models import DividendEvent


def _parse_date(value: Optional[str]) -> Optional[date]:
    if not value:
        return None
    return datetime.fromisoformat(value).date()


def normalize_dividends(raw: Iterable[dict]) -> list[DividendEvent]:
    events: list[DividendEvent] = []
    for row in raw:
        ex_date = _parse_date(row.get("exdate") or row.get("EXDATE"))
        if not ex_date:
            continue
        amount = row.get("value") or row.get("AMOUNT") or 0.0
        currency = row.get("currencyid") or row.get("CURRENCYID") or "RUB"
        status = row.get("status") or row.get("STATUS") or "historical"
        secid = row.get("secid") or row.get("SECID") or ""
        events.append(
            DividendEvent(
                secid=secid,
                ex_date=ex_date,
                amount=float(amount),
                currency=currency,
                status=status,
            )
        )
    return events


def load_dividends(client, secid: str) -> list[DividendEvent]:
    raw = client.get_dividends(secid)
    events = normalize_dividends(raw)
    return events


def apply_overrides(
    events: list[DividendEvent], overrides_path: Optional[Path]
) -> list[DividendEvent]:
    if not overrides_path or not overrides_path.exists():
        return events
    overrides = pd.read_csv(overrides_path)
    if overrides.empty:
        return events

    override_map = {
        (row["secid"], row["ex_date"]): row for _, row in overrides.iterrows()
    }
    updated: list[DividendEvent] = []
    for event in events:
        key = (event.secid, event.ex_date.isoformat())
        if key in override_map:
            row = override_map[key]
            updated.append(
                replace(
                    event,
                    amount=float(row.get("amount", event.amount)),
                    currency=row.get("currency", event.currency),
                    status=row.get("status", event.status),
                )
            )
        else:
            updated.append(event)
    return updated
