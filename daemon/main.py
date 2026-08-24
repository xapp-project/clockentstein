#!/usr/bin/python3
import datetime
import os
import signal
import sys

import gi
from setproctitle import setproctitle

gi.require_version("Gio", "2.0")
from gi.repository import Gio, GLib
from xapp.threading import run_async, run_idle

# Calendar modules remain shared with the graphical calendar application.
CALENDAR_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "calendar")
sys.path.insert(0, CALENDAR_DIR)

from dbus import BUS_INTERFACE, BUS_NAME, BUS_PATH
from backends.google import LIMITED_RANGE, NORMAL_RANGE, RESTRICTED_RANGE
from store import CalendarManager

CALDAV_REFRESH_INTERVAL_SECONDS = 15 * 60
GOOGLE_REFRESH_INTERVAL_SECONDS = 2 * 60 * 60
GOOGLE_REFRESH_EVERY = GOOGLE_REFRESH_INTERVAL_SECONDS // CALDAV_REFRESH_INTERVAL_SECONDS
REMINDER_CHECK_INTERVAL_SECONDS = 30
SETTINGS_SCHEMA = "org.x.clockenstein.daemon"
VERBOSE_KEY = "verbose"
NOTIFICATION_MINUTES_KEY = "notification-minutes"
VERSION = "__PROJECT_VERSION__"

INTERFACE_XML = f"""
<node>
  <interface name="{BUS_INTERFACE}">
    <method name="GetEvents">
      <arg type="x" name="since" direction="in"/>
      <arg type="x" name="until" direction="in"/>
      <arg type="a(sssbxxx)" name="events" direction="out"/>
    </method>
    <method name="NotifyChanged"/>
    <method name="RefreshCalendar">
      <arg type="s" name="provider" direction="in"/>
      <arg type="s" name="account_id" direction="in"/>
      <arg type="s" name="calendar_id" direction="in"/>
    </method>
    <method name="RefreshAccount">
      <arg type="s" name="provider" direction="in"/>
      <arg type="s" name="account_id" direction="in"/>
    </method>
    <method name="RefreshRange">
      <arg type="s" name="provider" direction="in"/>
      <arg type="x" name="since" direction="in"/>
      <arg type="x" name="until" direction="in"/>
    </method>
    <signal name="Changed"/>
    <signal name="Reminder">
      <arg type="s" name="uid"/>
      <arg type="s" name="summary"/>
      <arg type="s" name="location"/>
      <arg type="s" name="description"/>
      <arg type="s" name="calendar_name"/>
      <arg type="s" name="calendar_color"/>
      <arg type="x" name="start"/>
      <arg type="b" name="all_day"/>
    </signal>
  </interface>
</node>
"""


