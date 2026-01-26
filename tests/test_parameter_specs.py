from pydantic import BaseModel

from moex_carry.contracts.strategy_test import BacktestRequest
from moex_carry.parameter_specs import get_parameter_specs


def _flatten_model(model: BaseModel, prefix: str = "") -> list[str]:
    keys: list[str] = []
    for name in model.__class__.model_fields:
        value = getattr(model, name)
        key = f"{prefix}.{name}" if prefix else name
        if isinstance(value, BaseModel):
            keys.extend(_flatten_model(value, key))
        else:
            keys.append(key)
    return keys


def test_parameter_specs_keys_unique_and_complete():
    specs = get_parameter_specs(None)
    keys = [spec.key for spec in specs]
    assert len(keys) == len(set(keys))

    expected_keys = set(_flatten_model(BacktestRequest()))
    assert set(keys) == expected_keys
