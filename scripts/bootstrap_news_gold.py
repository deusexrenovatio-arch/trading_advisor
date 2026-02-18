from __future__ import annotations

import argparse
import json
import re
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

import requests


ALLOWED_DIRECTIONS = {"positive", "negative", "neutral", "uncertain"}
EIA_ARCHIVE_URL = "https://www.eia.gov/naturalgas/weekly/includes/archive.php"


@dataclass(frozen=True)
class PullResult:
    source_id: str
    rows: list[dict[str, Any]]
    notes: list[str]


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _normalize_text(value: Any) -> str:
    return str(value or "").strip()


def _normalize_datetime_utc(value: Any) -> str | None:
    raw = _normalize_text(value)
    if not raw:
        return None
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", raw):
        return f"{raw}T00:00:00Z"
    candidate = raw.replace("Z", "+00:00")
    try:
        dt = datetime.fromisoformat(candidate)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    else:
        dt = dt.astimezone(timezone.utc)
    return dt.replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _to_jsonable(value: Any) -> Any:
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    if isinstance(value, list):
        return [_to_jsonable(item) for item in value]
    if isinstance(value, dict):
        return {str(key): _to_jsonable(item) for key, item in value.items()}
    return str(value)


def _write_jsonl(path: Path, rows: Iterable[dict[str, Any]]) -> int:
    path.parent.mkdir(parents=True, exist_ok=True)
    count = 0
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(_to_jsonable(row), ensure_ascii=False) + "\n")
            count += 1
    return count


def _parse_years(raw: str) -> list[int]:
    years: list[int] = []
    for item in str(raw or "").split(","):
        value = item.strip()
        if not value:
            continue
        if "-" in value:
            parts = value.split("-", 1)
            try:
                start = int(parts[0].strip())
                end = int(parts[1].strip())
            except ValueError:
                continue
            if end < start:
                start, end = end, start
            years.extend(range(start, end + 1))
            continue
        try:
            years.append(int(value))
        except ValueError:
            continue
    unique = sorted({year for year in years if 1990 <= year <= 2100})
    return unique


def _label_from_score(score: float, threshold: float = 0.05) -> str:
    if score > threshold:
        return "positive"
    if score < -threshold:
        return "negative"
    return "neutral"


def _confidence_from_score(score: float) -> float:
    value = min(max(abs(float(score)), 0.0), 1.0)
    return round(value, 6)


def pull_hf_fiqa(*, max_rows: int = 0) -> PullResult:
    from datasets import load_dataset  # local import to keep script lightweight when unused

    dataset = load_dataset("TheFinAI/fiqa-sentiment-classification")
    rows: list[dict[str, Any]] = []
    notes: list[str] = []
    for split_name, split_rows in dataset.items():
        for idx, item in enumerate(split_rows):
            text = _normalize_text(item.get("sentence"))
            if not text:
                continue
            score = float(item.get("score") or 0.0)
            label = _label_from_score(score)
            rows.append(
                {
                    "gold_id": f"hf_fiqa:{split_name}:{idx}",
                    "source_id": "hf_fiqa",
                    "source_url": "https://huggingface.co/datasets/TheFinAI/fiqa-sentiment-classification",
                    "split": split_name,
                    "published_at_utc": None,
                    "language": "en",
                    "text": text,
                    "label_direction": label,
                    "confidence": _confidence_from_score(score),
                    "commodity": [],
                    "news_type": ["MARKET"],
                    "label_source": "human_external",
                    "provenance": {
                        "dataset": "TheFinAI/fiqa-sentiment-classification",
                        "record_id": item.get("_id"),
                        "target": item.get("target"),
                        "aspect": item.get("aspect"),
                        "score": score,
                        "type": item.get("type"),
                    },
                }
            )
            if max_rows > 0 and len(rows) >= max_rows:
                notes.append(f"truncated to max_rows={max_rows}")
                return PullResult(source_id="hf_fiqa", rows=rows, notes=notes)
    return PullResult(source_id="hf_fiqa", rows=rows, notes=notes)


