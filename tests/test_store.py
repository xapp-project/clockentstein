import datetime
import tempfile
import unittest
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "calendar"))

from backends.google import (EVENTS_PAGE_SIZE, GoogleBackend, SCOPES,
                             event_dict_to_google, google_event_fits_sync_range,
                             google_event_to_dict)
from store import LocalStore


class LocalStoreTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.store = LocalStore(Path(self.temp.name))

    def tearDown(self):
        self.temp.cleanup()

    def test_first_run_creates_personal_calendar(self):
        """A new data store creates exactly one usable Personal calendar."""
        calendars = self.store.list_calendars()
        self.assertEqual([c["name"] for c in calendars], ["Personal"])
        self.assertTrue((Path(self.temp.name) / "calendars" / "personal.ics").exists())

    def test_events_belong_to_their_local_calendar(self):
        """Creating an event stores and returns it under its selected calendar."""
        work = self.store.create_calendar("Work", "#ff0000")
        event = self.store.create_event({
            "calendar_id": work["id"], "summary": "Review", "all_day": False,
            "date_start": datetime.date(2026, 8, 22), "date_end": datetime.date(2026, 8, 22),
            "time_start": datetime.time(9), "time_end": datetime.time(10),
        })
        self.assertEqual(event["calendar_name"], "Work")
        self.assertEqual(event["provider"], "local")
        event["summary"] = "Updated"
        self.store.update_event(event["uid"], event)
        self.assertEqual(self.store.get_events()[0]["summary"], "Updated")
        self.assertTrue(self.store.delete_event(event["uid"], work["id"]))

    def test_visibility_is_persistent(self):
        """Calendar visibility survives reloading the store from disk."""
        personal = self.store.list_calendars()[0]
        self.store.set_visible(personal["id"], False)
        reopened = LocalStore(Path(self.temp.name))
        self.assertFalse(reopened.list_calendars()[0]["visible"])

    def test_local_calendar_name_and_color_can_be_changed(self):
        """Local calendar metadata updates are persisted and returned."""
        personal = self.store.list_calendars()[0]
        self.store.update_calendar(personal["id"], "Home", "#abcdef")
        reopened = LocalStore(Path(self.temp.name))
        updated = reopened.list_calendars()[0]
        self.assertEqual(updated["name"], "Home")
        self.assertEqual(updated["color"], "#abcdef")

    def test_local_calendar_can_be_removed_but_one_is_retained(self):
        """Calendars and their files can be removed without leaving the store empty."""
        work = self.store.create_calendar("Work")
        path = Path(self.temp.name) / "calendars" / f"{work['id']}.ics"
        self.store.delete_calendar(work["id"])
        self.assertFalse(path.exists())
        self.assertEqual([c["name"] for c in self.store.list_calendars()], ["Personal"])
        with self.assertRaises(ValueError):
            self.store.delete_calendar("personal")

    def test_local_event_stores_one_display_notification(self):
        """A local event round-trips its single display notification."""
        personal = self.store.list_calendars()[0]
        event = self.store.create_event({
            "calendar_id": personal["id"], "summary": "Alert", "all_day": False,
            "date_start": datetime.date.today() + datetime.timedelta(days=2),
            "date_end": datetime.date.today() + datetime.timedelta(days=2),
            "time_start": datetime.time(9), "time_end": datetime.time(10),
            "notification_minutes": 30,
        })
        self.assertEqual(event["notification_minutes"], 30)

    def test_query_returns_event_overlapping_from_previous_day(self):
        """Date queries include multiday events that began before the range."""
        personal = self.store.list_calendars()[0]
        self.store.create_event({
            "calendar_id": personal["id"], "summary": "Conference", "all_day": True,
            "date_start": datetime.date(2026, 8, 20), "date_end": datetime.date(2026, 8, 23),
        })
        events = self.store.get_events(datetime.date(2026, 8, 22), datetime.date(2026, 8, 22))
        self.assertEqual([event["summary"] for event in events], ["Conference"])
        self.assertEqual(events[0]["date_end"], datetime.date(2026, 8, 23))

    def test_legacy_calendar_is_copied_into_personal(self):
        """A legacy calendar is copied into Personal without deleting its source."""
        legacy_root = Path(self.temp.name) / "legacy"
        legacy_root.mkdir()
        original = self.store._new_calendar().to_ical()
        (legacy_root / "calendar.ics").write_bytes(original)
        migrated = LocalStore(legacy_root)
        self.assertEqual((legacy_root / "calendar.ics").read_bytes(), original)
        self.assertTrue((legacy_root / "calendars" / "personal.ics").exists())
        self.assertEqual(migrated.list_calendars()[0]["name"], "Personal")


