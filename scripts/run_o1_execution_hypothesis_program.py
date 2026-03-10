from __future__ import annotations

import argparse
import json
import math
import statistics
import subprocess
import sys
import tempfile
import time
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_REFERENCE = REPO_ROOT / 'artifacts' / 'research' / 'wf_goal_v6_h24_causal_rerun_execution_fixed_O1_limitfallback10m1t_frontnearest_seed124_20260305.json'
DEFAULT_OUTPUT = REPO_ROOT / 'artifacts' / 'research' / 'wf_goal_v6_h24_o1_execution_hypothesis_ladder_20260306.json'
ARTIFACT_DIR = REPO_ROOT / 'artifacts' / 'research'
FLOAT_TOLERANCE = 1e-9
FAMILY_ORDER = ('H0', 'H1', 'H2', 'H3', 'H4', 'H5')
COMPARISON_KEYS = (
    'setups_total',
    'filled_trades',
    'fill_rate',
    'tp_rate',
    'sl_rate',
    'exit_rate',
    'win_rate_net',
    'expectancy_net_ticks',
    'net_ticks_sum',
    'trades_per_week',
    'concentration_top_share',
)
EXECUTION_DEFAULTS: dict[str, Any] = {
    'break_even_rr': 0.0,
    'break_even_buffer_ticks': 0,
    'tp_rr': 0.0,
    'sl_rr': 0.0,
    'max_holding_minutes': 0,
    'max_profit_rr': 0.0,
    'max_profit_ticks': 0,
    'trail_activation_rr': 0.0,
    'trail_offset_ticks': 0,
    'same_bar_policy': 'sl_first',
    'limit_entry_improve_ticks': 0,
    'limit_fallback_to_market_minutes': 0,
    'limit_fallback_slip_ticks': 0,
    'tp_cost_mult': 1.0,
    'sl_cost_mult': 1.0,
    'exit_cost_mult': 1.0,
}


@dataclass(frozen=True)
class Hypothesis:
    hypothesis_id: str
    family: str
    label: str
    mechanism_note: str
    overrides: dict[str, Any] = field(default_factory=dict)
    group: str | None = None
    sensitivity_only: bool = False


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding='utf-8-sig'))


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')


def relpath(path: Path) -> str:
    try:
        return str(path.relative_to(REPO_ROOT)).replace('\\', '/')
    except ValueError:
        return str(path)


def normalize_execution_policy(reference: dict[str, Any]) -> dict[str, Any]:
    normalized = dict(EXECUTION_DEFAULTS)
    normalized.update(reference.get('tuning_points', {}).get('execution_policy') or {})
    return normalized


def metrics_from_report(report: dict[str, Any]) -> dict[str, Any]:
    summary = report.get('overall_test_summary') or {}
    acceptance = report.get('acceptance') or {}
    return {
        'setups_total': int(summary.get('setups_total', 0) or 0),
        'filled_trades': int(summary.get('filled_trades', 0) or 0),
        'fill_rate': float(summary.get('fill_rate', 0.0) or 0.0),
        'tp_rate': float(summary.get('tp_rate', 0.0) or 0.0),
        'sl_rate': float(summary.get('sl_rate', 0.0) or 0.0),
        'exit_rate': float(summary.get('exit_rate', 0.0) or 0.0),
        'win_rate_net': float(summary.get('win_rate_net', 0.0) or 0.0),
        'expectancy_net_ticks': float(summary.get('expectancy_net_ticks', 0.0) or 0.0),
        'net_ticks_sum': float(summary.get('net_ticks_sum', 0.0) or 0.0),
        'trades_per_week': float(acceptance.get('overall_trades_per_week', 0.0) or 0.0),
        'concentration_top_share': float(acceptance.get('overall_concentration_top_share', 0.0) or 0.0),
        'acceptance_passed': bool(acceptance.get('passed', False)),
        'failed_reasons': list(acceptance.get('failed_reasons') or []),
    }


