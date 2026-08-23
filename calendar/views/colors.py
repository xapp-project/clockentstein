import gi
gi.require_version("Gtk", "3.0")
from gi.repository import Gtk, Gdk


def apply_event_color(widget, event):
    rgba = Gdk.RGBA()
    if not rgba.parse(event.get("calendar_color", "#2aa198")):
        return
    widget.override_background_color(Gtk.StateFlags.NORMAL, rgba)
    luminance = 0.299 * rgba.red + 0.587 * rgba.green + 0.114 * rgba.blue
    foreground = Gdk.RGBA(0.08, 0.08, 0.08, 1) if luminance > 0.62 else Gdk.RGBA(1, 1, 1, 1)
    widget.override_color(Gtk.StateFlags.NORMAL, foreground)


def apply_tinted_event_color(widget, event, show_accent=True):
    """Apply an opaque calendar-color tint and optional left accent."""
    rgba = Gdk.RGBA()
    if not rgba.parse(event.get("calendar_color", "#2aa198")):
        return
    red = round(rgba.red * 255)
    green = round(rgba.green * 255)
    blue = round(rgba.blue * 255)
    accent = (f"border-left: 4px solid rgb({red}, {green}, {blue});" if show_accent else
              "border-left: none;")
    provider = Gtk.CssProvider()
    provider.load_from_data(f"""
        * {{
            background-color: mix(@theme_bg_color, rgb({red}, {green}, {blue}), 0.24);
            background-image: none;
            color: @theme_fg_color;
            {accent}
        }}
        *:hover {{
            background-color: mix(@theme_bg_color, rgb({red}, {green}, {blue}), 0.35);
            background-image: none;
        }}
    """.encode("utf-8"))
    widget.get_style_context().add_provider(
        provider, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION + 10
    )
    widget._clockenstein_color_provider = provider
