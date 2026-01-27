from moex_carry.hpo.types import HpoResult, TrialResult


def test_leaderboard_sorted_and_best_config():
    trials = [
        TrialResult(params={"a": 1}, objective=1.0, fold_objectives=[1.0], fold_results=[]),
        TrialResult(params={"a": 2}, objective=2.0, fold_objectives=[2.0], fold_results=[]),
        TrialResult(params={"a": 3}, objective=float("-inf"), fold_objectives=[float("-inf")], fold_results=[]),
    ]
    result = HpoResult(trials=trials, mode="max")
    leaderboard = result.leaderboard()
    assert leaderboard[0].objective == 2.0
    assert result.best_config == {"a": 2}
