"""State estimator — extends focus with alertness, relaxation, fatigue, affect.

Input: FeatureFrame + SignalQuality + FocusEstimate
Output: StateEstimate with multi-dimensional state scores.
This module uses interpretable heuristics, not ML.
Affect estimate is experimental and not clinically validated.
"""

from __future__ import annotations
from dataclasses import dataclass, field
import numpy as np
from ear_eeg_sound_lab.src.realtime_engine.schemas import FeatureFrame, FocusEstimate, SignalQuality

_EPSILON = 1e-12


@dataclass
class StateEstimate:
    focus: int = 0
    alertness: int = 0
    relaxation: int = 0
    fatigue: int = 0
    affect_arousal: int = 0
    affect_valence_hint: int = 50
    confidence: float = 0.0
    quality: float = 0.0
    labels: list[str] = field(default_factory=list)
    reasons: list[str] = field(default_factory=list)
    experimental: dict = field(default_factory=lambda: {
        "affect": True,
        "warning": "Affect estimate is experimental and not clinically validated.",
    })


def estimate_state(features: FeatureFrame, quality: SignalQuality, focus: FocusEstimate) -> StateEstimate:
    reasons = []
    labels = []
    q = quality.score
    tbr = features.theta_beta_ratio
    abr = features.alpha_beta_ratio
    gbp = features.global_band_powers

    # Focus (pass through)
    focus_score = focus.score

    # Alertness
    alertness = 50.0
    if gbp.beta > _EPSILON and tbr < 2.0:
        alertness += 20; reasons.append("low_theta_beta_alert")
    elif tbr > 4.0:
        alertness -= 20; reasons.append("high_theta_beta_drowsy")
    if gbp.delta > gbp.beta * 1.5:
        alertness -= 10; reasons.append("high_delta")
    alertness *= max(q, 0.3)
    alertness = int(np.clip(alertness, 0, 100))

    # Relaxation
    relaxation = 50.0
    if abr > 2.0:
        relaxation += 15; reasons.append("alpha_dominant_relax")
    if gbp.beta > gbp.alpha * 1.5 or gbp.gamma > gbp.alpha:
        relaxation -= 10; reasons.append("high_beta_gamma_tension")
    if features.artifact_ratio > 0.3:
        relaxation -= 10; reasons.append("artifact_penalty")
    relaxation *= max(q, 0.3)
    relaxation = int(np.clip(relaxation, 0, 100))

    # Fatigue
    fatigue = 30.0
    if tbr > 3.0:
        fatigue += 20; reasons.append("high_theta_beta_fatigue")
    if gbp.theta > gbp.beta * 1.5 or gbp.delta > gbp.beta:
        fatigue += 10; reasons.append("theta_delta_dominant")
    if focus_score < 45:
        fatigue += 15; reasons.append("low_focus_fatigue")
    fatigue *= max(q, 0.3)
    fatigue = int(np.clip(fatigue, 0, 100))

    # Affect (experimental)
    affect_arousal = alertness
    affect_valence_hint = 50
    if focus_score >= 70 and q > 0.7:
        affect_valence_hint += 5
    if fatigue >= 60:
        affect_valence_hint -= 5
    affect_valence_hint = int(np.clip(affect_valence_hint, 0, 100))

    # Confidence
    confidence = float(np.clip(q * (1.0 - features.artifact_ratio), 0.0, 1.0))

    # Labels
    if focus_score >= 70: labels.append("focused")
    if alertness >= 65: labels.append("alert")
    if relaxation >= 65: labels.append("relaxed")
    if fatigue >= 60: labels.append("fatigued")
    if not labels: labels.append("neutral")

    return StateEstimate(
        focus=focus_score, alertness=alertness, relaxation=relaxation,
        fatigue=fatigue, affect_arousal=affect_arousal,
        affect_valence_hint=affect_valence_hint,
        confidence=round(confidence, 3), quality=round(q, 3),
        labels=labels, reasons=reasons,
    )
