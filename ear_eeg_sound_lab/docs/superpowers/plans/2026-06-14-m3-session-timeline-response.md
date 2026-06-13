# M3: Session Timeline + EEG-Audio Response + StateEstimate — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 建立事件系统 + 状态扩展 + 音频响应分析，为推荐/报告打地基

**Architecture:** 在现有 eeg_viewer 基础上新增 session_timeline（事件记录）、state_estimator（状态扩展）、audio_response_service（音频响应分析）。RecordingService 接入 timeline，录制停止时保存 events.json + audio_response.json + summary.json。前端新增 Trigger/Feedback/State Detail/Music Response 弹窗。

**Tech Stack:** Python 3.14+, numpy, scipy, 标准库 (json, uuid, time, dataclasses)

**Spec:** 用户提供的 M3 规格书（Session Timeline + EEG-Audio Response + StateEstimate 扩展）

**执行顺序严格锁定为 1→2→3→4→5→6→7→8→9→10，不可跳步。**

---

## 文件结构总览

```
upper_machine/eeg_viewer/
  viewer_config.json              (新建) 统一配置
  session_timeline.py             (新建) 事件记录
  audio_response_service.py       (新建) 音频响应分析
  recording_service.py            (修改) 接入 timeline
  focus_service.py                (修改) 接入 state_estimator
  main.py                         (修改) 新增 API
  static/index.html               (修改) 新增弹窗
  static/viewer.js                (修改) Trigger/Feedback/State Detail/Music Response
  static/style.css                (修改) 新增样式

ear_eeg_sound_lab/src/realtime_engine/
  state_estimator.py              (新建) 状态扩展

upper_machine/
  test_session_timeline.py        (新建)
  test_audio_response_service.py  (新建)

ear_eeg_sound_lab/tests/
  test_state_estimator.py         (新建)
```

---

## Task 1: viewer_config.json — 统一配置

**Files:**
- Create: `upper_machine/eeg_viewer/viewer_config.json`

- [ ] **Step 1: 创建配置文件**

```json
{
  "session": {
    "outputDir": "recordings",
    "saveSidecarJson": true,
    "timelineFileSuffix": ".events.json",
    "summaryFileSuffix": ".summary.json"
  },
  "processing": {
    "sampleRate": 250,
    "channels": 16,
    "windowSeconds": 2.0,
    "updateSeconds": 0.5,
    "unit": "counts",
    "gain": 24.0,
    "vref": 4.5
  },
  "state": {
    "focusThreshold": 70,
    "stableThreshold": 45,
    "poorQualityThreshold": 0.4,
    "affectEnabled": true,
    "affectExperimental": true
  },
  "audioResponse": {
    "preBaselineSeconds": 10.0,
    "minSegmentSeconds": 20.0,
    "postEvalSeconds": 10.0,
    "minQuality": 0.6,
    "focusGainThreshold": 5.0,
    "relaxationGainThreshold": 5.0
  },
  "trigger": {
    "enabled": true,
    "hotkeys": {
      "space": "manual_marker",
      "1": "task_start",
      "2": "task_end",
      "3": "user_noted_focus",
      "4": "user_noted_distraction"
    }
  },
  "adaptive": {
    "enabledByDefault": false,
    "mode": "prompt",
    "focusDropPoints": 10,
    "focusDropDurationSeconds": 30,
    "minSongTrialSeconds": 60,
    "minQuality": 0.7
  }
}
```

- [ ] **Step 2: Commit**

```bash
git add upper_machine/eeg_viewer/viewer_config.json
git commit -m "feat(viewer): add unified viewer config JSON"
```

---

## Task 2: session_timeline.py — 事件记录系统

**Files:**
- Create: `upper_machine/eeg_viewer/session_timeline.py`
- Create: `upper_machine/test_session_timeline.py`

- [ ] **Step 1: 编写测试**

```python
"""Tests for session_timeline module."""

import json
import os
import tempfile
import unittest
import time

from upper_machine.eeg_viewer.session_timeline import SessionTimeline


class TestSessionTimeline(unittest.TestCase):

    def test_start_session_sets_id(self):
        tl = SessionTimeline()
        tl.start_session("test_001", start_monotonic=100.0)
        self.assertEqual(tl.session_id, "test_001")

    def test_add_event_returns_event(self):
        tl = SessionTimeline()
        tl.start_session("test_001", start_monotonic=100.0)
        event = tl.add_event("audio_play", source="viewer", now=105.0)
        self.assertEqual(event.type, "audio_play")
        self.assertIsNotNone(event.event_id)
        self.assertAlmostEqual(event.session_time, 5.0)

    def test_session_time_none_before_start(self):
        tl = SessionTimeline()
        event = tl.add_event("test_event", now=100.0)
        self.assertIsNone(event.session_time)

    def test_get_recent_events_limit(self):
        tl = SessionTimeline()
        tl.start_session("test", start_monotonic=0.0)
        for i in range(100):
            tl.add_event("test", now=float(i))
        recent = tl.get_recent_events(limit=10)
        self.assertEqual(len(recent), 10)

    def test_add_trigger(self):
        tl = SessionTimeline()
        tl.start_session("test", start_monotonic=0.0)
        event = tl.add_trigger("task_start", now=5.0)
        self.assertEqual(event.type, "trigger_marker")
        self.assertEqual(event.payload["label"], "task_start")

    def test_add_feedback(self):
        tl = SessionTimeline()
        tl.start_session("test", start_monotonic=0.0)
        event = tl.add_feedback("more_focused", target="current_audio", now=10.0)
        self.assertEqual(event.type, "user_feedback")
        self.assertEqual(event.payload["feedback"], "more_focused")

    def test_export_json(self):
        tl = SessionTimeline()
        tl.start_session("test_export", start_monotonic=0.0)
        tl.add_event("audio_play", now=1.0)
        tl.add_event("audio_stop", now=10.0)

        with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as f:
            path = f.name
        try:
            tl.export_json(path)
            with open(path) as f:
                data = json.load(f)
            self.assertEqual(data["sessionId"], "test_export")
            self.assertEqual(len(data["events"]), 2)
            self.assertEqual(data["version"], 1)
        finally:
            os.unlink(path)

    def test_clear(self):
        tl = SessionTimeline()
        tl.start_session("test", start_monotonic=0.0)
        tl.add_event("test", now=1.0)
        tl.clear()
        self.assertEqual(len(tl.get_events()), 0)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: 运行测试确认失败**

Run: `python -m unittest upper_machine.test_session_timeline -v`
Expected: `ModuleNotFoundError`

- [ ] **Step 3: 实现 session_timeline.py**

```python
"""Session timeline — unified event recording for earEEG experiments.

Records all key events during a session: acquisition, recording,
audio playback, triggers, user feedback, impedance, focus updates.
"""

