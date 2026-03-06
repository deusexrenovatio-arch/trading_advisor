from __future__ import annotations

import argparse
import os
import subprocess
import sys
import tempfile
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

import run_o1_execution_hypothesis_program as o1prog

MONTH_CODES = tuple('FGHJKMNQUVXZ')


def subprocess_env() -> dict[str, str]:
    env = os.environ.copy()
    src_path = str(o1prog.REPO_ROOT / 'src')
    repo_path = str(o1prog.REPO_ROOT)
    current = str(env.get('PYTHONPATH', '') or '')
    env['PYTHONPATH'] = os.pathsep.join([part for part in [src_path, repo_path, current] if part])
    return env


def parse_csv_tokens(raw: str | None) -> list[str]:
    if not raw:
        return []
    return [token.strip().upper() for token in str(raw).split(',') if token.strip()]


def generate_candidate_secids(roots: list[str], years: list[int], month_codes: list[str]) -> list[str]:
    secids = {
        f"{root}{month}{str(year)[-1]}"
        for root in roots
        for year in years
        for month in month_codes
    }
    return sorted(secids)


def summarize_prefetch(report: dict[str, Any], roots: list[str], years: list[int], month_codes: list[str], command: list[str]) -> dict[str, Any]:
    payload_sizes = dict(report.get('payload_sizes') or {})
    active = {
        secid: sizes
        for secid, sizes in payload_sizes.items()
        if any(int(value) > 0 for value in (sizes or {}).values())
    }
    inactive = sorted(secid for secid in payload_sizes if secid not in active)
    by_root: dict[str, dict[str, Any]] = {}
    for root in roots:
        root_rows = {secid: sizes for secid, sizes in active.items() if str(secid).startswith(root)}
        by_root[root] = {
            'active_secids': sorted(root_rows),
            'active_secids_count': len(root_rows),
            'has_coverage': bool(root_rows),
        }
    return {
        'generated_at': datetime.now(UTC).isoformat(),
        'mode': 'historical_front_contract_prefetch',
        'period': {
            'start_date': report.get('period', {}).get('start_date'),
            'end_date': report.get('period', {}).get('end_date'),
        },
        'roots': roots,
        'generated_years': years,
        'month_codes': month_codes,
        'candidate_secids_total': len(payload_sizes),
        'active_secids_total': len(active),
        'inactive_secids_total': len(inactive),
        'active_roots_total': sum(1 for item in by_root.values() if item['has_coverage']),
        'by_root': by_root,
        'cache': report.get('cache') or {},
        'reporting_instruments': report.get('reporting_instruments') or [],
        'active_payload_sizes': active,
        'inactive_secids_sample': inactive[:200],
        'raw_prefetch_report': report,
        'command': command,
    }


def chunked(items: list[str], size: int) -> list[list[str]]:
    batch_size = max(int(size), 1)
    return [items[index:index + batch_size] for index in range(0, len(items), batch_size)]


def merge_raw_reports(reports: list[dict[str, Any]], start_date: date, end_date: date) -> dict[str, Any]:
    payload_sizes: dict[str, Any] = {}
    cache_totals: dict[str, float] = {}
    reporting: set[str] = set()
    for report in reports:
        payload_sizes.update(report.get('payload_sizes') or {})
        for key, value in (report.get('cache') or {}).items():
            try:
                cache_totals[key] = float(cache_totals.get(key, 0.0)) + float(value or 0.0)
            except (TypeError, ValueError):
                continue
        for item in report.get('reporting_instruments') or []:
            reporting.add(str(item))
    normalized_cache: dict[str, Any] = {}
    for key, value in cache_totals.items():
        normalized_cache[key] = int(value) if float(value).is_integer() else float(value)
    return {
        'period': {
            'start_date': start_date.isoformat(),
            'end_date': end_date.isoformat(),
        },
        'payload_sizes': payload_sizes,
        'cache': normalized_cache,
        'reporting_instruments': sorted(reporting),
        'batch_count': len(reports),
    }


