from __future__ import annotations

from datetime import datetime, timezone
from typing import Iterable

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from moex_carry.storage import models as db
from moex_carry.storage.repositories_helpers import (
    _float_or_none,
    _int_or_none,
    _parse_datetime_value,
    _str_or_none,
    _to_iso_z,
)

def upsert_event_target_v2(session: Session, rows: Iterable[dict[str, object]]) -> int:
    stored = 0
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    for row in rows:
        event_id = _str_or_none(row.get("event_id"))
        symbol = _str_or_none(row.get("symbol"))
        horizon = _str_or_none(row.get("horizon"))
        t0 = _parse_datetime_value(row.get("t0"))
        t1 = _parse_datetime_value(row.get("t1"))
        if event_id is None or symbol is None or horizon is None or t0 is None or t1 is None:
            continue
        existing = (
            session.execute(
                select(db.EventTargetV2Model).where(
                    db.EventTargetV2Model.event_id == event_id,
                    db.EventTargetV2Model.symbol == symbol,
                    db.EventTargetV2Model.horizon == horizon,
                )
            )
            .scalars()
            .first()
        )
        payload = {
            "event_id": event_id,
            "symbol": symbol,
            "horizon": horizon,
            "t_pub": _parse_datetime_value(row.get("t_pub")),
            "t_anchor": _parse_datetime_value(row.get("t_anchor")),
            "t_event": _parse_datetime_value(row.get("t_event")),
            "event_time_source": _str_or_none(row.get("event_time_source")),
            "t0": t0,
            "t1": t1,
            "p0": _float_or_none(row.get("p0")) or 0.0,
            "p1": _float_or_none(row.get("p1")) or 0.0,
            "r_raw": _float_or_none(row.get("r_raw")) or 0.0,
            "r_post": _float_or_none(row.get("r_post")),
            "r_pre": _float_or_none(row.get("r_pre")),
            "r_exp": _float_or_none(row.get("r_exp")) or 0.0,
            "ar": _float_or_none(row.get("ar")) or 0.0,
            "sigma_pre": _float_or_none(row.get("sigma_pre")) or 0.0,
            "sigma_hat": _float_or_none(row.get("sigma_hat")),
            "z_post": _float_or_none(row.get("z_post")),
            "z_pre": _float_or_none(row.get("z_pre")),
            "z_hold": _float_or_none(row.get("z_hold")),
            "z_big": _float_or_none(row.get("z_big")),
            "impact_bin": _int_or_none(row.get("impact_bin")),
            "impact_score": _float_or_none(row.get("impact_score")),
            "overlap_count": _int_or_none(row.get("overlap_count")) or 0,
            "echo_score": _float_or_none(row.get("echo_score")),
            "premove_penalty": _float_or_none(row.get("premove_penalty")),
            "confidence": _float_or_none(row.get("confidence")),
            "label_v2": _int_or_none(row.get("label_v2")) or 0,
            "is_hi_conf": bool(row.get("is_hi_conf")),
            "leakage_postmove": bool(row.get("leakage_postmove")),
            "is_repost": bool(row.get("is_repost")),
            "is_overlapped": bool(row.get("is_overlapped")),
            "price_source": _str_or_none(row.get("price_source")) or "mid",
            "created_at": _parse_datetime_value(row.get("created_at")) or now,
            "updated_at": _parse_datetime_value(row.get("updated_at")) or now,
        }
        if existing is None:
            session.add(db.EventTargetV2Model(**payload))
        else:
            existing.t_pub = payload["t_pub"]
            existing.t_anchor = payload["t_anchor"]
            existing.t_event = payload["t_event"]
            existing.event_time_source = payload["event_time_source"]
            existing.t0 = payload["t0"]
            existing.t1 = payload["t1"]
            existing.p0 = payload["p0"]
            existing.p1 = payload["p1"]
            existing.r_raw = payload["r_raw"]
            existing.r_post = payload["r_post"]
            existing.r_pre = payload["r_pre"]
            existing.r_exp = payload["r_exp"]
            existing.ar = payload["ar"]
            existing.sigma_pre = payload["sigma_pre"]
            existing.sigma_hat = payload["sigma_hat"]
            existing.z_post = payload["z_post"]
            existing.z_pre = payload["z_pre"]
            existing.z_hold = payload["z_hold"]
            existing.z_big = payload["z_big"]
            existing.impact_bin = payload["impact_bin"]
            existing.impact_score = payload["impact_score"]
            existing.overlap_count = payload["overlap_count"]
            existing.echo_score = payload["echo_score"]
            existing.premove_penalty = payload["premove_penalty"]
            existing.confidence = payload["confidence"]
            existing.label_v2 = payload["label_v2"]
            existing.is_hi_conf = payload["is_hi_conf"]
            existing.leakage_postmove = payload["leakage_postmove"]
            existing.is_repost = payload["is_repost"]
            existing.is_overlapped = payload["is_overlapped"]
            existing.price_source = payload["price_source"]
            existing.created_at = payload["created_at"]
            existing.updated_at = payload["updated_at"]
        stored += 1
    session.commit()
    return stored