from __future__ import annotations

import json
import time
import uuid
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from pathlib import Path


@dataclass
class TimelineEvent:
    """A single timeline event."""
    event_id: str
    type: str
    time_monotonic: float
    session_time: float | None
    wall_time: str
    source: str
    payload: dict = field(default_factory=dict)


class SessionTimeline:
    """Records events during an earEEG session.

    Usage:
        tl = SessionTimeline()
        tl.start_session("20260614_101530")
        tl.add_event("audio_play", payload={"path": "song.wav"})
        tl.add_trigger("task_start")
        tl.add_feedback("more_focused")
        tl.export_json("recordings/session.events.json")
    """

    def __init__(self) -> None:
        self._events: list[TimelineEvent] = []
        self._session_id: str = ""
        self._start_monotonic: float | None = None

    @property
    def session_id(self) -> str:
        return self._session_id

    def start_session(
        self,
        session_id: str,
        start_monotonic: float | None = None,
    ) -> None:
        """Start a new session.

        Args:
            session_id: RecordingService sessionId.
            start_monotonic: Session start time (default: now).
        """
        self._session_id = session_id
        self._start_monotonic = start_monotonic if start_monotonic is not None else time.monotonic()

    def stop_session(self, stop_monotonic: float | None = None) -> None:
        """Stop the current session."""
        # No-op for now, session_id stays for export

    def add_event(
        self,
        event_type: str,
        source: str = "viewer",
        payload: dict | None = None,
        now: float | None = None,
    ) -> TimelineEvent:
        """Add an event to the timeline.

        Args:
            event_type: Event type string.
            source: Event source ("viewer", "proxy", "keyboard", "system").
            payload: Optional event data.
            now: Current monotonic time (default: time.monotonic()).

        Returns:
            The created TimelineEvent.
        """
        t = now if now is not None else time.monotonic()
        session_time = (t - self._start_monotonic) if self._start_monotonic is not None else None

        event = TimelineEvent(
            event_id=uuid.uuid4().hex[:12],
            type=event_type,
            time_monotonic=t,
            session_time=round(session_time, 3) if session_time is not None else None,
            wall_time=datetime.now(timezone.utc).isoformat(),
            source=source,
            payload=payload or {},
        )
        self._events.append(event)
        return event

    def add_trigger(
        self,
        label: str,
        payload: dict | None = None,
        now: float | None = None,
    ) -> TimelineEvent:
        """Add a trigger marker event.

        Args:
            label: Trigger label (e.g. "task_start", "manual_marker").
            now: Current monotonic time.
        """
        p = {"label": label}
        if payload:
            p.update(payload)
        return self.add_event("trigger_marker", source="keyboard", payload=p, now=now)

    def add_feedback(
        self,
        feedback: str,
        target: str = "current_audio",
        payload: dict | None = None,
        now: float | None = None,
    ) -> TimelineEvent:
        """Add a user feedback event.

        Args:
            feedback: Feedback type ("like", "dislike", "more_focused", etc.).
            target: Feedback target (e.g. "current_audio").
            now: Current monotonic time.
        """
        p = {"feedback": feedback, "target": target}
        if payload:
            p.update(payload)
        return self.add_event("user_feedback", source="viewer", payload=p, now=now)

    def get_events(self) -> list[dict]:
        """Return all events as dicts."""
        return [self._event_to_dict(e) for e in self._events]

    def get_recent_events(self, limit: int = 50) -> list[dict]:
        """Return the most recent events."""
        return [self._event_to_dict(e) for e in self._events[-limit:]]

    def clear(self) -> None:
        """Clear all events."""
        self._events.clear()
        self._session_id = ""
        self._start_monotonic = None

    def export_json(self, path: str | Path) -> Path:
        """Export events to JSON file.

        Args:
            path: Output file path.

        Returns:
            The Path object of the written file.
        """
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        data = {
            "sessionId": self._session_id,
            "version": 1,
            "events": self.get_events(),
        }
        path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
        return path

    @staticmethod
    def _event_to_dict(event: TimelineEvent) -> dict:
        return {
            "eventId": event.event_id,
            "type": event.type,
            "timeMonotonic": round(event.time_monotonic, 3),
            "sessionTime": event.session_time,
            "wallTime": event.wall_time,
            "source": event.source,
            "payload": event.payload,
        }
