import calendar
import datetime

import gi
gi.require_version("Gtk", "3.0")
from gi.repository import Gtk, Gdk, GLib
from xapp.util import l10n

_ = l10n("clockenstein")


class MiniCalendar(Gtk.Box):
    def __init__(self, date, on_date_selected):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        self.get_style_context().add_class("clockenstein-mini-calendar")
        self.date = date
        self.on_date_selected = on_date_selected
        self.events = []
        self.stack = Gtk.Stack(transition_type=Gtk.StackTransitionType.SLIDE_LEFT_RIGHT,
                               transition_duration=120)
        calendar_page = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        header = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=4)
        self.month_button = Gtk.Button()
        self.month_button.set_relief(Gtk.ReliefStyle.NONE)
        self.month_label = Gtk.Label(xalign=0)
        self.month_button.add(self.month_label)
        self.month_button.set_hexpand(True)
        self.month_button.get_style_context().add_class("mini-calendar-month")
        self.month_button.connect("clicked", self._show_months)
        header.pack_start(self.month_button, True, True, 0)
        self.year_button = Gtk.Button()
        self.year_button.set_relief(Gtk.ReliefStyle.NONE)
        self.year_label = Gtk.Label()
        self.year_button.add(self.year_label)
        self.year_button.get_style_context().add_class("mini-calendar-year")
        self.year_button.connect("clicked", self._show_years)
        header.pack_start(self.year_button, False, False, 0)
        for icon, offset in (("go-previous-symbolic", -1), ("go-next-symbolic", 1)):
            button = Gtk.Button.new_from_icon_name(icon, Gtk.IconSize.MENU)
            button.set_relief(Gtk.ReliefStyle.NONE)
            button.get_style_context().add_class("mini-calendar-nav")
            button.connect("clicked", self._change_month, offset)
            header.pack_start(button, False, False, 0)
        calendar_page.pack_start(header, False, False, 0)
        weekdays = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL)
        corner = Gtk.Label()
        corner.set_size_request(22, -1)
        weekdays.pack_start(corner, False, False, 0)
        monday = datetime.date(2024, 1, 1)
        for offset in range(7):
            label = Gtk.Label(label=(monday + datetime.timedelta(days=offset)).strftime("%a").upper())
            label.set_hexpand(True)
            label.get_style_context().add_class("mini-calendar-weekday")
            weekdays.pack_start(label, True, True, 0)
        calendar_page.pack_start(weekdays, False, False, 0)
        self.weeks_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=1)
        calendar_page.pack_start(self.weeks_box, False, False, 0)
        self.stack.add_named(calendar_page, "calendar")
        selector_page = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        selector_header = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=4)
        back = Gtk.Button.new_from_icon_name("go-previous-symbolic", Gtk.IconSize.MENU)
        back.set_relief(Gtk.ReliefStyle.NONE)
        back.connect("clicked", lambda _button: self.stack.set_visible_child_name("calendar"))
        selector_header.pack_start(back, False, False, 0)
        self.selector_title = Gtk.Label(xalign=0)
        self.selector_title.get_style_context().add_class("mini-calendar-selector-title")
        selector_header.pack_start(self.selector_title, True, True, 0)
        selector_page.pack_start(selector_header, False, False, 0)
        self.selector_scroll = Gtk.ScrolledWindow()
        self.selector_scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        self.selector_scroll.set_min_content_height(205)
        self.selector_list = Gtk.ListBox()
        self.selector_list.set_activate_on_single_click(True)
        self.selector_list.connect("row-activated", self._selector_activated)
        self.selector_scroll.add(self.selector_list)
        selector_page.pack_start(self.selector_scroll, True, True, 0)
        self.stack.add_named(selector_page, "selector")
        self.pack_start(self.stack, False, False, 0)
        self._render()

    def set_date(self, date):
        if date != self.date:
            self.date = date
            self._render()

    def set_events(self, events):
        self.events = events
        self._render()

    def _show_months(self, _button):
        values = [(month, datetime.date(2024, month, 1).strftime("%B"))
                  for month in range(1, 13)]
        self._show_selector(_("Select Month"), "month", values, self.date.month)

    def _show_years(self, _button):
        first = max(1, self.date.year - 100)
        last = min(9999, self.date.year + 100)
        values = [(year, str(year)) for year in range(first, last + 1)]
        self._show_selector(_("Select Year"), "year", values, self.date.year)

    def _show_selector(self, title, kind, values, selected):
        self.selector_title.set_text(title)
        for child in self.selector_list.get_children():
            self.selector_list.remove(child)
        selected_row = None
        for value, label in values:
            row = Gtk.ListBoxRow()
            row.selector_kind = kind
            row.selector_value = value
            text = Gtk.Label(label=label, xalign=0)
            text.set_margin_start(10)
            text.set_margin_end(10)
            text.set_margin_top(5)
            text.set_margin_bottom(5)
            row.add(text)
            self.selector_list.add(row)
            if value == selected:
                selected_row = row
        self.selector_list.show_all()
        self.selector_list.select_row(selected_row)
        self.stack.set_visible_child_name("selector")
        GLib.idle_add(self._center_selector_row, selected_row)

    def _center_selector_row(self, row):
        if row is None:
            return False
        adjustment = self.selector_scroll.get_vadjustment()
        allocation = row.get_allocation()
        target = allocation.y - (adjustment.get_page_size() - allocation.height) / 2
        adjustment.set_value(max(adjustment.get_lower(),
                                 min(target, adjustment.get_upper() - adjustment.get_page_size())))
        return False

    def _selector_activated(self, _listbox, row):
        if row.selector_kind == "month":
            day = min(self.date.day,
                      calendar.monthrange(self.date.year, row.selector_value)[1])
            date = self.date.replace(month=row.selector_value, day=day)
        else:
            day = min(self.date.day,
                      calendar.monthrange(row.selector_value, self.date.month)[1])
            date = self.date.replace(year=row.selector_value, day=day)
        self.stack.set_visible_child_name("calendar")
        self._select_date(date)

    def _change_month(self, _button, offset):
        month, year = self.date.month + offset, self.date.year
        if month == 0:
            month, year = 12, year - 1
        elif month == 13:
            month, year = 1, year + 1
        day = min(self.date.day, calendar.monthrange(year, month)[1])
        self._select_date(datetime.date(year, month, day))

    def _select_date(self, date):
        self.date = date
        self._render()
        self.on_date_selected(date)

    def _render(self):
        self.month_label.set_text(self.date.strftime("%B"))
        self.year_label.set_text(str(self.date.year))
        for child in self.weeks_box.get_children():
            self.weeks_box.remove(child)
        first = datetime.date(self.date.year, self.date.month, 1)
        grid_start = first - datetime.timedelta(days=first.weekday())
        colors = self._event_colors()
        selected_week = self.date - datetime.timedelta(days=self.date.weekday())
        for week_index in range(6):
            week_start = grid_start + datetime.timedelta(weeks=week_index)
            row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL)
            row.get_style_context().add_class("mini-calendar-week")
            if week_start == selected_week:
                row.get_style_context().add_class("selected")
            week_number = Gtk.Label(label=str(week_start.isocalendar()[1]))
            week_number.set_size_request(22, -1)
            week_number.get_style_context().add_class("mini-calendar-week-number")
            row.pack_start(week_number, False, False, 0)
            for day_offset in range(7):
                date = week_start + datetime.timedelta(days=day_offset)
                button = Gtk.Button()
                button.set_relief(Gtk.ReliefStyle.NONE)
                button.set_hexpand(True)
                button.get_style_context().add_class("mini-calendar-day")
                if date.month != self.date.month:
                    button.get_style_context().add_class("other-month")
                if date == self.date:
                    button.get_style_context().add_class("selected")
                if date == datetime.date.today():
                    button.get_style_context().add_class("today")
                content = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
                content.pack_start(Gtk.Label(label=str(date.day)), False, False, 0)
                content.pack_start(_EventDots(colors.get(date, ())), False, False, 0)
                button.add(content)
                button.connect("clicked", lambda _button, value=date: self._select_date(value))
                row.pack_start(button, True, True, 0)
            self.weeks_box.pack_start(row, False, False, 0)
        self.weeks_box.show_all()

    def _event_colors(self):
        result = {}
        month_start = datetime.date(self.date.year, self.date.month, 1)
        for event in self.events:
            start = event["date_start"]
            end = event.get("date_end", start)
            day = max(start, month_start - datetime.timedelta(days=7))
            while day <= end and day <= month_start + datetime.timedelta(days=42):
                colors = result.setdefault(day, [])
                color = event.get("calendar_color", "#3584e4")
                if color not in colors and len(colors) < 4:
                    colors.append(color)
                day += datetime.timedelta(days=1)
        return result


class _EventDots(Gtk.DrawingArea):
    def __init__(self, colors):
        super().__init__()
        self.colors = colors
        self.set_size_request(-1, 5)
        self.connect("draw", self._draw)

    def _draw(self, widget, cr):
        if not self.colors:
            return False
        diameter, gap = 3, 2
        width = len(self.colors) * diameter + (len(self.colors) - 1) * gap
        x = (widget.get_allocated_width() - width) / 2
        for color in self.colors:
            rgba = Gdk.RGBA()
            rgba.parse(color)
            Gdk.cairo_set_source_rgba(cr, rgba)
            cr.arc(x + diameter / 2, 2, diameter / 2, 0, 6.283)
            cr.fill()
            x += diameter + gap
        return False
