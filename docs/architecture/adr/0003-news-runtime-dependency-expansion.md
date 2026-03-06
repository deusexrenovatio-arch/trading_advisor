# 0003 News Runtime Dependency Expansion

## Status
Accepted

## Date
2026-03-06

## Context
The unified news runtime adds live ingestion, article extraction, causal scoring, multi-commodity linking, benchmarking, and market validation flows.
Those capabilities require dependencies that were not part of the original trading-only baseline in `pyproject.toml`.
The repository governance policy requires an ADR whenever dependency manifests change so reviewers can validate why each new package exists and what operational risk it introduces.

## Decision
Accept the following Python runtime dependencies for the news module expansion:
- `feedparser` for RSS/Atom feed ingestion.
- `trafilatura` and `beautifulsoup4` for article extraction and HTML cleanup.
- `dateparser` for source timestamp normalization across publishers.
- `transformers`, `tokenizers`, `datasets`, `onnxruntime`, and `optimum` for local text modeling, inference packaging, and evaluation workflows.
- `scikit-learn` for deterministic benchmark and labeling support in news research flows.
- `yfinance` for external market data comparisons used by news validation and research utilities.

## Consequences
- Pros:
  - the news pipeline can run end-to-end without ad hoc external notebooks or manual preprocessing;
  - dependency intent is explicit for review, operations, and future cleanup;
  - CI governance checks can validate the manifest change against a durable design record.
- Cons:
  - a larger Python environment increases install time and supply-chain surface area;
  - ML dependencies raise local and CI resource usage;
  - future upgrades need tighter monitoring for compatibility and runtime performance.

## Alternatives Considered
1. Keep the news pipeline behind optional out-of-repo tooling.
  - Rejected: production and validation flows would drift from the versioned repository contract.
2. Use hosted APIs for all extraction and modeling steps.
  - Rejected: lower determinism, higher recurring cost, and weaker offline reproducibility.
3. Delay dependency formalization until after rollout.
  - Rejected: violates repository governance and hides operational risk during review.

## Validation and Rollout
- Gate commands:
  - `python scripts/validate_dependency_decisions.py`
  - `python scripts/validate_quality_scorecards.py`
- Operational rollout:
  - merge through PR into `main`;
  - enable `news_root_cycle` with discovery feed routed to Telegram and gate in controlled rollout mode.