```

- [ ] **Step 4: 运行测试确认通过**

Run: `python -m unittest upper_machine.test_session_timeline -v`
Expected: `OK`

- [ ] **Step 5: Commit**

```bash
git add upper_machine/eeg_viewer/session_timeline.py upper_machine/test_session_timeline.py
git commit -m "feat(viewer): add session timeline event recording system"
```

---

## Task 3: RecordingService 接入 Timeline

**Files:**
- Modify: `upper_machine/eeg_viewer/recording_service.py`

- [ ] **Step 1: 修改 RecordingService.__init__**

在 `__init__` 中新增 `timeline` 参数：

```python
def __init__(self, output_dir: str | Path = "recordings", timeline=None):
    ...
    self._timeline = timeline
```

- [ ] **Step 2: 修改 start() 方法**

在 `self._running = True` 之前添加：

```python
if self._timeline:
    self._timeline.start_session(self._session_id, self._start_monotonic)
    self._timeline.add_event("recording_start", source="viewer", payload={"sessionId": self._session_id})
```

- [ ] **Step 3: 修改 stop() 方法**

在 `self._running = False` 之前添加：

```python
if self._timeline:
    self._timeline.add_event("recording_stop", source="viewer", payload={"sessionId": self._session_id})
    self._timeline.stop_session()
    events_path = self._output_dir / f"{self._session_id}.events.json"
    self._timeline.export_json(events_path)
```

返回值新增 `eventsPath`。

- [ ] **Step 4: 修改 stimulus_play/pause/resume/stop**

每个方法添加 timeline 事件：

```python
def stimulus_play(self, wav_path: str) -> None:
    ...
    if self._timeline and self._running:
        self._timeline.add_event("audio_play", payload={"path": wav_path, "fileName": Path(wav_path).name})

def stimulus_pause(self) -> None:
    ...
    if self._timeline and self._running:
        self._timeline.add_event("audio_pause")

def stimulus_resume(self) -> None:
    ...
    if self._timeline and self._running:
        self._timeline.add_event("audio_resume")

def stimulus_stop(self) -> None:
    ...
    if self._timeline and self._running:
        self._timeline.add_event("audio_stop")
```

- [ ] **Step 5: Commit**

```bash
git add upper_machine/eeg_viewer/recording_service.py
git commit -m "feat(viewer): integrate timeline into recording service"
```

---

## Task 4: state_estimator.py — 状态扩展

**Files:**
- Create: `ear_eeg_sound_lab/src/realtime_engine/state_estimator.py`
- Create: `ear_eeg_sound_lab/tests/test_state_estimator.py`

- [ ] **Step 1: 编写测试**

```python
"""Tests for state_estimator module."""

import unittest

import numpy as np

from ear_eeg_sound_lab.src.realtime_engine.schemas import (
    BandPower, FeatureFrame, FocusEstimate, SignalQuality,
)
from ear_eeg_sound_lab.src.realtime_engine.state_estimator import (
    StateEstimate, estimate_state,
)


def _make_features(
    theta: float = 5.0, beta: float = 5.0, alpha: float = 5.0,
    delta: float = 3.0, gamma: float = 2.0, artifact: float = 0.1,
) -> FeatureFrame:
    global_bp = BandPower(delta=delta, theta=theta, alpha=alpha, beta=beta, gamma=gamma)
    return FeatureFrame(
        timestamp=0.0, band_powers={}, global_band_powers=global_bp,
        theta_beta_ratio=theta / max(beta, 1e-12),
        alpha_beta_ratio=alpha / max(beta, 1e-12),
        artifact_ratio=artifact,
    )


def _make_quality(score: float = 0.9) -> SignalQuality:
    return SignalQuality(score=score, bad_channels=[], warnings=[])


def _make_focus(score: int = 70, state: str = "focused") -> FocusEstimate:
    return FocusEstimate(score=score, quality=0.9, state=state, reasons=["beta_present"])


class TestStateEstimator(unittest.TestCase):

    def test_output_range(self):
        """All scores should be 0-100."""
        features = _make_features()
        quality = _make_quality()
        focus = _make_focus()
        state = estimate_state(features, quality, focus)
        for attr in ["focus", "alertness", "relaxation", "fatigue", "affect_arousal", "affect_valence_hint"]:
            val = getattr(state, attr)
            self.assertGreaterEqual(val, 0, f"{attr} < 0")
            self.assertLessEqual(val, 100, f"{attr} > 100")

    def test_low_quality_low_confidence(self):
        """Low quality should reduce confidence."""
        features = _make_features()
        quality_low = _make_quality(0.2)
        quality_high = _make_quality(0.9)
        focus = _make_focus()
        state_low = estimate_state(features, quality_low, focus)
        state_high = estimate_state(features, quality_high, focus)
        self.assertLess(state_low.confidence, state_high.confidence)

    def test_high_theta_beta_increases_fatigue(self):
        """High theta/beta ratio should increase fatigue."""
        features_high_tbr = _make_features(theta=15.0, beta=3.0)
        features_low_tbr = _make_features(theta=3.0, beta=15.0)
        quality = _make_quality()
        focus = _make_focus()
        state_high = estimate_state(features_high_tbr, quality, focus)
        state_low = estimate_state(features_low_tbr, quality, focus)
        self.assertGreater(state_high.fatigue, state_low.fatigue)

    def test_high_alpha_increases_relaxation(self):
        """High alpha/beta ratio should increase relaxation."""
        features_high = _make_features(alpha=20.0, beta=3.0)
        features_low = _make_features(alpha=3.0, beta=20.0)
        quality = _make_quality()
        focus = _make_focus()
        state_high = estimate_state(features_high, quality, focus)
        state_low = estimate_state(features_low, quality, focus)
        self.assertGreater(state_high.relaxation, state_low.relaxation)

    def test_affect_experimental_warning(self):
        """Output should include affect experimental warning."""
        features = _make_features()
        quality = _make_quality()
        focus = _make_focus()
        state = estimate_state(features, quality, focus)
        self.assertTrue(state.experimental.get("affect"))
        self.assertIn("experimental", state.experimental.get("warning", "").lower())

    def test_labels_not_empty(self):
        """Labels should never be empty."""
        features = _make_features()
        quality = _make_quality()
        focus = _make_focus()
        state = estimate_state(features, quality, focus)
        self.assertGreater(len(state.labels), 0)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: 运行测试确认失败**

