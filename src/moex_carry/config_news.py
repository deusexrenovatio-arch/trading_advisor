from __future__ import annotations

from pydantic import BaseModel, Field


class NewsFilterConfig(BaseModel):
    live_ingest_enabled: bool = False
    live_db_url: str = "sqlite:///./data/news_livecheck_ng.db"
    live_feed_path: str = "./data/output/news_live/live_news_discovery.csv"
    live_min_impact_score: float = 0.35
    live_min_confidence: float = 0.9
    live_max_items: int = 200
    lookback_minutes: int = 180
    block_severity_threshold: str = "high"
    reduce_severity_threshold: str = "medium"
    sources: list[str] = []
    enforce_source_allowlist: bool = False


class NewsIngestConfig(BaseModel):
    class CommodityProfile(BaseModel):
        ticker: str
        name: str
        gdelt_query: str
        newsapi_query: str | None = None
        rss_urls: list[str] = []
        price_source: str = "yfinance"
        price_symbol: str = ""
        price_interval: str = "1d"

    enabled: bool = False
    rss_urls: list[str] = []
    max_items_per_run: int = 100
    gdelt_enabled: bool = True
    gdelt_max_records_per_call: int = 250
    gdelt_min_request_interval_sec: float = 5.2
    gdelt_request_timeout_sec: int = 40
    gdelt_backfill_max_pages_per_window: int = 10
    newsapi_enabled: bool = False
    newsapi_base_url: str = "https://newsapi.org/v2/everything"
    newsapi_api_key_env: str = "NEWSAPI_API_KEY"
    newsapi_api_key: str | None = None
    newsapi_language: str = "en"
    newsapi_sort_by: str = "publishedAt"
    newsapi_domains: list[str] = []
    newsapi_max_records_per_call: int = 100
    newsapi_backfill_max_pages_per_window: int = 2
    newsapi_request_timeout_sec: int = 30
    newsapi_daily_limit: int = 100
    newsapi_daily_state_path: str = "./data/state/newsapi_usage.json"
    backfill_start_date: str = "2018-01-01"
    backfill_chunk_days: int = 7
    backfill_max_windows_per_commodity: int = 0
    backfill_shock_bar_minutes: int = 0
    backfill_window_order: str = "chronological"
    qc_min_news_per_ticker: int = 500
    qc_min_price_points_per_ticker: int = 500
    commodity_profiles: list[CommodityProfile] = Field(
        default_factory=lambda: [
            NewsIngestConfig.CommodityProfile(
                ticker="BRN",
                name="Brent Crude Oil",
                gdelt_query='("brent crude" OR "brent oil" OR "ice brent" OR opec)',
                newsapi_query='("brent" OR "crude oil" OR opec)',
                rss_urls=["https://news.google.com/rss/search?q=Brent+crude+oil+futures"],
                price_source="yfinance",
                price_symbol="BZ=F",
                price_interval="1d",
            ),
            NewsIngestConfig.CommodityProfile(
                ticker="NG_US",
                name="US Natural Gas",
                gdelt_query='("natural gas" OR "henry hub" OR "us lng")',
                newsapi_query='("natural gas" OR "henry hub" OR lng)',
                rss_urls=["https://news.google.com/rss/search?q=henry+hub+natural+gas+futures"],
                price_source="yfinance",
                price_symbol="NG=F",
                price_interval="1d",
            ),
            NewsIngestConfig.CommodityProfile(
                ticker="GOLD",
                name="Gold",
                gdelt_query='("gold futures" OR "gold price" OR bullion)',
                newsapi_query='("gold" OR bullion OR "safe haven")',
                rss_urls=["https://news.google.com/rss/search?q=gold+futures"],
                price_source="yfinance",
                price_symbol="GC=F",
                price_interval="1d",
            ),
            NewsIngestConfig.CommodityProfile(
                ticker="SILVER",
                name="Silver",
                gdelt_query='("silver futures" OR "silver price" OR "industrial silver" OR "solar demand silver")',
                newsapi_query='("silver" OR xag OR "solar demand" OR "silver mine")',
                rss_urls=["https://news.google.com/rss/search?q=silver+futures"],
                price_source="yfinance",
                price_symbol="SI=F",
                price_interval="1d",
            ),
            NewsIngestConfig.CommodityProfile(
                ticker="PLATINUM",
                name="Platinum",
                gdelt_query='("platinum futures" OR "platinum price" OR "south africa platinum" OR "pgm supply")',
                newsapi_query='("platinum" OR xpt OR pgm OR autocatalyst)',
                rss_urls=["https://news.google.com/rss/search?q=platinum+futures"],
                price_source="yfinance",
                price_symbol="PL=F",
                price_interval="1d",
            ),
            NewsIngestConfig.CommodityProfile(
                ticker="PALLADIUM",
                name="Palladium",
                gdelt_query='("palladium futures" OR "palladium price" OR "russian palladium" OR "autocatalyst demand")',
                newsapi_query='("palladium" OR xpd OR "russian supply" OR autocatalyst)',
                rss_urls=["https://news.google.com/rss/search?q=palladium+futures"],
                price_source="yfinance",
                price_symbol="PA=F",
                price_interval="1d",
            ),
            NewsIngestConfig.CommodityProfile(
                ticker="COPPER",
                name="Copper",
                gdelt_query='("copper futures" OR "copper price" OR codelco OR "mine strike" OR smelter)',
                newsapi_query='("copper" OR codelco OR escondida OR "mine strike" OR smelter)',
                rss_urls=["https://news.google.com/rss/search?q=copper+futures"],
                price_source="yfinance",
                price_symbol="HG=F",
                price_interval="1d",
            ),
            NewsIngestConfig.CommodityProfile(
                ticker="ALUMINUM",
                name="Aluminum",
                gdelt_query='("aluminum futures" OR "aluminium price" OR bauxite OR alumina OR "smelter outage")',
                newsapi_query='("aluminum" OR "aluminium" OR bauxite OR alumina OR smelter)',
                rss_urls=["https://news.google.com/rss/search?q=aluminum+futures"],
                price_source="yfinance",
                price_symbol="",
                price_interval="1d",
            ),
            NewsIngestConfig.CommodityProfile(
                ticker="NICKEL",
                name="Nickel",
                gdelt_query='("nickel futures" OR "nickel price" OR "indonesia nickel" OR "ore export" OR "stainless steel demand")',
                newsapi_query='("nickel" OR "indonesia nickel" OR "ore ban" OR "stainless steel demand")',
                rss_urls=["https://news.google.com/rss/search?q=nickel+futures"],
                price_source="yfinance",
                price_symbol="",
                price_interval="1d",
            ),
            NewsIngestConfig.CommodityProfile(
                ticker="ZINC",
                name="Zinc",
                gdelt_query='("zinc futures" OR "zinc price" OR "zinc smelter" OR "mine disruption")',
                newsapi_query='("zinc" OR "zinc smelter" OR "mine disruption" OR "treatment charges")',
                rss_urls=["https://news.google.com/rss/search?q=zinc+futures"],
                price_source="yfinance",
                price_symbol="",
                price_interval="1d",
            ),
            NewsIngestConfig.CommodityProfile(
                ticker="WHEAT",
                name="Wheat",
                gdelt_query='("wheat futures" OR "black sea wheat" OR "grain corridor" OR "wheat drought" OR "crop condition")',
                newsapi_query='("wheat" OR "black sea wheat" OR "grain corridor" OR "wheat crop")',
                rss_urls=["https://news.google.com/rss/search?q=wheat+futures"],
                price_source="yfinance",
                price_symbol="ZW=F",
                price_interval="1d",
            ),
            NewsIngestConfig.CommodityProfile(
                ticker="SUGAR",
                name="Sugar",
                gdelt_query='("sugar futures" OR "raw sugar" OR "brazil sugar cane" OR "india sugar export" OR "ethanol parity")',
                newsapi_query='("sugar" OR "raw sugar" OR "brazil sugar" OR "ethanol parity")',
                rss_urls=["https://news.google.com/rss/search?q=sugar+futures"],
                price_source="yfinance",
                price_symbol="SB=F",
                price_interval="1d",
            ),
            NewsIngestConfig.CommodityProfile(
                ticker="COFFEE",
                name="Coffee",
                gdelt_query='("coffee futures" OR arabica OR robusta OR "brazil coffee crop" OR "coffee frost")',
                newsapi_query='("coffee" OR arabica OR robusta OR "coffee crop" OR frost)',
                rss_urls=["https://news.google.com/rss/search?q=coffee+futures"],
                price_source="yfinance",
                price_symbol="KC=F",
                price_interval="1d",
            ),
            NewsIngestConfig.CommodityProfile(
                ticker="COCOA",
                name="Cocoa",
                gdelt_query='("cocoa futures" OR "ivory coast cocoa" OR "ghana cocoa" OR harmattan OR "crop disease")',
                newsapi_query='("cocoa" OR "ivory coast" OR ghana OR harmattan OR "crop disease")',
                rss_urls=["https://news.google.com/rss/search?q=cocoa+futures"],
                price_source="yfinance",
                price_symbol="CC=F",
                price_interval="1d",
            ),
            NewsIngestConfig.CommodityProfile(
                ticker="ORANGE",
                name="Orange Juice",
                gdelt_query='("orange juice futures" OR fcoj OR "citrus greening" OR "florida orange crop")',
                newsapi_query='("orange juice" OR fcoj OR "citrus greening" OR "orange crop")',
                rss_urls=["https://news.google.com/rss/search?q=orange+juice+futures"],
                price_source="yfinance",
                price_symbol="OJ=F",
                price_interval="1d",
            ),
        ]
    )


