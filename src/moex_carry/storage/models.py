from __future__ import annotations

from sqlalchemy import (
    Boolean,
    Date,
    DateTime,
    Float,
    Integer,
    JSON,
    String,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, declarative_base, mapped_column


Base = declarative_base()


class InstrumentModel(Base):
    __tablename__ = "instruments"

    secid: Mapped[str] = mapped_column(String, primary_key=True)
    name: Mapped[str] = mapped_column(String)
    instrument_type: Mapped[str] = mapped_column(String)
    currency: Mapped[str] = mapped_column(String)
    board: Mapped[str | None] = mapped_column(String, nullable=True)


class ContractSpecModel(Base):
    __tablename__ = "contract_specs"

    secid: Mapped[str] = mapped_column(String, primary_key=True)
    asset_code: Mapped[str] = mapped_column(String, index=True)
    expiry: Mapped[Date] = mapped_column(Date)
    lot_size: Mapped[float] = mapped_column(Float)
    price_step: Mapped[float] = mapped_column(Float)
    multiplier: Mapped[float] = mapped_column(Float)


class PairMappingModel(Base):
    __tablename__ = "pair_mappings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    stock_secid: Mapped[str] = mapped_column(String, index=True)
    future_secid: Mapped[str] = mapped_column(String, index=True)
    expiry: Mapped[Date] = mapped_column(Date)


class QuoteModel(Base):
    __tablename__ = "quotes"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    secid: Mapped[str] = mapped_column(String, index=True)
    timestamp: Mapped[DateTime] = mapped_column(DateTime, index=True)
    bid: Mapped[float | None] = mapped_column(Float, nullable=True)
    ask: Mapped[float | None] = mapped_column(Float, nullable=True)
    last: Mapped[float | None] = mapped_column(Float, nullable=True)
    volume: Mapped[float | None] = mapped_column(Float, nullable=True)


class DividendEventModel(Base):
    __tablename__ = "dividend_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    secid: Mapped[str] = mapped_column(String, index=True)
    ex_date: Mapped[Date] = mapped_column(Date, index=True)
    amount: Mapped[float] = mapped_column(Float)
    currency: Mapped[str] = mapped_column(String)
    status: Mapped[str] = mapped_column(String)


class KeyRateModel(Base):
    __tablename__ = "key_rates"

    date: Mapped[Date] = mapped_column(Date, primary_key=True)
    rate: Mapped[float] = mapped_column(Float)


class SignalModel(Base):
    __tablename__ = "signals"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    timestamp: Mapped[DateTime] = mapped_column(DateTime, index=True)
    stock_secid: Mapped[str] = mapped_column(String, index=True)
    future_secid: Mapped[str] = mapped_column(String, index=True)
    direction: Mapped[str] = mapped_column(String)
    score: Mapped[float] = mapped_column(Float)
    reasons: Mapped[list[str]] = mapped_column(JSON)
    metrics: Mapped[dict] = mapped_column(JSON)


class SignalRunModel(Base):
    __tablename__ = "signal_runs"

    run_id: Mapped[str] = mapped_column(String, primary_key=True)
    as_of: Mapped[DateTime] = mapped_column(DateTime, index=True)
    params: Mapped[dict] = mapped_column(JSON)


class SignalHistoryModel(Base):
    __tablename__ = "signal_history"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    run_id: Mapped[str] = mapped_column(String, index=True)
    timestamp: Mapped[DateTime] = mapped_column(DateTime, index=True)
    stock_secid: Mapped[str] = mapped_column(String, index=True)
    future_secid: Mapped[str] = mapped_column(String, index=True)
    action: Mapped[str] = mapped_column(String)
    direction: Mapped[str | None] = mapped_column(String, nullable=True)
    score: Mapped[float] = mapped_column(Float)
    reasons: Mapped[list[str]] = mapped_column(JSON)
    metrics: Mapped[dict] = mapped_column(JSON)


class SignalExecutionModel(Base):
    __tablename__ = "signal_executions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    timestamp: Mapped[DateTime] = mapped_column(DateTime, index=True)
    stock_secid: Mapped[str] = mapped_column(String, index=True)
    future_secid: Mapped[str] = mapped_column(String, index=True)
    direction: Mapped[str | None] = mapped_column(String, nullable=True)
    action: Mapped[str] = mapped_column(String)
    price: Mapped[float | None] = mapped_column(Float, nullable=True)
    quantity: Mapped[float | None] = mapped_column(Float, nullable=True)
    side: Mapped[str | None] = mapped_column(String, nullable=True)
    order_id: Mapped[str | None] = mapped_column(String, nullable=True, index=True)
    idempotency_key: Mapped[str | None] = mapped_column(String, nullable=True, index=True)
    status: Mapped[str | None] = mapped_column(String, nullable=True)
    note: Mapped[str | None] = mapped_column(String, nullable=True)


class RuntimeLeaseModel(Base):
    __tablename__ = "runtime_leases"

    lease_name: Mapped[str] = mapped_column(String, primary_key=True)
    owner_id: Mapped[str] = mapped_column(String, index=True)
    acquired_at: Mapped[DateTime] = mapped_column(DateTime, index=True)
    lease_until: Mapped[DateTime] = mapped_column(DateTime, index=True)


class TradeModel(Base):
    __tablename__ = "trades"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    entry_date: Mapped[Date] = mapped_column(Date)
    exit_date: Mapped[Date | None] = mapped_column(Date, nullable=True)
    stock_secid: Mapped[str] = mapped_column(String)
    future_secid: Mapped[str] = mapped_column(String)
    direction: Mapped[str] = mapped_column(String)
    entry_price: Mapped[float] = mapped_column(Float)
    exit_price: Mapped[float | None] = mapped_column(Float, nullable=True)
    pnl: Mapped[float | None] = mapped_column(Float, nullable=True)


class BacktestRunModel(Base):
    __tablename__ = "backtest_runs"

    run_id: Mapped[str] = mapped_column(String, primary_key=True)
    started_at: Mapped[DateTime] = mapped_column(DateTime)
    params: Mapped[dict] = mapped_column(JSON)
    metrics: Mapped[dict] = mapped_column(JSON)


class DecisionViewProjectionModel(Base):
    __tablename__ = "decision_view_projection"

    decision_id: Mapped[str] = mapped_column(String, primary_key=True)
    created_at: Mapped[DateTime | None] = mapped_column(DateTime, index=True, nullable=True)
    strategy_type: Mapped[str | None] = mapped_column(String, nullable=True)
    primary_instrument: Mapped[str | None] = mapped_column(String, index=True, nullable=True)
    action: Mapped[str | None] = mapped_column(String, nullable=True)
    risk_state: Mapped[str | None] = mapped_column(String, nullable=True)
    news_severity: Mapped[str | None] = mapped_column(String, nullable=True)
    payload: Mapped[dict] = mapped_column(JSON)
    updated_at: Mapped[DateTime] = mapped_column(DateTime, index=True)


class NewsItemModel(Base):
    __tablename__ = "news_items"

    news_id: Mapped[str] = mapped_column(String, primary_key=True)
    source: Mapped[str] = mapped_column(String, index=True)
    url: Mapped[str | None] = mapped_column(String, nullable=True, unique=True)
    title: Mapped[str] = mapped_column(String)
    content: Mapped[str | None] = mapped_column(String, nullable=True)
    language: Mapped[str | None] = mapped_column(String, nullable=True, index=True)
    published_at: Mapped[DateTime] = mapped_column(DateTime, index=True)
    ingested_at: Mapped[DateTime] = mapped_column(DateTime, index=True)
    hash: Mapped[str] = mapped_column(String, unique=True, index=True)


class NewsEntityLinkModel(Base):
    __tablename__ = "news_entity_links"
    __table_args__ = (
        UniqueConstraint(
            "news_id",
            "entity_type",
            "entity_id",
            "ticker",
            "link_stage",
            name="uq_news_entity_link",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    news_id: Mapped[str] = mapped_column(String, index=True)
    entity_type: Mapped[str] = mapped_column(String, index=True)
    entity_id: Mapped[str] = mapped_column(String, index=True)
    ticker: Mapped[str | None] = mapped_column(String, nullable=True, index=True)
    link_confidence: Mapped[float] = mapped_column(Float)
    link_stage: Mapped[str] = mapped_column(String, index=True)


class NewsTagModel(Base):
    __tablename__ = "news_tags"

    tag_code: Mapped[str] = mapped_column(String, primary_key=True)
    tag_name: Mapped[str] = mapped_column(String)
    description: Mapped[str | None] = mapped_column(String, nullable=True)


class NewsItemTagModel(Base):
    __tablename__ = "news_item_tags"

    news_id: Mapped[str] = mapped_column(String, primary_key=True)
    tag_code: Mapped[str] = mapped_column(String, primary_key=True)
    score: Mapped[float] = mapped_column(Float)


class NewsImpactScoreModel(Base):
    __tablename__ = "news_impact_scores"
    __table_args__ = (
        UniqueConstraint(
            "news_id",
            "model_id",
            "model_version",
            name="uq_news_impact_score_model",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    news_id: Mapped[str] = mapped_column(String, index=True)
    target_level: Mapped[str | None] = mapped_column(String, nullable=True, index=True)
    target_id: Mapped[str | None] = mapped_column(String, nullable=True, index=True)
    model_id: Mapped[str] = mapped_column(String, index=True)
    model_version: Mapped[str] = mapped_column(String)
    direction: Mapped[str] = mapped_column(String, index=True)
    prob_up: Mapped[float] = mapped_column(Float)
    prob_down: Mapped[float] = mapped_column(Float)
    prob_neutral: Mapped[float] = mapped_column(Float)
    impact_score: Mapped[float] = mapped_column(Float, index=True)
    calibrated: Mapped[bool] = mapped_column(Boolean, default=False)
    inference_ts: Mapped[DateTime] = mapped_column(DateTime, index=True)


class NewsSignalLinkModel(Base):
    __tablename__ = "news_signal_links"

    link_id: Mapped[str] = mapped_column(String, primary_key=True)
    news_id: Mapped[str] = mapped_column(String, index=True)
    event_id: Mapped[str | None] = mapped_column(String, nullable=True, index=True)
    signal_id: Mapped[str | None] = mapped_column(String, nullable=True, index=True)
    decision_id: Mapped[str | None] = mapped_column(String, nullable=True, index=True)
    link_type: Mapped[str] = mapped_column(String, index=True)
    window_start: Mapped[DateTime] = mapped_column(DateTime, index=True)
    window_end: Mapped[DateTime] = mapped_column(DateTime, index=True)
    gate_action: Mapped[str] = mapped_column(String, index=True)
    source: Mapped[str] = mapped_column(String, default="runtime")
    created_at: Mapped[DateTime] = mapped_column(DateTime, index=True)


class NewsBacktestReportModel(Base):
    __tablename__ = "news_backtest_reports"

    run_id: Mapped[str] = mapped_column(String, primary_key=True)
    period_from: Mapped[DateTime] = mapped_column(DateTime, index=True)
    period_to: Mapped[DateTime] = mapped_column(DateTime, index=True)
    horizon: Mapped[str] = mapped_column(String, index=True)
    model_id: Mapped[str] = mapped_column(String, index=True)
    metrics_json: Mapped[dict] = mapped_column(JSON)
    created_at: Mapped[DateTime] = mapped_column(DateTime, index=True)


class NewsEventModel(Base):
    __tablename__ = "news_events"

    event_id: Mapped[str] = mapped_column(String, primary_key=True)
    event_first_published_at_utc: Mapped[DateTime] = mapped_column(DateTime, index=True)
    event_first_ingested_at_utc: Mapped[DateTime] = mapped_column(DateTime, index=True)
    event_last_published_at_utc: Mapped[DateTime | None] = mapped_column(
        DateTime, nullable=True, index=True
    )
    event_status: Mapped[str] = mapped_column(String, index=True)
    canonical_summary: Mapped[str | None] = mapped_column(String, nullable=True)
    canonical_mechanism: Mapped[str | None] = mapped_column(String, nullable=True)
    cluster_version: Mapped[str] = mapped_column(String, index=True)
    created_at: Mapped[DateTime] = mapped_column(DateTime, index=True)
    updated_at: Mapped[DateTime] = mapped_column(DateTime, index=True)


class NewsEventItemModel(Base):
    __tablename__ = "news_event_items"

    event_id: Mapped[str] = mapped_column(String, primary_key=True)
    news_id: Mapped[str] = mapped_column(String, primary_key=True)
    link_role: Mapped[str] = mapped_column(String, index=True)
    similarity_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    added_at: Mapped[DateTime] = mapped_column(DateTime, index=True)


class NewsEventUpdateModel(Base):
    __tablename__ = "news_event_updates"
    __table_args__ = (
        UniqueConstraint(
            "event_id",
            "ts_update",
            "source_hash",
            name="uq_news_event_update",
        ),
    )

    update_id: Mapped[str] = mapped_column(String, primary_key=True)
    event_id: Mapped[str] = mapped_column(String, index=True)
    ts_update: Mapped[DateTime] = mapped_column(DateTime, index=True)
    phase: Mapped[str | None] = mapped_column(String, nullable=True, index=True)
    severity: Mapped[float | None] = mapped_column(Float, nullable=True)
    facts_json: Mapped[object | None] = mapped_column(JSON, nullable=True)
    factor_delta_json: Mapped[object | None] = mapped_column(JSON, nullable=True)
    source_url: Mapped[str | None] = mapped_column(String, nullable=True)
    source_hash: Mapped[str | None] = mapped_column(String, nullable=True, index=True)
    created_at: Mapped[DateTime] = mapped_column(DateTime, index=True)


class NewsEventLinkModel(Base):
    __tablename__ = "news_event_links"
    __table_args__ = (
        UniqueConstraint(
            "src_event_id",
            "dst_event_id",
            "link_type",
            name="uq_news_event_link",
        ),
    )

    link_id: Mapped[str] = mapped_column(String, primary_key=True)
    src_event_id: Mapped[str] = mapped_column(String, index=True)
    dst_event_id: Mapped[str] = mapped_column(String, index=True)
    link_type: Mapped[str] = mapped_column(String, index=True)
    confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    evidence_json: Mapped[object | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[DateTime] = mapped_column(DateTime, index=True)


class NewsLabelModel(Base):
    __tablename__ = "news_labels"
    __table_args__ = (
        UniqueConstraint(
            "target_level",
            "target_id",
            "label_source",
            "label_version",
            "model_version",
            "prompt_version",
            name="uq_news_label_target_source_version",
        ),
    )

    label_id: Mapped[str] = mapped_column(String, primary_key=True)
    target_level: Mapped[str] = mapped_column(String, index=True)
    target_id: Mapped[str] = mapped_column(String, index=True)
    commodity_json: Mapped[object | None] = mapped_column(JSON, nullable=True)
    market_scope: Mapped[str | None] = mapped_column(String, nullable=True, index=True)
    instrument_candidates_json: Mapped[object | None] = mapped_column(JSON, nullable=True)
    relevance: Mapped[float | None] = mapped_column(Float, nullable=True)
    news_type_json: Mapped[object | None] = mapped_column(JSON, nullable=True)
    direction: Mapped[str | None] = mapped_column(String, nullable=True, index=True)
    magnitude: Mapped[float | None] = mapped_column(Float, nullable=True)
    lag_bucket: Mapped[str | None] = mapped_column(String, nullable=True, index=True)
    confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    uncertainty_type: Mapped[str | None] = mapped_column(String, nullable=True, index=True)
    geo_scope: Mapped[str | None] = mapped_column(String, nullable=True, index=True)
    evidence_json: Mapped[object | None] = mapped_column(JSON, nullable=True)
    label_source: Mapped[str] = mapped_column(String, index=True)
    label_version: Mapped[str] = mapped_column(String, index=True)
    model_version: Mapped[str | None] = mapped_column(String, nullable=True, index=True)
    prompt_version: Mapped[str | None] = mapped_column(String, nullable=True, index=True)
    created_at: Mapped[DateTime] = mapped_column(DateTime, index=True)


class NewsLlmRunModel(Base):
    __tablename__ = "news_llm_runs"
    __table_args__ = (
        UniqueConstraint(
            "target_level",
            "target_id",
            "provider",
            "model_id",
            "prompt_version",
            "input_hash",
            name="uq_news_llm_run_input",
        ),
    )

    run_id: Mapped[str] = mapped_column(String, primary_key=True)
    target_level: Mapped[str] = mapped_column(String, index=True)
    target_id: Mapped[str] = mapped_column(String, index=True)
    provider: Mapped[str] = mapped_column(String, index=True)
    model_id: Mapped[str] = mapped_column(String, index=True)
    prompt_version: Mapped[str | None] = mapped_column(String, nullable=True, index=True)
    input_hash: Mapped[str] = mapped_column(String, index=True)
    status: Mapped[str] = mapped_column(String, index=True)
    token_in: Mapped[int] = mapped_column(Integer, default=0)
    token_out: Mapped[int] = mapped_column(Integer, default=0)
    latency_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    error_code: Mapped[str | None] = mapped_column(String, nullable=True, index=True)
    created_at: Mapped[DateTime] = mapped_column(DateTime, index=True)


class EventMarketReactionModel(Base):
    __tablename__ = "event_market_reactions"
    __table_args__ = (
        UniqueConstraint(
            "event_id",
            "instrument_id",
            "window_id",
            "sampling_freq",
            name="uq_event_market_reaction",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    event_id: Mapped[str] = mapped_column(String, index=True)
    instrument_id: Mapped[str] = mapped_column(String, index=True)
    window_id: Mapped[str] = mapped_column(String, index=True)
    sampling_freq: Mapped[str] = mapped_column(String, index=True)
    return_raw: Mapped[float | None] = mapped_column(Float, nullable=True)
    return_abnormal: Mapped[float | None] = mapped_column(Float, nullable=True)
    car: Mapped[float | None] = mapped_column(Float, nullable=True)
    rv: Mapped[float | None] = mapped_column(Float, nullable=True)
    vol_change: Mapped[float | None] = mapped_column(Float, nullable=True)
    volume_change: Mapped[float | None] = mapped_column(Float, nullable=True)
    quality_flags_json: Mapped[object | None] = mapped_column(JSON, nullable=True)
    computed_at: Mapped[DateTime] = mapped_column(DateTime, index=True)


class EventTargetV2Model(Base):
    __tablename__ = "event_target_v2"
    __table_args__ = (
        UniqueConstraint(
            "event_id",
            "symbol",
            "horizon",
            name="uq_event_target_v2",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    event_id: Mapped[str] = mapped_column(String, index=True)
    symbol: Mapped[str] = mapped_column(String, index=True)
    horizon: Mapped[str] = mapped_column(String, index=True)
    t_pub: Mapped[DateTime | None] = mapped_column(DateTime, nullable=True, index=True)
    t_anchor: Mapped[DateTime | None] = mapped_column(DateTime, nullable=True, index=True)
    t_event: Mapped[DateTime | None] = mapped_column(DateTime, nullable=True, index=True)
    event_time_source: Mapped[str | None] = mapped_column(String, nullable=True, index=True)
    t0: Mapped[DateTime] = mapped_column(DateTime, index=True)
    t1: Mapped[DateTime] = mapped_column(DateTime, index=True)
    p0: Mapped[float] = mapped_column(Float)
    p1: Mapped[float] = mapped_column(Float)
    r_raw: Mapped[float] = mapped_column(Float)
    r_post: Mapped[float | None] = mapped_column(Float, nullable=True)
    r_pre: Mapped[float | None] = mapped_column(Float, nullable=True)
    r_exp: Mapped[float] = mapped_column(Float)
    ar: Mapped[float] = mapped_column(Float, index=True)
    sigma_pre: Mapped[float] = mapped_column(Float, index=True)
    sigma_hat: Mapped[float | None] = mapped_column(Float, nullable=True, index=True)
    z_post: Mapped[float | None] = mapped_column(Float, nullable=True, index=True)
    z_pre: Mapped[float | None] = mapped_column(Float, nullable=True)
    z_hold: Mapped[float | None] = mapped_column(Float, nullable=True)
    z_big: Mapped[float | None] = mapped_column(Float, nullable=True)
    impact_bin: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    impact_score: Mapped[float | None] = mapped_column(Float, nullable=True, index=True)
    overlap_count: Mapped[int] = mapped_column(Integer, default=0)
    echo_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    premove_penalty: Mapped[float | None] = mapped_column(Float, nullable=True)
    confidence: Mapped[float | None] = mapped_column(Float, nullable=True, index=True)
    label_v2: Mapped[int] = mapped_column(Integer, index=True)
    is_hi_conf: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    leakage_postmove: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    is_repost: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    is_overlapped: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    price_source: Mapped[str] = mapped_column(String, default="mid", index=True)
    created_at: Mapped[DateTime] = mapped_column(DateTime, index=True)
    updated_at: Mapped[DateTime] = mapped_column(DateTime, index=True)


class ExpReturnBucketStatsV2Model(Base):
    __tablename__ = "exp_return_bucket_stats_v2"
    __table_args__ = (
        UniqueConstraint(
            "symbol",
            "horizon",
            "bucket_b",
            "bucket_v",
            "bucket_s",
            "lookback_start",
            "lookback_end",
            name="uq_exp_return_bucket_stats_v2",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    symbol: Mapped[str] = mapped_column(String, index=True)
    horizon: Mapped[str] = mapped_column(String, index=True)
    bucket_b: Mapped[int] = mapped_column(Integer, index=True)
    bucket_v: Mapped[int] = mapped_column(Integer, index=True)
    bucket_s: Mapped[int] = mapped_column(Integer, index=True)
    lookback_start: Mapped[DateTime] = mapped_column(DateTime, index=True)
    lookback_end: Mapped[DateTime] = mapped_column(DateTime, index=True)
    n: Mapped[int] = mapped_column(Integer)
    mean_return: Mapped[float | None] = mapped_column(Float, nullable=True)
    median_return: Mapped[float | None] = mapped_column(Float, nullable=True)
    updated_at: Mapped[DateTime] = mapped_column(DateTime, index=True)


class EventFactorScoreV2Model(Base):
    __tablename__ = "event_factor_score_v2"
    __table_args__ = (
        UniqueConstraint(
            "event_id",
            "symbol",
            "factor_name",
            "model_name",
            name="uq_event_factor_score_v2",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    event_id: Mapped[str] = mapped_column(String, index=True)
    symbol: Mapped[str] = mapped_column(String, index=True)
    factor_name: Mapped[str] = mapped_column(String, index=True)
    p_entail_bull: Mapped[float] = mapped_column(Float)
    p_entail_bear: Mapped[float] = mapped_column(Float)
    factor_score: Mapped[float] = mapped_column(Float, index=True)
    factor_conf: Mapped[float] = mapped_column(Float, index=True)
    model_name: Mapped[str] = mapped_column(String, index=True)
    computed_at: Mapped[DateTime] = mapped_column(DateTime, index=True)


class ModelPredV2Model(Base):
    __tablename__ = "model_pred_v2"
    __table_args__ = (
        UniqueConstraint(
            "run_id",
            "event_id",
            "symbol",
            "horizon",
            name="uq_model_pred_v2",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    run_id: Mapped[str] = mapped_column(String, index=True)
    event_id: Mapped[str] = mapped_column(String, index=True)
    symbol: Mapped[str] = mapped_column(String, index=True)
    horizon: Mapped[str] = mapped_column(String, index=True)
    p_move: Mapped[float] = mapped_column(Float)
    p_up_given_move: Mapped[float] = mapped_column(Float)
    p_up: Mapped[float] = mapped_column(Float)
    p_down: Mapped[float] = mapped_column(Float)
    p_hold: Mapped[float] = mapped_column(Float)
    decision: Mapped[int] = mapped_column(Integer, index=True)
    threshold_set_id: Mapped[str] = mapped_column(String, index=True)
    model_version: Mapped[str] = mapped_column(String, index=True)
    is_calibrated: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    created_at: Mapped[DateTime] = mapped_column(DateTime, index=True)


class GateRunV2Model(Base):
    __tablename__ = "gate_run_v2"
    __table_args__ = (
        UniqueConstraint(
            "run_id",
            "symbol",
            "horizon",
            name="uq_gate_run_v2",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    run_id: Mapped[str] = mapped_column(String, index=True)
    symbol: Mapped[str] = mapped_column(String, index=True)
    horizon: Mapped[str] = mapped_column(String, index=True)
    period_start: Mapped[DateTime] = mapped_column(DateTime, index=True)
    period_end: Mapped[DateTime] = mapped_column(DateTime, index=True)
    market_pass: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    leakage_pass: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    supervised_pass_shadow: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    supervised_pass_prod: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    baseline_pass: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    utility_pass: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    overall_pass_prod: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    metrics_json: Mapped[object | None] = mapped_column(JSON, nullable=True)
    winner_model_version: Mapped[str | None] = mapped_column(String, nullable=True, index=True)
    created_at: Mapped[DateTime] = mapped_column(DateTime, index=True)


class NewsAnnotationModel(Base):
    __tablename__ = "news_annotations"

    annotation_id: Mapped[str] = mapped_column(String, primary_key=True)
    target_level: Mapped[str] = mapped_column(String, index=True)
    target_id: Mapped[str] = mapped_column(String, index=True)
    payload_json: Mapped[object] = mapped_column(JSON)
    author_id: Mapped[str | None] = mapped_column(String, nullable=True, index=True)
    reason: Mapped[str | None] = mapped_column(String, nullable=True)
    version: Mapped[str] = mapped_column(String, index=True)
    created_at: Mapped[DateTime] = mapped_column(DateTime, index=True)


class NewsGoldLabelModel(Base):
    __tablename__ = "news_gold_labels"
    __table_args__ = (
        UniqueConstraint(
            "target_type",
            "target_id",
            "source",
            "label_schema_version",
            name="uq_news_gold_label_target_source_schema",
        ),
    )

    label_id: Mapped[str] = mapped_column(String, primary_key=True)
    target_type: Mapped[str] = mapped_column(String, index=True)
    target_id: Mapped[str] = mapped_column(String, index=True)
    event_family: Mapped[str | None] = mapped_column(String, nullable=True, index=True)
    factors_json: Mapped[object | None] = mapped_column(JSON, nullable=True)
    phase: Mapped[str | None] = mapped_column(String, nullable=True, index=True)
    direction_label: Mapped[str | None] = mapped_column(String, nullable=True, index=True)
    quality: Mapped[str] = mapped_column(String, index=True)
    source: Mapped[str] = mapped_column(String, index=True)
    label_schema_version: Mapped[str] = mapped_column(String, index=True)
    confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    meta_json: Mapped[object | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[DateTime] = mapped_column(DateTime, index=True)


class NewsUnmatchedGoldModel(Base):
    __tablename__ = "news_unmatched_gold"
    __table_args__ = (
        UniqueConstraint(
            "source",
            "gold_id",
            name="uq_news_unmatched_gold_source_id",
        ),
    )

    unmatched_id: Mapped[str] = mapped_column(String, primary_key=True)
    source: Mapped[str] = mapped_column(String, index=True)
    gold_id: Mapped[str] = mapped_column(String, index=True)
    published_at_utc: Mapped[DateTime | None] = mapped_column(DateTime, nullable=True, index=True)
    commodity_json: Mapped[object | None] = mapped_column(JSON, nullable=True)
    event_family: Mapped[str | None] = mapped_column(String, nullable=True, index=True)
    confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    match_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    reason: Mapped[str | None] = mapped_column(String, nullable=True)
    payload_json: Mapped[object | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[DateTime] = mapped_column(DateTime, index=True)


class NewsModelEvalRecordModel(Base):
    __tablename__ = "news_model_eval_records"

    run_id: Mapped[str] = mapped_column(String, primary_key=True)
    model_version: Mapped[str] = mapped_column(String, index=True)
    dataset_version: Mapped[str | None] = mapped_column(String, nullable=True, index=True)
    horizon: Mapped[str | None] = mapped_column(String, nullable=True, index=True)
    supervised_metrics_json: Mapped[object | None] = mapped_column(JSON, nullable=True)
    market_metrics_json: Mapped[object | None] = mapped_column(JSON, nullable=True)
    pass_supervised: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    pass_market: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    promotion_state: Mapped[str] = mapped_column(String, index=True)
    gate_details_json: Mapped[object | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[DateTime] = mapped_column(DateTime, index=True)
