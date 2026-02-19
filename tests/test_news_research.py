from __future__ import annotations

from datetime import datetime, timedelta

from moex_carry.config import AppSettings, DataConfig, DatabaseConfig
from moex_carry.news.research import compare_news_models, run_news_backtest
from moex_carry.storage import models as db_models
from moex_carry.storage.db import create_engine_from_settings, create_session_factory, init_db


def _build_settings(tmp_path):
    return AppSettings(
        data=DataConfig(data_dir=str(tmp_path)),
        database=DatabaseConfig(url=f"sqlite:///{tmp_path}/news-research.db"),
    )


def _probs_for_direction(direction: str) -> tuple[float, float, float]:
    if direction == "up":
        return 0.82, 0.08, 0.10
    if direction == "down":
        return 0.08, 0.82, 0.10
    return 0.20, 0.20, 0.60


def _opposite_direction(direction: str) -> str:
    if direction == "up":
        return "down"
    if direction == "down":
        return "up"
    return "up"


def _label_for_return(value: float, epsilon: float) -> str:
    if value > epsilon:
        return "up"
    if value < -epsilon:
        return "down"
    return "neutral"


def _seed_news_research_fixture(session, *, epsilon: float) -> tuple[datetime, datetime]:
    base = datetime(2025, 1, 1, 9, 0, 0)
    returns = [0.02, -0.015, 0.0, 0.03, -0.02, 0.01]

    for idx, ret in enumerate(returns):
        news_ts = base + timedelta(hours=idx * 2)
        news_id = f"news-r-{idx + 1}"
        actual_direction = _label_for_return(ret, epsilon)

        start_price = 100.0 + float(idx)
        end_price = start_price * (1.0 + ret)

        session.add(
            db_models.NewsItemModel(
                news_id=news_id,
                source="fixture",
                url=f"https://example.com/{news_id}",
                title=f"Fixture {idx + 1}",
                content=f"Synthetic news {idx + 1}",
                language="en",
                published_at=news_ts,
                ingested_at=news_ts,
                hash=f"hash-{news_id}",
            )
        )
        session.add(
            db_models.NewsEntityLinkModel(
                news_id=news_id,
                entity_type="instrument",
                entity_id="AAA",
                ticker="AAA",
                link_confidence=0.9,
                link_stage="dictionary",
            )
        )

        finbert_prob_up, finbert_prob_down, finbert_prob_neutral = _probs_for_direction(actual_direction)
        nli_direction = _opposite_direction(actual_direction)
        nli_prob_up, nli_prob_down, nli_prob_neutral = _probs_for_direction(nli_direction)

        session.add(
            db_models.NewsImpactScoreModel(
                news_id=news_id,
                model_id="finbert",
                model_version="v1",
                direction=actual_direction,
                prob_up=finbert_prob_up,
                prob_down=finbert_prob_down,
                prob_neutral=finbert_prob_neutral,
                impact_score=0.75,
                calibrated=False,
                inference_ts=news_ts,
            )
        )
        session.add(
            db_models.NewsImpactScoreModel(
                news_id=news_id,
                model_id="nli",
                model_version="v1",
                direction=nli_direction,
                prob_up=nli_prob_up,
                prob_down=nli_prob_down,
                prob_neutral=nli_prob_neutral,
                impact_score=0.75,
                calibrated=False,
                inference_ts=news_ts + timedelta(seconds=1),
            )
        )

        session.add(
            db_models.QuoteModel(
                secid="AAA",
                timestamp=news_ts,
                bid=start_price - 0.1,
                ask=start_price + 0.1,
                last=start_price,
                volume=1_000.0 + idx,
            )
        )
        session.add(
            db_models.QuoteModel(
                secid="AAA",
                timestamp=news_ts + timedelta(hours=1),
                bid=end_price - 0.1,
                ask=end_price + 0.1,
                last=end_price,
                volume=1_200.0 + idx,
            )
        )

    session.commit()
    period_from = base - timedelta(hours=1)
    period_to = base + timedelta(hours=len(returns) * 2)
    return period_from, period_to


