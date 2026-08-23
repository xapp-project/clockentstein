import unittest
import sys
from pathlib import Path

import datetime

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "calendar"))

from views.day_view import (_assign_event_columns, _event_label_parts, _minute_to_y,
                            _timed_segment_minutes)


class DayLayoutTests(unittest.TestCase):
    def test_event_height_uses_exact_minutes(self):
        """Vertical event geometry maps its precise duration to pixels."""
        self.assertEqual(_minute_to_y(20 * 60 + 30) - _minute_to_y(18 * 60 + 45), 84)

    def test_overlapping_events_get_separate_equal_columns(self):
        """Concurrent events receive separate columns and later events reuse space."""
        events = [
            {"start": 9 * 60, "end": 11 * 60},
            {"start": 10 * 60, "end": 12 * 60},
            {"start": 12 * 60, "end": 13 * 60},
        ]
        _assign_event_columns(events)
        self.assertEqual([(e["column"], e["columns"]) for e in events],
                         [(0, 2), (1, 2), (0, 1)])

    def test_timed_multiday_event_uses_times_on_first_and_last_days(self):
        """Timed multiday segments honor endpoint times and fill intermediate days."""
        event = {
            "date_start": datetime.date(2026, 8, 20),
            "date_end": datetime.date(2026, 8, 22),
            "time_start": datetime.time(18, 45),
            "time_end": datetime.time(20, 30),
        }
        self.assertEqual(_timed_segment_minutes(event, event["date_start"]),
                         (18 * 60 + 45, 24 * 60))
        self.assertEqual(_timed_segment_minutes(event, datetime.date(2026, 8, 21)),
                         (0, 24 * 60))
        self.assertEqual(_timed_segment_minutes(event, event["date_end"]),
                         (0, 20 * 60 + 30))

    def test_day_event_label_orders_title_time_and_location(self):
        """Day-view card content presents title, time, then location."""
        parts = _event_label_parts(
            {"summary": "Match", "location": "Stadium"}, 18 * 60 + 45,
            20 * 60 + 30, False,
        )
        self.assertEqual(parts, ("Match", "18:45–20:30", "Stadium"))


if __name__ == "__main__":
    unittest.main()