def load_event_target_v2(
    session: Session,
    *,
    event_ids: Iterable[str] | None = None,
    symbol: str | None = None,
    horizon: str | None = None,
    from_ts: str | None = None,
    to_ts: str | None = None,
    clean_only: bool = False,
    limit: int = 10000,
) -> list[dict[str, object]]:
    query = select(db.EventTargetV2Model)
    if event_ids:
        normalized = [str(item).strip() for item in event_ids if str(item).strip()]
        if normalized:
            query = query.where(db.EventTargetV2Model.event_id.in_(normalized))
    if symbol:
        query = query.where(db.EventTargetV2Model.symbol == str(symbol).strip().upper())
    if horizon:
        query = query.where(db.EventTargetV2Model.horizon == str(horizon).strip().lower())
    parsed_from = _parse_datetime_value(from_ts)
    parsed_to = _parse_datetime_value(to_ts)
    if parsed_from is not None:
        query = query.where(db.EventTargetV2Model.t0 >= parsed_from)
    if parsed_to is not None:
        query = query.where(db.EventTargetV2Model.t0 <= parsed_to)
    if clean_only:
        query = query.where(db.EventTargetV2Model.leakage_postmove.is_(False))
        query = query.where(db.EventTargetV2Model.is_overlapped.is_(False))
        query = query.where(db.EventTargetV2Model.is_repost.is_(False))
    query = query.order_by(db.EventTargetV2Model.t0.asc(), db.EventTargetV2Model.event_id.asc())
    if limit > 0:
        query = query.limit(limit)
    rows = session.execute(query).scalars().all()
    return [
        {
            "event_id": row.event_id,
            "symbol": row.symbol,
            "horizon": row.horizon,
            "t_pub": _to_iso_z(row.t_pub),
            "t_anchor": _to_iso_z(row.t_anchor),
            "t_event": _to_iso_z(row.t_event),
            "event_time_source": row.event_time_source,
            "t0": _to_iso_z(row.t0),
            "t1": _to_iso_z(row.t1),
            "p0": row.p0,
            "p1": row.p1,
            "r_raw": row.r_raw,
            "r_post": row.r_post,
            "r_pre": row.r_pre,
            "r_exp": row.r_exp,
            "ar": row.ar,
            "sigma_pre": row.sigma_pre,
            "sigma_hat": row.sigma_hat,
            "z_post": row.z_post,
            "z_pre": row.z_pre,
            "z_hold": row.z_hold,
            "z_big": row.z_big,
            "impact_bin": row.impact_bin,
            "impact_score": row.impact_score,
            "overlap_count": row.overlap_count,
            "echo_score": row.echo_score,
            "premove_penalty": row.premove_penalty,
            "confidence": row.confidence,
            "label_v2": row.label_v2,
            "is_hi_conf": bool(row.is_hi_conf),
            "leakage_postmove": bool(row.leakage_postmove),
            "is_repost": bool(row.is_repost),
            "is_overlapped": bool(row.is_overlapped),
            "price_source": row.price_source,
            "created_at": _to_iso_z(row.created_at),
            "updated_at": _to_iso_z(row.updated_at),
        }
        for row in rows
    ]