def _seed_external_gold_event_labels(session, *, opposite: bool) -> None:
    news_rows = (
        session.query(db_models.NewsItemModel)
        .order_by(db_models.NewsItemModel.published_at.asc())
        .all()
    )
    score_by_news = {
        str(row.news_id): str(row.direction or "neutral").strip().lower()
        for row in session.query(db_models.NewsImpactScoreModel)
        .filter(db_models.NewsImpactScoreModel.model_id == "finbert")
        .all()
    }
    for idx, item in enumerate(news_rows, start=1):
        event_id = f"evt-r-{idx}"
        pred = score_by_news.get(str(item.news_id), "neutral")
        if pred == "up":
            direction = "positive"
        elif pred == "down":
            direction = "negative"
        else:
            direction = "neutral"
        if opposite:
            direction = "negative" if direction == "positive" else "positive"

        session.add(
            db_models.NewsEventModel(
                event_id=event_id,
                event_first_published_at_utc=item.published_at,
                event_first_ingested_at_utc=item.ingested_at,
                event_last_published_at_utc=item.published_at,
                event_status="resolved",
                canonical_summary=f"Event for {item.news_id}",
                canonical_mechanism="Fixture mechanism",
                cluster_version="det-v1",
                created_at=item.published_at,
                updated_at=item.published_at,
            )
        )
        session.add(
            db_models.NewsEventItemModel(
                event_id=event_id,
                news_id=item.news_id,
                link_role="primary",
                similarity_score=1.0,
                added_at=item.published_at,
            )
        )
        session.add(
            db_models.NewsLabelModel(
                label_id=f"lbl-ext-{idx}",
                target_level="event",
                target_id=event_id,
                commodity_json=["AAA"],
                market_scope="futures",
                instrument_candidates_json=[],
                relevance=1.0,
                news_type_json=["MARKET"],
                direction=direction,
                magnitude=1.0,
                lag_bucket="short",
                confidence=1.0,
                uncertainty_type="none",
                geo_scope="US",
                evidence_json={"seed": "test"},
                label_source="external_gold",
                label_version="gold-v1",
                model_version="fixture",
                prompt_version="fixture",
                created_at=item.published_at,
            )
        )
    session.commit()


def test_run_news_backtest_walk_forward_protocol_with_calibration(tmp_path):
    epsilon = 0.005
    settings = _build_settings(tmp_path)
    engine = create_engine_from_settings(settings)
    init_db(engine)
    session_factory = create_session_factory(engine)

    with session_factory() as session:
        period_from, period_to = _seed_news_research_fixture(session, epsilon=epsilon)
        report = run_news_backtest(
            session,
            model_id="finbert",
            horizon="1h",
            period_from=period_from,
            period_to=period_to,
            epsilon=epsilon,
            folds=3,
            embargo_minutes=0,
            walk_forward=True,
            calibration_mode="isotonic",
            calibration_min_train_samples=1,
        )

    assert report["model_id"] == "finbert"
    assert report["protocol"]["mode"] == "walk_forward"
    assert int(report["protocol"]["folds"]) == 3
    assert report["protocol"]["calibration_mode"] == "isotonic"
    assert report["total_samples"] >= report["sample_count"] > 0
    assert isinstance(report["fold_reports"], list)
    assert len(report["fold_reports"]) >= 1
    assert all("calibration_mode" in fold for fold in report["fold_reports"])
    assert all("calibration_applied" in fold for fold in report["fold_reports"])
    assert int(report["metrics"]["sample_count"]) == int(report["sample_count"])
    assert "AAA" in report["slices"]["ticker"]
    assert "UNKNOWN" in report["slices"]["event_family"]


def test_compare_news_models_promote_when_quality_gate_passes(tmp_path):
    epsilon = 0.005
    settings = _build_settings(tmp_path)
    engine = create_engine_from_settings(settings)
    init_db(engine)
    session_factory = create_session_factory(engine)

    with session_factory() as session:
        period_from, period_to = _seed_news_research_fixture(session, epsilon=epsilon)
        _seed_external_gold_event_labels(session, opposite=False)
        comparison = compare_news_models(
            session,
            model_ids=["finbert", "nli"],
            horizon="1h",
            period_from=period_from,
            period_to=period_to,
            epsilon=epsilon,
            folds=3,
            embargo_minutes=0,
            walk_forward=True,
            calibration_mode="none",
            promotion_min_accuracy=0.90,
            promotion_min_coverage=0.10,
            promotion_max_brier=1.0,
            promotion_min_sample_count=1,
            promotion_min_ticker_stability=0.10,
            promotion_require_baseline_superiority=False,
        )

    assert comparison["protocol"]["mode"] == "walk_forward"
    assert int(comparison["protocol"]["folds"]) == 3
    assert comparison["winner"]["model_id"] == "finbert"
    assert comparison["audit"]["decision"] == "promote"
    assert bool(comparison["audit"]["quality_gate"]["pass"]) is True
    assert len(comparison.get("baselines") or []) >= 4
    assert "time_shift_placebo" in (comparison.get("ablations") or {})
    assert "permutation_placebo" in (comparison.get("ablations") or {})


