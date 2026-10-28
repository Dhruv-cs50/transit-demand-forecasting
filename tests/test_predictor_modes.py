"""
tests/test_predictor_modes.py
─────────────────────────────
The AutoGluon fine-tuned backend was removed (Sprint 8, S8-07). A caller that
still asks for it must fail loudly: falling back to seasonal naive would label
naive forecasts as the model the caller named.
"""

from __future__ import annotations

from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def predictor(monkeypatch):
    monkeypatch.chdir(REPO_ROOT)
    from models.chronos2.predict import Predictor

    monkeypatch.setattr(Predictor, "_instance", None)
    return Predictor()


def test_force_mode_finetuned_raises(predictor):
    with pytest.raises(ValueError, match="finetuned"):
        predictor._ensure_loaded(force_mode="finetuned")


def test_unloadable_zeroshot_falls_back_to_naive_and_says_so(predictor, monkeypatch):
    monkeypatch.setattr(predictor, "_load_zeroshot", lambda: False)
    predictor._ensure_loaded(force_mode="zeroshot")
    assert predictor.mode == "naive"


def test_auto_mode_is_zeroshot_when_chronos_loads(predictor, monkeypatch):
    monkeypatch.setattr(predictor, "_load_zeroshot", lambda: setattr(predictor, "_mode", "zeroshot") or True)
    predictor._ensure_loaded()
    assert predictor.mode == "zeroshot"
