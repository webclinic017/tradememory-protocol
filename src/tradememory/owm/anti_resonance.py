"""Anti-resonance: decision-time evidence gate.

Distinct from `ensure_negative_balance` in hybrid_recall.py which rebalances
the recall result set. This module evaluates whether the recalled evidence
collectively supports or opposes a proposed trading direction.

Definition
----------
Given a set of similar past trades (refs) and a proposed direction for the
current decision, compute a consonance score in [0, 1]:

  - score = 1.0 -> all recalled evidence strongly supports the proposed
                   direction (high consonance, no anti-resonance signal)
  - score = 0.5 -> mixed / neutral evidence
  - score = 0.0 -> all recalled evidence opposes the proposed direction
                   (high anti-resonance signal)

Evidence interpretation (per ref):
  - Past trade same direction & profitable  -> supports proposed direction
  - Past trade same direction & loss        -> opposes (warns repetition)
  - Past trade opposite direction & profit  -> opposes (the other side worked)
  - Past trade opposite direction & loss    -> supports (validates avoiding it)

Each ref's contribution is weighted by its similarity to the current setup
and by |pnl_r| (capped at 3R, normalised).

The boolean `anti_resonance_applied` is True iff the consonance score falls
below `applied_threshold` (default 0.4) -- i.e. counter-evidence dominates.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Optional


# Default thresholds. Tune via SSRT in follow-up phases.
APPLIED_THRESHOLD = 0.4       # score below this -> counter-evidence flag
SUPPRESS_THRESHOLD = 0.2      # score below this -> recommend suppression
PNL_R_CAP = 3.0               # cap |pnl_r| at 3R for evidence weighting


@dataclass(frozen=True)
class ConsonanceResult:
    """Outcome of a recall-consonance computation.

    Attributes:
        score: Consonance score in [0, 1]. 1 = full support, 0 = full opposition.
        supporting_count: Number of refs that contributed positive evidence.
        opposing_count: Number of refs that contributed negative evidence.
        weighted_evidence: Raw signed mean evidence in [-1, 1] (pre-normalisation).
        considered_count: Refs with usable pnl_r AND direction.
        anti_resonance_applied: True iff score < APPLIED_THRESHOLD.
        suppression_recommended: True iff score < SUPPRESS_THRESHOLD.
    """

    score: float
    supporting_count: int
    opposing_count: int
    weighted_evidence: float
    considered_count: int
    anti_resonance_applied: bool
    suppression_recommended: bool


def _normalise_direction(direction: Optional[str]) -> Optional[str]:
    """Map direction strings to canonical 'long' / 'short'.

    Accepts: long, short, buy, sell, l, s (case-insensitive).
    Returns None for unparseable input so the ref is skipped.
    """
    if direction is None:
        return None
    d = str(direction).strip().lower()
    if d in {"long", "buy", "l"}:
        return "long"
    if d in {"short", "sell", "s"}:
        return "short"
    return None


def compute_recall_consonance(
    refs: List[Dict[str, Any]],
    proposed_direction: Optional[str],
    applied_threshold: float = APPLIED_THRESHOLD,
    suppress_threshold: float = SUPPRESS_THRESHOLD,
) -> ConsonanceResult:
    """Compute consonance of recalled refs against a proposed direction.

    Each ref dict should provide:
      - pnl_r:     Optional[float]  R-multiple outcome
      - direction: Optional[str]    'long' | 'short' | 'buy' | 'sell'
      - similarity: Optional[float] in [0, 1] (defaults to 1.0)

    Refs lacking pnl_r or direction are skipped (cannot contribute evidence).
    A proposed_direction of None yields a neutral score (0.5) because we
    cannot evaluate alignment without a hypothesis to test.
    """
    proposed = _normalise_direction(proposed_direction)
    if proposed is None or not refs:
        return ConsonanceResult(
            score=0.5,
            supporting_count=0,
            opposing_count=0,
            weighted_evidence=0.0,
            considered_count=0,
            anti_resonance_applied=False,
            suppression_recommended=False,
        )

    weighted_sum = 0.0
    total_weight = 0.0
    supporting = 0
    opposing = 0
    considered = 0

    for ref in refs:
        pnl_r = ref.get("pnl_r")
        ref_dir = _normalise_direction(ref.get("direction"))
        if pnl_r is None or ref_dir is None:
            continue

        # Clamp similarity to [0, 1]; treat missing as 1.0 so legacy callers
        # without similarity scores still contribute (with full weight).
        sim_raw = ref.get("similarity")
        sim = 1.0 if sim_raw is None else max(0.0, min(1.0, float(sim_raw)))
        if sim == 0.0:
            continue

        same_direction = (ref_dir == proposed)
        # Sign rule: ref supports proposed direction if (same_dir AND profit)
        # OR (opposite_dir AND loss).
        was_profit = pnl_r > 0
        sign = 1.0 if (same_direction == was_profit) else -1.0
        magnitude = min(abs(float(pnl_r)), PNL_R_CAP) / PNL_R_CAP

        contribution = sim * sign * magnitude
        weighted_sum += contribution
        total_weight += sim
        considered += 1
        if contribution > 0:
            supporting += 1
        elif contribution < 0:
            opposing += 1

    if total_weight == 0.0 or considered == 0:
        return ConsonanceResult(
            score=0.5,
            supporting_count=0,
            opposing_count=0,
            weighted_evidence=0.0,
            considered_count=0,
            anti_resonance_applied=False,
            suppression_recommended=False,
        )

    avg_evidence = weighted_sum / total_weight  # in [-1, 1]
    score = (avg_evidence + 1.0) / 2.0          # in [0, 1]

    return ConsonanceResult(
        score=score,
        supporting_count=supporting,
        opposing_count=opposing,
        weighted_evidence=avg_evidence,
        considered_count=considered,
        anti_resonance_applied=score < applied_threshold,
        suppression_recommended=score < suppress_threshold,
    )
