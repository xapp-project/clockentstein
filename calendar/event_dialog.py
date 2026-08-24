import datetime
from typing import Optional

import gi
gi.require_version("Gtk", "3.0")
from gi.repository import Gtk
from xapp.util import l10n

_ = l10n("clockenstein")

from store import CalendarManager
from backends.google import google_event_fits_sync_range


class _DatePicker(Gtk.MenuButton):
    def __init__(self):
        super().__init__()
        self.label = Gtk.Label()
        self.add(self.label)
        self.calendar = Gtk.Calendar()
        popover = Gtk.Popover.new(self)
        popover.add(self.calendar)
        self.set_popover(popover)
        self.calendar.connect("day-selected", self._on_day_selected)
        self.set_date(datetime.date.today())
        popover.show_all()

    def set_date(self, date):
        self.calendar.select_month(date.month - 1, date.year)
        self.calendar.select_day(date.day)
        self.label.set_text(date.strftime("%x"))

    def get_date(self):
        year, month, day = self.calendar.get_date()
        return datetime.date(year, month + 1, day)

    def _on_day_selected(self, _calendar):
        self.label.set_text(self.get_date().strftime("%x"))
        popover = self.get_popover()
        if popover.get_visible():
            popover.popdown()


def _format_time_spin(spin):
    spin.set_text(f"{spin.get_value_as_int():02d}")
    return True


def _time_picker():
    box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=3)
    hour = Gtk.SpinButton.new_with_range(0, 23, 1)
    minute = Gtk.SpinButton.new_with_range(0, 59, 1)
    for spin in (hour, minute):
        spin.set_numeric(True)
        spin.set_wrap(True)
        spin.set_width_chars(2)
        spin.connect("output", _format_time_spin)
    box.pack_start(hour, False, False, 0)
    box.pack_start(Gtk.Label(label=":"), False, False, 0)
    box.pack_start(minute, False, False, 0)
    return box, hour, minute


