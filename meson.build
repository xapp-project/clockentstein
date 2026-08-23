project('clockenstein', version: '0.1.0', meson_version: '>= 0.59.0')

prefix = get_option('prefix')
datadir = get_option('datadir')
bindir = get_option('bindir')
clockenstein_dir = join_paths(prefix, datadir, 'clockenstein')
calendar_dir = join_paths(clockenstein_dir, 'calendar')

install_data(
  'calendar/main.py',
  'calendar/store.py',
  'calendar/event_dialog.py',
  'calendar/style.css',
  install_dir: calendar_dir,
)

custom_target('clockenstein_main_window_versioned',
  input: 'calendar/main_window.py',
  output: 'main_window.py',
  command: ['sed', 's/__PROJECT_VERSION__/@0@/g'.format(meson.project_version()), '@INPUT@'],
  capture: true,
  install: true,
  install_dir: calendar_dir,
)

install_data(
  'calendar/backends/google.py',
  'calendar/backends/caldav.py',
  'calendar/backends/google.json',
  install_dir: join_paths(calendar_dir, 'backends'),
)

install_data(
  'calendar/views/__init__.py',
  'calendar/views/colors.py',
  'calendar/views/month_view.py',
  'calendar/views/week_view.py',
  'calendar/views/day_view.py',
  install_dir: join_paths(calendar_dir, 'views'),
)

install_data(
  'calendar/widgets/mini_calendar.py',
  install_dir: join_paths(calendar_dir, 'widgets'),
)

launcher_conf = configuration_data()
launcher_conf.set('calendar_dir', calendar_dir)
configure_file(
  input: 'data/clockenstein-calendar.in',
  output: 'clockenstein-calendar',
  configuration: launcher_conf,
  install: true,
  install_dir: bindir,
  install_mode: 'rwxr-xr-x',
)

subdir('data')
subdir('po')

python3 = find_program('/usr/bin/python3')
test(
  'unit-tests',
  python3,
  args: ['-m', 'unittest', 'discover', '-s', 'tests', '-v'],
  env: ['PYTHONDONTWRITEBYTECODE=1'],
  workdir: meson.project_source_root(),
)
