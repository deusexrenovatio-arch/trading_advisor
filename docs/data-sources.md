# Data Sources and Storage

## Overview
This project consumes market data from MOEX ISS and QUIK. Data is normalized
into a consistent schema, cached for low-latency access, and stored for
reproducible backtests.

## MOEX ISS ingestion
- Source: HTTP API (MOEX ISS endpoints).
- Normalization: convert timestamps to ISO-8601, align price/volume fields, and
  tag each row with source metadata.
- Caching: store latest snapshot in a local cache with a short TTL.
- Historical storage: persist raw responses and normalized tables for audit.
- Marketdata fields used when available:
  - Stocks: bid, ask, last, volume.
  - Futures: bid, ask, last, volume, open interest.
- Fallbacks: if bid/ask is missing, use last/close as mid; if open interest is
  missing, liquidity gates rely on volume only.

## QUIK ingestion
- Source: broker terminal or gateway.
- Normalization: map QUIK fields to canonical instrument, price, volume, and
  order book levels.
- Caching: keep the last known snapshot per instrument in memory.
- Historical storage: append to immutable time-partitioned tables.

## Snapshot IDs and hashes
Every decision must reference immutable snapshot IDs for reproducibility.

Snapshot ID format:
- `snap-{source}-{instrument}-{yyyyMMddHHmm}-{hash8}`

Hash inputs:
- Source name, query params, time window, and raw payload checksum.

Example:
- `snap-iss-RIH5-202501211200-acde1234`

## Decision log linkage
- `decision_log.input_snapshots[].snapshot_id` must include all sources used.
- Each snapshot includes `hash` for content verification.
- `decision_view.links.input_snapshots` may include the same IDs for UI drilldown.
