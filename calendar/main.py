#!/usr/bin/python3
import os
import gi

gi.require_version("Gtk", "3.0")
from gi.repository import Gtk, Gdk, GLib
from xapp.util import l10n

_ = l10n("clockenstein")

from store import CalendarManager
from main_window import MainWindow


def main():
    GLib.set_prgname("org.x.clockenstein.Calendar")
    GLib.set_application_name(_("Calendar"))
    css_provider = Gtk.CssProvider()
    css_path = os.path.join(os.path.dirname(__file__), "style.css")
    if os.path.exists(css_path):
        css_provider.load_from_path(css_path)
        Gtk.StyleContext.add_provider_for_screen(
            Gdk.Screen.get_default(),
            css_provider,
            Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION,
        )

    store = CalendarManager()
    win = MainWindow(store)
    win.connect("destroy", Gtk.main_quit)
    win.show_all()
    Gtk.main()


if __name__ == "__main__":
    main()