class GoogleMappingTests(unittest.TestCase):
    def test_google_event_must_fit_calendar_sync_range(self):
        today = datetime.date(2026, 8, 24)
        calendar = {"sync_range": "restricted"}
        self.assertTrue(google_event_fits_sync_range(
            calendar, today, today + datetime.timedelta(days=93), today
        ))
        self.assertFalse(google_event_fits_sync_range(
            calendar, today, today + datetime.timedelta(days=94), today
        ))
        self.assertFalse(google_event_fits_sync_range(
            {"sync_range": "too-big"}, today, today, today
        ))

    def test_google_event_pages_request_the_api_maximum(self):
        """Event pagination uses Google's largest authorized page size."""
        self.assertEqual(EVENTS_PAGE_SIZE, 2500)
        calls = []
        responses = iter([
            {"items": [{"id": "first"}], "nextPageToken": "next"},
            {"items": [{"id": "second"}]},
        ])

        class Request:
            def execute(self):
                return next(responses)

        class Events:
            def list(self, **arguments):
                calls.append(arguments)
                return Request()

        class Service:
            def events(self):
                return Events()

        stats = {"event_list_requests": 0, "events": 0}
        events, paginated = GoogleBackend._fetch_events(
            Service(), "calendar-id", datetime.date(2026, 1, 1),
            datetime.date(2026, 12, 31), stats
        )
        self.assertFalse(paginated)
        self.assertEqual([event["id"] for event in events], ["first", "second"])
        self.assertEqual([call["maxResults"] for call in calls],
                         [EVENTS_PAGE_SIZE, EVENTS_PAGE_SIZE])
        self.assertEqual([call["pageToken"] for call in calls], [None, "next"])
        self.assertEqual(stats, {"event_list_requests": 2, "events": 2})

    def test_paginated_normal_range_switches_calendar_to_limited_range(self):
        """A dense calendar is retried and persisted with the limited range."""
        event_calls = []

        class Request:
            def __init__(self, response):
                self.response = response

            def execute(self):
                return self.response

        class CalendarList:
            def list(self, **_arguments):
                return Request({"items": [{
                    "id": "dense", "summary": "Dense", "selected": True,
                    "accessRole": "owner",
                }]})

        class Events:
            def list(self, **arguments):
                event_calls.append(arguments)
                if len(event_calls) == 1:
                    return Request({
                        "items": [{"id": "discarded"}],
                        "nextPageToken": "another-page",
                    })
                return Request({"items": [{"id": "kept"}]})

        class Service:
            def calendarList(self):
                return CalendarList()

            def events(self):
                return Events()

        backend = object.__new__(GoogleBackend)
        backend.accounts = [{
            "id": "account", "calendars": [{
                "id": "dense", "name": "Dense", "visible": True,
                "access_role": "owner", "sync_range": "normal",
            }], "events": [],
        }]
        backend._services = {"account": Service()}
        backend._credentials = {}
        backend._errors = {}
        backend._save = lambda: None

        normal = (datetime.date(2026, 1, 1), datetime.date(2028, 1, 1))
        limited = (datetime.date(2026, 2, 1), datetime.date(2027, 2, 1))
        self.assertEqual(backend.refresh(*normal, limited), [])

        calendar = backend.accounts[0]["calendars"][0]
        self.assertEqual(calendar["sync_range"], "limited")
        self.assertEqual([event["id"] for event in backend.accounts[0]["events"]],
                         ["kept"])
        self.assertEqual(len(event_calls), 2)
        self.assertEqual(event_calls[0]["orderBy"], "startTime")
        self.assertNotEqual(event_calls[0]["timeMax"], event_calls[1]["timeMax"])
        self.assertEqual(backend.last_refresh_stats["limited_calendars"], 1)

    def test_paginated_restricted_range_marks_calendar_too_big(self):
        """All cached events are removed when even the restricted range paginates."""
        event_calls = []

        class Request:
            def __init__(self, response):
                self.response = response

            def execute(self):
                return self.response

        class CalendarList:
            def list(self, **_arguments):
                return Request({"items": [{
                    "id": "dense", "summary": "Dense", "selected": True,
                    "accessRole": "owner",
                }]})

        class Events:
            def list(self, **arguments):
                event_calls.append(arguments)
                return Request({
                    "items": [{"id": f"discarded-{len(event_calls)}"}],
                    "nextPageToken": "another-page",
                })

        class Service:
            def calendarList(self):
                return CalendarList()

            def events(self):
                return Events()

        backend = object.__new__(GoogleBackend)
        backend.accounts = [{
            "id": "account", "calendars": [{
                "id": "dense", "name": "Dense", "visible": True,
                "access_role": "owner", "sync_range": "normal",
            }],
            "events": [{"id": "cached", "_calendar_id": "dense",
                        "start": {"date": "2030-01-01"},
                        "end": {"date": "2030-01-02"}}],
        }]
        backend._services = {"account": Service()}
        backend._credentials = {}
        backend._errors = {}
        backend._save = lambda: None

        normal = (datetime.date(2026, 1, 1), datetime.date(2028, 1, 1))
        limited = (datetime.date(2026, 2, 1), datetime.date(2027, 2, 1))
        restricted = (datetime.date(2026, 2, 1), datetime.date(2026, 5, 1))
        self.assertEqual(backend.refresh(*normal, limited, restricted), [])

        calendar = backend.accounts[0]["calendars"][0]
        self.assertEqual(calendar["sync_range"], "too-big")
        self.assertEqual(backend.accounts[0]["events"], [])
        self.assertEqual(len(event_calls), 3)
        self.assertEqual(backend.last_refresh_stats["limited_calendars"], 1)
        self.assertEqual(backend.last_refresh_stats["restricted_calendars"], 1)
        self.assertEqual(backend.last_refresh_stats["too_big_calendars"], 1)

        listed = backend.list_calendars()[0]
        self.assertEqual(listed["sync_range"], "too-big")
        self.assertFalse(listed["available"])

    def test_legacy_limited_range_is_migrated(self):
        calendars = GoogleBackend._merge_calendar_preferences(
            [{"id": "dense", "limited_range": True}],
            [{"id": "dense", "summary": "Dense"}],
        )
        self.assertEqual(calendars[0]["sync_range"], "limited")

    def test_google_primary_calendar_metadata_is_preserved(self):
        """Google calendar-list merging retains the primary-calendar marker."""
        calendars = GoogleBackend._merge_calendar_preferences([], [{
            "id": "me@example.com", "summary": "me@example.com", "primary": True,
            "accessRole": "owner", "backgroundColor": "#123456",
        }])
        self.assertTrue(calendars[0]["primary"])

    def test_old_google_auth_credentials_can_be_serialized(self):
        """Credentials lacking a modern serializer still produce valid token JSON."""
        class OldCredentials:
            token = "access"
            refresh_token = "refresh"
            token_uri = "https://example.test/token"
            client_id = "client"
            client_secret = "secret"
            scopes = ("calendar",)
            expiry = datetime.datetime(2026, 8, 22, tzinfo=datetime.timezone.utc)

        import json
        saved = json.loads(GoogleBackend._credentials_json(OldCredentials()))
        self.assertEqual(saved["refresh_token"], "refresh")
        self.assertEqual(saved["scopes"], ["calendar"])
        self.assertEqual(saved["expiry"], "2026-08-22T00:00:00Z")

    def test_configured_credentials_can_override_scopes(self):
        """The bundled OAuth file may specify scopes, otherwise defaults are used."""
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "google.json"
            path.write_text('{"clockenstein_scopes": ["custom-scope"], "installed": {}}')
            self.assertEqual(GoogleBackend._scopes_for_credentials(path), ["custom-scope"])
            path.write_text('{"installed": {}}')
            self.assertEqual(GoogleBackend._scopes_for_credentials(path), SCOPES)

    def test_all_day_end_is_exclusive(self):
        """A one-day all-day event uses Google's exclusive next-day end date."""
        body = event_dict_to_google({"summary": "Day off", "all_day": True,
                                     "date_start": datetime.date(2026, 8, 22),
                                     "date_end": datetime.date(2026, 8, 22)})
        self.assertEqual(body["end"]["date"], "2026-08-23")

    def test_multi_day_all_day_end_is_exclusive(self):
        """A multiday all-day event advances its inclusive end for Google."""
        body = event_dict_to_google({"summary": "Trip", "all_day": True,
                                     "date_start": datetime.date(2026, 8, 22),
                                     "date_end": datetime.date(2026, 8, 25)})
        self.assertEqual(body["end"]["date"], "2026-08-26")

    def test_new_google_events_override_defaults_with_notification_off(self):
        """New Google events explicitly disable calendar-default reminders."""
        body = event_dict_to_google({"summary": "Quiet", "all_day": True,
                                     "date_start": datetime.date(2027, 8, 22),
                                     "date_end": datetime.date(2027, 8, 22)})
        self.assertEqual(body["reminders"], {"useDefault": False, "overrides": []})
        self.assertNotIn("reminders", event_dict_to_google(
            {"summary": "Edit", "all_day": True,
             "date_start": datetime.date(2027, 8, 22),
             "date_end": datetime.date(2027, 8, 22)}, include_reminders=False))

    def test_google_calendar_defaults_resolve_to_one_upcoming_notification(self):
        """Google defaults become the chronologically earliest popup still to come."""
        start = datetime.date.today() + datetime.timedelta(days=30)
        raw = {"id": "g1", "summary": "Future", "start": {"date": start.isoformat()},
               "end": {"date": (start + datetime.timedelta(days=1)).isoformat()},
               "reminders": {"useDefault": True}}
        calendar = {"id": "primary", "name": "Personal", "color": "#123456",
                    "access_role": "owner", "default_reminders": [
                        {"method": "popup", "minutes": 60},
                        {"method": "popup", "minutes": 1440}]}
        event = google_event_to_dict(raw, calendar, {"id": "me.test"}, True)
        self.assertEqual(event["notification_minutes"], 1440)

    def test_offline_google_event_is_cached_and_read_only(self):
        """Cached Google events are marked unavailable for offline editing."""
        raw = {"id": "g1", "summary": "Cached", "start": {"date": "2026-08-22"},
               "end": {"date": "2026-08-23"}}
        calendar = {"id": "primary", "name": "Personal", "color": "#123456",
                    "access_role": "owner"}
        event = google_event_to_dict(raw, calendar, {"id": "me@example.com"}, False)
        self.assertTrue(event["cached"])
        self.assertFalse(event["editable"])
        self.assertEqual(event["date_end"], datetime.date(2026, 8, 22))


if __name__ == "__main__":
    unittest.main()