def fold_dispersion(report: dict[str, Any]) -> dict[str, Any]:
    fold_nets = [
        float((fold.get('test_summary') or {}).get('net_ticks_sum', 0.0) or 0.0)
        for fold in report.get('folds', [])
    ]
    if not fold_nets:
        return {
            'fold_count': 0,
            'positive_folds': 0,
            'negative_folds': 0,
            'zero_folds': 0,
            'negative_fold_share': 0.0,
            'min': 0.0,
            'median': 0.0,
            'max': 0.0,
            'p25': 0.0,
            'p75': 0.0,
        }
    sorted_nets = sorted(fold_nets)
    quantiles = statistics.quantiles(sorted_nets, n=4, method='inclusive')
    negative = sum(1 for value in sorted_nets if value < 0.0)
    positive = sum(1 for value in sorted_nets if value > 0.0)
    zero = len(sorted_nets) - positive - negative
    return {
        'fold_count': len(sorted_nets),
        'positive_folds': positive,
        'negative_folds': negative,
        'zero_folds': zero,
        'negative_fold_share': float(negative / len(sorted_nets)),
        'min': float(sorted_nets[0]),
        'median': float(statistics.median(sorted_nets)),
        'max': float(sorted_nets[-1]),
        'p25': float(quantiles[0]),
        'p75': float(quantiles[2]),
    }


def metrics_delta(candidate: dict[str, Any], baseline: dict[str, Any]) -> dict[str, Any]:
    delta: dict[str, Any] = {}
    for key in COMPARISON_KEYS:
        delta[key] = float(candidate[key]) - float(baseline[key])
    delta['acceptance_passed'] = bool(candidate['acceptance_passed']) and not bool(baseline['acceptance_passed'])
    delta['failed_reasons_added'] = [item for item in candidate['failed_reasons'] if item not in baseline['failed_reasons']]
    return delta


def reproduction_match(candidate: dict[str, Any], baseline: dict[str, Any]) -> bool:
    for key in COMPARISON_KEYS:
        if not math.isclose(float(candidate[key]), float(baseline[key]), rel_tol=0.0, abs_tol=FLOAT_TOLERANCE):
            return False
    return bool(candidate['acceptance_passed']) == bool(baseline['acceptance_passed']) and list(candidate['failed_reasons']) == list(baseline['failed_reasons'])


def cluster_args(cluster_root_map: dict[str, str]) -> list[str]:
    grouped: dict[str, list[str]] = {}
    for root, cluster in sorted(cluster_root_map.items()):
        grouped.setdefault(cluster, []).append(root)
    args: list[str] = []
    for cluster, roots in grouped.items():
        args.extend(['--cluster', f"{cluster}={','.join(roots)}"])
    return args