class NewsEventsConfig(BaseModel):
    enabled: bool = True
    cluster_version: str = "det-v1"
    cluster_window_hours: int = 48
    similarity_threshold: float = 0.35
    resolve_after_hours: int = 72
    anchor_link_enabled: bool = False
    anchor_seed_enabled: bool = False
    anchor_seed_padding_days: int = 7
    anchor_match_window_minutes: int = 60
    anchor_request_timeout_sec: int = 30
    anchor_user_agent: str = "moex-carry/1.0"
    anchor_bsee_url: str = "https://www.bsee.gov/newsroom"
    anchor_suez_url: str = "https://www.suezcanal.gov.eg"
    anchor_panama_url: str = "https://pancanal.com/en/notices/"
    anchor_nhc_url: str = "https://www.nhc.noaa.gov"
    anchor_nws_url: str = "https://www.weather.gov"
    anchor_ukmto_url: str = "https://www.ukmto.org"
    anchor_fred_release_url: str = "https://api.stlouisfed.org/fred/releases/dates"
    anchor_fred_api_key_env: str = "FRED_API_KEY"
    anchor_fred_release_ids: list[int] = []
    anchor_cluster_version: str = "anchor-v1"
    anchor_episode_seed_enabled: bool = False
    anchor_episode_sources: list[str] = []
    anchor_episode_cluster_version: str = "anchor-episode-v1"
    anchor_episode_match_window_minutes: int = 180


