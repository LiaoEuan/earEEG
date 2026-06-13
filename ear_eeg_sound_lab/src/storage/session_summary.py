"""Session summary — aggregate EngineOutput list into statistics.

Provides a simple dict summary suitable for downstream reporting,
music policy, or LLM report input.
"""

from __future__ import annotations

from collections import Counter

from ear_eeg_sound_lab.src.realtime_engine.schemas import EngineOutput


def summarize_engine_outputs(outputs: list[EngineOutput]) -> dict:
    """Summarize a list of EngineOutput into aggregate statistics.

    Args:
        outputs: List of EngineOutput from pipeline processing.

    Returns:
        Dict with:
            - windowCount: Total number of windows.
            - meanFocus: Average focus score.
            - minFocus: Minimum focus score.
            - maxFocus: Maximum focus score.
            - meanQuality: Average signal quality score.
            - badWindowRatio: Fraction of windows with quality < 0.4.
            - stateCounts: Count of each focus state.
            - warnings: Deduplicated warning list.
    """
    if not outputs:
        return {
            "windowCount": 0,
            "meanFocus": 0,
            "minFocus": 0,
            "maxFocus": 0,
            "meanQuality": 0.0,
            "badWindowRatio": 0.0,
            "stateCounts": {},
            "warnings": [],
        }

    focus_scores = [o.focus.score for o in outputs]
    quality_scores = [o.quality.score for o in outputs]
    states = [o.focus.state for o in outputs]

    state_counts = dict(Counter(states))

    bad_window_count = sum(1 for q in quality_scores if q < 0.4)
    bad_window_ratio = bad_window_count / len(outputs)

    all_warnings: list[str] = []
    seen_warnings: set[str] = set()
    for o in outputs:
        for w in o.quality.warnings:
            if w not in seen_warnings:
                seen_warnings.add(w)
                all_warnings.append(w)

    return {
        "windowCount": len(outputs),
        "meanFocus": round(sum(focus_scores) / len(focus_scores), 1),
        "minFocus": min(focus_scores),
        "maxFocus": max(focus_scores),
        "meanQuality": round(sum(quality_scores) / len(quality_scores), 2),
        "badWindowRatio": round(bad_window_ratio, 2),
        "stateCounts": state_counts,
        "warnings": all_warnings,
    }
