#!/usr/bin/python3
"""Show a dummy reminder without creating an event in the calendar store."""
import datetime
import importlib.util
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "clockenstein_notification_agent", ROOT / "agent" / "main.py"
)
AGENT_MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(AGENT_MODULE)
AGENT_MODULE.ALARM_SOUND = str(ROOT / "data" / "notification.oga")

start = datetime.datetime.now().astimezone() + datetime.timedelta(minutes=10)
dummy = (
    "test:dummy-event",
    "Dummy calendar event",
    int(start.timestamp()),
    "Clockenstein Test Lab",
    "These are some notes attached to the dummy event.",
    "Personal",
    "#3584e4",
)
AGENT_MODULE.NotificationAgent().run(test_reminder=dummy)
