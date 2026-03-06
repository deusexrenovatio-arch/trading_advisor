from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

import pandas as pd

from moex_carry.config import AppSettings
from moex_carry.data.moex_iss import MoexIssClient
from moex_carry.news_shock_symbol_map import GLOBAL_CONTEXT_KEYWORDS, SYMBOL_TOPIC_KEYWORDS


def iso_utc(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def parse_date(value: object) -> datetime.date | None:
    raw = str(value or "").strip()
    if not raw:
        return None
    try:
        return datetime.fromisoformat(raw).date()
    except ValueError:
        try:
            return datetime.strptime(raw, "%Y-%m-%d").date()
        except ValueError:
            return None


def normalize_text(value: object) -> str:
    return " ".join(str(value or "").strip().split())


def topic_relevance(symbol: str, text: str, *, candidate_commodity: str = "") -> float:
    lowered = normalize_text(text).lower()
    if not lowered:
        return 0.0
    topic_hits = 0
    for token in SYMBOL_TOPIC_KEYWORDS.get(symbol, ()):
        if token in lowered:
            topic_hits += 1
    global_hits = 0
    for token in GLOBAL_CONTEXT_KEYWORDS:
        if token in lowered:
            global_hits += 1
    score = float(topic_hits)
    if topic_hits > 0:
        score += min(global_hits, 3) * 0.25
    if normalize_text(candidate_commodity).upper() == symbol.upper():
        score += 0.35 if topic_hits > 0 else 0.05
    return score


def to_bool(value: object) -> bool:
    if isinstance(value, bool):
        return value
    num = pd.to_numeric(value, errors="coerce")
    if pd.notna(num):
        return int(num) != 0
    return str(value or "").strip().lower() in {"1", "true", "yes", "y", "on"}


def root_candidate_score(row: pd.Series, cfg: Any) -> float:
    fundamental = float(pd.to_numeric(row.get("fundamental_score"), errors="coerce") or 0.0)
    cause_conf = float(pd.to_numeric(row.get("cause_confidence"), errors="coerce") or 0.0)
    impact = float(pd.to_numeric(row.get("impact_score"), errors="coerce") or 0.0)
    confidence = float(pd.to_numeric(row.get("confidence"), errors="coerce") or 0.0)
    relevance = float(pd.to_numeric(row.get("relevance"), errors="coerce") or 0.0)
    link_score = float(pd.to_numeric(row.get("commodity_link_score"), errors="coerce") or 0.0)
    delay = float(pd.to_numeric(row.get("delay_min"), errors="coerce") or 9999.0)
    is_primary = to_bool(row.get("is_primary_cause"))
    claim_status = normalize_text(row.get("cause_claim_status")).lower()
    classification = normalize_text(row.get("cause_classification")).lower()
    score = (
        (2.0 if is_primary else 0.0)
        + (1.4 * fundamental)
        + (1.1 * cause_conf)
        + (0.8 * impact)
        + (0.65 * confidence)
        + (0.9 * link_score)
        + (0.45 * relevance)
        - min(delay / max(float(cfg.max_delay_minutes), 1.0), 2.5) * 0.2
    )
    if classification == "cause":
        score += 0.18
    elif classification == "mixed":
        score += 0.08
    if claim_status == "confirmed":
        score += 0.08
    elif claim_status == "rumor":
        score -= 0.55
    if to_bool(row.get("is_same_commodity")):
        score += 0.1
    return float(score)


def load_front_contract_prices(
    *,
    settings: AppSettings,
    client: MoexIssClient,
    asset_code: str,
    start_utc: datetime,
    end_utc: datetime,
    cfg: Any,
) -> pd.DataFrame:
    specs = client.get_futures_specs(settings.moex.futures_board)
    rows: list[dict[str, Any]] = []
    for item in specs:
        if str(item.get("ASSETCODE") or "").strip().upper() != asset_code.upper():
            continue
        expiry = parse_date(item.get("LASTTRADEDATE"))
        secid = str(item.get("SECID") or "").strip().upper()
        if not secid or expiry is None:
            continue
        rows.append({"secid": secid, "expiry": expiry})
    if not rows:
        return pd.DataFrame(columns=["ts", "price", "secid"])

    start_date = (start_utc - timedelta(days=max(int(cfg.history_padding_days), 0))).date()
    end_date = end_utc.date()
    contracts = pd.DataFrame(rows).drop_duplicates(subset=["secid"]).sort_values("expiry")
    eligible = contracts[contracts["expiry"] >= (start_date - timedelta(days=max(int(cfg.history_padding_days), 0)))]
    if eligible.empty:
        eligible = contracts.tail(1)
    eligible = eligible.head(max(int(cfg.front_contract_candidates), 1))

    frames: list[pd.DataFrame] = []
    for _, row in eligible.iterrows():
        secid = str(row["secid"])
        expiry = row["expiry"]
        raw = client.get_candles(
            settings.moex.engine_futures,
            settings.moex.market_futures,
            secid,
            settings.moex.futures_board,
            from_date=start_date,
            till_date=end_date,
            interval=1,
        )
        if not raw:
            continue
        frame = pd.DataFrame(raw)
        if frame.empty:
            continue
        frame["ts"] = pd.to_datetime(frame.get("begin"), utc=True, errors="coerce")
        frame["price"] = pd.to_numeric(frame.get("close"), errors="coerce")
        frame = frame.dropna(subset=["ts", "price"])
        if frame.empty:
            continue
        frame["expiry"] = pd.to_datetime(str(expiry), utc=True).date()
        frame["secid"] = secid
        frame["days_to_expiry"] = (
            pd.to_datetime(frame["expiry"]).dt.date - frame["ts"].dt.date
        ).apply(lambda value: value.days)
        frame["_expiry_penalty"] = frame["days_to_expiry"].map(lambda days: 0 if days >= 0 else 1)
        frame["_distance"] = frame["days_to_expiry"].abs()
        frames.append(frame[["ts", "price", "secid", "_expiry_penalty", "_distance"]])

    if not frames:
        return pd.DataFrame(columns=["ts", "price", "secid"])

    merged = pd.concat(frames, ignore_index=True)
    merged = merged.sort_values(["ts", "_expiry_penalty", "_distance"])
    merged = merged.drop_duplicates(subset=["ts"], keep="first")
    merged = merged[
        (merged["ts"] >= start_utc - timedelta(days=max(int(cfg.history_padding_days), 0)))
        & (merged["ts"] <= end_utc)
    ]
    return merged[["ts", "price", "secid"]].sort_values("ts").reset_index(drop=True)
