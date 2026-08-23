import datetime
from typing import Callable

import gi
gi.require_version("Gtk", "3.0")
from gi.repository import Gtk, GLib, Gdk
from xapp.util import l10n

_ = l10n("clockenstein")

from formatting import WEEKDAY_NAMES
from views.colors import apply_tinted_event_color
from views.month_view import _event_has_ended, _event_tooltip
from views.day_view import (ALL_DAY_EVENT_MARGIN, ALL_DAY_HEIGHT,
                            DAY_END_MINUTE, DAY_START_MINUTE,
                            TIMELINE_HEIGHT,
                            _assign_event_columns, _draw_day_grid, _draw_now_line,
                            _minute_to_y,
                            _timed_segment_minutes, _timeline_y)

HOUR_HEIGHT = 48
START_HOUR  = 0
END_HOUR    = 24


class WeekView(Gtk.Box):
    def __init__(self, today: datetime.date, on_event: Callable, on_new_event: Callable,
                 on_select=None):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        self.today    = today
        self.on_event = on_event
        self.on_new_event = on_new_event
        self.on_select = on_select
        self.selected_date = today
        self._shows_today = True
        self._build()

    def _build(self):
        self.header = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=0)
        self.header.get_style_context().add_class("clockenstein-week-header")
        spacer = Gtk.Label()
        spacer.set_size_request(52, -1)
        self.header.pack_start(spacer, False, False, 0)
        self.day_headers: list[Gtk.Label] = []
        for i in range(7):
            lbl = Gtk.Label()
            lbl.set_hexpand(True)
            lbl.set_justify(Gtk.Justification.CENTER)
            lbl.get_style_context().add_class("clockenstein-week-day-header")
            lbl.get_style_context().add_class("clockenstein-dow-label")
            self.header.pack_start(lbl, True, True, 0)
            self.day_headers.append(lbl)
        right_spacer = Gtk.Label()
        right_spacer.set_size_request(52, -1)
        self.header.pack_end(right_spacer, False, False, 0)
        self.pack_start(self.header, False, False, 0)

        scroll = Gtk.ScrolledWindow()
        scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        self.pack_start(scroll, True, True, 0)

        body = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=0)
        scroll.add(body)
        self.timeline_body = body

        self.gutter = Gtk.Fixed()
        self.gutter.set_size_request(52, TIMELINE_HEIGHT)
        body.pack_start(self.gutter, False, False, 0)
        all_day_label = Gtk.Label(label=_("All day"))
        all_day_label.set_size_request(52, 20)
        all_day_label.set_xalign(1)
        all_day_label.get_style_context().add_class("clockenstein-time-label")
        self.gutter.put(all_day_label, 0, (ALL_DAY_HEIGHT - 20) // 2)
        for h in range(START_HOUR, END_HOUR):
            lbl = Gtk.Label(label=f"{h:02d}:00")
            lbl.set_size_request(52, 20)
            lbl.set_xalign(1)
            lbl.set_yalign(0.5)
            lbl.get_style_context().add_class("clockenstein-time-label")
            self.gutter.put(lbl, 0, _timeline_y(h * 60) - 10)
        self.now_label = Gtk.Label()
        self.now_label.set_size_request(52, 20)
        self.now_label.set_xalign(1)
        self.now_label.get_style_context().add_class("clockenstein-now-label")
        self.gutter.put(self.now_label, 0, 0)

        self.day_overlays: list[_DayColumn] = []
        for i in range(7):
            col = _DayColumn(self.on_event, self.on_new_event, self.on_select)
            body.pack_start(col, True, True, 0)
            self.day_overlays.append(col)

        self.right_gutter = Gtk.Fixed()
        self.right_gutter.set_size_request(52, TIMELINE_HEIGHT)
        body.pack_end(self.right_gutter, False, False, 0)
        right_all_day = Gtk.Label(label=_("All day"))
        right_all_day.set_size_request(52, 20)
        right_all_day.set_xalign(0)
        right_all_day.get_style_context().add_class("clockenstein-time-label")
        self.right_gutter.put(right_all_day, 0, (ALL_DAY_HEIGHT - 20) // 2)
        for hour in range(START_HOUR, END_HOUR):
            label = Gtk.Label(label=f"{hour:02d}:00")
            label.set_size_request(52, 20)
            label.set_xalign(0)
            label.set_yalign(0.5)
            label.get_style_context().add_class("clockenstein-time-label")
            self.right_gutter.put(label, 0, _timeline_y(hour * 60) - 10)
        self.right_now_label = Gtk.Label()
        self.right_now_label.set_size_request(52, 20)
        self.right_now_label.set_xalign(0)
        self.right_now_label.get_style_context().add_class("clockenstein-now-label")
        self.right_gutter.put(self.right_now_label, 0, 0)

        self.connect("map", lambda _w: GLib.idle_add(
            scroll.get_vadjustment().set_value, ALL_DAY_HEIGHT + 7 * HOUR_HEIGHT
        ))
        GLib.timeout_add_seconds(30, self._update_now_line)

    def update(self, current_date: datetime.date, events: list[dict], selected_date=None):
        if selected_date is not None:
            self.selected_date = selected_date
        start = current_date - datetime.timedelta(days=current_date.weekday())
        week = [start + datetime.timedelta(days=i) for i in range(7)]
        self._shows_today = self.today in week

        for lbl, day in zip(self.day_headers, week):
            text = f"{WEEKDAY_NAMES[day.weekday()]}\n{day.day}"
            if day == self.today:
                lbl.set_markup(f"<b>{text}</b>")
                lbl.get_style_context().add_class("clockenstein-today-header")
            else:
                lbl.set_text(text)
                lbl.get_style_context().remove_class("clockenstein-today-header")
            if day == self.selected_date:
                lbl.get_style_context().add_class("clockenstein-selected-week-day")
            else:
                lbl.get_style_context().remove_class("clockenstein-selected-week-day")

        by_date: dict[datetime.date, list[dict]] = {}
        for ev in events:
            day = ev["date_start"]
            while day <= ev.get("date_end", day):
                by_date.setdefault(day, []).append(ev)
                day += datetime.timedelta(days=1)

        week_has_events = any(by_date.get(day) for day in week)

        for header, col, day in zip(self.day_headers, self.day_overlays, week):
            col.show_now = self._shows_today
            col.is_today = day == self.today
            col.is_selected = day == self.selected_date
            day_events = by_date.get(day, [])
            col.set_events(day, day_events)
            has_events = bool(day_events)
            expands = has_events or not week_has_events
            header_text = f"{WEEKDAY_NAMES[day.weekday()]}\n{day.day}"
            text_width, _text_height = header.create_pango_layout(header_text).get_pixel_size()
            compact_width = text_width + 16
            requested_width = -1 if expands else compact_width
            header.set_size_request(requested_width, -1)
            header.set_hexpand(expands)
            col.set_size_request(requested_width, -1)
            col.set_hexpand(expands)
            self.header.set_child_packing(
                header, expands, True, 0, Gtk.PackType.START
            )
            self.timeline_body.set_child_packing(
                col, expands, True, 0, Gtk.PackType.START
            )

        self.show_all()
        self._update_now_line()

    def _update_now_line(self):
        now = datetime.datetime.now()
        minutes = now.hour * 60 + now.minute
        self.now_label.set_visible(self._shows_today)
        self.right_now_label.set_visible(self._shows_today)
        if self._shows_today:
            text = now.strftime("%H:%M")
            self.now_label.set_text(text)
            self.right_now_label.set_text(text)
            y = _timeline_y(minutes) - 10
            self.gutter.move(self.now_label, 0, y)
            self.right_gutter.move(self.right_now_label, 0, y)
        for column in self.day_overlays:
            column.queue_draw()
        return True


class _DayColumn(Gtk.Overlay):
    def __init__(self, on_event, on_new_event, on_select=None):
        super().__init__()
        self.on_event = on_event
        self.on_new_event = on_new_event
        self.on_select = on_select
        self.day = None
        self.add_events(Gdk.EventMask.BUTTON_PRESS_MASK)
        self.connect("button-press-event", self._on_background_click)
        self.show_now = True
        self.is_today = False
        self.is_selected = False
        self.set_hexpand(True)

        self.background = Gtk.DrawingArea()
        self.background.set_size_request(-1, TIMELINE_HEIGHT)
        self.background.connect("draw", self._draw_background)
        self.add(self.background)

        self.event_layer = Gtk.Fixed()
        self.event_layer.set_hexpand(True)
        self.event_layer.set_size_request(-1, TIMELINE_HEIGHT)
        self.event_layer.connect("size-allocate", self._position_events)
        self.add_overlay(self.event_layer)
        self._positioned_events = []
        self._position_source = None

    def _on_background_click(self, _widget, event):
        if event.button == 1 and self.day and self.on_select:
            self.on_select(self.day)
        if event.type == Gdk.EventType.DOUBLE_BUTTON_PRESS and self.day:
            self.on_new_event(self.day)
            return True
        return False

    def _draw_background(self, widget, cr):
        if self.is_today or self.is_selected:
            found, color = widget.get_style_context().lookup_color("theme_selected_bg_color")
            if found:
                alpha = 0.13 if self.is_selected else 0.07
                cr.set_source_rgba(color.red, color.green, color.blue, alpha)
                cr.paint()
        _draw_day_grid(widget, cr)
        if self.show_now:
            _draw_now_line(widget, cr)
        _draw_day_separator(widget, cr)
        return False

    def set_events(self, day, events):
        self.day = day
        for child in self.event_layer.get_children():
            self.event_layer.remove(child)
        self._positioned_events = []

        for ev in events:
            full_day = ev["all_day"] or ev["time_start"] is None
            if full_day:
                start_minutes, end_minutes = DAY_START_MINUTE, DAY_END_MINUTE
            else:
                start_minutes, end_minutes = _timed_segment_minutes(ev, day)
                if end_minutes <= start_minutes:
                    continue
            btn = _WeekEventButton()
            btn.get_style_context().add_class("clockenstein-week-event")
            btn.get_style_context().add_class("clockenstein-week-timeline-event")
            apply_tinted_event_color(btn, ev)
            if _event_has_ended(ev):
                btn.set_opacity(0.5)
            btn.connect("button-press-event",
                        lambda _widget, _click, e=ev: self.on_event(e))
            tooltip_markup = _event_tooltip(ev)
            content = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
            content.set_valign(Gtk.Align.CENTER if full_day else Gtk.Align.START)
            content.set_margin_top(5)
            content.set_margin_bottom(5)
            content.set_margin_start(7)
            content.set_margin_end(7)
            content.set_no_show_all(True)
            content.hide()
            label = Gtk.Label()
            label.set_xalign(0)
            label.set_single_line_mode(True)
            title = ev.get("summary") or _("Untitled")
            label.set_markup(f"<b>{GLib.markup_escape_text(title)}</b>")
            content.pack_start(label, False, False, 0)
            btn.add(content)
            for tooltip_target in (btn, content, label):
                tooltip_target.add_events(Gdk.EventMask.ENTER_NOTIFY_MASK |
                                          Gdk.EventMask.LEAVE_NOTIFY_MASK)
                tooltip_target.set_has_tooltip(True)
                tooltip_target.set_tooltip_markup(tooltip_markup)
                tooltip_target.connect("query-tooltip", _show_event_tooltip,
                                       tooltip_markup)
                tooltip_target.connect("enter-notify-event", _trigger_event_tooltip)
            top = ALL_DAY_EVENT_MARGIN if full_day else _timeline_y(start_minutes)
            height = (ALL_DAY_HEIGHT - 2 * ALL_DAY_EVENT_MARGIN if full_day else
                      max(1, _minute_to_y(end_minutes) - _minute_to_y(start_minutes)))
            self.event_layer.put(btn, 0, top)
            self._positioned_events.append({"widget": btn, "start": start_minutes,
                                            "end": end_minutes, "top": top,
                                            "height": height, "content": content,
                                            "label": label, "title": title,
                                            "all_day": full_day})

        _assign_event_columns([item for item in self._positioned_events if item["all_day"]])
        _assign_event_columns([item for item in self._positioned_events if not item["all_day"]])
        self.show_all()
        self._schedule_position_events()

    def _schedule_position_events(self):
        if self._position_source is None:
            self._position_source = GLib.idle_add(self._position_events_after_allocate)

    def _position_events_after_allocate(self):
        self._position_source = None
        allocation = self.event_layer.get_allocation()
        if allocation.width <= 1 and self.get_mapped():
            self._schedule_position_events()
            return False
        self._position_events(self.event_layer, allocation)
        return False

    def _position_events(self, _layer, allocation):
        width = max(1, allocation.width - 4)
        for item in self._positioned_events:
            column_width = width / item["columns"]
            x = 2 + round(item["column"] * column_width)
            event_width = max(1, round(column_width) - 3)
            item["widget"].set_timeline_size(event_width, item["height"])
            fitted_title = _fit_week_title(item["widget"], item["title"],
                                           max(0, event_width - 14))
            show_content = fitted_title is not None
            item["content"].set_no_show_all(not show_content)
            if show_content:
                item["label"].set_markup(
                    f"<b>{GLib.markup_escape_text(fitted_title)}</b>"
                )
                item["content"].show_all()
            else:
                item["content"].hide()
            self.event_layer.move(item["widget"], x, item["top"])


class _WeekEventButton(Gtk.EventBox):
    def __init__(self):
        super().__init__()
        self.add_events(Gdk.EventMask.ENTER_NOTIFY_MASK | Gdk.EventMask.LEAVE_NOTIFY_MASK)
        self.connect("enter-notify-event", self._on_pointer_enter)
        self.connect("leave-notify-event", self._on_pointer_leave)
        self._timeline_width = 1
        self._timeline_height = 1

    def _on_pointer_enter(self, _widget, _event):
        self.set_state_flags(Gtk.StateFlags.PRELIGHT, False)
        return False

    def _on_pointer_leave(self, _widget, _event):
        self.unset_state_flags(Gtk.StateFlags.PRELIGHT)
        return False

    def set_timeline_size(self, width, height):
        size = (max(1, width), max(1, height))
        if size != (self._timeline_width, self._timeline_height):
            self._timeline_width, self._timeline_height = size
            self.queue_resize()

    def do_get_preferred_width(self):
        return self._timeline_width, self._timeline_width

    def do_get_preferred_height(self):
        return self._timeline_height, self._timeline_height

    def do_get_preferred_height_for_width(self, _width):
        return self._timeline_height, self._timeline_height

    def do_draw(self, cr):
        allocation = self.get_allocation()
        cr.save()
        cr.rectangle(0, 0, allocation.width, allocation.height)
        cr.clip()
        result = Gtk.EventBox.do_draw(self, cr)
        cr.restore()
        return result


def _show_event_tooltip(_widget, _x, _y, _keyboard_mode, tooltip, markup):
    tooltip.set_markup(markup)
    return True


def _fit_week_title(widget, title, available_width):
    def fits(value):
        layout = widget.create_pango_layout("")
        layout.set_markup(f"<b>{GLib.markup_escape_text(value)}</b>", -1)
        width, _height = layout.get_pixel_size()
        return width <= available_width

    if fits(title):
        return title
    for length in range(len(title) - 1, 1, -1):
        candidate = title[:length].rstrip() + "·"
        if fits(candidate):
            return candidate
    return None


def _trigger_event_tooltip(widget, _event):
    Gtk.Tooltip.trigger_tooltip_query(widget.get_display())
    return False


def _draw_day_separator(widget, cr):
    width = widget.get_allocated_width()
    height = widget.get_allocated_height()
    cr.set_source_rgba(0.35, 0.35, 0.35, 0.55)
    cr.set_line_width(1)
    cr.move_to(width - 0.5, 0)
    cr.line_to(width - 0.5, height)
    cr.stroke()
    return False


def _draw_grid(widget, cr):
    return _draw_day_grid(widget, cr)


def _to_y(t: datetime.time) -> int:
    return int(((t.hour - START_HOUR) * 60 + t.minute) / 60 * HOUR_HEIGHT)


def _time_span_minutes(start, end):
    start_minutes = start.hour * 60 + start.minute
    end_minutes = end.hour * 60 + end.minute
    return max(30, end_minutes - start_minutes)
