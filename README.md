# Clockenstein Calendar

<img width="1317" height="737" alt="image" src="https://github.com/user-attachments/assets/97f35ad3-e434-49cc-9ab1-1c37b216ecc7" />

Calendar application for Linux desktops.

## Supported Calendars

- Local calendars.
- Google calendars
- CalDAV calendars (Nextcloud, Memotoo, etc)

Remote calendars are read-only when disconnected or offline.

## Architecture and synchronization

`clockenstein-calendar` is the client application.

`clockenstein-daemon` runs in the background, syncs remote calendars, schedules
event reminders, and emits them over D-Bus.

The daemon:

- writes to `.xsession-errors`.
- becomes verbose if the `gsettings` key `org.x.clockenstein.daemon verbose` is set to `true`
- is restarted on package updates (this is done in `debian/postinst`)
- handles all interactions with remote (Google, Caldav) servers except for CRUD operations and accounts setup (which are handled by the client)
- syncs remote events on startup and then on a regular basis
- communicates to clients via DBUS to tell when something has `Changed` or to accept or queue refresh requests

`clockenstein-notification-agent` runs in the backgrounds, and listens for reminder signals from the daemon. When it gets a signal, it
displays a reminder window with dismiss and snooze buttons.

Just like the daemon, it is started via XDG autostart, and it runs as a systemd user service which is respawned automatically when it dies.

`tools/dbus-calendar-client.py` simulates an applet which shows calendar events (similar to the Cinnamon clock applet)

The local cache is in `~/.local/share/clockenstein`.

### Limits, synchronization frequencies and ranges

There are no limits for local calendars.

It's important to keep the the number of requests low when it comes to the Google API because
we share one key for all users.

We sync Google every 2 hours.

We want a maximum of 2500 events per Google calendar in order to be able to sync in a single
API request.

Calendars with less than 2500 events get a sync range of 2 years. If the number of events
is larger than 2500, we reduce this to 1 year and try again, then 3 months and eventually
we refuse to sync the calendar.

CalDav is different because it's a different connection for each user.
We sync it every 15 minutes for a range of 2 years.

When we navigate outside the range, in the case of Google no events are shown, in the case of
CalDav we sync extra ranges from the remote.

## TODO

- Set up translations
- Support repeating tasks
- Implement time utilities (alarms, stopwatch, timers)
- Set up a Google app (the Clockenstein prototype uses GOA's google app, it needs its own app before release)

## Dependencies

### Runtime Dependencies

```text
gir1.2-gtk-3.0
gir1.2-gsound-1.0
gir1.2-secret-1
python3
python3-caldav
python3-gi
python3-google-auth-httplib2
python3-google-auth-oauthlib
python3-googleapi
python3-icalendar
python3-setproctitle
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
python3-setproctitle
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
