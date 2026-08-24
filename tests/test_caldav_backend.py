import datetime
import json
import tempfile
import unittest
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "calendar"))
from unittest.mock import patch

from backends.caldav import CalDAVBackend, CalDAVUnavailable, _event_ical, _without_alarms


class FakeCalendar:
    def __init__(self, url, name):
        self.url = url
        self.name = name


class CalDAVBackendTests(unittest.TestCase):
    def test_connection_metadata_excludes_password(self):
        """Connecting stores account metadata on disk but sends the password to Secret Service."""
        with tempfile.TemporaryDirectory() as directory:
            backend = CalDAVBackend(Path(directory))
            calendars = [FakeCalendar("https://dav.example.test/calendars/me/work/", "Work")]
            with patch.object(backend, "_open", return_value=(object(), calendars)), \
                    patch.object(backend, "_store_password") as store_password:
                account_id = backend.connect("https://dav.example.test/", "me", "secret")

            saved = (Path(directory) / "accounts.json").read_text(encoding="utf-8")
            self.assertNotIn("secret", saved)
            self.assertEqual(json.loads(saved)[0]["username"], "me")
            store_password.assert_called_once_with(account_id, "me", "secret")

    def test_cached_event_is_read_only_while_offline(self):
        """CalDAV cache entries remain visible but cannot be edited offline."""
        with tempfile.TemporaryDirectory() as directory:
            backend = CalDAVBackend(Path(directory))
            info = {"id": "account", "url": "https://dav.example.test/", "username": "me",
                    "calendars": [{"id": "https://dav.example.test/work/", "name": "Work",
                                   "visible": True, "writable": True}],
                    "events": [{"calendar_id": "https://dav.example.test/work/",
                                "url": "https://dav.example.test/work/one.ics",
                                "ical": _event_ical({"summary": "Meeting", "all_day": False,
                                                     "date_start": datetime.date(2026, 8, 22),
                                                     "date_end": datetime.date(2026, 8, 22),
                                                     "time_start": datetime.time(9),
                                                     "time_end": datetime.time(10)}, "one")}],
                    "name": "me — dav.example.test"}
            backend.accounts = [info]
            event = backend.get_events()[0]
            self.assertEqual(event["provider"], "caldav")
            self.assertTrue(event["cached"])
            self.assertFalse(event["editable"])

    def test_caldav_event_does_not_create_an_alarm(self):
        """Clockenstein's universal notification is not stored in CalDAV."""
        payload = _event_ical({"summary": "Alert", "all_day": False,
                               "date_start": datetime.date.today() + datetime.timedelta(days=2),
                               "date_end": datetime.date.today() + datetime.timedelta(days=2),
                               "time_start": datetime.time(9), "time_end": datetime.time(10)})
        self.assertNotIn("BEGIN:VALARM", payload)

    def test_remote_caldav_alarms_are_removed_from_cached_data(self):
        """Remote alarms are ignored rather than retained in Clockenstein's cache."""
        payload = _event_ical({"summary": "Alert", "all_day": False,
                               "date_start": datetime.date.today(),
                               "date_end": datetime.date.today(),
                               "time_start": datetime.time(9), "time_end": datetime.time(10)})
        payload = payload.replace(
            "END:VEVENT", "BEGIN:VALARM\r\nACTION:AUDIO\r\nTRIGGER:-PT10M\r\nEND:VALARM\r\nEND:VEVENT"
        )
        self.assertNotIn("BEGIN:VALARM", _without_alarms(payload))

    def test_plain_http_is_rejected(self):
        """CalDAV refuses connections that could transmit credentials over HTTP."""
        with self.assertRaises(CalDAVUnavailable):
            CalDAVBackend._normalise_url("http://dav.example.test/")


if __name__ == "__main__":
    unittest.main()
