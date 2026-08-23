import datetime
from typing import Callable

import gi
gi.require_version("Gtk", "3.0")
from gi.repository import Gtk, GLib, Pango
from xapp.util import l10n

_ = l10n("clockenstein")

from views.colors import apply_tinted_event_color

HOUR_HEIGHT = 48
DAY_START_MINUTE = 0
DAY_END_MINUTE = 24 * 60
DAY_HEIGHT = 24 * HOUR_HEIGHT
ALL_DAY_HEIGHT = 2 * HOUR_HEIGHT
ALL_DAY_EVENT_MARGIN = 4
TIMELINE_HEIGHT = ALL_DAY_HEIGHT + DAY_HEIGHT
EVENT_WIDTH = 260
EVENT_COLUMN_GAP = 4


class DayView(Gtk.Box):
    def __init__(self, today: datetime.date, on_event: Callable):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        self.today    = today
        self.current_date = today
        self.on_event = on_event
        self._positioned_events = []
        self._build()

    def _build(self):
        scroll = Gtk.ScrolledWindow()
        scroll.set_policy(Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.AUTOMATIC)
        self.pack_start(scroll, True, True, 0)

        body = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=0)
        scroll.add(body)

        self.gutter = Gtk.Fixed()
        self.gutter.set_size_request(52, TIMELINE_HEIGHT)
        body.pack_start(self.gutter, False, False, 0)
        all_day_label = Gtk.Label(label=_("All day"))
        all_day_label.set_size_request(52, 20)
        all_day_label.set_xalign(1)
        all_day_label.get_style_context().add_class("clockenstein-time-label")
        self.gutter.put(all_day_label, 0, (ALL_DAY_HEIGHT - 20) // 2)
        for h in range(24):
            lbl = Gtk.Label(label=f"{h:02d}:00")
            lbl.set_size_request(52, 20)
            lbl.set_xalign(1)
            lbl.set_yalign(0.5)
            lbl.get_style_context().add_class("clockenstein-time-label")
            # Centre the label on the same coordinate used by the grid line and
            # by events starting exactly on the hour.
            self.gutter.put(lbl, 0, _timeline_y(h * 60) - 10)
        self.now_label = Gtk.Label()
        self.now_label.set_size_request(52, 20)
        self.now_label.set_xalign(1)
        self.now_label.get_style_context().add_class("clockenstein-now-label")
        self.gutter.put(self.now_label, 0, 0)

        self.overlay = Gtk.Overlay()
        self.overlay.set_hexpand(True)
        body.pack_start(self.overlay, True, True, 0)

        self.background = Gtk.DrawingArea()
        self.background.set_size_request(-1, TIMELINE_HEIGHT)
        self.background.connect("draw", self._draw_background)
        self.overlay.add(self.background)

        self.event_layer = Gtk.Fixed()
        self.event_layer.set_hexpand(True)
        self.event_layer.set_size_request(-1, TIMELINE_HEIGHT)
        self.event_layer.connect("size-allocate", self._position_event_widgets)
        self.overlay.add_overlay(self.event_layer)

        self.connect("map", lambda _w: GLib.idle_add(
            scroll.get_vadjustment().set_value, ALL_DAY_HEIGHT + 7 * HOUR_HEIGHT
        ))
        GLib.timeout_add_seconds(30, self._update_now_line)

    def update(self, current_date: datetime.date, events: list[dict]):
        self.current_date = current_date
        day_events = [e for e in events
                      if e["date_start"] <= current_date <= e.get("date_end", e["date_start"])]

        for child in self.event_layer.get_children():
            self.event_layer.remove(child)
        self._positioned_events = []
        for ev in day_events:
            full_day_column = ev["all_day"] or ev["time_start"] is None
            if full_day_column:
                start_minutes = DAY_START_MINUTE
                end_minutes = DAY_END_MINUTE
            else:
                start_minutes, end_minutes = _timed_segment_minutes(ev, current_date)
                if end_minutes <= start_minutes:
                    continue

            btn = _DayEventButton()
            btn.get_style_context().add_class("clockenstein-week-event")
            btn.get_style_context().add_class("clockenstein-day-event")
            apply_tinted_event_color(btn, ev)
            btn.connect("clicked", lambda _, e=ev: self.on_event(e))
            content = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
            content.set_valign(Gtk.Align.CENTER if full_day_column else Gtk.Align.START)
            title, when, location = _event_label_parts(
                ev, start_minutes, end_minutes, full_day_column
            )
            if full_day_column:
                when, location = "", ""
            for value, bold in ((title, True), (when, False), (location, False)):
                if not value:
                    continue
                text = Gtk.Label()
                text.set_xalign(0)
                text.set_line_wrap(True)
                text.set_line_wrap_mode(Pango.WrapMode.WORD_CHAR)
                if bold:
                    text.set_markup(f"<b>{GLib.markup_escape_text(value)}</b>")
                else:
                    text.set_text(value)
                content.pack_start(text, False, False, 0)
            btn.add(content)
            top = ALL_DAY_EVENT_MARGIN if full_day_column else _timeline_y(start_minutes)
            height = (ALL_DAY_HEIGHT - 2 * ALL_DAY_EVENT_MARGIN if full_day_column else
                      max(1, _minute_to_y(end_minutes) - _minute_to_y(start_minutes)))
            self.event_layer.put(btn, 0, top)
            self._positioned_events.append({
                "widget": btn, "start": start_minutes, "end": end_minutes,
                "top": top, "height": height, "all_day": full_day_column,
            })

        _assign_event_columns([item for item in self._positioned_events if item["all_day"]])
        _assign_event_columns([item for item in self._positioned_events if not item["all_day"]])
        columns = max((item["columns"] for item in self._positioned_events), default=1)
        timeline_width = 8 + columns * (EVENT_WIDTH + EVENT_COLUMN_GAP)
        self.event_layer.set_size_request(timeline_width, TIMELINE_HEIGHT)
        self.background.set_size_request(timeline_width, TIMELINE_HEIGHT)

        self.show_all()
        self._position_event_widgets(self.event_layer, self.event_layer.get_allocation())
        self._update_now_line()

    def _draw_background(self, widget, cr):
        _draw_day_grid(widget, cr)
        if self.current_date == datetime.date.today():
            _draw_now_line(widget, cr)
        return False

    def _update_now_line(self):
        visible = self.current_date == datetime.date.today()
        self.now_label.set_visible(visible)
        if visible:
            now = datetime.datetime.now()
            minutes = now.hour * 60 + now.minute
            self.now_label.set_text(now.strftime("%H:%M"))
            self.gutter.move(self.now_label, 0, _timeline_y(minutes) - 10)
        self.background.queue_draw()
        return True

    def _position_event_widgets(self, _layer, allocation):
        for item in self._positioned_events:
            x = 4 + item["column"] * (EVENT_WIDTH + EVENT_COLUMN_GAP)
            item["widget"].set_timeline_height(item["height"])
            self.event_layer.move(item["widget"], x, item["top"])


class _DayEventButton(Gtk.Button):
    def __init__(self):
        super().__init__()
        self._timeline_height = 1

    def set_timeline_height(self, height):
        height = max(1, height)
        if height != self._timeline_height:
            self._timeline_height = height
            self.queue_resize()

    def do_get_preferred_width(self):
        return EVENT_WIDTH, EVENT_WIDTH

    def do_get_preferred_height(self):
        return self._timeline_height, self._timeline_height

    def do_get_preferred_height_for_width(self, _width):
        return self._timeline_height, self._timeline_height

    def do_draw(self, cr):
        allocation = self.get_allocation()
        cr.save()
        cr.rectangle(0, 0, allocation.width, allocation.height)
        cr.clip()
        result = Gtk.Button.do_draw(self, cr)
        cr.restore()
        return result


def _time_minutes(value):
    return value.hour * 60 + value.minute


def _minute_to_y(minutes):
    return round(minutes / 60 * HOUR_HEIGHT)


def _timeline_y(minutes):
    return ALL_DAY_HEIGHT + _minute_to_y(minutes)


def _timed_segment_minutes(event, day):
    start = (_time_minutes(event["time_start"])
             if day == event["date_start"] else DAY_START_MINUTE)
    end = (_time_minutes(event["time_end"])
           if day == event.get("date_end", event["date_start"]) else DAY_END_MINUTE)
    return start, end


def _event_label_parts(event, start_minutes, end_minutes, all_day):
    title = event.get("summary") or _("Untitled")
    when = _("All day") if all_day else (
        f"{_format_minutes(start_minutes)}–{_format_minutes(end_minutes)}"
    )
    return title, when, event.get("location", "")


def _format_minutes(minutes):
    if minutes == DAY_END_MINUTE:
        return "24:00"
    return f"{minutes // 60:02d}:{minutes % 60:02d}"


def _draw_day_grid(widget, cr):
    width = widget.get_allocated_width()
    cr.set_source_rgba(0.45, 0.45, 0.45, 0.32)
    cr.set_line_width(1)
    for hour in range(25):
        y = _timeline_y(hour * 60) + 0.5
        cr.move_to(0, y)
        cr.line_to(width, y)
        cr.stroke()
    cr.set_source_rgba(0.35, 0.35, 0.35, 0.75)
    cr.set_line_width(2)
    cr.move_to(0, ALL_DAY_HEIGHT)
    cr.line_to(width, ALL_DAY_HEIGHT)
    cr.stroke()


def _draw_now_line(widget, cr):
    now = datetime.datetime.now()
    y = _timeline_y(now.hour * 60 + now.minute) + 0.5
    cr.set_source_rgba(0.88, 0.10, 0.14, 0.9)
    cr.set_line_width(1)
    cr.move_to(0, y)
    cr.line_to(widget.get_allocated_width(), y)
    cr.stroke()


def _assign_event_columns(events):
    """Assign equal-width columns to each transitive group of overlaps."""
    ordered = sorted(events, key=lambda item: (item["start"], item["end"]))
    index = 0
    while index < len(ordered):
        group = [ordered[index]]
        group_end = ordered[index]["end"]
        index += 1
        while index < len(ordered) and ordered[index]["start"] < group_end:
            group.append(ordered[index])
            group_end = max(group_end, ordered[index]["end"])
            index += 1

        active = []
        column_count = 0
        for item in group:
            active = [(end, column) for end, column in active if end > item["start"]]
            occupied = {column for _end, column in active}
            column = next(candidate for candidate in range(len(group) + 1)
                          if candidate not in occupied)
            item["column"] = column
            active.append((item["end"], column))
            column_count = max(column_count, column + 1)
        for item in group:
            item["columns"] = column_count
