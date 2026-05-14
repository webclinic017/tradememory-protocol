"""Tests for owm.anti_resonance — recall-consonance evidence gate."""

from __future__ import annotations

import pytest

from tradememory.owm.anti_resonance import (
    APPLIED_THRESHOLD,
    SUPPRESS_THRESHOLD,
    compute_recall_consonance,
)


# ---------------------------------------------------------------------------
# Degenerate inputs
# ---------------------------------------------------------------------------

def test_no_refs_returns_neutral():
    r = compute_recall_consonance([], proposed_direction="long")
    assert r.score == 0.5
    assert r.considered_count == 0
    assert r.supporting_count == 0
    assert r.opposing_count == 0
    assert r.anti_resonance_applied is False
    assert r.suppression_recommended is False


def test_no_proposed_direction_returns_neutral():
    refs = [{"pnl_r": 1.5, "direction": "long"}]
    r = compute_recall_consonance(refs, proposed_direction=None)
    assert r.score == 0.5
    assert r.considered_count == 0
    assert r.anti_resonance_applied is False


def test_refs_without_pnl_or_direction_are_skipped():
    refs = [
        {"pnl_r": None, "direction": "long"},
        {"pnl_r": 1.0, "direction": None},
        {"direction": "long"},  # missing pnl_r entirely
    ]
    r = compute_recall_consonance(refs, proposed_direction="long")
    assert r.considered_count == 0
    assert r.score == 0.5


# ---------------------------------------------------------------------------
# Full support / full opposition
# ---------------------------------------------------------------------------

def test_all_refs_support_proposed_long():
    # Same direction + profit = supports
    refs = [
        {"pnl_r": 2.0, "direction": "long"},
        {"pnl_r": 1.5, "direction": "long"},
        {"pnl_r": 3.0, "direction": "long"},
    ]
    r = compute_recall_consonance(refs, proposed_direction="long")
    assert r.score > 0.7
    assert r.supporting_count == 3
    assert r.opposing_count == 0
    assert r.anti_resonance_applied is False


def test_all_refs_oppose_proposed_long():
    # Same direction + loss = opposes (warns against repetition)
    refs = [
        {"pnl_r": -1.5, "direction": "long"},
        {"pnl_r": -2.0, "direction": "long"},
        {"pnl_r": -1.0, "direction": "long"},
    ]
    r = compute_recall_consonance(refs, proposed_direction="long")
    assert r.score < 0.3
    assert r.opposing_count == 3
    assert r.supporting_count == 0
    assert r.anti_resonance_applied is True


def test_opposite_direction_profit_opposes_proposed():
    # Opposite direction profitable = the OTHER side worked = opposes proposed
    refs = [
        {"pnl_r": 2.0, "direction": "short"},
        {"pnl_r": 1.5, "direction": "short"},
    ]
    r = compute_recall_consonance(refs, proposed_direction="long")
    assert r.score < 0.3
    assert r.opposing_count == 2
    assert r.anti_resonance_applied is True


def test_opposite_direction_loss_supports_proposed():
    # Opposite direction loss = avoiding that side was correct = supports
    refs = [
        {"pnl_r": -2.0, "direction": "short"},
        {"pnl_r": -1.0, "direction": "short"},
    ]
    r = compute_recall_consonance(refs, proposed_direction="long")
    assert r.score > 0.7
    assert r.supporting_count == 2


# ---------------------------------------------------------------------------
# Mixed evidence
# ---------------------------------------------------------------------------

def test_balanced_mixed_evidence_near_neutral():
    refs = [
        {"pnl_r": 2.0, "direction": "long"},   # supports
        {"pnl_r": -2.0, "direction": "long"},  # opposes
        {"pnl_r": 2.0, "direction": "short"},  # opposes
        {"pnl_r": -2.0, "direction": "short"}, # supports
    ]
    r = compute_recall_consonance(refs, proposed_direction="long")
    assert 0.4 <= r.score <= 0.6
    assert r.supporting_count == 2
    assert r.opposing_count == 2