def build_command(reference: dict[str, Any], overrides: dict[str, Any]) -> list[str]:
    period = reference['period']
    tuning = reference['tuning_points']
    goal = tuning['goal']
    objective = tuning['objective_scoring']
    acceptance = reference['acceptance']['thresholds']
    costs = reference['cost_assumptions_ticks']
    execution = normalize_execution_policy(reference)
    execution.update({key: value for key, value in overrides.items() if key in EXECUTION_DEFAULTS})
    cost_stress_mult = float(overrides.get('cost_stress_mult', tuning.get('cost_stress_mult', 1.0)))
    args = [sys.executable, str(REPO_ROOT / 'scripts' / 'run_morning_plan_walk_forward.py')]
    for instrument in reference['instruments']:
        args.extend(['--instrument', str(instrument)])
    args.extend(cluster_args(tuning.get('cluster_root_map') or {}))
    args.extend([
        '--instrument-mode', str(reference['instrument_mode']),
        '--front-roll-avoid-expiry-days', str(tuning['front_roll_avoid_expiry_days']),
        '--start-date', str(period['start_date']),
        '--end-date', str(period['end_date']),
        '--decision-times', ','.join(period['decision_times']),
        '--train-days', str(tuning['train_days']),
        '--test-days', str(tuning['test_days']),
        '--step-days', str(tuning['step_days']),
        '--embargo-days', str(tuning['embargo_days']),
        '--purge-days', str(tuning['purge_days']),
        '--tuning-profile', str(tuning['profile']),
        '--search-algorithm', str(tuning['search_algorithm']),
        '--search-space-profile', str(tuning['search_space_profile']),
        '--hpo-trials', str(tuning['hpo_trials']),
        '--hpo-startup-trials', str(tuning['hpo_startup_trials']),
        '--hpo-seed', str(tuning['hpo_seed']),
        '--retune-every-folds', str(tuning['retune_every_folds']),
        '--cost-model-profile', str(tuning['cost_model_profile']),
        '--selection-objective', str(tuning['objective']),
        '--objective-concentration-penalty-weight', str(objective['concentration_penalty_weight']),
        '--objective-concentration-top-share-soft-cap', str(objective['concentration_top_share_soft_cap']),
        '--objective-normalization-floor-ticks', str(objective['normalization_floor_ticks']),
        '--objective-negative-fold-penalty', str(objective['negative_fold_penalty']),
        '--objective-subfold-days', str(objective['subfold_days']),
        '--objective-tail-penalty-weight', str(objective['tail_penalty_weight']),
        '--objective-tail-metric', str(objective['tail_metric']),
        '--objective-tail-alpha', str(objective['tail_alpha']),
        '--objective-tail-lower-quantile', str(objective['tail_lower_quantile']),
        '--objective-sl-rate-penalty-weight', str(objective['sl_rate_penalty_weight']),
        '--objective-exit-rate-penalty-weight', str(objective['exit_rate_penalty_weight']),
        '--objective-exit-rate-soft-cap', str(objective['exit_rate_soft_cap']),
        '--objective-causal-confidence', str(objective['causal_confidence']),
        '--objective-causal-winrate-lcb-weight', str(objective['causal_winrate_lcb_weight']),
        '--objective-causal-tpw-lcb-weight', str(objective['causal_tpw_lcb_weight']),
        '--objective-causal-expectancy-weight', str(objective['causal_expectancy_weight']),
        '--objective-causal-instability-penalty-weight', str(objective['causal_instability_penalty_weight']),
        '--goal-min-target-return-pct', str(goal['min_target_return_pct']),
        '--goal-min-trades-per-week', str(goal['min_trades_per_week']),
        '--goal-max-trades-per-week', str(goal['max_trades_per_week']),
        '--goal-trade-freq-penalty', str(goal['trade_freq_penalty']),
        '--goal-hard-min-winrate-net', str(goal['hard_min_win_rate_net']),
        '--goal-hard-min-trades-per-week', str(goal['hard_min_trades_per_week']),
        '--goal-hard-max-concentration-top-share', str(goal['hard_max_concentration_top_share']),
        '--goal-hard-violation-penalty', str(goal['hard_violation_penalty']),
        '--accept-max-negative-fold-share', str(acceptance['max_negative_fold_share']),
        '--accept-min-median-fold-net-ticks', str(acceptance['min_median_fold_net_ticks']),
        '--accept-min-tail-cvar-ticks', str(acceptance['min_tail_cvar_ticks']),
        '--min-train-trades', str(tuning['min_train_trades']),
        '--min-train-instruments-with-trades', str(tuning['min_train_instruments_with_trades']),
        '--min-trades-per-instrument', str(tuning['min_trades_per_instrument']),
        '--robust-mad-penalty', str(tuning['robust_mad_penalty']),
        '--commission-ticks-per-side', str(costs['commission_ticks_per_side']),
        '--slippage-ticks-per-side', str(costs['slippage_ticks_per_side']),
        '--spread-half-ticks', str(costs['spread_half_ticks']),
        '--cost-stress-mult', str(cost_stress_mult),
        '--execution-break-even-rr', str(execution['break_even_rr']),
        '--execution-break-even-buffer-ticks', str(execution['break_even_buffer_ticks']),
        '--execution-tp-rr', str(execution['tp_rr']),
        '--execution-sl-rr', str(execution['sl_rr']),
        '--execution-max-holding-minutes', str(execution['max_holding_minutes']),
        '--execution-max-profit-rr', str(execution['max_profit_rr']),
        '--execution-max-profit-ticks', str(execution['max_profit_ticks']),
        '--execution-trail-activation-rr', str(execution['trail_activation_rr']),
        '--execution-trail-offset-ticks', str(execution['trail_offset_ticks']),
        '--execution-same-bar-policy', str(execution['same_bar_policy']),
        '--execution-limit-entry-improve-ticks', str(execution['limit_entry_improve_ticks']),
        '--execution-limit-fallback-to-market-minutes', str(execution['limit_fallback_to_market_minutes']),
        '--execution-limit-fallback-slip-ticks', str(execution['limit_fallback_slip_ticks']),
        '--execution-tp-cost-mult', str(execution['tp_cost_mult']),
        '--execution-sl-cost-mult', str(execution['sl_cost_mult']),
        '--execution-exit-cost-mult', str(execution['exit_cost_mult']),
        '--cache-db', str(reference['cache']['cache_db']),
        '--offline-only',
        '--disable-news-gate',
    ])
    return args