Run: `python -m unittest ear_eeg_sound_lab.tests.test_state_estimator -v`
Expected: `ModuleNotFoundError`

- [ ] **Step 3: 实现 state_estimator.py**

```python
"""State estimator — extends focus with alertness, relaxation, fatigue, affect.

Input: FeatureFrame + SignalQuality + FocusEstimate
Output: StateEstimate with multi-dimensional state scores.

This module uses interpretable heuristics, not ML.
Affect estimate is experimental and not clinically validated.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

from ear_eeg_sound_lab.src.realtime_engine.schemas import (
    FeatureFrame,
    FocusEstimate,
    SignalQuality,
)

_EPSILON = 1e-12


@dataclass
class StateEstimate:
    """Multi-dimensional EEG state estimate.

    All scores are 0-100. Affect fields are experimental.
    """
    focus: int = 0
    alertness: int = 0
    relaxation: int = 0
    fatigue: int = 0
    affect_arousal: int = 0
    affect_valence_hint: int = 50  # 50 = neutral/unknown
    confidence: float = 0.0
    quality: float = 0.0
    labels: list[str] = field(default_factory=list)
    reasons: list[str] = field(default_factory=list)
    experimental: dict = field(default_factory=lambda: {
        "affect": True,
        "warning": "Affect estimate is experimental and not clinically validated.",
    })


def estimate_state(
    features: FeatureFrame,
    quality: SignalQuality,
    focus: FocusEstimate,
) -> StateEstimate:
    """Estimate multi-dimensional state from EEG features.

    Args:
        features: Output of extract_features().
        quality: Output of estimate_signal_quality().
        focus: Output of estimate_focus().

    Returns:
        StateEstimate with focus, alertness, relaxation, fatigue, affect.
    """
    reasons: list[str] = []
    labels: list[str] = []
    q = quality.score

    # --- Focus (pass through) ---
    focus_score = focus.score

    # --- Alertness ---
    alertness = 50.0
    tbr = features.theta_beta_ratio
    abr = features.alpha_beta_ratio
    gbp = features.global_band_powers

    if gbp.beta > _EPSILON and tbr < 2.0:
        alertness += 20
        reasons.append("low_theta_beta_alert")
    elif tbr > 4.0:
        alertness -= 20
        reasons.append("high_theta_beta_drowsy")

    if gbp.delta > gbp.beta * 1.5:
        alertness -= 10
        reasons.append("high_delta")

    alertness *= max(q, 0.3)
    alertness = int(np.clip(alertness, 0, 100))

    # --- Relaxation ---
    relaxation = 50.0
    if abr > 2.0:
        relaxation += 15
        reasons.append("alpha_dominant_relax")
    if gbp.beta > gbp.alpha * 1.5 or gbp.gamma > gbp.alpha:
        relaxation -= 10
        reasons.append("high_beta_gamma_tension")
    if features.artifact_ratio > 0.3:
        relaxation -= 10
        reasons.append("artifact_penalty")

    relaxation *= max(q, 0.3)
    relaxation = int(np.clip(relaxation, 0, 100))

    # --- Fatigue ---
    fatigue = 30.0
    if tbr > 3.0:
        fatigue += 20
        reasons.append("high_theta_beta_fatigue")
    if gbp.theta > gbp.beta * 1.5 or gbp.delta > gbp.beta:
        fatigue += 10
        reasons.append("theta_delta_dominant")
    if focus_score < 45:
        fatigue += 15
        reasons.append("low_focus_fatigue")

    fatigue *= max(q, 0.3)
    fatigue = int(np.clip(fatigue, 0, 100))

    # --- Affect (experimental) ---
    affect_arousal = alertness  # arousal ≈ alertness
    affect_valence_hint = 50  # neutral default
    if focus_score >= 70 and q > 0.7:
        affect_valence_hint += 5
    if fatigue >= 60:
        affect_valence_hint -= 5
    affect_valence_hint = int(np.clip(affect_valence_hint, 0, 100))

    # --- Confidence ---
    confidence = q * (1.0 - features.artifact_ratio)
    confidence = float(np.clip(confidence, 0.0, 1.0))

    # --- Labels ---
    if focus_score >= 70:
        labels.append("focused")
    if alertness >= 65:
        labels.append("alert")
    if relaxation >= 65:
        labels.append("relaxed")
    if fatigue >= 60:
        labels.append("fatigued")
    if not labels:
        labels.append("neutral")

    return StateEstimate(
        focus=focus_score,
        alertness=alertness,
        relaxation=relaxation,
        fatigue=fatigue,
        affect_arousal=affect_arousal,
        affect_valence_hint=affect_valence_hint,
        confidence=round(confidence, 3),
        quality=round(q, 3),
        labels=labels,
        reasons=reasons,
    )
```

- [ ] **Step 4: 运行测试确认通过**

Run: `python -m unittest ear_eeg_sound_lab.tests.test_state_estimator -v`
Expected: `OK`

- [ ] **Step 5: Commit**

```bash
git add ear_eeg_sound_lab/src/realtime_engine/state_estimator.py ear_eeg_sound_lab/tests/test_state_estimator.py
git commit -m "feat(engine): add state estimator with alertness, relaxation, fatigue, affect"
```

