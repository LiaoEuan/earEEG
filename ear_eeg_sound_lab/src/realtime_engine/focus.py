"""Focus estimation — heuristic-based attention/focus scoring.

Extended heuristic using theta/beta ratio, alpha/beta ratio,
beta presence, artifact ratio, and signal quality.

Input: FeatureFrame + SignalQuality
Output: FocusEstimate (score 0-100, state, reasons)

This is an algorithmic estimate, not a medical diagnosis.
"""

from __future__ import annotations

import numpy as np

from ear_eeg_sound_lab.src.realtime_engine.schemas import (
    FeatureFrame,
    FocusEstimate,
    SignalQuality,
)

# Small constant to prevent division by zero
_EPSILON = 1e-12


def estimate_focus(features: FeatureFrame, quality: SignalQuality) -> FocusEstimate:
    """Estimate focus level from EEG features and signal quality.

    Uses a heuristic combining:
        - Theta/beta ratio (primary attention indicator)
        - Alpha/beta ratio (relaxation indicator)
        - Beta presence (cognitive engagement)
        - Artifact ratio (signal contamination)
        - Signal quality (overall confidence)

    Args:
        features: Extracted frequency band features.
        quality: Signal quality assessment.

    Returns:
        FocusEstimate with score in [0, 100], quality, state label, and reasons.
    """
    reasons: list[str] = []

    # Quality gate: if quality is too low, return early
    if quality.score < 0.4:
        score = int(np.clip(quality.score * 100, 0, 40))
        return FocusEstimate(
            score=score,
            quality=quality.score,
            state="noisy",
            reasons=["poor_signal_quality"],
        )

    # Start with base score
    base = 50.0

    # Theta/beta ratio assessment (primary focus indicator)
    tbr = features.theta_beta_ratio
    if tbr < 1.5:
        base += 15
        reasons.append("low_theta_beta")
    elif tbr < 2.0:
        base += 10
        reasons.append("moderate_theta_beta")
    elif tbr > 4.0:
        base -= 15
        reasons.append("high_theta_beta")
    elif tbr > 3.0:
        base -= 8
        reasons.append("elevated_theta_beta")

    # Alpha/beta ratio assessment (relaxation indicator)
    abr = features.alpha_beta_ratio
    if abr > 3.0:
        base -= 10
        reasons.append("alpha_dominant")
    elif abr > 2.0:
        base -= 5
        reasons.append("alpha_elevated")

    # Beta presence (cognitive engagement)
    if features.global_band_powers.beta > _EPSILON:
        base += 5
        reasons.append("beta_present")

    # Artifact penalty
    if features.artifact_ratio > 0.3:
        penalty = int(features.artifact_ratio * 20)
        base -= penalty
        reasons.append("artifact_penalty")

    # Quality weighting
    base *= quality.score

    # Clamp to [0, 100]
    score = int(np.clip(round(base), 0, 100))

    # State determination
    if quality.score < 0.4:
        state = "noisy"
    elif score >= 70:
        state = "focused"
    elif score >= 45:
        state = "stable"
    elif score >= 30:
        state = "relaxed"
    else:
        state = "fatigued"

    # Ensure reasons is never empty
    if not reasons:
        reasons.append("default_assessment")

    return FocusEstimate(
        score=score,
        quality=quality.score,
        state=state,
        reasons=reasons,
    )
