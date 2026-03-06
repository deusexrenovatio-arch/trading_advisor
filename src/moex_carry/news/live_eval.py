from __future__ import annotations

import bisect
import math
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

from moex_carry.data.moex_iss import MoexIssClient
from moex_carry.storage.repositories import (
    load_event_target_v2,
    load_news_entity_links,
    load_news_event_items,
    load_news_events,
    load_news_impact_scores,
    load_news_items_by_ids,
)

MSK_TZ = ZoneInfo("Europe/Moscow")


@dataclass(frozen=True)
class _MoexContract:
    secid: str
    asset_code: str
    expiry: date


def _to_iso_z(value: datetime) -> str:
    normalized = value.astimezone(timezone.utc)
    return normalized.isoformat().replace("+00:00", "Z")


def _parse_iso_utc_dt(value: object) -> datetime | None:
    if value is None:
        return None
    raw = str(value).strip()
    if not raw:
        return None
    try:
        parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _format_local_human(value: object, tzinfo: ZoneInfo) -> str | None:
    parsed = _parse_iso_utc_dt(value)
    if parsed is None:
        return None
    return parsed.astimezone(tzinfo).strftime("%d.%m.%Y %H:%M %Z")


def _as_float(value: object, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _horizon_to_delta(horizon: str) -> timedelta:
    key = str(horizon or "1h").strip().lower()
    mapping = {
        "5m": timedelta(minutes=5),
        "15m": timedelta(minutes=15),
        "30m": timedelta(minutes=30),
        "1h": timedelta(hours=1),
        "4h": timedelta(hours=4),
        "1d": timedelta(days=1),
    }
    if key in mapping:
        return mapping[key]
    if key.endswith("m"):
        try:
            return timedelta(minutes=max(int(key[:-1]), 1))
        except ValueError:
            return timedelta(hours=1)
    if key.endswith("h"):
        try:
            return timedelta(hours=max(int(key[:-1]), 1))
        except ValueError:
            return timedelta(hours=1)
    if key.endswith("d"):
        try:
            return timedelta(days=max(int(key[:-1]), 1))
        except ValueError:
            return timedelta(hours=1)
    return timedelta(hours=1)


def _ticker_asset_codes(ticker: str) -> tuple[str, ...]:
    mapping = {
        "BRN": ("BR",),
        "GOLD": ("GOLD", "GD", "GL"),
        "NG_US": ("NG",),
        "SILVER": ("SILV", "SV"),
        "PLATINUM": ("PLT",),
        "PALLADIUM": ("PLD",),
        "COPPER": ("COPPER",),
        "ALUMINUM": ("ALUM",),
        "NICKEL": ("NICKEL",),
        "ZINC": ("ZINC",),
        "WHEAT": ("WHEAT", "WUSH"),
        "SUGAR": ("SUGAR", "SUGR"),
        "COFFEE": ("COFFEE",),
        "COCOA": ("COCOA",),
        "ORANGE": ("ORANGE",),
    }
    return mapping.get(str(ticker or "").strip().upper(), ())


def _parse_contracts(rows: list[dict[str, object]]) -> list[_MoexContract]:
    contracts: list[_MoexContract] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        secid = str(row.get("SECID") or row.get("secid") or "").strip().upper()
        asset_code = str(row.get("ASSETCODE") or row.get("assetcode") or "").strip().upper()
        expiry_raw = row.get("LASTTRADEDATE") or row.get("LASTTRADINGDAY") or row.get("lasttradedate")
        if not secid or not asset_code or not expiry_raw:
            continue
        try:
            expiry = datetime.fromisoformat(str(expiry_raw)[:10]).date()
        except ValueError:
            continue
        contracts.append(_MoexContract(secid=secid, asset_code=asset_code, expiry=expiry))
    contracts.sort(key=lambda item: (item.asset_code, item.expiry, item.secid))
    return contracts


def _select_contract(
    *,
    contracts: list[_MoexContract],
    ticker: str,
    event_ts_utc: datetime,
    roll_days: int,
) -> _MoexContract | None:
    asset_codes = _ticker_asset_codes(ticker)
    if not asset_codes:
        return None
    event_local_date = event_ts_utc.astimezone(MSK_TZ).date()
    min_expiry = event_local_date + timedelta(days=max(int(roll_days), 0))
    for asset_code in asset_codes:
        same_asset = [item for item in contracts if item.asset_code == asset_code]
        if not same_asset:
            continue
        eligible = [item for item in same_asset if item.expiry > min_expiry]
        if eligible:
            return min(eligible, key=lambda item: (item.expiry, item.secid))
        future_only = [item for item in same_asset if item.expiry >= event_local_date]
        if future_only:
            return min(future_only, key=lambda item: (item.expiry, item.secid))
        return max(same_asset, key=lambda item: (item.expiry, item.secid))
    return None


def _parse_moex_ts_utc(value: object) -> datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        parsed = datetime.fromisoformat(text.replace(" ", "T"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=MSK_TZ)
    return parsed.astimezone(timezone.utc)


def _build_contract_series(
    *,
    client: MoexIssClient,
    secid: str,
    board: str,
    from_date_local: date,
    to_date_local: date,
) -> tuple[list[datetime], list[float]]:
    rows = client.get_candles(
        "futures",
        "forts",
        secid,
        board,
        from_date_local,
        to_date_local,
        interval=1,
    )
    ts_list: list[datetime] = []
    px_list: list[float] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        ts = _parse_moex_ts_utc(row.get("begin"))
        close_price = _as_float(row.get("close"), default=0.0)
        if ts is None or close_price <= 0.0:
            continue
        if ts_list and ts <= ts_list[-1]:
            continue
        ts_list.append(ts)
        px_list.append(close_price)
    return ts_list, px_list


def _evaluate_on_series(
    *,
    event_ts_utc: datetime,
    horizon_delta: timedelta,
    ts_list: list[datetime],
    px_list: list[float],
) -> dict[str, object] | None:
    if not ts_list or not px_list or len(ts_list) != len(px_list):
        return None
    idx0 = bisect.bisect_left(ts_list, event_ts_utc) - 1
    if idx0 < 0 or idx0 >= len(ts_list):
        return None
    t0 = ts_list[idx0]
    p0 = px_list[idx0]
    if p0 <= 0.0:
        return None
    idx1 = bisect.bisect_left(ts_list, t0 + horizon_delta)
    if idx1 < 0 or idx1 >= len(ts_list):
        return None
    t1 = ts_list[idx1]
    p1 = px_list[idx1]
    if p1 <= 0.0 or t1 <= t0:
        return None
    return {
        "t0": _to_iso_z(t0),
        "t1": _to_iso_z(t1),
        "r_raw": float(math.log(p1 / p0)),
        "p0": float(p0),
        "p1": float(p1),
    }


def _map_pred_direction(value: object) -> int:
    lowered = str(value or "").strip().lower()
    if lowered in {"up", "positive", "bull", "bullish"}:
        return 1
    if lowered in {"down", "negative", "bear", "bearish"}:
        return -1
    return 0


def _map_label_direction(value: object) -> int:
    try:
        number = int(value)
    except (TypeError, ValueError):
        return 0
    if number > 0:
        return 1
    if number < 0:
        return -1
    return 0


def _select_primary_model_score(
    model_scores: list[dict[str, object]],
    preferred_models: list[str],
) -> dict[str, object] | None:
    for model_name in preferred_models:
        selected = next(
            (
                score
                for score in model_scores
                if isinstance(score, dict) and str(score.get("model_id") or "").strip() == model_name
            ),
            None,
        )
        if selected is not None:
            return selected
    return next((score for score in model_scores if isinstance(score, dict)), None)


def _derive_event_model_scores_from_news(
    *,
    event_id: str,
    news_rows: list[dict[str, object]],
) -> list[dict[str, object]]:
    grouped: dict[str, dict[str, object]] = {}
    for row in news_rows:
        if not isinstance(row, dict):
            continue
        model_id = str(row.get("model_id") or "").strip()
        if not model_id:
            continue
        bucket = grouped.setdefault(
            model_id,
            {
                "count": 0,
                "sum_up": 0.0,
                "sum_down": 0.0,
                "sum_neutral": 0.0,
                "sum_impact": 0.0,
                "latest_ts": None,
                "latest_version": None,
                "calibrated": False,
            },
        )
        bucket["count"] = int(bucket.get("count") or 0) + 1
        bucket["sum_up"] = _as_float(bucket.get("sum_up")) + _as_float(row.get("prob_up"))
        bucket["sum_down"] = _as_float(bucket.get("sum_down")) + _as_float(row.get("prob_down"))
        bucket["sum_neutral"] = _as_float(bucket.get("sum_neutral")) + _as_float(row.get("prob_neutral"))
        bucket["sum_impact"] = _as_float(bucket.get("sum_impact")) + _as_float(row.get("impact_score"))
        bucket["calibrated"] = bool(bucket.get("calibrated")) or bool(row.get("calibrated"))
        ts_value = _parse_iso_utc_dt(row.get("inference_ts"))
        latest_ts = bucket.get("latest_ts")
        if ts_value is not None and (latest_ts is None or ts_value > latest_ts):
            bucket["latest_ts"] = ts_value
            bucket["latest_version"] = row.get("model_version")

    derived: list[dict[str, object]] = []
    for model_id, bucket in grouped.items():
        count = max(int(bucket.get("count") or 0), 1)
        prob_up = _as_float(bucket.get("sum_up")) / count
        prob_down = _as_float(bucket.get("sum_down")) / count
        prob_neutral = _as_float(bucket.get("sum_neutral")) / count
        total_prob = prob_up + prob_down + prob_neutral
        if total_prob > 0.0:
            prob_up = prob_up / total_prob
            prob_down = prob_down / total_prob
            prob_neutral = prob_neutral / total_prob
        impact_score = _as_float(bucket.get("sum_impact")) / count
        direction = "neutral"
        if prob_up >= prob_down and prob_up >= prob_neutral:
            direction = "up"
        elif prob_down >= prob_up and prob_down >= prob_neutral:
            direction = "down"
        latest_ts = bucket.get("latest_ts")
        derived.append(
            {
                "news_id": None,
                "target_level": "event",
                "target_id": event_id,
                "model_id": model_id,
                "model_version": bucket.get("latest_version"),
                "direction": direction,
                "prob_up": prob_up,
                "prob_down": prob_down,
                "prob_neutral": prob_neutral,
                "impact_score": impact_score,
                "calibrated": bool(bucket.get("calibrated")),
                "inference_ts": _to_iso_z(latest_ts) if isinstance(latest_ts, datetime) else None,
                "derived_from": "news_items",
            }
        )
    derived.sort(key=lambda row: _as_float(row.get("impact_score")), reverse=True)
    return derived


def build_news_live_eval_rows(
    session,
    *,
    from_date: date,
    to_date: date,
    tickers: list[str],
    horizon: str,
    timezone_name: str,
    limit: int,
    preferred_models: list[str],
    gap_lag_minutes: int = 180,
    moex_client: MoexIssClient | None = None,
    moex_futures_board: str = "RFUD",
    moex_roll_days: int = 1,
) -> tuple[list[dict[str, object]], dict[str, dict[str, object]]]:
    from_dt = datetime.combine(from_date, time.min, tzinfo=timezone.utc)
    to_dt = datetime.combine(to_date, time.min, tzinfo=timezone.utc)
    normalized_tickers = [str(item).strip().upper() for item in tickers if str(item).strip()]
    local_tz = ZoneInfo(timezone_name or "Europe/Moscow")

    event_rows = load_news_events(
        session,
        event_status=None,
        published_from=_to_iso_z(from_dt),
        published_to=_to_iso_z(to_dt),
        limit=max(int(limit), 1) * max(len(normalized_tickers), 1) * 5,
    )
    event_ids = [str(row.get("event_id") or "").strip() for row in event_rows if isinstance(row, dict)]
    event_ids = [event_id for event_id in event_ids if event_id]
    if not event_ids:
        return [], {ticker: {"events_with_predictions": 0} for ticker in normalized_tickers}

    event_item_rows = load_news_event_items(
        session,
        event_ids=event_ids,
        limit=max(len(event_ids) * 30, 1000),
    )
    event_to_news_ids: dict[str, list[str]] = {}
    for row in event_item_rows:
        if not isinstance(row, dict):
            continue
        event_id = str(row.get("event_id") or "").strip()
        news_id = str(row.get("news_id") or "").strip()
        if not event_id or not news_id:
            continue
        event_to_news_ids.setdefault(event_id, []).append(news_id)

    all_news_ids = sorted(
        {
            news_id
            for news_ids in event_to_news_ids.values()
            for news_id in news_ids
            if isinstance(news_id, str) and news_id
        }
    )
    news_by_id: dict[str, dict[str, object]] = {}
    for row in load_news_items_by_ids(session, all_news_ids):
        if not isinstance(row, dict):
            continue
        news_id = str(row.get("news_id") or "").strip()
        if news_id:
            news_by_id[news_id] = row

    entity_links = load_news_entity_links(session, news_ids=all_news_ids, limit=max(len(all_news_ids) * 10, 1000))
    entity_tickers_by_news: dict[str, set[str]] = {}
    for row in entity_links:
        if not isinstance(row, dict):
            continue
        news_id = str(row.get("news_id") or "").strip()
        if not news_id:
            continue
        ticker = str(row.get("ticker") or row.get("entity_id") or "").strip().upper()
        if ticker:
            entity_tickers_by_news.setdefault(news_id, set()).add(ticker)

    event_score_rows = load_news_impact_scores(
        session,
        target_level="event",
        target_ids=event_ids,
        limit=max(len(event_ids) * 10, 1000),
    )
    news_score_rows = load_news_impact_scores(
        session,
        target_level="news",
        news_ids=all_news_ids,
        limit=max(len(all_news_ids) * 20, 2000),
    )

    event_scores_by_event: dict[str, list[dict[str, object]]] = {}
    for row in event_score_rows:
        event_id = str(row.get("target_id") or "").strip()
        if not event_id:
            continue
        event_scores_by_event.setdefault(event_id, []).append(row)

    news_scores_by_news: dict[str, list[dict[str, object]]] = {}
    for row in news_score_rows:
        news_id = str(row.get("news_id") or "").strip()
        if not news_id:
            continue
        news_scores_by_news.setdefault(news_id, []).append(row)

    target_by_event_ticker: dict[tuple[str, str], dict[str, object]] = {}
    for ticker in normalized_tickers:
        target_rows = load_event_target_v2(
            session,
            event_ids=event_ids,
            symbol=ticker,
            horizon=horizon,
            limit=max(len(event_ids) * 3, 1000),
        )
        for target in target_rows:
            if not isinstance(target, dict):
                continue
            event_id = str(target.get("event_id") or "").strip()
            symbol = str(target.get("symbol") or "").strip().upper()
            if event_id and symbol:
                target_by_event_ticker[(event_id, symbol)] = target

    horizon_delta = _horizon_to_delta(horizon)
    event_ts_by_id: dict[str, datetime] = {}
    for event in event_rows:
        if not isinstance(event, dict):
            continue
        event_id = str(event.get("event_id") or "").strip()
        if not event_id:
            continue
        event_ts = _parse_iso_utc_dt(event.get("event_first_published_at_utc"))
        if event_ts is not None:
            event_ts_by_id[event_id] = event_ts

    moex_eval_by_event_ticker: dict[tuple[str, str], dict[str, object]] = {}
    if moex_client is not None and event_ts_by_id:
        try:
            contracts = _parse_contracts(moex_client.get_futures_specs(moex_futures_board))
        except Exception:
            contracts = []
        if contracts:
            eval_contract_by_event_ticker: dict[tuple[str, str], _MoexContract] = {}
            required_secids: set[str] = set()
            for event_id, event_ts in event_ts_by_id.items():
                for ticker in normalized_tickers:
                    selected = _select_contract(
                        contracts=contracts,
                        ticker=ticker,
                        event_ts_utc=event_ts,
                        roll_days=moex_roll_days,
                    )
                    if selected is None:
                        continue
                    eval_contract_by_event_ticker[(event_id, ticker)] = selected
                    required_secids.add(selected.secid)

            series_by_secid: dict[str, tuple[list[datetime], list[float]]] = {}
            if required_secids:
                fetch_from_local = (from_dt - timedelta(days=3)).astimezone(MSK_TZ).date()
                fetch_to_local = (to_dt + horizon_delta + timedelta(days=3)).astimezone(MSK_TZ).date()
                for secid in sorted(required_secids):
                    try:
                        series_by_secid[secid] = _build_contract_series(
                            client=moex_client,
                            secid=secid,
                            board=moex_futures_board,
                            from_date_local=fetch_from_local,
                            to_date_local=fetch_to_local,
                        )
                    except Exception:
                        continue

            for (event_id, ticker), contract in eval_contract_by_event_ticker.items():
                event_ts = event_ts_by_id.get(event_id)
                series = series_by_secid.get(contract.secid)
                if event_ts is None or series is None:
                    continue
                evaluated = _evaluate_on_series(
                    event_ts_utc=event_ts,
                    horizon_delta=horizon_delta,
                    ts_list=series[0],
                    px_list=series[1],
                )
                if evaluated is None:
                    continue
                moex_eval_by_event_ticker[(event_id, ticker)] = {
                    **evaluated,
                    "contract_secid": contract.secid,
                    "contract_expiry": contract.expiry.isoformat(),
                    "contract_asset_code": contract.asset_code,
                }

    all_rows: list[dict[str, object]] = []
    summary: dict[str, dict[str, object]] = {}
    for ticker in normalized_tickers:
        ticker_rows: list[dict[str, object]] = []
        for event in event_rows:
            if not isinstance(event, dict):
                continue
            event_id = str(event.get("event_id") or "").strip()
            if not event_id:
                continue
            linked_news_ids = event_to_news_ids.get(event_id, [])
            event_tickers: set[str] = set()
            for news_id in linked_news_ids:
                event_tickers.update(entity_tickers_by_news.get(news_id, set()))
            if ticker not in event_tickers:
                continue

            model_scores = event_scores_by_event.get(event_id, [])
            if not model_scores:
                source_rows: list[dict[str, object]] = []
                for news_id in linked_news_ids:
                    source_rows.extend(news_scores_by_news.get(news_id, []))
                if source_rows:
                    model_scores = _derive_event_model_scores_from_news(event_id=event_id, news_rows=source_rows)
            if not model_scores:
                continue
            top_score = _select_primary_model_score(model_scores, preferred_models)
            if not isinstance(top_score, dict):
                continue

            primary_news = next(
                (
                    news_by_id.get(news_id)
                    for news_id in linked_news_ids
                    if isinstance(news_by_id.get(news_id), dict)
                ),
                None,
            )
            target = target_by_event_ticker.get((event_id, ticker))
            moex_eval = moex_eval_by_event_ticker.get((event_id, ticker))
            actual_eval = moex_eval if isinstance(moex_eval, dict) else target
            published_ts = _parse_iso_utc_dt(event.get("event_first_published_at_utc"))
            t0_ts = _parse_iso_utc_dt(actual_eval.get("t0")) if isinstance(actual_eval, dict) else None
            signal_to_t0_minutes: float | None = None
            if published_ts is not None and t0_ts is not None:
                signal_to_t0_minutes = (t0_ts - published_ts).total_seconds() / 60.0
            gap_lag_threshold = max(int(gap_lag_minutes or 0), 1)
            actual_t0_before_publication = bool(signal_to_t0_minutes is not None and signal_to_t0_minutes < 0.0)
            actual_t0_after_publication = bool(signal_to_t0_minutes is not None and signal_to_t0_minutes > 0.0)
            actual_gap_likely = bool(
                signal_to_t0_minutes is not None
                and (-signal_to_t0_minutes) >= float(gap_lag_threshold)
                and actual_t0_before_publication
            )
            pred_sign = _map_pred_direction(top_score.get("direction"))
            label_sign = _map_label_direction(target.get("label_v2") if isinstance(target, dict) else None)
            raw_sign = 0
            raw_value = None
            if isinstance(actual_eval, dict):
                try:
                    raw_value = float(actual_eval.get("r_raw"))
                    if raw_value > 0:
                        raw_sign = 1
                    elif raw_value < 0:
                        raw_sign = -1
                except (TypeError, ValueError):
                    raw_value = None
                    raw_sign = 0

            row = {
                "ticker": ticker,
                "news_event_id": event_id,
                "published_at_utc": event.get("event_first_published_at_utc"),
                "published_at_local": _format_local_human(event.get("event_first_published_at_utc"), local_tz),
                "headline": str(event.get("canonical_summary") or "").strip()
                or str((primary_news or {}).get("title") or event_id).strip(),
                "url": (primary_news or {}).get("url"),
                "pred_direction": "up" if pred_sign > 0 else "down" if pred_sign < 0 else "neutral",
                "pred_prob_up": top_score.get("prob_up"),
                "pred_prob_down": top_score.get("prob_down"),
                "pred_prob_neutral": top_score.get("prob_neutral"),
                "pred_impact_score": top_score.get("impact_score"),
                "pred_model_id": top_score.get("model_id"),
                "pred_derived_from": top_score.get("derived_from"),
                "target_row_found": bool(target),
                "moex_eval_row_found": bool(moex_eval),
                "actual_eval_source": "moex_contract" if bool(moex_eval) else ("target_v2" if bool(target) else None),
                "actual_contract_secid": moex_eval.get("contract_secid") if isinstance(moex_eval, dict) else None,
                "actual_contract_expiry": moex_eval.get("contract_expiry") if isinstance(moex_eval, dict) else None,
                "actual_label_v2": target.get("label_v2") if isinstance(target, dict) else None,
                "actual_direction_v2": "up" if label_sign > 0 else "down" if label_sign < 0 else "hold",
                "actual_t0_local": _format_local_human(actual_eval.get("t0"), local_tz) if isinstance(actual_eval, dict) else None,
                "actual_t1_local": _format_local_human(actual_eval.get("t1"), local_tz) if isinstance(actual_eval, dict) else None,
                "actual_signal_to_t0_minutes": signal_to_t0_minutes,
                "actual_t0_before_publication": actual_t0_before_publication,
                "actual_t0_after_publication": actual_t0_after_publication,
                "actual_gap_likely": actual_gap_likely,
                "actual_r_raw": raw_value,
                "actual_ar": target.get("ar") if isinstance(target, dict) else None,
                "actual_is_hi_conf": target.get("is_hi_conf") if isinstance(target, dict) else None,
                "actual_is_clean": (
                    bool(target)
                    and not bool(target.get("is_overlapped"))
                    and not bool(target.get("is_repost"))
                    and not bool(target.get("leakage_postmove"))
                )
                if isinstance(target, dict)
                else False,
                "directional_match_label_v2": bool(pred_sign != 0 and label_sign != 0 and pred_sign == label_sign),
                "directional_comparable_label_v2": bool(pred_sign != 0 and label_sign != 0),
                "directional_match_r_raw": bool(pred_sign != 0 and raw_sign != 0 and pred_sign == raw_sign),
                "directional_comparable_r_raw": bool(pred_sign != 0 and raw_sign != 0),
                "directional_match_r_raw_with_gap": bool(pred_sign != 0 and raw_sign != 0 and pred_sign == raw_sign),
                "directional_comparable_r_raw_with_gap": bool(pred_sign != 0 and raw_sign != 0),
                "directional_match_r_raw_no_gap": bool(
                    pred_sign != 0
                    and raw_sign != 0
                    and pred_sign == raw_sign
                    and not actual_gap_likely
                ),
                "directional_comparable_r_raw_no_gap": bool(pred_sign != 0 and raw_sign != 0 and not actual_gap_likely),
            }
            ticker_rows.append(row)
            all_rows.append(row)

        comparable_label = sum(1 for row in ticker_rows if row["directional_comparable_label_v2"])
        hits_label = sum(1 for row in ticker_rows if row["directional_match_label_v2"])
        comparable_raw = sum(1 for row in ticker_rows if row["directional_comparable_r_raw"])
        hits_raw = sum(1 for row in ticker_rows if row["directional_match_r_raw"])
        comparable_raw_no_gap = sum(1 for row in ticker_rows if row["directional_comparable_r_raw_no_gap"])
        hits_raw_no_gap = sum(1 for row in ticker_rows if row["directional_match_r_raw_no_gap"])
        summary[ticker] = {
            "events_with_predictions": len(ticker_rows),
            "events_with_target": sum(1 for row in ticker_rows if row["target_row_found"]),
            "events_with_moex_eval": sum(1 for row in ticker_rows if bool(row.get("moex_eval_row_found"))),
            "t0_before_publication_events": sum(
                1 for row in ticker_rows if bool(row.get("actual_t0_before_publication"))
            ),
            "t0_after_publication_events": sum(
                1 for row in ticker_rows if bool(row.get("actual_t0_after_publication"))
            ),
            "gap_likely_events": sum(1 for row in ticker_rows if bool(row.get("actual_gap_likely"))),
            "directional_comparable_label_v2": comparable_label,
            "directional_hits_label_v2": hits_label,
            "directional_hit_rate_label_v2": (hits_label / comparable_label) if comparable_label else None,
            "directional_comparable_r_raw": comparable_raw,
            "directional_hits_r_raw": hits_raw,
            "directional_hit_rate_r_raw": (hits_raw / comparable_raw) if comparable_raw else None,
            "directional_comparable_r_raw_with_gap": comparable_raw,
            "directional_hits_r_raw_with_gap": hits_raw,
            "directional_hit_rate_r_raw_with_gap": (hits_raw / comparable_raw) if comparable_raw else None,
            "directional_comparable_r_raw_no_gap": comparable_raw_no_gap,
            "directional_hits_r_raw_no_gap": hits_raw_no_gap,
            "directional_hit_rate_r_raw_no_gap": (
                (hits_raw_no_gap / comparable_raw_no_gap) if comparable_raw_no_gap else None
            ),
        }

    sorted_rows = sorted(
        all_rows,
        key=lambda row: (
            str(row.get("ticker") or ""),
            str(row.get("published_at_utc") or ""),
        ),
    )
    return sorted_rows, summary


def render_news_live_eval_top(
    rows: list[dict[str, object]],
    *,
    tickers: list[str],
    top_per_ticker: int,
) -> str:
    lines: list[str] = []
    for ticker in tickers:
        normalized = str(ticker).strip().upper()
        lines.append(f"=== {normalized} ===")
        top_rows = [row for row in rows if str(row.get("ticker") or "").strip().upper() == normalized]
        top_rows.sort(key=lambda row: _as_float(row.get("pred_impact_score")), reverse=True)
        for row in top_rows[: max(top_per_ticker, 1)]:
            lines.append(
                (
                    f"{row.get('published_at_local')} | {row.get('pred_direction')} | "
                    f"p_up={_as_float(row.get('pred_prob_up')):.3f} "
                    f"p_down={_as_float(row.get('pred_prob_down')):.3f} "
                    f"impact={_as_float(row.get('pred_impact_score')):.3f} | "
                    f"gap={'Y' if bool(row.get('actual_gap_likely')) else 'N'} | "
                    f"secid={str(row.get('actual_contract_secid') or '-')} | "
                    f"{str(row.get('headline') or '')[:120]}"
                )
            )
    return "\n".join(lines)
