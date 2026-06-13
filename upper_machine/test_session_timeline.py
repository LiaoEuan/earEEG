"""Tests for session_timeline module."""

import json
import os
import tempfile
import unittest

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
