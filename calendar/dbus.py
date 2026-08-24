from gi.repository import Gio, GLib

BUS_NAME = "org.x.clockenstein.Calendar.Service"
BUS_PATH = "/org/x/clockenstein/Calendar/Service"
BUS_INTERFACE = "org.x.clockenstein.Calendar.Service"


def notify_changed():
    try:
        connection = Gio.bus_get_sync(Gio.BusType.SESSION, None)
        connection.call(
            BUS_NAME,
            BUS_PATH,
            BUS_INTERFACE,
            "NotifyChanged",
            None,
            None,
            Gio.DBusCallFlags.NONE,
            -1,
            None,
            None,
        )
    except GLib.Error:
        pass