def test_compare_news_models_hold_when_quality_gate_fails(tmp_path):
    epsilon = 0.005
    settings = _build_settings(tmp_path)
    engine = create_engine_from_settings(settings)
    init_db(engine)
    session_factory = create_session_factory(engine)

    with session_factory() as session:
        period_from, period_to = _seed_news_research_fixture(session, epsilon=epsilon)
        comparison = compare_news_models(
            session,
            model_ids=["finbert", "nli"],
            horizon="1h",
            period_from=period_from,
            period_to=period_to,
            epsilon=epsilon,
            folds=3,
            embargo_minutes=0,
            walk_forward=True,
            calibration_mode="none",
            promotion_min_accuracy=1.10,
            promotion_min_coverage=0.10,
            promotion_max_brier=1.0,
            promotion_min_sample_count=1,
            promotion_min_ticker_stability=0.10,
        )

    assert comparison["winner"]["model_id"] == "finbert"
    assert comparison["audit"]["decision"] == "hold"
    assert bool(comparison["audit"]["quality_gate"]["pass"]) is False


def test_compare_news_models_holds_when_supervised_gate_fails(tmp_path):
    epsilon = 0.005
    settings = _build_settings(tmp_path)
    engine = create_engine_from_settings(settings)
    init_db(engine)
    session_factory = create_session_factory(engine)

    with session_factory() as session:
        period_from, period_to = _seed_news_research_fixture(session, epsilon=epsilon)
        _seed_external_gold_event_labels(session, opposite=True)
        comparison = compare_news_models(
            session,
            model_ids=["finbert", "nli"],
            horizon="1h",
            period_from=period_from,
            period_to=period_to,
            epsilon=epsilon,
            folds=3,
            embargo_minutes=0,
            walk_forward=True,
            calibration_mode="none",
            promotion_min_accuracy=0.30,
            promotion_min_coverage=0.10,
            promotion_max_brier=1.0,
            promotion_min_sample_count=1,
            promotion_min_ticker_stability=0.10,
        )

        eval_rows = session.query(db_models.NewsModelEvalRecordModel).all()

    assert comparison["winner"]["model_id"] == "finbert"
    assert comparison["audit"]["decision"] == "hold"
    quality_gate = comparison["audit"]["quality_gate"]
    assert bool(quality_gate["market_gate"]["pass"]) is True
    assert bool(quality_gate["supervised_gate"]["pass"]) is False
    assert bool(quality_gate["pass"]) is False
    assert len(eval_rows) >= 1


def test_run_news_backtest_supports_5m_horizon(tmp_path):
    epsilon = 0.005
    settings = _build_settings(tmp_path)
    engine = create_engine_from_settings(settings)
    init_db(engine)
    session_factory = create_session_factory(engine)

    with session_factory() as session:
        period_from, period_to = _seed_news_research_fixture(session, epsilon=epsilon)
        report = run_news_backtest(
            session,
            model_id="finbert",
            horizon="5m",
            period_from=period_from,
            period_to=period_to,
            epsilon=epsilon,
            folds=2,
            embargo_minutes=0,
            walk_forward=True,
            calibration_mode="none",
            calibration_min_train_samples=1,
        )

    assert report["protocol"]["horizon_minutes"] == 5