class ClockensteinDaemon:
    def __init__(self):
        self.settings = Gio.Settings.new(SETTINGS_SCHEMA)
        self.verbose = self.settings.get_boolean(VERBOSE_KEY)
        self.settings.connect(f"changed::{VERBOSE_KEY}", self._verbose_changed)
        self.connection = None
        self.registration_id = 0
        self.refreshing = False
        self.refresh_ticks = 0
        self.google_refresh_due = False
        self.refresh_queue = []
        self.last_reminder_check = None
        self.reminder_events = []
        self.loop = GLib.MainLoop()
        self.node_info = Gio.DBusNodeInfo.new_for_xml(INTERFACE_XML)

    def _verbose_changed(self, settings, _key):
        verbose = settings.get_boolean(VERBOSE_KEY)
        if verbose:
            self.verbose = True
            self._log("Verbose logging enabled")
        else:
            self._log("Verbose logging disabled")
            self.verbose = False

    def run(self):
        print(f"clockenstein-daemon: Starting version {VERSION}", flush=True)
        self._log(f"Requesting {BUS_NAME}")
        Gio.bus_own_name(
            Gio.BusType.SESSION,
            BUS_NAME,
            Gio.BusNameOwnerFlags.NONE,
            self._bus_acquired,
            self._name_acquired,
            self._name_lost,
        )
        signal.signal(signal.SIGINT, lambda _signum, _frame: self.loop.quit())
        signal.signal(signal.SIGTERM, lambda _signum, _frame: self.loop.quit())
        self.loop.run()
        self._log("Stopped")

    def _bus_acquired(self, connection, _name):
        self._log("Connected to the session bus")
        self.connection = connection
        self.registration_id = connection.register_object(
            BUS_PATH,
            self.node_info.interfaces[0],
            self._handle_method_call,
            None,
            None,
        )

    def _name_acquired(self, _connection, _name):
        self._log(f"Acquired {BUS_NAME}")
        self.last_reminder_check = datetime.datetime.now().astimezone()
        self._reload_reminder_events()
        GLib.timeout_add_seconds(
            REMINDER_CHECK_INTERVAL_SECONDS, self._reminder_timeout
        )
        GLib.timeout_add_seconds(CALDAV_REFRESH_INTERVAL_SECONDS, self._refresh_timeout)
        self._request_refresh(refresh_google=True, refresh_caldav=True)

    def _name_lost(self, _connection, _name):
        self._log(f"Could not own {BUS_NAME}; another instance may be running")
        self.loop.quit()

    def _handle_method_call(self, _connection, _sender, _path, _interface,
                            method, parameters, invocation):
        if method == "GetEvents":
            since, until = parameters.unpack()
            events = self._events_for_range(since, until)
            self._log(f"GetEvents({since}, {until}) -> {len(events)} event(s)")
            invocation.return_value(GLib.Variant("(a(sssbxxx))", (events,)))
        elif method == "NotifyChanged":
            self._log("NotifyChanged()")
            self._reload_reminder_events()
            self._emit_changed()
            invocation.return_value(None)
        elif method == "RefreshCalendar":
            provider, account_id, calendar_id = parameters.unpack()
            if provider not in ("google", "caldav"):
                invocation.return_dbus_error(
                    f"{BUS_INTERFACE}.InvalidProvider", "Unsupported calendar provider"
                )
                return
            self._log(f"RefreshCalendar({provider}, {account_id}, {calendar_id})")
            self._request_refresh(
                refresh_google=provider == "google",
                refresh_caldav=provider == "caldav",
                target=(provider, account_id, calendar_id),
            )
            invocation.return_value(None)
        elif method == "RefreshAccount":
            provider, account_id = parameters.unpack()
            if provider not in ("google", "caldav"):
                invocation.return_dbus_error(
                    f"{BUS_INTERFACE}.InvalidProvider", "Unsupported calendar provider"
                )
                return
            self._log(f"RefreshAccount({provider}, {account_id})")
            self._request_refresh(
                refresh_google=provider == "google",
                refresh_caldav=provider == "caldav",
                target=(provider, account_id, None),
            )
            invocation.return_value(None)
        elif method == "RefreshRange":
            provider, since, until = parameters.unpack()
            if provider != "caldav":
                invocation.return_dbus_error(
                    f"{BUS_INTERFACE}.InvalidProvider",
                    "Date-range refreshes are only supported for CalDAV",
                )
                return
            date_range = (datetime.datetime.fromtimestamp(since).date(),
                          datetime.datetime.fromtimestamp(until).date())
            self._log(f"RefreshRange({provider}, {date_range[0]}, {date_range[1]})")
            self._request_refresh(refresh_google=False, refresh_caldav=True,
                                  date_range=date_range)
            invocation.return_value(None)

    def _events_for_range(self, since, until):
        start = datetime.datetime.fromtimestamp(since).date()
        end = datetime.datetime.fromtimestamp(until).date()
        store = CalendarManager()
        return [self._event_tuple(event) for event in store.get_events(start, end)]

    @staticmethod
    def _event_tuple(event):
        all_day = bool(event.get("all_day"))
        start_time = event.get("time_start") or datetime.time.min
        start = datetime.datetime.combine(event["date_start"], start_time).astimezone()
        if all_day:
            end_date = event.get("date_end", event["date_start"]) + datetime.timedelta(days=1)
            end = datetime.datetime.combine(end_date, datetime.time.min).astimezone()
        else:
            end_time = event.get("time_end") or start_time
            end = datetime.datetime.combine(
                event.get("date_end", event["date_start"]), end_time
            ).astimezone()
        uid = ":".join((event.get("provider", "local"),
                        event.get("account_id", "local"),
                        event.get("calendar_id", ""), event["uid"]))
        return (uid, event.get("calendar_color", "#2aa198"),
                event.get("summary", ""), all_day,
                int(start.timestamp()), int(end.timestamp()), 0)

    def _refresh_timeout(self):
        self.refresh_ticks += 1
        if self.refresh_ticks % GOOGLE_REFRESH_EVERY == 0:
            self.google_refresh_due = True
        self._request_refresh(refresh_google=self.google_refresh_due,
                              refresh_caldav=True)
        return GLib.SOURCE_CONTINUE

    def _reminder_timeout(self):
        now = datetime.datetime.now().astimezone()
        since = self.last_reminder_check or now
        self.last_reminder_check = now
        try:
            minutes = self.settings.get_uint(NOTIFICATION_MINUTES_KEY)
            for event in _due_notifications(self.reminder_events, since, now, minutes):
                self._emit_reminder(event)
        except Exception as exc:
            self._log(f"Could not check reminders: {exc}")
        return GLib.SOURCE_CONTINUE

    def _reload_reminder_events(self):
        try:
            self.reminder_events = CalendarManager().get_events()
        except Exception as exc:
            self._log(f"Could not reload reminders: {exc}")

    def _emit_reminder(self, event):
        if not self.connection:
            return
        uid = ":".join((event.get("provider", "local"),
                        event.get("account_id", "local"),
                        event.get("calendar_id", ""), event["uid"]))
        parameters = GLib.Variant(
            "(ssssssxb)",
            (uid, event.get("summary", ""), event.get("location", ""),
             event.get("description", ""),
             event.get("calendar_name", ""),
             event.get("calendar_color", "#2aa198"),
             int(_event_start(event).timestamp()), bool(event.get("all_day"))),
        )
        self._log(f"Emitting Reminder for {uid}")
        self.connection.emit_signal(
            None, BUS_PATH, BUS_INTERFACE, "Reminder", parameters
        )

    def _request_refresh(self, refresh_google=False, refresh_caldav=True,
                         target=None, date_range=None):
        if self.refreshing:
            request = (refresh_google, refresh_caldav, target, date_range)
            if request not in self.refresh_queue:
                self.refresh_queue.append(request)
            self._log("Queued refresh because one is already running")
            return
        self.refreshing = True
        if refresh_google:
            self.google_refresh_due = False
        self._refresh_remote(refresh_google, refresh_caldav, target, date_range)

    @run_async
    def _refresh_remote(self, refresh_google=False, refresh_caldav=True,
                        target=None, date_range=None):
        store = CalendarManager()
        if not store.has_remote_accounts:
            self._log("No remote accounts to refresh")
            self._refresh_finished()
            return
        today = datetime.date.today()
        start = (date_range[0] if date_range else
                 today - datetime.timedelta(days=NORMAL_RANGE[0]))
        end = (date_range[1] if date_range else
               today + datetime.timedelta(days=NORMAL_RANGE[1]))
        limited_start = today - datetime.timedelta(days=LIMITED_RANGE[0])
        limited_end = today + datetime.timedelta(days=LIMITED_RANGE[1])
        restricted_start = today - datetime.timedelta(days=RESTRICTED_RANGE[0])
        restricted_end = today + datetime.timedelta(days=RESTRICTED_RANGE[1])
        providers = (target[0] if target else
                     "Google and CalDAV" if refresh_google and refresh_caldav
                     else "Google" if refresh_google else "CalDAV")
        self._log(f"Refreshing {providers} calendars from {start} through {end}")
        try:
            errors = []
            if refresh_google:
                errors.extend(store.google.refresh(
                    start, end,
                    limited_range=(limited_start, limited_end),
                    restricted_range=(restricted_start, restricted_end),
                    target_account_id=target[1] if target else None,
                    target_calendar_id=target[2] if target else None,
                ))
            if refresh_caldav:
                errors.extend(store.caldav.refresh(
                    start, end,
                    target_account_id=target[1] if target else None,
                    target_calendar_id=target[2] if target else None,
                ))
            stats = store.google.last_refresh_stats
            if refresh_google and stats.get("accounts"):
                self._log(
                    "Google refresh: "
                    f"page size {stats['page_size']}, "
                    f"{stats['calendars']} calendar(s), "
                    f"{stats['limited_calendars']} limited, "
                    f"{stats['restricted_calendars']} restricted, "
                    f"{stats['too_big_calendars']} too big, "
                    f"{stats['calendar_list_requests']} calendar-list request(s), "
                    f"{stats['event_list_requests']} event-list request(s), "
                    f"{stats['events']} event(s)"
                )
            if errors:
                self._log("Refresh completed with errors: " + "; ".join(errors))
            else:
                self._log("Refresh completed")
        finally:
            self._refresh_finished()

    @run_idle
    def _refresh_finished(self):
        self.refreshing = False
        self._reload_reminder_events()
        self._emit_changed()
        if self.refresh_queue:
            refresh_google, refresh_caldav, target, date_range = self.refresh_queue.pop(0)
            self._request_refresh(refresh_google, refresh_caldav, target, date_range)

    def _emit_changed(self):
        if self.connection:
            self._log("Emitting Changed")
            self.connection.emit_signal(None, BUS_PATH, BUS_INTERFACE, "Changed", None)

    def _log(self, message):
        if self.verbose:
            print(f"clockenstein-daemon: {message}", flush=True)


def _event_start(event):
    local_tz = datetime.datetime.now().astimezone().tzinfo
    return datetime.datetime.combine(
        event["date_start"], event.get("time_start") or datetime.time.min, local_tz
    )


def _due_notifications(events, since, until, minutes):
    """Return events whose universal notification became due in the interval."""
    if until < since:
        return []
    due = []
    for event in events:
        start = _event_start(event)
        trigger = start - datetime.timedelta(minutes=minutes)
        if since < trigger <= until:
            due.append(event)
    return sorted(due, key=_event_start)


if __name__ == "__main__":
    setproctitle("clockenstein-daemon")
    ClockensteinDaemon().run()