def build_command(reference: dict[str, Any], instruments: list[str], start_date: date, end_date: date, refresh_cache: bool, out_json: Path) -> list[str]:
    tuning = reference['tuning_points']
    period = reference['period']
    args = [
        sys.executable,
        str(o1prog.REPO_ROOT / 'scripts' / 'run_morning_plan_walk_forward.py'),
    ]
    for instrument in instruments:
        args.extend(['--instrument', instrument])
    args.extend(
        [
            '--instrument-mode',
            'fixed',
            '--start-date',
            start_date.isoformat(),
            '--end-date',
            end_date.isoformat(),
            '--decision-times',
            ','.join(period['decision_times']),
            '--train-days',
            str(tuning['train_days']),
            '--test-days',
            str(tuning['test_days']),
            '--step-days',
            str(tuning['step_days']),
            '--embargo-days',
            str(tuning['embargo_days']),
            '--purge-days',
            str(tuning['purge_days']),
            '--cache-db',
            str(reference['cache']['cache_db']),
            '--prefetch-only',
            '--out-json',
            str(out_json),
        ]
    )
    if refresh_cache:
        args.append('--refresh-cache')
    return args


def main() -> None:
    parser = argparse.ArgumentParser(description='Prefetch historical front-contract data for 2023-2024 using generated secid candidates.')
    parser.add_argument('--reference-artifact', default=str(o1prog.DEFAULT_REFERENCE))
    parser.add_argument('--roots', default='')
    parser.add_argument('--start-date', default='2023-01-01')
    parser.add_argument('--end-date', default='2024-12-31')
    parser.add_argument('--year-padding', type=int, default=1, help='Extra years before/after the requested range.')
    parser.add_argument('--month-codes', default='')
    parser.add_argument('--batch-size', type=int, default=120)
    parser.add_argument('--refresh-cache', action='store_true')
    parser.add_argument('--out-json', default=str(o1prog.ARTIFACT_DIR / 'wf_goal_v6_historical_front_contract_prefetch_2023_2024_20260306.json'))
    args = parser.parse_args()

    reference = o1prog.load_json(Path(args.reference_artifact))
    roots = parse_csv_tokens(args.roots) or [str(item).upper() for item in reference.get('reporting_instruments') or []]
    start = date.fromisoformat(args.start_date)
    end = date.fromisoformat(args.end_date)
    years = list(range(start.year - max(int(args.year_padding), 0), end.year + max(int(args.year_padding), 0) + 1))
    month_codes = parse_csv_tokens(args.month_codes) or list(MONTH_CODES)
    instruments = generate_candidate_secids(roots, years, month_codes)

    out_json = Path(args.out_json)
    batches = chunked(instruments, int(args.batch_size))
    raw_reports: list[dict[str, Any]] = []
    commands: list[list[str]] = []
    total_batches = len(batches)
    for index, batch in enumerate(batches, start=1):
        with tempfile.NamedTemporaryFile(suffix='.json', delete=False) as handle:
            raw_path = Path(handle.name)
        command = build_command(reference, batch, start, end, bool(args.refresh_cache), raw_path)
        print(f'prefetch batch {index}/{total_batches}: instruments={len(batch)}')
        try:
            subprocess.run(command, cwd=o1prog.REPO_ROOT, check=True, env=subprocess_env())
            raw_report = o1prog.load_json(raw_path)
        finally:
            if raw_path.exists():
                raw_path.unlink()
        raw_reports.append(raw_report)
        commands.append(command)
    merged_report = merge_raw_reports(raw_reports, start, end)
    summary = summarize_prefetch(merged_report, roots, years, month_codes, commands[0] if commands else [])
    summary['commands'] = commands
    summary['raw_prefetch_report'] = merged_report
    o1prog.write_json(out_json, summary)


if __name__ == '__main__':
    main()
