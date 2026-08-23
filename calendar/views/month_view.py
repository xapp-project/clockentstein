import datetime
from typing import Callable

import gi
gi.require_version("Gtk", "3.0")
from gi.repository import Gtk, Gdk, GLib
from xapp.util import l10n

_ = l10n("clockenstein")

from views.colors import apply_tinted_event_color

EVENT_HEIGHT = 22
EVENT_GAP = 3
DAY_HEADER_HEIGHT = 23
OVERFLOW_HEIGHT = 16


class MonthView(Gtk.Box):
    def __init__(self, today: datetime.date, on_event: Callable, on_day: Callable):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        self.today    = today
        self.on_event = on_event
        self.on_day   = on_day
        self.max_lanes = 1
        self.event_height = EVENT_HEIGHT
        self._last_update = None
        self._lane_reflow_source = None
        self._build()
        self.connect("size-allocate", self._on_size_allocate)

    def do_get_preferred_height(self):
        _minimum, natural = Gtk.Box.do_get_preferred_height(self)
        return 390, max(390, natural)

    def do_get_preferred_height_for_width(self, width):
        _minimum, natural = Gtk.Box.do_get_preferred_height_for_width(self, width)
        return 390, max(390, natural)

    def _build(self):
        dow = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=0)
        dow.get_style_context().add_class("clockenstein-dow-header")
        for name in (_("MON"), _("TUE"), _("WED"), _("THU"), _("FRI"), _("SAT"), _("SUN")):
            lbl = Gtk.Label(label=name)
            lbl.set_hexpand(True)
            lbl.set_xalign(1)
            lbl.set_margin_end(7)
            lbl.get_style_context().add_class("clockenstein-dow-label")
            dow.pack_start(lbl, True, True, 0)
        self.pack_start(dow, False, False, 0)

        self.grid = Gtk.Grid()
        self.grid.set_row_homogeneous(True)
        self.grid.set_column_homogeneous(True)
        self.grid.set_hexpand(True)
        self.grid.set_vexpand(True)
        self.pack_start(self.grid, True, True, 0)
        self.event_widgets = []

        self.cells: list[_DayCell] = []
        for row in range(6):
            for col in range(7):
                cell = _DayCell(self.today, self.on_event, self.on_day)
                self.grid.attach(cell, col, row, 1, 1)
                self.cells.append(cell)

    def update(self, current_date: datetime.date, events: list[dict]):
        self._last_update = (current_date, events)
        first = current_date.replace(day=1)
        grid_start = first - datetime.timedelta(days=first.weekday())

        for i, cell in enumerate(self.cells):
            day = grid_start + datetime.timedelta(days=i)
            cell.set_day(day, day.month == current_date.month)

        self._render_events(grid_start, events)
        self.show_all()

    def _render_events(self, grid_start, events):
        for widget in self.event_widgets:
            self.grid.remove(widget)
        self.event_widgets = []

        grid_end = grid_start + datetime.timedelta(days=41)
        occupied = [[set() for _lane in range(self.max_lanes)] for _row in range(6)]
        used_lanes = [0] * 6
        hidden_by_date = {}
        for event in sorted(events, key=lambda ev: (ev["date_start"], -((ev["date_end"] - ev["date_start"]).days))):
            segment_start = max(event["date_start"], grid_start)
            visible_end = min(event["date_end"], grid_end)
            while segment_start <= visible_end:
                offset = (segment_start - grid_start).days
                row, col = divmod(offset, 7)
                segment_end = min(visible_end, grid_start + datetime.timedelta(days=row * 7 + 6))
                end_col = (segment_end - (grid_start + datetime.timedelta(days=row * 7))).days
                columns = set(range(col, end_col + 1))
                lane = next((index for index, taken in enumerate(occupied[row])
                             if not taken.intersection(columns)), None)
                if lane is not None:
                    occupied[row][lane].update(columns)
                    used_lanes[row] = max(used_lanes[row], lane + 1)
                    pill = _SpanPill(event, self.on_event, segment_start == event["date_start"])
                    pill.set_size_request(-1, self.event_height)
                    pill.set_valign(Gtk.Align.START)
                    pill.set_margin_top(DAY_HEADER_HEIGHT + lane * (self.event_height + EVENT_GAP))
                    pill.set_margin_start(3)
                    pill.set_margin_end(3)
                    self.grid.attach(pill, col, row, end_col - col + 1, 1)
                    self.event_widgets.append(pill)
                else:
                    day = segment_start
                    while day <= segment_end:
                        hidden_by_date[day] = hidden_by_date.get(day, 0) + 1
                        day += datetime.timedelta(days=1)
                segment_start = segment_end + datetime.timedelta(days=1)

        for row in range(6):
            reserved = used_lanes[row] * (self.event_height + EVENT_GAP)
            for col in range(7):
                index = row * 7 + col
                day = grid_start + datetime.timedelta(days=index)
                self.cells[index].set_event_space(reserved, hidden_by_date.get(day, 0))

    def _on_size_allocate(self, _widget, _allocation):
        if self._lane_reflow_source is None:
            self._lane_reflow_source = GLib.idle_add(self._reflow_for_allocation)

    def _reflow_for_allocation(self):
        self._lane_reflow_source = None
        row_height = self.grid.get_allocated_height() // 6
        lane_height = self.event_height + EVENT_GAP
        lanes = max(1, (row_height - DAY_HEADER_HEIGHT - OVERFLOW_HEIGHT) // lane_height)
        if lanes == self.max_lanes:
            return False
        self.max_lanes = lanes
        if self._last_update:
            self.update(*self._last_update)
        return False


class _DayCell(Gtk.EventBox):
    def __init__(self, today, on_event, on_day):
        super().__init__()
        self.today    = today
        self.on_event = on_event
        self.on_day   = on_day
        self._date    = None
        self.get_style_context().add_class("clockenstein-day-cell")
        self.connect("button-press-event", self._on_click)

        outer = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=1)
        outer.set_margin_top(2)
        outer.set_margin_bottom(2)
        outer.set_margin_start(3)
        outer.set_margin_end(3)
        self.add(outer)

        self.day_lbl = Gtk.Label()
        self.day_lbl.set_xalign(1)
        self.day_lbl.get_style_context().add_class("clockenstein-day-number")
        outer.pack_start(self.day_lbl, False, False, 0)

        # Multi-day bars are drawn across the grid by MonthView.  Reserve their
        # rows with an actual widget so GTK always lays the per-day events below
        # them (a margin is not reliable when a cell is vertically constrained).
        self.span_space = Gtk.Box()
        self.span_space.set_size_request(-1, 0)
        outer.pack_start(self.span_space, False, False, 0)

        self.ev_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=1)
        outer.pack_start(self.ev_box, True, True, 0)

    def set_event_space(self, pixels, hidden):
        self.span_space.set_size_request(-1, pixels)
        for child in self.ev_box.get_children():
            self.ev_box.remove(child)
        if hidden:
            more = Gtk.Label(label=_("+%d more") % hidden)
            more.set_xalign(0)
            more.get_style_context().add_class("clockenstein-more-label")
            self.ev_box.pack_start(more, False, False, 0)

    def set_day(self, date, in_month):
        self._date = date
        ctx = self.get_style_context()
        for c in ("clockenstein-today", "clockenstein-other-month"):
            ctx.remove_class(c)
        if date == self.today:
            ctx.add_class("clockenstein-today")
        if not in_month:
            ctx.add_class("clockenstein-other-month")

        self.day_lbl.set_text(
            f"{date.day} {date.strftime('%b')}" if date.day == 1 else str(date.day)
        )

    def _on_click(self, _w, ev):
        if ev.type == Gdk.EventType.DOUBLE_BUTTON_PRESS and self._date:
            self.on_day(self._date)