def pull_hf_phrasebank(*, max_rows: int = 0) -> PullResult:
    from datasets import load_dataset

    dataset = load_dataset("warwickai/financial_phrasebank_mirror")
    label_map = {0: "negative", 1: "neutral", 2: "positive"}
    rows: list[dict[str, Any]] = []
    notes: list[str] = []
    for split_name, split_rows in dataset.items():
        for idx, item in enumerate(split_rows):
            text = _normalize_text(item.get("sentence"))
            if not text:
                continue
            raw_label = item.get("label")
            label = label_map.get(int(raw_label)) if raw_label is not None else None
            if label is None:
                continue
            rows.append(
                {
                    "gold_id": f"hf_phrasebank:{split_name}:{idx}",
                    "source_id": "hf_phrasebank_mirror",
                    "source_url": "https://huggingface.co/datasets/warwickai/financial_phrasebank_mirror",
                    "split": split_name,
                    "published_at_utc": None,
                    "language": "en",
                    "text": text,
                    "label_direction": label,
                    "confidence": 0.85,
                    "commodity": [],
                    "news_type": ["MARKET"],
                    "label_source": "human_external",
                    "provenance": {
                        "dataset": "warwickai/financial_phrasebank_mirror",
                        "label_raw": int(raw_label),
                    },
                }
            )
            if max_rows > 0 and len(rows) >= max_rows:
                notes.append(f"truncated to max_rows={max_rows}")
                return PullResult(source_id="hf_phrasebank_mirror", rows=rows, notes=notes)
    return PullResult(source_id="hf_phrasebank_mirror", rows=rows, notes=notes)


def pull_hf_nifty(*, max_rows: int = 0) -> PullResult:
    from datasets import load_dataset

    dataset = load_dataset("raeidsaqur/NIFTY", name="nifty-lm")
    label_map = {"Rise": "positive", "Fall": "negative", "Neutral": "neutral"}
    rows: list[dict[str, Any]] = []
    notes: list[str] = []
    for split_name, split_rows in dataset.items():
        for idx, item in enumerate(split_rows):
            text = _normalize_text(item.get("news"))
            if not text:
                text = _normalize_text(item.get("context"))
            if not text:
                continue
            raw_label = _normalize_text(item.get("label"))
            label = label_map.get(raw_label)
            if label is None:
                continue
            published = _normalize_datetime_utc(item.get("date"))
            rows.append(
                {
                    "gold_id": f"hf_nifty:{split_name}:{idx}",
                    "source_id": "hf_nifty",
                    "source_url": "https://huggingface.co/datasets/raeidsaqur/NIFTY",
                    "split": split_name,
                    "published_at_utc": published,
                    "language": "en",
                    "text": text,
                    "label_direction": label,
                    "confidence": 0.8,
                    "commodity": [],
                    "news_type": ["MARKET"],
                    "label_source": "human_external",
                    "provenance": {
                        "dataset": "raeidsaqur/NIFTY",
                        "id": item.get("id"),
                        "label_raw": raw_label,
                        "pct_change": item.get("pct_change"),
                    },
                }
            )
            if max_rows > 0 and len(rows) >= max_rows:
                notes.append(f"truncated to max_rows={max_rows}")
                return PullResult(source_id="hf_nifty", rows=rows, notes=notes)
    return PullResult(source_id="hf_nifty", rows=rows, notes=notes)


def _fetch_eia_archive_links(*, years: set[int], timeout_sec: int) -> list[str]:
    response = requests.get(EIA_ARCHIVE_URL, timeout=timeout_sec)
    response.raise_for_status()
    html = response.text
    href_pattern = re.compile(r'href="([^"]*archivenew_ngwu/20\d{2}/\d{2}_\d{2}/?)"', re.IGNORECASE)
    links: list[str] = []
    seen: set[str] = set()
    for match in href_pattern.findall(html):
        link = str(match).strip()
        if not link:
            continue
        if link.startswith("/"):
            link = f"https://www.eia.gov{link}"
        if not link.endswith("/"):
            link = f"{link}/"
        year_match = re.search(r"/(20\d{2})/\d{2}_\d{2}/?$", link)
        if year_match is None:
            continue
        year = int(year_match.group(1))
        if years and year not in years:
            continue
        if link in seen:
            continue
        seen.add(link)
        links.append(link)
    return links