---

## Task 5: FocusService 接入 estimate_state()

**Files:**
- Modify: `upper_machine/eeg_viewer/focus_service.py`

- [ ] **Step 1: 修改 _compute() 方法**

在 `output = process_window(window)` 之后添加：

```python
from ear_eeg_sound_lab.src.realtime_engine.state_estimator import estimate_state

state = estimate_state(output.features, output.quality, output.focus)
```

在 `self._latest` 字典中新增 `stateEstimate` 字段：

```python
self._latest = {
    "score": output.focus.score,
    "quality": round(output.focus.quality, 2),
    "state": output.focus.state,
    "reasons": output.focus.reasons,
    "bandPowers": { ... },
    "thetaBetaRatio": ...,
    "alphaBetaRatio": ...,
    "stateEstimate": {
        "focus": state.focus,
        "alertness": state.alertness,
        "relaxation": state.relaxation,
        "fatigue": state.fatigue,
        "affectArousal": state.affect_arousal,
        "affectValenceHint": state.affect_valence_hint,
        "confidence": state.confidence,
        "labels": state.labels,
        "experimental": state.experimental,
    },
}
```

- [ ] **Step 2: 验证旧字段不变**

`get_focus()` 返回的 `score`, `quality`, `state`, `reasons` 字段必须保持不变，旧 UI 不会坏。

- [ ] **Step 3: Commit**

```bash
git add upper_machine/eeg_viewer/focus_service.py
git commit -m "feat(viewer): extend focus service with state estimator output"
```

---

## Task 6: audio_response_service.py — 音频响应分析

**Files:**
- Create: `upper_machine/eeg_viewer/audio_response_service.py`
- Create: `upper_machine/test_audio_response_service.py`

- [ ] **Step 1: 编写测试**

```python
"""Tests for audio_response_service module."""

import json
import os
import tempfile
import unittest

from upper_machine.eeg_viewer.session_timeline import SessionTimeline
from upper_machine.eeg_viewer.audio_response_service import (
    AudioResponseService,
    StateSample,
    AudioSegment,
    AudioResponse,
)


class TestAudioResponseService(unittest.TestCase):

    def _make_service(self, **kwargs):
        tl = SessionTimeline()
        tl.start_session("test", start_monotonic=0.0)
        return AudioResponseService(timeline=tl, **kwargs)

    def test_build_segments_from_timeline(self):
        svc = self._make_service()
        svc._timeline.add_event("audio_play", payload={"path": "song.wav", "fileName": "song.wav"}, now=10.0)
        svc._timeline.add_event("audio_stop", payload={}, now=130.0)
        segments = svc.build_audio_segments()
        self.assertEqual(len(segments), 1)
        self.assertAlmostEqual(segments[0].start_time, 10.0)
        self.assertAlmostEqual(segments[0].end_time, 130.0)

    def test_short_segment_label(self):
        """Segments shorter than min_segment_seconds should get 'too_short'."""
        svc = self._make_service(min_segment_seconds=20.0)
        svc._timeline.add_event("audio_play", payload={"path": "s.wav", "fileName": "s.wav"}, now=0.0)
        svc._timeline.add_event("audio_stop", payload={}, now=5.0)
        segments = svc.build_audio_segments()
        response = svc.compute_response(segments[0])
        self.assertEqual(response.label, "too_short")

    def test_low_quality_label(self):
        """Low quality samples should produce 'uncertain' label."""
        svc = self._make_service(min_quality=0.6, min_segment_seconds=5.0)
        svc._timeline.add_event("audio_play", payload={"path": "s.wav", "fileName": "s.wav"}, now=0.0)
        svc._timeline.add_event("audio_stop", payload={}, now=30.0)
        # Add low quality samples
        for t in range(30):
            svc.append_state_sample(StateSample(
                time_monotonic=float(t), session_time=float(t),
                focus=50, quality=0.3,
            ))
        segments = svc.build_audio_segments()
        response = svc.compute_response(segments[0])
        self.assertEqual(response.label, "uncertain")

    def test_focus_supportive_label(self):
        """Positive focus delta should produce 'focus_supportive'."""
        svc = self._make_service(min_segment_seconds=5.0, focus_gain_threshold=5.0, min_quality=0.1)
        svc._timeline.add_event("audio_play", payload={"path": "s.wav", "fileName": "s.wav"}, now=0.0)
        svc._timeline.add_event("audio_stop", payload={}, now=30.0)
        for t in range(30):
            svc.append_state_sample(StateSample(
                time_monotonic=float(t), session_time=float(t),
                focus=60 + t, quality=0.9,
            ))
        segments = svc.build_audio_segments()
        response = svc.compute_response(segments[0])
        self.assertEqual(response.label, "focus_supportive")

    def test_feedback_association(self):
        """User feedback should be associated with responses."""
        svc = self._make_service(min_segment_seconds=5.0, min_quality=0.1)
        svc._timeline.add_event("audio_play", payload={"path": "s.wav", "fileName": "s.wav"}, now=0.0)
        svc._timeline.add_feedback("like", target="current_audio", now=10.0)
        svc._timeline.add_event("audio_stop", payload={}, now=30.0)
        for t in range(30):
            svc.append_state_sample(StateSample(
                time_monotonic=float(t), session_time=float(t),
                focus=60, quality=0.9,
            ))
        segments = svc.build_audio_segments()
        response = svc.compute_response(segments[0])
        self.assertIn("like", response.feedback)

    def test_export_json(self):
        svc = self._make_service(min_segment_seconds=5.0, min_quality=0.1)
        svc._timeline.add_event("audio_play", payload={"path": "s.wav", "fileName": "s.wav"}, now=0.0)
        svc._timeline.add_event("audio_stop", payload={}, now=30.0)
        for t in range(30):
            svc.append_state_sample(StateSample(
                time_monotonic=float(t), session_time=float(t),
                focus=60, quality=0.9,
            ))
        svc.build_audio_segments()
        svc.compute_all_responses()
        with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as f:
            path = f.name
        try:
            svc.export_json(path)
            with open(path) as f:
                data = json.load(f)
            self.assertEqual(data["version"], 1)
            self.assertGreater(len(data["responses"]), 0)
        finally:
            os.unlink(path)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: 运行测试确认失败**

Run: `python -m unittest upper_machine.test_audio_response_service -v`
Expected: `ModuleNotFoundError`

- [ ] **Step 3: 实现 audio_response_service.py**

```python
"""Audio response service — compute EEG state changes during audio playback.

Aligns timeline audio events with state samples to produce
per-segment EEG response summaries.
"""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass, field
from pathlib import Path

