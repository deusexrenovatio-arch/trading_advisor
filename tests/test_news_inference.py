from __future__ import annotations

from moex_carry.news import inference as inference_mod
from moex_carry.news.inference import _safe_import, run_dual_model_inference_batch


def test_safe_import_transformers_module():
    module = _safe_import("transformers")
    assert module is not None


def test_run_dual_model_inference_batch_builds_rows(monkeypatch):
    monkeypatch.setattr(inference_mod, "apply_inference_runtime_limits", lambda **_kwargs: None)
    monkeypatch.setattr(
        inference_mod,
        "_predict_finbert_batch",
        lambda **_kwargs: [(0.8, 0.1, 0.1), (0.1, 0.8, 0.1)],
    )
    monkeypatch.setattr(
        inference_mod,
        "_predict_nli_batch",
        lambda **_kwargs: [(0.6, 0.2, 0.2), (0.2, 0.7, 0.1)],
    )

    rows = run_dual_model_inference_batch(
        news_items=[
            {"news_id": "n1", "text": "abc"},
            {"news_id": "n2", "text": "def"},
        ],
        enabled_models=["finbert", "nli"],
        finbert_model_name="finbert",
        nli_model_name="nli",
        model_version="vtest",
        batch_size=8,
        text_max_chars=100,
        thread_cap=-1,
    )

    assert len(rows) == 4
    assert {row["model_id"] for row in rows} == {"finbert", "nli"}
    assert {row["news_id"] for row in rows} == {"n1", "n2"}


def test_run_dual_model_inference_batch_truncates_text(monkeypatch):
    captured: dict[str, object] = {}

    def _fake_finbert_batch(**kwargs):
        captured["texts"] = kwargs.get("texts")
        return [(0.4, 0.3, 0.3)]

    monkeypatch.setattr(inference_mod, "apply_inference_runtime_limits", lambda **_kwargs: None)
    monkeypatch.setattr(inference_mod, "_predict_finbert_batch", _fake_finbert_batch)

    rows = run_dual_model_inference_batch(
        news_items=[{"news_id": "n1", "text": "x" * 200}],
        enabled_models=["finbert"],
        finbert_model_name="finbert",
        nli_model_name="nli",
        text_max_chars=50,
    )

    assert len(rows) == 1
    assert isinstance(captured.get("texts"), list)
    assert len(captured["texts"][0]) == 50