def _extract_eia_henry_hub_sentence(page_text: str) -> tuple[str | None, float | None, float | None]:
    text = " ".join(_normalize_text(page_text).split())
    patterns = [
        re.compile(
            r"(Henry Hub spot price[^.]{0,360}?from \$?([0-9]+(?:\.[0-9]+)?)[^.]{0,220}?to \$?([0-9]+(?:\.[0-9]+)?)[^.]*\.)",
            re.IGNORECASE,
        ),
        re.compile(
            r"(at the Henry Hub[^.]{0,360}?from \$?([0-9]+(?:\.[0-9]+)?)[^.]{0,220}?to \$?([0-9]+(?:\.[0-9]+)?)[^.]*\.)",
            re.IGNORECASE,
        ),
    ]
    for pattern in patterns:
        match = pattern.search(text)
        if match is None:
            continue
        sentence = _normalize_text(match.group(1))
        try:
            from_price = float(match.group(2))
            to_price = float(match.group(3))
        except (TypeError, ValueError):
            return sentence, None, None
        return sentence, from_price, to_price
    return None, None, None


def pull_eia_ng_archive(
    *,
    years: set[int],
    max_pages: int = 0,
    timeout_sec: int = 30,
    sleep_sec: float = 0.15,
) -> PullResult:
    links = _fetch_eia_archive_links(years=years, timeout_sec=timeout_sec)
    rows: list[dict[str, Any]] = []
    notes: list[str] = []
    if max_pages > 0:
        links = links[:max_pages]
        notes.append(f"truncated links to max_pages={max_pages}")

    for idx, url in enumerate(links):
        try:
            response = requests.get(url, timeout=timeout_sec)
            response.raise_for_status()
            html = response.text
        except Exception as exc:
            notes.append(f"failed_fetch:{url}:{type(exc).__name__}")
            continue
        sentence, from_price, to_price = _extract_eia_henry_hub_sentence(html)
        if not sentence or from_price is None or to_price is None:
            continue

        if to_price > from_price:
            direction = "positive"
        elif to_price < from_price:
            direction = "negative"
        else:
            direction = "neutral"

        move_pct = abs(to_price - from_price) / max(abs(from_price), 1e-9)
        confidence = round(min(max(move_pct * 8.0, 0.15), 0.95), 6)

        release_match = re.search(r"/(20\d{2})/(\d{2})_(\d{2})/?$", url)
        published_at = None
        if release_match:
            year, month, day = release_match.group(1), release_match.group(2), release_match.group(3)
            published_at = f"{year}-{month}-{day}T00:00:00Z"

        rows.append(
            {
                "gold_id": f"eia_ng_archive:{idx}",
                "source_id": "eia_ng_archive",
                "source_url": url,
                "split": "archive",
                "published_at_utc": published_at,
                "language": "en",
                "text": sentence,
                "label_direction": direction,
                "confidence": confidence,
                "commodity": ["NG_US"],
                "news_type": ["MARKET", "INVENTORY"],
                "label_source": "heuristic_external",
                "provenance": {
                    "dataset": "eia_natural_gas_weekly_archive",
                    "from_price": from_price,
                    "to_price": to_price,
                    "move_pct": round(move_pct, 6),
                },
            }
        )
        if sleep_sec > 0:
            time.sleep(sleep_sec)
    return PullResult(source_id="eia_ng_archive", rows=rows, notes=notes)


