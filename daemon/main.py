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
from store import CalendarManager

REFRESH_INTERVAL_SECONDS = 15 * 60
SETTINGS_SCHEMA = "org.x.clockenstein.daemon"
VERBOSE_KEY = "verbose"
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
    <signal name="Changed"/>
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
        GLib.timeout_add_seconds(REFRESH_INTERVAL_SECONDS, self._refresh_timeout)
        self._refresh_remote()

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
            self._emit_changed()
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
        self._refresh_remote()
        return GLib.SOURCE_CONTINUE

    @run_async
    def _refresh_remote(self):
        if self.refreshing:
            self._log("Skipping refresh because one is already running")
            return
        self.refreshing = True
        store = CalendarManager()
        if not store.has_remote_accounts:
            self._log("No remote accounts to refresh")
            self.refreshing = False
            return
        today = datetime.date.today()
        start = today - datetime.timedelta(days=31)
        end = today + datetime.timedelta(days=365)
        self._log(f"Refreshing remote calendars from {start} through {end}")
        try:
            errors = store.refresh_remote(start, end)
            if errors:
                self._log("Refresh completed with errors: " + "; ".join(errors))
            else:
                self._log("Refresh completed")
        finally:
            self._refresh_finished()

    @run_idle
    def _refresh_finished(self):
        self.refreshing = False
        self._emit_changed()

    def _emit_changed(self):
        if self.connection:
            self._log("Emitting Changed")
            self.connection.emit_signal(None, BUS_PATH, BUS_INTERFACE, "Changed", None)

    def _log(self, message):
        if self.verbose:
            print(f"clockenstein-daemon: {message}", flush=True)


if __name__ == "__main__":
    setproctitle("clockenstein-daemon")
    ClockensteinDaemon().run()
