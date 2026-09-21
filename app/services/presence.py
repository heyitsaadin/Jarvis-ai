"""Active-user tracking and push notifications."""

import threading
from datetime import datetime, timezone, timedelta
from app.config import IST

# Shared in-memory state. Defined once here; every other module imports from here.
_active_users = {}
_active_lock  = threading.Lock()

_notifications = {}
_notif_lock    = threading.Lock()


def heartbeat(username):
    with _active_lock:
        _active_users[username] = datetime.now(IST)


def get_active_users(timeout_minutes=5):
    cutoff = datetime.now(IST) - timedelta(minutes=timeout_minutes)
    with _active_lock:
        alive = []
        for uname, last in list(_active_users.items()):
            if last >= cutoff:
                delta = datetime.now(IST) - last
                secs  = int(delta.total_seconds())
                since = f"{secs}s ago" if secs < 60 else f"{secs // 60}m ago"
                alive.append({"username": uname, "since": since})
            else:
                del _active_users[uname]
    return alive


def push_notification(username, title, body):
    ts = datetime.now(IST).strftime("%H:%M")
    with _notif_lock:
        _notifications.setdefault(username, []).append({"title": title, "body": body, "ts": ts})