def delete_event_target_v2_window(
    session: Session,
    *,
    symbol: str | None = None,
    horizon: str | None = None,
    from_ts: str | None = None,
    to_ts: str | None = None,
) -> int:
    query = delete(db.EventTargetV2Model)
    if symbol:
        query = query.where(db.EventTargetV2Model.symbol == str(symbol).strip().upper())
    if horizon:
        query = query.where(db.EventTargetV2Model.horizon == str(horizon).strip().lower())
    parsed_from = _parse_datetime_value(from_ts)
    parsed_to = _parse_datetime_value(to_ts)
    if parsed_from is not None:
        query = query.where(db.EventTargetV2Model.t0 >= parsed_from)
    if parsed_to is not None:
        query = query.where(db.EventTargetV2Model.t0 <= parsed_to)
    result = session.execute(query)
    session.commit()
    return int(result.rowcount or 0)


def upsert_exp_return_bucket_stats_v2(session: Session, rows: Iterable[dict[str, object]]) -> int:
    stored = 0
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    for row in rows:
        symbol = _str_or_none(row.get("symbol"))
        horizon = _str_or_none(row.get("horizon"))
        bucket_b = _int_or_none(row.get("bucket_b"))
        bucket_v = _int_or_none(row.get("bucket_v"))
        bucket_s = _int_or_none(row.get("bucket_s"))
        lookback_start = _parse_datetime_value(row.get("lookback_start"))
        lookback_end = _parse_datetime_value(row.get("lookback_end"))
        if (
            symbol is None
            or horizon is None
            or bucket_b is None
            or bucket_v is None
            or bucket_s is None
            or lookback_start is None
            or lookback_end is None
        ):
            continue
        existing = (
            session.execute(
                select(db.ExpReturnBucketStatsV2Model).where(
                    db.ExpReturnBucketStatsV2Model.symbol == symbol,
                    db.ExpReturnBucketStatsV2Model.horizon == horizon,
                    db.ExpReturnBucketStatsV2Model.bucket_b == bucket_b,
                    db.ExpReturnBucketStatsV2Model.bucket_v == bucket_v,
                    db.ExpReturnBucketStatsV2Model.bucket_s == bucket_s,
                    db.ExpReturnBucketStatsV2Model.lookback_start == lookback_start,
                    db.ExpReturnBucketStatsV2Model.lookback_end == lookback_end,
                )
            )
            .scalars()
            .first()
        )
        payload = {
            "symbol": symbol,
            "horizon": horizon,
            "bucket_b": bucket_b,
            "bucket_v": bucket_v,
            "bucket_s": bucket_s,
            "lookback_start": lookback_start,
            "lookback_end": lookback_end,
            "n": _int_or_none(row.get("n")) or 0,
            "mean_return": _float_or_none(row.get("mean_return")),
            "median_return": _float_or_none(row.get("median_return")),
            "updated_at": _parse_datetime_value(row.get("updated_at")) or now,
        }
        if existing is None:
            session.add(db.ExpReturnBucketStatsV2Model(**payload))
        else:
            existing.n = payload["n"]
            existing.mean_return = payload["mean_return"]
            existing.median_return = payload["median_return"]
            existing.updated_at = payload["updated_at"]
        stored += 1
    session.commit()
    return stored