def run_walk_forward(reference: dict[str, Any], hypothesis: Hypothesis) -> tuple[dict[str, Any], float, list[str]]:
    command = build_command(reference, hypothesis.overrides)
    with tempfile.NamedTemporaryFile(suffix='.json', delete=False) as handle:
        temp_path = Path(handle.name)
    command.extend(['--out-json', str(temp_path)])
    started = time.perf_counter()
    try:
        subprocess.run(command, cwd=REPO_ROOT, check=True)
        report = load_json(temp_path)
    finally:
        if temp_path.exists():
            temp_path.unlink()
    return report, time.perf_counter() - started, command


def result_artifact_path(hypothesis_id: str) -> Path:
    return ARTIFACT_DIR / f"wf_goal_v6_h24_o1_{hypothesis_id.lower()}_20260306.json"


def family_summary_path(family: str) -> Path:
    return ARTIFACT_DIR / f"wf_goal_v6_h24_o1_{family.lower()}_family_summary_20260306.json"


def run_verdict(hypothesis: Hypothesis, candidate_metrics: dict[str, Any], delta: dict[str, Any]) -> str:
    if hypothesis.sensitivity_only:
        return 'disallowed'
    if float(delta['net_ticks_sum']) > 0.0 and bool(candidate_metrics['acceptance_passed']):
        return 'useful'
    return 'noisy'


def serialize_hypothesis(hypothesis: Hypothesis, reference_label: str, reference_execution: dict[str, Any], report: dict[str, Any], runtime_seconds: float, command: list[str], baseline_metrics: dict[str, Any]) -> dict[str, Any]:
    candidate_metrics = metrics_from_report(report)
    delta = metrics_delta(candidate_metrics, baseline_metrics)
    payload = {
        'generated_at': datetime.now(UTC).isoformat(),
        'hypothesis_id': hypothesis.hypothesis_id,
        'family': hypothesis.family,
        'label': hypothesis.label,
        'mechanism_note': hypothesis.mechanism_note,
        'sensitivity_only': hypothesis.sensitivity_only,
        'changed_params': dict(hypothesis.overrides),
        'unchanged_o1_params': {key: value for key, value in reference_execution.items() if key not in hypothesis.overrides},
        'o1_reference_artifact': reference_label,
        'o1_reference_execution': reference_execution,
        'candidate_metrics': candidate_metrics,
        'delta_vs_o1': delta,
        'fold_dispersion': fold_dispersion(report),
        'acceptance': report.get('acceptance') or {},
        'runtime_seconds': round(runtime_seconds, 3),
        'command': command,
        'group': hypothesis.group,
    }
    payload['verdict'] = run_verdict(hypothesis, candidate_metrics, delta)
    return payload


