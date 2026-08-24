#!/usr/bin/python3
"""Small GTK client for the Clockenstein calendar D-Bus interface."""

import datetime
import sys
from pathlib import Path

import gi
gi.require_version("Gtk", "3.0")
from gi.repository import Gio, GLib, Gtk

CALENDAR_DIR = Path(__file__).resolve().parents[1] / "calendar"
sys.path.insert(0, str(CALENDAR_DIR))
from widgets.mini_calendar import MiniCalendar


BUS_NAME = "org.x.clockenstein.Calendar.Service"
BUS_PATH = "/org/x/clockenstein/Calendar/Service"
BUS_INTERFACE = "org.x.clockenstein.Calendar.Service"
EVENTS_TYPE = GLib.VariantType.new("(a(sssbxxx))")


def local_datetime(timestamp):
    return datetime.datetime.fromtimestamp(timestamp).astimezone()


class CalendarClient(Gtk.ApplicationWindow):
    def __init__(self, application):
        super().__init__(application=application, title="Clockenstein D-Bus Client")
        self.set_default_size(520, 520)
        self.events = []
        self.loaded_month = None
        self.request_serial = 0
        self.connection = Gio.bus_get_sync(Gio.BusType.SESSION, None)
        self.connection.signal_subscribe(
            BUS_NAME,
            BUS_INTERFACE,
            "Changed",
            BUS_PATH,
            None,
            Gio.DBusSignalFlags.NONE,
            self._changed,
        )

        content = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        content.set_border_width(12)
        self.add(content)

        self.calendar = MiniCalendar(datetime.date.today(), self._date_selected)
        self.calendar.set_hexpand(True)
        content.pack_start(self.calendar, False, False, 0)

        self.heading = Gtk.Label(xalign=0)
        self.heading.get_style_context().add_class("title")
        content.pack_start(self.heading, False, False, 0)

        scroll = Gtk.ScrolledWindow()
        scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        scroll.set_vexpand(True)
        content.pack_start(scroll, True, True, 0)

        self.event_list = Gtk.ListBox()
        self.event_list.set_selection_mode(Gtk.SelectionMode.NONE)
        self.event_list.set_activate_on_single_click(True)
        self.event_list.connect("row-activated", self._event_activated)
        scroll.add(self.event_list)

        self.status = Gtk.Label(xalign=0)
        content.pack_start(self.status, False, False, 0)

        self._query_month()

    def _selected_date(self):
        return self.calendar.date

    def _visible_range(self):
        selected = self._selected_date()
        first = datetime.date(selected.year, selected.month, 1)
        start = first - datetime.timedelta(days=first.weekday())
        return start, start + datetime.timedelta(days=42)

    @staticmethod
    def _timestamp(date):
        value = datetime.datetime.combine(date, datetime.time.min).astimezone()
        return int(value.timestamp())

    def _query_month(self):
        start, end = self._visible_range()
        self.loaded_month = self._selected_date().replace(day=1)
        self.request_serial += 1
        request_serial = self.request_serial
        self.status.set_text("Loading events…")
        self.connection.call(
            BUS_NAME,
            BUS_PATH,
            BUS_INTERFACE,
            "GetEvents",
            GLib.Variant("(xx)", (self._timestamp(start), self._timestamp(end) - 1)),
            EVENTS_TYPE,
            Gio.DBusCallFlags.NONE,
            -1,
            None,
            lambda connection, result: self._events_ready(
                connection, result, request_serial
            ),
        )

    def _events_ready(self, connection, result, request_serial):
        if request_serial != self.request_serial:
            return
        try:
            self.events = connection.call_finish(result).unpack()[0]
        except GLib.Error as error:
            self.events = []
            self.calendar.set_events([])
            self.status.set_text(f"Calendar service unavailable: {error.message}")
            self._show_selected_day()
            return

        self.status.set_text(f"{len(self.events)} event(s) in the requested range")
        self.calendar.set_events([
            {
                "date_start": self._event_dates(event)[0],
                "date_end": self._event_dates(event)[1],
                "calendar_color": event[1],
            }
            for event in self.events
        ])
        self._show_selected_day()

    def _event_dates(self, event):
        _uid, _color, _summary, all_day, start, end, _modified = event
        first = local_datetime(start).date()
        last = local_datetime(end).date()
        if all_day and end > start:
            last = local_datetime(end - 1).date()
        return first, last

    def _show_selected_day(self):
        for row in self.event_list.get_children():
            row.destroy()

        selected = self._selected_date()
        self.heading.set_text(selected.strftime("%A %d %B %Y"))
        matching = [event for event in self.events
                    if self._event_dates(event)[0] <= selected <= self._event_dates(event)[1]]
        if not matching:
            row = Gtk.ListBoxRow()
            label = Gtk.Label(label="No events", xalign=0)
            label.set_margin_top(12)
            label.set_margin_bottom(12)
            row.add(label)
            row.set_activatable(False)
            self.event_list.add(row)
        else:
            matching.sort(key=lambda event: event[4])
            for event in matching:
                self.event_list.add(self._event_row(event, selected))
        self.event_list.show_all()

    def _event_row(self, event, selected):
        _uid, color, summary, all_day, start, end, _modified = event
        row = Gtk.ListBoxRow()
        row.event_date = selected
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=3)
        box.set_border_width(10)
        row.add(box)
        title = Gtk.Label(xalign=0)
        title.set_markup(f'<span foreground="{GLib.markup_escape_text(color)}">●</span> '
                         f'<b>{GLib.markup_escape_text(summary or "(Untitled)")}</b>')
        box.pack_start(title, False, False, 0)
        if all_day:
            time_text = "All day"
        else:
            time_text = f"{local_datetime(start):%H:%M}–{local_datetime(end):%H:%M}"
        box.pack_start(Gtk.Label(label=time_text, xalign=0), False, False, 0)
        return row

    def _date_selected(self, date):
        if self.loaded_month != date.replace(day=1):
            self._query_month()
        else:
            self._show_selected_day()

    def _changed(self, *_args):
        self._query_month()

    def _event_activated(self, _listbox, row):
        if not hasattr(row, "event_date"):
            return
        try:
            Gio.Subprocess.new(
                ["clockenstein-calendar", f"--date={row.event_date.isoformat()}"],
                Gio.SubprocessFlags.NONE,
            )
        except GLib.Error as error:
            self.status.set_text(f"Could not open Clockenstein: {error.message}")


class ClientApplication(Gtk.Application):
    def __init__(self):
        super().__init__(application_id="org.x.clockenstein.Calendar.DBusClient")

    def do_activate(self):
        window = self.props.active_window or CalendarClient(self)
        window.show_all()
        window.present()


if __name__ == "__main__":
    ClientApplication().run(sys.argv)
