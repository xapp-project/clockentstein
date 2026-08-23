# Clockenstein Calendar

Calendar application for Linux desktops.

## Supported Calendars

- Local calendars.
- Google calendars (read-only when disconnected or offline)
- CalDAV, Nextcloud, Memotoo, etc (read-only when disconnected or offline)

## TODO

- Turn into a singleton app
- Set up translations
- Sync reminders info from caldav/google
- Implement an alarm/reminder/notification service
- Support repeating tasks
- Implement time utilities (alarms, stopwatch, timers)
- Implement DBUS interfaces for calendar applets and migrate Cinnamon
- Set up a Google app (the Clockenstein prototype uses GOA's google app, it needs its own app before release)

## Dependencies

### Runtime Dependencies

```text
gir1.2-gtk-3.0
gir1.2-secret-1
python3
python3-caldav
python3-gi
python3-google-auth-httplib2
python3-google-auth-oauthlib
python3-googleapi
python3-icalendar
python3-xapp
```

### Build Dependencies

```text
gettext
gir1.2-gtk-3.0
libglib2.0-dev-bin
meson
python3
python3-caldav
python3-gi
python3-google-auth-httplib2
python3-google-auth-oauthlib
python3-googleapi
python3-icalendar
python3-xapp
```

## Building from source

### For Debian distributions (Mint, Ubuntu, etc.)

```bash
sudo apt build-dep --mark-auto .
dpkg-buildpackage
```

This creates a `.deb` package in the parent directory. After installing it, run
`clockenstein-calendar` from the command line or open Calendar from the Office
category of the application menu.

### For other distributions

Clockenstein uses the Meson build system. Install the equivalent build and runtime
dependencies for your distribution. For example:

```bash
# Fedora: sudo dnf install meson ninja-build python3 gettext
# Arch: sudo pacman -S meson ninja python gettext
# openSUSE: sudo zypper install meson ninja python3 gettext-tools
```

### Build and install

```bash
meson setup build --prefix=/usr/local
meson compile -C build
sudo meson install -C build
```

### Uninstall

To remove a Meson installation while retaining the build directory:

```bash
sudo ninja -C build uninstall
```

## Translations

Please use Launchpad to translate this project: https://translations.launchpad.net/linuxmint/latest/.

The PO files in this project are imported from there.

## License

Code: GPLv3