def family_hypotheses() -> dict[str, list[Hypothesis]]:
    return {
        'H0': [
            Hypothesis('H0_REPRO', 'H0', 'Reproduce O1', 'Re-run the frozen O1 command on the active code path and require zero metric drift before any new hypothesis is trusted.'),
        ],
        'H1': [
            Hypothesis('H1A_IMPROVE_0', 'H1', 'Disable entry improvement', 'Remove the 1-tick favorable LIMIT improvement requirement to test whether more fills outweigh poorer entry quality.', {'limit_entry_improve_ticks': 0}, 'improve'),
            Hypothesis('H1A_IMPROVE_2', 'H1', 'Require 2-tick improvement', 'Demand a stricter favorable LIMIT improvement to test whether better entry quality offsets the expected fill loss.', {'limit_entry_improve_ticks': 2}, 'improve'),
            Hypothesis('H1B_FALLBACK_0M', 'H1', 'Disable LIMIT fallback', 'Turn off fallback-to-market to see whether O1 net is mostly coming from rescued LIMIT orders rather than pure passive fills.', {'limit_fallback_to_market_minutes': 0}, 'fallback_minutes'),
            Hypothesis('H1B_FALLBACK_5M', 'H1', 'Faster LIMIT fallback', 'Shorten fallback timeout to 5 minutes to test whether earlier rescue improves fill completion without too much adverse execution.', {'limit_fallback_to_market_minutes': 5}, 'fallback_minutes'),
            Hypothesis('H1B_FALLBACK_15M', 'H1', 'Slower LIMIT fallback', 'Delay fallback timeout to 15 minutes to test whether more patience improves entry quality enough to offset lost fills.', {'limit_fallback_to_market_minutes': 15}, 'fallback_minutes'),
            Hypothesis('H1C_FALLBACK_SLIP_0', 'H1', 'Zero fallback slip', 'Remove extra adverse ticks on fallback fills to test whether O1 is over-penalizing market rescue quality.', {'limit_fallback_slip_ticks': 0}, 'fallback_slip'),
            Hypothesis('H1C_FALLBACK_SLIP_2', 'H1', '2-tick fallback slip', 'Increase fallback slip penalty to 2 ticks to test whether O1 is understating the cost of market rescue fills.', {'limit_fallback_slip_ticks': 2}, 'fallback_slip'),
        ],
        'H2': [
            Hypothesis('H2A_BE_OFF', 'H2', 'Disable break-even', 'Remove break-even stop lifting to measure whether O1 is prematurely flattening trades that later pay.', {'break_even_rr': 0.0, 'break_even_buffer_ticks': 0}),
            Hypothesis('H2A_BE_EARLY_TIGHT', 'H2', 'Earlier tighter break-even', 'Arm break-even earlier and with a smaller cushion to test whether faster risk neutralization improves net by cutting reversals.', {'break_even_rr': 0.05, 'break_even_buffer_ticks': 1}),
            Hypothesis('H2A_BE_LATER', 'H2', 'Later break-even', 'Delay break-even arming to test whether O1 is cutting trades too early before they can reach managed targets.', {'break_even_rr': 0.2, 'break_even_buffer_ticks': 2}),
            Hypothesis('H2B_TRAIL_OFF', 'H2', 'Disable trailing stop', 'Turn trailing off to measure whether O1 tail management is helping or just clipping winners.', {'trail_activation_rr': 0.0, 'trail_offset_ticks': 0}),
            Hypothesis('H2B_TRAIL_EARLY_TIGHT', 'H2', 'Earlier tighter trailing', 'Activate trailing sooner with a tighter offset to test whether faster profit protection reduces giveback on reversals.', {'trail_activation_rr': 0.05, 'trail_offset_ticks': 1}),
            Hypothesis('H2B_TRAIL_LATER_WIDE', 'H2', 'Later wider trailing', 'Delay trailing and widen its offset to test whether O1 is over-tight on winning trades.', {'trail_activation_rr': 0.2, 'trail_offset_ticks': 3}),
            Hypothesis('H2C_HOLD_120', 'H2', 'Shorter max hold', 'Reduce max holding time to 120 minutes to test whether stale intraday positions are hurting O1 net.', {'max_holding_minutes': 120}),
            Hypothesis('H2C_HOLD_240', 'H2', 'Longer max hold', 'Extend max holding time to 240 minutes to test whether O1 is exiting too early on slow intraday trends.', {'max_holding_minutes': 240}),
        ],
        'H3': [
            Hypothesis('H3A_TP_SETUP', 'H3', 'Keep setup TP', 'Disable post-fill TP re-scaling to test whether original setup targets outperform the O1 0.6R target rewrite.', {'tp_rr': 0.0}, 'tp_rr'),
            Hypothesis('H3A_TP_0P8', 'H3', 'Wider TP at 0.8R', 'Push TP farther from fill to test whether O1 leaves too much money on the table at 0.6R.', {'tp_rr': 0.8}, 'tp_rr'),
            Hypothesis('H3B_SL_SETUP', 'H3', 'Keep setup SL', 'Disable post-fill SL re-scaling to test whether original structural stops outperform O1 2.5R stop rewrite.', {'sl_rr': 0.0}, 'sl_rr'),
            Hypothesis('H3B_SL_3P0', 'H3', 'Wider SL at 3.0R', 'Widen the post-fill stop to test whether O1 is still too tight on noisy intraday paths.', {'sl_rr': 3.0}, 'sl_rr'),
        ],
        'H4': [
            Hypothesis('H4A_CAP_OFF', 'H4', 'Disable RR profit cap', 'Remove the O1 max-profit RR cap to test whether it is clipping too many winners before their natural exit.', {'max_profit_rr': 0.0}),
            Hypothesis('H4A_CAP_0P4', 'H4', 'Looser RR profit cap', 'Raise the RR profit cap from 0.3R to 0.4R to test whether O1 winner clipping is too aggressive.', {'max_profit_rr': 0.4}),
            Hypothesis('H4B_ABS_CAP_120', 'H4', 'Absolute cap 120 ticks', 'Introduce a hard absolute profit cap to test whether outsized winners are destabilizing O1 net concentration.', {'max_profit_ticks': 120}),
            Hypothesis('H4B_ABS_CAP_240', 'H4', 'Absolute cap 240 ticks', 'Use a looser absolute cap to test whether some clipping helps concentration without fully truncating strong winners.', {'max_profit_ticks': 240}),
        ],
        'H5': [
            Hypothesis('H5A_SAMEBAR_SL_FIRST', 'H5', 'Same-bar SL first', 'Stress-test O1 under a more conservative same-bar collision rule; this is sensitivity evidence only and cannot justify promotion.', {'same_bar_policy': 'sl_first'}, sensitivity_only=True),
            Hypothesis('H5A_SAMEBAR_TP_FIRST', 'H5', 'Same-bar TP first', 'Stress-test O1 under a more favorable same-bar collision rule; this is sensitivity evidence only and cannot justify promotion.', {'same_bar_policy': 'tp_first'}, sensitivity_only=True),
            Hypothesis('H5B_COST_STRESS_125', 'H5', 'Cost stress 1.25x', 'Re-run O1 under 1.25x cost stress to test whether any uplift survives harsher execution assumptions; this is sensitivity evidence only.', {'cost_stress_mult': 1.25}, sensitivity_only=True),
            Hypothesis('H5B_COST_STRESS_150', 'H5', 'Cost stress 1.50x', 'Re-run O1 under 1.50x cost stress to map downside robustness; this is sensitivity evidence only.', {'cost_stress_mult': 1.5}, sensitivity_only=True),
        ],
    }