class NewsLlmConfig(BaseModel):
    enabled: bool = False
    full_pass_enabled: bool = False
    provider: str = "openai"
    model_id: str = "gpt-5-mini"
    api_base_url: str = "https://api.openai.com/v1"
    api_key_env: str = "OPENAI_API_KEY"
    prompt_version: str = "news-v1"
    label_version: str = "v1"
    max_items_per_run: int = 50
    max_input_chars: int = 6000
    max_output_tokens: int = 512
    max_calls_per_run: int = 0
    max_prompt_tokens_per_run: int = 0
    max_completion_tokens_per_run: int = 0
    max_total_tokens_per_run: int = 0
    request_timeout_sec: int = 45
    max_retries: int = 2
    retry_backoff_sec: float = 1.5
    temperature: float = 0.0
    top_impact_priority: bool = True
    min_impact_for_priority: float = 0.0


class NewsModelsConfig(BaseModel):
    enabled_models: list[str] = ["finbert", "nli"]
    primary_model: str = "finbert"
    finbert_model_name: str = "ProsusAI/finbert"
    nli_model_name: str = "facebook/bart-large-mnli"
    model_version: str = "v1"
    multilingual_nli_model_name: str = "MoritzLaurer/mDeBERTa-v3-base-mnli-xnli"
    inference_batch_size: int = 16
    inference_text_max_chars: int = 2000
    inference_thread_cap: int = 0
    calibration_mode: str = "none"
    calibration_min_train_samples: int = 30
    epsilon_default: float = 0.0005
    horizons: list[str] = ["5m", "1h", "4h", "1d", "5d"]
    target_mode_default: str = "close"
    promotion_min_accuracy: float = 0.70
    promotion_min_coverage: float = 0.20
    promotion_max_brier: float = 0.25
    promotion_min_sample_count: int = 30
    promotion_min_ticker_stability: float = 0.55
    decision_weight_rollout_mode: str = "limited"
    decision_weight_min_sample_size: int = 3
    decision_weight_limited_max_deviation: float = 0.25
    decision_weight_signal_threshold: float = 0.12
    decision_weight_min_impact: float = 0.6
    decision_weight_reduce_factor: float = 0.5
    decision_weight_boost_factor: float = 1.1
    decision_weight_quality_horizon: str = "1h"
    decision_weight_quality_max_age_hours: int = 72