class _SpanPill(Gtk.EventBox):
    def __init__(self, event, on_event, _show_start_time):
        super().__init__()
        single_timed = (not event.get("all_day") and
                        event.get("date_end", event["date_start"]) == event["date_start"])
        self.get_style_context().add_class("clockenstein-event-pill")
        self.get_style_context().add_class("clockenstein-event-span")
        if single_timed:
            self.get_style_context().add_class("clockenstein-event-dot-row")
        else:
            apply_tinted_event_color(self, event)
        if _event_has_ended(event):
            self.set_opacity(0.5)
        self.connect("button-press-event", lambda _widget, _click: on_event(event))
        self.set_tooltip_markup(_event_tooltip(event))

        content = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=5)
        if single_timed:
            content.set_margin_start(4)
            dot = Gtk.DrawingArea()
            dot.set_size_request(12, 12)
            dot.set_valign(Gtk.Align.CENTER)
            rgba = Gdk.RGBA()
            rgba.parse(event.get("calendar_color", "#2aa198"))
            dot.connect("draw", _draw_event_dot, rgba)
            content.pack_start(dot, False, False, 0)

        label = Gtk.Label()
        label.set_xalign(0)
        label.set_ellipsize(3)
        summary = event.get("summary") or _("Untitled")
        escaped_summary = GLib.markup_escape_text(summary)
        label.set_markup(f"<b>{escaped_summary}</b>")
        label.set_margin_start(0 if single_timed else 9)
        label.set_margin_end(4)
        content.pack_start(label, True, True, 0)
        self.add(content)


def _draw_event_dot(widget, cr, color):
    allocation = widget.get_allocation()
    cr.set_source_rgba(color.red, color.green, color.blue, color.alpha)
    cr.arc(allocation.width / 2, allocation.height / 2,
           min(allocation.width, allocation.height) / 2, 0, 2 * 3.14159265)
    cr.fill()
    return False


def _event_tooltip(event):
    title = GLib.markup_escape_text(event.get("summary") or _("Untitled"))
    start_date = event["date_start"]
    end_date = event.get("date_end", start_date)
    if event.get("all_day"):
        when = start_date.strftime("%d %b %Y")
        if end_date != start_date:
            when += " – " + end_date.strftime("%d %b %Y")
        when += " " + _("(all day)")
    else:
        start = start_date.strftime("%d %b %Y")
        if event.get("time_start"):
            start += " " + event["time_start"].strftime("%H:%M")
        end = end_date.strftime("%d %b %Y")
        if event.get("time_end"):
            end += " " + event["time_end"].strftime("%H:%M")
        when = f"{start} – {end}"
    properties = [f"🕒\ufe0e  {when}"]
    if event.get("calendar_name"):
        properties.append(f"📅\ufe0e  {event['calendar_name']}")
    if event.get("provider") != "local" and event.get("account_id"):
        properties.append(f"👤\ufe0e  {event.get('account_name', event['account_id'])}")
    if event.get("location"):
        properties.append(f"📍\ufe0e  {event['location']}")
    details = GLib.markup_escape_text("\n".join(properties))
    return f"<b>{title}</b>\n\n{details}"


def _event_has_ended(event):
    now = datetime.datetime.now()
    end_date = event.get("date_end", event["date_start"])
    if event.get("all_day"):
        return end_date < now.date()
    end_time = event.get("time_end") or datetime.time.max
    return datetime.datetime.combine(end_date, end_time) < now