def test_run_news_backtest_target_mode_v2_uses_event_target_rows(tmp_path):
    settings = _build_settings(tmp_path)
    engine = create_engine_from_settings(settings)
    init_db(engine)
    session_factory = create_session_factory(engine)
    base = datetime(2025, 6, 1, 10, 0, 0)

    with session_factory() as session:
        for idx in range(3):
            event_id = f"evt-v2-{idx+1}"
            news_id = f"news-v2-{idx+1}"
            t0 = base + timedelta(hours=idx * 2)
            t1 = t0 + timedelta(hours=1)
            direction = "up" if idx != 1 else "down"
            label = 1 if direction == "up" else -1

            session.add(
                db_models.NewsEventModel(
                    event_id=event_id,
                    event_first_published_at_utc=t0,
                    event_first_ingested_at_utc=t0,
                    event_last_published_at_utc=t0,
                    event_status="active",
                    canonical_summary=f"event-{idx+1}",
                    canonical_mechanism="scheduled_anchor|event_family=NG_STORAGE_EIA",
                    cluster_version="det-v1",
                    created_at=t0,
                    updated_at=t0,
                )
            )
            session.add(
                db_models.NewsItemModel(
                    news_id=news_id,
                    source="fixture",
                    url=f"https://example.com/{news_id}",
                    title=f"v2 sample {idx+1}",
                    content="sample",
                    language="en",
                    published_at=t0,
                    ingested_at=t0,
                    hash=f"hash-{news_id}",
                )
            )
            session.add(
                db_models.NewsEventItemModel(
                    event_id=event_id,
                    news_id=news_id,
                    link_role="primary",
                    similarity_score=1.0,
                    added_at=t0,
                )
            )
            session.add(
                db_models.NewsLabelModel(
                    label_id=f"lbl-v2-{idx+1}",
                    target_level="event",
                    target_id=event_id,
                    commodity_json=["NG_US"],
                    market_scope="futures",
                    instrument_candidates_json=[],
                    relevance=1.0,
                    news_type_json=["NG_STORAGE_EIA"],
                    direction="positive" if label > 0 else "negative",
                    magnitude=0.8,
                    lag_bucket="short",
                    confidence=0.9,
                    uncertainty_type="none",
                    geo_scope="US",
                    evidence_json={},
                    label_source="rules",
                    label_version="v1",
                    model_version=None,
                    prompt_version=None,
                    created_at=t0,
                )
            )
            session.add(
                db_models.NewsImpactScoreModel(
                    news_id=news_id,
                    target_level=None,
                    target_id=None,
                    model_id="finbert",
                    model_version="v1",
                    direction=direction,
                    prob_up=0.8 if direction == "up" else 0.1,
                    prob_down=0.8 if direction == "down" else 0.1,
                    prob_neutral=0.1,
                    impact_score=0.7,
                    calibrated=False,
                    inference_ts=t0,
                )
            )
            session.add(
                db_models.EventTargetV2Model(
                    event_id=event_id,
                    symbol="NG_US",
                    horizon="1h",
                    t_pub=t0,
                    t_anchor=t0,
                    t0=t0,
                    t1=t1,
                    p0=100.0,
                    p1=101.0 if label > 0 else 99.0,
                    r_raw=0.01 if label > 0 else -0.01,
                    r_exp=0.0,
                    ar=0.01 if label > 0 else -0.01,
                    sigma_pre=0.003,
                    label_v2=label,
                    is_hi_conf=True,
                    leakage_postmove=False,
                    is_repost=False,
                    is_overlapped=False,
                    price_source="mid",
                    created_at=t0,
                    updated_at=t0,
                )
            )
        session.commit()

        report = run_news_backtest(
            session,
            model_id="finbert",
            horizon="1h",
            period_from=base - timedelta(hours=1),
            period_to=base + timedelta(hours=8),
            epsilon=0.0005,
            folds=2,
            embargo_minutes=0,
            walk_forward=True,
            calibration_mode="none",
            calibration_min_train_samples=1,
            target_mode="v2",
        )

    assert report["protocol"]["target_mode"] == "v2"
    assert report["protocol"]["decision_policy"] == "two_stage"
    assert "utility" in report
    assert "bootstrap_ci_95" in report["utility"]
    assert int(report["sample_count"]) >= 1
    assert float(report["metrics"]["accuracy"]) >= 0.0