def best_positive(results: list[dict[str, Any]], group: str) -> dict[str, Any] | None:
    matches = [item for item in results if item.get('group') == group]
    positive = [item for item in matches if float(item['delta_vs_o1']['net_ticks_sum']) > 0.0 and bool(item['candidate_metrics']['acceptance_passed'])]
    if not positive:
        return None
    return max(positive, key=lambda item: float(item['delta_vs_o1']['net_ticks_sum']))


def dynamic_family_hypothesis(family: str, results: list[dict[str, Any]]) -> Hypothesis | None:
    if family == 'H1':
        best_timeout = best_positive(results, 'fallback_minutes')
        best_slip = best_positive(results, 'fallback_slip')
        if best_timeout and best_slip:
            overrides = dict(best_timeout['changed_params'])
            overrides.update(best_slip['changed_params'])
            return Hypothesis('H1D_BEST_FALLBACK_PAIR', 'H1', 'Best fallback timeout+slip pair', 'Combine the best positive timeout and fallback-slip single-axis results to test whether the market-rescue path has a coherent fill-quality uplift.', overrides, 'pair')
    if family == 'H3':
        best_tp = best_positive(results, 'tp_rr')
        best_sl = best_positive(results, 'sl_rr')
        if best_tp and best_sl:
            overrides = dict(best_tp['changed_params'])
            overrides.update(best_sl['changed_params'])
            return Hypothesis('H3C_BEST_TP_SL_PAIR', 'H3', 'Best TP+SL pair', 'Combine the best positive TP and SL single-axis results to test whether bracket geometry has a stable joint uplift versus O1.', overrides, 'pair')
    return None


def family_summary(reference_label: str, reference_metrics: dict[str, Any], results: list[dict[str, Any]], family: str) -> dict[str, Any]:
    best = max(results, key=lambda item: float(item['delta_vs_o1']['net_ticks_sum']))
    useful = [item for item in results if item['verdict'] == 'useful']
    if family == 'H0':
        verdict = 'useful' if all(bool(item.get('reproduction_match')) for item in results) else 'disallowed'
    elif family == 'H5':
        verdict = 'disallowed'
    elif useful:
        verdict = 'useful'
    else:
        verdict = 'noisy'
    promotion = max(useful, key=lambda item: float(item['delta_vs_o1']['net_ticks_sum']))['hypothesis_id'] if useful else None
    return {
        'generated_at': datetime.now(UTC).isoformat(),
        'family': family,
        'o1_reference_artifact': reference_label,
        'o1_reference_metrics': reference_metrics,
        'family_verdict': verdict,
        'promotion_candidate': promotion,
        'best_net_delta_hypothesis': best['hypothesis_id'],
        'best_net_delta': best['delta_vs_o1']['net_ticks_sum'],
        'results': results,
    }