def build_qc_report(rows: list[dict[str, Any]]) -> dict[str, Any]:
    total = len(rows)
    ids = [str(row.get("gold_id") or "").strip() for row in rows]
    id_set = set(ids)
    duplicate_ids = max(total - len(id_set), 0)

    missing_text = 0
    invalid_direction = 0
    missing_provenance = 0
    source_counts: dict[str, int] = {}
    commodity_counts: dict[str, int] = {}
    direction_counts: dict[str, int] = {}
    for row in rows:
        source = str(row.get("source_id") or "").strip() or "unknown"
        source_counts[source] = int(source_counts.get(source, 0)) + 1
        direction = str(row.get("label_direction") or "").strip().lower()
        direction_counts[direction] = int(direction_counts.get(direction, 0)) + 1
        if direction not in ALLOWED_DIRECTIONS:
            invalid_direction += 1
        text = _normalize_text(row.get("text"))
        if not text:
            missing_text += 1
        if not isinstance(row.get("provenance"), dict):
            missing_provenance += 1
        commodities = row.get("commodity")
        if isinstance(commodities, list):
            for item in commodities:
                ticker = str(item or "").strip().upper()
                if ticker:
                    commodity_counts[ticker] = int(commodity_counts.get(ticker, 0)) + 1

    pass_gates = (
        duplicate_ids == 0
        and missing_text == 0
        and invalid_direction == 0
        and missing_provenance == 0
    )
    return {
        "generated_at_utc": _utc_now_iso(),
        "total_rows": total,
        "source_counts": source_counts,
        "commodity_counts": commodity_counts,
        "direction_counts": direction_counts,
        "gates": {
            "source_document_uniqueness": {"passed": duplicate_ids == 0, "duplicate_ids": duplicate_ids},
            "required_text_present": {"passed": missing_text == 0, "missing_text": missing_text},
            "direction_valid": {"passed": invalid_direction == 0, "invalid_direction": invalid_direction},
            "provenance_required": {"passed": missing_provenance == 0, "missing_provenance": missing_provenance},
        },
        "passed": pass_gates,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Pull external gold labels for news-impact research.")
    parser.add_argument("--output-dir", type=str, default="data/external/news_gold")
    parser.add_argument("--years", type=str, default="2020-2026", help="Years for EIA NG archive, e.g. 2022-2026")
    parser.add_argument("--eia-max-pages", type=int, default=0, help="Optional cap for EIA pages (0 = no cap)")
    parser.add_argument("--hf-max-rows", type=int, default=0, help="Optional cap per HF source (0 = no cap)")
    parser.add_argument("--skip-eia", action="store_true")
    parser.add_argument("--skip-hf", action="store_true")
    args = parser.parse_args()

    out_dir = Path(args.output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    run_started = _utc_now_iso()

    results: list[PullResult] = []
    errors: list[str] = []
    years = set(_parse_years(args.years))

    if not args.skip_hf:
        for pull_fn in (pull_hf_fiqa, pull_hf_phrasebank, pull_hf_nifty):
            try:
                results.append(pull_fn(max_rows=max(int(args.hf_max_rows), 0)))
            except Exception as exc:
                errors.append(f"{pull_fn.__name__}:{type(exc).__name__}:{exc}")

    if not args.skip_eia:
        try:
            results.append(
                pull_eia_ng_archive(
                    years=years,
                    max_pages=max(int(args.eia_max_pages), 0),
                )
            )
        except Exception as exc:
            errors.append(f"pull_eia_ng_archive:{type(exc).__name__}:{exc}")

    all_rows: list[dict[str, Any]] = []
    per_source_files: list[dict[str, Any]] = []
    for result in results:
        source_file = out_dir / f"{result.source_id}.jsonl"
        written = _write_jsonl(source_file, result.rows)
        all_rows.extend(result.rows)
        per_source_files.append(
            {
                "source_id": result.source_id,
                "rows": written,
                "path": str(source_file),
                "notes": result.notes,
            }
        )

    combined_file = out_dir / "news_gold_seed.jsonl"
    combined_written = _write_jsonl(combined_file, all_rows)
    qc_report = build_qc_report(all_rows)
    qc_path = out_dir / "qc_report.json"
    qc_path.write_text(json.dumps(qc_report, ensure_ascii=False, indent=2), encoding="utf-8")

    manifest = {
        "run_started_at_utc": run_started,
        "run_finished_at_utc": _utc_now_iso(),
        "output_dir": str(out_dir),
        "combined_rows": combined_written,
        "combined_path": str(combined_file),
        "sources": per_source_files,
        "qc_report_path": str(qc_path),
        "errors": errors,
    }
    manifest_path = out_dir / "manifest.json"
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")

    print(json.dumps(manifest, ensure_ascii=False, indent=2))
    print()
    print(json.dumps(qc_report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()