def load_exp_return_bucket_stats_v2(
    session: Session,
    *,
    symbol: str | None = None,
    horizon: str | None = None,
    lookback_end_from: str | None = None,
    lookback_end_to: str | None = None,
    limit: int = 50000,
) -> list[dict[str, object]]:
    query = select(db.ExpReturnBucketStatsV2Model)
    if symbol:
        query = query.where(db.ExpReturnBucketStatsV2Model.symbol == str(symbol).strip().upper())
    if horizon:
        query = query.where(db.ExpReturnBucketStatsV2Model.horizon == str(horizon).strip().lower())
    parsed_from = _parse_datetime_value(lookback_end_from)
    parsed_to = _parse_datetime_value(lookback_end_to)
    if parsed_from is not None:
        query = query.where(db.ExpReturnBucketStatsV2Model.lookback_end >= parsed_from)
    if parsed_to is not None:
        query = query.where(db.ExpReturnBucketStatsV2Model.lookback_end <= parsed_to)
    query = query.order_by(db.ExpReturnBucketStatsV2Model.lookback_end.desc())
    if limit > 0:
        query = query.limit(limit)
    rows = session.execute(query).scalars().all()
    return [
        {
            "symbol": row.symbol,
            "horizon": row.horizon,
            "bucket_b": row.bucket_b,
            "bucket_v": row.bucket_v,
            "bucket_s": row.bucket_s,
            "lookback_start": _to_iso_z(row.lookback_start),
            "lookback_end": _to_iso_z(row.lookback_end),
            "n": row.n,
            "mean_return": row.mean_return,
            "median_return": row.median_return,
            "updated_at": _to_iso_z(row.updated_at),
        }
        for row in rows
    ]


def upsert_event_factor_scores_v2(session: Session, rows: Iterable[dict[str, object]]) -> int:
    stored = 0
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    for row in rows:
        event_id = _str_or_none(row.get("event_id"))
        symbol = _str_or_none(row.get("symbol"))
        factor_name = _str_or_none(row.get("factor_name"))
        model_name = _str_or_none(row.get("model_name"))
        if event_id is None or symbol is None or factor_name is None or model_name is None:
            continue
        existing = (
            session.execute(
                select(db.EventFactorScoreV2Model).where(
                    db.EventFactorScoreV2Model.event_id == event_id,
                    db.EventFactorScoreV2Model.symbol == symbol,
                    db.EventFactorScoreV2Model.factor_name == factor_name,
                    db.EventFactorScoreV2Model.model_name == model_name,
                )
            )
            .scalars()
            .first()
        )
        payload = {
            "event_id": event_id,
            "symbol": symbol,
            "factor_name": factor_name,
            "p_entail_bull": _float_or_none(row.get("p_entail_bull")) or 0.0,
            "p_entail_bear": _float_or_none(row.get("p_entail_bear")) or 0.0,
            "factor_score": _float_or_none(row.get("factor_score")) or 0.0,
            "factor_conf": _float_or_none(row.get("factor_conf")) or 0.0,
            "model_name": model_name,
            "computed_at": _parse_datetime_value(row.get("computed_at")) or now,
        }
        if existing is None:
            session.add(db.EventFactorScoreV2Model(**payload))
        else:
            existing.p_entail_bull = payload["p_entail_bull"]
            existing.p_entail_bear = payload["p_entail_bear"]
            existing.factor_score = payload["factor_score"]
            existing.factor_conf = payload["factor_conf"]
            existing.computed_at = payload["computed_at"]
        stored += 1
    session.commit()
    return stored


def load_event_factor_scores_v2(
    session: Session,
    *,
    event_id: str | None = None,
    symbol: str | None = None,
    model_name: str | None = None,
    limit: int = 10000,
) -> list[dict[str, object]]:
    query = select(db.EventFactorScoreV2Model)
    if event_id:
        query = query.where(db.EventFactorScoreV2Model.event_id == str(event_id).strip())
    if symbol:
        query = query.where(db.EventFactorScoreV2Model.symbol == str(symbol).strip().upper())
    if model_name:
        query = query.where(db.EventFactorScoreV2Model.model_name == str(model_name).strip())
    query = query.order_by(db.EventFactorScoreV2Model.computed_at.desc())
    if limit > 0:
        query = query.limit(limit)
    rows = session.execute(query).scalars().all()
    return [
        {
            "event_id": row.event_id,
            "symbol": row.symbol,
            "factor_name": row.factor_name,
            "p_entail_bull": row.p_entail_bull,
            "p_entail_bear": row.p_entail_bear,
            "factor_score": row.factor_score,
            "factor_conf": row.factor_conf,
            "model_name": row.model_name,
            "computed_at": _to_iso_z(row.computed_at),
        }
        for row in rows
    ]


