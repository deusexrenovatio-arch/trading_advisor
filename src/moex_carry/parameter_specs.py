from __future__ import annotations

from typing import Any, get_args, get_origin

from pydantic import BaseModel

from moex_carry.contracts.strategy_test import BacktestRequest, ParameterSpec


_PRESETS = {"NEUTRAL_5_20D"}


def get_parameter_specs(preset: str | None = None) -> list[ParameterSpec]:
    if preset is not None:
        preset = preset.strip()
        if not preset:
            preset = None
    if preset and preset not in _PRESETS:
        raise ValueError(f"unknown preset: {preset}")

    request = BacktestRequest()
    if preset == "NEUTRAL_5_20D":
        request = _apply_neutral_preset(request)

    specs: list[ParameterSpec] = []
    for key, value, annotation in _flatten_model(request):
        specs.append(
            ParameterSpec(
                key=key,
                value_type=_infer_value_type(value, annotation),
                default=value,
            )
        )
    return specs


def _apply_neutral_preset(request: BacktestRequest) -> BacktestRequest:
    return request


def _flatten_model(model: BaseModel, prefix: str = "") -> list[tuple[str, Any, Any]]:
    items: list[tuple[str, Any, Any]] = []
    for name, field in model.__class__.model_fields.items():
        value = getattr(model, name)
        key = f"{prefix}.{name}" if prefix else name
        if isinstance(value, BaseModel):
            items.extend(_flatten_model(value, key))
        else:
            items.append((key, value, field.annotation))
    return items


def _infer_value_type(value: Any, annotation: Any) -> str:
    if value is not None:
        if isinstance(value, bool):
            return "bool"
        if isinstance(value, int) and not isinstance(value, bool):
            return "int"
        if isinstance(value, float):
            return "float"
        if isinstance(value, str):
            return "str"
        if isinstance(value, list):
            return "list"
        if isinstance(value, dict):
            return "dict"
    origin = get_origin(annotation)
    if origin is None:
        if annotation in (int, float, bool, str):
            return annotation.__name__
        if annotation is None or annotation is type(None):
            return "unknown"
        name = getattr(annotation, "__name__", None)
        return name or "unknown"
    if origin is list:
        return "list"
    if origin is dict:
        return "dict"
    if origin is tuple:
        return "tuple"
    if origin is set:
        return "set"
    if origin is type(None):
        return "unknown"
    if origin is not None:
        args = [arg for arg in get_args(annotation) if arg is not type(None)]
        if len(args) == 1:
            return _infer_value_type(None, args[0])
        return "union"
    return "unknown"