class EventDialog(Gtk.Dialog):
    def __init__(
        self,
        parent: Gtk.Window,
        store: CalendarManager,
        event: Optional[dict] = None,
        default_date: Optional[datetime.date] = None,
        calendar_options: Optional[list] = None,
    ):
        is_new = event is None
        editable = is_new or bool(event.get("editable", True))
        super().__init__(
            title=_("New Event") if is_new else (_("Event Details")),
            transient_for=parent,
            modal=True,
        )
        self.store = store
        self.event = event or {}
        self.is_new = is_new
        self.editable = editable
        self._populating = True
        self._adjusting_end = False
        self.calendar_options = (calendar_options if is_new and calendar_options is not None else
                                 store.writable_calendars() if is_new else [self.event])

        self.set_default_size(420, -1)
        self.add_button(_("Cancel") if editable else _("Close"), Gtk.ResponseType.CANCEL)
        if not is_new and editable:
            del_btn = self.add_button(_("Delete"), Gtk.ResponseType.REJECT)
            del_btn.get_style_context().add_class("destructive-action")
            del_btn.connect("clicked", self._on_delete)
        if editable:
            save_btn = self.add_button(_("Save"), Gtk.ResponseType.OK)
            save_btn.get_style_context().add_class("suggested-action")
            self.set_default_response(Gtk.ResponseType.OK)

        self._build_form()
        self._populate(default_date)
        self._populating = False
        self.connect("response", self._on_response)
        if not editable:
            self._set_form_sensitive(False)

    def _build_form(self):
        box = self.get_content_area()
        box.set_spacing(8)
        box.set_margin_top(12)
        box.set_margin_bottom(4)
        box.set_margin_start(16)
        box.set_margin_end(16)

        grid = Gtk.Grid()
        grid.set_column_spacing(12)
        grid.set_row_spacing(8)
        box.pack_start(grid, True, True, 0)

        def lbl(text):
            l = Gtk.Label(label=text)
            l.set_xalign(1.0)
            l.get_style_context().add_class("dim-label")
            return l

        grid.attach(lbl(_("Title")), 0, 0, 1, 1)
        self.title_entry = Gtk.Entry()
        self.title_entry.set_hexpand(True)
        self.title_entry.set_activates_default(True)
        grid.attach(self.title_entry, 1, 0, 2, 1)

        grid.attach(lbl(_("Calendar")), 0, 1, 1, 1)
        self.calendar_model = Gtk.ListStore(str, str)
        for cal in self.calendar_options:
            provider = cal.get("provider", "local")
            owner = _("Local") if provider == "local" else cal.get("account_name", cal.get("account_id", "Google"))
            self.calendar_model.append([
                cal.get("color", cal.get("calendar_color", "#2aa198")),
                f"{cal.get('name', cal.get('calendar_name', _('Calendar')))} — {owner}",
            ])
        self.calendar_combo = Gtk.ComboBox.new_with_model(self.calendar_model)
        color_cell = Gtk.CellRendererText()
        color_cell.set_property("text", "●")
        color_cell.set_property("scale", 1.25)
        self.calendar_combo.pack_start(color_cell, False)
        self.calendar_combo.add_attribute(color_cell, "foreground", 0)
        text_cell = Gtk.CellRendererText()
        self.calendar_combo.pack_start(text_cell, True)
        self.calendar_combo.add_attribute(text_cell, "text", 1)
        self.calendar_combo.set_active(0)
        self.calendar_combo.set_sensitive(self.is_new)
        grid.attach(self.calendar_combo, 1, 1, 2, 1)

        grid.attach(lbl(_("All day")), 0, 2, 1, 1)
        self.allday_switch = Gtk.Switch()
        self.allday_switch.set_halign(Gtk.Align.START)
        self.allday_switch.connect("notify::active", self._on_allday_toggled)
        grid.attach(self.allday_switch, 1, 2, 1, 1)

        grid.attach(lbl(_("Start")), 0, 3, 1, 1)
        start_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        self.date_picker = _DatePicker()
        start_box.pack_start(self.date_picker, False, False, 0)
        self.start_time, self.start_hour, self.start_minute = _time_picker()
        start_box.pack_start(self.start_time, False, False, 0)
        grid.attach(start_box, 1, 3, 2, 1)

        grid.attach(lbl(_("End")), 0, 4, 1, 1)
        end_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        self.end_date_picker = _DatePicker()
        end_box.pack_start(self.end_date_picker, False, False, 0)
        self.end_time, self.end_hour, self.end_minute = _time_picker()
        end_box.pack_start(self.end_time, False, False, 0)
        grid.attach(end_box, 1, 4, 2, 1)

        self.date_picker.calendar.connect("day-selected", self._on_start_changed)
        self.start_hour.connect("value-changed", self._on_start_changed)
        self.start_minute.connect("value-changed", self._on_start_changed)
        self.end_date_picker.calendar.connect("day-selected", self._on_end_changed)
        self.end_hour.connect("value-changed", self._on_end_changed)
        self.end_minute.connect("value-changed", self._on_end_changed)

        grid.attach(lbl(_("Location")), 0, 5, 1, 1)
        self.location_entry = Gtk.Entry()
        self.location_entry.set_hexpand(True)
        self.location_entry.set_placeholder_text(_("Optional"))
        grid.attach(self.location_entry, 1, 5, 2, 1)

        grid.attach(lbl(_("Notes")), 0, 6, 1, 1)
        self.desc_view = Gtk.TextView()
        self.desc_view.set_wrap_mode(Gtk.WrapMode.WORD_CHAR)
        self.desc_view.set_left_margin(8)
        self.desc_view.set_right_margin(8)
        self.desc_view.set_top_margin(6)
        self.desc_view.set_bottom_margin(6)
        scroll = Gtk.ScrolledWindow()
        scroll.set_size_request(-1, 72)
        scroll.set_shadow_type(Gtk.ShadowType.IN)
        scroll.add(self.desc_view)
        grid.attach(scroll, 1, 6, 2, 1)

        self.status_label = Gtk.Label(label="")
        self.status_label.get_style_context().add_class("error")
        box.pack_start(self.status_label, False, False, 0)

        box.show_all()

    def _populate(self, default_date):
        ev = self.event
        self.title_entry.set_text(ev.get("summary", ""))
        self.location_entry.set_text(ev.get("location", ""))
        self.desc_view.get_buffer().set_text(ev.get("description", ""))

        all_day = ev.get("all_day", True)
        self.allday_switch.set_active(all_day)

        date = ev.get("date_start") or default_date or datetime.date.today()
        start_time = ev.get("time_start") or datetime.datetime.now().replace(
            minute=0, second=0, microsecond=0).time()
        default_end = datetime.datetime.combine(date, start_time) + datetime.timedelta(hours=1)
        end_time = ev.get("time_end") or default_end.time()
        end_date = ev.get("date_end") or (date if all_day else default_end.date())
        self.date_picker.set_date(date)
        self.end_date_picker.set_date(end_date)
        self.start_hour.set_value(start_time.hour)
        self.start_minute.set_value(start_time.minute)
        self.end_hour.set_value(end_time.hour)
        self.end_minute.set_value(end_time.minute)

        self._on_allday_toggled(self.allday_switch, None)

    def _on_allday_toggled(self, switch, _param):
        timed = self.editable and not switch.get_active()
        self.start_time.set_sensitive(timed)
        self.end_time.set_sensitive(timed)
        if timed:
            self._ensure_valid_end()

    def _on_start_changed(self, _widget):
        self._ensure_valid_end()

    def _on_end_changed(self, _widget):
        self._ensure_valid_end()

    def _ensure_valid_end(self):
        if self._populating or self._adjusting_end:
            return
        start_date = self.date_picker.get_date()
        end_date = self.end_date_picker.get_date()
        if self.allday_switch.get_active():
            if end_date < start_date:
                self._adjusting_end = True
                self.end_date_picker.set_date(start_date)
                self._adjusting_end = False
            return
        start = datetime.datetime.combine(
            start_date, datetime.time(self.start_hour.get_value_as_int(),
                                      self.start_minute.get_value_as_int()))
        end = datetime.datetime.combine(
            end_date, datetime.time(self.end_hour.get_value_as_int(),
                                    self.end_minute.get_value_as_int()))
        if end <= start:
            self._set_end_datetime(start + datetime.timedelta(hours=1))

    def _set_end_datetime(self, value):
        self._adjusting_end = True
        self.end_date_picker.set_date(value.date())
        self.end_hour.set_value(value.hour)
        self.end_minute.set_value(value.minute)
        self._adjusting_end = False

    def _set_form_sensitive(self, sensitive):
        for widget in (self.title_entry, self.allday_switch, self.date_picker, self.end_date_picker,
                       self.start_time, self.end_time, self.location_entry, self.desc_view):
            widget.set_sensitive(sensitive)

    def _on_response(self, _dialog, response):
        if response == Gtk.ResponseType.OK:
            if not self._save():
                _dialog.stop_emission_by_name("response")

    def _save(self) -> bool:
        summary = self.title_entry.get_text().strip() or _("Untitled")

        self._ensure_valid_end()
        date = self.date_picker.get_date()
        end_date = self.end_date_picker.get_date()

        all_day = self.allday_switch.get_active()
        time_start = time_end = None

        if not all_day:
            time_start = datetime.time(self.start_hour.get_value_as_int(),
                                       self.start_minute.get_value_as_int())
            time_end = datetime.time(self.end_hour.get_value_as_int(),
                                     self.end_minute.get_value_as_int())

        buf = self.desc_view.get_buffer()
        data = {
            "summary":     summary,
            "location":    self.location_entry.get_text().strip(),
            "description": buf.get_text(*buf.get_bounds(), True),
            "all_day":     all_day,
            "date_start":  date,
            "date_end":    end_date,
            "time_start":  time_start,
            "time_end":    time_end,
        }
        calendar = self.calendar_options[self.calendar_combo.get_active()]
        if (calendar.get("provider") == "google"
                and not google_event_fits_sync_range(calendar, date, end_date)):
            self.status_label.set_text(
                _("The event dates are outside the sync range for %s.")
                % calendar.get("name", calendar.get("calendar_name", _("this calendar")))
            )
            return False
        data.update({"calendar_id": calendar.get("id", calendar.get("calendar_id")),
                     "provider": calendar.get("provider", "local"),
                     "account_id": calendar.get("account_id", "local")})

        try:
            if self.is_new:
                self.store.create_event(data)
            else:
                self.store.update_event(self.event["uid"], data)
        except Exception as ex:
            self.status_label.set_text(_("Error: %s") % ex)
            return False

        return True

    def _on_delete(self, _btn):
        dlg = Gtk.MessageDialog(
            transient_for=self,
            message_type=Gtk.MessageType.QUESTION,
            buttons=Gtk.ButtonsType.YES_NO,
            text=_("Delete '%s'?") % self.event.get("summary", _("Untitled")),
        )
        dlg.format_secondary_text(_("This event will be permanently deleted."))
        resp = dlg.run()
        dlg.destroy()
        if resp == Gtk.ResponseType.YES:
            try:
                self.store.delete_event(self.event["uid"], self.event.get("calendar_id"),
                                        self.event.get("provider", "local"), self.event.get("account_id"))
                self.response(Gtk.ResponseType.REJECT)
            except Exception as ex:
                self.status_label.set_text(_("Error: %s") % ex)