def upsert_model_pred_v2(session: Session, rows: Iterable[dict[str, object]]) -> int:
    stored = 0
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    for row in rows:
        run_id = _str_or_none(row.get("run_id"))
        event_id = _str_or_none(row.get("event_id"))
        symbol = _str_or_none(row.get("symbol"))
        horizon = _str_or_none(row.get("horizon"))
        if run_id is None or event_id is None or symbol is None or horizon is None:
            continue
        existing = (
            session.execute(
                select(db.ModelPredV2Model).where(
                    db.ModelPredV2Model.run_id == run_id,
                    db.ModelPredV2Model.event_id == event_id,
                    db.ModelPredV2Model.symbol == symbol,
                    db.ModelPredV2Model.horizon == horizon,
                )
            )
            .scalars()
            .first()
        )
        payload = {
            "run_id": run_id,
            "event_id": event_id,
            "symbol": symbol,
            "horizon": horizon,
            "p_move": _float_or_none(row.get("p_move")) or 0.0,
            "p_up_given_move": _float_or_none(row.get("p_up_given_move")) or 0.5,
            "p_up": _float_or_none(row.get("p_up")) or 0.0,
            "p_down": _float_or_none(row.get("p_down")) or 0.0,
            "p_hold": _float_or_none(row.get("p_hold")) or 1.0,
            "decision": _int_or_none(row.get("decision")) or 0,
            "threshold_set_id": _str_or_none(row.get("threshold_set_id")) or "default-v2",
            "model_version": _str_or_none(row.get("model_version")) or "v2",
            "is_calibrated": bool(row.get("is_calibrated")),
            "created_at": _parse_datetime_value(row.get("created_at")) or now,
        }
        if existing is None:
            session.add(db.ModelPredV2Model(**payload))
        else:
            existing.p_move = payload["p_move"]
            existing.p_up_given_move = payload["p_up_given_move"]
            existing.p_up = payload["p_up"]
            existing.p_down = payload["p_down"]
            existing.p_hold = payload["p_hold"]
            existing.decision = payload["decision"]
            existing.threshold_set_id = payload["threshold_set_id"]
            existing.model_version = payload["model_version"]
            existing.is_calibrated = payload["is_calibrated"]
            existing.created_at = payload["created_at"]
        stored += 1
    session.commit()
    return stored


def load_model_pred_v2(
    session: Session,
    *,
    run_id: str | None = None,
    symbol: str | None = None,
    horizon: str | None = None,
    limit: int = 10000,
) -> list[dict[str, object]]:
    query = select(db.ModelPredV2Model)
    if run_id:
        query = query.where(db.ModelPredV2Model.run_id == str(run_id).strip())
    if symbol:
        query = query.where(db.ModelPredV2Model.symbol == str(symbol).strip().upper())
    if horizon:
        query = query.where(db.ModelPredV2Model.horizon == str(horizon).strip().lower())
    query = query.order_by(db.ModelPredV2Model.created_at.desc())
    if limit > 0:
        query = query.limit(limit)
    rows = session.execute(query).scalars().all()
    return [
        {
            "run_id": row.run_id,
            "event_id": row.event_id,
            "symbol": row.symbol,
            "horizon": row.horizon,
            "p_move": row.p_move,
            "p_up_given_move": row.p_up_given_move,
            "p_up": row.p_up,
            "p_down": row.p_down,
            "p_hold": row.p_hold,
            "decision": row.decision,
            "threshold_set_id": row.threshold_set_id,
            "model_version": row.model_version,
            "is_calibrated": bool(row.is_calibrated),
            "created_at": _to_iso_z(row.created_at),
        }
        for row in rows
    ]


