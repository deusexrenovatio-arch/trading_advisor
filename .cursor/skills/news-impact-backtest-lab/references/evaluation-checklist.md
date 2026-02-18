# Evaluation checklist

## Dataset
- Canonical entity IDs present.
- Published timestamp in UTC.
- No duplicate `(news_id, entity_id, published_at)` keys.

## Labels
- Horizon set documented (`1h`, `4h`, `1d`, `5d` or project specific).
- Neutral epsilon documented and versioned.
- Signed returns persisted alongside class labels.

## Split and leakage
- Time-based split only.
- Embargo window configured.
- Validation and test windows do not overlap.

## Metrics
- Accuracy, precision, recall, F1 by class and horizon.
- Brier score and reliability bins.
- Coverage and abstain rate.
- Slice metrics by commodity, tag, and source.

## Promotion gates
- Thresholds per horizon declared before run.
- Pass or fail decision logged with reasons.
- Full config, code version, and input hash stored.