from upper_machine.eeg_viewer.session_timeline import SessionTimeline


@dataclass
class StateSample:
    """A single state measurement point."""
    time_monotonic: float
    session_time: float | None
    focus: int
    quality: float
    alertness: int | None = None
    relaxation: int | None = None
    fatigue: int | None = None
    band_powers: dict = field(default_factory=dict)
    theta_beta_ratio: float = 0.0
    alpha_beta_ratio: float = 0.0


@dataclass
class AudioSegment:
    """An audio playback segment from timeline events."""
    segment_id: str
    path: str
    file_name: str
    start_time: float
    end_time: float | None
    duration: float | None
    events: list[dict] = field(default_factory=list)


@dataclass
class AudioResponse:
    """EEG response summary for a single audio segment."""
    segment_id: str
    path: str
    file_name: str
    duration: float
    mean_focus: float | None = None
    focus_delta: float | None = None
    mean_quality: float | None = None
    mean_alertness: float | None = None
    mean_relaxation: float | None = None
    mean_fatigue: float | None = None
    label: str = "unknown"
    reasons: list[str] = field(default_factory=list)
    feedback: list[str] = field(default_factory=list)


class AudioResponseService:
    """Computes EEG state changes during audio playback.

    Args:
        timeline: SessionTimeline instance.
        pre_baseline_seconds: Seconds before audio to use as baseline.
        min_segment_seconds: Minimum segment duration for valid analysis.
        min_quality: Minimum mean quality for valid analysis.
        focus_gain_threshold: Focus delta threshold for "focus_supportive".
        relaxation_gain_threshold: Relaxation delta threshold for "relaxation_supportive".
    """

    def __init__(
        self,
        timeline: SessionTimeline,
        pre_baseline_seconds: float = 10.0,
        min_segment_seconds: float = 20.0,
        min_quality: float = 0.6,
        focus_gain_threshold: float = 5.0,
        relaxation_gain_threshold: float = 5.0,
    ) -> None:
        self._timeline = timeline
        self._pre_baseline = pre_baseline_seconds
        self._min_segment = min_segment_seconds
        self._min_quality = min_quality
        self._focus_threshold = focus_gain_threshold
        self._relaxation_threshold = relaxation_gain_threshold
        self._samples: list[StateSample] = []
        self._segments: list[AudioSegment] = []
        self._responses: list[AudioResponse] = []

    def append_state_sample(self, sample: StateSample) -> None:
        """Append a state sample (called by FocusService after each computation)."""
        self._samples.append(sample)

    def get_state_samples(self) -> list[dict]:
        """Return all state samples as dicts."""
        return [
            {
                "timeMonotonic": s.time_monotonic,
                "sessionTime": s.session_time,
                "focus": s.focus,
                "quality": s.quality,
                "alertness": s.alertness,
                "relaxation": s.relaxation,
                "fatigue": s.fatigue,
            }
            for s in self._samples
        ]

    def build_audio_segments(self) -> list[AudioSegment]:
        """Build audio segments from timeline audio events."""
        events = self._timeline.get_events()
        segments: list[AudioSegment] = []
        current: AudioSegment | None = None

        for ev in events:
            if ev["type"] == "audio_play":
                current = AudioSegment(
                    segment_id=uuid.uuid4().hex[:12],
                    path=ev["payload"].get("path", ""),
                    file_name=ev["payload"].get("fileName", ""),
                    start_time=ev["timeMonotonic"],
                    end_time=None,
                    duration=None,
                    events=[ev],
                )
            elif ev["type"] == "audio_stop" and current is not None:
                current.end_time = ev["timeMonotonic"]
                current.duration = current.end_time - current.start_time
                current.events.append(ev)
                segments.append(current)
                current = None
            elif current is not None:
                current.events.append(ev)

        # Handle still-playing segment
        if current is not None:
            current.end_time = self._samples[-1].time_monotonic if self._samples else current.start_time
            current.duration = current.end_time - current.start_time
            segments.append(current)

        self._segments = segments
        return segments

    def compute_response(self, segment: AudioSegment) -> AudioResponse:
        """Compute EEG response for a single audio segment."""
        # Filter samples within segment time range
        seg_samples = [
            s for s in self._samples
            if segment.start_time <= s.time_monotonic <= (segment.end_time or segment.start_time)
        ]

        # Baseline samples (before segment)
        baseline_samples = [
            s for s in self._samples
            if segment.start_time - self._pre_baseline <= s.time_monotonic < segment.start_time
        ]

        duration = segment.duration or 0.0
        response = AudioResponse(
            segment_id=segment.segment_id,
            path=segment.path,
            file_name=segment.file_name,
            duration=duration,
        )

        # Too short
        if duration < self._min_segment:
            response.label = "too_short"
            response.reasons.append("segment_too_short")
            return response

        if not seg_samples:
            response.label = "uncertain"
            response.reasons.append("no_samples")
            return response

        # Compute means
        response.mean_focus = round(sum(s.focus for s in seg_samples) / len(seg_samples), 1)
        response.mean_quality = round(sum(s.quality for s in seg_samples) / len(seg_samples), 3)

        alertness_samples = [s.alertness for s in seg_samples if s.alertness is not None]
        relaxation_samples = [s.relaxation for s in seg_samples if s.relaxation is not None]
        fatigue_samples = [s.fatigue for s in seg_samples if s.fatigue is not None]

        if alertness_samples:
            response.mean_alertness = round(sum(alertness_samples) / len(alertness_samples), 1)
        if relaxation_samples:
            response.mean_relaxation = round(sum(relaxation_samples) / len(relaxation_samples), 1)
        if fatigue_samples:
            response.mean_fatigue = round(sum(fatigue_samples) / len(fatigue_samples), 1)

        # Low quality
        if response.mean_quality < self._min_quality:
            response.label = "uncertain"
            response.reasons.append("low_quality")
            return response

        # Focus delta
        if baseline_samples:
            baseline_focus = sum(s.focus for s in baseline_samples) / len(baseline_samples)
            response.focus_delta = round(response.mean_focus - baseline_focus, 1)

        # Label
        if response.focus_delta is not None and response.focus_delta >= self._focus_threshold:
            response.label = "focus_supportive"
            response.reasons.append("focus_delta_positive")
        elif response.mean_relaxation is not None and baseline_samples:
            baseline_relax = [s.relaxation for s in baseline_samples if s.relaxation is not None]
            if baseline_relax:
                relax_delta = response.mean_relaxation - sum(baseline_relax) / len(baseline_relax)
                if relax_delta >= self._relaxation_threshold:
                    response.label = "relaxation_supportive"
                    response.reasons.append("relaxation_delta_positive")
        elif response.focus_delta is not None and response.focus_delta <= -self._focus_threshold:
            response.label = "distracting"
            response.reasons.append("focus_delta_negative")
        else:
            response.label = "neutral"
            response.reasons.append("no_significant_change")

        # Feedback
        for ev in segment.events:
            if ev["type"] == "user_feedback":
                response.feedback.append(ev["payload"].get("feedback", ""))

        return response

    def compute_all_responses(self) -> list[AudioResponse]:
        """Compute responses for all segments."""
        if not self._segments:
            self.build_audio_segments()
        self._responses = [self.compute_response(seg) for seg in self._segments]
        return self._responses

    def export_json(self, path: str | Path) -> Path:
        """Export responses to JSON."""
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        data = {
            "sessionId": self._timeline.session_id,
            "version": 1,
            "responses": [
                {
                    "segmentId": r.segment_id,
                    "fileName": r.file_name,
                    "duration": round(r.duration, 1),
                    "meanFocus": r.mean_focus,
                    "focusDelta": r.focus_delta,
                    "meanQuality": r.mean_quality,
                    "meanAlertness": r.mean_alertness,
                    "meanRelaxation": r.mean_relaxation,
                    "meanFatigue": r.mean_fatigue,
                    "label": r.label,
                    "reasons": r.reasons,
                    "feedback": r.feedback,
                }
                for r in self._responses
            ],
        }
        path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
        return path