def test_compare_news_models_v2_exposes_utility_gate(tmp_path):
    settings = _build_settings(tmp_path)
    engine = create_engine_from_settings(settings)
    init_db(engine)
    session_factory = create_session_factory(engine)
    base = datetime(2025, 7, 10, 9, 0, 0)

    with session_factory() as session:
        for idx in range(4):
            event_id = f"evt-v2-cmp-{idx+1}"
            news_id = f"news-v2-cmp-{idx+1}"
            t0 = base + timedelta(hours=idx * 2)
            t1 = t0 + timedelta(hours=1)
            direction = "up" if idx % 2 == 0 else "down"
            label = 1 if direction == "up" else -1

            session.add(
                db_models.NewsEventModel(
                    event_id=event_id,
                    event_first_published_at_utc=t0,
                    event_first_ingested_at_utc=t0,
                    event_last_published_at_utc=t0,
                    event_status="active",
                    canonical_summary=f"event-cmp-{idx+1}",
                    canonical_mechanism="scheduled_anchor|event_family=NG_STORAGE_EIA",
                    cluster_version="det-v1",
                    created_at=t0,
                    updated_at=t0,
                )
            )
            session.add(
                db_models.NewsItemModel(
                    news_id=news_id,
                    source="fixture",
                    url=f"https://example.com/{news_id}",
                    title=f"v2 cmp {idx+1}",
                    content="sample",
                    language="en",
                    published_at=t0,
                    ingested_at=t0,
                    hash=f"hash-{news_id}",
                )
            )
            session.add(
                db_models.NewsEventItemModel(
                    event_id=event_id,
                    news_id=news_id,
                    link_role="primary",
                    similarity_score=1.0,
                    added_at=t0,
                )
            )
            session.add(
                db_models.NewsLabelModel(
                    label_id=f"lbl-v2-cmp-{idx+1}",
                    target_level="event",
                    target_id=event_id,
                    commodity_json=["NG_US"],
                    market_scope="futures",
                    instrument_candidates_json=[],
                    relevance=1.0,
                    news_type_json=["NG_STORAGE_EIA"],
                    direction="positive" if label > 0 else "negative",
                    magnitude=0.8,
                    lag_bucket="short",
                    confidence=0.9,
                    uncertainty_type="none",
                    geo_scope="US",
                    evidence_json={},
                    label_source="rules",
                    label_version="v1",
                    model_version=None,
                    prompt_version=None,
                    created_at=t0,
                )
            )
            session.add(
                db_models.NewsImpactScoreModel(
                    news_id=news_id,
                    target_level=None,
                    target_id=None,
                    model_id="finbert",
                    model_version="v1",
                    direction=direction,
                    prob_up=0.8 if direction == "up" else 0.1,
                    prob_down=0.8 if direction == "down" else 0.1,
                    prob_neutral=0.1,
                    impact_score=0.7,
                    calibrated=False,
                    inference_ts=t0,
                )
            )
            session.add(
                db_models.NewsImpactScoreModel(
                    news_id=news_id,
                    target_level=None,
                    target_id=None,
                    model_id="nli",
                    model_version="v1",
                    direction="down" if direction == "up" else "up",
                    prob_up=0.2 if direction == "up" else 0.7,
                    prob_down=0.7 if direction == "up" else 0.2,
                    prob_neutral=0.1,
                    impact_score=0.6,
                    calibrated=False,
                    inference_ts=t0 + timedelta(seconds=1),
                )
            )
            session.add(
                db_models.EventTargetV2Model(
                    event_id=event_id,
                    symbol="NG_US",
                    horizon="1h",
                    t_pub=t0,
                    t_anchor=t0,
                    t0=t0,
                    t1=t1,
                    p0=100.0,
                    p1=101.0 if label > 0 else 99.0,
                    r_raw=0.01 if label > 0 else -0.01,
                    r_exp=0.0,
                    ar=0.01 if label > 0 else -0.01,
                    sigma_pre=0.003,
                    label_v2=label,
                    is_hi_conf=True,
                    leakage_postmove=False,
                    is_repost=False,
                    is_overlapped=False,
                    price_source="mid",
                    created_at=t0,
                    updated_at=t0,
                )
            )
        session.commit()

        comparison = compare_news_models(
            session,
            model_ids=["finbert", "nli"],
            horizon="1h",
            period_from=base - timedelta(hours=1),
            period_to=base + timedelta(hours=10),
            epsilon=0.0005,
            folds=2,
            embargo_minutes=0,
            walk_forward=True,
            calibration_mode="none",
            target_mode="v2",
            promotion_min_accuracy=0.0,
            promotion_min_coverage=0.0,
            promotion_max_brier=1.0,
            promotion_min_sample_count=1,
            promotion_min_ticker_stability=0.0,
            promotion_require_baseline_superiority=False,
            promotion_utility_min_trades=1,
            promotion_utility_max_drawdown=1.0,
        )

    assert comparison["protocol"]["target_mode"] == "v2"
    assert "utility_gate" in comparison["audit"]["quality_gate"]
    assert "utility" in comparison["reports"][0]
