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
