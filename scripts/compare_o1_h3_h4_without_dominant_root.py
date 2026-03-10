from __future__ import annotations

import argparse
import copy
import subprocess
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import run_o1_execution_hypothesis_program as o1prog

SCENARIOS: dict[str, dict[str, Any]] = {
    'O1_SUBSET': {
        'label': 'O1 without dominant root',
        'overrides': {},
    },
    'H3B_SL_3P0_SUBSET': {
        'label': 'H3 stop widening without dominant root',
        'overrides': {'sl_rr': 3.0},
    },
    'H4A_CAP_OFF_SUBSET': {
        'label': 'H4 RR-cap removal without dominant root',
        'overrides': {'max_profit_rr': 0.0},
    },
}


def detect_dominant_root(report: dict[str, Any]) -> str:
    by_instrument = (report.get('overall_test_summary') or {}).get('by_instrument') or {}
    rows = sorted(
        ((str(root), abs(float(payload.get('net_ticks_sum', 0.0)))) for root, payload in by_instrument.items()),
        key=lambda item: item[1],
        reverse=True,
    )
    if not rows:
        raise ValueError('dominant_root_not_found')
    return rows[0][0]


def filtered_reference(reference: dict[str, Any], excluded_roots: set[str]) -> dict[str, Any]:
    filtered = copy.deepcopy(reference)
    instruments = [secid for secid in filtered['instruments'] if str(secid)[:2].upper() not in excluded_roots]
    if not instruments:
        raise ValueError('filtered_instrument_list_empty')
    filtered['instruments'] = instruments
    filtered['reporting_instruments'] = [root for root in filtered.get('reporting_instruments') or [] if str(root).upper() not in excluded_roots]
    return filtered


def top_instruments(report: dict[str, Any], limit: int = 10) -> list[dict[str, Any]]:
    by_instrument = (report.get('overall_test_summary') or {}).get('by_instrument') or {}
    rows = []
    for root, payload in by_instrument.items():
        if not isinstance(payload, dict):
            continue
        rows.append(
            {
                'root': str(root),
                'net_ticks_sum': float(payload.get('net_ticks_sum', 0.0) or 0.0),
                'count': int(payload.get('count', 0) or 0),
                'win_rate_net': float(payload.get('win_rate_net', 0.0) or 0.0),
            }
        )
    rows.sort(key=lambda item: abs(float(item['net_ticks_sum'])), reverse=True)
    return rows[:limit]


def run_report(reference: dict[str, Any], overrides: dict[str, Any]) -> tuple[dict[str, Any], list[str]]:
    command = o1prog.build_command(reference, overrides)
    with tempfile.NamedTemporaryFile(suffix='.json', delete=False) as handle:
        temp_path = Path(handle.name)
    command.extend(['--out-json', str(temp_path)])
    try:
        subprocess.run(command, cwd=o1prog.REPO_ROOT, check=True)
        report = o1prog.load_json(temp_path)
    finally:
        if temp_path.exists():
            temp_path.unlink()
    return report, command


def main() -> None:
    parser = argparse.ArgumentParser(description='Compare O1 vs H3 vs H4 after removing the dominant O1 revenue root.')
    parser.add_argument('--reference-artifact', default=str(o1prog.DEFAULT_REFERENCE))
    parser.add_argument('--exclude-root', default='')
    parser.add_argument('--out-json', default=str(o1prog.ARTIFACT_DIR / 'wf_goal_v6_h24_o1_h3_h4_compare_without_dominant_root_20260306.json'))
    args = parser.parse_args()

    reference_path = Path(args.reference_artifact)
    reference = o1prog.load_json(reference_path)
    dominant_root = str(args.exclude_root).strip().upper() or detect_dominant_root(reference)
    filtered = filtered_reference(reference, {dominant_root})

    scenario_reports: dict[str, dict[str, Any]] = {}
    scenario_metrics: dict[str, dict[str, Any]] = {}
    scenario_commands: dict[str, list[str]] = {}
    for scenario_id, spec in SCENARIOS.items():
        report, command = run_report(filtered, dict(spec['overrides']))
        scenario_reports[scenario_id] = report
        scenario_metrics[scenario_id] = {
            **o1prog.metrics_from_report(report),
            'top_instruments': top_instruments(report),
            'acceptance': report.get('acceptance') or {},
        }
        scenario_commands[scenario_id] = command

    baseline_metrics = scenario_metrics['O1_SUBSET']
    deltas = {
        scenario_id: o1prog.metrics_delta(metrics, baseline_metrics)
        for scenario_id, metrics in scenario_metrics.items()
        if scenario_id != 'O1_SUBSET'
    }

    payload = {
        'generated_at': datetime.now(UTC).isoformat(),
        'reference_artifact': o1prog.relpath(reference_path),
        'excluded_root': dominant_root,
        'excluded_root_o1_net_ticks': float(
            ((reference.get('overall_test_summary') or {}).get('by_instrument') or {}).get(dominant_root, {}).get('net_ticks_sum', 0.0)
        ),
        'remaining_instruments': filtered['instruments'],
        'comparison': {
            scenario_id: {
                'label': spec['label'],
                'metrics': scenario_metrics[scenario_id],
                'command': scenario_commands[scenario_id],
            }
            for scenario_id, spec in SCENARIOS.items()
        },
        'delta_vs_o1_subset': deltas,
    }
    o1prog.write_json(Path(args.out_json), payload)


if __name__ == '__main__':
    main()
