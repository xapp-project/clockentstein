#!/usr/bin/python3
import datetime
import math
import os
import signal

import gi
from setproctitle import setproctitle

gi.require_version("Gio", "2.0")
gi.require_version("Gdk", "3.0")
gi.require_version("GSound", "1.0")
gi.require_version("Gtk", "3.0")
from gi.repository import Gdk, Gio, GLib, GSound, Gtk, Pango

BUS_NAME = "org.x.clockenstein.Calendar.Service"
BUS_PATH = "/org/x/clockenstein/Calendar/Service"
BUS_INTERFACE = "org.x.clockenstein.Calendar.Service"
SETTINGS_SCHEMA = "org.x.clockenstein.daemon"
VERBOSE_KEY = "verbose"
MUTED_KEY = "notification-muted"
ALARM_SOUND = os.path.join(os.path.dirname(__file__), "notification.oga")


class NotificationAgent:
    def __init__(self):
        self.settings = Gio.Settings.new(SETTINGS_SCHEMA)
        self.verbose = self.settings.get_boolean(VERBOSE_KEY)
        self.settings.connect(f"changed::{VERBOSE_KEY}", self._verbose_changed)
        self.settings.connect(f"changed::{MUTED_KEY}", self._muted_changed)
        self.muted = self.settings.get_boolean(MUTED_KEY)
        self.mute_items = set()
        self.updating_mute_items = False
        self.connection = None
        self.subscription_id = 0
        self.windows = set()
        self.sound_loops = {}
        self.sound = GSound.Context()

    def run(self, test_reminder=None):
        GLib.set_prgname("org.x.clockenstein.Calendar")
        GLib.set_application_name("Calendar Reminder")
        Gtk.init(None)
        Gtk.Window.set_default_icon_name("clockenstein-calendar")
        self._log("Starting")
        self.sound.init(None)
        if test_reminder:
            GLib.idle_add(self._show_reminder, *test_reminder)
        else:
            self.connection = Gio.bus_get_sync(Gio.BusType.SESSION, None)
            self.subscription_id = self.connection.signal_subscribe(
                BUS_NAME,
                BUS_INTERFACE,
                "Reminder",
                BUS_PATH,
                None,
                Gio.DBusSignalFlags.NONE,
                self._reminder_received,
            )
            self._log("Listening for reminders")
        signal.signal(signal.SIGINT, lambda _signum, _frame: Gtk.main_quit())
        signal.signal(signal.SIGTERM, lambda _signum, _frame: Gtk.main_quit())
        Gtk.main()
        for window in list(self.windows):
            self._stop_sound_loop(window)
        if self.connection and self.subscription_id:
            self.connection.signal_unsubscribe(self.subscription_id)
        self._log("Stopped")

    def _verbose_changed(self, settings, _key):
        verbose = settings.get_boolean(VERBOSE_KEY)
        if verbose:
            self.verbose = True
            self._log("Verbose logging enabled")
        else:
            self._log("Verbose logging disabled")
            self.verbose = False

    def _reminder_received(self, _connection, _sender, _path, _interface,
                           _signal, parameters):
        (uid, summary, location, description, calendar_name, calendar_color,
         start_timestamp, all_day) = parameters.unpack()
        self._log(f"Received Reminder for {uid}")
        self._show_reminder(
            uid, summary or "Clockenstein", start_timestamp, location, description,
            calendar_name, calendar_color
        )

    def _show_reminder(self, uid, summary, start_timestamp, location, description,
                       calendar_name, calendar_color):
        window = Gtk.Window(title="Calendar Event")
        window.reminder_uid = uid
        window.set_default_size(420, -1)
        window.set_resizable(False)
        window.set_position(Gtk.WindowPosition.CENTER)
        window.set_urgency_hint(True)
        window.set_keep_above(True)
        window.set_icon_name("clockenstein-calendar")

        header = Gtk.HeaderBar()
        header.set_show_close_button(False)
        menu_button = Gtk.MenuButton()
        menu_button.set_image(Gtk.Image.new_from_icon_name(
            "open-menu-symbolic", Gtk.IconSize.BUTTON
        ))
        menu_button.set_tooltip_text("Menu")
        menu = Gtk.Menu()
        mute = Gtk.CheckMenuItem.new_with_label("Mute")
        mute.set_active(self.muted)
        mute.connect("toggled", self._mute_toggled)
        self.mute_items.add(mute)
        menu.append(mute)
        menu.show_all()
        menu_button.set_popup(menu)
        header.pack_start(menu_button)
        title = Gtk.Label(xalign=0)
        title.set_markup(
            f'<span size="x-large" weight="bold">{GLib.markup_escape_text(summary)}</span>'
        )
        title.set_line_wrap(True)
        header.set_custom_title(title)
        window.sound_icon = Gtk.Image.new_from_icon_name(
            "audio-volume-high-symbolic", Gtk.IconSize.BUTTON
        )
        window.sound_icon.set_no_show_all(True)
        window.sound_icon.set_margin_end(12)
        header.pack_end(window.sound_icon)
        header_css = Gtk.CssProvider()
        header_css.load_from_data(b"""
            headerbar {
                background-color: @theme_bg_color;
                background-image: none;
                border: none;
                box-shadow: none;
            }
        """)
        header.get_style_context().add_provider(
            header_css, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION
        )
        window.set_titlebar(header)

        accent_rgba = Gdk.RGBA()
        if not accent_rgba.parse(calendar_color):
            accent_rgba.parse("#2aa198")

        content = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        content.set_border_width(18)
        window.add(content)

        if calendar_name:
            content.pack_start(
                _calendar_detail_row(calendar_name, calendar_color), False, False, 0
            )
        time_row, time_label = _detail_row(
            "preferences-system-time-symbolic", _relative_start_label(start_timestamp),
            prominent=True
        )
        content.pack_start(time_row, False, False, 0)
        window.details_label = time_label
        window.time_icon = time_row.get_children()[0]
        window.start_timestamp = start_timestamp
        window.mute_item = mute
        window.relative_timer_id = GLib.timeout_add_seconds(
            15, self._update_relative_time, window
        )
        if location:
            location_row, _label = _detail_row(
                "mark-location-symbolic", location, dim=True
            )
            content.pack_start(location_row, False, False, 0)
        if description:
            notes_row, _label = _detail_row(
                "document-edit-symbolic", description, dim=True, max_lines=3
            )
            content.pack_start(notes_row, False, False, 0)

        accent = Gtk.DrawingArea()
        accent.set_size_request(-1, 2)
        accent.set_margin_top(4)
        accent.connect("draw", _draw_calendar_accent, accent_rgba)
        content.pack_start(accent, False, False, 0)

        open_calendar_button = Gtk.Button()
        open_calendar_button.set_image(Gtk.Image.new_from_icon_name(
            "x-office-calendar-symbolic", Gtk.IconSize.BUTTON
        ))
        open_calendar_button.set_tooltip_text("Open Calendar")
        open_calendar_button.connect(
            "clicked", self._open_calendar, start_timestamp, uid
        )

        buttons = Gtk.ButtonBox(orientation=Gtk.Orientation.HORIZONTAL)
        buttons.set_layout(Gtk.ButtonBoxStyle.END)
        buttons.set_halign(Gtk.Align.END)
        buttons.set_margin_top(6)
        buttons.set_spacing(6)
        dismiss = Gtk.Button.new_with_label("Dismiss")
        dismiss.get_style_context().add_class("destructive-action")
        snooze = Gtk.MenuButton()
        snooze_content = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        snooze_content.pack_start(Gtk.Label(label="Snooze"), False, False, 0)
        snooze_content.pack_start(Gtk.Image.new_from_icon_name(
            "pan-down-symbolic", Gtk.IconSize.MENU
        ), False, False, 0)
        snooze.add(snooze_content)
        snooze.get_style_context().add_class("suggested-action")
        snooze_menu = Gtk.Menu()
        for minutes in (1, 5, 10):
            label = f"{minutes} minute" if minutes == 1 else f"{minutes} minutes"
            item = Gtk.MenuItem.new_with_label(label)
            item.connect("activate", self._snooze_selected, window, uid, minutes)
            snooze_menu.append(item)
        snooze_menu.show_all()
        snooze.set_popup(snooze_menu)
        buttons.add(open_calendar_button)
        buttons.add(snooze)
        buttons.add(dismiss)
        content.pack_start(buttons, False, False, 0)

        self.windows.add(window)
        window.connect("destroy", self._window_destroyed)
        dismiss.connect("clicked", self._dismiss_clicked, window, uid)
        window.fade_timer_id = 0
        self._present_window(window)
        self._update_relative_time(window)
        self._start_sound_loop(window, uid)
        self._log(f"Showing reminder window for {uid}")
        return GLib.SOURCE_REMOVE

    def _window_destroyed(self, window):
        if window.fade_timer_id:
            GLib.source_remove(window.fade_timer_id)
            window.fade_timer_id = 0
        if window.relative_timer_id:
            GLib.source_remove(window.relative_timer_id)
            window.relative_timer_id = 0
        self._stop_sound_loop(window)
        self.mute_items.discard(window.mute_item)
        self.windows.discard(window)
        self._log(f"Dismissed reminder for {window.reminder_uid}")

    def _dismiss_clicked(self, _button, window, _uid):
        window.destroy()

    def _snooze_selected(self, _item, window, uid, minutes):
        self._log(f"Snoozed reminder for {uid} for {minutes} minute(s)")
        self._stop_sound_loop(window)
        window.hide()
        GLib.timeout_add_seconds(minutes * 60, self._wake_snoozed, window, uid)

    def _wake_snoozed(self, window, uid):
        if window in self.windows:
            self._log(f"Showing snoozed reminder for {uid}")
            self._present_window(window)
            self._start_sound_loop(window, uid)
        return GLib.SOURCE_REMOVE

    def _present_window(self, window):
        window.show_all()
        self._place_on_active_monitor(window)
        settings = Gtk.Settings.get_default()
        if settings and settings.get_property("gtk-enable-animations"):
            window.set_opacity(0.0)
            if window.fade_timer_id:
                GLib.source_remove(window.fade_timer_id)
            window.fade_timer_id = GLib.timeout_add(25, self._fade_in, window)
        else:
            window.set_opacity(1.0)
        window.present()

    def _fade_in(self, window):
        if window not in self.windows:
            return GLib.SOURCE_REMOVE
        opacity = min(1.0, window.get_opacity() + 0.14)
        window.set_opacity(opacity)
        if opacity >= 1.0:
            window.fade_timer_id = 0
            return GLib.SOURCE_REMOVE
        return GLib.SOURCE_CONTINUE

    @staticmethod
    def _place_on_active_monitor(window):
        display = Gdk.Display.get_default()
        seat = display.get_default_seat() if display else None
        pointer = seat.get_pointer() if seat else None
        if not pointer:
            return
        _screen, x, y = pointer.get_position()
        monitor = display.get_monitor_at_point(x, y)
        if monitor is None:
            return
        geometry = monitor.get_workarea()
        width, height = window.get_size()
        window.move(
            geometry.x + max(0, (geometry.width - width) // 2),
            geometry.y + max(0, (geometry.height - height) // 2),
        )

    def _update_relative_time(self, window):
        if window not in self.windows:
            return GLib.SOURCE_REMOVE
        relative = _relative_start_label(window.start_timestamp)
        window.details_label.set_text(relative)
        started = window.start_timestamp <= datetime.datetime.now().timestamp()
        context = window.details_label.get_style_context()
        if started:
            context.add_class("clockenstein-started")
            window.time_icon.set_from_icon_name(
                "appointment-soon-symbolic", Gtk.IconSize.BUTTON
            )
        else:
            context.remove_class("clockenstein-started")
        return GLib.SOURCE_CONTINUE

    def _open_calendar(self, _item, start_timestamp, uid):
        event_date = datetime.datetime.fromtimestamp(start_timestamp).date().isoformat()
        self._log(f"Opening calendar on {event_date} for {uid}")
        try:
            Gio.Subprocess.new(
                ["clockenstein-calendar", "--date", event_date],
                Gio.SubprocessFlags.NONE,
            )
        except GLib.Error as exc:
            self._log(f"Could not open calendar: {exc.message}")

    def _mute_toggled(self, item):
        if not self.updating_mute_items:
            self.settings.set_boolean(MUTED_KEY, item.get_active())

    def _muted_changed(self, settings, _key):
        self.muted = settings.get_boolean(MUTED_KEY)
        self.updating_mute_items = True
        for item in self.mute_items:
            item.set_active(self.muted)
        self.updating_mute_items = False
        if self.muted:
            for window in list(self.sound_loops):
                self._stop_sound_loop(window)
            self._log("Reminder sounds muted")
        else:
            for window in self.windows:
                if window.get_visible():
                    self._start_sound_loop(window, window.reminder_uid)
            self._log("Reminder sounds unmuted")

    def _start_sound_loop(self, window, uid):
        self._stop_sound_loop(window)
        if self.muted:
            return
        if not os.path.exists(ALARM_SOUND):
            self._log(f"Alarm sound not found: {ALARM_SOUND}")
            return
        cancellable = Gio.Cancellable()
        timeout_id = GLib.timeout_add_seconds(2 * 60, self._sound_limit, window, uid)
        self.sound_loops[window] = {
            "cancellable": cancellable,
            "limit_id": timeout_id,
            "replay_id": 0,
            "pulse_id": 0,
        }
        self._play_sound_iteration(window)
        self._log(f"Started alarm sound loop for {uid}")

    def _play_sound_iteration(self, window):
        state = self.sound_loops.get(window)
        if state is None:
            return
        cancellable = state["cancellable"]
        try:
            window.sound_icon.show()
            window.sound_icon.set_opacity(1.0)
            state["pulse_id"] = GLib.timeout_add(
                500, self._pulse_sound_icon, window
            )
            self.sound.play_full(
                {GSound.ATTR_MEDIA_FILENAME: ALARM_SOUND},
                cancellable,
                self._sound_finished,
                window,
            )
        except GLib.Error as exc:
            self._stop_sound_icon(window)
            self._log(f"Could not play alarm sound: {exc.message}")

    def _sound_finished(self, context, result, window):
        self._stop_sound_icon(window)
        try:
            context.play_full_finish(result)
        except GLib.Error as exc:
            state = self.sound_loops.get(window)
            if state is not None and not state["cancellable"].is_cancelled():
                self._log(f"Could not play alarm sound: {exc.message}")
            return
        state = self.sound_loops.get(window)
        if state is not None:
            state["replay_id"] = GLib.timeout_add_seconds(
                5, self._replay_sound, window
            )

    def _replay_sound(self, window):
        state = self.sound_loops.get(window)
        if state is not None:
            state["replay_id"] = 0
            self._play_sound_iteration(window)
        return GLib.SOURCE_REMOVE

    def _pulse_sound_icon(self, window):
        state = self.sound_loops.get(window)
        if state is None:
            return GLib.SOURCE_REMOVE
        opacity = 0.45 if window.sound_icon.get_opacity() > 0.7 else 1.0
        window.sound_icon.set_opacity(opacity)
        return GLib.SOURCE_CONTINUE

    def _stop_sound_icon(self, window):
        state = self.sound_loops.get(window)
        if state is not None and state["pulse_id"]:
            GLib.source_remove(state["pulse_id"])
            state["pulse_id"] = 0
        window.sound_icon.set_opacity(1.0)
        window.sound_icon.hide()

    def _stop_sound_loop(self, window):
        state = self.sound_loops.pop(window, None)
        if state is None:
            return
        if state["pulse_id"]:
            GLib.source_remove(state["pulse_id"])
        window.sound_icon.set_opacity(1.0)
        window.sound_icon.hide()
        state["cancellable"].cancel()
        GLib.source_remove(state["limit_id"])
        if state["replay_id"]:
            GLib.source_remove(state["replay_id"])

    def _sound_limit(self, window, uid):
        state = self.sound_loops.pop(window, None)
        if state is not None:
            if state["pulse_id"]:
                GLib.source_remove(state["pulse_id"])
            window.sound_icon.set_opacity(1.0)
            window.sound_icon.hide()
            state["cancellable"].cancel()
            if state["replay_id"]:
                GLib.source_remove(state["replay_id"])
            self._log(f"Stopped alarm sound for {uid} after 2 minutes")
        return GLib.SOURCE_REMOVE

    def _log(self, message):
        if self.verbose:
            print(f"clockenstein-notification-agent: {message}", flush=True)


def _notification_body(start_timestamp, _all_day, location, description="", now=None):
    body = _relative_start_label(start_timestamp, now)
    if location:
        body = f"{body}\n{location}"
    if description:
        body = f"{body}\n\n{description}"
    return body


def _detail_row(icon_name, text, prominent=False, dim=False, max_lines=0):
    row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
    image = Gtk.Image.new_from_icon_name(icon_name, Gtk.IconSize.BUTTON)
    image.set_valign(Gtk.Align.START)
    row.pack_start(image, False, False, 0)
    label = Gtk.Label(label=text, xalign=0)
    label.set_line_wrap(True)
    label.set_line_wrap_mode(Pango.WrapMode.WORD_CHAR)
    label.set_max_width_chars(50)
    if prominent:
        label.get_style_context().add_class("clockenstein-time")
        css = Gtk.CssProvider()
        css.load_from_data(b"""
            .clockenstein-time { font-weight: bold; font-size: 1.1em; }
            .clockenstein-started { color: @warning_color; }
        """)
        label.get_style_context().add_provider(
            css, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION
        )
    if dim:
        image.set_opacity(0.65)
        label.get_style_context().add_class("dim-label")
    if max_lines:
        label.set_lines(max_lines)
        label.set_ellipsize(Pango.EllipsizeMode.END)
    row.pack_start(label, True, True, 0)
    return row, label


def _calendar_detail_row(name, color):
    row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
    swatch = Gtk.DrawingArea()
    swatch.set_size_request(16, 16)
    rgba = Gdk.RGBA()
    if not rgba.parse(color):
        rgba.parse("#2aa198")
    swatch.connect("draw", _draw_calendar_swatch, rgba)
    row.pack_start(swatch, False, False, 0)
    label = Gtk.Label(label=name, xalign=0)
    row.pack_start(label, True, True, 0)
    return row


def _draw_calendar_swatch(widget, cr, rgba):
    allocation = widget.get_allocation()
    radius = min(allocation.width, allocation.height) / 2
    cr.arc(allocation.width / 2, allocation.height / 2, radius, 0, 2 * math.pi)
    Gdk.cairo_set_source_rgba(cr, rgba)
    cr.fill()
    return False


def _draw_calendar_accent(widget, cr, rgba):
    allocation = widget.get_allocation()
    cr.rectangle(0, 0, allocation.width, allocation.height)
    Gdk.cairo_set_source_rgba(cr, rgba)
    cr.fill()
    return False


def _relative_start_label(start_timestamp, now=None):
    now = now or datetime.datetime.now().astimezone()
    seconds = start_timestamp - now.timestamp()
    if seconds > 0:
        minutes = math.ceil(seconds / 60)
        if minutes == 1:
            return "Starts in 1 minute"
        return f"Starts in {minutes} minutes"
    if seconds > -60:
        return "Starts now"
    minutes = math.floor(-seconds / 60)
    if minutes == 1:
        return "This event started 1 minute ago"
    return f"This event started {minutes} minutes ago"


if __name__ == "__main__":
    setproctitle("clockenstein-notification-agent")
    NotificationAgent().run()
