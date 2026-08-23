#!/usr/bin/python3
import os
import sys
from setproctitle import setproctitle
import gi

gi.require_version("Gtk", "3.0")
from gi.repository import Gtk, Gdk, Gio, GLib
from xapp.util import l10n

_ = l10n("clockenstein")

from store import CalendarManager
from main_window import MainWindow


def _activate(application):
    windows = application.get_windows()
    if windows:
        windows[0].present()
        return

    css_provider = Gtk.CssProvider()
    css_path = os.path.join(os.path.dirname(__file__), "style.css")
    if os.path.exists(css_path):
        css_provider.load_from_path(css_path)
        Gtk.StyleContext.add_provider_for_screen(
            Gdk.Screen.get_default(),
            css_provider,
            Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION,
        )

    window = MainWindow(CalendarManager())
    application.add_window(window)
    window.show_all()


def main():
    setproctitle("clockenstein-calendar")
    GLib.set_prgname("org.x.clockenstein.Calendar")
    GLib.set_application_name(_("Calendar"))
    application = Gtk.Application(
        application_id="org.x.clockenstein.Calendar",
        flags=Gio.ApplicationFlags.FLAGS_NONE,
    )
    application.connect("activate", _activate)
    return application.run(sys.argv)


if __name__ == "__main__":
    main()