def upsert_gate_run_v2(session: Session, row: dict[str, object]) -> str | None:
    run_id = _str_or_none(row.get("run_id"))
    symbol = _str_or_none(row.get("symbol"))
    horizon = _str_or_none(row.get("horizon"))
    period_start = _parse_datetime_value(row.get("period_start"))
    period_end = _parse_datetime_value(row.get("period_end"))
    if run_id is None or symbol is None or horizon is None or period_start is None or period_end is None:
        return None
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    existing = (
        session.execute(
            select(db.GateRunV2Model).where(
                db.GateRunV2Model.run_id == run_id,
                db.GateRunV2Model.symbol == symbol,
                db.GateRunV2Model.horizon == horizon,
            )
        )
        .scalars()
        .first()
    )
    payload = {
        "run_id": run_id,
        "symbol": symbol,
        "horizon": horizon,
        "period_start": period_start,
        "period_end": period_end,
        "market_pass": bool(row.get("market_pass")),
        "leakage_pass": bool(row.get("leakage_pass")),
        "supervised_pass_shadow": bool(row.get("supervised_pass_shadow")),
        "supervised_pass_prod": bool(row.get("supervised_pass_prod")),
        "baseline_pass": bool(row.get("baseline_pass")),
        "utility_pass": bool(row.get("utility_pass")),
        "overall_pass_prod": bool(row.get("overall_pass_prod")),
        "metrics_json": row.get("metrics_json"),
        "winner_model_version": _str_or_none(row.get("winner_model_version")),
        "created_at": _parse_datetime_value(row.get("created_at")) or now,
    }
    if existing is None:
        session.add(db.GateRunV2Model(**payload))
    else:
        existing.period_start = payload["period_start"]
        existing.period_end = payload["period_end"]
        existing.market_pass = payload["market_pass"]
        existing.leakage_pass = payload["leakage_pass"]
        existing.supervised_pass_shadow = payload["supervised_pass_shadow"]
        existing.supervised_pass_prod = payload["supervised_pass_prod"]
        existing.baseline_pass = payload["baseline_pass"]
        existing.utility_pass = payload["utility_pass"]
        existing.overall_pass_prod = payload["overall_pass_prod"]
        existing.metrics_json = payload["metrics_json"]
        existing.winner_model_version = payload["winner_model_version"]
        existing.created_at = payload["created_at"]
    session.commit()
    return run_id


def load_gate_run_v2(
    session: Session,
    *,
    symbol: str | None = None,
    horizon: str | None = None,
    run_id: str | None = None,
    limit: int = 200,
) -> list[dict[str, object]]:
    query = select(db.GateRunV2Model)
    if symbol:
        query = query.where(db.GateRunV2Model.symbol == str(symbol).strip().upper())
    if horizon:
        query = query.where(db.GateRunV2Model.horizon == str(horizon).strip().lower())
    if run_id:
        query = query.where(db.GateRunV2Model.run_id == str(run_id).strip())
    query = query.order_by(db.GateRunV2Model.created_at.desc())
    if limit > 0:
        query = query.limit(limit)
    rows = session.execute(query).scalars().all()
    return [
        {
            "run_id": row.run_id,
            "symbol": row.symbol,
            "horizon": row.horizon,
            "period_start": _to_iso_z(row.period_start),
            "period_end": _to_iso_z(row.period_end),
            "market_pass": bool(row.market_pass),
            "leakage_pass": bool(row.leakage_pass),
            "supervised_pass_shadow": bool(row.supervised_pass_shadow),
            "supervised_pass_prod": bool(row.supervised_pass_prod),
            "baseline_pass": bool(row.baseline_pass),
            "utility_pass": bool(row.utility_pass),
            "overall_pass_prod": bool(row.overall_pass_prod),
            "metrics_json": row.metrics_json,
            "winner_model_version": row.winner_model_version,
            "created_at": _to_iso_z(row.created_at),
        }
        for row in rows
    ]