# ---------------------------------------------------------------------------
# Similarity weighting
# ---------------------------------------------------------------------------

def test_similarity_weights_evidence():
    # Two opposing refs; supporter has high similarity, opposer low.
    refs = [
        {"pnl_r": 2.0, "direction": "long", "similarity": 1.0},   # supports, high weight
        {"pnl_r": -2.0, "direction": "long", "similarity": 0.1},  # opposes, low weight
    ]
    r = compute_recall_consonance(refs, proposed_direction="long")
    # Net should lean supportive even though counts are 1-1.
    assert r.score > 0.6


def test_similarity_zero_skips_ref():
    refs = [
        {"pnl_r": 2.0, "direction": "long", "similarity": 0.0},
        {"pnl_r": -2.0, "direction": "long", "similarity": 1.0},
    ]
    r = compute_recall_consonance(refs, proposed_direction="long")
    # Only the opposing ref counts.
    assert r.considered_count == 1
    assert r.score < 0.3


# ---------------------------------------------------------------------------
# Direction normalisation
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("proposed_alias", ["LONG", "buy", "Buy", "L", "l"])
def test_long_direction_aliases(proposed_alias):
    refs = [{"pnl_r": 2.0, "direction": "long"}]
    r = compute_recall_consonance(refs, proposed_direction=proposed_alias)
    assert r.supporting_count == 1


@pytest.mark.parametrize("ref_alias", ["SHORT", "sell", "Sell", "S", "s"])
def test_short_direction_aliases(ref_alias):
    refs = [{"pnl_r": 2.0, "direction": ref_alias}]
    # Past short + profit = opposes proposed long
    r = compute_recall_consonance(refs, proposed_direction="long")
    assert r.opposing_count == 1


def test_unrecognised_direction_skipped():
    refs = [
        {"pnl_r": 2.0, "direction": "sideways"},
        {"pnl_r": 1.0, "direction": "long"},
    ]
    r = compute_recall_consonance(refs, proposed_direction="long")
    assert r.considered_count == 1


# ---------------------------------------------------------------------------
# Threshold behaviour
# ---------------------------------------------------------------------------

def test_threshold_applied_flag_fires_below_default():
    # Strong opposition -> applied=True
    refs = [{"pnl_r": -3.0, "direction": "long"} for _ in range(5)]
    r = compute_recall_consonance(refs, proposed_direction="long")
    assert r.score < APPLIED_THRESHOLD
    assert r.anti_resonance_applied is True


def test_threshold_suppression_fires_at_strong_opposition():
    refs = [{"pnl_r": -3.0, "direction": "long"} for _ in range(5)]
    r = compute_recall_consonance(refs, proposed_direction="long")
    assert r.score < SUPPRESS_THRESHOLD
    assert r.suppression_recommended is True


def test_custom_thresholds_respected():
    refs = [
        {"pnl_r": 0.3, "direction": "long"},  # mildly supportive
    ]
    # With normal threshold this won't fire; raise threshold artificially.
    r = compute_recall_consonance(
        refs, proposed_direction="long", applied_threshold=0.9
    )
    assert r.anti_resonance_applied is True


# ---------------------------------------------------------------------------
# PnL magnitude is capped (3R)
# ---------------------------------------------------------------------------

def test_pnl_magnitude_capped_at_3r():
    # A 100R outcome shouldn't dominate beyond what a 3R outcome would.
    huge = compute_recall_consonance(
        [{"pnl_r": 100.0, "direction": "long"}], proposed_direction="long"
    )
    capped = compute_recall_consonance(
        [{"pnl_r": 3.0, "direction": "long"}], proposed_direction="long"
    )
    # Both should reach near-maximum support, identical after capping.
    assert pytest.approx(huge.score, abs=1e-9) == capped.score