```

- [ ] **Step 4: 运行测试确认通过**

Run: `python -m unittest upper_machine.test_audio_response_service -v`
Expected: `OK`

- [ ] **Step 5: Commit**

```bash
git add upper_machine/eeg_viewer/audio_response_service.py upper_machine/test_audio_response_service.py
git commit -m "feat(viewer): add audio response service for EEG-audio analysis"
```

---

## Task 7: RecordingService 保存 audio_response.json + summary.json

**Files:**
- Modify: `upper_machine/eeg_viewer/recording_service.py`

- [ ] **Step 1: 修改 stop() 方法**

在保存 events.json 之后添加：

```python
if self._timeline and self._audio_response:
    self._audio_response.compute_all_responses()
    response_path = self._output_dir / f"{self._session_id}.audio_response.json"
    self._audio_response.export_json(response_path)

    summary_path = self._output_dir / f"{self._session_id}.summary.json"
    self._export_summary(summary_path)
```

- [ ] **Step 2: 添加 _export_summary() 方法**

```python
def _export_summary(self, path: Path) -> None:
    """Export session summary JSON."""
    events = self._timeline.get_events() if self._timeline else []
    responses = self._audio_response._responses if self._audio_response else []

    event_counts = {}
    for ev in events:
        t = ev["type"]
        event_counts[t] = event_counts.get(t, 0) + 1

    audio_labels = {}
    for r in responses:
        audio_labels[r.label] = audio_labels.get(r.label, 0) + 1

    focus_values = [s.focus for s in self._audio_response._samples] if self._audio_response else []
    quality_values = [s.quality for s in self._audio_response._samples] if self._audio_response else []

    summary = {
        "sessionId": self._session_id,
        "version": 1,
        "durationSeconds": round(time.monotonic() - self._start_monotonic, 1) if self._start_monotonic else 0,
        "meanFocus": round(sum(focus_values) / len(focus_values), 1) if focus_values else None,
        "meanQuality": round(sum(quality_values) / len(quality_values), 3) if quality_values else None,
        "eventCounts": event_counts,
        "audioLabels": audio_labels,
        "warnings": ["Affect estimate is experimental and not clinically validated."],
    }
    path.write_text(json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8")
```

- [ ] **Step 3: 修改 __init__ 接收 audio_response 参数**

```python
def __init__(self, output_dir="recordings", timeline=None, audio_response=None):
    ...
    self._audio_response = audio_response
```

- [ ] **Step 4: Commit**

```bash
git add upper_machine/eeg_viewer/recording_service.py
git commit -m "feat(viewer): save audio_response.json and summary.json on recording stop"
```

---

## Task 8: main.py 新增 API

**Files:**
- Modify: `upper_machine/eeg_viewer/main.py`

- [ ] **Step 1: 新增 GET 端点**

```python
if path == "/api/timeline":
    self._send_json({"ok": True, "events": self.timeline.get_recent_events()})
    return
if path == "/api/audio/responses":
    self._send_json({"ok": True, "responses": [...]})
    return
if path == "/api/config":
    self._send_json({"ok": True, "config": self.viewer_config})
    return
```

- [ ] **Step 2: 新增 POST 端点**

```python
def do_POST(self) -> None:
    ...
    if path == "/api/trigger":
        body = self._read_json_body()
        event = self.timeline.add_trigger(body.get("label", "manual_marker"), payload=body)
        self._send_json({"ok": True, "event": TimelineEvent...})
        return
    if path == "/api/feedback":
        body = self._read_json_body()
        event = self.timeline.add_feedback(body.get("feedback", ""), target=body.get("target", "current_audio"))
        self._send_json({"ok": True, "event": ...})
        return
```

- [ ] **Step 3: 修改 main() 初始化**

```python
from upper_machine.eeg_viewer.session_timeline import SessionTimeline
from upper_machine.eeg_viewer.audio_response_service import AudioResponseService

timeline = SessionTimeline()
audio_response = AudioResponseService(timeline=timeline, ...)
recorder = RecordingService(output_dir="recordings", timeline=timeline, audio_response=audio_response)
```

- [ ] **Step 4: Commit**

```bash
git add upper_machine/eeg_viewer/main.py
git commit -m "feat(viewer): add timeline, trigger, feedback, config API endpoints"
```

---

## Task 9: 前端 — Trigger / Feedback / State Detail / Music Response

**Files:**
- Modify: `upper_machine/eeg_viewer/static/index.html`
- Modify: `upper_machine/eeg_viewer/static/viewer.js`
- Modify: `upper_machine/eeg_viewer/static/style.css`

- [ ] **Step 1: Trigger 功能**

在 viewer.js 中添加：
- 键盘事件监听（key 1/2/3/4/space → POST /api/trigger）
- Trigger 按钮点击 → POST /api/trigger
- EEG 画绘制 trigger 竖线（从 WebSocket timeline.recentEvents 获取）

- [ ] **Step 2: Feedback 按钮**

在 Record/Playback 面板或 Music Response 弹窗中添加：
- [Like] [Dislike] [More Focused] [More Distracted] [More Relaxed]
- 点击 → POST /api/feedback

- [ ] **Step 3: State Detail 弹窗**

点击底部 focus 条弹出，显示：
- focus, alertness, relaxation, fatigue, affect_arousal, affect_valence_hint
- 频段功率
- ratios
- reasons
- Experimental 标注

数据来源：`frame.focus.stateEstimate`

- [ ] **Step 4: Music Response 弹窗**

新增按钮 "Music Response: View"，弹窗显示：
- 当前音频片段
- 历史 responses
- label, meanFocus, focusDelta, meanQuality
- feedback 按钮

数据来源：GET /api/audio/responses

- [ ] **Step 5: Trigger 竖线绘制**

在 EEG canvas draw 函数中：
- 从 WebSocket payload.timeline.recentEvents 过滤 trigger_marker
- 在对应 sessionTime 位置绘制竖线 + 标签

- [ ] **Step 6: Commit**

```bash
git add upper_machine/eeg_viewer/static/
git commit -m "feat(viewer): add trigger, feedback, state detail, music response UI"
```

---

## Task 10: 联调验证

- [ ] **Step 1: 运行全量测试**

```powershell
python -m unittest discover -s ear_eeg_sound_lab/tests -p "test_*.py"
python -m unittest discover -s upper_machine -p "test_*.py"
```

Expected: All pass.

- [ ] **Step 2: 启动联调**

```powershell
.\start_all.ps1
```

浏览器打开 http://127.0.0.1:8765

- [ ] **Step 3: 验证清单**

- [ ] 开始录制
- [ ] 播放 WAV
- [ ] 按键盘 1 → EEG 画布出现 trigger 竖线
- [ ] 点击 feedback 按钮
- [ ] 停止录制
- [ ] recordings/ 下生成 4 个文件：.npz, .events.json, .audio_response.json, .summary.json
- [ ] 打开 State Detail 弹窗，显示 alertness/relaxation/fatigue/affect
- [ ] 打开 Music Response 弹窗，显示音频响应
- [ ] affect 相关显示 "Experimental"

- [ ] **Step 4: Commit**

```bash
git add -A
git commit -m "feat: M3 session timeline + audio response + state estimate complete"
```

---

## 总结

| Task | 模块 | 测试 | 依赖 |
|------|------|------|------|
| 1 | viewer_config.json | — | 无 |
| 2 | session_timeline.py | test_session_timeline.py | 无 |
| 3 | RecordingService 接入 timeline | — | Task 2 |
| 4 | state_estimator.py | test_state_estimator.py | 无 |
| 5 | FocusService 接入 estimate_state() | — | Task 4 |
| 6 | audio_response_service.py | test_audio_response_service.py | Task 2 |
| 7 | RecordingService 保存 JSON | — | Task 3, 6 |
| 8 | main.py 新增 API | — | Task 2, 6 |
| 9 | 前端 UI | — | Task 8 |
| 10 | 联调验证 | 全量测试 | 全部 |
