import datetime
import os

import gi
gi.require_version("Gtk", "3.0")
from gi.repository import Gtk, Gdk, Gio, Pango
from xapp.threading import run_async, run_idle
from xapp.util import l10n

_ = l10n("clockenstein")

from event_dialog import EventDialog
from store import CalendarManager
from views.month_view import MonthView
from views.week_view import WeekView
from views.day_view import DayView


class MainWindow(Gtk.Window):
    def __init__(self, store: CalendarManager):
        super().__init__(title=_("Calendar"))
        self.store = store
        self.settings = Gio.Settings.new("org.x.clockenstein.Calendar")
        width = self.settings.get_int("window-width")
        height = self.settings.get_int("window-height")
        self.set_default_size(width, height)
        self.set_position(Gtk.WindowPosition.CENTER)
        self.set_icon_name("clockenstein-calendar")
        self.today = datetime.date.today()
        self.current_date = self.today
        saved_view = self.settings.get_string("default-view")
        self._active_view = saved_view.title() if saved_view in ("month", "week", "day") else "Month"
        self._refreshing = False
        self._build_ui()
        geometry = Gdk.Geometry()
        geometry.min_width = 640
        geometry.min_height = 460
        self.set_geometry_hints(None, geometry, Gdk.WindowHints.MIN_SIZE)
        self.connect("configure-event", self._on_configure)
        self._refresh(refresh_remote=self.store.has_remote_accounts)

    def _build_ui(self):
        vbox = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        self.add(vbox)
        header = Gtk.HeaderBar()
        header.set_show_close_button(True)
        header.set_title(_("Calendar"))
        self.set_titlebar(header)

        nav = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=0)
        nav.get_style_context().add_class("linked")
        for icon, callback in (("go-previous-symbolic", lambda _: self._navigate(-1)),
                               (None, lambda _: self._go_today()),
                               ("go-next-symbolic", lambda _: self._navigate(1))):
            button = (Gtk.Button.new_from_icon_name(icon, Gtk.IconSize.BUTTON)
                      if icon else Gtk.Button(label=_("Today")))
            button.connect("clicked", callback)
            nav.pack_start(button, False, False, 0)
        header.pack_start(nav)

        self.date_label = Gtk.Label()
        self.date_label.get_style_context().add_class("clockenstein-date-label")
        header.set_custom_title(self.date_label)

        view_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=0)
        view_box.get_style_context().add_class("linked")
        self.view_buttons = {}
        for name, label in (("Month", _("Month")), ("Week", _("Week")), ("Day", _("Day"))):
            button = Gtk.ToggleButton(label=label)
            button.connect("toggled", self._on_view_toggle, name)
            view_box.pack_start(button, False, False, 0)
            self.view_buttons[name] = button
        header.pack_end(view_box)

        new_button = Gtk.Button.new_from_icon_name("list-add-symbolic", Gtk.IconSize.BUTTON)
        new_button.set_tooltip_text(_("New event (Ctrl+N)"))
        new_button.connect("clicked", lambda _: self._new_event())
        header.pack_end(new_button)
        self.refresh_button = Gtk.Button.new_from_icon_name("view-refresh-symbolic", Gtk.IconSize.BUTTON)
        self.refresh_button.set_tooltip_text(_("Refresh online calendars"))
        self.refresh_button.connect("clicked", lambda _: self._refresh(refresh_remote=True))
        header.pack_end(self.refresh_button)
        self.spinner = Gtk.Spinner()
        self.spinner.set_no_show_all(True)
        self.spinner.hide()
        header.pack_end(self.spinner)

        menu = Gtk.Menu()
        calendars_item = Gtk.MenuItem(label=_("Calendars…"))
        calendars_item.connect("activate", self._manage_calendars)
        menu.append(calendars_item)
        menu.append(Gtk.SeparatorMenuItem())
        about_item = Gtk.MenuItem(label=_("About"))
        about_item.connect("activate", self._show_about)
        menu.append(about_item)
        menu.show_all()
        menu_button = Gtk.MenuButton()
        menu_button.set_image(Gtk.Image.new_from_icon_name("open-menu-symbolic", Gtk.IconSize.BUTTON))
        menu_button.set_tooltip_text(_("Main menu"))
        menu_button.set_popup(menu)
        header.pack_end(menu_button)

        body = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=0)
        vbox.pack_start(body, True, True, 0)
        body.pack_start(self._build_sidebar(), False, False, 0)
        body.pack_start(Gtk.Separator(orientation=Gtk.Orientation.VERTICAL), False, False, 0)

        self.stack = Gtk.Stack(transition_type=Gtk.StackTransitionType.CROSSFADE,
                               transition_duration=100)
        self.stack.set_hexpand(True)
        self.stack.set_vexpand(True)
        body.pack_start(self.stack, True, True, 0)
        self.month_view = MonthView(self.today, self._on_event_activated, self._on_day_activated)
        self.week_view = WeekView(self.today, self._on_event_activated)
        self.day_view = DayView(self.today, self._on_event_activated)
        for name, view in (("Month", self.month_view), ("Week", self.week_view), ("Day", self.day_view)):
            self.stack.add_named(view, name)
        self.view_buttons[self._active_view].set_active(True)
        self.stack.set_visible_child_name(self._active_view)
        self.connect("key-press-event", self._on_key)

    def _build_sidebar(self):
        outer = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        outer.set_size_request(225, -1)
        for side in ("top", "bottom", "start", "end"):
            getattr(outer, f"set_margin_{side}")(8)
        self.mini_cal = Gtk.Calendar()
        self.mini_cal.connect("day-selected", self._on_mini_cal_selected)
        self.mini_cal.connect("month-changed", self._on_mini_cal_month)
        outer.pack_start(self.mini_cal, False, False, 0)
        outer.pack_start(Gtk.Separator(orientation=Gtk.Orientation.HORIZONTAL), False, False, 4)

        visible_scroll = Gtk.ScrolledWindow()
        visible_scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        self.visible_calendar_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        visible_scroll.add(self.visible_calendar_box)
        outer.pack_start(visible_scroll, True, True, 0)
        self.status_label = Gtk.Label()
        self.status_label.set_xalign(0)
        self.status_label.set_line_wrap(True)
        self.status_label.set_line_wrap_mode(Pango.WrapMode.WORD_CHAR)
        self.status_label.set_max_width_chars(28)
        self.status_label.set_no_show_all(True)
        self.status_label.get_style_context().add_class("clockenstein-status")
        outer.pack_start(self.status_label, False, False, 0)
        return outer

    def _show_about(self, _item):
        dialog = Gtk.AboutDialog(transient_for=self, modal=True)
        dialog.set_program_name("Clocksenstein")
        dialog.set_version("__PROJECT_VERSION__")
        dialog.set_comments(_("A calendar application for Linux desktops"))
        dialog.set_logo_icon_name("clockenstein-calendar")
        dialog.set_website("https://github.com/xapp-project/clockenstein")
        dialog.set_license_type(Gtk.License.GPL_3_0)
        dialog.run()
        dialog.destroy()

    def _populate_calendar_list(self):
        for child in self.visible_calendar_box.get_children():
            self.visible_calendar_box.remove(child)
        for cal in self._sorted_calendars():
            if cal.get("visible", True):
                self.visible_calendar_box.pack_start(self._calendar_label(cal), False, False, 0)
        self.visible_calendar_box.show_all()

        states = self.store.google.account_states() + self.store.caldav.account_states()
        offline = [s for s in states if not s.get("online")]
        if offline:
            names = ", ".join(s["name"] for s in offline)
            self._set_status(_("Some online calendars are disconnected (read-only).") + " " + names)
        else:
            self._set_status("")

    def _fill_calendar_box(self, box):
        for child in box.get_children():
            box.remove(child)
        calendars = self.store.list_calendars()
        groups = [(_("Local"), "local", [c for c in calendars if c["provider"] == "local"])]
        account_keys = []
        for cal in calendars:
            key = (cal["provider"], cal.get("account_id"))
            if cal["provider"] != "local" and key not in account_keys:
                account_keys.append(key)
        states = {
            **{("google", s["id"]): s for s in self.store.google.account_states()},
            **{("caldav", s["id"]): s for s in self.store.caldav.account_states()},
        }
        for provider, account_id in account_keys:
            state = states.get((provider, account_id), {})
            label = state.get("name", account_id)
            status = _("Online") if state.get("online") else _("Offline, read only")
            label += f" — {status}"
            groups.append((label, (provider, account_id),
                           [c for c in calendars if c["provider"] == provider
                            and c.get("account_id") == account_id]))

        for heading, group_id, items in groups:
            group_header = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=4)
            label = Gtk.Label(label=heading)
            label.set_xalign(0)
            label.set_hexpand(True)
            label.get_style_context().add_class("clockenstein-section-label")
            group_header.pack_start(label, True, True, 0)
            if group_id != "local":
                disconnect = Gtk.Button.new_from_icon_name("window-close-symbolic", Gtk.IconSize.MENU)
                disconnect.set_relief(Gtk.ReliefStyle.NONE)
                disconnect.set_tooltip_text(_("Disconnect %s") % group_id[1])
                disconnect.connect("clicked", self._disconnect_remote, group_id[0], group_id[1])
                group_header.pack_end(disconnect, False, False, 0)
            box.pack_start(group_header, False, False, 4)
            if group_id != "local":
                items = sorted(items, key=self._google_calendar_sort_key)
            previous_section = None
            for cal in items:
                if group_id != "local":
                    section = _("My Calendars") if cal.get("writable", False) else _("Other Calendars")
                    if section != previous_section:
                        section_label = Gtk.Label(label=section)
                        section_label.set_xalign(0)
                        section_label.get_style_context().add_class("clockenstein-calendar-subsection")
                        box.pack_start(section_label, False, False, 2)
                        previous_section = section
                row_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=4)
                row_box.pack_start(self._calendar_label(cal), True, True, 0)
                visibility = Gtk.Switch()
                visibility.set_active(cal.get("visible", True))
                visibility.set_valign(Gtk.Align.CENTER)
                visibility.set_tooltip_text(_("Show this calendar"))
                visibility.connect("notify::active", self._calendar_switch_toggled, cal)
                row_box.pack_end(visibility, False, False, 0)
                if cal["provider"] == "local":
                    edit = Gtk.Button.new_from_icon_name("document-edit-symbolic", Gtk.IconSize.MENU)
                    edit.set_relief(Gtk.ReliefStyle.NONE)
                    edit.set_tooltip_text(_("Edit"))
                    edit.connect("clicked", self._edit_local_calendar, cal, box,
                                 box.get_toplevel())
                    row_box.pack_end(edit, False, False, 0)
                    remove = Gtk.Button.new_from_icon_name("edit-delete-symbolic", Gtk.IconSize.MENU)
                    remove.set_relief(Gtk.ReliefStyle.NONE)
                    remove.set_tooltip_text(_("Remove"))
                    remove.connect("clicked", self._remove_local_calendar, cal, box,
                                   box.get_toplevel())
                    row_box.pack_end(remove, False, False, 0)
                box.pack_start(row_box, False, False, 0)
        box.show_all()

    def _sorted_calendars(self):
        calendars = self.store.list_calendars()
        local = [cal for cal in calendars if cal["provider"] == "local"]
        google = [cal for cal in calendars if cal["provider"] == "google"]
        account_order = {state["id"]: index for index, state in enumerate(
                         self.store.google.account_states())}
        google.sort(key=lambda cal: (
            account_order.get(cal.get("account_id"), len(account_order)),
            *self._google_calendar_sort_key(cal),
        ))
        caldav = [cal for cal in calendars if cal["provider"] == "caldav"]
        return local + google + caldav

    @staticmethod
    def _google_calendar_sort_key(cal):
        return (not cal.get("writable", False),
                not cal.get("primary", cal.get("id") == cal.get("account_id")),
                cal["name"].casefold())

    @staticmethod
    def _calendar_label(cal):
        content = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        swatch = Gtk.DrawingArea()
        swatch.set_size_request(12, 12)
        rgba = Gdk.RGBA()
        rgba.parse(cal.get("color", "#2aa198"))
        swatch.connect("draw", _draw_calendar_swatch, rgba)
        content.pack_start(swatch, False, False, 0)
        name = Gtk.Label(label=cal["name"])
        name.set_xalign(0)
        name.set_ellipsize(Pango.EllipsizeMode.END)
        content.pack_start(name, True, True, 0)
        return content

    def _manage_calendars(self, _button):
        dialog = Gtk.Dialog(title=_("Calendars"), transient_for=self, modal=True)
        add_button = Gtk.MenuButton(label=_("Add a New Calendar…"))
        add_button.set_popover(self._calendar_type_popover(add_button, dialog))
        dialog.get_action_area().pack_start(add_button, False, False, 0)
        dialog.set_default_size(420, 420)
        scroll = Gtk.ScrolledWindow()
        scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        scroll.set_border_width(12)
        calendar_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        scroll.add(calendar_box)
        dialog.get_content_area().pack_start(scroll, True, True, 0)
        self._fill_calendar_box(calendar_box)
        dialog.show_all()
        while True:
            response = dialog.run()
            if response == 1:
                self._add_local_calendar(None, dialog)
                self._fill_calendar_box(calendar_box)
            elif response == 2:
                dialog.destroy()
                self._connect_google(None)
                return
            elif response == 3:
                dialog.destroy()
                self._connect_caldav()
                return
            else:
                break
        dialog.destroy()

    def _calendar_type_popover(self, relative_to, dialog):
        popover = Gtk.Popover.new(relative_to)
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        box.set_border_width(6)
        choices = (
            (_("Local"), 1),
            ("Google", 2),
            (_("CalDAV (Nextcloud, Memotoo, etc.)"), 3),
        )
        for label, response in choices:
            button = Gtk.ModelButton(text=label)
            button.connect("clicked", self._calendar_type_selected,
                           popover, dialog, response)
            box.pack_start(button, False, False, 0)
        popover.add(box)
        box.show_all()
        return popover

    def _calendar_type_selected(self, _button, popover, dialog, response):
        popover.popdown()
        dialog.response(response)

    def _edit_local_calendar(self, _button, cal, calendar_box, parent):
        dialog = Gtk.Dialog(title=_("Edit Calendar"), transient_for=parent, modal=True)
        dialog.add_buttons(_("Cancel"), Gtk.ResponseType.CANCEL, _("Save"), Gtk.ResponseType.OK)
        box = dialog.get_content_area()
        box.set_spacing(8)
        box.set_border_width(12)
        name = Gtk.Entry()
        name.set_text(cal["name"])
        color = Gtk.ColorButton()
        rgba = Gdk.RGBA()
        rgba.parse(cal.get("color", "#2aa198"))
        color.set_rgba(rgba)
        box.pack_start(Gtk.Label(label=_("Name"), xalign=0), False, False, 0)
        box.pack_start(name, False, False, 0)
        box.pack_start(Gtk.Label(label=_("Color"), xalign=0), False, False, 0)
        box.pack_start(color, False, False, 0)
        box.show_all()
        if dialog.run() == Gtk.ResponseType.OK and name.get_text().strip():
            self.store.update_local_calendar(
                cal["id"], name.get_text().strip(), color.get_rgba().to_string()
            )
            self._fill_calendar_box(calendar_box)
            self._populate_calendar_list()
            self._update_views()
        dialog.destroy()

    def _remove_local_calendar(self, _button, cal, calendar_box, parent):
        if len(self.store.local.list_calendars()) <= 1:
            warning = Gtk.MessageDialog(
                transient_for=parent, message_type=Gtk.MessageType.INFO,
                buttons=Gtk.ButtonsType.OK, text=_("At least one local calendar is required"),
            )
            warning.run()
            warning.destroy()
            return
        confirm = Gtk.MessageDialog(
            transient_for=parent, message_type=Gtk.MessageType.WARNING,
            buttons=Gtk.ButtonsType.CANCEL, text=_("Remove %s?") % cal['name'],
        )
        confirm.add_button(_("Remove"), Gtk.ResponseType.OK)
        confirm.format_secondary_text(_("All the events from this calendar will be permanently removed."))
        response = confirm.run()
        confirm.destroy()
        if response == Gtk.ResponseType.OK:
            self.store.delete_local_calendar(cal["id"])
            self._fill_calendar_box(calendar_box)
            self._populate_calendar_list()
            self._update_views()

    def _set_status(self, message=""):
        self.status_label.set_text(message)
        self.status_label.set_visible(bool(message))

    def _calendar_switch_toggled(self, switch, _property, cal):
        self.store.set_visible(cal["provider"], cal["id"], switch.get_active(), cal.get("account_id"))
        self._populate_calendar_list()
        self._update_views()

    def _add_local_calendar(self, _button, parent=None):
        dialog = Gtk.Dialog(title=_("New Calendar"), transient_for=parent or self, modal=True)
        dialog.add_buttons(_("Cancel"), Gtk.ResponseType.CANCEL, _("Create"), Gtk.ResponseType.OK)
        box = dialog.get_content_area()
        box.set_spacing(8)
        box.set_border_width(12)
        name = Gtk.Entry()
        color = Gtk.ColorButton()
        rgba = Gdk.RGBA()
        rgba.parse("#2aa198")
        color.set_rgba(rgba)
        box.pack_start(Gtk.Label(label=_("Name"), xalign=0), False, False, 0)
        box.pack_start(name, False, False, 0)
        box.pack_start(Gtk.Label(label=_("Color"), xalign=0), False, False, 0)
        box.pack_start(color, False, False, 0)
        box.show_all()
        if dialog.run() == Gtk.ResponseType.OK and name.get_text().strip():
            self.store.create_calendar(name.get_text().strip(), color.get_rgba().to_string())
            self._populate_calendar_list()
        dialog.destroy()

    def _connect_google(self, _button=None):
        filename = os.path.join(os.path.dirname(__file__), "backends", "google.json")
        self._set_refreshing(True)
        self._set_status(_("Connecting…"))
        self._connect_worker(filename)

    @run_async
    def _connect_worker(self, filename):
        try:
            self.store.google.connect(filename, self._connection_progress)
            start, end = self._date_range()
            self._connection_progress(_("Downloading events…"))
            errors = self.store.google.refresh(start, end)
            self._remote_done(errors)
        except Exception as exc:
            self._remote_done([str(exc)])

    @run_idle
    def _connection_progress(self, message):
        print(f"Clockenstein: {message}", flush=True)
        self._set_status(message)

    def _connect_caldav(self):
        dialog = Gtk.Dialog(title="CalDAV", transient_for=self, modal=True)
        dialog.add_buttons(_("Cancel"), Gtk.ResponseType.CANCEL, _("Connect"), Gtk.ResponseType.OK)
        box = dialog.get_content_area()
        box.set_spacing(8)
        box.set_border_width(12)
        url = Gtk.Entry(placeholder_text="https://example.com/remote.php/dav/")
        username = Gtk.Entry()
        password = Gtk.Entry()
        password.set_visibility(False)
        password.set_input_purpose(Gtk.InputPurpose.PASSWORD)
        for label, entry in ((_("Server URL"), url), (_("Username"), username), (_("Password"), password)):
            box.pack_start(Gtk.Label(label=label, xalign=0), False, False, 0)
            box.pack_start(entry, False, False, 0)
        box.show_all()
        response = dialog.run()
        values = (url.get_text().strip(), username.get_text().strip(), password.get_text())
        dialog.destroy()
        if response != Gtk.ResponseType.OK:
            return
        self._set_refreshing(True)
        self._set_status(_("Connecting…"))
        self._connect_caldav_worker(*values)

    @run_async
    def _connect_caldav_worker(self, url, username, password):
        try:
            self.store.caldav.connect(url, username, password, self._connection_progress)
            start, end = self._date_range()
            self._connection_progress(_("Downloading events…"))
            errors = self.store.caldav.refresh(start, end)
            self._remote_done(errors)
        except Exception as exc:
            self._remote_done([str(exc)])

    def _disconnect_remote(self, button, provider, account_id):
        dialog = Gtk.MessageDialog(
            transient_for=self, message_type=Gtk.MessageType.QUESTION,
            buttons=Gtk.ButtonsType.YES_NO, text=_("Disconnect %s?") % account_id,
        )
        dialog.format_secondary_text(
            _("This online calendar will be disconnected and removed from the application.")
        )
        response = dialog.run()
        dialog.destroy()
        if response == Gtk.ResponseType.YES:
            if provider == "google":
                self.store.google.disconnect(account_id)
            else:
                self.store.caldav.disconnect(account_id)
            self._refresh(refresh_remote=False)

    def _navigate(self, direction):
        d = self.current_date
        if self._active_view == "Month":
            month, year = d.month + direction, d.year
            if month < 1: month, year = 12, year - 1
            if month > 12: month, year = 1, year + 1
            self.current_date = d.replace(year=year, month=month, day=min(d.day, _month_days(year, month)))
        elif self._active_view == "Week":
            self.current_date += datetime.timedelta(weeks=direction)
        else:
            self.current_date += datetime.timedelta(days=direction)
        self._sync_mini_cal()
        self._refresh(refresh_remote=self.store.has_remote_accounts)

    def _go_today(self):
        self.current_date = self.today
        self._sync_mini_cal()
        self._refresh(refresh_remote=self.store.has_remote_accounts)

    def _sync_mini_cal(self):
        d = self.current_date
        self.mini_cal.handler_block_by_func(self._on_mini_cal_selected)
        self.mini_cal.handler_block_by_func(self._on_mini_cal_month)
        self.mini_cal.select_month(d.month - 1, d.year)
        self.mini_cal.select_day(d.day)
        self.mini_cal.handler_unblock_by_func(self._on_mini_cal_selected)
        self.mini_cal.handler_unblock_by_func(self._on_mini_cal_month)

    def _on_mini_cal_selected(self, cal):
        year, month, day = cal.get_date()
        self.current_date = datetime.date(year, month + 1, day)
        self._refresh(refresh_remote=self.store.has_remote_accounts)

    def _on_mini_cal_month(self, cal):
        year, month, day = cal.get_date()
        month += 1
        self.current_date = datetime.date(year, month, min(self.current_date.day, _month_days(year, month)))
        self._refresh(refresh_remote=self.store.has_remote_accounts)

    def _on_view_toggle(self, button, name):
        if not button.get_active():
            return
        for other_name, other in self.view_buttons.items():
            if other_name != name:
                other.handler_block_by_func(self._on_view_toggle)
                other.set_active(False)
                other.handler_unblock_by_func(self._on_view_toggle)
        self._active_view = name
        self.settings.set_string("default-view", name.lower())
        self.stack.set_visible_child_name(name)
        self._refresh(refresh_remote=False)

    def _on_configure(self, _widget, event):
        if not (self.get_window().get_state() & Gdk.WindowState.MAXIMIZED):
            self.settings.set_int("window-width", event.width)
            self.settings.set_int("window-height", event.height)
        return False

    def _on_day_activated(self, date):
        self.current_date = date
        self._sync_mini_cal()
        self.view_buttons["Day"].set_active(True)

    def _on_event_activated(self, event):
        dialog = EventDialog(self, store=self.store, event=event)
        if dialog.run() in (Gtk.ResponseType.OK, Gtk.ResponseType.REJECT):
            self._refresh(refresh_remote=False)
        dialog.destroy()

    def _new_event(self):
        dialog = EventDialog(self, store=self.store, default_date=self.current_date)
        if dialog.run() == Gtk.ResponseType.OK:
            self._refresh(refresh_remote=False)
        dialog.destroy()

    def _on_key(self, _widget, event):
        if event.keyval == Gdk.KEY_n and event.state & Gdk.ModifierType.CONTROL_MASK: self._new_event()
        elif event.keyval == Gdk.KEY_t: self._go_today()
        elif event.keyval == Gdk.KEY_Left: self._navigate(-1)
        elif event.keyval == Gdk.KEY_Right: self._navigate(1)

    def _date_range(self):
        d = self.current_date
        if self._active_view == "Month":
            start = datetime.date(d.year, d.month, 1) - datetime.timedelta(days=7)
            return start, start + datetime.timedelta(days=48)
        if self._active_view == "Week":
            start = d - datetime.timedelta(days=d.weekday())
            return start, start + datetime.timedelta(days=6)
        return d, d

    def _refresh(self, refresh_remote=False):
        self._update_views()
        self._populate_calendar_list()
        if refresh_remote and not self._refreshing:
            self._set_refreshing(True)
            self._set_status(_("Connecting to online calendars…"))
            start, end = self._date_range()
            self._refresh_worker(start, end)

    @run_async
    def _refresh_worker(self, start, end):
        errors = self.store.refresh_remote(start, end)
        self._remote_done(errors)

    @run_idle
    def _remote_done(self, errors):
        self._set_refreshing(False)
        self._update_views()
        self._populate_calendar_list()
        if errors:
            self._set_status(
                _("Some online calendars are disconnected (read-only).")
                + " " + "; ".join(errors)
            )
        return False

    def _set_refreshing(self, active):
        self._refreshing = active
        self.refresh_button.set_sensitive(not active)
        if active:
            self.spinner.show()
            self.spinner.start()
        else:
            self.spinner.stop()
            self.spinner.hide()

    def _update_views(self):
        self._update_date_label()
        start, end = self._date_range()
        events = self.store.get_events(start, end)
        self.month_view.update(self.current_date, events)
        self.week_view.update(self.current_date, events)
        self.day_view.update(self.current_date, events)
        self.mini_cal.clear_marks()
        year, month, day = self.mini_cal.get_date()
        for event in self.store.get_events():
            if event["date_start"].year == year and event["date_start"].month == month + 1:
                self.mini_cal.mark_day(event["date_start"].day)

    def _update_date_label(self):
        d = self.current_date
        if self._active_view == "Month":
            text = d.strftime("%B %Y")
        elif self._active_view == "Week":
            monday = d - datetime.timedelta(days=d.weekday())
            sunday = monday + datetime.timedelta(days=6)
            text = (f"{monday.strftime('%b %-d')}–{sunday.strftime('%-d, %Y')}" if monday.month == sunday.month
                    else f"{monday.strftime('%b %-d')} – {sunday.strftime('%b %-d, %Y')}")
        else:
            text = d.strftime("%A, %B %-d, %Y")
        self.date_label.set_text(text)


def _month_days(year, month):
    import calendar
    return calendar.monthrange(year, month)[1]


def _draw_calendar_swatch(widget, cr, rgba):
    width = widget.get_allocated_width()
    height = widget.get_allocated_height()
    radius = min(width, height) / 2
    cr.set_source_rgba(rgba.red, rgba.green, rgba.blue, rgba.alpha)
    cr.arc(width / 2, height / 2, radius, 0, 2 * 3.14159265)
    cr.fill()
    return False
