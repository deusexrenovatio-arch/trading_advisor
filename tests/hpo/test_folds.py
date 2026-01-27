from datetime import date, timedelta

from moex_carry.hpo.folds import build_walk_forward_folds


def _dates(count: int) -> list[date]:
    start = date(2025, 1, 1)
    return [start + timedelta(days=offset) for offset in range(count)]


def test_walk_forward_folds_with_embargo():
    dates = _dates(30)
    folds = build_walk_forward_folds(
        dates,
        train_days=5,
        val_days=3,
        test_days=2,
        step_days=4,
        embargo_days=1,
    )
    assert len(folds) == 5
    first = folds[0]
    assert first.train_start == dates[0]
    assert first.train_end == dates[4]
    assert first.val_start == dates[6]
    assert first.val_end == dates[8]
    assert first.test_start == dates[10]
    assert first.test_end == dates[11]

    last = folds[-1]
    assert last.train_start == dates[16]
    assert last.test_end == dates[27]