def load_existing_output(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    return load_json(path)


def run_family(family: str, reference: dict[str, Any], reference_label: str, reference_metrics: dict[str, Any], output_path: Path) -> dict[str, Any]:
    execution = normalize_execution_policy(reference)
    results: list[dict[str, Any]] = []
    for hypothesis in family_hypotheses()[family]:
        print(f"[{family}] running {hypothesis.hypothesis_id}", flush=True)
        report, runtime_seconds, command = run_walk_forward(reference, hypothesis)
        payload = serialize_hypothesis(hypothesis, reference_label, execution, report, runtime_seconds, command, reference_metrics)
        if family == 'H0':
            payload['reproduction_match'] = reproduction_match(payload['candidate_metrics'], reference_metrics)
            payload['verdict'] = 'useful' if payload['reproduction_match'] else 'disallowed'
        artifact_path = result_artifact_path(hypothesis.hypothesis_id)
        payload['artifact_path'] = relpath(artifact_path)
        write_json(artifact_path, payload)
        results.append(payload)
        if family == 'H0' and not payload['reproduction_match']:
            raise RuntimeError('H0 reproduction drift detected; stop the ladder, review the drift artifact, and decide before running later families.')
    dynamic = dynamic_family_hypothesis(family, results)
    if dynamic is not None:
        print(f"[{family}] running {dynamic.hypothesis_id}", flush=True)
        report, runtime_seconds, command = run_walk_forward(reference, dynamic)
        payload = serialize_hypothesis(dynamic, reference_label, execution, report, runtime_seconds, command, reference_metrics)
        artifact_path = result_artifact_path(dynamic.hypothesis_id)
        payload['artifact_path'] = relpath(artifact_path)
        write_json(artifact_path, payload)
        results.append(payload)
    summary = family_summary(reference_label, reference_metrics, results, family)
    summary_path = family_summary_path(family)
    write_json(summary_path, summary)

    existing = load_existing_output(output_path)
    existing.setdefault('generated_at', datetime.now(UTC).isoformat())
    existing['reference_artifact'] = reference_label
    existing['reference_metrics'] = reference_metrics
    existing.setdefault('families', {})
    existing['families'][family] = {
        'summary_artifact': relpath(summary_path),
        'family_verdict': summary['family_verdict'],
        'promotion_candidate': summary['promotion_candidate'],
        'hypothesis_artifacts': [item['artifact_path'] for item in results],
    }
    existing['completed_families'] = [code for code in FAMILY_ORDER if code in existing['families']]
    existing['status'] = 'completed' if all(code in existing['families'] for code in FAMILY_ORDER) else 'running'
    write_json(output_path, existing)
    return summary


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description='Run the O1-relative execution hypothesis ladder and emit per-family verdict artifacts.')
    parser.add_argument('--reference-artifact', default=str(DEFAULT_REFERENCE))
    parser.add_argument('--out-json', default=str(DEFAULT_OUTPUT))
    parser.add_argument('--families', default='H0,H1,H2,H3,H4,H5', help='Comma-separated subset of families to run in order.')
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    reference_path = Path(args.reference_artifact)
    output_path = Path(args.out_json)
    reference = load_json(reference_path)
    reference_label = relpath(reference_path)
    reference_metrics = metrics_from_report(reference)
    requested = [item.strip().upper() for item in args.families.split(',') if item.strip()]
    invalid = [item for item in requested if item not in FAMILY_ORDER]
    if invalid:
        raise SystemExit(f"Unsupported families: {', '.join(invalid)}")
    existing = load_existing_output(output_path)
    completed = set((existing.get('families') or {}).keys())
    if any(item != 'H0' for item in requested) and 'H0' not in completed and 'H0' not in requested:
        raise SystemExit('H0 must be completed first or included in the current run.')
    ordered = [family for family in FAMILY_ORDER if family in requested]
    for family in ordered:
        run_family(family, reference, reference_label, reference_metrics, output_path)


if __name__ == '__main__':
    main()
